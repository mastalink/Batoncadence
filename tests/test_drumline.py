"""Drumline shared-context tests: remember/recall, distillation, routes, injection."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import mco.notifiers.ntfy as ntfy_mod
import mco.orchestrator.routes as routes_mod
from mco.orchestrator.auth import require_agent
from mco.orchestrator.context_routes import context_router
from mco.orchestrator.drumline import (
    distill_job,
    recall,
    remember,
    render_context_block,
)
from mco.orchestrator.routes import router as jobs_router

from tests.test_routes import FakeDB

AGENT = {"instance_id": "agent-1", "role": "codex", "status": "online"}


@pytest.fixture(autouse=True)
def _no_outbound_ntfy(monkeypatch):
    monkeypatch.setattr(ntfy_mod, "notify", lambda *a, **k: True)


# ── Core: remember / recall ───────────────────────────────────────────────────

class TestRememberRecall:
    def test_remember_stores_normalized_entry(self):
        db = FakeDB()
        entry = remember(db, title="Prod DB is read-only on Sundays",
                         content="Maintenance window 02:00-06:00 UTC.",
                         kind="fact", tags=["Postgres", " ops "], created_by="joe")
        assert entry["tags"] == ["postgres", "ops"]
        assert entry["kind"] == "fact"
        assert entry["created_by"] == "joe"

    def test_invalid_kind_coerced_to_fact(self):
        db = FakeDB()
        entry = remember(db, title="t", content="c", kind="gossip")
        assert entry["kind"] == "fact"

    def test_recall_matches_query_terms(self):
        db = FakeDB()
        remember(db, title="Dynatrace token rotated", content="New scope problems.write", tags=["dynatrace"])
        remember(db, title="Office wifi password", content="Ask reception")
        hits = recall(db, query="dynatrace problems token")
        assert len(hits) == 1
        assert "Dynatrace" in hits[0]["title"]

    def test_recall_without_query_returns_freshest(self):
        db = FakeDB()
        for i in range(8):
            remember(db, title=f"note {i}", content=f"body {i}")
        hits = recall(db, limit=3)
        assert len(hits) == 3
        assert hits[0]["title"] == "note 7"  # newest first

    def test_recall_tag_filter_is_hard(self):
        db = FakeDB()
        remember(db, title="release checklist", content="steps...", tags=["release"])
        remember(db, title="release party", content="cake", tags=["social"])
        hits = recall(db, query="release", tags=["release"])
        assert [h["title"] for h in hits] == ["release checklist"]

    def test_role_affinity_boosts_matching_role(self):
        db = FakeDB()
        remember(db, title="codex build flags", content="use -O2", role="claude")
        remember(db, title="codex build flags", content="use -O2", role="codex")
        hits = recall(db, query="codex build flags", role="codex", limit=1)
        assert hits[0]["role"] == "codex"

    def test_recall_empty_db_safe(self):
        assert recall(FakeDB(), query="anything") == []


# ── Distillation ──────────────────────────────────────────────────────────────

class TestDistillation:
    def test_completed_job_distills_prompt_and_outcome(self):
        db = FakeDB()
        entry = distill_job(db, {
            "id": "j1", "title": "Triage P-99",
            "target_agent_role": "claude", "source_agent_role": "connector",
            "leased_by_instance_id": "claude-worker-1",
            "input_payload": {"prompt": "Investigate high CPU on web-01", "connector": "dynatrace"},
            "output_payload": {"result": "Root cause: runaway cron. Disabled job foo."},
        })
        assert entry["kind"] == "handoff"
        assert entry["source_job_id"] == "j1"
        assert "runaway cron" in entry["content"]
        assert "dynatrace" in entry["tags"]
        assert entry["created_by"] == "claude-worker-1"

    def test_job_without_output_is_not_distilled(self):
        assert distill_job(FakeDB(), {"id": "j2", "title": "x", "output_payload": {}}) is None

    def test_distilled_entry_is_recallable(self):
        db = FakeDB()
        distill_job(db, {
            "id": "j3", "title": "Fix VPN flapping",
            "target_agent_role": "codex",
            "input_payload": {"prompt": "VPN drops every 10m"},
            "output_payload": {"result": "MTU mismatch; set 1400 on tun0."},
        })
        hits = recall(db, query="VPN MTU")
        assert hits and "MTU mismatch" in hits[0]["content"]


# ── Rendering / injection ─────────────────────────────────────────────────────

class TestRendering:
    def test_block_contains_entries_and_markers(self):
        block = render_context_block([
            {"kind": "lesson", "title": "Never deploy Fridays", "content": "Seriously.",
             "created_by": "joe", "created_at": "2026-06-01T00:00:00Z"},
        ])
        assert block.startswith("=== SHARED CONTEXT (Drumline) ===")
        assert block.rstrip().endswith("=== END SHARED CONTEXT ===")
        assert "[lesson] Never deploy Fridays (joe, 2026-06-01)" in block
        assert "Seriously." in block

    def test_empty_entries_render_nothing(self):
        assert render_context_block([]) == ""


# ── Routes + end-to-end loop ──────────────────────────────────────────────────

class TestContextRoutes:
    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        self.db = FakeDB()
        monkeypatch.setattr(routes_mod, "get_db_client", lambda: self.db)
        app = FastAPI()
        app.include_router(jobs_router)
        app.include_router(context_router)
        app.dependency_overrides[require_agent] = lambda: AGENT
        self.http = TestClient(app)

    def test_remember_endpoint_stamps_caller(self):
        resp = self.http.post("/api/context", json={"title": "t", "content": "c", "kind": "decision"})
        assert resp.status_code == 200
        assert resp.json()["entry"]["created_by"] == "agent-1"

    def test_remember_requires_title_and_content(self):
        assert self.http.post("/api/context", json={"title": "t"}).status_code == 400

    def test_recall_endpoint_with_query_and_tags(self):
        self.http.post("/api/context", json={"title": "supabase keys rotated",
                                             "content": "new anon key in vault", "tags": ["supabase"]})
        resp = self.http.get("/api/context", params={"query": "supabase vault", "tags": "supabase"})
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_completed_job_flows_into_shared_context(self):
        """The full loop: job completes -> distilled into Drumline -> recallable,
        with a context_distilled audit event."""
        self.db.add_job(id="loop1", title="Patch nginx CVE", status="in_progress",
                        target_agent_role="codex",
                        input_payload={"prompt": "patch CVE-2026-1234"})
        resp = self.http.put("/api/jobs/loop1", json={
            "status": "completed",
            "output_payload": {"result": "Upgraded nginx to 1.27.5 across fleet."},
        })
        assert resp.status_code == 200
        hits = self.http.get("/api/context", params={"query": "nginx CVE"}).json()
        assert hits and "1.27.5" in hits[0]["content"]
        events = [e["event"] for e in self.db._events if e["job_id"] == "loop1"]
        assert "context_distilled" in events
