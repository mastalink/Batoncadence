"""Regression coverage for LocalStore contention freezing the ASGI loop."""

import asyncio
import hashlib
import json
import time

import httpx
import pytest

from mco.localstore import LocalStore
import mco.orchestrator.routes as routes_mod


class ProductionSizedStore(LocalStore):
    """Models the observed whole-board JSON decode while keeping the test bounded."""

    def _load_rows(self, table):
        if table == "agent_jobs":
            time.sleep(0.6)
        return super()._load_rows(table)


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
    store.close()
