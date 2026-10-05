"""Request-scoped timing shared with synchronous AnyIO worker threads."""

from contextvars import ContextVar
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import threading
import time

_current = ContextVar("mco_request_timing", default=None)
_logger_lock = threading.Lock()
_loggers = {}


def add_lock_wait(milliseconds):
    timing = _current.get()
    if timing is not None:
        # Mutable context is deliberately shared across dependency/handler threads.
        with timing["lock"]:
            timing["lock_wait_ms"] += milliseconds


def identify_caller(instance_id):
    timing = _current.get()
    if timing is not None:
        timing["instance_id"] = instance_id


def _slow_logger(path):
    with _logger_lock:
        key = str(path.resolve())
        if key not in _loggers:
            path.parent.mkdir(parents=True, exist_ok=True)
            logger = logging.getLogger("mco.gateway.slow." + key)
            logger.setLevel(logging.INFO)
            logger.propagate = False
            handler = RotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(handler)
            _loggers[key] = logger
        return _loggers[key]


class SlowRequestMiddleware:
    """Log requests over one second without headers, bodies or query strings."""

    def __init__(self, app, *, log_path=None, threshold_ms=1000):
        self.app = app
        self.log_path = Path(log_path) if log_path else Path.home() / ".mco" / "logs" / "gateway-slow.log"
        self.threshold_ms = threshold_ms

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        timing = {"lock_wait_ms": 0.0, "instance_id": None, "lock": threading.Lock()}
        token = _current.set(timing)
        started = time.perf_counter()
        try:
            await self.app(scope, receive, send)
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            _current.reset(token)
            if elapsed > self.threshold_ms:
                from starlette.concurrency import run_in_threadpool

                route = scope.get("route")
                record = {
                    "timestamp": time.time(), "method": scope["method"],
                    # Route templates exclude arbitrary path parameters too.
                    "path": getattr(route, "path", "<unmatched>"),
                    "instance_id": timing["instance_id"],
                    "total_ms": round(elapsed, 3),
                    "lock_wait_ms": round(timing["lock_wait_ms"], 3),
                }
                try:
                    await run_in_threadpool(lambda: _slow_logger(self.log_path).info(json.dumps(record)))
                except OSError:
                    logging.getLogger(__name__).exception("Could not write gateway slow-request log")
