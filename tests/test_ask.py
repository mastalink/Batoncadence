"""Slice 4: "Ask for something". One planner behind the terminal and the console."""
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import mco.cli as cli
from mco import ask_plan, plain
from mco.orchestrator.ask_routes import ask_router

ROOT = Path(__file__).parents[1]
SRC = ROOT / "src/mco/console_src"
runner = CliRunner()
REQUEST = "Research open PRs, run tests, if green draft release notes and ask me to publish."


class Gateway:
    """GatewayClient-shaped stand-in that numbers the jobs it creates."""

    def __init__(self):
        self.sent = []

    def jobs(self, **_):
        return []

    def agents(self):
        return [{"instance_id": "codex-1", "role": "codex", "effective_status": "online", "state": "standby"}]

    def settings(self):
        return {"groups": {"safety": []}}

    def send(self, **kwargs):
        self.sent.append(kwargs)
        return {"success": True, "job": {"id": f"job{len(self.sent)}", "status": "needs_approval"}}


@pytest.fixture
def gateway(monkeypatch, tmp_path):
    gw = Gateway()
    monkeypatch.setattr(cli, "_gateway_client", lambda: gw)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    return gw


# -- the planner ---------------------------------------------------------------
def test_the_mockup_request_becomes_the_mockup_plan():
    plan = ask_plan.draft_plan(REQUEST, "codex")
    assert [s["label"] for s in plan["steps"]] == [
        "Look at open pull requests", "Run tests", "Draft release notes", "Ask you before publishing"]
    assert [s["gate"] for s in plan["steps"]] == [False, False, False, True]
    assert plan["steps"][2]["note"] == "If everything passes"
    assert [s["depends_on"] for s in plan["steps"]] == [[], ["step-1"], ["step-2"], ["step-3"]]


def test_a_simple_request_is_one_step_that_keeps_its_words():
    plan = ask_plan.draft_plan("tidy the install docs")
    assert len(plan["steps"]) == 1 and plan["steps"][0]["instructions"] == "tidy the install docs"


def test_an_empty_request_is_refused_in_plain_words():
    with pytest.raises(ask_plan.PlanError, match="Tell me"):
        ask_plan.draft_plan("   ")


def test_remove_a_step_reconnects_the_chain():
    plan = ask_plan.remove_step(ask_plan.draft_plan(REQUEST), "step-2")
    assert [s["id"] for s in plan["steps"]] == ["step-1", "step-3", "step-4"]
    assert plan["steps"][1]["depends_on"] == ["step-1"]


def test_cannot_remove_the_last_step_or_a_missing_one():
    with pytest.raises(ask_plan.PlanError):
        ask_plan.remove_step(ask_plan.draft_plan("tidy docs"), "step-1")
    with pytest.raises(ask_plan.PlanError):
        ask_plan.remove_step(ask_plan.draft_plan(REQUEST), "step-9")


def test_ask_me_at_the_end_adds_one_gate_with_a_unique_id():
    plan = ask_plan.draft_plan("check the site, tidy the docs, write a note, send it")
    plan = ask_plan.apply_tweaks(plan, remove=["step-2"], ask_end=True)
    ids = [s["id"] for s in plan["steps"]]
    assert len(ids) == len(set(ids)) and plan["steps"][-1]["gate"]
    assert ask_plan.ask_at_end(plan) == plan  # already asking: nothing more is added


@pytest.mark.parametrize("phrase,cron,words", [
    ("every Friday at 9 AM", "0 9 * * 5", "Every Friday at 9:00 AM"),
    ("every weekday at 7:30 pm", "30 19 * * 1-5", "Every weekday at 7:30 PM"),
    ("every day", "0 9 * * *", "Every day at 9:00 AM"),
])
def test_repeat_phrases(phrase, cron, words):
    assert ask_plan.parse_repeat(phrase) == {"cron": cron, "words": words}


def test_a_repeat_nobody_can_schedule_is_refused():
    with pytest.raises(ask_plan.PlanError, match="how often"):
        ask_plan.parse_repeat("sometimes")


def test_saved_repeat_loads_in_the_real_scheduler(tmp_path):
    from mco import scheduler
    from mco.orchestrator.workflows import load_workflow
    plan = ask_plan.make_repeat(ask_plan.draft_plan(REQUEST), "every Friday at 9 AM")
    name = ask_plan.save_repeat(plan, tmp_path)
    launchers, schedules = scheduler.load_config(tmp_path / "schedules.yaml")
    assert schedules[name].cron.raw == "0 9 * * 5" and launchers[name].is_workflow
    saved = load_workflow(Path(launchers[name].workflow).read_text(encoding="utf-8"))
    assert len(saved["steps"]) == 4


def test_saving_a_repeat_keeps_existing_schedules_and_a_backup(tmp_path):
    (tmp_path / "schedules.yaml").write_text(yaml.safe_dump({
        "launchers": {"old": {"role": "claude", "title": "Old"}},
        "schedules": {"old": {"launcher": "old", "every": "1h"}}}), encoding="utf-8")
    ask_plan.save_repeat(ask_plan.make_repeat(ask_plan.draft_plan("tidy docs"), "every day"), tmp_path)
    saved = yaml.safe_load((tmp_path / "schedules.yaml").read_text(encoding="utf-8"))
    assert "old" in saved["schedules"] and len(saved["schedules"]) == 2
    assert (tmp_path / "schedules.yaml.bak").exists()


# -- the terminal path ---------------------------------------------------------
def test_cli_ask_draws_the_plan_and_chains_the_jobs(gateway):
    result = runner.invoke(cli.app, ["ask", REQUEST, "--yes"])
    assert result.exit_code == 0, result.output
    assert "1. Look at open pull requests" in result.output and "4. Ask you before publishing" in result.output
    assert len(gateway.sent) == 4
    assert gateway.sent[0]["requires_approval"] is True and gateway.sent[1]["requires_approval"] is False
    assert gateway.sent[3]["requires_approval"] is True
    assert gateway.sent[1]["depends_on"] == ["job1"] and gateway.sent[3]["depends_on"] == ["job3"]
    assert len({s["extra_payload"]["workflow"]["run"] for s in gateway.sent}) == 1


def test_do_ask_uses_the_shared_planner(gateway, monkeypatch):
    seen = []
    real = ask_plan.draft_plan
    monkeypatch.setattr(ask_plan, "draft_plan", lambda *a, **k: seen.append(a) or real(*a, **k))
    plain.do_ask(gateway, "tidy docs", yes=True)
    assert seen and gateway.sent


def test_cli_tweaks_remove_ask_me_and_repeat(gateway, tmp_path):
    result = runner.invoke(cli.app, ["ask", REQUEST, "--yes", "--remove", "2", "--ask-me",
                                     "--repeat", "every Friday at 9 AM"])
    assert result.exit_code == 0, result.output
    assert [s["title"] for s in gateway.sent] == [
        "Look at open pull requests", "Draft release notes", "Ask you before publishing"]
    assert gateway.sent[2]["instructions"] == "Wait for the owner's OK to publish."
    assert "Repeats: Every Friday at 9:00 AM" in result.output and "Scheduled:" in result.output
    assert list((tmp_path / ".mco" / "workflows").glob("ask-*.yaml"))


def test_cli_bad_tweaks_start_nothing(gateway):
    for args in (["--remove", "9"], ["--repeat", "sometimes"]):
        result = runner.invoke(cli.app, ["ask", REQUEST, "--yes", *args])
        assert result.exit_code == 1 and not gateway.sent


def test_yaml_files_still_load_through_ask_file(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(cli, "submit_workflow_file", lambda path, dry_run=False: seen.append(path))
    runner.invoke(cli.app, ["ask", "--file", str(tmp_path / "plan.yaml")])
    assert seen == [str(tmp_path / "plan.yaml")]


# -- the gateway path the console calls ----------------------------------------
def _app(monkeypatch, tmp_path):
    import mco.orchestrator.routes as board_routes
    from mco.localstore import LocalStore
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    board = LocalStore(tmp_path / "board.db")
    monkeypatch.setattr(board_routes, "get_db_client", lambda: board)
    app = FastAPI()
    app.include_router(ask_router)
    for route in app.routes:
        if getattr(route, "path", "").startswith("/api/ask"):
            app.dependency_overrides[route.dependant.dependencies[0].call] = lambda: {
                "org_id": "default", "instance_id": "me", "role": "human",
                "scopes": ["jobs:read", "jobs:write"]}
    return TestClient(app), board


def test_ask_routes_need_a_login():
    app = FastAPI()
    app.include_router(ask_router)
    http = TestClient(app)
    assert http.post("/api/ask/plan", json={"request": "x"}).status_code == 401
    assert http.post("/api/ask/start", json={"request": "x"}).status_code == 401


def test_plan_route_draws_with_tweaks_and_creates_nothing(monkeypatch, tmp_path):
    http, board = _app(monkeypatch, tmp_path)
    res = http.post("/api/ask/plan", json={"request": REQUEST, "role": "codex", "remove": ["step-2"],
                                           "ask_at_end": True, "repeat": "every Friday at 9 AM"})
    plan = res.json()["plan"]
    assert res.status_code == 200 and [s["id"] for s in plan["steps"]] == ["step-1", "step-3", "step-4"]
    assert plan["steps"][0]["role"] == "codex" and plan["repeat"]["words"] == "Every Friday at 9:00 AM"
    assert not board.table("agent_jobs").select("*").execute().data


@pytest.mark.parametrize("body", [{"request": ""}, {"request": "x" * 3000}, {"request": "x", "remove": "step-1"},
                                  {"request": "x", "repeat": "sometimes"}, {"request": "x", "remove": ["step-1"]}])
def test_plan_route_rejects_bad_input_in_plain_words(monkeypatch, tmp_path, body):
    http, _ = _app(monkeypatch, tmp_path)
    res = http.post("/api/ask/plan", json=body)
    assert res.status_code == 400 and "{" not in res.json()["detail"]


def test_start_route_creates_the_chain_and_the_approve_click_is_the_ok(monkeypatch, tmp_path):
    http, board = _app(monkeypatch, tmp_path)
    res = http.post("/api/ask/start", json={"request": REQUEST, "role": "codex",
                                            "repeat": "every day at 7 AM"})
    assert res.status_code == 200, res.text
    assert res.json()["repeat"] == "Every day at 7:00 AM" and res.json()["scheduled"]
    jobs = {j["id"]: j for j in board.table("agent_jobs").select("*").execute().data}
    ids = res.json()["jobs"]
    assert len(jobs) == 4
    first, second, last = (jobs[ids[k]] for k in ("step-1", "step-2", "step-4"))
    assert first["status"] == "pending" and first["target_agent_role"] == "codex"  # no extra wait
    assert second["depends_on"] == [ids["step-1"]] and second["status"] == "waiting"
    assert last["requires_approval"] is True  # the plan's own "ask you" step still asks
    assert (tmp_path / "schedules.yaml").exists() is False
    assert (tmp_path / ".mco" / "schedules.yaml").exists()


# -- the console ---------------------------------------------------------------
def _read(prefix):
    return next(SRC.glob(prefix + "*")).read_text(encoding="utf-8")


def test_console_ask_page_calls_the_planner_and_the_builders_are_gone():
    page, store, shell, home = (_read(p) for p in ("bb158701", "47e66145", "8ec84a72", "43b328d0"))
    assert 'api("/api/ask/plan"' in store and 'api("/api/ask/start"' in store
    assert "store.draftAsk(" in page and "store.startAsk(" in page
    assert "ask: <AskPage" in shell and 'id: "ask"' in shell and 'onNav("ask")' in home
    for gone in ("draggable", "onDragStart", "WorkflowBuilder", "toYaml", "submitWorkflow"):
        assert gone not in page + store + shell + home + _read("e63b9c8d")


def test_console_ask_page_follows_the_design_rules():
    page = _read("bb158701")
    for text in ("Ask for something", "Draft a plan", "Remove a step", "Always ask me at the end",
                 "Make it repeat", "Approve and start", "Change my request"):
        assert text in page
    assert "min-height:48px" in page and ":focus-visible" in page and "prefers-reduced-motion" in page
    assert "aria-pressed" in page
    bundle = (ROOT / "src/mco/static/console.html").read_text(encoding="utf-8")
    assert "WorkflowBuilder" not in bundle


def test_flow_page_is_gone_but_gui_flag_still_works():
    paths = {getattr(r, "path", None) for r in cli.create_app().routes}
    assert "/flow" not in paths and "/console" in paths and "/api/ask/plan" in paths
    assert not (ROOT / "src/mco/static/flow.html").exists()
    result = runner.invoke(cli.app, ["gui", "--flow", "--print"])
    assert result.exit_code == 0 and result.output.strip().endswith("/console")


@pytest.mark.skipif(os.environ.get("BC_TEST_BROWSER") != "1", reason="Set BC_TEST_BROWSER=1 with Playwright Chromium installed")
def test_shipped_bundle_ask_page_end_to_end():
    result = subprocess.run([sys.executable, str(ROOT / "scripts/capture_ask.py")], cwd=ROOT,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "production Ask -> plan -> approve" in result.stdout
