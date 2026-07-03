"""
OS service integration for the BatonCadence gateway.

The service managers run the same foreground command as an operator would:
``python -m mco.cli serve --host ... --port ...``. This module keeps artifact
rendering separate from install actions so tests can validate the generated
Windows Task Scheduler XML, systemd unit, launchd plist, and command argv
without touching the real host service manager.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from xml.sax.saxutils import escape

SERVICE_NAME = "BatonCadence-gateway"
SYSTEMD_UNIT_NAME = "batoncadence-gateway.service"
LAUNCHD_LABEL = "com.batoncadence.gateway"


def gateway_log_path() -> Path:
    return Path.home() / ".mco" / "logs" / "gateway.log"


def _serve_argv(host: str, port: int) -> list[str]:
    """Argv that runs the gateway in the foreground."""
    return [sys.executable, "-m", "mco.cli", "serve", "--host", host, "--port", str(port)]


def _windows_task_xml(host: str, port: int) -> str:
    argv = _serve_argv(host, port)
    command = escape(argv[0])
    arguments = escape(" ".join(shlex.quote(part) for part in argv[1:]))
    working_dir = escape(str(Path.home()))
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>BatonCadence gateway</Description>
  </RegistrationInfo>
  <Triggers>
    <BootTrigger>
      <Enabled>true</Enabled>
    </BootTrigger>
    <LogonTrigger>
      <Enabled>true</Enabled>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{command}</Command>
      <Arguments>{arguments}</Arguments>
      <WorkingDirectory>{working_dir}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _windows_task_xml_path() -> Path:
    return Path.home() / ".mco" / "service" / f"{SERVICE_NAME}.xml"


def _windows_create_cmd(xml_path: Path) -> list[str]:
    return ["schtasks", "/Create", "/TN", SERVICE_NAME, "/XML", str(xml_path), "/F"]


def _write_windows_task_xml(host: str, port: int) -> Path:
    path = _windows_task_xml_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_windows_task_xml(host, port), encoding="utf-16")
    return path


def _systemd_unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / SYSTEMD_UNIT_NAME


def _systemd_unit_text(host: str, port: int) -> str:
    exec_start = " ".join(shlex.quote(part) for part in _serve_argv(host, port))
    return f"""[Unit]
Description=BatonCadence gateway
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={exec_start}
Restart=always
RestartSec=5
WorkingDirectory=%h
Environment=HOME=%h
StandardOutput=append:%h/.mco/logs/gateway.log
StandardError=append:%h/.mco/logs/gateway.log

[Install]
WantedBy=default.target
"""


def _launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def _launchd_plist_xml(host: str, port: int) -> str:
    args_xml = "\n".join(f"      <string>{escape(part)}</string>" for part in _serve_argv(host, port))
    log_path = escape(str(gateway_log_path()))
    working_dir = escape(str(Path.home()))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{LAUNCHD_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
{args_xml}
  </array>
  <key>WorkingDirectory</key>
  <string>{working_dir}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>{log_path}</string>
  <key>StandardErrorPath</key>
  <string>{log_path}</string>
</dict>
</plist>
"""


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def _base_status(installed: bool, running: bool = False, last_exit: str = "unknown") -> dict[str, object]:
    return {"installed": installed, "running": running, "last_exit": last_exit}


def _parse_windows_status(stdout: str) -> dict[str, object]:
    data: dict[str, str] = {}
    for line in stdout.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            data[key.strip().lower()] = value.strip()
    status = data.get("status", "")
    return _base_status(
        installed=True,
        running=status.lower() == "running",
        last_exit=data.get("last run result") or data.get("last result") or "unknown",
    )


def _win_install(host: str, port: int) -> tuple[bool, str]:
    xml_path = _write_windows_task_xml(host, port)
    res = _run(_windows_create_cmd(xml_path))
    if res.returncode != 0:
        return False, res.stderr.strip() or res.stdout.strip() or "schtasks /Create failed"
    start = _run(["schtasks", "/Run", "/TN", SERVICE_NAME])
    if start.returncode != 0:
        return False, start.stderr.strip() or start.stdout.strip() or "schtasks /Run failed"
    return True, f"Registered scheduled task '{SERVICE_NAME}' with ONSTART and ONLOGON triggers."


def _win_uninstall() -> tuple[bool, str]:
    res = _run(["schtasks", "/Delete", "/TN", SERVICE_NAME, "/F"])
    if res.returncode != 0:
        return False, res.stderr.strip() or res.stdout.strip() or "Task not found."
    return True, f"Removed scheduled task '{SERVICE_NAME}'."


def _win_status() -> dict[str, object]:
    res = _run(["schtasks", "/Query", "/TN", SERVICE_NAME, "/FO", "LIST", "/V"])
    if res.returncode != 0:
        return _base_status(False)
    return _parse_windows_status(res.stdout)


def _win_restart() -> tuple[bool, str]:
    stop = _run(["schtasks", "/End", "/TN", SERVICE_NAME])
    if stop.returncode != 0 and "not currently running" not in (stop.stderr + stop.stdout).lower():
        return False, stop.stderr.strip() or stop.stdout.strip() or "schtasks /End failed"
    start = _run(["schtasks", "/Run", "/TN", SERVICE_NAME])
    if start.returncode != 0:
        return False, start.stderr.strip() or start.stdout.strip() or "schtasks /Run failed"
    return True, f"Restarted scheduled task '{SERVICE_NAME}'."


def _linux_install(host: str, port: int) -> tuple[bool, str]:
    path = _systemd_unit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    gateway_log_path().parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_systemd_unit_text(host, port), encoding="utf-8")
    for cmd in (
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", SYSTEMD_UNIT_NAME],
    ):
        res = _run(cmd)
        if res.returncode != 0:
            return False, res.stderr.strip() or res.stdout.strip() or f"{' '.join(cmd)} failed"
    return True, (f"Installed systemd --user unit at {path} and started it.\n"
                  "For boot-without-login, run: sudo loginctl enable-linger $USER")


def _linux_uninstall() -> tuple[bool, str]:
    _run(["systemctl", "--user", "disable", "--now", SYSTEMD_UNIT_NAME])
    path = _systemd_unit_path()
    if path.exists():
        path.unlink()
    _run(["systemctl", "--user", "daemon-reload"])
    return True, "Removed systemd --user unit."


def _linux_status() -> dict[str, object]:
    enabled = _run(["systemctl", "--user", "is-enabled", SYSTEMD_UNIT_NAME])
    if enabled.returncode != 0:
        return _base_status(False)
    active = _run(["systemctl", "--user", "is-active", SYSTEMD_UNIT_NAME])
    exit_code = _run(["systemctl", "--user", "show", SYSTEMD_UNIT_NAME, "-p", "ExecMainStatus", "--value"])
    return _base_status(
        installed=True,
        running=active.stdout.strip() == "active",
        last_exit=exit_code.stdout.strip() or "unknown",
    )


def _linux_restart() -> tuple[bool, str]:
    res = _run(["systemctl", "--user", "restart", SYSTEMD_UNIT_NAME])
    if res.returncode != 0:
        return False, res.stderr.strip() or res.stdout.strip() or "systemctl restart failed"
    return True, f"Restarted {SYSTEMD_UNIT_NAME}."


def _mac_install(host: str, port: int) -> tuple[bool, str]:
    path = _launchd_plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    gateway_log_path().parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_launchd_plist_xml(host, port), encoding="utf-8")
    _run(["launchctl", "unload", str(path)])
    res = _run(["launchctl", "load", str(path)])
    if res.returncode != 0:
        return False, res.stderr.strip() or res.stdout.strip() or "launchctl load failed"
    return True, f"Installed LaunchAgent at {path} and loaded it."


def _mac_uninstall() -> tuple[bool, str]:
    path = _launchd_plist_path()
    if path.exists():
        _run(["launchctl", "unload", str(path)])
        path.unlink()
    return True, "Removed LaunchAgent."


def _mac_status() -> dict[str, object]:
    path = _launchd_plist_path()
    if not path.exists():
        return _base_status(False)
    res = _run(["launchctl", "print", f"gui/{os.getuid()}/{LAUNCHD_LABEL}"])
    output = res.stdout + res.stderr
    return _base_status(
        installed=True,
        running=res.returncode == 0 and "state = running" in output.lower(),
        last_exit=_extract_launchd_last_exit(output),
    )


def _extract_launchd_last_exit(output: str) -> str:
    for line in output.splitlines():
        lower = line.strip().lower()
        if lower.startswith("last exit code"):
            _, value = line.split("=", 1)
            return value.strip()
    return "unknown"


def _mac_restart() -> tuple[bool, str]:
    path = _launchd_plist_path()
    if not path.exists():
        return False, "LaunchAgent is not installed."
    _run(["launchctl", "unload", str(path)])
    res = _run(["launchctl", "load", str(path)])
    if res.returncode != 0:
        return False, res.stderr.strip() or res.stdout.strip() or "launchctl load failed"
    return True, f"Restarted {LAUNCHD_LABEL}."


def install(host: str, port: int) -> tuple[bool, str]:
    if os.name == "nt":
        return _win_install(host, port)
    if sys.platform == "darwin":
        return _mac_install(host, port)
    return _linux_install(host, port)


def uninstall() -> tuple[bool, str]:
    if os.name == "nt":
        return _win_uninstall()
    if sys.platform == "darwin":
        return _mac_uninstall()
    return _linux_uninstall()


def status() -> dict[str, object]:
    if os.name == "nt":
        return _win_status()
    if sys.platform == "darwin":
        return _mac_status()
    return _linux_status()


def restart() -> tuple[bool, str]:
    if os.name == "nt":
        return _win_restart()
    if sys.platform == "darwin":
        return _mac_restart()
    return _linux_restart()


def backend_name() -> str:
    if os.name == "nt":
        return "Windows Task Scheduler"
    if sys.platform == "darwin":
        return "macOS launchd"
    return "systemd --user"


def tail_log(lines: int = 80, follow: bool = False, sleep_seconds: float = 1.0):
    """Yield the tail of the gateway log, optionally following new lines."""
    path = gateway_log_path()
    if not path.exists():
        return
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        buffer = handle.readlines()[-lines:]
        for line in buffer:
            yield line.rstrip("\n")
        if not follow:
            return
        while True:
            line = handle.readline()
            if line:
                yield line.rstrip("\n")
            else:
                time.sleep(sleep_seconds)
