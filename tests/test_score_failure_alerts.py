"""A Score run that blocks or fails pushes the owner once (incident #30)."""

import asyncio
import json
from types import SimpleNamespace

from mco.orchestrator import health, score_sweep
from mco.orchestrator.score_sweep import FAILING_ALERTS_FILENAME, SweepResult, alert_new_failures


def _config(tmp_path):
    return {"MCO_SCORE_ARTIFACT_ROOT": str(tmp_path)}


def _recorder():
    sent = []
    return sent, lambda kind, job_id, project="operations": sent.append((kind, job_id, project))


def _seed(tmp_path, alerted):
    (tmp_path / FAILING_ALERTS_FILENAME).write_text(json.dumps({"alerted": alerted}), encoding="utf-8")


def test_first_start_records_existing_failures_silently(tmp_path):
    sent, notify = _recorder()
    pushed = alert_new_failures({"bitcadence-redesign-20261006-05": "blocked"}, _config(tmp_path), notify)
    assert pushed == [] and sent == []
    state = json.loads((tmp_path / FAILING_ALERTS_FILENAME).read_text(encoding="utf-8"))
    assert state["alerted"] == ["bitcadence-redesign-20261006-05"]


def test_a_newly_blocked_run_pushes_once(tmp_path):
    _seed(tmp_path, [])
    sent, notify = _recorder()
    failing = {"bitcadence-redesign-20261006-06": "blocked"}
    assert alert_new_failures(failing, _config(tmp_path), notify) == ["bitcadence-redesign-20261006-06"]
    assert alert_new_failures(failing, _config(tmp_path), notify) == []   # next pass: silent
    assert sent == [("alert", "26100606", "bitcadence")]


def test_a_cleared_run_alerts_again_if_it_fails_later(tmp_path):
    _seed(tmp_path, ["run-a"])
    sent, notify = _recorder()
    alert_new_failures({}, _config(tmp_path), notify)                  # run-a cleared
    alert_new_failures({"run-a": "failed"}, _config(tmp_path), notify)  # fails again
    assert [s[0] for s in sent] == ["alert"]


def test_a_broken_notifier_never_raises(tmp_path):
    _seed(tmp_path, [])
    def boom(*_a, **_k):
        raise RuntimeError("relay down")
    assert alert_new_failures({"run-a": "blocked"}, _config(tmp_path), boom) == []


def test_an_empty_first_pass_does_not_seed_an_empty_list(tmp_path):
    sent, notify = _recorder()
    alert_new_failures({}, _config(tmp_path), notify)
    assert not (tmp_path / FAILING_ALERTS_FILENAME).exists()
    alert_new_failures({"old-run": "blocked"}, _config(tmp_path), notify)   # real first seed
    assert sent == []


def _loop_once(monkeypatch, result):
    calls = []
    stop = asyncio.Event()

    async def _once(_conductor):
        stop.set()
        return result

    monkeypatch.setattr(score_sweep, "open_conductor", lambda *a, **k: object())
    monkeypatch.setattr(health, "score_sweep_once", _once)
    monkeypatch.setattr(score_sweep, "alert_new_failures", lambda failing: calls.append(dict(failing)))
    app = SimpleNamespace(state=SimpleNamespace(
        score_sweep_seconds=1, score_sweep_started=0.0, score_sweep_last_ok=None,
        score_sweep_error=None, score_sweep_failing_runs=[]))
    asyncio.run(asyncio.wait_for(health.score_sweep_loop(app, 0.01, stop), timeout=5))
    return calls


def test_a_paused_sweep_does_not_touch_the_alert_state(monkeypatch):
    """Paused sweeps return before reading the runs table; an empty result must not wipe the alerted set."""
    assert _loop_once(monkeypatch, SweepResult(skipped={"_all": "sweep_paused"})) == []


def test_pause_then_resume_pushes_once(tmp_path):
    _seed(tmp_path, [])
    sent, notify = _recorder()
    alert_new_failures({"run-a": "blocked"}, _config(tmp_path), notify)
    # (paused passes are skipped by the loop, so no call here)
    alert_new_failures({"run-a": "blocked"}, _config(tmp_path), notify)
    assert len(sent) == 1


def test_the_gateway_sweep_loop_calls_the_alert(monkeypatch):
    """Wiring: the production sweep loop hands durable failures to the alert, not tick errors."""
    calls = []
    result = SweepResult(failing={"run-a": "blocked", "run-b": "RuntimeError: boom"},
                         errors={"run-b": "RuntimeError: boom"})
    stop = asyncio.Event()

    async def _once(_conductor):
        stop.set()
        return result

    monkeypatch.setattr(score_sweep, "open_conductor", lambda *a, **k: object())
    monkeypatch.setattr(health, "score_sweep_once", _once)
    monkeypatch.setattr(score_sweep, "alert_new_failures", lambda failing: calls.append(dict(failing)))
    app = SimpleNamespace(state=SimpleNamespace(
        score_sweep_seconds=1, score_sweep_started=0.0, score_sweep_last_ok=None,
        score_sweep_error=None, score_sweep_failing_runs=[]))

    asyncio.run(asyncio.wait_for(health.score_sweep_loop(app, 0.01, stop), timeout=5))

    assert calls == [{"run-a": "blocked"}]
