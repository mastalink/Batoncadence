"""FastAPI routes for the Job Board API, serving GET and POST requests."""

import os
import logging
from fastapi import APIRouter, HTTPException
from mco.orchestrator.contracts import JobStatus
from mco.config import get_config

logger = logging.getLogger("mco.orchestrator.routes")
router = APIRouter(prefix="/api/jobs")

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
