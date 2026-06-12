"""Security hardening regressions.

1. The standalone listener's shell-command executor is OPT-IN: a job carrying a
   raw `command` must NOT run unless MCO_ENABLE_SHELL_EXECUTOR is set, since any
   agent that can address a job to the worker could otherwise achieve RCE.
2. The Local-Only WebSocket honors MCO_LOCAL_TOKEN, matching the HTTP auth path,
   so a token-protected gateway bound to a public interface can't be reached by
   an unauthenticated socket.
"""

import asyncio

import pytest

import mco.orchestrator.listener as listener_mod
from mco.orchestrator.listener import AgentListener


@pytest.fixture(autouse=True)
def _clear_shell_env(monkeypatch):
    monkeypatch.delenv("MCO_ENABLE_SHELL_EXECUTOR", raising=False)
    # get_config() also reads .env / secret store; force the env path by stubbing
    monkeypatch.setattr(listener_mod, "get_config", lambda: {}, raising=True)
    # The executor registry is module-level: other test files register a
    # "codex" executor, which would short-circuit before the shell gate.
    monkeypatch.setattr(listener_mod, "_executor_registry", {}, raising=True)


def _job(cmd):
    return {"title": "t", "description": "d", "input_payload": {"command": cmd}}


def test_shell_executor_disabled_by_default(monkeypatch):
    """A job with a shell command is refused (not executed) when the gate is off."""
    sentinel = {"ran": False}

    async def _boom(*a, **k):
        sentinel["ran"] = True
        raise AssertionError("subprocess must not launch when gate is disabled")

    monkeypatch.setattr(asyncio, "create_subprocess_shell", _boom)
    listener = AgentListener.__new__(AgentListener)
    listener.role = "codex"

    out, err = asyncio.run(listener._execute_task(_job("echo pwned")))
    assert out is None
    assert err is not None and "disabled" in err.lower()
    assert sentinel["ran"] is False


def test_shell_executor_runs_when_explicitly_enabled(monkeypatch):
    monkeypatch.setenv("MCO_ENABLE_SHELL_EXECUTOR", "1")

    class _FakeProc:
        returncode = 0

        async def communicate(self):
            return (b"hello", b"")

    async def _fake_shell(cmd, **kw):
        assert cmd == "echo hello"
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_shell", _fake_shell)
    listener = AgentListener.__new__(AgentListener)
    listener.role = "codex"

    out, err = asyncio.run(listener._execute_task(_job("echo hello")))
    assert err is None
    assert out == "hello"


def test_shell_gate_helper_truthiness(monkeypatch):
    monkeypatch.setattr(listener_mod, "get_config", lambda: {}, raising=True)
    for val in ("1", "true", "On", "yes"):
        monkeypatch.setenv("MCO_ENABLE_SHELL_EXECUTOR", val)
        assert listener_mod._shell_executor_enabled() is True
    for val in ("0", "false", "", "nope"):
        monkeypatch.setenv("MCO_ENABLE_SHELL_EXECUTOR", val)
        assert listener_mod._shell_executor_enabled() is False


# ── WebSocket Local-Only token parity ────────────────────────────────────────

def _ws_app(monkeypatch, local_token):
    """Build the gateway app with no DB and a given MCO_LOCAL_TOKEN."""
    import mco.cli as cli
    import mco.orchestrator.routes as routes
    monkeypatch.setattr(routes, "get_db_client", lambda: None, raising=True)
    monkeypatch.setattr(cli, "get_config",
                        lambda: {"MCO_LOCAL_TOKEN": local_token}, raising=True)
    return cli.create_app()


def test_ws_local_only_rejects_bad_token(monkeypatch):
    from fastapi.testclient import TestClient
    app = _ws_app(monkeypatch, local_token="s3cret")
    client = TestClient(app)
    with client.websocket_connect("/ws/broadcast") as ws:
        ws.send_json({"type": "authenticate", "payload": {"token": "wrong"}})
        reply = ws.receive_json()
        assert reply["payload"]["success"] is False


def test_ws_local_only_accepts_good_token(monkeypatch):
    from fastapi.testclient import TestClient
    app = _ws_app(monkeypatch, local_token="s3cret")
    client = TestClient(app)
    with client.websocket_connect("/ws/broadcast") as ws:
        ws.send_json({"type": "authenticate", "payload": {"token": "s3cret"}})
        # Authenticated socket stays open; send a no-op and confirm no disconnect.
        ws.send_json({"type": "ping", "payload": {}})


def test_ws_local_only_no_token_allows_loopback(monkeypatch):
    """Zero-config local use (no MCO_LOCAL_TOKEN) keeps working without auth."""
    from fastapi.testclient import TestClient
    app = _ws_app(monkeypatch, local_token="")
    client = TestClient(app)
    with client.websocket_connect("/ws/broadcast") as ws:
        ws.send_json({"type": "ping", "payload": {}})
