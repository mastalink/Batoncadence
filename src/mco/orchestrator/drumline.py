"""
Drumline - the shared context substrate all agents dip into.

Every agent on the mesh (Claude, Codex, Gemini, connector workers) reads from
and writes to one collective memory, so knowledge survives across jobs, roles,
vendors, and time:

- **Auto-distillation**: when a job completes, its essence (what was asked,
  what came back) is distilled into a context entry - the audit trail becomes
  living memory, not just evidence.
- **Deliberate memory**: agents call remember() (via MCP tool / REST) to store
  facts, decisions, and lessons for everyone downstream.
- **Recall + injection**: workers recall the most relevant entries before
  executing a lease and prepend them to the prompt as a SHARED CONTEXT block.

Storage is one append-mostly table (`agent_context`). Retrieval is a
deterministic score - term overlap x entry weight + recency + role affinity -
chosen over embeddings so the substrate stays standalone, cheap, auditable,
and testable. An embedding back-end can replace `score_entry` later without
changing any caller.
"""

from __future__ import annotations

import logging
import re
from typing import Any, List, Optional

logger = logging.getLogger("mco.drumline")

CONTEXT_TABLE = "agent_context"
KINDS = ("fact", "decision", "lesson", "handoff", "artifact")
FETCH_WINDOW = 200          # newest entries considered per recall
MAX_CONTENT_CHARS = 2000    # stored content cap
DISTILL_PROMPT_CHARS = 280  # how much of the ask survives distillation
DISTILL_RESULT_CHARS = 1200 # how much of the answer survives distillation

_STOPWORDS = {
    "the", "a", "an", "and", "or", "for", "with", "from", "this", "that",
    "into", "onto", "your", "our", "you", "are", "is", "was", "were", "be",
    "to", "of", "in", "on", "it", "as", "at", "by", "we", "do", "does",
}


def _terms(text: str) -> List[str]:
    """Lower-cased significant terms from free text."""
    words = re.findall(r"[a-zA-Z0-9_\-]{3,}", (text or "").lower())
    return [w for w in words if w not in _STOPWORDS]


# ── Writing memory ────────────────────────────────────────────────────────────

def remember(
    db_client: Any,
    *,
    title: str,
    content: str,
    kind: str = "fact",
    scope: str = "global",
    role: Optional[str] = None,
    tags: Optional[List[str]] = None,
    created_by: str = "system",
    source_job_id: Optional[str] = None,
    weight: float = 1.0,
    org_id: str = "default",
) -> Optional[dict]:
    """Append one entry to the shared context. Returns the stored row or None."""
    if db_client is None or not title or not content:
        return None
    if kind not in KINDS:
        kind = "fact"
    data = {
        "scope": scope,
        "role": (role or None),
        "kind": kind,
        "title": title[:300],
        "content": content[:MAX_CONTENT_CHARS],
        "tags": [t.strip().lower() for t in (tags or []) if t and t.strip()],
        "created_by": created_by,
        "source_job_id": source_job_id,
        "weight": max(0.1, min(float(weight), 5.0)),
    }
    # Tenant stamp (omitted for the default org so pre-migration DBs keep working).
    if org_id and org_id != "default":
        data["org_id"] = org_id
    try:
        res = db_client.table(CONTEXT_TABLE).insert(data).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logger.warning(f"Drumline remember skipped: {e}")
        return None


def distill_job(db_client: Any, job: dict) -> Optional[dict]:
    """Distill a completed job into a handoff entry (prompt -> outcome).

    This is the bridge between the audit log and living memory: the *evidence*
    of what happened stays immutable in agent_job_events; the *essence* of what
    was learned becomes recallable context for every future job.
    """
    if not job or not job.get("id"):
        return None
    output = ((job.get("output_payload") or {}).get("result")) or ""
    if not output:
        return None
    payload = job.get("input_payload") or {}
    asked = payload.get("prompt") or job.get("description") or job.get("title") or ""
    content = (
        f"Asked: {asked[:DISTILL_PROMPT_CHARS]}\n"
        f"Outcome: {str(output)[:DISTILL_RESULT_CHARS]}"
    )
    tags = [t for t in (
        job.get("target_agent_role"),
        job.get("source_agent_role"),
        payload.get("connector"),
    ) if t]
    return remember(
        db_client,
        title=f"Job outcome: {job.get('title', 'untitled')}",
        content=content,
        kind="handoff",
        role=job.get("target_agent_role"),
        tags=tags,
        created_by=job.get("leased_by_instance_id") or job.get("target_agent_role") or "system",
        source_job_id=str(job.get("id")),
        org_id=job.get("org_id") or "default",
    )


# ── Recalling memory ──────────────────────────────────────────────────────────

def score_entry(entry: dict, terms: List[str], role: Optional[str], recency: float) -> float:
    """Deterministic relevance: term overlap x weight + role affinity + recency."""
    haystack = " ".join([
        entry.get("title") or "",
        entry.get("content") or "",
        " ".join(entry.get("tags") or []),
    ]).lower()
    hits = sum(1 for t in set(terms) if t in haystack)
    s = hits * float(entry.get("weight") or 1.0)
    if role and (entry.get("role") or "").lower() == role.lower():
        s += 0.75
    s += recency  # 0..0.5, newest first
    return s


def recall(
    db_client: Any,
    query: str = "",
    role: Optional[str] = None,
    tags: Optional[List[str]] = None,
    limit: int = 5,
    org_id: str = "default",
) -> List[dict]:
    """Return the most relevant shared-context entries, best first.

    With no query, returns the freshest entries (role-affine first). Tag
    filters are hard filters; the query is soft-scored.
    """
    if db_client is None:
        return []
    try:
        res = (
            db_client.table(CONTEXT_TABLE)
            .select("*")
            .order("created_at", desc=True)
            .limit(FETCH_WINDOW)
            .execute()
        )
    except Exception as e:
        logger.warning(f"Drumline recall skipped: {e}")
        return []

    # Tenant isolation: an org only ever recalls its own memory.
    entries = [e for e in (res.data or []) if (e.get("org_id") or "default") == (org_id or "default")]
    if tags:
        wanted = {t.strip().lower() for t in tags if t and t.strip()}
        entries = [e for e in entries if wanted & set(e.get("tags") or [])]

    terms = _terms(query)
    n = max(len(entries), 1)
    scored = []
    for i, entry in enumerate(entries):
        recency = 0.5 * (n - i) / n
        s = score_entry(entry, terms, role, recency)
        if terms and s <= recency:  # query given but nothing matched: drop
            continue
        scored.append((s, i, entry))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [e for _, _, e in scored[:max(1, min(limit, 25))]]


def render_context_block(entries: List[dict]) -> str:
    """Render recalled entries as the SHARED CONTEXT block injected into prompts."""
    if not entries:
        return ""
    lines = ["=== SHARED CONTEXT (Drumline) ===",
             "Collective memory from prior agent work. Use it; correct it via mco_remember if wrong."]
    for e in entries:
        stamp = str(e.get("created_at") or "")[:10]
        by = e.get("created_by") or "unknown"
        lines.append(f"- [{e.get('kind', 'fact')}] {e.get('title', '')} ({by}, {stamp})")
        content = (e.get("content") or "").strip()
        if content:
            lines.append(f"  {content[:600]}")
    lines.append("=== END SHARED CONTEXT ===")
    return "\n".join(lines)
