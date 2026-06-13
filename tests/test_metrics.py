"""Prometheus /metrics endpoint: exposition shape, auth, empty-DB safety."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import mco.orchestrator.metrics_routes as metrics_mod
import mco.orchestrator.routes as routes_mod
from mco.orchestrator.metrics_routes import metrics_router, render_metrics

from tests.test_routes import FakeDB


class FakeConfig:
    def __init__(self, **values):
        self._values = values

    def get(self, key, default=None):
        return self._values.get(key, default)


@pytest.fixture
def client(monkeypatch):
    db = FakeDB()
    db.add_job(id="j1", title="a", status="pending", target_agent_role="codex")
    db.add_job(id="j2", title="b", status="needs_approval", target_agent_role="codex")
    db.add_job(id="j3", title="c", status="completed", target_agent_role="codex")
    db.add_agent("w1", "codex", "tok", status="online")  # last_seen 2026-01-01 = stale
    monkeypatch.setattr(routes_mod, "get_db_client", lambda: db)
    monkeypatch.setattr(metrics_mod, "get_config", lambda: FakeConfig())
    app = FastAPI()
    app.include_router(metrics_router)
    return TestClient(app)


def test_exposition_format_and_content_type(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    body = resp.text
    assert "# HELP mco_up" in body and "# TYPE mco_up gauge" in body
    assert "mco_up 1" in body
    assert 'mco_build_info{version=' in body


def test_job_status_gauges(client):
    body = client.get("/metrics").text
    assert 'mco_jobs{status="pending"} 1' in body
    assert 'mco_jobs{status="needs_approval"} 1' in body
    assert 'mco_jobs{status="completed"} 1' in body
    assert 'mco_jobs{status="failed"} 0' in body          # always emitted, even at zero
    assert "mco_approval_queue_depth 1" in body


def test_presence_gauges_use_derived_status(client):
    body = client.get("/metrics").text
    assert "mco_agents_registered 1" in body
    assert "mco_agents_online 0" in body                   # stale online agent -> offline


def test_kill_switch_reflected(client, monkeypatch):
    monkeypatch.setattr(routes_mod, "get_config",
                        lambda: FakeConfig(MCO_KILL_SWITCH="true"))
    assert "mco_kill_switch 1" in client.get("/metrics").text


def test_token_required_when_configured(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(routes_mod, "get_db_client", lambda: db)
    monkeypatch.setattr(metrics_mod, "get_config",
                        lambda: FakeConfig(MCO_METRICS_TOKEN="s3cret"))
    app = FastAPI()
    app.include_router(metrics_router)
    http = TestClient(app)
    assert http.get("/metrics").status_code == 401
    assert http.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert http.get("/metrics", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_no_database_is_safe(monkeypatch):
    monkeypatch.setattr(routes_mod, "get_db_client", lambda: None)
    monkeypatch.setattr(metrics_mod, "get_config", lambda: FakeConfig())
    body = render_metrics()
    assert "mco_database_up 0" in body
    assert "mco_up 1" in body
