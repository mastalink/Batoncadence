import hashlib
import json
import threading
import time

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from mco.localstore import LocalStore
from mco.orchestrator import auth, routes
from mco.request_timing import SlowRequestMiddleware


def test_slow_log_attributes_authenticated_caller_and_writer_wait_without_tokens(tmp_path, monkeypatch):
    store = LocalStore(tmp_path / "timing.db")
    token = "must-never-appear-in-log"
    store.table("agent_registry").insert({
        "instance_id": "codex-mac", "role": "admin", "status": "online",
        "auth_token_hash": hashlib.sha256(token.encode()).hexdigest(),
    }).execute()
    monkeypatch.setattr(routes, "get_db_client", lambda force_new=False: store)
    path = tmp_path / "gateway-slow.log"
    app = FastAPI()
    app.add_middleware(SlowRequestMiddleware, log_path=path, threshold_ms=20)
    started = threading.Event()
    lock_held = threading.Event()
    @app.post("/slow/{job_id}")
    def slow(agent=Depends(auth.require_agent)):
        started.set()
        return store.table("agent_jobs").insert({"id": "logged", "title": "write"}).execute().data
    @app.get("/fast")
    def fast():
        return {}
    def hold():
        with store.transaction():
            lock_held.set()
            assert started.wait(timeout=3)
            time.sleep(0.08)
    holder = threading.Thread(target=hold)
    holder.start()
    assert lock_held.wait(timeout=3)
    try:
        with TestClient(app) as client:
            response = client.post(f"/slow/{token}?token={token}", headers={"Authorization": f"Bearer {token}"})
            assert response.status_code == 200
            client.get("/fast")
        holder.join(timeout=3)
        assert not holder.is_alive()
        records = [json.loads(line) for line in path.read_text().splitlines()]
        assert len(records) == 1
        assert records[0]["instance_id"] == "codex-mac"
        assert records[0]["method"] == "POST"
        assert records[0]["path"] == "/slow/{job_id}"
        assert records[0]["lock_wait_ms"] >= 50
        assert records[0]["total_ms"] >= records[0]["lock_wait_ms"]
        assert token not in path.read_text()
    finally:
        started.set()
        holder.join(timeout=3)
        store.close()
