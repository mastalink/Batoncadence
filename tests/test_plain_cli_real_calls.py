"""Regression coverage through real verbs/menu actions; only external seams are fake."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from mco import autostart, cli, menu, plain, quiet, scheduler, service, waker
from mco.config import ConfigManager
from mco.localstore import LocalStore
from mco.security import SecretStore

runner = CliRunner()


@pytest.fixture
def gateway_start(monkeypatch, tmp_path):
    import psutil
    import requests
    import subprocess

    launched = []
    up = {"now": False}
    monkeypatch.setattr(cli, "get_config", lambda: {})
    monkeypatch.setattr(psutil, "net_connections", lambda **kw: [])
    monkeypatch.setattr(service, "gateway_log_path", lambda: tmp_path / "gateway.log")
    def launch(cmd, **kw):
        launched.append(cmd)
        up["now"] = True
        return SimpleNamespace(pid=123, poll=lambda: None)
    monkeypatch.setattr(subprocess, "Popen", launch)
    monkeypatch.setattr(requests, "get", lambda *a, **kw: SimpleNamespace(ok=up["now"]))
    # Nothing here may touch the real home folder, login entry, tray or browser.
    monkeypatch.setattr(quiet, "state_dir", lambda: tmp_path)
    (tmp_path / "first-run-done").write_text("1")
    monkeypatch.setattr(quiet, "gateway_state", lambda *a, **k: "running" if up["now"] else "stopped")
    monkeypatch.setattr(quiet, "ensure_tray", lambda: None)
    monkeypatch.setattr(quiet, "login_url", lambda *a, **k: "http://127.0.0.1/x")
    monkeypatch.setattr(quiet.webbrowser, "open", lambda url: True)
    monkeypatch.setattr(autostart, "install", lambda **k: "nowhere")
    return launched


@pytest.mark.parametrize("action", ["menu", "fix", "start", "restart"])
def test_real_start_paths_use_concrete_host_and_port(monkeypatch, gateway_start, action):
    class Down:
        def jobs(self):
            raise ConnectionRefusedError()
    monkeypatch.setattr(cli, "_gateway_client", lambda: Down())
    if action == "menu":
        monkeypatch.setattr(plain, "interactive", lambda: True)
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.delenv("MCO_NO_MENU", raising=False)
        choices = iter([0, None])
        real_menu = menu.run_menu
        monkeypatch.setattr(menu, "run_menu", lambda client, help_text: real_menu(
            client, help_text, chooser=lambda *a: next(choices), pause=lambda: None))
        result = runner.invoke(cli.app, [])
    else:
        result = runner.invoke(cli.app, [action] + (["--yes"] if action == "fix" else []))
    assert result.exit_code == 0, result.output
    assert len(gateway_start) == 1, result.output
    assert gateway_start[0][-4:] == ["--host", "127.0.0.1", "--port", "18789"]
    assert "BitCadence is running" in result.output


@pytest.mark.parametrize("verb", ["ask", "workflow"])
def test_file_workflow_really_submits(monkeypatch, tmp_path, verb):
    sent = []
    class Gateway:
        def send(self, **kw):
            sent.append(kw)
            return {"success": True, "job": {"id": "created-job"}}
    monkeypatch.setattr(cli, "_gateway_client", Gateway)
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("name: demo\nsteps:\n  - id: build\n    role: codex\n    instructions: build it\n")
    args = ["ask", "--file", str(workflow)] if verb == "ask" else ["workflow", str(workflow)]
    result = runner.invoke(cli.app, args)
    assert result.exit_code == 0, result.output
    assert len(sent) == 1
    assert sent[0]["instructions"] == "build it"
    assert "Workflow submitted" in result.output
    assert "Dry run" not in result.output


def test_helpers_add_saves_credential_without_printing_it(monkeypatch, tmp_path):
    from mco.orchestrator import routes
    db = LocalStore(tmp_path / "local.db")
    store = SecretStore(tmp_path / "secrets.enc")
    store.initialize(b"k" * 32)
    config = ConfigManager(env_path=tmp_path / ".env", store_path=store._path)
    config._store = store
    monkeypatch.setattr(cli, "get_config", lambda: config)
    monkeypatch.setattr(routes, "get_db_client", lambda: db)
    monkeypatch.setattr(waker, "AGENT_TOKEN_DIR", tmp_path / "tokens")
    monkeypatch.setattr(cli.secrets, "token_hex", lambda n: "a" * 48)
    token = "mco_tok_" + "a" * 48
    result = runner.invoke(cli.app, ["helpers", "add", "--name", "demo", "--role", "codex"])
    assert result.exit_code == 0, result.output
    assert token not in result.output
    assert (tmp_path / "tokens" / "demo.token").read_text() == token
    assert store.get("MCO_SECRET_AGENT_TOKEN_DEMO") == token
    assert token not in (tmp_path / ".env").read_text()
    assert "Saved" in result.output and "demo.token" in result.output
    assert db.table("agent_registry").select("*").eq("instance_id", "demo").execute().data


@pytest.mark.parametrize("args", [["schedule"], ["schedule", "list"]])
def test_bad_schedule_is_friendly_on_real_command(monkeypatch, tmp_path, args):
    path = tmp_path / "schedules.yaml"
    path.write_text(scheduler.sample_config().replace('0 3 * * *', 'not a cron'))
    monkeypatch.setattr(scheduler, "SCHEDULES_CONFIG_PATH", path)
    result = runner.invoke(cli.app, args)
    assert result.exit_code == 1, result.output
    assert "I didn't understand" in result.output
    assert 'Try "every weekday at 2 AM"' in result.output
