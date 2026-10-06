"""Quiet background start: no window, no token, no web address to type.

``bitcadence start`` (and first run) goes through :func:`run_start`:

1. start the gateway hidden, through the one spawn point ``cli.start_gateway``
   (this module never supervises or spawns the gateway itself);
2. on first run, set BitCadence to start at sign-in (per-user, no admin);
3. bring up the tray icon, the status light;
4. open the app already signed in, through a one-time local link
   (see :mod:`mco.local_login`).

Everything the person sees is plain words. No port, address or token is printed.
"""

from __future__ import annotations

import errno
import os
import socket
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Callable, Optional

from mco import friendly, plain

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18789


class StartFailed(RuntimeError):
    """The gateway was launched but never answered."""

    friendly_kind = "start_failed"


def state_dir() -> Path:
    return Path.home() / ".mco"


def first_run_marker() -> Path:
    return state_dir() / "first-run-done"


def tray_pidfile() -> Path:
    return state_dir() / "tray.pid"


# Hiding the window
def hidden_python(gui: bool = False) -> str:
    """The interpreter for a background process.

    The gateway keeps ``python.exe`` (it needs real standard streams for its log
    file; a hidden console comes from CREATE_NO_WINDOW). Pure GUI processes, such
    as the tray and the sign-in entry, use ``pythonw.exe``, which never opens a
    console at all. Same split as ``desktop.controller.StackSupervisor``.
    """
    if os.name != "nt":
        return sys.executable
    folder = os.path.dirname(sys.executable)
    if gui:
        from mco.service import _service_python

        return _service_python()
    return os.path.join(folder, "python.exe") if os.path.exists(os.path.join(folder, "python.exe")) else sys.executable


def detached_kwargs() -> dict:
    """Popen flags: fully detached, and no console window on Windows."""
    if os.name == "nt":
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0  # SW_HIDE
        return {
            "creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
            "startupinfo": startup,
        }
    return {"start_new_session": True}


# What is on the port
def gateway_state(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> str:
    """'running' (BitCadence answers), 'busy' (something else holds the port), or 'stopped'."""
    import requests

    try:
        if requests.get(f"http://{host}:{port}/healthz", timeout=1.5).ok:
            return "running"
    except Exception:  # noqa: BLE001
        pass
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return "busy" if probe.connect_ex((host, port)) == 0 else "stopped"


# Signed-in hand-off
def _token() -> str:
    from mco.config import get_config

    config = get_config()
    return (config.get("MCO_AGENT_TOKEN") or config.get("MCO_LOCAL_TOKEN") or "").strip()


def login_url(host: str, port: int, landing: str = "console", token: Optional[str] = None) -> str:
    """A one-time link that opens the app already signed in.

    Falls back to the plain console address if the gateway can't mint one, so
    the worst case is the old behaviour, never a dead end.
    """
    import requests

    base = f"http://{host}:{port}"
    token = _token() if token is None else token
    try:
        resp = requests.post(
            f"{base}/api/local-login", params={"landing": landing},
            headers={"Authorization": f"Bearer {token}"} if token else {}, timeout=5)
        if resp.ok:
            return base + resp.json()["path"]
    except Exception:  # noqa: BLE001
        pass
    return f"{base}/{'welcome' if landing == 'welcome' else 'console'}"


# The tray icon
def tray_running() -> bool:
    try:
        import psutil

        pid = int(tray_pidfile().read_text(encoding="utf-8").strip())
        return psutil.pid_exists(pid) and "mco" in " ".join(psutil.Process(pid).cmdline()).lower()
    except Exception:  # noqa: BLE001
        return False


def ensure_tray() -> Optional[str]:
    """Start the tray icon unless it is already there.

    Returns a plain note when it can't run (no display, extra not installed),
    else None. Never raises: no icon must not stop BitCadence from starting.
    """
    try:
        from mco.tray.app import preflight

        problem = preflight()
        if problem:
            return "The status icon isn't available here, but BitCadence is running."
        if tray_running():
            return None
        subprocess.Popen(
            [hidden_python(gui=True), "-m", "mco.cli", "tray"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            **detached_kwargs())
        return None
    except Exception:  # noqa: BLE001
        return "The status icon couldn't start, but BitCadence is running."


# The verb
def run_start(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    *,
    open_app: bool = True,
    autostart: bool = True,
    tray: bool = True,
    opener: Optional[Callable[[str], object]] = None,
    start_fn: Optional[Callable[..., object]] = None,
    say: Callable[[str], None] = plain.say,
) -> int:
    """Start BitCadence quietly and (optionally) open it signed in. Returns an exit code."""
    from mco import autostart as autostart_mod
    from mco import local_login

    first_run = not first_run_marker().exists()
    try:
        state = gateway_state(host, port)
        if state == "busy":
            raise OSError(errno.EADDRINUSE, "Address already in use")
        if state == "stopped":
            if start_fn is None:
                from mco import cli

                start_fn = cli.start_gateway
            start_fn(host=host, port=port)

        if autostart and first_run:
            try:
                autostart_mod.install()
            except Exception:  # noqa: BLE001 - a missing login entry is not a failed start
                say("I couldn't set BitCadence to start when you sign in. You can still start it any time.")
        note = ensure_tray() if tray else None

        if open_app:
            url = login_url(host, port, landing="welcome" if first_run else "console")
            (opener or webbrowser.open)(url)

        if first_run:
            say(local_login.welcome_text())
            _mark_first_run_done()
        elif state == "running":
            say("BitCadence is already running.")
        else:
            say("BitCadence is running. Look for the icon near your clock.")
        if note:
            say(note)
        return 0
    except Exception as exc:  # noqa: BLE001 - translated for the person
        say(friendly.translate(exc).render())
        if friendly.debug_enabled():
            import traceback

            traceback.print_exception(type(exc), exc, exc.__traceback__)
        return 1


def _mark_first_run_done() -> None:
    try:
        marker = first_run_marker()
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("1", encoding="utf-8")
    except OSError:
        pass
