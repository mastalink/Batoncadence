import hashlib
from datetime import datetime, timezone

from mco.localstore import LocalStore
from mco.orchestrator import presence, routes


def test_fleet_evidence_cached_for_five_seconds_and_explicit_time_bypasses(tmp_path, monkeypatch):
    from mco.orchestrator import fleet_cache
    clock = [10.0]
    monkeypatch.setattr(fleet_cache, "monotonic", lambda: clock[0])
    store = LocalStore(tmp_path / "evidence.db")
    agent = {"instance_id": "worker", "role": "codex", "status": "online"}
    describe = lambda **kwargs: presence.describe_fleet(store, [agent], threshold=300, connected={"worker"}, **kwargs)[0]
    try:
        assert describe()["state"] == "standby"
        store.table("agent_jobs").insert({"id": "leased", "status": "leased", "leased_by_instance_id": "worker"}).execute()
        assert describe()["state"] == "standby"
        assert describe(now=datetime.now(timezone.utc))["state"] == "working"
        clock[0] += 5.01
        assert describe()["state"] == "working"
    finally:
        store.close()


def test_api_agents_cache_is_tenant_safe_and_returns_copies(tmp_path, monkeypatch):
    from mco.orchestrator import fleet_cache
    clock = [10.0]
    monkeypatch.setattr(fleet_cache, "monotonic", lambda: clock[0])
    store = LocalStore(tmp_path / "agents.db")
    monkeypatch.setattr(routes, "get_db_client", lambda force_new=False: store)
    try:
        for org in ("default", "tenant-a", "tenant-b"):
            store.table("agent_registry").insert({
                "instance_id": org, "role": "admin", "org_id": org, "status": "online",
                "auth_token_hash": hashlib.sha256(org.encode()).hexdigest(),
            }).execute()
        first = routes.get_agents({"org_id": "default"})
        assert len(first) == 3
        first[0]["instance_id"] = "mutated"
        assert routes.get_agents({"org_id": "tenant-a"})[0]["instance_id"] == "tenant-a"
        assert routes.get_agents({"org_id": "tenant-b"})[0]["instance_id"] == "tenant-b"
        store.table("agent_registry").insert({"instance_id": "new", "role": "codex"}).execute()
        assert len(routes.get_agents({"org_id": "default"})) == 3
        clock[0] += 5.01
        refreshed = routes.get_agents({"org_id": "default"})
        assert len(refreshed) == 4
        assert all("auth_token_hash" not in row for row in refreshed)
    finally:
        store.close()


def test_concurrent_refreshes_coalesce_and_transaction_does_not_poison_cache(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    import time
    from mco.orchestrator.fleet_cache import cached_fleet

    store = LocalStore(tmp_path / "coalescing.db")
    calls = []
    gate = threading.Barrier(8)
    def load():
        calls.append(1)
        time.sleep(0.02)
        return [{"value": "committed"}]
    def get():
        gate.wait(timeout=3)
        return cached_fleet(store, "test", None, load)
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: get(), range(8)))
        assert len(calls) == 1
        assert all(row == [{"value": "committed"}] for row in results)
        with store.transaction():
            assert cached_fleet(store, "test", None, lambda: [{"value": "uncommitted"}]) == [{"value": "uncommitted"}]
        assert cached_fleet(store, "test", None, load) == [{"value": "committed"}]
    finally:
        store.close()
