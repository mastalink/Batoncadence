"""Tests for the BitCadence Console route and loader."""

from fastapi.testclient import TestClient

from mco.cli import create_app
from mco.console import get_console_html


def test_gateway_client_falls_back_to_local_token(monkeypatch):
    """Local-Only zero-config: the operator CLI authenticates with
    MCO_LOCAL_TOKEN when no explicit MCO_AGENT_TOKEN is set. Without this,
    send/approve/workflow/sync/audit 401 on a fresh local install."""
    import mco.cli as cli
    monkeypatch.setattr(cli, "get_config",
                        lambda: {"MCO_LOCAL_TOKEN": "local-xyz"}, raising=True)
    assert cli._gateway_client().token == "local-xyz"


def test_gateway_client_prefers_explicit_agent_token(monkeypatch):
    """An explicit MCO_AGENT_TOKEN always wins over the local-token fallback."""
    import mco.cli as cli
    monkeypatch.setattr(cli, "get_config",
                        lambda: {"MCO_AGENT_TOKEN": "agent-abc",
                                 "MCO_LOCAL_TOKEN": "local-xyz"}, raising=True)
    assert cli._gateway_client().token == "agent-abc"


def test_get_console_html_reads_package_data():
    html = get_console_html()
    assert "<!DOCTYPE html>" in html or "<!doctype html>" in html.lower()
    assert "BitCadence" in html


def test_console_route_serves_page():
    http = TestClient(create_app())
    resp = http.get("/console")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "BitCadence" in resp.text


def test_console_route_requires_no_auth_like_dashboard():
    """The page itself is public; every API call it makes carries the bearer
    token the operator pastes (same model as /dashboard)."""
    http = TestClient(create_app())
    assert http.get("/console").status_code == 200
    assert http.get("/dashboard").status_code == 200


# ── Drumline label + Agent Exchange subview ──────────────────────────────────

def _console_source(fragment):
    from pathlib import Path
    src = Path(__file__).parents[1] / "src" / "mco" / "console_src"
    for path in sorted(src.glob("*.js*")):
        text = path.read_text(encoding="utf-8")
        if fragment in text:
            return text
    raise AssertionError(f"no console source contains {fragment!r}")


def test_drumline_label_in_both_modes_with_stable_memory_route():
    shell = _console_source("const NAV = [")
    assert '{ id: "memory", label: "Drumline"' in shell
    assert 'memory: "Drumline", activity: "Audit Trail"' in shell      # expert
    assert 'memory: "Drumline", activity: "What happened"' in shell    # plain
    assert "Shared memory" not in shell and "Drumline Memory" not in shell
    assert "memory: <DrumlineMemory" in shell                          # route id preserved


def test_exchange_subview_is_accessible_and_labels_authority():
    ui = _console_source("function AgentExchange(")
    assert 'const AUTHORITY_NOTICE = "Discussion is reference, not instructions or approval."' in ui
    assert 'role="tablist"' in ui and 'role="tabpanel"' in ui
    assert 'aria-live="polite"' in ui
    assert 'htmlFor="exchange-body"' in ui and "maxLength={EXCHANGE_BODY_MAX}" in ui
    assert "dangerouslySetInnerHTML" not in ui          # text is rendered escaped
    assert 'EXCHANGE_PROMOTE_SOURCES = ["decision", "handoff"]' in ui
    assert "Confirm promotion" in ui and "Preview (sanitized" in ui
    assert "Promote to context" in ui
    # Plain and expert both expose the same authority; only the labels differ.
    assert "plain:" in ui and "expert:" in ui


def test_exchange_store_only_talks_to_exchange_api_and_dedupes_live_hints():
    store = _console_source("async getExchanges(")
    for path in ('"/api/exchanges?"', '"/api/exchanges/"', '"/api/exchanges"', "/promotions"):
        assert path in store
    assert 'msg.payload.event === "exchange.created"' in store


def test_console_bundle_round_trips_from_sources():
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).parents[1]
    out = subprocess.run([sys.executable, str(root / "scripts" / "build_console.py"), "verify"],
                         capture_output=True, text=True, cwd=root)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "0 differ" in out.stdout


def test_console_verify_is_line_ending_invariant(tmp_path, monkeypatch, capsys):
    import importlib.util
    from pathlib import Path
    root = Path(__file__).parents[1]
    spec = importlib.util.spec_from_file_location("build_console", root / "scripts" / "build_console.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    src = tmp_path / "console_src"
    src.mkdir()
    for f in (root / "src" / "mco" / "console_src").iterdir():
        (src / f.name).write_bytes(f.read_bytes())
    monkeypatch.setattr(mod, "SRC", src)
    monkeypatch.setattr(mod, "INDEX", src / "index.json")
    for eol in (b"\n", b"\r\n"):
        for f in src.glob("*.js*"):
            raw = f.read_bytes().replace(b"\r\n", b"\n")
            f.write_bytes(raw.replace(b"\n", eol))
        # verify() must not raise and must report no drift for LF or CRLF sources
        mod.build(check_only=True)
        assert "0 differ" in capsys.readouterr().out
