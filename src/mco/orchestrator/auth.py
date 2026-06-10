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
from mco.config import get_config


def hash_token(token: str) -> str:
    """SHA-256 hex digest of an agent access token (matches `mco register`)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_token(db_client: Any, token: str) -> Optional[dict]:
    """Return the `agent_registry` row for a valid token, else None.

    The row includes `org_id`, the tenant boundary every downstream query is
    scoped to (pre-migration databases fall back to the 'default' org).
    """
    if not token or db_client is None:
        return None
    try:
        res = (
            db_client.table("agent_registry")
            .select("instance_id, role, status, org_id")
            .eq("auth_token_hash", hash_token(token))
            .execute()
        )
    except Exception:
        # Pre-multi-tenancy schema without org_id.
        res = (
            db_client.table("agent_registry")
            .select("instance_id, role, status")
            .eq("auth_token_hash", hash_token(token))
            .execute()
        )
    rows = res.data or []
    if not rows:
        return None
    agent = rows[0]
    agent.setdefault("org_id", "default")
    return agent


def extract_bearer(authorization: str) -> str:
    """Pull the raw token out of an `Authorization: Bearer <token>` header."""
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


async def require_agent(authorization: str = Header(default="")) -> dict:
    """FastAPI dependency: authenticate the caller as a registered agent.

    When no database is configured (Local-Only profile), validates against
    MCO_LOCAL_TOKEN from config instead.  This lets the console connect
    without a Supabase database — paste the token shown in the server window.

    Raises 401 if the token is missing/invalid.
    Returns the agent's {instance_id, role, status} for downstream checks.
    """
    from mco.orchestrator.routes import get_db_client

    db_client = get_db_client()
    if db_client is None:
        # Local-Only mode: validate against the static token in config.
        local_token = (get_config().get("MCO_LOCAL_TOKEN") or "").strip()
        bearer = extract_bearer(authorization)
        if local_token:
            if bearer != local_token:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid token. Paste the MCO_LOCAL_TOKEN shown in your server window.",
                )
        elif not bearer:
            # No token configured and none provided — block unauthenticated requests.
            raise HTTPException(
                status_code=401,
                detail="No agent token. Add MCO_LOCAL_TOKEN to .env or run 'mco setup'.",
            )
        # Token is either correct or MCO_LOCAL_TOKEN is absent and any token is accepted.
        return {
            "instance_id": "local",
            "role": "admin",
            "status": "online",
            "org_id": "default",
        }

    agent = verify_token(db_client, extract_bearer(authorization))
    if not agent:
        raise HTTPException(status_code=401, detail="Invalid or missing agent token")
    return agent
