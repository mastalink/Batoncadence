import json
from datetime import datetime, timezone

import pytest
import yaml

from mco.launcher import (
    LaunchError,
    has_active_jobs,
    launch,
    load_state,
    run_forever,
    save_state,
    tick,
)
from mco.scheduler import Launcher, ScheduleState


def _utc(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


class FakeClient:
    """Minimal stand-in for GatewayClient: records sends, serves a fake board."""

    def __init__(self, board=None, fail_send=False):
        self.sends = []
        self.board = board or []
        self.fail_send = fail_send
        self._next_id = 0

    def send(self, **kwargs):
        self.sends.append(kwargs)
        if self.fail_send:
            return {"success": False, "error": "boom"}
        self._next_id += 1
        job_id = f"job{self._next_id}"
        return {"success": True, "job": {"id": job_id}}

    def jobs(self, include_archived=False):
        return self.board


def _write_config(tmp_path, data):
    path = tmp_path / "schedules.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def _base_config(**overrides):
    base = {
        "launchers": {
            "audit": {"role": "reviewer", "title": "Audit", "instructions": "Check deps"},
        },
        "schedules": {"nightly": {"launcher": "audit", "every": "1h"}},
    }
    base.update(overrides)
    return base


# ── launching ─────────────────────────────────────────────────────────────────

def test_launch_creates_a_job_with_origin_stamp():
    client = FakeClient()
    launcher = Launcher(name="audit", role="reviewer", title="Audit", instructions="Check")
    job_ids = launch(launcher, client, trigger="schedule", schedule_name="nightly", iteration=3)

    assert job_ids == ["job1"]
    sent = client.sends[0]
    assert sent["to_role"] == "reviewer"
    # The audit trail must be able to answer "what created this job?" - the
    # question plain cron can never answer.
    origin = sent["extra_payload"]["origin"]
    assert origin["launcher"] == "audit"
    assert origin["schedule"] == "nightly"
    assert origin["trigger"] == "schedule"
    assert origin["iteration"] == 3


def test_launch_raises_when_the_gateway_rejects():
    client = FakeClient(fail_send=True)
    launcher = Launcher(name="audit", role="reviewer", title="Audit")
    with pytest.raises(LaunchError, match="failed to create a job"):
        launch(launcher, client)


def test_launch_honours_approval_override():
    client = FakeClient()
    launcher = Launcher(name="a", role="r", title="t", requires_approval=False)
    launch(launcher, client, requires_approval_override=True)
    assert client.sends[0]["requires_approval"] is True


def test_workflow_launcher_reports_a_missing_file():
    client = FakeClient()
    launcher = Launcher(name="rel", workflow="/nonexistent/workflow.yaml")
    with pytest.raises(LaunchError, match="workflow file not found"):
        launch(launcher, client)


def test_workflow_launcher_submits_every_step(tmp_path):
    workflow = tmp_path / "release.yaml"
    workflow.write_text(yaml.safe_dump({
        "name": "release",
        "steps": [
            {"id": "build", "role": "codex", "title": "Build"},
            {"id": "ship", "role": "codex", "title": "Ship", "depends_on": ["build"]},
        ],
    }), encoding="utf-8")

    client = FakeClient()
    job_ids = launch(Launcher(name="rel", workflow=str(workflow)), client)
    assert len(job_ids) == 2
    assert len(client.sends) == 2


# ── state persistence ─────────────────────────────────────────────────────────

def test_state_round_trips_through_disk(tmp_path):
    path = tmp_path / "state.json"
    save_state({"s": ScheduleState(name="s", iterations=2, last_run_at=_utc(2026, 7, 1))}, path)
    restored = load_state(path)
    assert restored["s"].iterations == 2
    assert restored["s"].last_run_at == _utc(2026, 7, 1)


def test_missing_state_file_is_empty_not_an_error(tmp_path):
    assert load_state(tmp_path / "nope.json") == {}


def test_corrupt_state_starts_fresh_rather_than_wedging(tmp_path):
    # A scheduler that refuses to start because its state file is damaged is a
    # worse failure than one duplicate run.
    path = tmp_path / "state.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_state(path) == {}


def test_save_state_is_atomic_and_leaves_no_temp_files(tmp_path):
    path = tmp_path / "state.json"
    save_state({"s": ScheduleState(name="s", iterations=1)}, path)
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".schedule-state-")]


# ── overlap detection ─────────────────────────────────────────────────────────

def test_has_active_jobs_detects_in_flight_work():
    client = FakeClient(board=[{"id": "job1", "status": "in_progress"}])
    assert has_active_jobs(client, ["job1"]) is True


def test_has_active_jobs_ignores_finished_work():
    client = FakeClient(board=[{"id": "job1", "status": "completed"}])
    assert has_active_jobs(client, ["job1"]) is False


def test_has_active_jobs_fails_open_when_gateway_is_down():
    class Broken(FakeClient):
        def jobs(self, include_archived=False):
            raise ConnectionError("gateway down")

    # Fail open: a transient blip must not silently pause every schedule.
    assert has_active_jobs(Broken(), ["job1"]) is False


def test_has_active_jobs_short_circuits_on_empty():
    assert has_active_jobs(FakeClient(), []) is False


# ── the tick ──────────────────────────────────────────────────────────────────

def test_tick_fires_a_due_schedule_and_records_state(tmp_path):
    config = _write_config(tmp_path, _base_config())
    state_path = tmp_path / "state.json"
    client = FakeClient()

    report = tick(client, config, state_path, now=_utc(2026, 7, 1, 12))

    assert [r["action"] for r in report] == ["fired"]
    assert report[0]["job_ids"] == ["job1"]
    saved = load_state(state_path)
    assert saved["nightly"].iterations == 1
    assert saved["nightly"].last_job_ids == ["job1"]


def test_tick_does_not_refire_before_the_interval(tmp_path):
    config = _write_config(tmp_path, _base_config())
    state_path = tmp_path / "state.json"
    client = FakeClient()

    tick(client, config, state_path, now=_utc(2026, 7, 1, 12))
    report = tick(client, config, state_path, now=_utc(2026, 7, 1, 12, 30))

    assert report == []
    assert len(client.sends) == 1


def test_tick_skips_when_previous_run_is_still_active(tmp_path):
    config = _write_config(tmp_path, _base_config())
    state_path = tmp_path / "state.json"
    client = FakeClient()

    tick(client, config, state_path, now=_utc(2026, 7, 1, 12))
    client.board = [{"id": "job1", "status": "in_progress"}]
    report = tick(client, config, state_path, now=_utc(2026, 7, 1, 13, 1))

    assert [r["action"] for r in report] == ["skipped-overlap"]
    assert len(client.sends) == 1  # no duplicate job


def test_tick_allows_overlap_when_configured(tmp_path):
    config = _write_config(tmp_path, _base_config(
        schedules={"nightly": {"launcher": "audit", "every": "1h", "overlap": "allow"}}
    ))
    state_path = tmp_path / "state.json"
    client = FakeClient()

    tick(client, config, state_path, now=_utc(2026, 7, 1, 12))
    client.board = [{"id": "job1", "status": "in_progress"}]
    report = tick(client, config, state_path, now=_utc(2026, 7, 1, 13, 1))

    assert [r["action"] for r in report] == ["fired"]
    assert len(client.sends) == 2


def test_tick_dry_run_creates_nothing(tmp_path):
    config = _write_config(tmp_path, _base_config())
    state_path = tmp_path / "state.json"
    client = FakeClient()

    report = tick(client, config, state_path, now=_utc(2026, 7, 1, 12), dry_run=True)

    assert [r["action"] for r in report] == ["would-fire"]
    assert client.sends == []
    assert not state_path.exists()


def test_tick_records_an_error_without_dying(tmp_path):
    config = _write_config(tmp_path, _base_config())
    client = FakeClient(fail_send=True)

    report = tick(client, config, tmp_path / "state.json", now=_utc(2026, 7, 1, 12))

    assert [r["action"] for r in report] == ["error"]
    assert "failed to create a job" in report[0]["detail"]


def test_loop_stops_itself_after_max_iterations(tmp_path):
    config = _write_config(tmp_path, _base_config(schedules={}, loops={
        "triage": {"launcher": "audit", "every": "1m", "max_iterations": 2}
    }))
    state_path = tmp_path / "state.json"
    client = FakeClient()

    for minute in range(5):
        tick(client, config, state_path, now=_utc(2026, 7, 1, 12, minute))

    # The bound is enforced by the runtime, not just documented in config.
    assert len(client.sends) == 2
    saved = load_state(state_path)
    assert saved["triage"].iterations == 2
    assert "completed all 2 iterations" in (saved["triage"].exhausted_reason or "")


def test_loop_stops_itself_at_until(tmp_path):
    config = _write_config(tmp_path, _base_config(schedules={}, loops={
        "windowed": {
            "launcher": "audit", "every": "1m", "until": "2026-07-01T12:02:00Z",
        }
    }))
    state_path = tmp_path / "state.json"
    client = FakeClient()

    for minute in range(6):
        tick(client, config, state_path, now=_utc(2026, 7, 1, 12, minute))

    assert len(client.sends) == 3  # 12:00, 12:01, 12:02 - then the window closes


def test_disabled_schedule_never_fires(tmp_path):
    config = _write_config(tmp_path, _base_config(
        schedules={"off": {"launcher": "audit", "every": "1m", "enabled": False}}
    ))
    report = tick(FakeClient(), config, tmp_path / "state.json", now=_utc(2026, 7, 1, 12))
    assert report == []


def test_run_forever_survives_a_broken_tick(tmp_path, monkeypatch):
    # A bad config must not kill the daemon - the failure operators actually
    # suffer is a scheduler that quietly died weeks ago.
    monkeypatch.setattr("mco.launcher.time.sleep", lambda _: None)
    missing = tmp_path / "nope.yaml"
    run_forever(FakeClient(), missing, tmp_path / "state.json", interval=0, max_ticks=3)
