"""Event-loop stall detector: the gateway notices its own freeze.

On 2026-10-04 the gateway froze twice. The process stayed alive and kept its
port, but it answered nothing and connections piled up in CLOSE_WAIT. Something
had blocked the asyncio event loop, and nothing inside the process could say
what, because everything that could have said it ran on that loop.

This runs on a plain thread, outside the loop. The loop ticks a heartbeat
every second. If the heartbeat goes quiet:

* after ``MCO_LOOP_STALL_DUMP_SECONDS`` (default 60) it writes every thread's
  stack to ``~/.mco/logs/gateway-stall-<time>.txt``, once per stall. That file
  names the call that blocked the loop, so the freeze can be fixed instead of
  only restarted.
* after ``MCO_LOOP_STALL_EXIT_SECONDS`` (default 300; 0 turns it off) it exits
  the process with code 70. A frozen gateway that still holds its port helps
  nobody. Exiting hands it to the supervisor, which restarts it (the Windows
  task has restart-on-failure).

A loop that recovers by itself before the exit deadline is left alone. The
dump stays as evidence.
"""
from __future__ import annotations

import asyncio
import faulthandler
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

STALL_EXIT_CODE = 70


def _env_seconds(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


class LoopWatchdog:
    def __init__(
        self,
        *,
        dump_after: float,
        exit_after: float,
        dump_dir: Path,
        check_every: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        exit_fn: Callable[[int], None] = os._exit,
    ) -> None:
        self.dump_after = dump_after
        self.exit_after = exit_after
        self.dump_dir = dump_dir
        self.check_every = check_every
        self._clock = clock
        self._exit = exit_fn
        self.last_beat = clock()
        self._dumped_this_stall = False
        self._exited_this_stall = False
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.dumps: list[Path] = []

    def beat(self) -> None:
        self.last_beat = self._clock()
        self._dumped_this_stall = False
        self._exited_this_stall = False

    def check(self) -> None:
        """One inspection; the thread calls this every ``check_every`` s."""
        stalled_for = self._clock() - self.last_beat
        if stalled_for >= self.dump_after and not self._dumped_this_stall:
            self._dumped_this_stall = True
            path = self._dump(stalled_for)
            logger.error("Event loop stalled for %.0fs; thread stacks written to %s", stalled_for, path)
        if (
            self.exit_after > 0
            and stalled_for >= self.exit_after
            and not self._exited_this_stall
        ):
            self._exited_this_stall = True
            logger.critical("Event loop stalled for %.0fs; exiting so the supervisor restarts the gateway",
                            stalled_for)
            self._exit(STALL_EXIT_CODE)

    def _dump(self, stalled_for: float) -> Optional[Path]:
        try:
            self.dump_dir.mkdir(parents=True, exist_ok=True)
            path = self.dump_dir / f"gateway-stall-{datetime.now():%Y%m%d-%H%M%S}.txt"
            with path.open("w", encoding="utf-8") as fh:
                fh.write(f"event loop silent for {stalled_for:.1f}s; all thread stacks follow\n\n")
                fh.flush()
                faulthandler.dump_traceback(file=fh, all_threads=True)
            self.dumps.append(path)
            return path
        except OSError:  # a full disk is one way we got here; never die on the evidence
            logger.exception("Could not write the stall dump")
            return None

    def _run(self) -> None:
        while not self._stop.wait(self.check_every):
            self.check()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="loop-watchdog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()


async def heartbeat(watchdog: LoopWatchdog, every: float = 1.0) -> None:
    while True:
        watchdog.beat()
        await asyncio.sleep(every)


def from_env() -> Optional[LoopWatchdog]:
    dump_after = _env_seconds("MCO_LOOP_STALL_DUMP_SECONDS", 60)
    if dump_after <= 0:
        return None
    exit_after = _env_seconds("MCO_LOOP_STALL_EXIT_SECONDS", 300)
    dump_dir = Path(os.environ.get("MCO_LOOP_STALL_DIR") or Path.home() / ".mco" / "logs")
    return LoopWatchdog(dump_after=dump_after, exit_after=exit_after, dump_dir=dump_dir)
