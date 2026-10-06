"""Start BitCadence when the person signs in, without administrator rights.

Only per-user locations are ever written:

* Windows: ``HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Run``
* macOS:   ``~/Library/LaunchAgents``
* Linux:   ``~/.config/autostart``

Never HKLM, a machine-wide Startup folder, or a scheduled task, so there is no
"Run as administrator" step. The machine-wide lock-down service
(``mco service install``) stays a separate, optional choice behind its own
consent prompt.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "BitCadence"
PLIST_NAME = "ai.bitcadence.login.plist"
DESKTOP_NAME = "bitcadence.desktop"


def login_command() -> list[str]:
    """What runs at sign-in: start quietly, no browser, don't re-register."""
    from mco import quiet

    return [quiet.hidden_python(gui=True), "-m", "mco.cli", "start", "--no-open", "--no-autostart"]


def _quote(argv: list[str]) -> str:
    return " ".join(f'"{a}"' if (" " in a or not a) else a for a in argv)


def _platform(platform: Optional[str]) -> str:
    return platform or sys.platform


def entry_path(platform: Optional[str] = None, home: Optional[Path] = None) -> str:
    """Where the entry lives, for messages and tests."""
    plat = _platform(platform)
    home = home or Path.home()
    if plat.startswith("win"):
        return f"HKEY_CURRENT_USER\\{RUN_KEY}\\{VALUE_NAME}"
    if plat == "darwin":
        return str(home / "Library" / "LaunchAgents" / PLIST_NAME)
    return str(home / ".config" / "autostart" / DESKTOP_NAME)


def _plist(argv: list[str]) -> str:
    args = "".join(f"    <string>{escape(a)}</string>\n" for a in argv)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n<dict>\n'
        "  <key>Label</key><string>ai.bitcadence.login</string>\n"
        f"  <key>ProgramArguments</key>\n  <array>\n{args}  </array>\n"
        "  <key>RunAtLoad</key><true/>\n"
        "</dict>\n</plist>\n"
    )


def _desktop(argv: list[str]) -> str:
    return (
        "[Desktop Entry]\nType=Application\nName=BitCadence\n"
        f"Exec={_quote(argv)}\nX-GNOME-Autostart-enabled=true\nTerminal=false\n"
    )


def _winreg(winreg=None):
    if winreg is not None:
        return winreg
    import winreg as real  # Windows only

    return real


def install(*, platform: Optional[str] = None, home: Optional[Path] = None,
            argv: Optional[list[str]] = None, winreg=None) -> str:
    """Turn on start-at-sign-in for this user. Returns where it was written."""
    plat = _platform(platform)
    argv = argv or login_command()
    where = entry_path(plat, home)
    if plat.startswith("win"):
        reg = _winreg(winreg)
        key = reg.CreateKey(reg.HKEY_CURRENT_USER, RUN_KEY)
        try:
            reg.SetValueEx(key, VALUE_NAME, 0, reg.REG_SZ, _quote(argv))
        finally:
            reg.CloseKey(key)
        return where
    path = Path(where)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_plist(argv) if plat == "darwin" else _desktop(argv), encoding="utf-8")
    return where


def remove(*, platform: Optional[str] = None, home: Optional[Path] = None, winreg=None) -> bool:
    """Turn off start-at-sign-in. True if an entry was removed."""
    plat = _platform(platform)
    if plat.startswith("win"):
        reg = _winreg(winreg)
        try:
            key = reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_SET_VALUE)
        except OSError:
            return False
        try:
            reg.DeleteValue(key, VALUE_NAME)
            return True
        except OSError:
            return False
        finally:
            reg.CloseKey(key)
    path = Path(entry_path(plat, home))
    if path.exists():
        path.unlink()
        return True
    return False


def is_enabled(*, platform: Optional[str] = None, home: Optional[Path] = None, winreg=None) -> bool:
    plat = _platform(platform)
    if plat.startswith("win"):
        reg = _winreg(winreg)
        try:
            key = reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY)
        except OSError:
            return False
        try:
            reg.QueryValueEx(key, VALUE_NAME)
            return True
        except OSError:
            return False
        finally:
            reg.CloseKey(key)
    return Path(entry_path(plat, home)).exists()
