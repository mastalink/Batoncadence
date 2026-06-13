"""Service-manager integration: argv shaping, unit/plist rendering, dispatch."""

import sys
from pathlib import Path

import mco.service as service


def test_serve_argv_runs_the_gateway():
    argv = service._serve_argv("0.0.0.0", 9000)
    assert argv[0] == sys.executable
    assert argv[-5:] == ["serve", "--host", "0.0.0.0", "--port", "9000"]


def test_backend_name_is_platform_appropriate():
    name = service.backend_name()
    assert name in ("Windows Task Scheduler", "macOS launchd", "systemd --user")


def test_systemd_unit_renders_execstart_and_restart(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "_systemd_unit_path", lambda: tmp_path / "bc.service")
    calls = []
    monkeypatch.setattr(service.subprocess, "run",
                        lambda cmd, **k: calls.append(cmd) or type("R", (), {"returncode": 0, "stderr": "", "stdout": ""})())
    ok_flag, detail = service._linux_install("127.0.0.1", 18789)
    assert ok_flag
    unit = (tmp_path / "bc.service").read_text()
    assert "ExecStart=" in unit and "serve --host 127.0.0.1 --port 18789" in unit
    assert "Restart=on-failure" in unit
    assert ["systemctl", "--user", "enable", "--now", "batoncadence.service"] in calls


def test_launchd_plist_is_valid_xml(monkeypatch, tmp_path):
    import xml.dom.minidom as minidom
    monkeypatch.setattr(service, "_launchd_plist_path", lambda: tmp_path / "bc.plist")
    monkeypatch.setattr(service.subprocess, "run",
                        lambda cmd, **k: type("R", (), {"returncode": 0, "stderr": "", "stdout": ""})())
    ok_flag, _ = service._mac_install("127.0.0.1", 18789)
    assert ok_flag
    xml = (tmp_path / "bc.plist").read_text()
    minidom.parseString(xml)  # raises if malformed
    assert "com.batoncadence.gateway" in xml
    assert "<key>RunAtLoad</key>" in xml


def test_windows_install_uses_schtasks(monkeypatch):
    calls = []
    monkeypatch.setattr(service.subprocess, "run",
                        lambda cmd, **k: calls.append(cmd) or type("R", (), {"returncode": 0, "stderr": "", "stdout": ""})())
    ok_flag, detail = service._win_install("127.0.0.1", 18789)
    assert ok_flag
    create = calls[0]
    assert create[0] == "schtasks" and "/Create" in create
    assert "ONLOGON" in create
    assert any(c[:2] == ["schtasks", "/Run"] for c in calls)


def test_install_dispatch_matches_platform(monkeypatch):
    seen = {}
    monkeypatch.setattr(service, "_win_install", lambda h, p: seen.setdefault("win", True) or (True, ""))
    monkeypatch.setattr(service, "_mac_install", lambda h, p: seen.setdefault("mac", True) or (True, ""))
    monkeypatch.setattr(service, "_linux_install", lambda h, p: seen.setdefault("linux", True) or (True, ""))
    service.install("127.0.0.1", 18789)
    assert len(seen) == 1  # exactly one backend was dispatched to
