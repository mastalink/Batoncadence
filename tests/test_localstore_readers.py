import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from mco.localstore import LocalStore


def test_same_store_reader_sees_only_committed_state_and_audit_during_writer(tmp_path):
    store = LocalStore(tmp_path / "snapshots.db")
    store.table("agent_jobs").insert({"id": "job", "status": "pending"}).execute()
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with store.transaction():
                store.table("agent_jobs").update({"status": "completed"}).eq("id", "job").execute()
                # The writer itself must retain read-your-writes semantics.
                assert store.table("agent_jobs").select("*").execute().data[0]["status"] == "completed"
                def read():
                    return (store.table("agent_jobs").select("*").execute().data,
                            store.table("mco_audit_outbox").select("*").execute().data)
                future = pool.submit(read)
                rows, events = future.result(timeout=1)
                assert rows[0]["status"] == "pending"
                assert len(events) == 1
            rows, events = pool.submit(read).result(timeout=1)
            assert rows[0]["status"] == "completed"
            assert len(events) == 2
        def broken_outbox(table, row):
            if table == "mco_audit_outbox":
                raise RuntimeError("outbox failed")
            original(table, row)
        original = store._write_row
        store._write_row = broken_outbox
        with pytest.raises(RuntimeError, match="outbox failed"):
            store.table("agent_jobs").update({"status": "pending"}).eq("id", "job").execute()
        assert store.table("agent_jobs").select("*").execute().data[0]["status"] == "completed"
        assert len(store.table("mco_audit_outbox").select("*").execute().data) == 2
    finally:
        store.close()


def test_readers_are_thread_local_read_only_and_close_with_store(tmp_path):
    store = LocalStore(tmp_path / "readers.db")
    gate = threading.Barrier(4)
    def read():
        conn = store._read_connection()
        gate.wait(timeout=2)
        assert store._read_connection() is conn
        assert store.table("never_created").select("*").execute().data == []
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("CREATE TABLE forbidden (id TEXT)")
        return conn
    with ThreadPoolExecutor(max_workers=4) as pool:
        readers = list(pool.map(lambda _: read(), range(4)))
    assert len({id(conn) for conn in readers}) == 4
    assert store._conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    store.close()
    for conn in readers:
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")
