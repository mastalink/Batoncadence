"""Regression coverage for LocalStore contention freezing the ASGI loop."""

import asyncio
import hashlib
import json
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from mco.localstore import LocalStore
import mco.orchestrator.routes as routes_mod


class ProductionSizedStore(LocalStore):
    """Models a contended board select while keeping the test bounded."""

    def _select_rows(self, query):
        if query._table == "agent_jobs":
            time.sleep(0.1)
        return super()._select_rows(query)


class ObservableStore(LocalStore):
    """Expose when WebSocket authentication reaches its registry lookup."""

    def __init__(self, path):
        super().__init__(path)
        self.registry_select_started = threading.Event()

    def _run_once(self, query):
        if query._table == "agent_registry" and query._op == "select":
            self.registry_select_started.set()
        return super()._run_once(query)


def _seed_jobs(store: LocalStore, count: int = 1_000) -> None:
    rows = []
    for index in range(count):
        job = {
            "id": f"job-{index:04d}",
            "title": f"Production-sized job {index}",
            "status": "pending",
            "source_agent_id": "load-test",
            "source_agent_role": "codex",
            "target_agent_role": "codex",
            "created_at": f"2026-10-04T12:{index // 60:02d}:{index % 60:02d}+00:00",
            "org_id": "default",
            "input_payload": {"prompt": "x" * 512},
        }
        rows.append((job["id"], json.dumps(job)))
    with store.transaction():
        store._ensure_table("agent_jobs")
        store._conn.executemany('INSERT INTO agent_jobs(pk, data) VALUES (?, ?)', rows)


@pytest.mark.asyncio
async def test_parallel_job_lists_keep_health_and_authenticated_api_responsive(tmp_path, monkeypatch):
    store = ProductionSizedStore(tmp_path / "load.db")
    token = "gateway-load-token"
    store.table("agent_registry").insert({
        "instance_id": "load-test",
        "role": "admin",
        "status": "online",
        "auth_token_hash": hashlib.sha256(token.encode()).hexdigest(),
    }).execute()
    _seed_jobs(store)
    monkeypatch.setattr(routes_mod, "get_db_client", lambda force_new=False: store)

    from mco.cli import create_app

    auth = {"Authorization": f"Bearer {token}"}
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        started = time.perf_counter()
        board_tasks = [asyncio.create_task(client.get("/api/jobs", headers=auth)) for _ in range(6)]
        health_task = asyncio.create_task(client.get("/healthz"))
        agents_task = asyncio.create_task(client.get("/api/agents", headers=auth))

        health = await health_task
        health_elapsed = time.perf_counter() - started
        agents = await agents_task
        agents_elapsed = time.perf_counter() - started
        boards = await asyncio.gather(*board_tasks)
        boards_elapsed = time.perf_counter() - started

    print(
        "gateway-load-timing "
        f"health={health_elapsed:.3f}s agents={agents_elapsed:.3f}s boards={boards_elapsed:.3f}s"
    )
    assert health.status_code == 200
    assert agents.status_code == 200
    assert all(response.status_code == 200 for response in boards)
    assert health_elapsed < 3.0
    assert agents_elapsed < 3.0
    assert boards_elapsed >= 0.5
    store.close()


def test_websocket_authentication_does_not_block_health_while_store_is_locked(tmp_path, monkeypatch):
    store = ObservableStore(tmp_path / "websocket-lock.db")
    token = "websocket-lock-token"
    store.table("agent_registry").insert({
        "instance_id": "websocket-lock-test",
        "role": "codex",
        "status": "offline",
        "auth_token_hash": hashlib.sha256(token.encode()).hexdigest(),
    }).execute()
    monkeypatch.setattr(routes_mod, "get_db_client", lambda force_new=False: store)

    lock_held = threading.Event()
    health_started = threading.Event()

    def hold_store_lock():
        with store._lock:
            lock_held.set()
            assert health_started.wait(timeout=2.0)
            time.sleep(0.6)

    holder = threading.Thread(target=hold_store_lock)
    holder.start()
    assert lock_held.wait(timeout=2.0)

    websocket_result = {}

    def authenticate(client):
        with client.websocket_connect("/ws/broadcast") as websocket:
            websocket.send_json({
                "type": "authenticate",
                "payload": {"instance_id": "websocket-lock-test", "token": token},
            })
            websocket_result.update(websocket.receive_json())

    try:
        from mco.cli import create_app

        with TestClient(create_app()) as client:
            socket_thread = threading.Thread(target=authenticate, args=(client,))
            socket_thread.start()
            assert store.registry_select_started.wait(timeout=2.0)

            health_started.set()
            started = time.perf_counter()
            health = client.get("/healthz")
            elapsed = time.perf_counter() - started

            socket_thread.join(timeout=2.0)
            assert not socket_thread.is_alive()
    finally:
        health_started.set()
        holder.join(timeout=2.0)
        store.close()

    assert health.status_code == 200
    assert elapsed < 0.3
    assert websocket_result == {"type": "authenticated", "payload": {"success": True}}
