"""FastAPI routes for Drumline, the shared agent context (/api/context)."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from mco.orchestrator.auth import require_agent
from mco.orchestrator.drumline import recall, remember

logger = logging.getLogger("mco.orchestrator.context")
context_router = APIRouter(prefix="/api/context")


def _db():
    from mco.orchestrator.routes import get_db_client
    db_client = get_db_client()
    if not db_client:
        raise HTTPException(status_code=400, detail="Database not configured")
    return db_client


@context_router.get("")
async def recall_context(
    query: str = "",
    role: str = "",
    tags: str = "",
    limit: int = 5,
    agent: dict = Depends(require_agent),
):
    """Recall the most relevant shared-context entries (best first)."""
    tag_list = [t for t in (tags or "").split(",") if t.strip()]
    org = agent.get("org_id") or "default"
    return recall(_db(), query=query, role=role or None, tags=tag_list or None,
                  limit=limit, org_id=org)


@context_router.post("")
async def remember_context(payload: dict, agent: dict = Depends(require_agent)):
    """Append an entry to the shared context (any authenticated agent)."""
    title = (payload or {}).get("title")
    content = (payload or {}).get("content")
    if not title or not content:
        raise HTTPException(status_code=400, detail="title and content are required")
    entry = remember(
        _db(),
        title=title,
        content=content,
        kind=payload.get("kind") or "fact",
        scope=payload.get("scope") or "global",
        role=payload.get("role"),
        tags=payload.get("tags") or [],
        created_by=agent["instance_id"],
        source_job_id=payload.get("source_job_id"),
        weight=payload.get("weight") or 1.0,
        org_id=agent.get("org_id") or "default",
    )
    if not entry:
        raise HTTPException(status_code=500, detail="Failed to store context entry")
    return {"success": True, "entry": entry}
