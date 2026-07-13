import asyncio
import json
import sys

import pytest

from mco.waker import Waker, WakerAuthError


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


# --- run_forever retry policy (boot race vs. genuinely bad token) ---


AUTH_OK = json.dumps({"type": "authenticated", "payload": {"success": True}})
AUTH_REJECTED = json.dumps({
    "type": "authenticated",
    "payload": {"success": False, "error": "invalid token"},
})


class FakeWS:
    """Async-context-manager WebSocket: one auth reply, then scripted frames."""

    def __init__(self, auth_reply=AUTH_OK, frames=()):
        self.auth_reply = auth_reply
        self.frames = list(frames)
        self.sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def send(self, data):
        self.sent.append(data)

    async def recv(self):
        return self.auth_reply

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.frames:
            return self.frames.pop(0)
        raise StopAsyncIteration


class FakeConnect:
    """Scripted connect factory; raises CancelledError when the script runs out."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.attempts = 0

    def __call__(self, url):
        self.attempts += 1
        if not self.outcomes:
            raise asyncio.CancelledError
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeTime:
    """Monotonic clock advanced only by the waker's own sleeps."""

    def __init__(self):
        self.now = 0.0

    def clock(self):
        return self.now

    async def sleep(self, duration):
        self.now += duration
        await asyncio.sleep(0)


def _run_forever_waker(connect, client=None, **kwargs):
    fake_time = FakeTime()
    waker = Waker(
        _exit_cmd(0),
        "codex",
        "codex-beast",
        min_interval=0,
        client=client or FakeClient([]),
        sleep=fake_time.sleep,
        connect=connect,
        clock=fake_time.clock,
        **kwargs,
    )
    return waker, fake_time


@pytest.mark.asyncio
async def test_boot_race_auth_rejections_are_retried(tmp_path):
    """Gateway briefly serving 401s at boot must not kill the waker."""
    marker = tmp_path / "spawned.txt"
    connect = FakeConnect([
        FakeWS(auth_reply=AUTH_REJECTED),
        FakeWS(auth_reply=AUTH_REJECTED),
        FakeWS(auth_reply=AUTH_REJECTED),
        FakeWS(),  # gateway finished starting; auth now succeeds
    ])
    client = FakeClient([[{"id": "j1"}]])
    # Rejection count exceeds the threshold, but the window has not elapsed,
    # so these must be treated as transient (the boot race lasts seconds).
    waker, _ = _run_forever_waker(
        connect, client=client, auth_exit_threshold=2, auth_exit_window=300.0)
    waker.exec_command = _marker_cmd(marker)

    with pytest.raises(asyncio.CancelledError):
        await waker.run_forever()
    await waker.wait_for_idle()

    assert connect.attempts == 5  # 3 rejections + 1 success + 1 script-exhausted stop
    assert marker.read_text() == "x"  # startup sweep ran after the eventual success
    assert client.calls == 1


@pytest.mark.asyncio
async def test_persistent_auth_failure_exits_with_clear_error():
    """A genuinely bad token still fast-fails once rejections span the window."""
    connect = FakeConnect([FakeWS(auth_reply=AUTH_REJECTED) for _ in range(10)])
    waker, fake_time = _run_forever_waker(
        connect, auth_exit_threshold=3, auth_exit_window=10.0)

    with pytest.raises(WakerAuthError) as excinfo:
        await waker.run_forever()

    message = str(excinfo.value)
    assert "invalid token" in message
    assert "MCO_AGENT_TOKEN" in message
    # Exited as soon as both thresholds were met, not on the first rejection
    # and not after exhausting all 10 scripted connections.
    assert waker._auth_failures >= 3
    assert fake_time.now >= 10.0
    assert connect.outcomes  # gave up before draining the script


@pytest.mark.asyncio
async def test_successful_connect_resets_auth_failure_count():
    connect = FakeConnect([
        FakeWS(auth_reply=AUTH_REJECTED),
        FakeWS(auth_reply=AUTH_REJECTED),
        FakeWS(),  # success resets the consecutive-rejection counter
        FakeWS(auth_reply=AUTH_REJECTED),
        FakeWS(auth_reply=AUTH_REJECTED),
    ])
    # window=0 means the count alone decides; without the reset, the
    # 4 total rejections would exceed the threshold of 3 and exit.
    waker, _ = _run_forever_waker(connect, auth_exit_threshold=3, auth_exit_window=0.0)

    with pytest.raises(asyncio.CancelledError):
        await waker.run_forever()
    await waker.wait_for_idle()

    assert connect.attempts == 6
    assert waker._auth_failures == 2


@pytest.mark.asyncio
async def test_connection_errors_never_count_as_auth_failures():
    connect = FakeConnect([
        ConnectionRefusedError("gateway not listening yet"),
        OSError("network unreachable"),
        FakeWS(),
    ])
    # Even with the strictest possible policy, connection failures
    # (gateway down at boot) must retry rather than exit.
    waker, _ = _run_forever_waker(connect, auth_exit_threshold=1, auth_exit_window=0.0)

    with pytest.raises(asyncio.CancelledError):
        await waker.run_forever()
    await waker.wait_for_idle()

    assert connect.attempts == 4
    assert waker._auth_failures == 0
