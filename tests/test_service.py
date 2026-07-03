"""Service-manager integration: argv shaping, artifact rendering, dispatch."""

import sys
import xml.dom.minidom as minidom

import mco.service as service


class _RunResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_serve_argv_runs_the_gateway():
    argv = service._serve_argv("0.0.0.0", 9000)
    assert argv[0] == sys.executable
    assert argv[-5:] == ["serve", "--host", "0.0.0.0", "--port", "9000"]


def test_backend_name_is_platform_appropriate():
    name = service.backend_name()
    assert name in ("Windows Task Scheduler", "macOS launchd", "systemd --user")


def test_windows_task_xml_has_boot_and_logon_triggers():
    xml = service._windows_task_xml("127.0.0.1", 18789)
    minidom.parseString(xml.encode("utf-16"))
    assert "<BootTrigger>" in xml
    assert "<LogonTrigger>" in xml
    assert "<Command>" in xml and sys.executable in xml
    assert "-m mco.cli serve --host 127.0.0.1 --port 18789" in xml


def test_windows_install_uses_schtasks_xml_without_real_install(monkeypatch, tmp_path):
    calls = []
    xml_path = tmp_path / "BatonCadence-gateway.xml"
    monkeypatch.setattr(service, "_windows_task_xml_path", lambda: xml_path)

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _RunResult()

    monkeypatch.setattr(service.subprocess, "run", fake_run)

    ok_flag, detail = service._win_install("127.0.0.1", 18789)

    assert ok_flag
    assert "ONSTART and ONLOGON" in detail
    assert xml_path.exists()
    assert calls[0] == ["schtasks", "/Create", "/TN", service.SERVICE_NAME, "/XML", str(xml_path), "/F"]
    assert calls[1] == ["schtasks", "/Run", "/TN", service.SERVICE_NAME]


def test_windows_status_parses_running_and_last_exit():
    parsed = service._parse_windows_status(
        "TaskName: BatonCadence-gateway\n"
        "Status: Running\n"
        "Last Run Result: 0x0\n"
    )
    assert parsed == {"installed": True, "running": True, "last_exit": "0x0"}


def test_systemd_unit_renders_execstart_restart_and_logs():
    unit = service._systemd_unit_text("127.0.0.1", 18789)
    assert "ExecStart=" in unit
    assert "serve --host 127.0.0.1 --port 18789" in unit
    assert "Restart=always" in unit
    assert "StandardOutput=append:%h/.mco/logs/gateway.log" in unit
    assert "StandardError=append:%h/.mco/logs/gateway.log" in unit


def test_systemd_install_writes_unit_and_enables_without_real_install(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(service, "_systemd_unit_path", lambda: tmp_path / "bc.service")
    monkeypatch.setattr(service, "gateway_log_path", lambda: tmp_path / "logs" / "gateway.log")
    monkeypatch.setattr(
        service.subprocess,
        "run",
        lambda cmd, **kwargs: calls.append(cmd) or _RunResult(),
    )

    ok_flag, _ = service._linux_install("127.0.0.1", 18789)

    assert ok_flag
    assert (tmp_path / "bc.service").read_text(encoding="utf-8") == service._systemd_unit_text("127.0.0.1", 18789)
    assert ["systemctl", "--user", "enable", "--now", service.SYSTEMD_UNIT_NAME] in calls


def test_launchd_plist_is_valid_xml_and_logs_to_gateway_log():
    xml = service._launchd_plist_xml("127.0.0.1", 18789)
    minidom.parseString(xml)
    assert service.LAUNCHD_LABEL in xml
    assert "<key>RunAtLoad</key>" in xml
    assert "<key>KeepAlive</key>" in xml
    assert ".mco/logs/gateway.log" in xml.replace("\\", "/")


def test_install_dispatch_matches_platform(monkeypatch):
    seen = {}
    monkeypatch.setattr(service, "_win_install", lambda h, p: seen.setdefault("win", True) and (True, ""))
    monkeypatch.setattr(service, "_mac_install", lambda h, p: seen.setdefault("mac", True) and (True, ""))
    monkeypatch.setattr(service, "_linux_install", lambda h, p: seen.setdefault("linux", True) and (True, ""))
    service.install("127.0.0.1", 18789)
    assert len(seen) == 1  # exactly one backend was dispatched to
