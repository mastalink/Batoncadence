"""
OS service integration: keep the gateway running across reboots.

`mco start` survives a closed terminal but not a restart. This wires the
gateway into the platform's own service manager so it comes back on boot:

    Windows   Task Scheduler (schtasks) - runs at logon, no extra packages.
    Linux     systemd --user unit (lingering-friendly).
    macOS     launchd LaunchAgent plist.

Each backend is self-contained and reversible (install/uninstall/status).
We deliberately use the built-in manager per OS rather than a dependency
(NSSM, supervisor) so the dad-friendly install stays dependency-free.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SERVICE_NAME = "BatonCadence"
TASK_NAME = "BatonCadenceGateway"  # Windows Task Scheduler name


def _serve_argv(host: str, port: int) -> list:
    """Argv that runs the gateway in the foreground (the service supervises it)."""
    return [sys.executable, "-m", "mco.cli", "serve", "--host", host, "--port", str(port)]


# ── Windows: Task Scheduler ──────────────────────────────────────────────────

def _win_install(host: str, port: int) -> tuple:
    exe = " ".join(f'"{a}"' if " " in a else a for a in _serve_argv(host, port))
    # /RL LIMITED = normal privileges; /SC ONLOGON = start at user logon.
    cmd = ["schtasks", "/Create", "/TN", TASK_NAME, "/TR", exe,
           "/SC", "ONLOGON", "/RL", "LIMITED", "/F"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        return False, res.stderr.strip() or res.stdout.strip()
    # Start it now too, so the user doesn't have to log out first.
    subprocess.run(["schtasks", "/Run", "/TN", TASK_NAME], capture_output=True, text=True)
    return True, f"Registered scheduled task '{TASK_NAME}' (runs at logon)."


def _win_uninstall() -> tuple:
    res = subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
                         capture_output=True, text=True)
    if res.returncode != 0:
        return False, res.stderr.strip() or "Task not found."
    return True, f"Removed scheduled task '{TASK_NAME}'."


def _win_status() -> str:
    res = subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME],
                         capture_output=True, text=True)
    return "installed" if res.returncode == 0 else "not installed"


# ── Linux: systemd --user ────────────────────────────────────────────────────

def _systemd_unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / "batoncadence.service"


def _linux_install(host: str, port: int) -> tuple:
    argv = _serve_argv(host, port)
    exec_start = " ".join(argv)
    unit = f"""[Unit]
Description=BatonCadence gateway
After=network.target

[Service]
Type=simple
ExecStart={exec_start}
Restart=on-failure
RestartSec=5
Environment=HOME={Path.home()}

[Install]
WantedBy=default.target
"""
    path = _systemd_unit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(unit, encoding="utf-8")
    for cmd in (["systemctl", "--user", "daemon-reload"],
                ["systemctl", "--user", "enable", "--now", "batoncadence.service"]):
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            return False, res.stderr.strip() or f"{' '.join(cmd)} failed"
    return True, (f"Installed systemd --user unit at {path} and started it.\n"
                  "     For boot-without-login, run: sudo loginctl enable-linger $USER")


def _linux_uninstall() -> tuple:
    subprocess.run(["systemctl", "--user", "disable", "--now", "batoncadence.service"],
                   capture_output=True, text=True)
    path = _systemd_unit_path()
    if path.exists():
        path.unlink()
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True, text=True)
    return True, "Removed systemd --user unit."


def _linux_status() -> str:
    res = subprocess.run(["systemctl", "--user", "is-enabled", "batoncadence.service"],
                         capture_output=True, text=True)
    return "installed" if res.returncode == 0 else "not installed"


# ── macOS: launchd ───────────────────────────────────────────────────────────

def _launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / "com.batoncadence.gateway.plist"


def _mac_install(host: str, port: int) -> tuple:
    argv = _serve_argv(host, port)
    args_xml = "\n".join(f"      <string>{a}</string>" for a in argv)
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.batoncadence.gateway</string>
  <key>ProgramArguments</key>
  <array>
{args_xml}
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardErrorPath</key><string>{Path.home()}/.mco/gateway.log</string>
  <key>StandardOutPath</key><string>{Path.home()}/.mco/gateway.log</string>
</dict>
</plist>
"""
    path = _launchd_plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plist, encoding="utf-8")
    subprocess.run(["launchctl", "unload", str(path)], capture_output=True, text=True)
    res = subprocess.run(["launchctl", "load", str(path)], capture_output=True, text=True)
    if res.returncode != 0:
        return False, res.stderr.strip() or "launchctl load failed"
    return True, f"Installed LaunchAgent at {path} and loaded it."


def _mac_uninstall() -> tuple:
    path = _launchd_plist_path()
    if path.exists():
        subprocess.run(["launchctl", "unload", str(path)], capture_output=True, text=True)
        path.unlink()
    return True, "Removed LaunchAgent."


def _mac_status() -> str:
    return "installed" if _launchd_plist_path().exists() else "not installed"


# ── Dispatch ─────────────────────────────────────────────────────────────────

def install(host: str, port: int) -> tuple:
    if os.name == "nt":
        return _win_install(host, port)
    if sys.platform == "darwin":
        return _mac_install(host, port)
    return _linux_install(host, port)


def uninstall() -> tuple:
    if os.name == "nt":
        return _win_uninstall()
    if sys.platform == "darwin":
        return _mac_uninstall()
    return _linux_uninstall()


def status() -> str:
    if os.name == "nt":
        return _win_status()
    if sys.platform == "darwin":
        return _mac_status()
    return _linux_status()


def backend_name() -> str:
    if os.name == "nt":
        return "Windows Task Scheduler"
    if sys.platform == "darwin":
        return "macOS launchd"
    return "systemd --user"
