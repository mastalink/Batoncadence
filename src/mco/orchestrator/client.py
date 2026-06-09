"""
Thin HTTP client for the MCO gateway dropbox.

Used by the MCP server so an IDE/agent (Claude, Codex, Antigravity) can work the
dropbox over its own scheduler. Identity (token/role/instance) and gateway URL
come from env by default:
    MCO_GATEWAY_URL   (default http://127.0.0.1:18789)
    MCO_AGENT_TOKEN   (bearer token from `mco register`)
    AGENT_ROLE        (this agent's role, e.g. "codex")
    AGENT_INSTANCE_ID (this agent's instance name)
"""

import os
from typing import Any, List, Optional

import httpx

DEFAULT_GATEWAY = "http://127.0.0.1:18789"


class GatewayClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        role: Optional[str] = None,
        instance_id: Optional[str] = None,
        timeout: float = 30.0,
        transport: Optional[httpx.BaseTransport] = None,
    ):
        self.base_url = (base_url or os.environ.get("MCO_GATEWAY_URL") or DEFAULT_GATEWAY).rstrip("/")
        self.token = token if token is not None else os.environ.get("MCO_AGENT_TOKEN", "")
        self.role = role if role is not None else os.environ.get("AGENT_ROLE", "")
        self.instance_id = instance_id if instance_id is not None else os.environ.get("AGENT_INSTANCE_ID", "")
        self.timeout = timeout
        self._transport = transport  # test hook (httpx.MockTransport); None in production

    def _client(self) -> httpx.Client:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        kwargs: dict = {"base_url": self.base_url, "headers": headers, "timeout": self.timeout}
        if self._transport is not None:
            kwargs["transport"] = self._transport
        return httpx.Client(**kwargs)

    def inbox(self) -> List[dict]:
        """Jobs addressed to this agent (role/instance) that are pending."""
        with self._client() as c:
            r = c.get("/api/jobs/pending", params={"role": self.role, "instance_id": self.instance_id})
            r.raise_for_status()
            return r.json()

    def lease(self, task_id: str) -> dict:
        """Atomically claim a job before working it."""
        with self._client() as c:
            r = c.post("/api/jobs/lease", json={"task_id": task_id, "agent_instance_id": self.instance_id})
            r.raise_for_status()
            return r.json()

    def complete(self, task_id: str, output: str) -> dict:
        with self._client() as c:
            r = c.put(f"/api/jobs/{task_id}", json={"status": "completed", "output_payload": {"result": output}})
            r.raise_for_status()
            return r.json()

    def fail(self, task_id: str, error: str) -> dict:
        with self._client() as c:
            r = c.put(f"/api/jobs/{task_id}", json={"status": "failed", "error_message": error})
            r.raise_for_status()
            return r.json()

    def send(self, to_role: str, title: str, instructions: str, to_instance: Optional[str] = None,
             depends_on: Optional[List[str]] = None, requires_approval: bool = False,
             max_retries: int = 0, escalate_to_role: Optional[str] = None) -> dict:
        """Drop a task/message into another agent's dropbox."""
        payload: dict[str, Any] = {
            "title": title,
            "description": instructions,
            "target_agent_role": to_role,
            "target_agent_id": to_instance,
            "input_payload": {"prompt": instructions},
            "depends_on": depends_on or [],
        }
        if requires_approval:
            payload["requires_approval"] = True
        if max_retries:
            payload["max_retries"] = max_retries
        if escalate_to_role:
            payload["escalate_to_role"] = escalate_to_role
        with self._client() as c:
            r = c.post("/api/jobs", json=payload)
            r.raise_for_status()
            return r.json()

    def approve(self, task_id: str) -> dict:
        """Approve a job paused at the human-in-the-loop gate (releases it to pending)."""
        with self._client() as c:
            r = c.post(f"/api/jobs/{task_id}/approve")
            r.raise_for_status()
            return r.json()

    def reject(self, task_id: str, reason: str = "") -> dict:
        """Reject a job paused at the human-in-the-loop gate (terminal)."""
        with self._client() as c:
            r = c.post(f"/api/jobs/{task_id}/reject", json={"reason": reason})
            r.raise_for_status()
            return r.json()

    def events(self, task_id: str) -> List[dict]:
        """Immutable audit trail for a job, oldest first."""
        with self._client() as c:
            r = c.get(f"/api/jobs/{task_id}/events")
            r.raise_for_status()
            return r.json()

    def jobs(self) -> List[dict]:
        """Most recent jobs on the board (any status)."""
        with self._client() as c:
            r = c.get("/api/jobs")
            r.raise_for_status()
            return r.json()

    def integrations(self) -> List[dict]:
        """Configured enterprise connectors with health and supported actions."""
        with self._client() as c:
            r = c.get("/api/integrations")
            r.raise_for_status()
            return r.json()

    def sync_connector(self, name: str) -> dict:
        """Ingest open platform objects (incidents/problems) as jobs."""
        with self._client() as c:
            r = c.post(f"/api/integrations/{name}/sync")
            r.raise_for_status()
            return r.json()

    def platform_action(self, name: str, action: str, params: Optional[dict] = None) -> dict:
        """Run a connector control action directly (approver roles only)."""
        with self._client() as c:
            r = c.post(f"/api/integrations/{name}/action",
                       json={"action": action, "params": params or {}})
            r.raise_for_status()
            return r.json()

    def agents(self) -> List[dict]:
        with self._client() as c:
            r = c.get("/api/agents")
            r.raise_for_status()
            return r.json()
