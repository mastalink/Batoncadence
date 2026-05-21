"""FastAPI routes for the Job Board API, serving GET and POST requests."""

import os
import logging
from fastapi import APIRouter, HTTPException
from mco.orchestrator.contracts import JobStatus
from mco.config import get_config

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


def get_db_client():
    """Retrieve Supabase database client dynamically from MCO config."""
    config = get_config()
    url = config.get("SUPABASE_URL")
    key = config.get("SUPABASE_KEY")
    if url and key and url != "encrypted_in_secret_store":
        from supabase import create_client
        return create_client(url, key)

    return None


@router.get("")
async def get_jobs():
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
async def create_job(payload: dict):
    """Manually trigger/create a job from the dashboard."""
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
            "source_agent_id": "dashboard",
            "source_agent_role": "web_ui",
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
            return {"success": True, "job": res.data[0]}
        return {"success": False, "error": "Insert failed"}
    except Exception as e:
        logger.error(f"Error creating job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pending")
async def get_pending_jobs(role: str, instance_id: str = None):
    """Retrieve pending jobs for a specific role and optional instance_id."""
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
async def lease_job(payload: dict):
    """Atomically lease a job on behalf of a worker agent."""
    db_client = get_db_client()
    if not db_client:
        raise HTTPException(status_code=400, detail="Database not configured")
    try:
        task_id = payload.get("task_id")
        agent_instance_id = payload.get("agent_instance_id")
        if not task_id or not agent_instance_id:
            raise HTTPException(status_code=400, detail="task_id and agent_instance_id are required")
        
        res = db_client.rpc("lease_task", {
            "p_agent_instance_id": agent_instance_id,
            "p_task_id": task_id
        }).execute()
        
        success = res.data if hasattr(res, "data") else False
        
        if success and _broadcast_callback:
            try:
                job_res = db_client.table("agent_jobs").select("*").eq("id", task_id).execute()
                if job_res.data:
                    await _broadcast_callback("job_leased", job_res.data[0])
            except Exception as e:
                logger.warning(f"Error executing broadcast callback after lease: {e}")
                
        return {"success": success}
    except Exception as e:
        logger.error(f"Error leasing job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{job_id}")
async def update_job_status(job_id: str, payload: dict):
    """Update job status and results with cascading unlocking checks."""
    db_client = get_db_client()
    if not db_client:
        raise HTTPException(status_code=400, detail="Database not configured")
    try:
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
            
        return {"success": True, "job": updated_job}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@agents_router.get("")
async def get_agents():
    """Retrieve registered agents and their current presence status."""
    db_client = get_db_client()
    if not db_client:
        return []
    try:
        res = db_client.table("agent_registry").select("*").order("instance_id").execute()
        return res.data or []
    except Exception as e:
        logger.error(f"Error fetching registered agents: {e}")
        return []
