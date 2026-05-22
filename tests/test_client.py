"""Functional tests for the gateway HTTP client using httpx.MockTransport (no extra deps)."""

import json

import httpx

from mco.orchestrator.client import GatewayClient

BASE = "http://127.0.0.1:18789"


class Recorder:
    def __init__(self):
        self.requests = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/api/jobs/pending":
            return httpx.Response(200, json=[{"id": "j1", "title": "do thing"}])
        if path == "/api/jobs/lease":
            return httpx.Response(200, json={"success": True})
        if path.startswith("/api/jobs/") and request.method == "PUT":
            return httpx.Response(200, json={"success": True})
        if path == "/api/jobs" and request.method == "POST":
            return httpx.Response(200, json={"success": True, "job": {"id": "j2"}})
        if path == "/api/agents":
            return httpx.Response(200, json=[{"instance_id": "coding-beast-codex", "role": "codex", "status": "online"}])
        return httpx.Response(404, json={})

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]


def _client(rec):
    return GatewayClient(
        base_url=BASE, token="tok123", role="codex", instance_id="coding-beast-codex",
        transport=httpx.MockTransport(rec.handler),
    )


def test_inbox_sends_bearer_and_filters():
    rec = Recorder()
    jobs = _client(rec).inbox()
    assert jobs == [{"id": "j1", "title": "do thing"}]
    assert rec.last.headers["authorization"] == "Bearer tok123"
    assert rec.last.url.params["role"] == "codex"
    assert rec.last.url.params["instance_id"] == "coding-beast-codex"


def test_lease_posts_self_as_instance():
    rec = Recorder()
    assert _client(rec).lease("j1") == {"success": True}
    body = json.loads(rec.last.content)
    assert body == {"task_id": "j1", "agent_instance_id": "coding-beast-codex"}


def test_complete_and_fail_put_status():
    rec = Recorder()
    c = _client(rec)
    c.complete("j1", "all good")
    body = json.loads(rec.last.content)
    assert body["status"] == "completed"
    assert body["output_payload"] == {"result": "all good"}
    c.fail("j1", "boom")
    body2 = json.loads(rec.last.content)
    assert body2["status"] == "failed"
    assert body2["error_message"] == "boom"


def test_send_drops_mail_to_target():
    rec = Recorder()
    res = _client(rec).send("claude", "Review PR", "Please review the diff", to_instance="coding-beast-claude")
    assert res["success"] is True
    body = json.loads(rec.last.content)
    assert body["target_agent_role"] == "claude"
    assert body["target_agent_id"] == "coding-beast-claude"
    assert body["title"] == "Review PR"
    assert body["input_payload"]["prompt"] == "Please review the diff"


def test_agents_lists():
    rec = Recorder()
    agents = _client(rec).agents()
    assert agents[0]["role"] == "codex"
