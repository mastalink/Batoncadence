"""Tests for capacity scheduling, unavailable-until/reason/usage-observed-at,
resolver exclusion, and lease eligibility enforcement.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import pytest

from mco.localstore import LocalStore
from mco.orchestrator import leases, presence
from mco.orchestrator.leases import acquire_lease, renew_lease, fenced_update, Lease
from mco.orchestrator.presence import (
    BROKEN,
    DISABLED,
    OFFLINE,
    STANDBY,
    WORKING,
    CLAUDE_PAUSE_UNTIL,
    CLAUDE_PAUSE_REASON,
    CLAUDE_USAGE_OBSERVED_AT,
    describe_fleet,
    is_agent_quota_eligible,
)
from mco.orchestrator.routes import _pending_for_agent
from mco.orchestrator.score_resolver import resolve_score_targets


NY_TZ = ZoneInfo("America/New_York")
THRESHOLD = 300
STALL = 600

# Snapshot time during review: Sunday Sep 27, 2026 ~15:15 UTC
DURING_PAUSE_NOW = datetime(2026, 9, 27, 19, 0, 0, tzinfo=timezone.utc)
# After Tuesday Sep 29, 2026 11:00 AM EDT (15:00 UTC)
AFTER_PAUSE_NOW = datetime(2026, 9, 29, 11, 30, 0, tzinfo=NY_TZ)


@pytest.fixture
def db(tmp_path):
    s = LocalStore(tmp_path / "capacity_test.db")
    yield s
    s.close()


def _agent(instance, role, *, seen_seconds_ago=10, status="online", org_id="default", ref_time=None, **kwargs):
    now_ref = ref_time or DURING_PAUSE_NOW
    row = {
        "instance_id": instance,
        "role": role,
        "status": status,
        "org_id": org_id,
        "last_seen_at": (
            None
            if seen_seconds_ago is None
            else (now_ref - timedelta(seconds=seen_seconds_ago)).isoformat()
        ),
    }
    row.update(kwargs)
    return row


def _job(db, job_id, *, status="pending", role="claude", target=None, leased_by=None, ref_time=None):
    now_ref = ref_time or datetime.now(timezone.utc)
    db.table("agent_jobs").insert({
        "id": job_id,
        "title": job_id,
        "status": status,
        "target_agent_role": role,
        "target_agent_id": target,
        "leased_by_instance_id": leased_by,
        "created_at": now_ref.isoformat(),
        "started_at": now_ref.isoformat() if leased_by else None,
        "lease_epoch": 1 if leased_by else 0,
        "lease_id": "existing-lease-id" if leased_by else None,
        "lease_incarnation": leases.store_incarnation(db),
        "lease_expires_at": (now_ref + timedelta(seconds=3600)).isoformat() if leased_by else None,
    }).execute()


def make_score(roles=None):
    roles = roles or [("claude", "grok")]
    tasks = []
    for i, (work_role, rev_role) in enumerate(roles):
        tasks.append(dict(
            id=f"task_{i+1}",
            goal=f"G0{i+1}",
            title=f"Task {i+1}",
            instructions="Execute capacity-governed work",
            role=work_role,
            review_role=rev_role,
            depends_on=[f"task_{i}"] if i > 0 else [],
            resources=[f"res_{i+1}"],
            capabilities=["cloud:inspect"],
            evidence=["report"],
            max_attempts=1,
            timeout_seconds=300,
            max_cost_cents=0,
            checkpoint=None,
        ))
    return dict(
        score_version=1,
        id="test-capacity-score",
        revision=1,
        objective="Capacity test",
        constraints=["Zero spend"],
        budget_cents=0,
        max_parallel=1,
        tasks=tasks,
        launch_requires=["task_1"],
    )


def test_presence_decorates_capacity_fields(db):
    custom_until = "2026-09-30T12:00:00Z"
    custom_reason = "API budget capped for billing cycle"
    custom_observed = "2026-09-27T18:00:00Z"

    agent_data = _agent(
        "worker-paused",
        "custom",
        unavailable_until=custom_until,
        reason=custom_reason,
        usage_observed_at=custom_observed,
    )

    described = describe_fleet(db, [agent_data], threshold=THRESHOLD, now=DURING_PAUSE_NOW)
    assert len(described) == 1
    row = described[0]

    assert row["unavailable_until"] == custom_until
    assert row["reason"] == custom_reason
    assert row["unavailable_reason"] == custom_reason
    assert row["usage_observed_at"] == custom_observed
    assert row["quota_eligible"] is False


def test_claude_beast_and_mac_default_pause_schedule(db):
    agents = [
        _agent("claude-beast", "claude"),
        _agent("claude-mac", "claude"),
        _agent("codex-beast", "codex"),
    ]

    described = {r["instance_id"]: r for r in describe_fleet(db, agents, threshold=THRESHOLD, now=DURING_PAUSE_NOW)}

    cb = described["claude-beast"]
    cm = described["claude-mac"]
    cx = described["codex-beast"]

    # Claude Beast & Mac are paused
    assert cb["quota_eligible"] is False
    assert cb["unavailable_until"] == CLAUDE_PAUSE_UNTIL
    assert "Tuesday" in cb["reason"] or "2026-09-29" in cb["reason"]
    assert cb["usage_observed_at"] == CLAUDE_USAGE_OBSERVED_AT

    assert cm["quota_eligible"] is False
    assert cm["unavailable_until"] == CLAUDE_PAUSE_UNTIL
    assert cm["usage_observed_at"] == CLAUDE_USAGE_OBSERVED_AT

    # Codex Beast is not paused
    assert cx["quota_eligible"] is True
    assert cx["unavailable_until"] is None


def test_ui_distinguishes_connected_from_quota_eligible(db):
    # claude-mac holds a live broadcast socket: connected is True, but quota_eligible is False
    agents = [_agent("claude-mac", "claude")]
    described = describe_fleet(
        db, agents, threshold=THRESHOLD, connected={"claude-mac"}, now=DURING_PAUSE_NOW
    )
    row = described[0]

    assert row["connected"] is True
    assert row["effective_status"] == "online"
    assert row["quota_eligible"] is False
    assert row["state"] == STANDBY


def test_capacity_recheck_on_expiry(db):
    agents = [
        _agent("claude-beast", "claude", ref_time=AFTER_PAUSE_NOW),
        _agent("claude-mac", "claude", ref_time=AFTER_PAUSE_NOW),
    ]

    # After Tuesday 11:00 AM EDT, capacity recheck allows them
    described = describe_fleet(db, agents, threshold=THRESHOLD, now=AFTER_PAUSE_NOW)
    for row in described:
        assert row["quota_eligible"] is True


def test_active_lease_preserved_during_pause(db):
    # claude-beast holds an active lease on j-active (using real-time for lease expiry)
    _job(db, "j-active", status="in_progress", role="claude", leased_by="claude-beast")

    described = describe_fleet(db, [_agent("claude-beast", "claude")], threshold=THRESHOLD, now=DURING_PAUSE_NOW)
    row = described[0]

    # Active lease maintains WORKING state even while quota_eligible is False
    assert row["state"] == WORKING
    assert row["quota_eligible"] is False

    # Existing lease can be renewed
    claim = Lease("j-active", "existing-lease-id", 1, leases.store_incarnation(db), "claude-beast")
    assert renew_lease(db, claim, ttl_seconds=1800) is True

    # Existing lease can complete
    res = fenced_update(
        db,
        "j-active",
        claim.as_claim(),
        {"status": "completed", "output_payload": {"ready": True}},
    )
    assert res["status"] == "completed"


def test_acquire_lease_enforces_capacity_and_quota_eligibility(db):
    db.table("agent_registry").insert(_agent("claude-beast", "claude")).execute()
    db.table("agent_registry").insert(_agent("codex-beast", "codex")).execute()

    _job(db, "j-new-1", status="pending", role="claude")
    _job(db, "j-new-2", status="pending", role="codex")

    # Claude Beast cannot acquire a new lease during pause
    lease_cb = acquire_lease(db, "j-new-1", "claude-beast", now=DURING_PAUSE_NOW)
    assert lease_cb is None

    # Codex Beast can acquire a lease
    lease_cx = acquire_lease(db, "j-new-2", "codex-beast", now=DURING_PAUSE_NOW)
    assert lease_cx is not None
    assert lease_cx.owner == "codex-beast"

    # After expiry, Claude Beast can acquire a lease
    lease_cb_after = acquire_lease(db, "j-new-1", "claude-beast", now=AFTER_PAUSE_NOW)
    assert lease_cb_after is not None
    assert lease_cb_after.owner == "claude-beast"


def test_score_resolver_excludes_claude_during_pause(db):
    score = make_score([("claude", "grok")])

    db.table("agent_registry").insert(_agent("claude-beast", "claude", ref_time=DURING_PAUSE_NOW)).execute()
    db.table("agent_registry").insert(_agent("claude-mac", "claude", ref_time=DURING_PAUSE_NOW)).execute()
    db.table("agent_registry").insert(_agent("grok-beast", "grok", ref_time=DURING_PAUSE_NOW)).execute()

    targets = resolve_score_targets(score, org_id="default", db_client=db, now=DURING_PAUSE_NOW)

    # Claude identities excluded from role targets
    assert targets["claude"] == []
    assert targets["grok"] == ["grok-beast"]


def test_score_resolver_admits_eligible_alternative_during_claude_pause(db):
    score = make_score([("claude", "grok")])

    # claude-beast is paused by default
    db.table("agent_registry").insert(_agent("claude-beast", "claude", ref_time=DURING_PAUSE_NOW)).execute()
    # claude-unpaused has an explicitly expired unavailable_until
    db.table("agent_registry").insert(_agent(
        "claude-backup",
        "claude",
        ref_time=DURING_PAUSE_NOW,
        unavailable_until="2026-09-20T00:00:00Z",
    )).execute()
    db.table("agent_registry").insert(_agent("grok-beast", "grok", ref_time=DURING_PAUSE_NOW)).execute()

    targets = resolve_score_targets(score, org_id="default", db_client=db, now=DURING_PAUSE_NOW)

    # Only the eligible alternative is assigned
    assert targets["claude"] == ["claude-backup"]


def test_score_resolver_rechecks_and_admits_claude_after_expiry(db):
    score = make_score([("claude", "grok")])

    db.table("agent_registry").insert(_agent("claude-beast", "claude", ref_time=AFTER_PAUSE_NOW)).execute()
    db.table("agent_registry").insert(_agent("claude-mac", "claude", ref_time=AFTER_PAUSE_NOW)).execute()
    db.table("agent_registry").insert(_agent("grok-beast", "grok", ref_time=AFTER_PAUSE_NOW)).execute()

    targets = resolve_score_targets(score, org_id="default", db_client=db, now=AFTER_PAUSE_NOW)

    assert targets["claude"] == ["claude-beast", "claude-mac"]
    assert targets["grok"] == ["grok-beast"]


def test_pending_inbox_empty_for_paused_worker(db):
    db.table("agent_registry").insert(_agent("claude-beast", "claude", ref_time=datetime.now(timezone.utc))).execute()
    _job(db, "j-claude", status="pending", role="claude", target="claude-beast")

    agent_dict = {"instance_id": "claude-beast", "role": "claude", "org_id": "default"}

    # Paused worker polling inbox receives empty list
    jobs = _pending_for_agent(db, "claude", "claude-beast", agent_dict)
    assert jobs == []
