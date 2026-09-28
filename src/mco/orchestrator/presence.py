"""What each agent is actually doing: working, standby, broken, or offline.

`effective_status` only answers "heard from recently", from HTTP heartbeats. A
waker holding the broadcast socket never polls, so a Beast worker ready to take
work in seconds read "offline" - while one whose CLI rejected every job read
"online" on the last heartbeat it managed. Neither told the operator whether
work would get done.

`state` is derived at read time from what the gateway already knows, with no
schema change (so LocalStore and PostgreSQL behave the same):

  working  - holds a lease on a job right now
  broken   - reachable, but work addressed to it is not being taken: a job
             stalled past the delivery window, or jobs the delivery watchdog
             had to reroute away from it within the last hour
  standby  - reachable and nothing waiting on it: a live waker socket, or a
             fresh heartbeat
  offline  - none of the above (and `disabled` passes through)

`status`/`effective_status` stay "online"/"offline" for existing consumers; a
live waker socket now counts as online, because it is.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Optional

WORKING = "working"
STANDBY = "standby"
BROKEN = "broken"
OFFLINE = "offline"
DISABLED = "disabled"

BROKEN_WINDOW_SECONDS = 3600
_ACTIVE_JOB_STATUSES = ["leased", "in_progress"]
_NON_WORKER_ROLES = {"admin", "human", "operator", "owner", "approver"}

# Capacity and quota pause constants:
# Claude identities (Claude Beast / Claude Mac) are paused until Tuesday, September 29, 2026, 11:00 AM America/New_York.
CLAUDE_PAUSE_UNTIL = "2026-09-29T11:00:00-04:00"
CLAUDE_PAUSE_REASON = "Claude identities unavailable until 2026-09-29 11:00 America/New_York; no new Claude assignments"
CLAUDE_USAGE_OBSERVED_AT = "2026-09-27T15:15:00Z"
CLAUDE_EXCLUDED_INSTANCES = frozenset({"claude-beast", "claude-mac"})


def get_default_capacity_schedule() -> dict[str, dict[str, Any]]:
    """Deterministic default capacity pause schedule for known fleet identities."""
    return {
        inst: {
            "unavailable_until": CLAUDE_PAUSE_UNTIL,
            "reason": CLAUDE_PAUSE_REASON,
            "unavailable_reason": CLAUDE_PAUSE_REASON,
            "usage_observed_at": CLAUDE_USAGE_OBSERVED_AT,
        }
        for inst in CLAUDE_EXCLUDED_INSTANCES
    }


def is_agent_quota_eligible(
    row: dict,
    *,
    now: Optional[datetime] = None,
    capacity_schedule: Optional[dict] = None,
) -> bool:
    """Evaluate whether an agent identity currently has usable quota / capacity.
    
    Returns False if the agent is disabled or within an unexpired pause window
    (now < unavailable_until). On expiry (now >= unavailable_until), returns True
    (rechecks capacity on expiry).
    """
    if str(row.get("status") or "").lower() == DISABLED:
        return False

    cur_now = now or datetime.now(timezone.utc)
    instance = row.get("instance_id")

    unavail_val = row.get("unavailable_until")
    if unavail_val is None:
        sched = (capacity_schedule or get_default_capacity_schedule()).get(instance)
        if sched:
            unavail_val = sched.get("unavailable_until")

    if unavail_val:
        ts = _parse_ts(unavail_val)
        if ts is not None and cur_now < ts:
            return False

    return True


# Registered by the gateway process: returns instance ids holding an
# authenticated (non-admin) broadcast socket. None outside the gateway.
_connected_probe: Optional[Callable[[], set]] = None


def register_connected_probe(probe: Optional[Callable[[], set]]) -> None:
    global _connected_probe
    _connected_probe = probe


def connected_instances() -> Optional[set]:
    if _connected_probe is None:
        return None
    try:
        return set(_connected_probe())
    except Exception:
        return None


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _addressed_to(job: dict, row: dict) -> bool:
    target_id = job.get("target_agent_id")
    if target_id:
        return target_id == row.get("instance_id")
    return str(job.get("target_agent_role") or "").lower() == str(row.get("role") or "").lower()


def describe_fleet(
    db: Any,
    rows: Iterable[dict],
    *,
    threshold: int,
    connected: Optional[set] = None,
    stall_seconds: Optional[int] = None,
    now: Optional[datetime] = None,
    capacity_schedule: Optional[dict] = None,
) -> list[dict]:
    """Decorate registry rows (copies) with presence and `state`/`state_reason`.

    Store reads are best-effort: if jobs or events cannot be read, rows still
    get heartbeat/socket presence rather than failing the whole listing.
    """
    from mco.orchestrator.delivery import REROUTED, get_stall_seconds
    from mco.orchestrator.routes import decorate_presence

    now = now or datetime.now(timezone.utc)
    stall = get_stall_seconds() if stall_seconds is None else stall_seconds
    connected = connected if connected is not None else (connected_instances() or set())
    schedule = capacity_schedule if capacity_schedule is not None else get_default_capacity_schedule()

    try:
        active = db.table("agent_jobs").select("*").in_("status", _ACTIVE_JOB_STATUSES).execute().data or []
    except Exception:
        active = []
    try:
        pending = db.table("agent_jobs").select("*").eq("status", "pending").execute().data or []
    except Exception:
        pending = []
    try:
        since = (now - timedelta(seconds=BROKEN_WINDOW_SECONDS)).isoformat()
        reroutes = (db.table("agent_job_events").select("*").eq("event", REROUTED)
                    .gt("created_at", since).execute().data or [])
    except Exception:
        reroutes = []

    working = {job.get("leased_by_instance_id") for job in active if job.get("leased_by_instance_id")}
    rerouted_from: dict[str, int] = {}
    for event in reroutes:
        source = (event.get("detail") or {}).get("from_instance")
        if source:
            rerouted_from[source] = rerouted_from.get(source, 0) + 1

    stalled = []
    if stall and stall > 0:
        cutoff = now - timedelta(seconds=stall)
        stalled = [job for job in pending
                   if not job.get("archived")
                   and (ts := _parse_ts(job.get("created_at"))) is not None and ts <= cutoff]

    out = []
    for raw in rows:
        row = decorate_presence(dict(raw), threshold, now=now)
        instance = row.get("instance_id")
        live_socket = instance in connected
        if live_socket and row["effective_status"] == "offline" and raw.get("status") != DISABLED:
            row["effective_status"] = row["status"] = "online"
        row["connected"] = live_socket

        # Capacity & quota eligibility evaluation
        sched_entry = schedule.get(instance) or {}
        unavail_val = raw.get("unavailable_until")
        reason_val = raw.get("reason") or raw.get("unavailable_reason")
        usage_obs_val = raw.get("usage_observed_at")

        if unavail_val is None and sched_entry:
            unavail_val = sched_entry.get("unavailable_until")
        if reason_val is None and sched_entry:
            reason_val = sched_entry.get("reason") or sched_entry.get("unavailable_reason")
        if usage_obs_val is None and sched_entry:
            usage_obs_val = sched_entry.get("usage_observed_at")

        unavail_ts = _parse_ts(unavail_val)
        is_paused = bool(unavail_ts is not None and now < unavail_ts)
        quota_eligible = not is_paused and (raw.get("status") != DISABLED)

        row["unavailable_until"] = unavail_val
        row["reason"] = reason_val
        row["unavailable_reason"] = reason_val
        row["usage_observed_at"] = usage_obs_val
        row["quota_eligible"] = quota_eligible

        reason = None
        if raw.get("status") == DISABLED or row["effective_status"] == DISABLED:
            state = DISABLED
        elif instance in working:
            state = WORKING
        elif row["effective_status"] != "online":
            state = OFFLINE
        else:
            waiting = [job for job in stalled if _addressed_to(job, row)]
            moved = rerouted_from.get(instance, 0)
            if str(row.get("role") or "").lower() in _NON_WORKER_ROLES:
                state = STANDBY
            elif waiting or moved:
                state = BROKEN
                parts = []
                if waiting:
                    oldest = max(int((now - _parse_ts(j["created_at"])).total_seconds() // 60) for j in waiting)
                    parts.append(f"{len(waiting)} job(s) addressed to it untaken for up to {oldest} min")
                if moved:
                    parts.append(f"{moved} job(s) rerouted away in the last hour")
                reason = "; ".join(parts)
            else:
                state = STANDBY
        row["state"] = state
        row["state_reason"] = reason
        out.append(row)
    return out


def available_roles(described: Iterable[dict], org: str = "default", *, require_quota: bool = False) -> set:
    """Roles with at least one agent that can take new work now."""
    return {str(row.get("role") or "").lower() for row in described
            if (row.get("org_id") or "default") == org
            and row.get("state") in {STANDBY, WORKING}
            and (not require_quota or row.get("quota_eligible", True))}
