"""
Immutable audit trail for the Job Board.

Every job mutation (create, lease, status change, approval decision, retry,
escalation) is recorded as an append-only row in `agent_job_events`. The table
is protected by a database trigger that rejects UPDATE/DELETE (see
docs/migrations/), so the trail is tamper-evident: rows can only ever be added.

Audit writes must never break the orchestration path - failures are logged and
swallowed.
"""

import logging
from typing import Any, Optional

logger = logging.getLogger("mco.orchestrator.audit")

EVENTS_TABLE = "agent_job_events"


def record_event(
    db_client: Any,
    job_id: str,
    event: str,
    actor_id: Optional[str] = None,
    actor_role: Optional[str] = None,
    detail: Optional[dict] = None,
) -> bool:
    """Append one event to the immutable audit trail. Never raises."""
    if db_client is None or not job_id:
        return False
    try:
        db_client.table(EVENTS_TABLE).insert({
            "job_id": str(job_id),
            "event": event,
            "actor_id": actor_id,
            "actor_role": actor_role,
            "detail": detail or {},
        }).execute()
        return True
    except Exception as e:
        logger.warning(f"Audit write skipped for job {job_id} ({event}): {e}")
        return False


def get_events(db_client: Any, job_id: str) -> list:
    """Return the full audit trail for a job, oldest first."""
    if db_client is None:
        return []
    try:
        res = (
            db_client.table(EVENTS_TABLE)
            .select("*")
            .eq("job_id", str(job_id))
            .order("created_at", desc=False)
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.error(f"Error fetching audit events for job {job_id}: {e}")
        return []
