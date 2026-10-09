"""Gateway API behind the console's Helpers page.

Same code as `bitcadence helpers` / `bitcadence fix` (mco.helpers). Handlers are
plain `def`, so FastAPI runs them in its threadpool: the database reads and the
process scan never block the event loop. Job reads are always limited.
"""
from fastapi import APIRouter, Depends, HTTPException

from mco import helpers
from mco.orchestrator.auth import require_scopes

helpers_router = APIRouter(prefix="/api/helpers")

_ACTIVE_LIMIT = 200


def _agents(caller: dict) -> list:
    from mco.orchestrator.routes import get_agents

    return get_agents(caller)


def _active_jobs() -> list:
    from mco.orchestrator.routes import get_db_client

    db = get_db_client()
    if not db:
        return []
    try:
        return (db.table("agent_jobs").select("*").in_("status", ["leased", "in_progress"])
                .limit(_ACTIVE_LIMIT).execute().data or [])
    except Exception:  # noqa: BLE001 - "doing" is a nicety; the list still shows
        return []


def _findings(agents: list) -> list:
    try:
        return helpers.scan(a.get("instance_id") for a in agents)
    except Exception:  # noqa: BLE001 - never let a process scan break the page
        return []


@helpers_router.get("")
def list_helpers(caller: dict = Depends(require_scopes("agents:read"))):
    """Every helper: friendly name, health light + word, what it is doing."""
    agents = _agents(caller)
    findings = _findings(agents)
    return {"helpers": helpers.describe(agents, _active_jobs(), findings),
            "problems": [f.to_json() for f in findings],
            "roles": [{"role": r, "label": label} for r, label in helpers.KNOWN_AIS]}


@helpers_router.post("/add")
def add_helper(payload: dict, caller: dict = Depends(require_scopes("agents:manage"))):
    """Add a helper by the same path as `bitcadence helpers add`. The reply carries
    only a masked credential."""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Give the helper a name.")
    try:
        added = helpers.add_helper(str(payload.get("name") or ""), str(payload.get("role") or ""))
    except helpers.HelperError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "helper": {k: added[k] for k in ("name", "id", "role", "credential")}}


@helpers_router.post("/fix")
def fix_helpers(payload: dict, caller: dict = Depends(require_scopes("agents:manage"))):
    """Fix it. Without `confirm: true` this is a dry run that only says what it
    found and what it would do; the repair runs only after the confirm."""
    confirmed = isinstance(payload, dict) and payload.get("confirm") is True
    findings = _findings(_agents(caller))
    return {"dry_run": not confirmed,
            "problems": [f.to_json() for f in findings],
            "results": helpers.repair(findings, confirmed=confirmed)}
