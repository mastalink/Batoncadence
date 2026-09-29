"""E / C1 — Fake Score store interface + Memory/SQLite parity (unit only)."""

from __future__ import annotations

import sqlite3

import pytest

from mco.orchestrator.score_cloud.store import (
    InMemoryScoreStore,
    ScoreRunRecord,
    ScoreStoreError,
    ScoreTaskRecord,
    SqliteScoreStore,
    score_store_parity_events,
)


def _run(run_id: str = "run-1") -> ScoreRunRecord:
    return ScoreRunRecord(
        run_id=run_id,
        org_id="org-demo",
        score_id="demo",
        score_digest="digest-1",
        status="open",
        definition={"id": "demo", "revision": 1},
    )


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        yield InMemoryScoreStore()
        return
    path = tmp_path / "score-fake.db"
    s = SqliteScoreStore(path)
    try:
        yield s
    finally:
        s.close()


def test_create_get_run_and_reject_duplicate(store):
    store.create_run(_run())
    got = store.get_run("run-1")
    assert got is not None
    assert got.score_digest == "digest-1"
    assert got.definition["id"] == "demo"
    with pytest.raises(ScoreStoreError, match="run_already_exists"):
        store.create_run(_run())


def test_append_only_events_and_task_transition(store):
    store.create_run(_run())
    store.upsert_task(
        ScoreTaskRecord("run-1", "build", "ready", 0, {"lane": "local:builder"})
    )
    event = store.transition_task(
        "run-1",
        "build",
        status="running",
        attempt=1,
        detail={"lane": "local:builder"},
        event_type="task_started",
        event_detail={"task_id": "build", "attempt": 1},
    )
    assert event.seq >= 1
    assert event.event_type == "task_started"
    task = store.get_task("run-1", "build")
    assert task is not None and task.status == "running" and task.attempt == 1
    events = store.list_events("run-1")
    assert [e.event_type for e in events] == ["task_started"]


def test_missing_run_fails_closed(store):
    with pytest.raises(ScoreStoreError, match="run_missing"):
        store.append_event("missing", "noop", {})
    with pytest.raises(ScoreStoreError, match="run_missing"):
        store.upsert_task(ScoreTaskRecord("missing", "t", "ready", 0, {}))


def test_sqlite_events_are_append_only(tmp_path):
    path = tmp_path / "append.db"
    store = SqliteScoreStore(path)
    try:
        store.create_run(_run())
        store.append_event("run-1", "task_started", {"task_id": "build"})
        with pytest.raises(sqlite3.IntegrityError):
            store._conn.execute("UPDATE score_events SET event_type='tamper' WHERE seq=1")
        with pytest.raises(sqlite3.IntegrityError):
            store._conn.execute("DELETE FROM score_events WHERE seq=1")
    finally:
        store.close()


def test_memory_sqlite_parity_identical_event_sequences(tmp_path):
    memory = InMemoryScoreStore()
    sqlite = SqliteScoreStore(tmp_path / "parity.db")
    try:
        traces = score_store_parity_events([memory, sqlite], run_id="parity-run")
        assert len(traces) == 2
        assert traces[0] == traces[1]
        assert [t[0] for t in traces[0]] == [
            "task_started",
            "task_finished",
            "task_accepted",
            "task_blocked",
        ]
        # No Postgres DSN / host literals in the module source.
        from pathlib import Path

        src = Path(__file__).parents[1] / "src/mco/orchestrator/score_cloud/store.py"
        text = src.read_text(encoding="utf-8")
        for banned in ("postgres://", "postgresql://", "supabase.co", "rds.amazonaws"):
            assert banned not in text.lower()
    finally:
        sqlite.close()


def test_interface_names_exported():
    from mco.orchestrator import score_cloud as pkg

    assert pkg.ScoreStore is not None
    assert pkg.SqliteScoreStore is not None
    assert pkg.InMemoryScoreStore is not None
    assert callable(pkg.score_store_parity_events)
