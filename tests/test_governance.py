"""Phase A governance tests: approval gates, immutable audit trail, escalation."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import mco.notifiers.ntfy as ntfy_mod
import mco.orchestrator.routes as routes_mod
from mco.orchestrator.auth import require_agent
from mco.orchestrator.routes import router, agents_router

from tests.test_routes import FakeDB


CODEX_AGENT = {"instance_id": "agent-1", "role": "codex", "status": "online"}
HUMAN_AGENT = {"instance_id": "joe", "role": "human", "status": "online"}


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.include_router(agents_router)
    return app


@pytest.fixture(autouse=True)
def _no_outbound_ntfy(monkeypatch):
    """Keep tests offline: ntfy pushes become no-ops."""
    monkeypatch.setattr(ntfy_mod, "notify", lambda *a, **k: True)


class _GovernanceBase:
    agent = CODEX_AGENT

    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        self.db = FakeDB()
        monkeypatch.setattr(routes_mod, "get_db_client", lambda: self.db)
        self.app = _build_app()
        self.app.dependency_overrides[require_agent] = lambda: self.agent
        self.http = TestClient(self.app)

    def _as(self, agent):
        self.app.dependency_overrides[require_agent] = lambda: agent


class TestApprovalGates(_GovernanceBase):
    def test_create_with_requires_approval_pauses_at_gate(self):
        resp = self.http.post("/api/jobs", json={
            "title": "Risky deploy",
            "target_agent_role": "codex",
            "requires_approval": True,
        })
        assert resp.status_code == 200
        assert resp.json()["job"]["status"] == "needs_approval"

    def test_create_with_deps_and_approval_starts_waiting(self):
        self.db.add_job(id="dep-1", status="pending", target_agent_role="codex")
        resp = self.http.post("/api/jobs", json={
            "title": "Gated downstream",
            "target_agent_role": "codex",
            "requires_approval": True,
            "depends_on": ["dep-1"],
        })
        assert resp.json()["job"]["status"] == "waiting"

    def _gated_job(self) -> str:
        return self.db.add_job(
            id="gated-1", title="Gated", status="needs_approval",
            target_agent_role="codex", requires_approval=True,
        )

    def test_approver_role_can_approve(self):
        job_id = self._gated_job()
        self._as(HUMAN_AGENT)
        resp = self.http.post(f"/api/jobs/{job_id}/approve")
        assert resp.status_code == 200
        job = resp.json()["job"]
        assert job["status"] == "pending"
        assert job["approved_by"] == "joe"

    def test_non_approver_role_gets_403(self):
        job_id = self._gated_job()
        resp = self.http.post(f"/api/jobs/{job_id}/approve")
        assert resp.status_code == 403

    def test_reject_is_terminal_with_reason(self):
        job_id = self._gated_job()
        self._as(HUMAN_AGENT)
        resp = self.http.post(f"/api/jobs/{job_id}/reject", json={"reason": "too risky"})
        assert resp.status_code == 200
        job = resp.json()["job"]
        assert job["status"] == "rejected"
        assert "too risky" in job["error_message"]

    def test_approve_non_gated_job_is_400(self):
        self.db.add_job(id="plain-1", status="pending", target_agent_role="codex")
        self._as(HUMAN_AGENT)
        resp = self.http.post("/api/jobs/plain-1/approve")
        assert resp.status_code == 400

    def test_approve_unknown_job_is_404(self):
        self._as(HUMAN_AGENT)
        resp = self.http.post("/api/jobs/no-such-job/approve")
        assert resp.status_code == 404

    def test_custom_approver_roles_config(self, monkeypatch):
        monkeypatch.setattr(routes_mod, "get_approver_roles", lambda: {"codex"})
        job_id = self._gated_job()
        resp = self.http.post(f"/api/jobs/{job_id}/approve")
        assert resp.status_code == 200


class TestAuditTrail(_GovernanceBase):
    def _events(self, job_id):
        resp = self.http.get(f"/api/jobs/{job_id}/events")
        assert resp.status_code == 200
        return [e["event"] for e in resp.json()]

    def test_create_is_audited(self):
        resp = self.http.post("/api/jobs", json={"title": "x", "target_agent_role": "codex"})
        job_id = resp.json()["job"]["id"]
        assert "created" in self._events(job_id)

    def test_lease_is_audited(self):
        self.db.add_job(id="jl1", status="pending", target_agent_role="codex")
        self.db.set_rpc(True)
        self.http.post("/api/jobs/lease", json={"task_id": "jl1", "agent_instance_id": "agent-1"})
        assert "leased" in self._events("jl1")

    def test_status_change_is_audited_with_actor(self):
        self.db.add_job(id="ju1", status="in_progress", target_agent_role="codex")
        self.http.put("/api/jobs/ju1", json={"status": "completed"})
        events = self.http.get("/api/jobs/ju1/events").json()
        assert any(e["event"] == "status:completed" and e["actor_id"] == "agent-1" for e in events)

    def test_approval_decision_is_audited(self):
        self.db.add_job(id="ga1", status="needs_approval", target_agent_role="codex")
        self._as(HUMAN_AGENT)
        self.http.post("/api/jobs/ga1/approve")
        assert "approved" in self._events("ga1")


class TestEscalation(_GovernanceBase):
    def test_failed_job_with_retry_budget_is_requeued(self):
        self.db.add_job(id="rt1", status="in_progress", target_agent_role="codex",
                        max_retries=2, retry_count=0, leased_by_instance_id="agent-1")
        self.http.put("/api/jobs/rt1", json={"status": "failed", "error_message": "boom"})
        job = self.db._jobs["rt1"]
        assert job["status"] == "pending"
        assert job["retry_count"] == 1
        assert job["leased_by_instance_id"] is None
        events = [e["event"] for e in self.db._events if e["job_id"] == "rt1"]
        assert "retried" in events

    def test_exhausted_retries_escalates_to_role(self):
        self.db.add_job(id="es1", title="Flaky task", status="in_progress",
                        target_agent_role="codex", max_retries=1, retry_count=1,
                        escalate_to_role="human", description="orig instructions")
        self.http.put("/api/jobs/es1", json={"status": "failed", "error_message": "still broken"})
        assert self.db._jobs["es1"]["status"] == "failed"
        escalations = [j for j in self.db._jobs.values()
                       if j.get("target_agent_role") == "human" and "ESCALATION" in (j.get("title") or "")]
        assert len(escalations) == 1
        assert "still broken" in escalations[0]["description"]
        assert escalations[0]["input_payload"]["escalated_from"] == "es1"
        events = [e["event"] for e in self.db._events if e["job_id"] == "es1"]
        assert "escalated" in events

    def test_failed_job_without_policy_stays_failed(self):
        self.db.add_job(id="pl1", status="in_progress", target_agent_role="codex")
        self.http.put("/api/jobs/pl1", json={"status": "failed", "error_message": "x"})
        assert self.db._jobs["pl1"]["status"] == "failed"
        assert len(self.db._jobs) == 1

    def test_dependency_unlock_respects_approval_gate(self):
        self.db.add_job(id="up1", status="in_progress", target_agent_role="codex")
        self.db.add_job(id="dn1", status="waiting", target_agent_role="claude",
                        depends_on=["up1"], requires_approval=True)
        self.db.add_job(id="dn2", status="waiting", target_agent_role="claude",
                        depends_on=["up1"])
        self.http.put("/api/jobs/up1", json={"status": "completed"})
        assert self.db._jobs["dn1"]["status"] == "needs_approval"
        assert self.db._jobs["dn2"]["status"] == "pending"
