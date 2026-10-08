"""The plain-verb CLI front door: menu, verbs, friendly errors, aliases.

Everything runs against a fake gateway; nothing here touches a real board.
"""

from __future__ import annotations

import errno
import json

import httpx
import pytest
from typer.testing import CliRunner

import mco.cli as cli
from mco import friendly, menu, plain, quiet

runner = CliRunner()

WAITING_JOBS = [
    {"id": "aaaa1111", "title": "Publish release notes", "status": "needs_approval", "target_agent_role": "codex"},
    {"id": "bbbb2222", "title": "Send the weekly note", "status": "needs_approval", "target_agent_role": "claude"},
]
RUNNING_JOB = {"id": "cccc3333", "title": "Tidy the docs", "status": "in_progress", "target_agent_role": "claude"}
FAILED_JOB = {"id": "dddd4444", "title": "Nightly check", "status": "failed", "target_agent_role": "codex"}


class FakeGateway:
    """GatewayClient-shaped stand-in that records every write."""

    def __init__(self, jobs=None, agents=None, paused=False, down=None):
        self.job_list = list(jobs if jobs is not None else WAITING_JOBS + [RUNNING_JOB])
        self.agent_list = agents if agents is not None else [
            {"instance_id": "codex-1", "role": "codex", "effective_status": "online", "state": "standby"},
            {"instance_id": "claude-1", "role": "claude", "effective_status": "online", "state": "working"},
        ]
        self.paused = paused
        self.down = down
        self.calls = []

    def _guard(self):
        if self.down:
            raise self.down

    def jobs(self, **_):
        self._guard()
        return self.job_list

    def agents(self):
        self._guard()
        return self.agent_list

    def settings(self):
        self._guard()
        return {"groups": {"safety": [{"key": "MCO_KILL_SWITCH", "value": "true" if self.paused else ""}]}}

    def settings_put(self, values):
        self.calls.append(("settings_put", values))
        return {"success": True}

    def approve(self, job_id):
        self.calls.append(("approve", job_id))
        return {"job": {"id": job_id, "status": "pending"}}

    def reject(self, job_id, reason=""):
        self.calls.append(("reject", job_id, reason))
        return {"job": {"id": job_id, "status": "rejected"}}

    def retry(self, job_id):
        self.calls.append(("retry", job_id))
        return {"job": {"id": job_id, "status": "pending"}}

    def send(self, **kwargs):
        self._guard()
        self.calls.append(("send", kwargs))
        return {"success": True, "job": {"id": "newjob", "status": "needs_approval"}}

    def remember(self, **kwargs):
        self.calls.append(("remember", kwargs))
        return {"entry": {"id": "m1"}}


@pytest.fixture
def gateway(monkeypatch):
    gw = FakeGateway()
    monkeypatch.setattr(cli, "_gateway_client", lambda: gw)
    return gw


def refused():
    return httpx.ConnectError("[WinError 10061] connection refused")


# ── menu ─────────────────────────────────────────────────────────────────────
def test_menu_renders_live_counts():
    gw = FakeGateway(jobs=WAITING_JOBS + [FAILED_JOB])
    labels = [i.label for i in menu.build_items(plain.take_snapshot(gw))]
    assert "Approvals (2 waiting)" in labels
    assert "Fix problems (1)" in labels
    for plain_item in ("Status", "Ask for something", "Helpers", "Schedules", "Connect an AI",
                       "Pause everything", "Settings", "Help", "Quit"):
        assert plain_item in labels


def test_menu_offers_resume_when_paused():
    labels = [i.label for i in menu.build_items(plain.take_snapshot(FakeGateway(paused=True)))]
    assert "Resume everything" in labels and "Pause everything" not in labels


def test_menu_without_gateway_offers_start_and_no_counts():
    snap = plain.take_snapshot(FakeGateway(down=refused()))
    labels = [i.label for i in menu.build_items(snap)]
    assert labels[0] == "Start BitCadence"
    assert "Approvals" in labels and not any("waiting" in label for label in labels)


def test_every_menu_item_maps_to_a_verb(monkeypatch):
    gw = FakeGateway(paused=False)
    hit = []
    for name in ("do_status", "do_ask", "do_approve", "do_fix", "do_helpers",
                 "do_schedules", "do_connect", "do_pause", "do_resume", "do_settings"):
        monkeypatch.setattr(plain, name, lambda *a, _n=name, **k: hit.append(_n))
    monkeypatch.setattr(quiet, "run_start", lambda *a, **k: hit.append("start"))
    monkeypatch.setattr(plain, "say", lambda text="": hit.append(("say", text)))
    verbs = menu._verbs(gw, lambda: "HELP TEXT")
    expected_keys = {i.key for i in menu.build_items(plain.take_snapshot(gw))} - {"quit"}
    expected_keys |= {"resume", "start"}
    assert expected_keys <= set(verbs)
    for key in sorted(expected_keys):
        verbs[key]()
    assert {"do_status", "do_ask", "do_approve", "do_fix", "do_helpers", "do_schedules",
            "do_connect", "do_pause", "do_resume", "do_settings", "start"} <= set(
        h for h in hit if isinstance(h, str))
    assert ("say", "HELP TEXT") in hit


def test_menu_loop_runs_picked_item_then_quits(monkeypatch):
    gw = FakeGateway()
    picked = []
    monkeypatch.setattr(plain, "do_approve", lambda client, *a, **k: picked.append("approve") or 0)
    seen_titles = []

    def chooser(title, labels):
        seen_titles.append(labels)
        return labels.index("Approvals (2 waiting)") if not picked else labels.index("Quit")

    code = menu.run_menu(gw, lambda: "", chooser=chooser, pause=lambda: None)
    assert code == 0 and picked == ["approve"]
    assert len(seen_titles) == 2  # menu came back (with fresh counts) after the item


def test_escape_at_menu_quits():
    assert menu.run_menu(FakeGateway(), lambda: "", chooser=lambda t, labels: None, pause=lambda: None) == 0


def test_a_failing_item_does_not_close_the_menu(monkeypatch, capsys):
    monkeypatch.setattr(plain, "do_status", lambda *a, **k: (_ for _ in ()).throw(refused()))
    answers = iter([0, None])
    menu.run_menu(FakeGateway(), lambda: "", chooser=lambda t, labels: next(answers), pause=lambda: None)
    assert "BitCadence isn't running. Start it with: bitcadence start" in capsys.readouterr().out


def test_numbered_fallback_accepts_plain_numbers(monkeypatch):
    answers = iter(["zzz", "9", "2"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert menu.numbered_choose("t", ["a", "b", "c"]) == 1
    monkeypatch.setattr("builtins.input", lambda prompt="": "q")
    assert menu.numbered_choose("t", ["a"]) is None


# ── non-TTY never blocks ─────────────────────────────────────────────────────
def test_bare_invocation_without_a_terminal_prints_help_not_menu(monkeypatch):
    monkeypatch.setattr(menu, "run_menu", lambda *a, **k: pytest.fail("menu must not open without a TTY"))
    result = runner.invoke(cli.app, [])
    assert result.exit_code == 2  # unchanged from the old bare-invocation exit code
    assert "Usage:" in result.output and "status" in result.output


def test_no_menu_flag_prints_help_even_on_a_terminal(monkeypatch):
    monkeypatch.setattr(plain, "interactive", lambda: True)
    monkeypatch.setattr(menu, "run_menu", lambda *a, **k: pytest.fail("--no-menu must not open the menu"))
    result = runner.invoke(cli.app, ["--no-menu"])
    assert result.exit_code == 0 and "Usage:" in result.output


def test_bare_invocation_on_a_terminal_opens_the_menu(monkeypatch, gateway):
    monkeypatch.setattr(plain, "interactive", lambda: True)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("MCO_NO_MENU", raising=False)
    opened = []
    monkeypatch.setattr(menu, "run_menu", lambda client, help_text, **k: opened.append(client) or 0)
    assert runner.invoke(cli.app, []).exit_code == 0
    assert opened == [gateway]


@pytest.mark.parametrize("env", ["CI", "MCO_NO_MENU"])
def test_ci_and_env_opt_out_never_show_the_menu(monkeypatch, env):
    monkeypatch.setattr(plain, "interactive", lambda: True)
    monkeypatch.setenv(env, "1")
    assert menu.should_show_menu([]) is False


def test_menu_not_shown_when_there_are_arguments(monkeypatch):
    monkeypatch.setattr(plain, "interactive", lambda: True)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("MCO_NO_MENU", raising=False)
    assert menu.should_show_menu(["status"]) is False


def test_prompts_never_block_a_script(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("must not prompt without a terminal"))
    assert plain.confirm("Sure?") is False
    assert plain.confirm("Sure?", yes=True) is True
    assert plain.ask_text("Why?") == ""


# ── friendly errors: one test per row of the CLI.md table ────────────────────
def test_error_not_running():
    for exc in (ConnectionRefusedError(111, "refused"), refused()):
        assert friendly.translate(exc).render() == "BitCadence isn't running. Start it with: bitcadence start"


def _http_error(status, text=""):
    request = httpx.Request("POST", "http://x/api/jobs/1/approve")
    response = httpx.Response(status, text=text, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


def test_error_missing_approver_rights():
    err = friendly.translate(_http_error(403, "missing scope jobs:approve"))
    assert err.render().startswith("You can't approve yet because your account isn't an approver.")
    assert "bitcadence fix" in err.render()
    assert "403" not in err.render() and "scope" not in err.render()


def test_error_nobody_to_do_the_job():
    assert friendly.no_helper_free().render().startswith("Approved, but no helper is free.")


def test_error_locked_log():
    assert "another copy has the file open" in friendly.locked_log("Fixer").render()
    assert friendly.locked_log("Fixer").render().startswith("Fixer can't save its notes")
    locked = OSError(13, "locked")
    locked.winerror = 32
    assert friendly.translate(locked).kind == "locked_log"


def test_error_bad_schedule():
    assert friendly.bad_schedule("every second tuesday").render() == (
        'I didn\'t understand "every second tuesday". Try "every weekday at 2 AM".')
    from mco import scheduler
    assert friendly.translate(scheduler.CronExpressionError("minute: nope")).kind == "bad_schedule"
    # Other schedule-file problems keep their own message (the cause is the useful part).
    assert friendly.translate(scheduler.ScheduleConfigError("loop needs max_iterations")).kind == "unknown"
    # The old guess from the words "invalid cron" is gone: only the error type counts.
    assert friendly.translate(ValueError("invalid cron expression")).kind == "unknown"


def test_error_port_in_use():
    exc = OSError(errno.EADDRINUSE, "Address already in use")
    err = friendly.translate(exc)
    assert err.render() == "Another program is using what BitCadence needs. Run: bitcadence fix"
    assert friendly.translate(OSError(10048, "x")).kind == "port_in_use"


def test_error_app_not_found_when_connecting():
    assert friendly.app_not_found("gemini").render() == (
        "I couldn't find Gemini on this computer. Install it, then run: bitcadence connect gemini")
    missing = FileNotFoundError(2, "No such file", "claude_desktop_config.json")
    assert friendly.translate(missing).render().startswith("I couldn't find Claude on this computer.")


def test_unknown_errors_keep_their_words_and_hide_traces():
    err = friendly.translate(RuntimeError("something odd"))
    assert err.render().startswith("something odd.") and "Traceback" not in err.render()


def test_plain_error_on_a_real_command_and_debug_flag(monkeypatch, capsys):
    gw = FakeGateway(down=refused())
    monkeypatch.setattr(cli, "_gateway_client", lambda: gw)
    result = runner.invoke(cli.app, ["send", "claude", "-t", "x"])
    assert result.exit_code == 1
    assert "BitCadence isn't running. Start it with: bitcadence start" in result.output
    assert "ConnectError" not in result.output


def test_debug_flag_adds_the_trace(monkeypatch):
    monkeypatch.setattr(cli, "_gateway_client", lambda: FakeGateway(down=refused()))
    monkeypatch.delenv("MCO_DEBUG", raising=False)
    result = runner.invoke(cli.app, ["--debug", "send", "claude", "-t", "x"])
    assert "BitCadence isn't running." in result.output
    assert "ConnectError" in result.output  # trace only under --debug
    monkeypatch.delenv("MCO_DEBUG", raising=False)


# ── verbs ────────────────────────────────────────────────────────────────────
def test_status_json_is_a_stable_machine_summary(gateway):
    result = runner.invoke(cli.app, ["status", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output[result.output.index("{"):])
    assert [j["title"] for j in data["needs_you"]] == ["Publish release notes", "Send the weekly note"]
    assert data["running"][0]["title"] == "Tidy the docs"


def test_status_plain_summary(gateway):
    out = runner.invoke(cli.app, ["status"]).output
    assert "Needs you (2)" in out and "1. Publish release notes?" in out
    assert "Running (1)" in out and "Tidy the docs" in out
    assert "bitcadence approve" in out
    for secret in ("127.0.0.1", "18789", "token", "Token"):
        assert secret not in out


def test_status_when_not_running_is_plain(monkeypatch):
    monkeypatch.setattr(cli, "_gateway_client", lambda: FakeGateway(down=refused()))
    result = runner.invoke(cli.app, ["status"])
    assert result.exit_code == 0
    assert "BitCadence isn't running. Start it with: bitcadence start" in result.output


def test_status_details_keeps_the_old_diagnostics(monkeypatch):
    called = []
    monkeypatch.setattr(cli, "_status_details", lambda show_all=False: called.append(show_all))
    assert runner.invoke(cli.app, ["status", "--details"]).exit_code == 0
    assert runner.invoke(cli.app, ["status", "--all"]).exit_code == 0
    assert called == [False, True]


def test_approve_by_name_number_or_id(gateway):
    runner.invoke(cli.app, ["approve", "Publish"])
    runner.invoke(cli.app, ["approve", "2"])
    runner.invoke(cli.app, ["approve", "not-in-the-list-id"])
    assert [c for c in gateway.calls if c[0] == "approve"] == [
        ("approve", "aaaa1111"), ("approve", "bbbb2222"), ("approve", "not-in-the-list-id")]


def test_approve_with_nothing_waiting(monkeypatch):
    monkeypatch.setattr(cli, "_gateway_client", lambda: FakeGateway(jobs=[RUNNING_JOB]))
    assert "Nothing is waiting for you." in runner.invoke(cli.app, ["approve"]).output


def test_approve_without_a_terminal_lists_and_does_not_block(gateway):
    result = runner.invoke(cli.app, ["approve"])
    assert result.exit_code == 0 and "1. Publish release notes" in result.output
    assert not [c for c in gateway.calls if c[0] == "approve"]


def test_approve_walkthrough_yes_no_and_change_request(gateway, monkeypatch):
    monkeypatch.setattr(plain, "interactive", lambda: True)
    answers = iter(["y", "n", "make it shorter"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert plain.do_approve(gateway) == 0
    assert ("approve", "aaaa1111") in gateway.calls
    assert ("reject", "bbbb2222", "make it shorter") in gateway.calls


def test_approve_warns_when_no_helper_is_free(monkeypatch, capsys):
    gw = FakeGateway(agents=[])
    plain.do_approve(gw, "Publish")
    assert "Approved, but no helper is free." in capsys.readouterr().out


def test_old_approve_by_id_still_exits_nonzero_on_403(monkeypatch):
    class Denied(FakeGateway):
        def approve(self, job_id):
            raise _http_error(403, "missing scope jobs:approve")

    monkeypatch.setattr(cli, "_gateway_client", lambda: Denied())
    result = runner.invoke(cli.app, ["approve", "aaaa1111"])
    assert result.exit_code == 1 and "isn't an approver" in result.output


def test_fix_offers_a_retry_and_runs_it_on_yes(gateway):
    gateway.job_list = [FAILED_JOB]
    result = runner.invoke(cli.app, ["fix", "--yes"])
    assert result.exit_code == 0 and "Found 1 problem." in result.output
    assert ("retry", "dddd4444") in gateway.calls


def test_fix_without_yes_or_terminal_changes_nothing(gateway):
    gateway.job_list = [FAILED_JOB]
    runner.invoke(cli.app, ["fix"])
    assert not gateway.calls


def test_fix_all_clear(gateway):
    assert "Everything looks fine." in runner.invoke(cli.app, ["fix"]).output


def test_fix_flags_work_waiting_with_no_helper(monkeypatch):
    pending = {"id": "p1", "title": "x", "status": "pending", "target_agent_role": "grok"}
    monkeypatch.setattr(cli, "_gateway_client", lambda: FakeGateway(jobs=[pending]))
    assert "grok helper" in runner.invoke(cli.app, ["fix"]).output


def test_old_failures_are_history_not_problems(gateway):
    gateway.job_list = [dict(FAILED_JOB, created_at="2020-01-01T00:00:00+00:00")]
    assert plain.find_problems(plain.take_snapshot(gateway), gateway) == []


def test_ask_shows_a_plan_then_sends_for_approval(gateway):
    result = runner.invoke(cli.app, ["ask", "tidy the install docs", "--yes"])
    assert result.exit_code == 0 and "Here's the plan:" in result.output
    (_, sent), = [c for c in gateway.calls if c[0] == "send"]
    assert sent["requires_approval"] is True and sent["instructions"] == "tidy the install docs"
    assert sent["to_role"] in {"codex", "claude"}


def test_ask_without_yes_or_terminal_starts_nothing(gateway):
    result = runner.invoke(cli.app, ["ask", "tidy the docs"])
    assert "I didn't start anything." in result.output
    assert not gateway.calls


def test_pause_asks_first_and_resume_clears(gateway):
    runner.invoke(cli.app, ["pause"])
    assert not gateway.calls
    runner.invoke(cli.app, ["pause", "--yes"])
    runner.invoke(cli.app, ["resume"])
    assert gateway.calls == [("settings_put", {"MCO_KILL_SWITCH": "true"}),
                             ("settings_put", {"MCO_KILL_SWITCH": None})]


def test_remember_one_sentence_and_old_two_argument_form(gateway):
    runner.invoke(cli.app, ["remember", "the blue folder"])
    runner.invoke(cli.app, ["remember", "A title", "the body"])
    first, second = [c[1] for c in gateway.calls]
    assert first["title"] == first["content"] == "the blue folder"
    assert (second["title"], second["content"]) == ("A title", "the body")


def test_helpers_lists_with_health_words(gateway):
    out = runner.invoke(cli.app, ["helpers"]).output
    assert "Codex 1" in out and "Ready" in out and "Working" in out


def test_helpers_json(gateway):
    data = json.loads(runner.invoke(cli.app, ["helpers", "--json"]).output)
    assert {h["instance_id"] for h in data} == {"codex-1", "claude-1"}


def test_connect_finds_writes_and_backs_up(tmp_path, monkeypatch):
    target = tmp_path / "settings.json"
    target.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}), encoding="utf-8")
    monkeypatch.setattr(plain, "_connect_targets", lambda: {"gemini": [target]})
    assert plain.do_connect("gemini", yes=True) == 0
    data = json.loads(target.read_text(encoding="utf-8"))
    assert "other" in data["mcpServers"] and "bitcadence" in data["mcpServers"]
    assert (tmp_path / "settings.json.bak").exists()
    assert plain.do_connect("gemini", yes=True) == 0  # idempotent


def test_connect_app_not_found_is_plain(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(plain, "_connect_targets", lambda: {"gemini": [tmp_path / "nope.json"]})
    assert plain.do_connect("gemini", yes=True) == 1
    assert "I couldn't find Gemini on this computer." in capsys.readouterr().out


# ── aliases: every old command is still here, unchanged ──────────────────────
OLD_COMMANDS = {
    "setup", "serve", "start", "restart", "gui", "tray", "launch", "stop", "mcp", "listen",
    "status", "upgrade", "doctor", "register", "edition", "agents", "send", "workflow",
    "audit", "audit-checkpoint", "restore-fence", "approve", "reject", "retry", "cancel",
    "archive", "unarchive", "duplicates", "reassign", "recall", "remember", "settings",
    "orgs", "reset-token", "deregister", "watch", "tail", "wake", "connectors", "sync",
    "platform",
}


def test_every_old_command_is_still_registered():
    import typer

    registered = set(typer.main.get_command(cli.app).commands)
    assert OLD_COMMANDS - registered == set()
    assert {"ask", "fix", "helpers", "connect", "pause", "resume", "advanced"} <= registered


def test_old_send_flags_are_unchanged(gateway):
    result = runner.invoke(cli.app, [
        "send", "codex", "--title", "T", "--message", "M", "--approve", "--retries", "2", "--priority", "5"])
    assert result.exit_code == 0
    (_, sent), = gateway.calls
    assert sent["to_role"] == "codex" and sent["title"] == "T" and sent["instructions"] == "M"
    assert sent["requires_approval"] is True and sent["max_retries"] == 2 and sent["priority"] == 5


def test_old_reject_still_takes_job_id_and_reason(gateway):
    runner.invoke(cli.app, ["reject", "aaaa1111", "--reason", "nope"])
    assert gateway.calls == [("reject", "aaaa1111", "nope")]


def test_advanced_runs_an_original_command(monkeypatch):
    result = runner.invoke(cli.app, ["advanced", "--version"])
    assert result.exit_code == 0 and "BitCadence" in result.output
    assert runner.invoke(cli.app, ["advanced"]).exit_code == 1


def test_schedule_alone_lists_and_old_subcommands_stay(monkeypatch):
    listed = []
    monkeypatch.setattr(cli, "list_schedules", lambda: listed.append(1))
    assert runner.invoke(cli.app, ["schedule"]).exit_code == 0 and listed
    import typer
    sub = typer.main.get_command(cli.app).commands["schedule"].commands
    assert {"init", "list", "enable", "disable", "reset", "tick", "run"} <= set(sub)


def test_entry_points_share_one_main():
    from pathlib import Path

    try:
        import tomllib
    except ImportError:  # Python 3.9/3.10
        import tomli as tomllib

    scripts = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text("utf-8"))["project"]["scripts"]
    assert scripts["bitcadence"] == scripts["mco"] == "mco.cli:main"


def test_say_survives_unprintable_characters(monkeypatch):
    import io

    buf = io.BytesIO()
    monkeypatch.setattr("sys.stdout", io.TextIOWrapper(buf, encoding="ascii", errors="strict"))
    plain.say("Tidy — docs")  # must not raise UnicodeEncodeError
    import sys
    sys.stdout.flush()
    assert b"Tidy" in buf.getvalue()
