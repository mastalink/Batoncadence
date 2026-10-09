"""BitCadence Console -- full control-plane GUI served at /console.

A single self-contained HTML file (no build step, no node_modules) shipped as
package data. It talks to the exact same REST API as the minimal /dashboard,
with a richer UI: mission-control overview, job board with audit-trail drawer,
human-in-the-loop approvals inbox, "Ask for something" (a plain-language request
drawn as a plan you approve once), and agent fleet presence. Workflow YAML files
still run through `bitcadence ask --file` and `mco workflow`.

Auth model is identical to /dashboard: the page is public, every API call
carries the bearer token the operator pastes in Settings -> Connection
(kept in browser localStorage).
"""
from pathlib import Path

_STATIC = Path(__file__).parent / "static"
_CONSOLE_PATH = _STATIC / "console.html"


def get_console_html() -> str:
    """Read the bundled console page from package data."""
    return _CONSOLE_PATH.read_text(encoding="utf-8")
