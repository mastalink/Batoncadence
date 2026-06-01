"""FastAPI routes for the Job Board API, serving GET and POST requests."""

import os
import logging
from fastapi import APIRouter, HTTPException, Depends
from mco.orchestrator.contracts import JobStatus
from mco.orchestrator.auth import require_agent
from mco.config import get_config
from mco.notifiers.ntfy import notify_job_created, notify_job_completed, notify_job_failed, notify_job_leased

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
    """Return a cached Supabase client (created on first use), or None if unconfigured."""
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

    return None


@router.get("")
async def get_jobs(agent: dict = Depends(require_agent)):
    """Retrieve job list from the Supabase database."""
    db_client = get_db_client()
    if not db_client:
        return []
    try:
        res = db_client.table("agent_jobs").select("*").order("created_at", desc=True).limit(100).execute()
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
    try:
        title = payload.get("title")
        description = payload.get("description")
        target_agent_role = payload.get("target_agent_role")
        target_agent_id = payload.get("target_agent_id")
        depends_on = payload.get("depends_on") or []
        input_payload = payload.get("input_payload") or {}

        if not title or not target_agent_role:
            raise HTTPException(status_code=400, detail="title and target_agent_role are required")

        # Check dependencies
        has_incomplete_deps = False
        if depends_on:
            dep_res = db_client.table("agent_jobs").select("status").in_("id", depends_on).execute()
            for dep in (dep_res.data or []):
                if dep.get("status") != JobStatus.COMPLETED.value:
                    has_incomplete_deps = True
                    break

        status = JobStatus.WAITING.value if has_incomplete_deps else JobStatus.PENDING.value

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

        res = db_client.table("agent_jobs").insert(data).execute()
        if res.data:
            # Trigger registered broadcast callback first
            if _broadcast_callback:
                try:
                    event_name = "job_created" if status == JobStatus.WAITING.value else "job_pending"
                    await _broadcast_callback(event_name, res.data[0])
                except Exception as e:
                    logger.warning(f"Error executing broadcast callback: {e}")
            # ntfy webhook addon (if enabled via NTFY_* env vars)
            try:
                notify_job_created(
                    job_id=res.data[0].get("id", "unknown"),
                    title=res.data[0].get("title", "Untitled job"),
                    to_role=res.data[0].get("target_agent_role", "unknown"),
                )
            except Exception as ntfy_err:
                logger.debug(f"ntfy addon skipped: {ntfy_err}")

            return {"success": True, "job": res.data[0]}
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
    try:
        task_id = payload.get("task_id")
        agent_instance_id = payload.get("agent_instance_id")
        if not task_id or not agent_instance_id:
            raise HTTPException(status_code=400, detail="task_id and agent_instance_id are required")
        if agent_instance_id != agent["instance_id"]:
            raise HTTPException(status_code=403, detail="Cannot lease on behalf of another agent")
        
        res = db_client.rpc("lease_task", {
            "p_agent_instance_id": agent_instance_id,
            "p_task_id": task_id
        }).execute()
        
        success = res.data if hasattr(res, "data") else False
        
        if success:
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
        job_res = db_client.table("agent_jobs").select("target_agent_role, target_agent_id").eq("id", job_id).execute()
        if job_res.data:
            j = job_res.data[0]
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
            broadcast_event=broadcast_event
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


@agents_router.get("")
async def get_agents(agent: dict = Depends(require_agent)):
    """Retrieve registered agents and presence. Excludes the auth_token_hash column."""
    db_client = get_db_client()
    if not db_client:
        return []
    try:
        # Never expose auth_token_hash over the API.
        res = db_client.table("agent_registry").select("instance_id, role, status, last_seen_at").order("instance_id").execute()
        return res.data or []
    except Exception as e:
        logger.error(f"Error fetching registered agents: {e}")
        return []
