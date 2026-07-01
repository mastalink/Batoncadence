"""mco doctor / mco status / mco upgrade parity over HTTP (/api/doctor,
/api/migrations, /api/migrations/apply)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import mco.orchestrator.admin_routes as admin_mod
import mco.orchestrator.routes as routes_mod
from mco.localstore import LocalStore
from mco.orchestrator.admin_routes import status_router
from mco.orchestrator.auth import require_agent

from tests.test_admin_routes import ADMIN, WORKER, FakeConfig


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    db = LocalStore(tmp_path / "test.db")
    cfg = FakeConfig()
    monkeypatch.setattr(routes_mod, "get_db_client", lambda: db)
    monkeypatch.setattr(admin_mod, "get_config", lambda: cfg)

    app = FastAPI()
    app.include_router(status_router)
    app.dependency_overrides[require_agent] = lambda: ADMIN

    obj = type("Ctx", (), {})()
    obj.db, obj.cfg, obj.app = db, cfg, app
    obj.http = TestClient(app)
    yield obj
    db.close()


def _as(ctx, agent):
    ctx.app.dependency_overrides[require_agent] = lambda: agent


class TestDoctor:
    def test_returns_a_checks_list(self, ctx):
        resp = ctx.http.get("/api/doctor")
        assert resp.status_code == 200
        checks = resp.json()["checks"]
        assert isinstance(checks, list) and len(checks) > 0
        for c in checks:
            assert c["level"] in ("ok", "warn", "bad")
            assert c["label"]

    def test_reports_python_ok(self, ctx):
        checks = ctx.http.get("/api/doctor").json()["checks"]
        assert any(c["level"] == "ok" and "Python" in c["label"] for c in checks)

    def test_reports_database_reachable(self, ctx):
        checks = ctx.http.get("/api/doctor").json()["checks"]
        assert any("Database" in c["label"] and c["level"] == "ok" for c in checks)

    def test_worker_token_forbidden(self, ctx):
        _as(ctx, WORKER)
        assert ctx.http.get("/api/doctor").status_code == 403


class TestMigrationsStatus:
    def test_local_backend_needs_no_migrations(self, ctx):
        # ctx's db is already a LocalStore -> backend_kind() sees "local"
        body = ctx.http.get("/api/migrations").json()
        assert body["backend_kind"] == "local"
        assert body["pending"] == []
        assert body["can_apply"] is False

    def test_no_database_configured(self, ctx, monkeypatch):
        monkeypatch.setattr(routes_mod, "get_db_client", lambda: None)
        body = ctx.http.get("/api/migrations").json()
        assert body["backend_kind"] == "none"

    def test_worker_token_forbidden(self, ctx):
        _as(ctx, WORKER)
        assert ctx.http.get("/api/migrations").status_code == 403


class TestMigrationsApply:
    def test_rejected_on_local_backend(self, ctx):
        resp = ctx.http.post("/api/migrations/apply")
        assert resp.status_code == 400

    def test_rejected_without_database_url(self, ctx, monkeypatch):
        import mco.migrations_runner as mig
        monkeypatch.setattr(mig, "backend_kind", lambda: "postgres")
        resp = ctx.http.post("/api/migrations/apply")
        assert resp.status_code == 400
        assert "DATABASE_URL" in resp.json()["detail"]

    def test_applies_when_configured(self, ctx, monkeypatch):
        import mco.migrations_runner as mig
        monkeypatch.setattr(mig, "backend_kind", lambda: "postgres")
        monkeypatch.setattr(mig, "apply_postgres",
                            lambda url: {"applied": ["001_x.sql"], "driver": "psycopg"})
        ctx.cfg.values["DATABASE_URL"] = "postgres://x"
        resp = ctx.http.post("/api/migrations/apply")
        assert resp.status_code == 200
        assert resp.json()["applied"] == ["001_x.sql"]

    def test_worker_token_forbidden(self, ctx):
        _as(ctx, WORKER)
        assert ctx.http.post("/api/migrations/apply").status_code == 403
