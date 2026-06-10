"""
Connector sync engine: ingest enterprise platform objects as MCO jobs.

`sync_connector()` pulls normalized events from a connector and creates one
job per *new* event. Dedupe is by the stable `external_id` each connector
stamps into input_payload, checked against recent jobs on the board - so
repeated syncs (CLI, REST, or the gateway's background loop) are idempotent.

`normalize_webhook_event()` maps inbound push payloads (generic, ServiceNow
event registry, Dynatrace problem notification) onto the same job-spec shape,
so webhooks and polling share one ingestion path.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from mco.orchestrator.audit import record_event
from mco.orchestrator.contracts import JobStatus

logger = logging.getLogger("mco.connectors.sync")


def _known_external_ids(db_client, limit: int = 500) -> set:
    res = (
        db_client.table("agent_jobs")
        .select("input_payload")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    known = set()
    for row in (res.data or []):
        ext = ((row.get("input_payload") or {}).get("external_id"))
        if ext:
            known.add(ext)
    return known


def ingest_specs(db_client, specs: List[dict], source: str) -> dict:
    """Insert job specs that aren't already on the board. Returns a summary."""
    known = _known_external_ids(db_client)
    created, skipped = [], 0

    for spec in specs:
        ext_id = spec.get("external_id") or (spec.get("input_payload") or {}).get("external_id")
        if ext_id and ext_id in known:
            skipped += 1
            continue

        data = {
            "title": spec.get("title") or "External event",
            "description": spec.get("description") or "",
            "source_agent_id": source,
            "source_agent_role": "connector",
            "target_agent_role": spec.get("target_agent_role") or "claude",
            "target_agent_id": spec.get("target_agent_id"),
            "status": JobStatus.PENDING.value,
            "depends_on": [],
            "input_payload": spec.get("input_payload") or {},
        }
        if ext_id:
            data["input_payload"].setdefault("external_id", ext_id)
            known.add(ext_id)

        res = db_client.table("agent_jobs").insert(data).execute()
        if res.data:
            job = res.data[0]
            created.append(job.get("id"))
            record_event(db_client, job.get("id"), "created", source, "connector",
                         {"external_id": ext_id, "status": JobStatus.PENDING.value})
            try:
                from mco.notifiers.ntfy import notify_job_created
                notify_job_created(job.get("id", "unknown"), data["title"], data["target_agent_role"])
            except Exception:
                pass

    return {"created": created, "skipped": skipped}


def sync_connector(db_client, connector) -> dict:
    """One sync pass: pull open platform objects, create jobs for new ones."""
    specs = connector.pull_events()
    summary = ingest_specs(db_client, specs, source=f"connector:{connector.name}")
    summary["pulled"] = len(specs)
    logger.info(
        f"Sync {connector.name}: pulled={summary['pulled']} "
        f"created={len(summary['created'])} skipped={summary['skipped']}"
    )
    return summary


def normalize_webhook_event(connector_name: str, payload: dict, default_role: str = "claude") -> Optional[dict]:
    """Map an inbound webhook payload to a job spec (None if unusable)."""
    payload = payload or {}

    if connector_name == "dynatrace":
        # Dynatrace problem-notification webhook format
        pid = payload.get("ProblemID") or payload.get("problemId")
        title = payload.get("ProblemTitle") or payload.get("title")
        if not (pid and title):
            return None
        return {
            "external_id": f"dynatrace:{pid}",
            "title": f"[{payload.get('ProblemID', pid)}] {title}",
            "description": payload.get("ProblemDetailsText") or payload.get("ImpactedEntity") or "",
            "target_agent_role": default_role,
            "input_payload": {
                "external_id": f"dynatrace:{pid}",
                "connector": "dynatrace",
                "platform_ref": {"problemId": pid, "state": payload.get("State")},
                "prompt": f"Dynatrace problem {pid}: {title}\n{payload.get('ProblemDetailsText') or ''}",
            },
        }

    if connector_name == "servicenow":
        # ServiceNow event/business-rule webhook (flat record fields)
        sys_id = payload.get("sys_id")
        short = payload.get("short_description") or payload.get("title")
        if not (sys_id and short):
            return None
        return {
            "external_id": f"servicenow:{sys_id}",
            "title": f"[{payload.get('number', 'INC')}] {short}",
            "description": payload.get("description") or "",
            "target_agent_role": default_role,
            "input_payload": {
                "external_id": f"servicenow:{sys_id}",
                "connector": "servicenow",
                "platform_ref": {"sys_id": sys_id, "number": payload.get("number")},
                "prompt": f"ServiceNow incident {payload.get('number')}: {short}\n{payload.get('description') or ''}",
            },
        }

    # Generic contract: {id|external_id, title, description?, target_agent_role?}
    ext = payload.get("external_id") or payload.get("id")
    title = payload.get("title")
    if not title:
        return None
    return {
        "external_id": f"{connector_name}:{ext}" if ext else None,
        "title": str(title),
        "description": payload.get("description") or "",
        "target_agent_role": payload.get("target_agent_role") or default_role,
        "input_payload": {
            "external_id": f"{connector_name}:{ext}" if ext else None,
            "connector": connector_name,
            "platform_ref": payload.get("ref") or {},
            "prompt": payload.get("prompt") or f"{title}\n{payload.get('description') or ''}",
        },
    }
