"""
Gateway authentication & authorization.

Bearer-token auth for the REST API, reusing the same SHA-256 token-hash scheme
the WebSocket handshake uses (one source of truth). Authorization follows the
"dropbox" model: any authenticated agent may *send* (create a job to any target),
but *pulling/leasing/updating* a job requires the caller's identity to match the
job's addressee.
"""

import hashlib
from typing import Any, Optional

from fastapi import Header, HTTPException


def hash_token(token: str) -> str:
    """SHA-256 hex digest of an agent access token (matches `mco register`)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_token(db_client: Any, token: str) -> Optional[dict]:
    """Return the `agent_registry` row for a valid token, else None."""
    if not token or db_client is None:
        return None
    res = (
        db_client.table("agent_registry")
        .select("instance_id, role, status")
        .eq("auth_token_hash", hash_token(token))
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


def extract_bearer(authorization: str) -> str:
    """Pull the raw token out of an `Authorization: Bearer <token>` header."""
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


async def require_agent(authorization: str = Header(default="")) -> dict:
    """FastAPI dependency: authenticate the caller as a registered agent.

    Raises 503 if the gateway has no database, 401 if the token is missing/invalid.
    Returns the agent's `{instance_id, role, status}` for downstream policy checks.
    """
    # Lazy import to avoid a circular import with routes.py.
    from mco.orchestrator.routes import get_db_client

    db_client = get_db_client()
    if db_client is None:
        raise HTTPException(status_code=503, detail="Gateway database not configured")
    agent = verify_token(db_client, extract_bearer(authorization))
    if not agent:
        raise HTTPException(status_code=401, detail="Invalid or missing agent token")
    return agent
