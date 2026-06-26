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


# ── Constant-time token comparison (no `!=` timing oracle) ───────────────────
# Local-Only HTTP auth and /metrics both compare a caller-supplied token to a
# server secret. They must use hmac.compare_digest so a network attacker can't
# recover the token byte-by-byte from response timing (security findings #2/#3).

def _http_local_app(monkeypatch, local_token):
    """Minimal app whose one route depends on the real require_agent, in
    Local-Only mode (no DB) with a given MCO_LOCAL_TOKEN."""
    from fastapi import Depends, FastAPI
    import mco.orchestrator.auth as auth_mod
    import mco.orchestrator.routes as routes
    from mco.orchestrator.auth import require_agent

    monkeypatch.setattr(routes, "get_db_client", lambda: None, raising=True)
    monkeypatch.setattr(auth_mod, "get_config",
                        lambda: {"MCO_LOCAL_TOKEN": local_token}, raising=True)

    app = FastAPI()

    @app.get("/whoami")
    def whoami(agent: dict = Depends(require_agent)):
        return agent

    return app


def test_http_local_token_rejects_wrong(monkeypatch):
    from fastapi.testclient import TestClient
    client = TestClient(_http_local_app(monkeypatch, "s3cret"))
    assert client.get("/whoami", headers={"Authorization": "Bearer wrong"}).status_code == 401
    # a right-length-wrong-value token is rejected the same way (no oracle)
    assert client.get("/whoami", headers={"Authorization": "Bearer s3creT"}).status_code == 401


def test_http_local_token_accepts_right(monkeypatch):
    from fastapi.testclient import TestClient
    client = TestClient(_http_local_app(monkeypatch, "s3cret"))
    assert client.get("/whoami", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def _metrics_app(monkeypatch, token):
    from fastapi import FastAPI
    import mco.orchestrator.metrics_routes as metrics_mod

    monkeypatch.setattr(metrics_mod, "get_config",
                        lambda: {"MCO_METRICS_TOKEN": token}, raising=True)
    # Keep it unit-level: don't hit the real board/fleet to render.
    monkeypatch.setattr(metrics_mod, "render_metrics", lambda: "# ok\n", raising=True)

    app = FastAPI()
    app.include_router(metrics_mod.metrics_router)
    return app


def test_metrics_rejects_wrong_token(monkeypatch):
    from fastapi.testclient import TestClient
    client = TestClient(_metrics_app(monkeypatch, "metpass"))
    assert client.get("/metrics", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_metrics_accepts_right_token(monkeypatch):
    from fastapi.testclient import TestClient
    client = TestClient(_metrics_app(monkeypatch, "metpass"))
    assert client.get("/metrics", headers={"Authorization": "Bearer metpass"}).status_code == 200


def test_metrics_open_without_token(monkeypatch):
    """No MCO_METRICS_TOKEN => open like /healthz (loopback bind)."""
    from fastapi.testclient import TestClient
    client = TestClient(_metrics_app(monkeypatch, ""))
    assert client.get("/metrics").status_code == 200


# ── Bind-safety guard: don't expose the gateway on a network interface ───────
# (audit findings C-01 / H-01: zero-config Local-Only auth grants admin, which
# is only dangerous when the gateway is reachable off-loopback.)

def test_bind_guard_blocks_exposed_without_auth():
    import typer
    import mco.cli as cli
    for host in ("0.0.0.0", "10.0.0.5", "::"):
        with pytest.raises(typer.Exit):
            cli._assert_safe_bind(host, {})


def test_bind_guard_allows_loopback():
    import mco.cli as cli
    for host in ("127.0.0.1", "localhost", "::1", "127.0.1.1", ""):
        cli._assert_safe_bind(host, {})  # must not raise


def test_bind_guard_allows_exposed_with_token_or_db():
    import mco.cli as cli
    cli._assert_safe_bind("0.0.0.0", {"MCO_LOCAL_TOKEN": "s3cret"})  # token set
    cli._assert_safe_bind("0.0.0.0", {"SUPABASE_URL": "https://x.supabase.co",
                                      "SUPABASE_KEY": "anon-key"})    # cloud DB
    # placeholder URL is not a real DB -> still blocked
    import typer
    with pytest.raises(typer.Exit):
        cli._assert_safe_bind("0.0.0.0", {"SUPABASE_URL": "encrypted_in_secret_store",
                                          "SUPABASE_KEY": "x"})


def test_token_compares_stay_constant_time_in_source():
    """Lock the fix: the timing-unsafe `!=` forms must never come back, and
    hmac.compare_digest must remain the comparison primitive."""
    import pathlib
    import mco
    root = pathlib.Path(mco.__file__).parent
    auth_src = (root / "orchestrator" / "auth.py").read_text(encoding="utf-8")
    metrics_src = (root / "orchestrator" / "metrics_routes.py").read_text(encoding="utf-8")

    assert "hmac.compare_digest(bearer" in auth_src
    assert "bearer != local_token" not in auth_src

    assert "hmac.compare_digest(extract_bearer" in metrics_src
    assert "extract_bearer(authorization) != token" not in metrics_src
