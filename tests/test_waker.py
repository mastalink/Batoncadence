import asyncio
import sys

import pytest

from mco.waker import Waker


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def inbox(self):
        self.calls += 1
        if self.responses:
            return self.responses.pop(0)
        return []


def _event(event="job_pending", role="codex", instance=""):
    return {
        "type": "event",
        "payload": {
            "event": event,
            "job": {
                "id": "j1",
                "target_agent_role": role,
                "target_agent_id": instance,
            },
        },
    }


def _marker_cmd(marker, sleep=0.0):
    code = (
        "import pathlib,time; "
        f"p=pathlib.Path({str(marker)!r}); "
        "p.write_text((p.read_text() if p.exists() else '') + 'x'); "
        f"time.sleep({sleep})"
    )
    return f'"{sys.executable}" -c "{code}"'


def _exit_cmd(code):
    return f'"{sys.executable}" -c "import sys; sys.exit({code})"'


async def _wait_for_marker(marker, timeout=2.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if marker.exists():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"marker was not written: {marker}")


@pytest.mark.asyncio
async def test_matching_job_pending_spawns(tmp_path):
    marker = tmp_path / "spawned.txt"
    client = FakeClient([[{"id": "j1"}]])
    waker = Waker(_marker_cmd(marker), "codex", "codex-beast", min_interval=0, client=client)

    await waker.handle_message(_event(role="CoDeX"))
    await waker.wait_for_idle()

    assert marker.read_text() == "x"
    assert client.calls == 1


@pytest.mark.asyncio
async def test_non_matching_events_do_not_spawn(tmp_path):
    marker = tmp_path / "spawned.txt"
    client = FakeClient([[{"id": "j1"}]])
    waker = Waker(_marker_cmd(marker), "codex", "codex-beast", min_interval=0, client=client)

    await waker.handle_message(_event(role="reviewer"))
    await waker.handle_message(_event(role="codex", instance="other-instance"))
    await waker.handle_message(_event(event="job_needs_approval", role="codex"))
    await waker.handle_message(_event(event="job_leased", role="codex"))
    await asyncio.sleep(0)

    assert not marker.exists()
    assert client.calls == 0


@pytest.mark.asyncio
async def test_burst_while_child_runs_sets_dirty_for_one_extra_drain(tmp_path):
    marker = tmp_path / "spawned.txt"
    client = FakeClient([[{"id": "j1"}], [{"id": "j2"}], [{"id": "j3"}]])
    waker = Waker(_marker_cmd(marker, sleep=0.25), "codex", "codex-beast", min_interval=0, client=client)

    await waker.handle_message(_event(role="codex"))
    await _wait_for_marker(marker)
    for _ in range(5):
        await waker.handle_message(_event(role="codex"))
    await waker.wait_for_idle()

    assert marker.read_text() == "xx"
    assert client.calls == 2


@pytest.mark.asyncio
async def test_reconnect_sweep_spawns_without_event(tmp_path):
    marker = tmp_path / "spawned.txt"
    client = FakeClient([[{"id": "j1"}]])
    waker = Waker(_marker_cmd(marker), "codex", "codex-beast", min_interval=0, client=client)

    waker.on_connected()
    await waker.wait_for_idle()

    assert marker.read_text() == "x"
    assert client.calls == 1


@pytest.mark.asyncio
async def test_empty_inbox_blocks_spawn_even_for_matching_event(tmp_path):
    marker = tmp_path / "spawned.txt"
    client = FakeClient([[]])
    waker = Waker(_marker_cmd(marker), "codex", "codex-beast", min_interval=0, client=client)

    await waker.handle_message(_event(role="codex"))
    await waker.wait_for_idle()

    assert not marker.exists()
    assert client.calls == 1


@pytest.mark.asyncio
async def test_nonzero_exec_does_not_kill_waker(tmp_path):
    marker = tmp_path / "spawned.txt"
    client = FakeClient([[{"id": "j1"}], [{"id": "j2"}]])
    waker = Waker(_exit_cmd(1), "codex", "codex-beast", min_interval=0, client=client)

    await waker.handle_message(_event(role="codex"))
    await waker.wait_for_idle()

    waker.exec_command = _marker_cmd(marker)
    await waker.handle_message(_event(role="codex"))
    await waker.wait_for_idle()

    assert marker.read_text() == "x"
    assert client.calls == 2
