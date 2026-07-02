"""FastAPI routes for enterprise integrations (/api/integrations)."""

import hmac
import logging

from fastapi import APIRouter, Depends, Header, HTTPException

from mco.config import get_config
from mco.connectors import get_connector, list_connectors
from mco.connectors.sync import ingest_specs, normalize_webhook_event, sync_connector
from mco.editions import require_feature
from mco.orchestrator.auth import require_scopes

logger = logging.getLogger("mco.orchestrator.integrations")
integrations_router = APIRouter(
    prefix="/api/integrations",
    dependencies=[Depends(require_feature("connectors"))],
)


def _db():
    from mco.orchestrator.routes import get_db_client
    db_client = get_db_client()
    if not db_client:
        raise HTTPException(status_code=400, detail="Database not configured")
    return db_client


@integrations_router.get("")
async def get_integrations(agent: dict = Depends(require_scopes("integrations:read"))):
    """List configured connectors with reachability/auth health."""
    out = []
    for conn in list_connectors():
        out.append({"name": conn.name, "actions": conn.actions(), "health": conn.health()})
    return out


@integrations_router.post("/{name}/sync")
async def sync_integration(name: str, agent: dict = Depends(require_scopes("integrations:read", "jobs:write"))):
    """Pull open platform objects into the job board (idempotent by external_id)."""
    conn = get_connector(name)
    if not conn:
        raise HTTPException(status_code=404, detail=f"Connector '{name}' is not configured")
    try:
        return sync_connector(_db(), conn)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Sync failed for {name}: {e}")
        raise HTTPException(status_code=502, detail=f"Sync failed: {e}")


@integrations_router.post("/{name}/action")
async def run_integration_action(name: str, payload: dict, agent: dict = Depends(require_scopes("integrations:manage"))):
    """Run a connector control action directly (approver roles only).

    Side effects hit a live enterprise platform, so this is gated like the
    approval endpoints. Agents acting autonomously should instead address a
    job to the connector's role, keeping the lease/audit lifecycle intact.
    """
    from mco.orchestrator.utils import get_approver_roles
    if (agent.get("role") or "").lower() not in get_approver_roles():
        raise HTTPException(status_code=403, detail="Your role is not permitted to run connector actions directly")

    conn = get_connector(name)
    if not conn:
        raise HTTPException(status_code=404, detail=f"Connector '{name}' is not configured")
    action = payload.get("action")
    if not action:
        raise HTTPException(status_code=400, detail="action is required")
    try:
        result = conn.execute_action(action, payload.get("params") or {})
        return {"success": True, "result": result}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@integrations_router.post("/{name}/webhook")
async def integration_webhook(
    name: str,
    payload: dict,
    x_mco_webhook_secret: str = Header(default=""),
):
    """Inbound push ingestion (ServiceNow business rules, Dynatrace problem
    notifications, or any platform using the generic contract).

    Authenticated by the shared secret in MCO_WEBHOOK_SECRET - the endpoint is
    disabled (403) until that secret is configured.
    """
    secret = get_config().get("MCO_WEBHOOK_SECRET") or ""
    if not secret:
        raise HTTPException(status_code=403, detail="Webhook ingestion is disabled (MCO_WEBHOOK_SECRET not set)")
    if not hmac.compare_digest(x_mco_webhook_secret, secret):
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    default_role = get_config().get("MCO_WEBHOOK_TARGET_ROLE") or "claude"
    spec = normalize_webhook_event(name.lower(), payload, default_role=default_role)
    if not spec:
        raise HTTPException(status_code=400, detail="Payload missing required fields (title / id)")

    summary = ingest_specs(_db(), [spec], source=f"webhook:{name.lower()}")
    return {"success": True, **summary}
