"""Redesign slice 2: quiet background start, one-time sign-in, tray, login entry.

The real-path test starts an actual gateway process (``cli.start_gateway`` is
not mocked); everything else here uses fakes only at true external seams
(registry, browser, tray library).
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
from types import SimpleNamespace

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mco import autostart, cli, local_login, plain, quiet, service
from mco.tray import simple


@pytest.fixture(autouse=True)
def _no_debug_leak(monkeypatch):
    # `--debug` sets MCO_DEBUG for the rest of the process; plain errors must be testable.
    monkeypatch.delenv("MCO_DEBUG", raising=False)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# Real path: start the actual gateway, sign in with the one-time link
@pytest.fixture
def real_home(monkeypatch, tmp_path):
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(tmp_path))
    monkeypatch.setenv("MCO_LOCAL_TOKEN", "test-local-token")
    for name in ("MCO_AGENT_TOKEN", "SUPABASE_URL", "SUPABASE_KEY", "MCO_DB_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(service, "gateway_log_path", lambda: tmp_path / "gateway.log")
    monkeypatch.setattr(quiet, "state_dir", lambda: tmp_path / ".mco")
    monkeypatch.setattr(quiet, "_token", lambda: "test-local-token")
    return tmp_path


def test_start_really_starts_a_gateway_and_signs_in_once(real_home, monkeypatch):
    installed, opened, said = [], [], []
    monkeypatch.setattr(autostart, "install", lambda **k: installed.append(k) or "login-entry")
    port = _free_port()
    try:
        code = quiet.run_start(
            port=port, tray=False, opener=opened.append, say=said.append)  # real cli.start_gateway
        log = (real_home / "gateway.log").read_text(errors="replace") if (real_home / "gateway.log").exists() else ""
        assert code == 0, (said, log)
        assert requests.get(f"http://127.0.0.1:{port}/healthz", timeout=3).ok

        # First run: the "You're all set" screen, login entry set once, no port or token shown.
        assert "You're all set" in "\n".join(said)
        assert str(port) not in "\n".join(said) and "test-local-token" not in "\n".join(said)
        assert installed, "first run should set start-at-sign-in"
        assert (real_home / ".mco" / "first-run-done").exists()

        # The app opened on a one-time link that carries no token.
        assert len(opened) == 1
        link = opened[0]
        assert "/local-login?code=" in link and "test-local-token" not in link

        first = requests.get(link, timeout=3)
        assert first.status_code == 200
        assert "bitcadence_conn" in first.text and "test-local-token" in first.text
        assert "/welcome" in first.text
        assert first.headers["Cache-Control"] == "no-store"
        again = requests.get(link, timeout=3)
        assert again.status_code == 410 and "test-local-token" not in again.text

        # The welcome page itself is served.
        assert "You're all set" in requests.get(f"http://127.0.0.1:{port}/welcome", timeout=3).text

        # A second start finds it running, opens the console (not the welcome page), sets nothing up again.
        said.clear(), opened.clear(), installed.clear()
        assert quiet.run_start(port=port, tray=False, opener=opened.append, say=said.append) == 0
        assert said == ["BitCadence is already running."]
        assert not installed
        redeemed = requests.get(opened[0], timeout=3)
        assert "/console" in redeemed.text and "/welcome" not in redeemed.text
    finally:
        try:
            cli.stop_gateway(port=port, force=True)
        except BaseException:  # noqa: BLE001 - typer.Exit when nothing is listening
            pass


def test_start_reports_a_port_held_by_something_else_in_plain_words(real_home, monkeypatch):
    said = []
    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen()
        port = blocker.getsockname()[1]
        code = quiet.run_start(port=port, tray=False, open_app=False, autostart=False, say=said.append)
    assert code == 1
    assert said == ["Another program is using what BitCadence needs. Run: bitcadence fix"]


def test_a_gateway_that_never_answers_is_a_plain_failure(real_home):
    said = []

    def never(**kwargs):
        raise quiet.StartFailed("log says no")

    code = quiet.run_start(port=_free_port(), tray=False, open_app=False, autostart=False,
                           start_fn=never, say=said.append)
    assert code == 1
    assert said == ["BitCadence couldn't start. Run: bitcadence fix"]


# No console window
def test_background_processes_get_no_console_window(monkeypatch):
    monkeypatch.setattr(quiet.os, "name", "nt")
    startup = SimpleNamespace(dwFlags=0, wShowWindow=1)
    monkeypatch.setattr(subprocess, "STARTUPINFO", lambda: startup, raising=False)
    monkeypatch.setattr(subprocess, "STARTF_USESHOWWINDOW", 1, raising=False)
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)
    kwargs = quiet.detached_kwargs()
    assert kwargs["creationflags"] & 0x08000000
    assert startup.wShowWindow == 0 and startup.dwFlags & 1


def test_gateway_is_spawned_hidden(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(service, "gateway_log_path", lambda: tmp_path / "g.log")
    monkeypatch.setattr(cli, "get_config", lambda: {})
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: seen.update(cmd=cmd, kw=kw) or SimpleNamespace(
        pid=1, poll=lambda: None))
    monkeypatch.setattr(requests, "get", lambda *a, **k: SimpleNamespace(ok=True))
    cli.start_gateway("127.0.0.1", 18789)
    assert seen["kw"].get("stdin") == subprocess.DEVNULL
    if os.name == "nt":
        assert seen["kw"]["creationflags"] & subprocess.CREATE_NO_WINDOW
    else:
        assert seen["kw"]["start_new_session"] is True


# One-time sign-in handoff
@pytest.fixture
def gateway_app(monkeypatch):
    from mco.orchestrator import auth

    local_login.reset()
    app = FastAPI()
    app.include_router(local_login.local_login_router)
    app.dependency_overrides[auth.require_agent] = lambda: {"instance_id": "local"}
    return app


def _client(app, host="127.0.0.1"):
    return TestClient(app, base_url="http://127.0.0.1:18789", client=(host, 50000))


def test_login_code_works_once(gateway_app):
    client = _client(gateway_app)
    path = client.post("/api/local-login", headers={"Authorization": "Bearer sekret"}).json()["path"]
    assert "sekret" not in path
    assert client.get(path).status_code == 200
    assert client.get(path).status_code == 410


def test_login_code_expires():
    code = local_login.mint("sekret", now=100.0)
    assert local_login.redeem(code, now=100.0 + local_login.CODE_TTL_SECONDS + 1) is None
    code = local_login.mint("sekret", now=100.0)
    assert local_login.redeem(code, now=100.0 + local_login.CODE_TTL_SECONDS - 1) == ("sekret", "/console")


def test_login_refuses_a_non_local_peer(gateway_app):
    remote = _client(gateway_app, host="203.0.113.9")
    assert remote.post("/api/local-login", headers={"Authorization": "Bearer sekret"}).status_code == 403
    code = local_login.mint("sekret")
    assert remote.get(f"/local-login?code={code}").status_code == 403
    # The refused request did not burn the code.
    assert _client(gateway_app).get(f"/local-login?code={code}").status_code == 200


def test_login_refuses_a_foreign_host_header(gateway_app):
    code = local_login.mint("sekret")
    rebinding = TestClient(gateway_app, base_url="http://evil.example:18789", client=("127.0.0.1", 50000))
    assert rebinding.get(f"/local-login?code={code}").status_code == 403


def test_login_page_cannot_be_broken_out_of(gateway_app):
    code = local_login.mint('x</script><script>alert(1)</script>')
    page = _client(gateway_app).get(f"/local-login?code={code}").text
    assert "</script><script>alert" not in page


def test_login_landing_is_a_fixed_list(gateway_app):
    client = _client(gateway_app)
    bad = client.post("/api/local-login?landing=https://evil.example",
                      headers={"Authorization": "Bearer sekret"})
    assert bad.status_code == 400


def test_login_url_falls_back_to_plain_console_when_gateway_cant_mint(monkeypatch):
    def refuse(*a, **k):
        raise requests.ConnectionError()
    monkeypatch.setattr(requests, "post", refuse)
    assert quiet.login_url("127.0.0.1", 18789, token="t") == "http://127.0.0.1:18789/console"


# Start at sign-in: per-user only
class FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"
    HKEY_LOCAL_MACHINE = "HKLM"
    REG_SZ = 1
    KEY_SET_VALUE = 2

    def __init__(self):
        self.values = {}

    def CreateKey(self, root, path):
        return (root, path)

    def OpenKey(self, root, path, reserved=0, access=0):
        return (root, path)

    def SetValueEx(self, key, name, reserved, kind, data):
        self.values[(key, name)] = data

    def QueryValueEx(self, key, name):
        if (key, name) not in self.values:
            raise OSError
        return self.values[(key, name)], 1

    def DeleteValue(self, key, name):
        if (key, name) not in self.values:
            raise OSError
        del self.values[(key, name)]

    def CloseKey(self, key):
        pass


def test_windows_login_entry_is_current_user_only():
    reg = FakeWinreg()
    where = autostart.install(platform="win32", winreg=reg, argv=["C:/py/pythonw.exe", "-m", "mco.cli", "start"])
    assert where.startswith("HKEY_CURRENT_USER\\")
    ((root, path), name), command = next(iter(reg.values.items()))
    assert root == "HKCU" and "HKLM" not in {k[0][0] for k in reg.values}
    assert path == r"Software\Microsoft\Windows\CurrentVersion\Run" and name == "BitCadence"
    assert command == "C:/py/pythonw.exe -m mco.cli start"
    assert autostart.is_enabled(platform="win32", winreg=reg)
    assert autostart.remove(platform="win32", winreg=reg) is True
    assert not autostart.is_enabled(platform="win32", winreg=reg)


def test_login_command_is_quiet_and_does_not_open_a_window():
    argv = autostart.login_command()
    assert argv[1:] == ["-m", "mco.cli", "start", "--no-open", "--no-autostart"]
    assert os.path.basename(argv[0]).lower() in {"pythonw.exe", "python.exe", "python", "python3", "python3.14"} \
        or os.path.basename(argv[0]).lower().startswith("python")


@pytest.mark.parametrize("platform,rel", [
    ("darwin", ("Library", "LaunchAgents", autostart.PLIST_NAME)),
    ("linux", (".config", "autostart", autostart.DESKTOP_NAME)),
])
def test_mac_and_linux_login_entries_stay_in_the_home_folder(tmp_path, platform, rel):
    where = autostart.install(platform=platform, home=tmp_path, argv=["/usr/bin/python3", "-m", "mco.cli", "start"])
    assert where == str(tmp_path.joinpath(*rel))
    assert os.path.exists(where)
    assert "mco.cli" in open(where).read()
    assert autostart.remove(platform=platform, home=tmp_path) is True
    assert not os.path.exists(where)


def test_login_entry_never_uses_a_scheduled_task_or_admin(monkeypatch):
    called = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: called.append(a))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: called.append(a))
    autostart.install(platform="win32", winreg=FakeWinreg(), argv=["pythonw", "-m", "mco.cli", "start"])
    assert called == []


def test_first_run_sets_login_entry_only_once(real_home, monkeypatch):
    installed = []
    monkeypatch.setattr(autostart, "install", lambda **k: installed.append(1) or "x")
    port = _free_port()
    for _ in range(3):
        code = quiet.run_start(port=port, tray=False, open_app=False,
                               start_fn=lambda **k: None, say=lambda t: None)
        assert code == 0
    assert len(installed) == 1


# Tray: state mapping, words, menu
def _snap(**kw):
    return plain.Snapshot(**kw)


def test_tray_state_mapping_has_a_word_for_every_colour():
    assert simple.tray_state(_snap(reachable=False)) == ("red", "Stopped")
    assert simple.tray_state(_snap(paused=True)) == ("amber", "Paused")
    failed = {"id": "j1", "title": "Weekly release", "status": "failed",
              "updated_at": "2999-01-01T00:00:00+00:00", "created_at": "2999-01-01T00:00:00+00:00"}
    assert simple.tray_state(_snap(failed=[failed])) == ("amber", "Needs attention")
    assert simple.tray_state(_snap()) == ("green", "Running")
    # Waiting approvals are not a fault: still green, shown as a count.
    assert simple.tray_state(_snap(waiting=[{"id": "a"}])) == ("green", "Running")


def test_paused_wins_over_a_problem():
    failed = {"id": "j1", "status": "failed"}
    assert simple.tray_state(_snap(paused=True, failed=[failed]))[1] == "Paused"


def test_tooltip_always_carries_the_word():
    assert simple.tooltip("Running", None) == "BitCadence: Running"
    assert simple.tooltip("Paused", 2) == "BitCadence: Paused - 2 approvals waiting"
    assert simple.tooltip("Running", 1).endswith("1 approval waiting")


def test_tray_menu_is_exactly_the_four_items_plus_a_status_line():
    items = simple.menu_items("Running")
    assert [i["label"] for i in items] == ["BitCadence: Running", "Open BitCadence", "Pause", "Fix problems", "Quit"]
    assert items[0]["enabled"] is False
    assert [i["action"] for i in items[1:]] == ["open", "pause", "fix", "quit"]
    assert [i["label"] for i in simple.menu_items("Paused")][2] == "Resume"
    assert simple.menu_items("Paused")[2]["action"] == "resume"


def test_tray_actions_run_the_same_verbs_as_the_cli(monkeypatch):
    calls = []
    monkeypatch.setattr(plain, "do_pause", lambda c, yes=False: calls.append(("pause", yes)))
    monkeypatch.setattr(plain, "do_resume", lambda c: calls.append(("resume",)))
    monkeypatch.setattr(plain, "do_fix", lambda c, yes=False: calls.append(("fix", yes)))
    opened = []
    tray = simple.SimpleTray(client_factory=lambda: object(), opener=lambda: opened.append(1))
    tray.pause(), tray.resume(), tray.fix(), tray.open_app()
    assert calls == [("pause", True), ("resume",), ("fix", True)]
    assert opened == [1]


def test_tray_refresh_reads_the_board():
    class Board:
        def jobs(self):
            return [{"id": "a", "status": "needs_approval", "title": "Publish"}]

        def agents(self):
            return []

        def settings(self):
            return {"groups": {"g": [{"key": "MCO_KILL_SWITCH", "value": "true"}]}}

    tray = simple.SimpleTray(client_factory=Board)
    assert tray.refresh() == ("amber", "Paused")
    assert tray.waiting == 1


def test_tray_when_gateway_is_down_is_red_stopped():
    class Down:
        def jobs(self):
            raise ConnectionRefusedError()

    tray = simple.SimpleTray(client_factory=Down)
    assert tray.refresh() == ("red", "Stopped")
    assert tray.waiting is None


# Slice 1 follow-ups
def test_legacy_register_failure_is_plain_and_keeps_the_cause(monkeypatch):
    from typer.testing import CliRunner
    from mco.orchestrator import routes

    class Broken:
        def table(self, name):
            raise RuntimeError("disk is full")

    monkeypatch.setattr(routes, "get_db_client", lambda: Broken())
    result = CliRunner().invoke(cli.app, ["register", "--name", "w", "--role", "codex"])
    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "Failed to register agent in database" in result.output and "disk is full" in result.output


def test_cron_errors_are_recognised_by_type_not_by_the_word_cron():
    from mco import friendly, scheduler

    with pytest.raises(scheduler.ScheduleConfigError) as raised:
        scheduler.parse_cron("not a cron")
    assert isinstance(raised.value, scheduler.CronExpressionError)
    assert friendly.translate(raised.value).kind == "bad_schedule"
    # Same words, wrong type: no longer mistaken for a schedule problem.
    assert friendly.translate(RuntimeError("cron expression in some other tool")).kind == "unknown"
    assert friendly.translate(ValueError("invalid cron")).kind == "unknown"


def _helpers_add_env(monkeypatch, tmp_path):
    from mco import waker
    from mco.config import ConfigManager
    from mco.localstore import LocalStore
    from mco.orchestrator import routes
    from mco.security import SecretStore

    db = LocalStore(tmp_path / "local.db")
    store = SecretStore(tmp_path / "secrets.enc")
    store.initialize(b"k" * 32)
    config = ConfigManager(env_path=tmp_path / ".env", store_path=store._path)
    config._store = store
    monkeypatch.setattr(cli, "get_config", lambda: config)
    monkeypatch.setattr(routes, "get_db_client", lambda: db)
    monkeypatch.setattr(waker, "AGENT_TOKEN_DIR", tmp_path / "tokens")
    return db, store, config


def _add_with_unwritable_token_file(monkeypatch):
    from typer.testing import CliRunner

    real_open = os.open

    def deny_token_file(path, *args, **kwargs):
        if str(path).endswith(".token"):
            raise PermissionError("read-only")
        return real_open(path, *args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(os, "open", deny_token_file)
        return CliRunner().invoke(cli.app, ["helpers", "add", "--name", "demo", "--role", "codex"])


def _registered(db, name):
    return db.table("agent_registry").select("*").eq("instance_id", name).execute().data


def test_helpers_add_undoes_the_registration_when_nothing_holds_the_token(monkeypatch, tmp_path):
    db, store, config = _helpers_add_env(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "set", lambda *a, **k: (_ for _ in ()).throw(OSError("vault locked")))
    result = _add_with_unwritable_token_file(monkeypatch)
    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert not _registered(db, "demo"), "a registered helper nobody holds a token for"


def test_helpers_add_restores_an_existing_helper_when_it_fails(monkeypatch, tmp_path):
    db, store, config = _helpers_add_env(monkeypatch, tmp_path)
    db.table("agent_registry").upsert({
        "instance_id": "demo", "role": "codex", "status": "offline", "auth_token_hash": "OLD"}).execute()
    monkeypatch.setattr(config, "set", lambda *a, **k: (_ for _ in ()).throw(OSError("vault locked")))
    result = _add_with_unwritable_token_file(monkeypatch)
    assert result.exit_code == 1
    assert _registered(db, "demo")[0]["auth_token_hash"] == "OLD"


def test_helpers_add_is_not_a_failure_when_the_store_has_the_token(monkeypatch, tmp_path):
    db, store, config = _helpers_add_env(monkeypatch, tmp_path)
    result = _add_with_unwritable_token_file(monkeypatch)
    stored = store.get("MCO_SECRET_AGENT_TOKEN_DEMO")
    registered = _registered(db, "demo")
    assert result.exit_code == 0, result.output
    assert stored and registered
    assert "encrypted secret store" in result.output
