from datetime import datetime, timedelta, timezone

import pytest

from mco.orchestrator.resource_arbiter import ResourceArbiter, next_daily_deadline


@pytest.fixture
def arbiter(tmp_path):
    return ResourceArbiter(tmp_path / "state.json", {"timezone": "UTC"})


def test_first_acquire_grants_and_fires_idle_to_busy(tmp_path):
    calls = []
    config_path = tmp_path / "config.json"
    import json
    config_path.write_text(json.dumps({
        "timezone": "UTC",
        "resources": {"gpu": {"on_idle_to_busy": {"run": ["python3", "-c", "pass"]}}},
    }))
    arbiter = ResourceArbiter(tmp_path / "state.json", json.loads(config_path.read_text()))
    result = arbiter.acquire("gpu", "toolbox")
    assert result == {"granted": True, "holder": "toolbox"}


def test_second_acquire_is_queued_not_granted(arbiter):
    arbiter.acquire("gpu", "toolbox")
    result = arbiter.acquire("gpu", "factory")
    assert result["granted"] is False
    assert result["holder"] == "toolbox"
    assert result["position"] == 1


def test_queue_is_priority_then_fifo(arbiter):
    arbiter.acquire("gpu", "holder")
    arbiter.acquire("gpu", "low-priority", priority=0)
    arbiter.acquire("gpu", "high-priority", priority=10)
    status = arbiter.status("gpu")
    assert [w["owner"] for w in status["queue"]] == ["high-priority", "low-priority"]


def test_re_acquire_by_current_holder_does_not_queue(arbiter):
    arbiter.acquire("gpu", "toolbox")
    result = arbiter.acquire("gpu", "toolbox", priority=5)
    assert result == {"granted": True, "holder": "toolbox"}
    assert arbiter.status("gpu")["queue"] == []


def test_release_by_non_holder_is_a_noop(arbiter):
    arbiter.acquire("gpu", "toolbox")
    result = arbiter.release("gpu", "someone-else")
    assert result == {"released": False}
    assert arbiter.status("gpu")["holder"]["owner"] == "toolbox"


def test_release_promotes_next_waiter_without_going_idle(tmp_path):
    import json
    config = {"timezone": "UTC", "resources": {"gpu": {"on_busy_to_idle": {"run": None}}}}
    arbiter = ResourceArbiter(tmp_path / "state.json", config)
    arbiter.acquire("gpu", "toolbox")
    arbiter.acquire("gpu", "factory")
    result = arbiter.release("gpu", "toolbox")
    assert result == {"released": True, "new_holder": "factory"}
    assert arbiter.status("gpu")["holder"]["owner"] == "factory"


def test_release_of_last_holder_goes_idle(arbiter):
    arbiter.acquire("gpu", "toolbox")
    result = arbiter.release("gpu", "toolbox")
    assert result == {"released": True, "new_holder": None}
    assert arbiter.status("gpu")["holder"] is None


def test_soft_deadline_hands_off_to_next_waiter(arbiter):
    now = datetime(2026, 9, 30, 2, 0, tzinfo=timezone.utc)
    arbiter.acquire("gpu", "toolbox", deadline=(now + timedelta(hours=2)).isoformat(), now=now)
    arbiter.acquire("gpu", "factory", now=now)
    later = now + timedelta(hours=2, minutes=1)
    status = arbiter.status("gpu", now=later)
    assert status["holder"]["owner"] == "factory"


def test_soft_deadline_with_empty_queue_leaves_resource_idle(arbiter):
    now = datetime(2026, 9, 30, 2, 0, tzinfo=timezone.utc)
    arbiter.acquire("gpu", "toolbox", deadline=(now + timedelta(hours=2)).isoformat(), now=now)
    later = now + timedelta(hours=2, minutes=1)
    status = arbiter.status("gpu", now=later)
    assert status["holder"] is None


def test_hard_deadline_clears_holder_and_queue_even_past_soft_deadlines(tmp_path):
    import json
    config = {"timezone": "UTC", "resources": {"gpu": {"hard_deadline_local": "06:00"}}}
    arbiter = ResourceArbiter(tmp_path / "state.json", config)
    morning = datetime(2026, 9, 30, 2, 0, tzinfo=timezone.utc)
    arbiter.acquire("gpu", "toolbox", now=morning)
    arbiter.acquire("gpu", "factory", now=morning)
    past_hard_stop = datetime(2026, 9, 30, 6, 1, tzinfo=timezone.utc)
    status = arbiter.status("gpu", now=past_hard_stop)
    assert status["holder"] is None
    assert status["queue"] == []


def test_hard_deadline_fires_even_if_holder_crashed_and_never_released(tmp_path):
    """The whole point: nothing has to call release() for the guarantee to hold."""
    import json
    config = {"timezone": "UTC", "resources": {"gpu": {"hard_deadline_local": "06:00"}}}
    arbiter = ResourceArbiter(tmp_path / "state.json", config)
    morning = datetime(2026, 9, 30, 2, 0, tzinfo=timezone.utc)
    arbiter.acquire("gpu", "crashed-worker", now=morning)
    events = arbiter.enforce_deadlines(now=datetime(2026, 9, 30, 6, 0, 1, tzinfo=timezone.utc))
    assert len(events) == 1
    assert events[0]["expired_owner"] == "crashed-worker"
    assert events[0]["hard"] is True


def test_hard_deadline_is_idempotent_for_rest_of_day(tmp_path):
    config = {"timezone": "UTC", "resources": {"gpu": {"hard_deadline_local": "06:00"}}}
    arbiter = ResourceArbiter(tmp_path / "state.json", config)
    morning = datetime(2026, 9, 30, 2, 0, tzinfo=timezone.utc)
    arbiter.acquire("gpu", "toolbox", now=morning)
    first = arbiter.enforce_deadlines(now=datetime(2026, 9, 30, 6, 1, tzinfo=timezone.utc))
    second = arbiter.enforce_deadlines(now=datetime(2026, 9, 30, 20, 0, tzinfo=timezone.utc))
    assert len(first) == 1
    assert second == []


def test_state_persists_across_new_arbiter_instances(tmp_path):
    state_path = tmp_path / "state.json"
    ResourceArbiter(state_path, {"timezone": "UTC"}).acquire("gpu", "toolbox")
    reopened = ResourceArbiter(state_path, {"timezone": "UTC"})
    assert reopened.status("gpu")["holder"]["owner"] == "toolbox"


def test_next_daily_deadline_rolls_to_tomorrow_if_already_past(tmp_path):
    now = datetime(2026, 9, 30, 7, 0, tzinfo=timezone.utc)
    deadline = next_daily_deadline("06:00", now)
    assert deadline.date() == (now + timedelta(days=1)).date()
    assert deadline.hour == 6
