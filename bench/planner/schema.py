"""Planner plan schema + mapping onto the real Score v1 contract.

Why two shapes: a Score v1 task carries 14 required fields (resources, evidence,
timeout, cost caps...). Asking a 1-3B model to author all of that wastes tokens and
invites errors. The model fills in a COMPACT plan (PLAN_SCHEMA); `to_score()` expands
it deterministically into a document that validates against docs/score-v1.schema.json.

Safety gates are code, not model output: `enforce_gates()` forces an approval on every
step that publishes, spends, or deletes, whatever the model (or the user's request,
e.g. "skip approvals") said. The benchmark scores the model's RAW gate placement
separately so we know how much the code is catching.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# action -> (effect class, risky?)  Risky = publishes, spends, deletes, or sends to others.
ACTIONS = {
    "read_file": "read", "search_web": "read", "fetch_data": "read",
    "summarize": "none", "draft_text": "write", "write_file": "write",
    "move_copy": "write", "create_event": "write", "notify": "none",
    "ask_user": "none", "wait": "none", "check_condition": "none", "run_code": "write",
    "send_email": "publish", "publish": "publish", "buy": "spend", "pay": "spend",
    "delete": "delete",
    "other": "unknown",  # the model could not map the step to a known verb -> escalation signal
}
EFFECTS = ["none", "read", "write", "publish", "spend", "delete", "unknown"]
RISKY_EFFECTS = {"publish", "spend", "delete"}
RISKY_ACTIONS = {a for a, e in ACTIONS.items() if e in RISKY_EFFECTS}
SCHEDULE_KINDS = ["on_demand", "once", "hourly", "daily", "weekly", "monthly"]
MAX_STEPS = 10
STEP_IDS = [f"s{i}" for i in range(1, MAX_STEPS + 1)]

PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "schedule", "steps", "confidence"],
    "properties": {
        "title": {"type": "string", "minLength": 1, "maxLength": 80},
        "schedule": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "detail"],
            "properties": {
                "kind": {"enum": SCHEDULE_KINDS},
                "detail": {"type": "string", "maxLength": 60},  # e.g. "Mondays 09:00"; "" if none
            },
        },
        "steps": {
            "type": "array",
            "minItems": 1,
            "maxItems": MAX_STEPS,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "action", "what", "depends_on", "condition", "needs_approval"],
                "properties": {
                    "id": {"enum": STEP_IDS},
                    "action": {"enum": list(ACTIONS)},
                    "what": {"type": "string", "minLength": 1, "maxLength": 120},
                    "depends_on": {"type": "array", "maxItems": 4, "items": {"enum": STEP_IDS}},
                    "condition": {"type": "string", "maxLength": 80},  # "" unless this step is a branch
                    "needs_approval": {"type": "boolean"},
                },
            },
        },
        "confidence": {"enum": ["low", "medium", "high"]},
    },
}


# ---------- semantic validation (JSON schema cannot express these) ----------
def semantic_errors(plan: dict) -> list[str]:
    errs, seen = [], []
    for s in plan["steps"]:
        if s["id"] in seen:
            errs.append(f"duplicate id {s['id']}")
        for d in s["depends_on"]:
            if d not in seen:  # must reference an EARLIER step -> guarantees a DAG, no cycles
                errs.append(f"{s['id']} depends on {d} which is not an earlier step")
        seen.append(s["id"])
    return errs


def risky(step: dict) -> bool:
    return step["action"] in RISKY_ACTIONS


def enforce_gates(plan: dict) -> dict:
    """Code-enforced safety: every risky step needs approval. Never trusts the model."""
    out = json.loads(json.dumps(plan))
    for s in out["steps"]:
        if risky(s):
            s["needs_approval"] = True
    return out


# ---------- mapping onto Score v1 ----------
_SCORE_SCHEMA = Path(__file__).resolve().parents[2] / "docs" / "score-v1.schema.json"
_CAPS = {"read": "read-only", "write": "local-write", "publish": "external-publish",
         "spend": "spend-money", "delete": "delete-data", "none": "no-effect", "unknown": "no-effect"}


def to_score(plan: dict, plan_id: str = "ask-for-something", budget_cents: int = 0) -> dict:
    """Expand a compact plan to a Score v1 document (validated by the caller/tests)."""
    plan = enforce_gates(plan)
    slug = re.sub(r"[^a-z0-9]+", "-", plan["title"].lower()).strip("-")[:40] or "plan"
    tasks = []
    for s in plan["steps"]:
        eff = ACTIONS[s["action"]]
        instr = s["what"] + (f" (only if: {s['condition']})" if s["condition"] else "")
        tasks.append({
            "id": s["id"], "goal": s["what"], "title": f"{s['action']}: {s['what']}"[:100],
            "instructions": instr, "role": "worker", "review_role": "reviewer",
            "depends_on": list(s["depends_on"]), "resources": [f"plan:{slug}"],
            "capabilities": [_CAPS[eff]], "evidence": ["step result recorded"],
            "max_attempts": 1, "timeout_seconds": 600, "max_cost_cents": 0,
            "checkpoint": ({"id": f"approve-{s['id']}", "reason": f"{s['action']} needs your approval"}
                           if s["needs_approval"] else None),
        })
    constraints = ["Risky steps (publish, spend, delete) pause for human approval"]
    if plan["schedule"]["kind"] != "on_demand":
        constraints.append(f"Schedule: {plan['schedule']['kind']} {plan['schedule']['detail']}".strip())
    return {
        "score_version": 1, "id": f"{plan_id}-{slug}", "revision": 1, "objective": plan["title"],
        "constraints": constraints, "budget_cents": budget_cents, "max_parallel": 1,
        "launch_requires": ["owner approves the flowchart"], "tasks": tasks,
    }


def validate_score(score: dict) -> list[str]:
    import jsonschema
    schema = json.loads(_SCORE_SCHEMA.read_text(encoding="utf-8"))
    return [e.message for e in jsonschema.Draft202012Validator(schema).iter_errors(score)]
