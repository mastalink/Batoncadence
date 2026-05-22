"""Decoupled database transactional handlers for Job Board operations."""

import logging
from typing import Any, Callable, Coroutine, Dict, Optional
from mco.orchestrator.contracts import JobStatus

logger = logging.getLogger("mco.orchestrator.handlers")

async def handle_job_create(
    db_client: Any,
    payload: Dict[str, Any],
    source_agent_id: str,
    source_agent_role: str,
    correlation_id: str,
    send_error: Callable[[str, str], Coroutine[Any, Any, None]],
    send_ack: Callable[[Dict[str, Any]], Coroutine[Any, Any, None]],
    broadcast_event: Callable[[str, Dict[str, Any]], Coroutine[Any, Any, None]],
) -> None:
    """Handle creation of a new job on the Job Board."""
    title = payload.get("title")
    description = payload.get("description")
    target_agent_role = payload.get("target_agent_role")
    target_agent_id = payload.get("target_agent_id")
    depends_on = payload.get("depends_on") or []
    input_payload = payload.get("input_payload") or {}

    if not title or not target_agent_role:
        await send_error("Missing required fields: 'title' and 'target_agent_role'", correlation_id)
        return

    try:
        # Check for incomplete dependencies
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
            "source_agent_id": source_agent_id,
            "source_agent_role": source_agent_role,
            "target_agent_role": target_agent_role,
            "target_agent_id": target_agent_id,
            "status": status,
            "depends_on": depends_on,
            "input_payload": input_payload,
        }

        res = db_client.table("agent_jobs").insert(data).execute()
        if not res.data:
            await send_error("Failed to insert job into database", correlation_id)
            return

        new_job = res.data[0]

        # Send ACK to creator
        await send_ack({"status": "job_created", "job": new_job})

        # Broadcast new job event
        event_type = "job_created" if status == JobStatus.WAITING.value else "job_pending"
        await broadcast_event(event_type, new_job)

    except Exception as e:
        logger.exception(f"[{correlation_id}] JOB_CREATE handler error: {e}")
        await send_error(f"JOB_CREATE failed: {str(e)}", correlation_id)


async def handle_job_lease(
    db_client: Any,
    payload: Dict[str, Any],
    fallback_agent_instance_id: str,
    correlation_id: str,
    send_error: Callable[[str, str], Coroutine[Any, Any, None]],
    send_ack: Callable[[Dict[str, Any]], Coroutine[Any, Any, None]],
    broadcast_event: Callable[[str, Dict[str, Any]], Coroutine[Any, Any, None]],
) -> None:
    """Handle atomic leasing/claiming of a pending job."""
    task_id = payload.get("task_id")
    agent_instance_id = payload.get("agent_instance_id") or fallback_agent_instance_id

    if not task_id:
        await send_error("Missing 'task_id'", correlation_id)
        return

    try:
        # Atomic database-level lease function (uses Supabase RPC lease_task)
        res = db_client.rpc("lease_task", {
            "p_agent_instance_id": agent_instance_id,
            "p_task_id": task_id
        }).execute()

        success = res.data if hasattr(res, "data") else False

        if success:
            # Fetch updated job details
            job_res = db_client.table("agent_jobs").select("*").eq("id", task_id).execute()
            if job_res.data:
                job = job_res.data[0]
                # ACK to the leasing agent
                await send_ack({"status": "job_leased", "job": job})

                # Broadcast lease event
                await broadcast_event("job_leased", job)
            else:
                await send_error("Task leased but could not retrieve details", correlation_id)
        else:
            await send_error("Task is no longer pending or is not assigned to this instance", correlation_id)

    except Exception as e:
        logger.exception(f"[{correlation_id}] JOB_LEASE handler error: {e}")
        await send_error(f"JOB_LEASE failed: {str(e)}", correlation_id)


async def handle_job_update(
    db_client: Any,
    payload: Dict[str, Any],
    correlation_id: str,
    send_error: Callable[[str, str], Coroutine[Any, Any, None]],
    send_ack: Callable[[Dict[str, Any]], Coroutine[Any, Any, None]],
    broadcast_event: Callable[[str, Dict[str, Any]], Coroutine[Any, Any, None]],
) -> None:
    """Handle status, progress, or output updates for a leased job."""
    task_id = payload.get("task_id")
    status = payload.get("status")
    output_payload = payload.get("output_payload")
    error_message = payload.get("error_message")

    if not task_id or not status:
        await send_error("Missing 'task_id' or 'status'", correlation_id)
        return

    try:
        update_data = {"status": status}
        # completed_at is stamped by the DB trigger (trg_mco_stamp_completed_at) via now(),
        # keeping it on the same clock as created_at / started_at (no worker-clock skew).
        if output_payload is not None:
            update_data["output_payload"] = output_payload
        if error_message is not None:
            update_data["error_message"] = error_message

        res = db_client.table("agent_jobs").update(update_data).eq("id", task_id).execute()
        if not res.data:
            await send_error("Job not found or update failed", correlation_id)
            return

        updated_job = res.data[0]

        # ACK to agent
        await send_ack({"status": "job_updated", "job": updated_job})

        # Broadcast update event
        await broadcast_event("job_updated", updated_job)

        # Unlock downstream dependencies if completed
        if status == JobStatus.COMPLETED.value:
            # Find waiting tasks dependent on this task_id
            waiting_res = db_client.table("agent_jobs").select("*").eq("status", JobStatus.WAITING.value).execute()
            for waiting_job in (waiting_res.data or []):
                depends_on = waiting_job.get("depends_on") or []
                if task_id in depends_on:
                    # Check all parent statuses
                    parents_res = db_client.table("agent_jobs").select("status").in_("id", depends_on).execute()
                    all_completed = True
                    for parent in (parents_res.data or []):
                        if parent.get("status") != JobStatus.COMPLETED.value:
                            all_completed = False
                            break
                    
                    if all_completed:
                        unlock_res = db_client.table("agent_jobs").update({"status": JobStatus.PENDING.value}).eq("id", waiting_job["id"]).execute()
                        if unlock_res.data:
                            unlocked_job = unlock_res.data[0]
                            # Broadcast that this job is now pending
                            await broadcast_event("job_pending", unlocked_job)

    except Exception as e:
        logger.exception(f"[{correlation_id}] JOB_UPDATE handler error: {e}")
        await send_error(f"JOB_UPDATE failed: {str(e)}", correlation_id)
