"""Tests for the robustness fixes applied in the enterprise-hardening pass.

Covers:
  1. cli.py WebSocket disconnect — list.remove() ValueError guard
  2. orchestrator/routes.py — max_retries=0 should not be dropped (is not None)
  3. orchestrator/client.py — single shared httpx.Client instance (no per-call factory)
"""

import json

import httpx
import pytest

from mco.orchestrator.client import GatewayClient

BASE = "http://127.0.0.1:18789"


# ─────────────────────────────────────────────────────────────────────────────
# 1. cli.py — ConnectionManager.disconnect() robustness
# ─────────────────────────────────────────────────────────────────────────────

def test_connection_manager_disconnect_missing_does_not_raise():
    """Removing a WebSocket that is not in active_connections must be silent."""
    from mco.cli import ConnectionManager

    mgr = ConnectionManager()
    # A fake websocket object - just needs to be a distinct Python object.
    fake_ws = object()

    # Should not raise ValueError even though fake_ws was never added.
    mgr.disconnect(fake_ws)


def test_connection_manager_disconnect_removes_present_entry():
    """Normal disconnect still removes the entry when it is present."""
    from mco.cli import ConnectionManager

    mgr = ConnectionManager()
    fake_ws = object()
    mgr.active_connections.append(fake_ws)
    mgr.disconnect(fake_ws)
    assert fake_ws not in mgr.active_connections


# ─────────────────────────────────────────────────────────────────────────────
# 2. routes.py — max_retries=0 must not be silently dropped
# ─────────────────────────────────────────────────────────────────────────────

def test_routes_max_retries_zero_is_persisted(monkeypatch):
    """create_job must include max_retries=0 in the DB payload, not drop it."""
    from mco.orchestrator import routes as _routes

    persisted: list[dict] = []

    class _FakeResult:
        data = [{"id": "j99", "status": "pending", "org_id": "default"}]

    class _FakeExec:
        def execute(self):
            return _FakeResult()

    class _FakeQuery:
        def insert(self, data):
            persisted.append(data)
            return _FakeExec()

    class _FakeDB:
        backend = "local"

        def table(self, name):
            if name == "agent_jobs":
                return _FakeQuery()
            # audit / other tables — no-op
            return _FakeQuery()

        def rpc(self, *a, **kw):
            return _FakeExec()

    # Patch helpers so create_job can run synchronously in the test.
    monkeypatch.setattr(_routes, "get_db_client", lambda: _FakeDB())
    monkeypatch.setattr(_routes, "kill_switch_active", lambda: False)
    monkeypatch.setattr(_routes, "get_gated_roles", lambda: set())
    monkeypatch.setattr(_routes, "_broadcast_callback", None)

    # Patch the audit record_event to be a no-op.
    import mco.orchestrator.audit as _audit
    monkeypatch.setattr(_audit, "record_event", lambda *a, **kw: None)

    # Patch the dependency (handlers._initial_status).
    import mco.orchestrator.handlers as _handlers
    monkeypatch.setattr(_handlers, "_initial_status", lambda db, deps, req_appr: "pending")

    import asyncio

    agent = {"instance_id": "op", "role": "human", "org_id": "default"}
    payload = {
        "title": "t",
        "target_agent_role": "codex",
        "max_retries": 0,
    }

    asyncio.run(_routes.create_job(payload, agent))

    assert persisted, "insert() was never called"
    inserted = persisted[0]
    # max_retries=0 must be present — the old `if max_retries:` would drop it.
    assert "max_retries" in inserted, "max_retries=0 was silently dropped"
    assert inserted["max_retries"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 3. client.py — shared httpx.Client (single instance, reuse, context manager)
# ─────────────────────────────────────────────────────────────────────────────

class _Recorder:
    def __init__(self):
        self.requests: list = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/api/jobs/pending":
            return httpx.Response(200, json=[])
        if path == "/api/jobs" and request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={})


def _gc(rec: _Recorder) -> GatewayClient:
    return GatewayClient(
        base_url=BASE, token="tok", role="codex", instance_id="inst",
        transport=httpx.MockTransport(rec.handler),
    )


def test_client_instance_is_reused():
    """_client() must return the same httpx.Client object on repeated calls."""
    rec = _Recorder()
    gc = _gc(rec)
    c1 = gc._client()
    c2 = gc._client()
    assert c1 is c2, "A new httpx.Client was created on every call (regression)"


def test_client_close_releases_instance():
    """close() must set the internal client to None so a fresh one is created."""
    rec = _Recorder()
    gc = _gc(rec)
    c1 = gc._client()
    gc.close()
    # After close, _client() must create a fresh instance.
    c2 = gc._client()
    assert c1 is not c2


def test_client_context_manager_closes_on_exit():
    """GatewayClient used as a context manager must close the HTTP client on exit."""
    rec = _Recorder()
    gc = _gc(rec)
    with gc:
        _ = gc._client()  # force creation
        internal_before = gc._GatewayClient__client  # name-mangled attribute
    # After __exit__, the internal client should be None.
    assert gc._GatewayClient__client is None


def test_multiple_calls_reuse_one_connection():
    """inbox() then jobs() should both succeed and share the same client."""
    rec = _Recorder()
    gc = _gc(rec)

    gc.inbox()
    gc.jobs()

    # Both calls should have gone through (two recorded requests).
    assert len(rec.requests) == 2
    # And the client instance is still the same object (not recreated).
    assert gc._client() is gc._client()
