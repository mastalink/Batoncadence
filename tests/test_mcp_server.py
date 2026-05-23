"""Tests for the MCO MCP server tools — verify delegation to GatewayClient."""

import mco.mcp_server as mcp_mod
from mco.mcp_server import (
    mco_agents,
    mco_complete,
    mco_fail,
    mco_inbox,
    mco_lease,
    mco_send,
)


# ── Fake GatewayClient ────────────────────────────────────────────────────────

class FakeGatewayClient:
    """Records every call made through MCP tool delegation."""

    def __init__(self, **responses):
        self.calls: list = []
        self._responses = responses

    def inbox(self):
        self.calls.append(("inbox",))
        return self._responses.get("inbox", [])

    def lease(self, task_id: str):
        self.calls.append(("lease", task_id))
        return self._responses.get("lease", {"success": True})

    def complete(self, task_id: str, output: str):
        self.calls.append(("complete", task_id, output))
        return self._responses.get("complete", {"success": True})

    def fail(self, task_id: str, error: str):
        self.calls.append(("fail", task_id, error))
        return self._responses.get("fail", {"success": True})

    def send(self, to_role: str, title: str, instructions: str, to_instance=None):
        self.calls.append(("send", to_role, title, instructions, to_instance))
        return self._responses.get("send", {"success": True})

    def agents(self):
        self.calls.append(("agents",))
        return self._responses.get("agents", [])


def _fake(monkeypatch, **responses) -> FakeGatewayClient:
    client = FakeGatewayClient(**responses)
    monkeypatch.setattr(mcp_mod, "_client", lambda: client)
    return client


# ── Tool delegation tests ─────────────────────────────────────────────────────

def test_mco_inbox_delegates_and_returns_payload(monkeypatch):
    jobs = [{"id": "j1", "title": "do thing", "input_payload": {"prompt": "do X"}}]
    fake = _fake(monkeypatch, inbox=jobs)
    result = mco_inbox()
    assert result == jobs
    assert fake.calls == [("inbox",)]

def test_mco_inbox_preserves_input_payload_shape(monkeypatch):
    jobs = [{"id": "j1", "input_payload": {"prompt": "run tests"}, "status": "pending"}]
    fake = _fake(monkeypatch, inbox=jobs)
    result = mco_inbox()
    assert result[0]["input_payload"]["prompt"] == "run tests"

def test_mco_lease_delegates_task_id(monkeypatch):
    fake = _fake(monkeypatch, lease={"success": True})
    result = mco_lease("task-123")
    assert result == {"success": True}
    assert fake.calls == [("lease", "task-123")]

def test_mco_complete_delegates_task_and_output(monkeypatch):
    fake = _fake(monkeypatch, complete={"success": True})
    result = mco_complete("task-456", "all done")
    assert result == {"success": True}
    assert fake.calls == [("complete", "task-456", "all done")]

def test_mco_fail_delegates_task_and_error(monkeypatch):
    fake = _fake(monkeypatch, fail={"success": True})
    result = mco_fail("task-789", "something broke")
    assert result == {"success": True}
    assert fake.calls == [("fail", "task-789", "something broke")]

def test_mco_send_blank_to_instance_coerced_to_none(monkeypatch):
    fake = _fake(monkeypatch)
    mco_send("claude", "Review PR", "Please look at this", to_instance="")
    _, to_role, title, instructions, to_instance = fake.calls[0]
    assert to_role == "claude"
    assert title == "Review PR"
    assert instructions == "Please look at this"
    assert to_instance is None

def test_mco_send_explicit_instance_preserved(monkeypatch):
    fake = _fake(monkeypatch)
    mco_send("codex", "Fix bug", "Here is the issue", to_instance="coding-beast-codex")
    _, _, _, _, to_instance = fake.calls[0]
    assert to_instance == "coding-beast-codex"

def test_mco_send_no_instance_arg_passes_none(monkeypatch):
    fake = _fake(monkeypatch)
    mco_send("gemini", "Analyze", "Instructions here")
    _, _, _, _, to_instance = fake.calls[0]
    assert to_instance is None

def test_mco_agents_delegates_and_returns_list(monkeypatch):
    agents = [{"instance_id": "a1", "role": "codex", "status": "online"}]
    fake = _fake(monkeypatch, agents=agents)
    result = mco_agents()
    assert result == agents
    assert fake.calls == [("agents",)]

def test_each_tool_call_builds_a_fresh_client(monkeypatch):
    """_client() is called once per tool invocation (no shared HTTP state)."""
    call_count = 0

    def counting_factory():
        nonlocal call_count
        call_count += 1
        return FakeGatewayClient()

    monkeypatch.setattr(mcp_mod, "_client", counting_factory)
    mco_inbox()
    mco_agents()
    assert call_count == 2
