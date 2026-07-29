"""Event-driven worker wake-up loop for the MCO job board."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Optional

from mco.orchestrator.client import DEFAULT_GATEWAY, GatewayClient

logger = logging.getLogger("mco.waker")

# Per-instance agent tokens live here, one file per instance id.
AGENT_TOKEN_DIR = Path.home() / ".mco" / "tokens"


class WakerAuthError(RuntimeError):
    """Raised when the broadcast WebSocket rejects authentication."""


class WakerTokenError(RuntimeError):
    """Raised when no usable agent token could be resolved for this instance."""


def agent_token_path(instance_id: str) -> Path:
    """Where this instance's bearer token is stored."""
    return AGENT_TOKEN_DIR / f"{instance_id}.token"


def read_agent_token_file(instance_id: str) -> Optional[str]:
    """Read `~/.mco/tokens/<instance>.token`, or None if absent/empty/unreadable."""
    if not instance_id:
        return None
    path = agent_token_path(instance_id)
    try:
        token = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return token or None


def resolve_agent_token(
    instance_id: str,
    explicit: Optional[str] = None,
    config: Any = None,
    strict: bool = True,
) -> str:
    """Resolve the bearer token a waker should authenticate with.

    Order, most specific first:

      1. an explicit `--token`
      2. `MCO_AGENT_TOKEN` in the environment
      3. `~/.mco/tokens/<instance>.token`   <-- per-instance, the multi-agent case
      4. `MCO_AGENT_TOKEN` from the config/.env
      5. `MCO_LOCAL_TOKEN` (single-agent convenience only)

    Step 3 exists because a machine running several agents cannot express more
    than one identity through a single global `MCO_AGENT_TOKEN`. Without it every
    waker on a multi-agent host silently falls back to the *operator* token,
    fails role authentication, and exits 1 - which reads as "the fleet is down"
    with no indication that the cause is identity, not connectivity.

    `strict` refuses the MCO_LOCAL_TOKEN fallback when an instance id is set:
    the operator token cannot authenticate as a named agent, so using it is a
    guaranteed failure that is better reported here, by name, than as a generic
    rejection from the far end of a WebSocket.
    """
    explicit = (explicit or "").strip()
    if explicit:
        return explicit

    env_token = (os.environ.get("MCO_AGENT_TOKEN") or "").strip()
    if env_token:
        return env_token

    file_token = read_agent_token_file(instance_id)
    if file_token:
        logger.debug(f"using per-instance token file for '{instance_id}'")
        return file_token

    cfg_token = ""
    if config is not None:
        cfg_token = (config.get("MCO_AGENT_TOKEN") or "").strip()
    if cfg_token:
        return cfg_token

    local = ""
    if config is not None:
        local = (config.get("MCO_LOCAL_TOKEN") or "").strip()
    local = local or (os.environ.get("MCO_LOCAL_TOKEN") or "").strip()

    if local and not (strict and instance_id):
        return local

    if strict:
        raise WakerTokenError(
            f"No agent token for instance '{instance_id or '(unset)'}'.\n"
            f"  Looked for, in order:\n"
            f"    1. --token\n"
            f"    2. MCO_AGENT_TOKEN in the environment\n"
            f"    3. {agent_token_path(instance_id) if instance_id else '~/.mco/tokens/<instance>.token'}\n"
            f"    4. MCO_AGENT_TOKEN in ~/.mco/.env\n"
            + (
                "  MCO_LOCAL_TOKEN was found but is the operator token - it cannot\n"
                "  authenticate as a named agent, so it was not used.\n"
                if local else ""
            )
            + f"  Fix: mco reset-token {instance_id or '<instance>'}  then save it to\n"
            f"       {agent_token_path(instance_id) if instance_id else '~/.mco/tokens/<instance>.token'}"
        )
    return local


def websocket_url_from_gateway(gateway_url: Optional[str]) -> str:
    base = (gateway_url or DEFAULT_GATEWAY).rstrip("/")
    if base.startswith("https://"):
        return "wss://" + base[len("https://"):] + "/ws/broadcast"
    if base.startswith("http://"):
        return "ws://" + base[len("http://"):] + "/ws/broadcast"
    return base + "/ws/broadcast"


class Waker:
    """Listen to broadcast events and wake a local worker when inbox has work."""

    def __init__(
        self,
        exec_command: str,
        role: str,
        instance_id: str,
        gateway_url: Optional[str] = None,
        token: str = "",
        min_interval: float = 10.0,
        client: Optional[GatewayClient] = None,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ):
        self.exec_command = exec_command
        self.role = role or ""
        self.instance_id = instance_id or ""
        self.gateway_url = (gateway_url or DEFAULT_GATEWAY).rstrip("/")
        self.ws_url = websocket_url_from_gateway(self.gateway_url)
        self.token = token or ""
        self.min_interval = max(0.0, float(min_interval))
        self.client = client or GatewayClient(
            base_url=self.gateway_url,
            token=self.token,
            role=self.role,
            instance_id=self.instance_id,
        )
        self._sleep = sleep
        self._drain_task: Optional[asyncio.Task] = None
        self._dirty = False
        self._last_spawn_start = 0.0

    async def run_forever(self) -> None:
        """Connect to the broadcast socket and reconnect forever on failures."""
        import websockets

        backoff = 1.0
        while True:
            try:
                async with websockets.connect(self.ws_url) as ws:
                    await self._authenticate(ws)
                    logger.info("Connected to the broadcast socket")
                    backoff = 1.0
                    self.on_connected()
                    async for frame in ws:
                        await self.handle_frame(frame)
            except WakerAuthError:
                raise
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Disconnected from the broadcast socket (%s); retrying in %ss",
                               type(exc).__name__, int(backoff))
                await self._sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _authenticate(self, ws: Any) -> None:
        await ws.send(json.dumps({
            "type": "authenticate",
            "payload": {
                "instance_id": self.instance_id,
                "role": self.role,
                "token": self.token,
            },
        }))
        first = await ws.recv()
        msg = self._decode_frame(first)
        if msg.get("type") == "authenticated":
            payload = msg.get("payload") or {}
            if payload.get("success") is False:
                detail = payload.get("error") or "check MCO_AGENT_TOKEN / MCO_LOCAL_TOKEN"
                raise WakerAuthError(f"WebSocket authentication failed: {detail}")
            return
        await self.handle_message(msg)

    async def handle_frame(self, frame: Any) -> None:
        await self.handle_message(self._decode_frame(frame))

    async def handle_message(self, msg: dict) -> None:
        if self._is_matching_pending_event(msg):
            self.trigger_drain()

    def on_connected(self) -> None:
        """Run a startup/reconnect sweep through the authoritative inbox."""
        self.trigger_drain()

    def trigger_drain(self) -> None:
        """Start one inbox-confirmed drain, or mark a running drain dirty."""
        if self._drain_task is not None and not self._drain_task.done():
            self._dirty = True
            return
        self._drain_task = asyncio.create_task(self._drain_loop())

    async def wait_for_idle(self) -> None:
        task = self._drain_task
        if task is not None:
            await task

    async def _drain_loop(self) -> None:
        while True:
            self._dirty = False
            jobs = await asyncio.to_thread(self.client.inbox)
            if not jobs:
                logger.debug("Waker drain found no pending jobs")
                return
            await self._enforce_min_interval()
            code = await self._run_exec()
            if code != 0:
                logger.warning("Waker exec exited with code %s; continuing", code)
            if not self._dirty:
                return

    async def _enforce_min_interval(self) -> None:
        now = time.monotonic()
        wait_for = self.min_interval - (now - self._last_spawn_start)
        if wait_for > 0:
            await self._sleep(wait_for)
        self._last_spawn_start = time.monotonic()

    async def _run_exec(self) -> int:
        proc = await asyncio.create_subprocess_shell(self.exec_command)
        return await proc.wait()

    def _is_matching_pending_event(self, msg: dict) -> bool:
        if msg.get("type") != "event":
            return False
        payload = msg.get("payload") or {}
        if payload.get("event") != "job_pending":
            return False
        job = payload.get("job") or {}
        target_role = str(job.get("target_agent_role") or "")
        if target_role.lower() != self.role.lower():
            return False
        target_id = job.get("target_agent_id")
        return not target_id or target_id == self.instance_id

    @staticmethod
    def _decode_frame(frame: Any) -> dict:
        if isinstance(frame, dict):
            return frame
        try:
            return json.loads(frame)
        except (TypeError, ValueError):
            return {}
