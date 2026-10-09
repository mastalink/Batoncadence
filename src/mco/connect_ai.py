"""Connect an AI: find the app, back up its settings, add BitCadence.

Spec: design/redesign-v1/02-connect-ai.html. Same code behind ``bitcadence connect``
and the console's Connect an AI page. Every write keeps the original file as a
``.bak`` first, goes through a temp file so a crash never leaves half a file,
and refuses to touch a settings file it cannot read.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

SERVER_NAME = "bitcadence"

# app key -> (label, file kind, hint shown in the picker)
APPS: Dict[str, tuple] = {
    "claude": ("Claude", "json", "Chat and desktop app"),
    "codex": ("ChatGPT / Codex", "toml", "OpenAI apps"),
    "gemini": ("Gemini", "json", "Google's assistant"),
    "antigravity": ("Antigravity", "json", "Google's coding app"),
    "cursor": ("Cursor", "json", "Code editor"),
}


class ConnectError(Exception):
    """A plain-words problem. ``kind`` is not_found, unreadable or unknown."""

    def __init__(self, message: str, kind: str = "error"):
        super().__init__(message)
        self.kind = kind


def targets() -> Dict[str, List[Path]]:
    """App -> candidate settings files, most likely first."""
    home = Path.home()
    appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    return {
        "claude": [
            appdata / "Claude" / "claude_desktop_config.json",
            home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
            home / ".config" / "Claude" / "claude_desktop_config.json",
        ],
        "codex": [home / ".codex" / "config.toml"],
        "gemini": [home / ".gemini" / "settings.json"],
        "antigravity": [home / ".gemini" / "antigravity" / "mcp_config.json"],
        "cursor": [home / ".cursor" / "mcp.json"],
    }


def label(app: str) -> str:
    return APPS[app][0] if app in APPS else app.capitalize()


def _kind(app: str) -> str:
    return APPS[app][1] if app in APPS else "json"


def server_entry() -> dict:
    return {"command": sys.executable, "args": ["-m", "mco.cli", "mcp"]}


def other_snippet() -> str:
    """For 'Another app': the entry to paste, in the usual MCP shape."""
    return json.dumps({"mcpServers": {SERVER_NAME: server_entry()}}, indent=2)


def _find(app: str, table: Dict[str, List[Path]]) -> Optional[Path]:
    if app not in table:
        raise ConnectError(f"I don't know {app!r} yet. I can connect: {', '.join(sorted(table))}.", "unknown")
    return next((p for p in table[app] if p.exists()), None)


def _located(app: str, table: Optional[Dict[str, List[Path]]]):
    table = table if table is not None else targets()
    app = (app or "").strip().lower()
    path = _find(app, table)
    if path is None:
        raise ConnectError(f"I couldn't find {label(app)} on this computer.", "not_found")
    return app, path


def _toml_block() -> str:
    entry = server_entry()
    args = ", ".join(json.dumps(a) for a in entry["args"])
    return f"[mcp_servers.{SERVER_NAME}]\ncommand = {json.dumps(entry['command'])}\nargs = [{args}]\n"


_TOML_HEADER = re.compile(r'^\s*\[\[?mcp_servers\.["\']?%s["\']?\]\]?\s*$' % SERVER_NAME)
_ANY_HEADER = re.compile(r"^\s*\[")


def _toml_has(text: str) -> bool:
    return any(_TOML_HEADER.match(line) for line in text.splitlines())


def _toml_strip(text: str) -> str:
    out, skipping = [], False
    for line in text.splitlines(keepends=True):
        if _TOML_HEADER.match(line):
            skipping = True
            continue
        if skipping and _ANY_HEADER.match(line):
            skipping = False
        if not skipping:
            out.append(line)
    return "".join(out)


def _read_json(path: Path, app: str) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (ValueError, OSError):
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("mcpServers", {}), dict):
        raise ConnectError(f"{label(app)}'s settings file isn't readable, so I left it alone.", "unreadable")
    return data


def _is_connected(app: str, path: Path) -> bool:
    try:
        if _kind(app) == "toml":
            return _toml_has(path.read_text(encoding="utf-8"))
        return SERVER_NAME in _read_json(path, app).get("mcpServers", {})
    except (ConnectError, OSError):
        return False


def backup(path: Path) -> Path:
    """Copy the original aside. The first backup is never overwritten, so the
    untouched original survives repeated connect/disconnect."""
    dest = path.with_suffix(path.suffix + ".bak")
    if dest.exists():
        dest = path.with_suffix(path.suffix + f".{time.strftime('%Y%m%d-%H%M%S')}.bak")
    dest.write_bytes(path.read_bytes())
    return dest


def _write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def status(table: Optional[Dict[str, List[Path]]] = None) -> List[dict]:
    """One row per app: found on this computer? already connected?"""
    table = table if table is not None else targets()
    rows = []
    for app in table:
        path = _find(app, table)
        rows.append({"app": app, "name": label(app), "hint": APPS.get(app, ("", "", ""))[2],
                     "found": path is not None, "connected": bool(path and _is_connected(app, path))})
    return rows


def connect(app: str, table: Optional[Dict[str, List[Path]]] = None) -> dict:
    app, path = _located(app, table)
    if _kind(app) == "toml":
        text = path.read_text(encoding="utf-8")
        if _toml_has(text):
            return {"app": app, "changed": False, "backup": None}
        saved = backup(path)
        gap = "" if not text else ("\n" if text.endswith("\n") else "\n\n")
        _write(path, text + gap + _toml_block())
    else:
        data = _read_json(path, app)
        servers = data.setdefault("mcpServers", {})
        if SERVER_NAME in servers:
            return {"app": app, "changed": False, "backup": None}
        saved = backup(path)
        servers[SERVER_NAME] = server_entry()
        _write(path, json.dumps(data, indent=2))
    return {"app": app, "changed": True, "backup": saved.name}


def disconnect(app: str, table: Optional[Dict[str, List[Path]]] = None) -> dict:
    app, path = _located(app, table)
    if _kind(app) == "toml":
        text = path.read_text(encoding="utf-8")
        if not _toml_has(text):
            return {"app": app, "changed": False, "backup": None}
        saved = backup(path)
        _write(path, _toml_strip(text))
    else:
        data = _read_json(path, app)
        if SERVER_NAME not in data.get("mcpServers", {}):
            return {"app": app, "changed": False, "backup": None}
        saved = backup(path)
        del data["mcpServers"][SERVER_NAME]
        _write(path, json.dumps(data, indent=2))
    return {"app": app, "changed": True, "backup": saved.name}


def check(app: str, table: Optional[Dict[str, List[Path]]] = None) -> dict:
    """'Send a test': the setting is in place and the program it starts exists.
    We can't talk to the app itself, so this checks our side honestly."""
    app, path = _located(app, table)
    if not _is_connected(app, path):
        return {"app": app, "ok": False, "message": f"{label(app)} isn't connected yet."}
    if not Path(server_entry()["command"]).exists():
        return {"app": app, "ok": False,
                "message": f"{label(app)} is set up, but the program it starts has moved. Connect it again."}
    return {"app": app, "ok": True,
            "message": f"{label(app)} is set up. If it was open, close and reopen it once."}
