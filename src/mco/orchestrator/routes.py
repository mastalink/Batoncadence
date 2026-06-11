"""FastAPI routes for the Job Board API, serving GET and POST requests."""

import os
import logging
from fastapi import APIRouter, HTTPException, Depends
from mco.orchestrator.contracts import JobStatus
from mco.orchestrator.auth import require_agent
from mco.orchestrator.audit import record_event, get_events
from mco.config import get_config
from mco.notifiers.ntfy import (
    notify_job_created,
    notify_job_completed,
    notify_job_failed,
    notify_job_leased,
    notify_job_needs_approval,
)

# Roles allowed to approve/reject jobs paused at the human-in-the-loop gate.
DEFAULT_APPROVER_ROLES = "human,admin,operator"


def get_approver_roles() -> set:
    """Lower-cased roles permitted to decide approval gates (MCO_APPROVER_ROLES)."""
    raw = get_config().get("MCO_APPROVER_ROLES") or DEFAULT_APPROVER_ROLES
    return {r.strip().lower() for r in raw.split(",") if r.strip()}


def agent_org(agent: dict) -> str:
    """Tenant boundary for the calling agent ('default' on single-tenant installs)."""
    return agent.get("org_id") or "default"


def job_org(job: dict) -> str:
    return job.get("org_id") or "default"


def get_gated_roles() -> set:
    """Roles whose jobs are force-gated on human approval (MCO_POLICY_GATED_ROLES).

    Guardrail for high-blast-radius targets: set it to your connector roles
    (e.g. 'servicenow,dynatrace') and no agent can write to those platforms
    without a human approving first - regardless of what the sender asked for.
    """
    raw = get_config().get("MCO_POLICY_GATED_ROLES") or ""
    return {r.strip().lower() for r in raw.split(",") if r.strip()}


def kill_switch_active() -> bool:
    """Global pause (MCO_KILL_SWITCH): no new jobs created, no leases granted.

    In-flight work may finish and report; humans can still approve/audit.
    """
    return str(get_config().get("MCO_KILL_SWITCH") or "").lower() in ("1", "true", "on", "yes")

logger = logging.getLogger("mco.orchestrator.routes")
router = APIRouter(prefix="/api/jobs")
agents_router = APIRouter(prefix="/api/agents")

# Dynamic callback hook for gateway websocket notifications
# Callable signature: async def callback(event: str, job: dict)
_broadcast_callback = None

def register_broadcast_callback(callback) -> None:
    """Register a custom callback function to broadcast gateway events."""
    global _broadcast_callback
    _broadcast_callback = callback
    logger.info("Registered custom Job Board broadcast callback.")


# Memoized Supabase client. create_client() is expensive (~3-4s: spins up
# PostgREST/Auth/Realtime sub-clients), so building it per request made every
# endpoint slow enough to trip client timeouts. Build once, reuse.
_db_client = None


def get_db_client(force_new: bool = False):
    """Return the cached data-plane client (created on first use).

    Supabase when credentials are configured; otherwise BatonCadence's
    embedded LocalStore (SQLite) so the Local-Only profile gets real
    persistence - jobs, audit trail, agent registry, and Mythos shared
    context all work with zero cloud dependencies. Set MCO_DISABLE_LOCAL_DB
    to opt out of the embedded fallback (returns None, as before).
    """
    global _db_client
    if _db_client is not None and not force_new:
        return _db_client
    config = get_config()
    url = config.get("SUPABASE_URL")
    key = config.get("SUPABASE_KEY")
    if url and key and url != "encrypted_in_secret_store":
        from supabase import create_client
        _db_client = create_client(url, key)
        return _db_client

    if str(config.get("MCO_DISABLE_LOCAL_DB") or "").lower() in ("1", "true", "on", "yes"):
        return None

    from mco.localstore import get_local_store, seed_local_operator
    store = get_local_store()
    local_token = (config.get("MCO_LOCAL_TOKEN") or "").strip()
    if local_token:
        try:
            seed_local_operator(store, local_token)
        except Exception as e:
            logger.warning(f"Could not seed local operator agent: {e}")
    _db_client = store
    return _db_client


@router.get("")
async def get_jobs(agent: dict = Depends(require_agent)):
    """Retrieve job list from the Supabase database."""
    db_client = get_db_client()
    if not db_client:
        return []
    try:
        res = (
            db_client.table("agent_jobs").select("*")
            .eq("org_id", agent_org(agent))
            .order("created_at", desc=True).limit(100).execute()
        )
        return res.data or []
    except Exception as e:
        logger.error(f"Error fetching jobs: {e}")
        return []


@router.post("")
async def create_job(payload: dict, agent: dict = Depends(require_agent)):
    """Create a job. Any authenticated agent may send to any target ('drop mail')."""
    db_client = get_db_client()
    if not db_client:
        raise HTTPException(status_code=400, detail="Database not configured")
    if kill_switch_active():
        raise HTTPException(status_code=503, detail="MCO_KILL_SWITCH is active: job intake is paused")
    try:
        title = payload.get("title")
        description = payload.get("description")
        target_agent_role = payload.get("target_agent_role")
        target_agent_id = payload.get("target_agent_id")
        depends_on = payload.get("depends_on") or []
        input_payload = payload.get("input_payload") or {}
        requires_approval = bool(payload.get("requires_approval"))
        max_retries = int(payload.get("max_retries") or 0)
        escalate_to_role = payload.get("escalate_to_role")

        if not title or not target_agent_role:
            raise HTTPException(status_code=400, detail="title and target_agent_role are required")

        # Policy guardrail: jobs targeting gated roles ALWAYS pause for a human,
        # no matter what the sender requested.
        if target_agent_role.lower() in get_gated_roles():
            requires_approval = True

        from mco.orchestrator.handlers import _initial_status
        status = _initial_status(db_client, depends_on, requires_approval)

        data = {
            "title": title,
            "description": description,
            "source_agent_id": agent["instance_id"],
            "source_agent_role": agent["role"],
            "target_agent_role": target_agent_role,
            "target_agent_id": target_agent_id,
            "status": status,
            "depends_on": depends_on,
            "input_payload": input_payload,
        }
        # Tenant stamp (omitted for the default org so pre-migration DBs keep working).
        if agent_org(agent) != "default":
            data["org_id"] = agent_org(agent)
        # Governance columns are only sent when used (pre-migration DB compatibility).
        if requires_approval:
            data["requires_approval"] = True
        if max_retries:
            data["max_retries"] = max_retries
        if escalate_to_role:
            data["escalate_to_role"] = escalate_to_role

        res = db_client.table("agent_jobs").insert(data).execute()
        if res.data:
            new_job = res.data[0]
            record_event(db_client, new_job.get("id"), "created",
                         agent["instance_id"], agent["role"],
                         {"status": status, "target_agent_role": target_agent_role})
            # Trigger registered broadcast callback first
            if _broadcast_callback:
                try:
                    if status == JobStatus.PENDING.value:
                        event_name = "job_pending"
                    elif status == JobStatus.NEEDS_APPROVAL.value:
                        event_name = "job_needs_approval"
                    else:
                        event_name = "job_created"
                    await _broadcast_callback(event_name, new_job)
                except Exception as e:
                    logger.warning(f"Error executing broadcast callback: {e}")
            # ntfy webhook addon (if enabled via NTFY_* env vars)
            try:
                if status == JobStatus.NEEDS_APPROVAL.value:
                    notify_job_needs_approval(
                        job_id=new_job.get("id", "unknown"),
                        title=new_job.get("title", "Untitled job"),
                        to_role=new_job.get("target_agent_role", "unknown"),
                    )
                else:
                    notify_job_created(
                        job_id=new_job.get("id", "unknown"),
                        title=new_job.get("title", "Untitled job"),
                        to_role=new_job.get("target_agent_role", "unknown"),
                    )
            except Exception as ntfy_err:
                logger.debug(f"ntfy addon skipped: {ntfy_err}")

            return {"success": True, "job": new_job}
        return {"success": False, "error": "Insert failed"}
    except Exception as e:
        logger.error(f"Error creating job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pending")
async def get_pending_jobs(role: str, instance_id: str = None, agent: dict = Depends(require_agent)):
    """Retrieve pending jobs for a role. Dropbox rule: you may only poll your own mail."""
    if role.lower() != agent["role"].lower():
        raise HTTPException(status_code=403, detail="Cannot poll jobs for a role you are not registered as")
    if instance_id and instance_id != agent["instance_id"]:
        raise HTTPException(status_code=403, detail="instance_id does not match the authenticated agent")
    db_client = get_db_client()
    if not db_client:
        return []
    try:
        res = db_client.table("agent_jobs")\
            .select("*")\
            .eq("status", "pending")\
            .eq("target_agent_role", role)\
            .execute()

        jobs = res.data or []
        filtered = []
        for job in jobs:
            if job_org(job) != agent_org(agent):
                continue
            target_id = job.get("target_agent_id")
            if target_id and target_id != instance_id:
                continue
            filtered.append(job)
        return filtered
    except Exception as e:
        logger.error(f"Error fetching pending jobs: {e}")
        return []


@router.post("/lease")
async def lease_job(payload: dict, agent: dict = Depends(require_agent)):
    """Atomically lease a job. Dropbox rule: you may only lease as yourself."""
    db_client = get_db_client()
    if not db_client:
        raise HTTPException(status_code=400, detail="Database not configured")
    if kill_switch_active():
        raise HTTPException(status_code=503, detail="MCO_KILL_SWITCH is active: leasing is paused")
    try:
        task_id = payload.get("task_id")
        agent_instance_id = payload.get("agent_instance_id")
        if not task_id or not agent_instance_id:
            raise HTTPException(status_code=400, detail="task_id and agent_instance_id are required")
        if agent_instance_id != agent["instance_id"]:
            raise HTTPException(status_code=403, detail="Cannot lease on behalf of another agent")

        # Tenant isolation: you can only lease jobs inside your own org.
        pre = db_client.table("agent_jobs").select("*").eq("id", task_id).execute()
        if pre.data and job_org(pre.data[0]) != agent_org(agent):
            raise HTTPException(status_code=404, detail="Job not found")

        res = db_client.rpc("lease_task", {
            "p_agent_instance_id": agent_instance_id,
            "p_task_id": task_id
        }).execute()
        
        success = res.data if hasattr(res, "data") else False
        
        if success:
            record_event(db_client, task_id, "leased", agent_instance_id, agent["role"])
            try:
                notify_job_leased(task_id, agent_instance_id, agent["role"])
            except Exception as ntfy_err:
                logger.debug(f"ntfy lease hook skipped: {ntfy_err}")
        
        if success and _broadcast_callback:
            try:
                job_res = db_client.table("agent_jobs").select("*").eq("id", task_id).execute()
                if job_res.data:
                    await _broadcast_callback("job_leased", job_res.data[0])
            except Exception as e:
                logger.warning(f"Error executing broadcast callback after lease: {e}")
                
        return {"success": success}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error leasing job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{job_id}")
async def update_job_status(job_id: str, payload: dict, agent: dict = Depends(require_agent)):
    """Update job status/results. Dropbox rule: you may only update mail addressed to you."""
    db_client = get_db_client()
    if not db_client:
        raise HTTPException(status_code=400, detail="Database not configured")
    try:
        # Authorization: the job must be addressed to the calling agent's role or instance.
        job_res = db_client.table("agent_jobs").select("*").eq("id", job_id).execute()
        if job_res.data:
            j = job_res.data[0]
            if job_org(j) != agent_org(agent):
                raise HTTPException(status_code=404, detail="Job not found")
            target_role = (j.get("target_agent_role") or "").lower()
            caller_role = (agent.get("role") or "").lower()
            target_id = j.get("target_agent_id")
            caller_id = agent.get("instance_id")
            if target_role != caller_role and target_id != caller_id:
                raise HTTPException(status_code=403, detail="Cannot update a job not addressed to you")

        status = payload.get("status")
        output_payload = payload.get("output_payload")
        error_message = payload.get("error_message")
        
        if not status:
            raise HTTPException(status_code=400, detail="status is required")
            
        from mco.orchestrator.handlers import handle_job_update
        
        updated_job = None
        error_occurred = None
        
        async def send_ack(ack_payload: dict):
            nonlocal updated_job
            updated_job = ack_payload.get("job")
            
        async def send_error(err_msg: str, correlation_id: str):
            nonlocal error_occurred
            error_occurred = err_msg
            
        async def broadcast_event(event_name: str, event_job: dict):
            if _broadcast_callback:
                await _broadcast_callback(event_name, event_job)
                
        await handle_job_update(
            db_client=db_client,
            payload={
                "task_id": job_id,
                "status": status,
                "output_payload": output_payload,
                "error_message": error_message
            },
            correlation_id="http_update",
            send_error=send_error,
            send_ack=send_ack,
            broadcast_event=broadcast_event,
            actor=agent,
        )
        
        if error_occurred:
            raise HTTPException(status_code=400, detail=error_occurred)

        # NTFY addon hooks for completion/failure
        try:
            final_status = (updated_job or {}).get("status", status)
            role = (updated_job or {}).get("target_agent_role") or "unknown"
            jid = (updated_job or {}).get("id", job_id)

            if final_status in ("completed", "success", "done"):
                notify_job_completed(jid, final_status, role)
            elif final_status in ("failed", "error"):
                notify_job_failed(jid, error_message or "Unknown error", role)
        except Exception as ntfy_err:
            logger.debug(f"ntfy completion/failure hook skipped: {ntfy_err}")

        return {"success": True, "job": updated_job}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{job_id}/events")
async def get_job_events(job_id: str, agent: dict = Depends(require_agent)):
    """Immutable audit trail for one job, oldest event first."""
    db_client = get_db_client()
    if not db_client:
        return []
    # Tenant isolation: only jobs in the caller's org expose their trail.
    job_res = db_client.table("agent_jobs").select("*").eq("id", job_id).execute()
    if job_res.data and job_org(job_res.data[0]) != agent_org(agent):
        return []
    return get_events(db_client, job_id)


async def _decide_approval(job_id: str, agent: dict, approve: bool, reason: str = "") -> dict:
    """Shared approve/reject flow for jobs paused at the human-in-the-loop gate."""
    db_client = get_db_client()
    if not db_client:
        raise HTTPException(status_code=400, detail="Database not configured")

    if (agent.get("role") or "").lower() not in get_approver_roles():
        raise HTTPException(status_code=403, detail="Your role is not permitted to decide approval gates")

    job_res = db_client.table("agent_jobs").select("*").eq("id", job_id).execute()
    if not job_res.data:
        raise HTTPException(status_code=404, detail="Job not found")
    job = job_res.data[0]
    if job_org(job) != agent_org(agent):
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") != JobStatus.NEEDS_APPROVAL.value:
        raise HTTPException(status_code=400, detail=f"Job is not awaiting approval (status: {job.get('status')})")

    if approve:
        update_data = {
            "status": JobStatus.PENDING.value,
            "approved_by": agent["instance_id"],
        }
        event, event_name = "approved", "job_pending"
    else:
        update_data = {
            "status": JobStatus.REJECTED.value,
            "approved_by": agent["instance_id"],
            "error_message": f"Rejected by {agent['instance_id']}: {reason or 'no reason given'}",
        }
        event, event_name = "rejected", "job_updated"

    res = db_client.table("agent_jobs").update(update_data).eq("id", job_id).execute()
    if not res.data:
        raise HTTPException(status_code=500, detail="Approval decision failed to persist")
    decided_job = res.data[0]

    record_event(db_client, job_id, event, agent["instance_id"], agent["role"],
                 {"reason": reason} if reason else None)

    if _broadcast_callback:
        try:
            await _broadcast_callback(event_name, decided_job)
        except Exception as e:
            logger.warning(f"Error executing broadcast callback after approval decision: {e}")

    return {"success": True, "job": decided_job}


@router.post("/{job_id}/approve")
async def approve_job(job_id: str, agent: dict = Depends(require_agent)):
    """Approve a NEEDS_APPROVAL job, releasing it to PENDING for execution."""
    return await _decide_approval(job_id, agent, approve=True)


@router.post("/{job_id}/retry")
async def retry_job(job_id: str, agent: dict = Depends(require_agent)):
    """Re-queue a FAILED or REJECTED job (approver roles only).

    Clears the lease and puts the job back to PENDING so a worker can pick it
    up again - the human override behind the console's 'Try again' button.
    """
    db_client = get_db_client()
    if not db_client:
        raise HTTPException(status_code=400, detail="Database not configured")
    if (agent.get("role") or "").lower() not in get_approver_roles():
        raise HTTPException(status_code=403, detail="Your role is not permitted to re-queue jobs")

    job_res = db_client.table("agent_jobs").select("*").eq("id", job_id).execute()
    if not job_res.data:
        raise HTTPException(status_code=404, detail="Job not found")
    job = job_res.data[0]
    if job_org(job) != agent_org(agent):
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") not in (JobStatus.FAILED.value, JobStatus.REJECTED.value):
        raise HTTPException(status_code=400, detail=f"Only failed/rejected jobs can be retried (status: {job.get('status')})")

    res = db_client.table("agent_jobs").update({
        "status": JobStatus.PENDING.value,
        "leased_by_instance_id": None,
        "error_message": None,
    }).eq("id", job_id).execute()
    if not res.data:
        raise HTTPException(status_code=500, detail="Retry failed to persist")
    requeued_job = res.data[0]

    record_event(db_client, job_id, "retried", agent["instance_id"], agent["role"],
                 {"manual": True, "previous_status": job.get("status")})

    if _broadcast_callback:
        try:
            await _broadcast_callback("job_pending", requeued_job)
        except Exception as e:
            logger.warning(f"Error executing broadcast callback after retry: {e}")

    return {"success": True, "job": requeued_job}


@router.post("/{job_id}/reject")
async def reject_job(job_id: str, payload: dict = None, agent: dict = Depends(require_agent)):
    """Reject a NEEDS_APPROVAL job. Terminal: the job moves to REJECTED."""
    reason = (payload or {}).get("reason", "")
    return await _decide_approval(job_id, agent, approve=False, reason=reason)


@agents_router.get("")
async def get_agents(agent: dict = Depends(require_agent)):
    """Retrieve registered agents and presence. Excludes the auth_token_hash column."""
    db_client = get_db_client()
    if not db_client:
        return []
    try:
        res = db_client.table("agent_registry").select("*").order("instance_id").execute()
        org = agent_org(agent)
        out = []
        for r in (res.data or []):
            # Tenant isolation (app-side so pre-migration schemas keep working).
            if (r.get("org_id") or "default") != org:
                continue
            # Never expose auth_token_hash over the API.
            out.append({k: v for k, v in r.items() if k != "auth_token_hash"})
        return out
    except Exception as e:
        logger.error(f"Error fetching registered agents: {e}")
        return []
