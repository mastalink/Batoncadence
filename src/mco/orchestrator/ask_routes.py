"""Gateway API behind the console's "Ask for something" page.

Both routes call the same planner as `bitcadence ask` (mco.ask_plan). The plan
is stateless: the console sends the request plus the light tweaks it has
applied, and gets the drawn plan back.
"""
from fastapi import APIRouter, Depends, HTTPException

from mco import ask_plan
from mco.orchestrator.auth import require_scopes

ask_router = APIRouter(prefix="/api/ask")

_MAX_REQUEST = 2000


def _plan_from(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Tell me what you want done.")
    request = str(payload.get("request") or "")
    if len(request) > _MAX_REQUEST:
        raise HTTPException(status_code=400, detail="That request is too long. Shorten it and try again.")
    role = str(payload.get("role") or "claude")[:64]
    remove = payload.get("remove") or []
    if not isinstance(remove, list):
        raise HTTPException(status_code=400, detail="Tweaks were not understood.")
    try:
        plan = ask_plan.draft_plan(request, role)
        return ask_plan.apply_tweaks(plan, remove=[str(r) for r in remove],
                                     ask_end=bool(payload.get("ask_at_end")),
                                     repeat=str(payload.get("repeat") or ""))
    except ask_plan.PlanError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@ask_router.post("/plan")
def draft_ask_plan(payload: dict, caller: dict = Depends(require_scopes("jobs:read"))):
    """Draw the plan for a plain-language request. Creates nothing."""
    return {"plan": _plan_from(payload)}


@ask_router.post("/start")
async def start_ask_plan(payload: dict, caller: dict = Depends(require_scopes("jobs:write"))):
    """Approve and start: create the plan's jobs. The Approve click is the OK,
    so only the plan's own "ask me" steps wait."""
    from starlette.concurrency import run_in_threadpool
    from mco.orchestrator.routes import create_job

    plan = _plan_from(payload)
    run = ask_plan.new_run()
    ids: dict = {}
    for index, step in enumerate(plan["steps"]):
        spec = ask_plan.step_job(plan, index, ids, run, first_step_waits=False)
        res = await create_job({
            "title": spec["title"], "description": spec["instructions"],
            "target_agent_role": spec["to_role"], "depends_on": spec["depends_on"],
            "requires_approval": spec["requires_approval"], "max_retries": spec["max_retries"],
            "input_payload": {"prompt": spec["instructions"], **spec["extra_payload"]},
        }, caller)
        job = (res or {}).get("job") or {}
        if not (res or {}).get("success") or not job.get("id"):
            raise HTTPException(status_code=500, detail="That didn't go through. Nothing more was started.")
        ids[step["id"]] = job["id"]
    scheduled = None
    if plan.get("repeat"):
        try:
            scheduled = await run_in_threadpool(ask_plan.save_repeat, plan)
        except ask_plan.PlanError as exc:
            return {"success": True, "run": run, "jobs": ids, "repeat_error": str(exc)}
    return {"success": True, "run": run, "jobs": ids, "scheduled": scheduled,
            "repeat": (plan.get("repeat") or {}).get("words")}
