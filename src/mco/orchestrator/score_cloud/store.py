"""C1 — Score store interface with in-memory and SQLite fakes.

Parity helpers replay simple event sequences. No live Postgres connection
strings or hosts appear here; a future PostgresScoreStore stays out of scope
for this offline packet.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


class ScoreStoreError(ValueError):
    """Store contract violation or immutable-event breach."""


@dataclass(frozen=True)
class ScoreRunRecord:
    run_id: str
    org_id: str
    score_id: str
    score_digest: str
    status: str
    definition: Mapping[str, Any]


@dataclass(frozen=True)
class ScoreEventRecord:
    seq: int
    run_id: str
    event_type: str
    detail: Mapping[str, Any]


@dataclass(frozen=True)
class ScoreTaskRecord:
    run_id: str
    task_id: str
    status: str
    attempt: int
    detail: Mapping[str, Any]


class ScoreStore(ABC):
    """One interface for Appliance SQLite and (later) Postgres Score stores."""

    @abstractmethod
    def create_run(self, record: ScoreRunRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_run(self, run_id: str) -> ScoreRunRecord | None:
        raise NotImplementedError

    @abstractmethod
    def upsert_task(self, record: ScoreTaskRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_task(self, run_id: str, task_id: str) -> ScoreTaskRecord | None:
        raise NotImplementedError

    @abstractmethod
    def append_event(self, run_id: str, event_type: str, detail: Mapping[str, Any]) -> ScoreEventRecord:
        raise NotImplementedError

    @abstractmethod
    def list_events(self, run_id: str) -> Sequence[ScoreEventRecord]:
        raise NotImplementedError

    @abstractmethod
    def transition_task(
        self,
        run_id: str,
        task_id: str,
        *,
        status: str,
        attempt: int | None = None,
        detail: Mapping[str, Any] | None = None,
        event_type: str,
        event_detail: Mapping[str, Any] | None = None,
    ) -> ScoreEventRecord:
        """Atomically update task state and append one event (plan+outbox shape)."""
        raise NotImplementedError


def _freeze(mapping: Mapping[str, Any] | None) -> dict[str, Any]:
    return json.loads(json.dumps(dict(mapping or {}), sort_keys=True))


class InMemoryScoreStore(ScoreStore):
    """Thread-safe in-memory fake for unit tests."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._runs: dict[str, ScoreRunRecord] = {}
        self._tasks: dict[tuple[str, str], ScoreTaskRecord] = {}
        self._events: list[ScoreEventRecord] = []
        self._seq = 0

    def create_run(self, record: ScoreRunRecord) -> None:
        with self._lock:
            if record.run_id in self._runs:
                raise ScoreStoreError("run_already_exists")
            self._runs[record.run_id] = ScoreRunRecord(
                run_id=record.run_id,
                org_id=record.org_id,
                score_id=record.score_id,
                score_digest=record.score_digest,
                status=record.status,
                definition=_freeze(record.definition),
            )

    def get_run(self, run_id: str) -> ScoreRunRecord | None:
        with self._lock:
            return self._runs.get(run_id)

    def upsert_task(self, record: ScoreTaskRecord) -> None:
        with self._lock:
            if record.run_id not in self._runs:
                raise ScoreStoreError("run_missing")
            self._tasks[(record.run_id, record.task_id)] = ScoreTaskRecord(
                run_id=record.run_id,
                task_id=record.task_id,
                status=record.status,
                attempt=record.attempt,
                detail=_freeze(record.detail),
            )

    def get_task(self, run_id: str, task_id: str) -> ScoreTaskRecord | None:
        with self._lock:
            return self._tasks.get((run_id, task_id))

    def append_event(self, run_id: str, event_type: str, detail: Mapping[str, Any]) -> ScoreEventRecord:
        with self._lock:
            if run_id not in self._runs:
                raise ScoreStoreError("run_missing")
            self._seq += 1
            event = ScoreEventRecord(
                seq=self._seq,
                run_id=run_id,
                event_type=event_type,
                detail=_freeze(detail),
            )
            self._events.append(event)
            return event

    def list_events(self, run_id: str) -> Sequence[ScoreEventRecord]:
        with self._lock:
            return tuple(e for e in self._events if e.run_id == run_id)

    def transition_task(
        self,
        run_id: str,
        task_id: str,
        *,
        status: str,
        attempt: int | None = None,
        detail: Mapping[str, Any] | None = None,
        event_type: str,
        event_detail: Mapping[str, Any] | None = None,
    ) -> ScoreEventRecord:
        with self._lock:
            existing = self._tasks.get((run_id, task_id))
            next_attempt = attempt if attempt is not None else (existing.attempt if existing else 0)
            next_detail = _freeze(detail if detail is not None else (existing.detail if existing else {}))
            self.upsert_task(
                ScoreTaskRecord(
                    run_id=run_id,
                    task_id=task_id,
                    status=status,
                    attempt=next_attempt,
                    detail=next_detail,
                )
            )
            return self.append_event(run_id, event_type, event_detail or {"task_id": task_id, "status": status})


_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS score_runs (
  run_id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL,
  score_id TEXT NOT NULL,
  score_digest TEXT NOT NULL,
  status TEXT NOT NULL,
  definition TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS score_tasks (
  run_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  status TEXT NOT NULL,
  attempt INTEGER NOT NULL,
  detail TEXT NOT NULL,
  PRIMARY KEY (run_id, task_id),
  FOREIGN KEY (run_id) REFERENCES score_runs(run_id)
);
CREATE TABLE IF NOT EXISTS score_events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  detail TEXT NOT NULL,
  FOREIGN KEY (run_id) REFERENCES score_runs(run_id)
);
CREATE TRIGGER IF NOT EXISTS score_events_no_update
BEFORE UPDATE ON score_events
BEGIN
  SELECT RAISE(ABORT, 'score_events are append-only');
END;
CREATE TRIGGER IF NOT EXISTS score_events_no_delete
BEFORE DELETE ON score_events
BEGIN
  SELECT RAISE(ABORT, 'score_events are append-only');
END;
"""


class SqliteScoreStore(ScoreStore):
    """SQLite fake implementing ScoreStore (Appliance-shaped, unit-test safe)."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = str(path) if path is not None else ":memory:"
        # One shared connection for :memory: so schema survives across calls;
        # file-backed uses check_same_thread=False with a lock.
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SQLITE_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def create_run(self, record: ScoreRunRecord) -> None:
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO score_runs(run_id, org_id, score_id, score_digest, status, definition) VALUES (?,?,?,?,?,?)",
                    (
                        record.run_id,
                        record.org_id,
                        record.score_id,
                        record.score_digest,
                        record.status,
                        json.dumps(_freeze(record.definition), sort_keys=True),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ScoreStoreError("run_already_exists") from exc

    def get_run(self, run_id: str) -> ScoreRunRecord | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM score_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                return None
            return ScoreRunRecord(
                run_id=row["run_id"],
                org_id=row["org_id"],
                score_id=row["score_id"],
                score_digest=row["score_digest"],
                status=row["status"],
                definition=json.loads(row["definition"]),
            )

    def upsert_task(self, record: ScoreTaskRecord) -> None:
        with self._lock:
            if self.get_run(record.run_id) is None:
                raise ScoreStoreError("run_missing")
            self._conn.execute(
                """
                INSERT INTO score_tasks(run_id, task_id, status, attempt, detail)
                VALUES (?,?,?,?,?)
                ON CONFLICT(run_id, task_id) DO UPDATE SET
                  status=excluded.status,
                  attempt=excluded.attempt,
                  detail=excluded.detail
                """,
                (
                    record.run_id,
                    record.task_id,
                    record.status,
                    record.attempt,
                    json.dumps(_freeze(record.detail), sort_keys=True),
                ),
            )

    def get_task(self, run_id: str, task_id: str) -> ScoreTaskRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM score_tasks WHERE run_id=? AND task_id=?",
                (run_id, task_id),
            ).fetchone()
            if row is None:
                return None
            return ScoreTaskRecord(
                run_id=row["run_id"],
                task_id=row["task_id"],
                status=row["status"],
                attempt=row["attempt"],
                detail=json.loads(row["detail"]),
            )

    def append_event(self, run_id: str, event_type: str, detail: Mapping[str, Any]) -> ScoreEventRecord:
        with self._lock:
            if self.get_run(run_id) is None:
                raise ScoreStoreError("run_missing")
            cur = self._conn.execute(
                "INSERT INTO score_events(run_id, event_type, detail) VALUES (?,?,?)",
                (run_id, event_type, json.dumps(_freeze(detail), sort_keys=True)),
            )
            seq = int(cur.lastrowid)
            return ScoreEventRecord(seq=seq, run_id=run_id, event_type=event_type, detail=_freeze(detail))

    def list_events(self, run_id: str) -> Sequence[ScoreEventRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT seq, run_id, event_type, detail FROM score_events WHERE run_id=? ORDER BY seq",
                (run_id,),
            ).fetchall()
            return tuple(
                ScoreEventRecord(
                    seq=row["seq"],
                    run_id=row["run_id"],
                    event_type=row["event_type"],
                    detail=json.loads(row["detail"]),
                )
                for row in rows
            )

    def transition_task(
        self,
        run_id: str,
        task_id: str,
        *,
        status: str,
        attempt: int | None = None,
        detail: Mapping[str, Any] | None = None,
        event_type: str,
        event_detail: Mapping[str, Any] | None = None,
    ) -> ScoreEventRecord:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                existing = self.get_task(run_id, task_id)
                next_attempt = attempt if attempt is not None else (existing.attempt if existing else 0)
                next_detail = _freeze(detail if detail is not None else (existing.detail if existing else {}))
                self.upsert_task(
                    ScoreTaskRecord(
                        run_id=run_id,
                        task_id=task_id,
                        status=status,
                        attempt=next_attempt,
                        detail=next_detail,
                    )
                )
                event = self.append_event(
                    run_id,
                    event_type,
                    event_detail or {"task_id": task_id, "status": status},
                )
                self._conn.execute("COMMIT")
                return event
            except Exception:
                self._conn.execute("ROLLBACK")
                raise


def score_store_parity_events(
    stores: Iterable[ScoreStore],
    *,
    run_id: str = "parity-run",
    org_id: str = "org-demo",
    score_id: str = "demo-canary",
    score_digest: str = "digest-demo",
) -> list[list[tuple[str, Mapping[str, Any]]]]:
    """Replay a simple canary-like event sequence on each store; return comparable traces.

    Trace entries are (event_type, detail) in append order — enough to prove
    Memory and SQLite fakes produce identical sequences without Postgres.
    """
    traces: list[list[tuple[str, Mapping[str, Any]]]] = []
    for store in stores:
        store.create_run(
            ScoreRunRecord(
                run_id=run_id,
                org_id=org_id,
                score_id=score_id,
                score_digest=score_digest,
                status="open",
                definition={"id": score_id, "revision": 1},
            )
        )
        store.transition_task(
            run_id,
            "build",
            status="running",
            attempt=1,
            detail={"lane": "local:builder"},
            event_type="task_started",
            event_detail={"task_id": "build", "attempt": 1},
        )
        store.transition_task(
            run_id,
            "build",
            status="awaiting_review",
            attempt=1,
            detail={"lane": "local:builder", "artifact": "sha-demo"},
            event_type="task_finished",
            event_detail={"task_id": "build", "artifact": "sha-demo"},
        )
        store.transition_task(
            run_id,
            "build",
            status="accepted",
            attempt=1,
            detail={"lane": "local:builder", "artifact": "sha-demo", "reviewer": "reviewer"},
            event_type="task_accepted",
            event_detail={"task_id": "build", "reviewer": "reviewer"},
        )
        store.transition_task(
            run_id,
            "launch",
            status="blocked",
            attempt=0,
            detail={"reason": "human_checkpoint"},
            event_type="task_blocked",
            event_detail={"task_id": "launch", "reason": "human_checkpoint"},
        )
        traces.append([(e.event_type, dict(e.detail)) for e in store.list_events(run_id)])
    return traces
