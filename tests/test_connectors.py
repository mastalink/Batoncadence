"""Enterprise connector tests: ServiceNow, Dynatrace, sync engine, executor."""

import json

import httpx
import pytest

from mco.connectors.base import ConnectorError, make_connector_executor
from mco.connectors.dynatrace import DynatraceConnector
from mco.connectors.servicenow import ServiceNowConnector
from mco.connectors.sync import ingest_specs, normalize_webhook_event, sync_connector

from tests.test_routes import FakeDB


# ── Mock transports ───────────────────────────────────────────────────────────

def snow_transport(recorder):
    def handler(request: httpx.Request) -> httpx.Response:
        recorder.append(request)
        if request.method == "GET" and request.url.path == "/api/now/table/kb_knowledge":
            return httpx.Response(200, json={"result": [{
                "sys_id": "kb1", "number": "KB0007",
                "short_description": "Recovering checkout-service after retry storms",
                "text": "Roll back the payment client and enable the circuit breaker.",
            }]})
        if request.method == "GET" and request.url.path == "/api/now/table/incident":
            q = request.url.params.get("sysparm_query") or ""
            if q.startswith("123TEXTQUERY321="):
                # similar-incident search: resolved tickets with their fixes
                return httpx.Response(200, json={"result": [{
                    "sys_id": "old42", "number": "INC0042",
                    "short_description": "checkout-service error spike",
                    "close_code": "Solved (Permanently)",
                    "close_notes": "Rolled back payment client; added circuit breaker.",
                    "resolved_at": "2026-02-14 09:00:00",
                }]})
            return httpx.Response(200, json={"result": [{
                "sys_id": "abc123", "number": "INC0001",
                "short_description": "DB latency spike",
                "description": "Customers report slow queries.",
                "urgency": "1", "state": "1",
            }]})
        if request.method == "POST" and request.url.path == "/api/now/table/incident":
            return httpx.Response(201, json={"result": {"sys_id": "new789", "number": "INC0042"}})
        if request.method == "PATCH" and request.url.path.startswith("/api/now/table/incident/"):
            return httpx.Response(200, json={"result": {}})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def dt_transport(recorder):
    def handler(request: httpx.Request) -> httpx.Response:
        recorder.append(request)
        if request.method == "GET" and request.url.path == "/api/v2/problems":
            return httpx.Response(200, json={"problems": [{
                "problemId": "P-1", "displayId": "P-1", "title": "High CPU",
                "severityLevel": "PERFORMANCE", "impactLevel": "SERVICES",
                "impactedEntities": [{"name": "web-01"}],
            }]})
        if request.method == "POST" and "/comments" in request.url.path:
            return httpx.Response(201)
        if request.method == "POST" and request.url.path.endswith("/close"):
            return httpx.Response(200, json={})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def _snow(recorder=None):
    return ServiceNowConnector(
        instance_url="https://acme.service-now.com",
        username="bot", password="pw",
        transport=snow_transport(recorder if recorder is not None else []),
    )


def _dt(recorder=None):
    return DynatraceConnector(
        base_url="https://abc.live.dynatrace.com", api_token="dt0c01.token",
        transport=dt_transport(recorder if recorder is not None else []),
    )


# ── ServiceNow ────────────────────────────────────────────────────────────────

class TestServiceNow:
    def test_requires_credentials(self):
        with pytest.raises(ConnectorError):
            ServiceNowConnector(instance_url="https://x.service-now.com")

    def test_pull_events_normalizes_incidents(self):
        specs = _snow().pull_events()
        assert len(specs) == 1
        spec = specs[0]
        assert spec["external_id"] == "servicenow:abc123"
        assert "INC0001" in spec["title"]
        assert spec["input_payload"]["platform_ref"]["number"] == "INC0001"
        assert "prompt" in spec["input_payload"]

    def test_create_incident(self):
        res = _snow().execute_action("create_incident", {"short_description": "boom"})
        assert res == {"sys_id": "new789", "number": "INC0042"}

    def test_resolve_incident_requires_sys_id(self):
        with pytest.raises(ConnectorError, match="sys_id"):
            _snow().execute_action("resolve_incident", {})

    def test_unknown_action_rejected(self):
        with pytest.raises(ConnectorError, match="Unknown"):
            _snow().execute_action("launch_missiles", {})

    def test_escalate_opens_incident_with_context(self):
        recorder = []
        res = _snow(recorder).escalate(
            {"id": "j1", "title": "Flaky sync", "target_agent_role": "codex", "description": "orig"},
            "still broken",
        )
        assert res["number"] == "INC0042"
        body = json.loads(recorder[-1].content)
        assert "MCO escalation" in body["short_description"]
        assert "still broken" in body["description"]

    def test_bearer_token_auth_header(self):
        recorder = []
        conn = ServiceNowConnector(
            instance_url="https://acme.service-now.com", token="tok123",
            transport=snow_transport(recorder),
        )
        conn.health()
        assert recorder[0].headers["Authorization"] == "Bearer tok123"

    def test_health_ok(self):
        assert _snow().health()["ok"] is True

    def test_search_similar_incidents_returns_prior_fixes(self):
        recorder = []
        res = _snow(recorder).execute_action("search_similar_incidents",
                                             {"query": "checkout error rate"})
        match = res["matches"][0]
        assert match["number"] == "INC0042"
        assert "circuit breaker" in match["close_notes"]
        # full-text operator + closed/resolved filter actually sent
        q = recorder[-1].url.params["sysparm_query"]
        assert q.startswith("123TEXTQUERY321=checkout error rate")
        assert "stateIN6,7" in q

    def test_search_kb_returns_published_articles(self):
        recorder = []
        res = _snow(recorder).execute_action("search_kb", {"query": "checkout retry"})
        art = res["articles"][0]
        assert art["number"] == "KB0007"
        assert "circuit breaker" in art["text"]
        assert "workflow_state=published" in recorder[-1].url.params["sysparm_query"]

    def test_search_requires_query(self):
        with pytest.raises(ConnectorError, match="query"):
            _snow().execute_action("search_similar_incidents", {})


# ── Dynatrace ─────────────────────────────────────────────────────────────────

class TestDynatrace:
    def test_requires_credentials(self):
        with pytest.raises(ConnectorError):
            DynatraceConnector(base_url="", api_token="")

    def test_pull_events_normalizes_problems(self):
        specs = _dt().pull_events()
        assert len(specs) == 1
        spec = specs[0]
        assert spec["external_id"] == "dynatrace:P-1"
        assert "High CPU" in spec["title"]
        assert "web-01" in spec["description"]

    def test_add_comment_and_close(self):
        recorder = []
        conn = _dt(recorder)
        assert conn.execute_action("add_comment", {"problem_id": "P-1", "comment": "looking"})["commented"]
        assert conn.execute_action("close_problem", {"problem_id": "P-1"})["closed"]
        assert recorder[0].headers["Authorization"] == "Api-Token dt0c01.token"

    def test_health_ok(self):
        assert _dt().health()["ok"] is True


# ── Connector-as-worker executor ──────────────────────────────────────────────

class TestConnectorExecutor:
    @pytest.mark.asyncio
    async def test_executes_action_from_payload(self):
        executor = make_connector_executor(_snow())
        out, err = await executor(
            {"input_payload": {"action": "create_incident", "params": {"short_description": "x"}}}, "")
        assert err is None
        assert json.loads(out)["number"] == "INC0042"

    @pytest.mark.asyncio
    async def test_missing_action_fails(self):
        executor = make_connector_executor(_snow())
        out, err = await executor({"input_payload": {}}, "")
        assert out is None
        assert "missing input_payload.action" in err


# ── Sync engine ───────────────────────────────────────────────────────────────

class TestSyncEngine:
    def test_sync_creates_jobs_with_audit(self):
        db = FakeDB()
        summary = sync_connector(db, _snow())
        assert summary["pulled"] == 1
        assert len(summary["created"]) == 1
        job = list(db._jobs.values())[0]
        assert job["source_agent_id"] == "connector:servicenow"
        assert job["input_payload"]["external_id"] == "servicenow:abc123"
        assert any(e["event"] == "created" for e in db._events)

    def test_sync_is_idempotent_by_external_id(self):
        db = FakeDB()
        first = sync_connector(db, _snow())
        second = sync_connector(db, _snow())
        assert len(first["created"]) == 1
        assert len(second["created"]) == 0
        assert second["skipped"] == 1
        assert len(db._jobs) == 1


# ── Webhook normalization ─────────────────────────────────────────────────────

class TestWebhookNormalization:
    def test_dynatrace_problem_notification(self):
        spec = normalize_webhook_event("dynatrace", {
            "ProblemID": "P-9", "ProblemTitle": "Disk full",
            "ProblemDetailsText": "host-7 at 98%", "State": "OPEN",
        })
        assert spec["external_id"] == "dynatrace:P-9"
        assert "Disk full" in spec["title"]

    def test_servicenow_record(self):
        spec = normalize_webhook_event("servicenow", {
            "sys_id": "zzz", "number": "INC0099", "short_description": "VPN down",
        })
        assert spec["external_id"] == "servicenow:zzz"
        assert "INC0099" in spec["title"]

    def test_generic_contract(self):
        spec = normalize_webhook_event("pagerduty", {
            "id": "pd-1", "title": "Service degraded", "target_agent_role": "codex",
        })
        assert spec["external_id"] == "pagerduty:pd-1"
        assert spec["target_agent_role"] == "codex"

    def test_unusable_payload_returns_none(self):
        assert normalize_webhook_event("dynatrace", {"foo": "bar"}) is None
        assert normalize_webhook_event("generic", {"no_title": True}) is None

    def test_webhook_specs_flow_through_ingest(self):
        db = FakeDB()
        spec = normalize_webhook_event("servicenow", {"sys_id": "a1", "short_description": "x"})
        summary = ingest_specs(db, [spec], source="webhook:servicenow")
        assert len(summary["created"]) == 1
        assert list(db._jobs.values())[0]["source_agent_id"] == "webhook:servicenow"
