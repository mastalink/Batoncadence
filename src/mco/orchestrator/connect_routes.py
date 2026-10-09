"""Gateway API behind the console's Connect an AI page.

Same code as `bitcadence connect` (mco.connect_ai). Handlers are plain `def`, so
FastAPI runs the small file reads/writes in its threadpool. Nothing here returns
a path or a credential: only app names, found/connected and a plain sentence.
"""
from fastapi import APIRouter, Depends, HTTPException

from mco import connect_ai
from mco.orchestrator.auth import require_scopes

connect_router = APIRouter(prefix="/api/connect-ai")

_STATUS = {"not_found": 404, "unknown": 404, "unreadable": 409}


def _run(fn, app: str):
    try:
        return fn(app)
    except connect_ai.ConnectError as exc:
        raise HTTPException(status_code=_STATUS.get(exc.kind, 400), detail=str(exc)) from exc


@connect_router.get("")
def list_apps(caller: dict = Depends(require_scopes("agents:read"))):
    return {"apps": connect_ai.status()}


@connect_router.get("/other")
def other_app(caller: dict = Depends(require_scopes("agents:read"))):
    return {"snippet": connect_ai.other_snippet()}


@connect_router.post("/{app}/connect")
def connect_app(app: str, caller: dict = Depends(require_scopes("agents:manage"))):
    res = _run(connect_ai.connect, app)
    name = connect_ai.label(res["app"])
    message = (f"{name} is connected. We found the app and set it up. Please close and reopen it once."
               if res["changed"] else f"{name} is already connected.")
    return {"success": True, "app": res["app"], "changed": res["changed"], "message": message}


@connect_router.post("/{app}/disconnect")
def disconnect_app(app: str, caller: dict = Depends(require_scopes("agents:manage"))):
    res = _run(connect_ai.disconnect, app)
    name = connect_ai.label(res["app"])
    return {"success": True, "app": res["app"], "changed": res["changed"],
            "message": f"{name} is disconnected." if res["changed"] else f"{name} wasn't connected."}


@connect_router.post("/{app}/test")
def test_app(app: str, caller: dict = Depends(require_scopes("agents:manage"))):
    return _run(connect_ai.check, app)
