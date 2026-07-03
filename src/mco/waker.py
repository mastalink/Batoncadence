"""Event-driven worker wake-up loop for the MCO job board."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable, Optional

from mco.orchestrator.client import DEFAULT_GATEWAY, GatewayClient

logger = logging.getLogger("mco.waker")


class WakerAuthError(RuntimeError):
    """Raised when the broadcast WebSocket rejects authentication."""


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
