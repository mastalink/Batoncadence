"""
Admin API - everything the CLI can do, over REST, for the Control Panel UI.

Three routers:
    /api/agents     (manage)  register / reset-token / edit / delete agents
    /api/settings   (admin)   read + write the operator-tunable configuration
    /api/workflows  (write)   submit a workflow DAG (the `mco workflow` parity)

Design rules:
- Settings writes go through a strict whitelist (SETTING_GROUPS). Unknown
  keys are rejected: the web surface must never become "write arbitrary env
  vars over HTTP". Secrets are write-only - reads return set/unset, never
  the value.
- Tokens are generated server-side, returned exactly once, and stored only
  as SHA-256 hashes - same contract as `mco register`.
- Tenant isolation: a non-default-org caller can only manage agents inside
  its own org.
"""

import hashlib
import logging
import re
import secrets as _secrets

from fastapi import APIRouter, Depends, HTTPException

from mco.config import get_config
from mco.editions import edition_summary
from mco.orchestrator import llm_connections
from mco.orchestrator.auth import KNOWN_SCOPES, normalize_scopes, require_scopes

logger = logging.getLogger("mco.orchestrator.admin")

# instance_id / role are rendered into the dashboard (and into shell-free
# argv elsewhere); constrain them to a safe identifier charset so a crafted
# value can never break out of an HTML/JS context in the Control Panel.
_IDENT_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")

agents_admin_router = APIRouter(prefix="/api/agents")
settings_router = APIRouter(prefix="/api/settings")
workflows_router = APIRouter(prefix="/api/workflows")
llm_connections_router = APIRouter(prefix="/api/llm-connections")
status_router = APIRouter(prefix="/api")


def _db():
    from mco.orchestrator.routes import get_db_client
    db_client = get_db_client()
    if not db_client:
        raise HTTPException(status_code=400, detail="Database not configured")
    return db_client


def _caller_org(agent: dict) -> str:
    return agent.get("org_id") or "default"


def allowed_orgs() -> list:
    """The configured org allowlist: 'default' plus MCO_ORGS (comma-separated).

    Orgs are tenant boundaries, so they are minted deliberately by an admin
    in Settings - never implicitly by whatever string arrives at
    registration (that is how a typo becomes an isolated tenant)."""
    raw = get_config().get("MCO_ORGS") or ""
    orgs = {"default"}
    orgs.update(o.strip() for o in str(raw).split(",") if o.strip())
    return sorted(orgs)


def _generate_token() -> tuple:
    token = "mco_tok_" + _secrets.token_hex(24)
    return token, hashlib.sha256(token.encode("utf-8")).hexdigest()


def _get_agent_row(db, instance_id: str, caller: dict) -> dict:
    res = db.table("agent_registry").select("*").eq("instance_id", instance_id).execute()
    rows = res.data or []
    if not rows or (rows[0].get("org_id") or "default") != _caller_org(caller):
        raise HTTPException(status_code=404, detail=f"Agent '{instance_id}' not found")
    return rows[0]


def _public(row: dict) -> dict:
    return {k: v for k, v in row.items() if k != "auth_token_hash"}


# ── Agent management ─────────────────────────────────────────────────────────

@agents_admin_router.get("/orgs")
async def list_orgs(caller: dict = Depends(require_scopes("agents:read"))):
    """Orgs available for registration (powers the Control Panel dropdown).

    Host operators see the configured allowlist plus any orgs already in use
    (so grandfathered tenants stay visible); org-scoped callers see only
    their own org - it is the only one they may register into anyway."""
    org = _caller_org(caller)
    if org != "default":
        return {"orgs": [org], "host_operator": False}
    in_use = set()
    try:
        res = _db().table("agent_registry").select("*").execute()
        in_use = {r.get("org_id") or "default" for r in (res.data or [])}
    except Exception as e:
        logger.debug(f"Org in-use scan skipped: {e}")
    return {
        "orgs": allowed_orgs(),
        "in_use": sorted(in_use),
        "host_operator": True,
    }


@agents_admin_router.post("")
async def register_agent(payload: dict, caller: dict = Depends(require_scopes("agents:manage"))):
    """Register a new agent and return its access token - shown exactly once.

    Stricter than `mco register`: an existing instance_id is a 409, never a
    silent token rotation. Use /reset-token for that, deliberately.
    """
    db = _db()
    instance_id = (payload.get("instance_id") or payload.get("name") or "").strip()
    role = (payload.get("role") or "").strip()
    if not instance_id or not role:
        raise HTTPException(status_code=400, detail="instance_id and role are required")
    if not _IDENT_RE.match(instance_id) or not _IDENT_RE.match(role):
        raise HTTPException(
            status_code=400,
            detail="instance_id and role may contain only letters, digits, and . _ : - (max 64 chars)",
        )

    scopes = normalize_scopes(payload.get("scopes"))
    unknown = [s for s in scopes if s not in KNOWN_SCOPES]
    if unknown:
        raise HTTPException(status_code=400,
                            detail=f"Unknown scope(s): {', '.join(unknown)}. "
                                   f"Valid: {', '.join(sorted(KNOWN_SCOPES))}")

    existing = db.table("agent_registry").select("*").eq("instance_id", instance_id).execute()
    if existing.data:
        raise HTTPException(status_code=409,
                            detail=f"Agent '{instance_id}' already exists. Use reset-token to rotate its token.")

    # Host operators (default org) may stamp any ALLOWED org; org admins stay
    # home. Unknown orgs are rejected, not silently created.
    org = _caller_org(caller)
    if org == "default":
        org = (payload.get("org") or "default").strip() or "default"
        if org not in allowed_orgs():
            raise HTTPException(
                status_code=400,
                detail=(f"Org '{org}' is not configured. Allowed: "
                        f"{', '.join(allowed_orgs())}. Add it in Settings -> "
                        f"Tenancy (MCO_ORGS) first - orgs are isolation "
                        f"boundaries, minted deliberately."))

    token, token_hash = _generate_token()
    data = {"instance_id": instance_id, "role": role, "status": "offline",
            "auth_token_hash": token_hash}
    if org != "default":
        data["org_id"] = org
    if scopes:
        data["scopes"] = scopes
    try:
        res = db.table("agent_registry").insert(data).execute()
    except Exception:
        if scopes:
            # Pre-migration database without the scopes column.
            data.pop("scopes", None)
            res = db.table("agent_registry").insert(data).execute()
        else:
            raise
    if not res.data:
        raise HTTPException(status_code=500, detail="Registration failed to persist")
    logger.info(f"Agent '{instance_id}' registered via API by {caller.get('instance_id')}")
    return {"success": True, "agent": _public(res.data[0]), "token": token}


@agents_admin_router.post("/{instance_id}/reset-token")
async def reset_agent_token(instance_id: str, caller: dict = Depends(require_scopes("agents:manage"))):
    """Rotate an agent's access token. The old token stops working immediately;
    the new one is returned exactly once."""
    db = _db()
    _get_agent_row(db, instance_id, caller)
    token, token_hash = _generate_token()
    res = db.table("agent_registry").update({"auth_token_hash": token_hash})\
        .eq("instance_id", instance_id).execute()
    if not res.data:
        raise HTTPException(status_code=500, detail="Token reset failed to persist")
    logger.info(f"Token rotated for '{instance_id}' by {caller.get('instance_id')}")
    return {"success": True, "instance_id": instance_id, "token": token}


@agents_admin_router.patch("/{instance_id}")
async def update_agent(instance_id: str, payload: dict,
                       caller: dict = Depends(require_scopes("agents:manage"))):
    """Edit an agent's role, scopes, or status."""
    db = _db()
    _get_agent_row(db, instance_id, caller)
    update = {}
    if payload.get("role"):
        update["role"] = str(payload["role"]).strip()
    if "scopes" in payload:
        scopes = normalize_scopes(payload.get("scopes"))
        unknown = [s for s in scopes if s not in KNOWN_SCOPES]
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unknown scope(s): {', '.join(unknown)}")
        update["scopes"] = scopes or None  # empty list -> role-derived defaults
    if payload.get("status") in ("online", "offline", "disabled"):
        update["status"] = payload["status"]
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update (role, scopes, status)")
    res = db.table("agent_registry").update(update).eq("instance_id", instance_id).execute()
    if not res.data:
        raise HTTPException(status_code=500, detail="Update failed to persist")
    return {"success": True, "agent": _public(res.data[0])}


@agents_admin_router.delete("/{instance_id}")
async def delete_agent(instance_id: str, caller: dict = Depends(require_scopes("agents:manage"))):
    """Remove an agent registration. Its token stops working immediately."""
    db = _db()
    _get_agent_row(db, instance_id, caller)
    db.table("agent_registry").delete().eq("instance_id", instance_id).execute()
    logger.info(f"Agent '{instance_id}' deleted by {caller.get('instance_id')}")
    return {"success": True, "instance_id": instance_id}


# ── Settings (the Control Panel back end) ────────────────────────────────────
#
# Every entry: type bool|text|secret|choice, a label, and the group it renders
# under. This metadata is served to the UI so the panel always matches the
# whitelist - one source of truth.

SETTING_GROUPS = {
    "governance": {
        "MCO_KILL_SWITCH": {"type": "bool", "label": "Kill switch (pause all new jobs and leases)"},
        "MCO_APPROVER_ROLES": {"type": "text", "label": "Approver roles (comma-separated)",
                               "placeholder": "human,admin,operator"},
        "MCO_POLICY_GATED_ROLES": {"type": "text", "label": "Always-gated roles (jobs to these pause for a human)",
                                   "placeholder": "servicenow,dynatrace"},
        "MCO_ESCALATION_CONNECTOR": {"type": "text", "label": "Escalation connector (mirror terminal failures to ITSM)",
                                     "placeholder": "servicenow"},
    },
    "memory": {
        "MCO_DRUMLINE_DISTILL": {"type": "bool", "label": "Distill completed jobs into shared memory", "default": True},
        "MCO_DRUMLINE_INJECT": {"type": "bool", "label": "Inject shared memory into worker prompts", "default": True},
    },
    "presence": {
        "MCO_AGENT_OFFLINE_AFTER": {"type": "text",
                                    "label": "Mark an agent offline after no contact for (seconds)",
                                    "placeholder": "300"},
    },
    "observability": {
        "MCO_METRICS_TOKEN": {"type": "secret",
                              "label": "Protect /metrics with a bearer token (blank = open, like /healthz)"},
        "MCO_LOG_JSON": {"type": "bool",
                         "label": "Structured JSON logs (restart to apply)"},
    },
    "tenancy": {
        "MCO_ORGS": {"type": "text",
                     "label": "Allowed orgs (comma-separated; 'default' always exists). "
                              "Orgs are isolation boundaries - agents only see jobs and "
                              "memory inside their own org.",
                     "placeholder": "acme, beta-team"},
    },
    "edition": {
        "MCO_EDITION": {"type": "choice", "label": "Edition (blank = infer from configuration)",
                        "choices": ["", "community", "team", "enterprise"]},
    },
    "security": {
        "MCO_TRUSTED_HEADER_AUTH": {"type": "bool", "label": "Trusted-header SSO (only behind an auth proxy!)"},
        "MCO_TRUSTED_HEADER_USER": {"type": "text", "label": "Identity header",
                                    "placeholder": "X-Forwarded-User"},
        "MCO_TRUSTED_HEADER_ROLE": {"type": "text", "label": "Role header",
                                    "placeholder": "X-Forwarded-Role"},
        "MCO_TRUSTED_HEADER_DEFAULT_ROLE": {"type": "text", "label": "Default role for SSO users",
                                            "placeholder": "human"},
        "MCO_TRUSTED_HEADER_SECRET": {"type": "secret", "label": "Proxy shared secret (X-MCO-Proxy-Secret)"},
        "MCO_WEBHOOK_SECRET": {"type": "secret", "label": "Inbound webhook secret (enables /webhook ingestion)"},
    },
    "notifications": {
        "NTFY_SERVER": {"type": "text", "label": "ntfy server", "placeholder": "https://ntfy.sh"},
        "NTFY_TOPIC": {"type": "text", "label": "ntfy topic (blank = notifications off)"},
    },
}

_ALL_SETTINGS = {k: (g, meta) for g, keys in SETTING_GROUPS.items() for k, meta in keys.items()}

_TRUTHY = ("1", "true", "on", "yes")


@settings_router.get("")
async def get_settings(caller: dict = Depends(require_scopes("admin"))):
    """Current settings (secrets masked to set/unset), UI metadata, the
    edition matrix, and the scope vocabulary - everything the Control Panel
    needs in one call."""
    config = get_config()
    groups = {}
    for group, keys in SETTING_GROUPS.items():
        groups[group] = []
        for key, meta in keys.items():
            raw = config.get(key)
            if meta["type"] == "secret":
                value = bool(raw)  # never echo the secret itself
            elif meta["type"] == "bool":
                value = str(raw or meta.get("default", False)).lower() in _TRUTHY \
                    if raw is not None else bool(meta.get("default", False))
            else:
                value = raw or ""
            groups[group].append({"key": key, "value": value, **meta})
    return {
        "groups": groups,
        "edition": edition_summary(),
        "known_scopes": sorted(KNOWN_SCOPES),
    }


@settings_router.put("")
async def put_settings(payload: dict, caller: dict = Depends(require_scopes("admin"))):
    """Apply settings changes. Only whitelisted keys; values persist to the
    global config home (~/.mco/.env) and take effect immediately in-process.
    Empty string clears a key back to its default."""
    if not isinstance(payload, dict) or not payload:
        raise HTTPException(status_code=400, detail="Provide a {KEY: value} object")
    unknown = [k for k in payload if k not in _ALL_SETTINGS]
    if unknown:
        raise HTTPException(status_code=400,
                            detail=f"Not settable via API: {', '.join(unknown)}")
    config = get_config()
    applied = {}
    for key, value in payload.items():
        meta = _ALL_SETTINGS[key][1]
        if meta["type"] == "bool":
            value = "true" if (value is True or str(value).lower() in _TRUTHY) else "false"
        elif meta["type"] == "choice":
            if str(value) not in meta["choices"]:
                raise HTTPException(status_code=400,
                                    detail=f"{key}: must be one of {meta['choices']}")
            value = str(value)
        else:
            value = str(value or "")
        if value == "":
            config.delete(key)
            applied[key] = None
        else:
            config.set(key, value)
            applied[key] = True if meta["type"] == "secret" else value
        logger.info(f"Setting {key} changed via API by {caller.get('instance_id')}")
    return {"success": True, "applied": applied}


# ── Workflows (mco workflow parity) ──────────────────────────────────────────

@workflows_router.post("")
async def submit_workflow_api(payload: dict, caller: dict = Depends(require_scopes("jobs:write"))):
    """Submit a workflow DAG: {"yaml": "..."} or {"name": ..., "steps": [...]}.

    Validates (ids, deps, cycles), then creates every step through the same
    create_job path the REST API uses - governance, audit, broadcast, and
    Context Exchange run-stamping all included. Returns {step_id: job_id}.
    """
    import uuid
    from mco.orchestrator.workflows import WorkflowError, load_workflow, topo_order
    from mco.orchestrator.routes import create_job

    source = payload.get("yaml") if isinstance(payload, dict) and payload.get("yaml") else payload
    try:
        workflow = load_workflow(source)
    except WorkflowError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse workflow: {e}")

    name = workflow["name"]
    run_id = uuid.uuid4().hex[:12]
    job_ids = {}
    for step in topo_order(workflow["steps"]):
        step_id = step["id"]
        instructions = step.get("instructions") or step.get("title") or ""
        job_payload = {
            "title": step.get("title") or f"{name}:{step_id}",
            "description": instructions,
            "target_agent_role": step["role"],
            "target_agent_id": step.get("instance"),
            "depends_on": [job_ids[d] for d in (step.get("depends_on") or [])],
            "input_payload": {
                "prompt": instructions,
                "workflow": {"name": name, "run": run_id, "step": step_id},
            },
            "requires_approval": bool(step.get("requires_approval")),
            "max_retries": int(step.get("max_retries") or 0),
            "escalate_to_role": step.get("escalate_to_role"),
        }
        res = await create_job(job_payload, caller)
        job = (res or {}).get("job") or {}
        if not res.get("success") or not job.get("id"):
            raise HTTPException(status_code=500,
                                detail=f"Step '{step_id}' failed to submit (created so far: {job_ids})")
        job_ids[step_id] = job["id"]
    return {"success": True, "workflow": name, "run": run_id, "jobs": job_ids}


# ── LLM Provider Connections ("Model Connections" in the Control Panel) ──────
#
# Named, testable connections to LLM providers. See llm_connections.py for
# why the API key is never stored in the llm_connections table itself.

def _llm_public(row: dict, key_set: bool) -> dict:
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "provider": row.get("provider"),
        "base_url": row.get("base_url"),
        "model": row.get("model"),
        "org_id": row.get("org_id") or "default",
        "created_at": row.get("created_at"),
        "key_set": key_set,
    }


def _get_llm_row(db, conn_id: str, caller: dict) -> dict:
    res = db.table("llm_connections").select("*").eq("id", conn_id).execute()
    rows = res.data or []
    if not rows or (rows[0].get("org_id") or "default") != _caller_org(caller):
        raise HTTPException(status_code=404, detail=f"Connection '{conn_id}' not found")
    return rows[0]


@llm_connections_router.get("/providers")
async def list_llm_providers(caller: dict = Depends(require_scopes("admin"))):
    """Provider metadata for the Add Connection form."""
    return {p: {"label": m["label"], "base_url_editable": m["base_url"] is None}
            for p, m in llm_connections.PROVIDERS.items()}


@llm_connections_router.get("")
async def list_llm_connections(caller: dict = Depends(require_scopes("admin"))):
    db = _db()
    res = db.table("llm_connections").select("*").execute()
    rows = [r for r in (res.data or []) if (r.get("org_id") or "default") == _caller_org(caller)]
    config = get_config()
    return [_llm_public(r, bool(config.get(llm_connections.config_key_for(r["id"]))))
            for r in rows]


@llm_connections_router.post("")
async def create_llm_connection(payload: dict, caller: dict = Depends(require_scopes("admin"))):
    name = (payload.get("name") or "").strip()
    provider = (payload.get("provider") or "").strip().lower()
    base_url = (payload.get("base_url") or "").strip() or None
    model = (payload.get("model") or "").strip() or None
    api_key = (payload.get("api_key") or "").strip()

    if not name or not provider:
        raise HTTPException(status_code=400, detail="name and provider are required")
    if not _IDENT_RE.match(name):
        raise HTTPException(status_code=400,
                            detail="name may contain only letters, digits, and . _ : - (max 64 chars)")
    if provider not in llm_connections.PROVIDERS:
        raise HTTPException(status_code=400,
                            detail=f"Unknown provider '{provider}'. Valid: {', '.join(sorted(llm_connections.PROVIDERS))}")
    if provider == "custom" and not base_url:
        raise HTTPException(status_code=400, detail="base_url is required for a custom connection")
    if provider != "custom":
        # Built-in providers use a fixed URL - never let the client steer an
        # outbound request an operator didn't intend (SSRF guard).
        base_url = None

    db = _db()
    row = {"name": name, "provider": provider, "base_url": base_url, "model": model}
    if _caller_org(caller) != "default":
        row["org_id"] = _caller_org(caller)
    res = db.table("llm_connections").insert(row).execute()
    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to persist connection")
    saved = res.data[0]

    if api_key:
        get_config().set(llm_connections.config_key_for(saved["id"]), api_key)

    logger.info(f"LLM connection '{name}' ({provider}) created by {caller.get('instance_id')}")
    return {"success": True, "connection": _llm_public(saved, bool(api_key))}


@llm_connections_router.patch("/{conn_id}")
async def update_llm_connection(conn_id: str, payload: dict,
                                caller: dict = Depends(require_scopes("admin"))):
    """Edit name/model/base_url, and optionally rotate the API key. A blank
    api_key leaves the stored key untouched (mirrors the Settings pattern)."""
    db = _db()
    row = _get_llm_row(db, conn_id, caller)
    update = {}
    if "name" in payload:
        name = str(payload["name"]).strip()
        if not _IDENT_RE.match(name):
            raise HTTPException(status_code=400,
                                detail="name may contain only letters, digits, and . _ : - (max 64 chars)")
        update["name"] = name
    if "model" in payload:
        update["model"] = str(payload["model"]).strip() or None
    if row.get("provider") == "custom" and "base_url" in payload:
        base_url = str(payload["base_url"]).strip()
        if not base_url:
            raise HTTPException(status_code=400, detail="base_url is required for a custom connection")
        update["base_url"] = base_url

    api_key = str(payload.get("api_key") or "").strip()
    if api_key:
        get_config().set(llm_connections.config_key_for(conn_id), api_key)

    if not update and not api_key:
        raise HTTPException(status_code=400, detail="Nothing to update")

    if update:
        res = db.table("llm_connections").update(update).eq("id", conn_id).execute()
        if not res.data:
            raise HTTPException(status_code=500, detail="Update failed to persist")
        row = res.data[0]

    key_set = bool(get_config().get(llm_connections.config_key_for(conn_id)))
    return {"success": True, "connection": _llm_public(row, key_set)}


@llm_connections_router.delete("/{conn_id}")
async def delete_llm_connection(conn_id: str, caller: dict = Depends(require_scopes("admin"))):
    db = _db()
    _get_llm_row(db, conn_id, caller)
    db.table("llm_connections").delete().eq("id", conn_id).execute()
    get_config().delete(llm_connections.config_key_for(conn_id))
    logger.info(f"LLM connection '{conn_id}' deleted by {caller.get('instance_id')}")
    return {"success": True, "id": conn_id}


@llm_connections_router.post("/{conn_id}/test")
async def test_llm_connection(conn_id: str, caller: dict = Depends(require_scopes("admin"))):
    """Make one cheap, real call to the provider to prove the key/base_url
    actually authenticate. Never returns the key itself."""
    db = _db()
    row = _get_llm_row(db, conn_id, caller)
    api_key = get_config().get(llm_connections.config_key_for(conn_id)) or ""
    return llm_connections.test_connection(row.get("provider"), api_key, row.get("base_url"))


# ── Diagnostics + migrations (mco doctor / mco status / mco upgrade parity) ──

@status_router.get("/doctor")
async def api_doctor(caller: dict = Depends(require_scopes("admin"))):
    """Structured diagnostics for the machine running this gateway."""
    import shutil
    import sys as _sys
    from mco.config import resolve_env_path
    from mco.editions import current_edition
    from mco.notifiers.ntfy import get_ntfy_config
    from mco.orchestrator.routes import (
        get_db_client, decorate_presence, get_offline_after_seconds, kill_switch_active,
    )
    from mco.security import get_secret_store

    checks = []

    def add(level, label, detail=None):
        checks.append({"level": level, "label": label, "detail": detail})

    v = _sys.version_info
    if v >= (3, 9):
        add("ok", f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        add("bad", f"Python {v.major}.{v.minor} is too old (3.9+ required)",
            "Re-run the installer; it finds or installs a supported Python.")

    config = get_config()
    env_path = resolve_env_path()
    if env_path.is_file():
        token = (config.get("MCO_LOCAL_TOKEN") or "").strip()
        add("ok", f"Config: {env_path}", "MCO_LOCAL_TOKEN set" if token else "no MCO_LOCAL_TOKEN")
    else:
        add("warn", f"No config file at {env_path}", "Run 'mco setup' to create one.")

    store = get_secret_store()
    if not store.is_initialized():
        add("ok", "Secret store: off (plaintext .env mode)")
    elif store.is_unlocked or store.auto_unlock():
        add("ok", "Secret store: unlocked")
    else:
        add("warn", f"Secret store at {store._path} is locked (no working key)",
            "Run 'mco setup --menu' -> security to unlock or recreate it.")

    add("ok", f"Edition: {current_edition()}")

    db = get_db_client()
    if db is None:
        add("warn", "No database (MCO_DISABLE_LOCAL_DB is set?)")
    else:
        backend = getattr(db, "backend", "supabase")
        try:
            res = db.table("agent_registry").select("*").execute()
            agents = res.data or []
            threshold = get_offline_after_seconds()
            online = sum(1 for a in agents
                        if decorate_presence(dict(a), threshold)["effective_status"] == "online")
            add("ok", f"Database: {'embedded LocalStore' if backend == 'local' else 'Supabase'} reachable",
                f"{len(agents)} agent(s) registered, {online} online")
        except Exception as e:
            add("bad", f"Database query failed ({backend})", type(e).__name__)

    if kill_switch_active():
        add("warn", "Kill switch: ACTIVE - no new jobs or leases")
    else:
        add("ok", "Kill switch: off")

    found = {name: bool(shutil.which(name)) for name in ("claude", "codex", "gemini", "git", "docker")}
    add("ok", "Vendor CLIs (on this machine)",
        ", ".join(f"{k}={'yes' if v else 'no'}" for k, v in found.items()))

    ntfy_cfg = get_ntfy_config()
    if ntfy_cfg.get("server") and ntfy_cfg.get("topic"):
        add("ok", f"Notifications: ntfy -> {ntfy_cfg['server']}/{ntfy_cfg['topic']}")
    else:
        add("warn", "Notifications: off", "Set NTFY_TOPIC to enable push alerts.")

    return {"checks": checks}


@status_router.get("/migrations")
async def api_migrations_status(caller: dict = Depends(require_scopes("admin"))):
    import os as _os
    from mco import migrations_runner as mig

    kind = mig.backend_kind()
    all_migs = [n for n, _ in mig.discover()]
    if kind != "postgres":
        note = "Embedded LocalStore needs no migrations - rows pick up new fields automatically." \
            if kind == "local" else "No database configured."
        return {"backend_kind": kind, "all": all_migs, "pending": [], "can_apply": False, "note": note}

    database_url = (get_config().get("DATABASE_URL") or _os.environ.get("DATABASE_URL") or "").strip()
    _, pending = mig.write_combined_script()
    return {"backend_kind": kind, "all": all_migs, "pending": pending, "can_apply": bool(database_url)}


@status_router.post("/migrations/apply")
async def api_migrations_apply(caller: dict = Depends(require_scopes("admin"))):
    import os as _os
    from mco import migrations_runner as mig

    kind = mig.backend_kind()
    if kind != "postgres":
        raise HTTPException(status_code=400,
                            detail="Only the Postgres/Supabase backend supports applying migrations here.")
    database_url = (get_config().get("DATABASE_URL") or _os.environ.get("DATABASE_URL") or "").strip()
    if not database_url:
        raise HTTPException(status_code=400,
                            detail="DATABASE_URL is not configured - apply the pending SQL manually in the Supabase SQL editor.")
    try:
        result = mig.apply_postgres(database_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Migration failed: {type(e).__name__}")
    logger.info(f"Migrations applied via API by {caller.get('instance_id')}: {result.get('applied')}")
    return {"success": True, **result}
