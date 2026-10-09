"""Plain-language planning for "Ask for something".

One planner serves every front door: `bitcadence ask` (plain.do_ask), and the
console's Ask page through /api/ask/plan and /api/ask/start. Spec:
design/redesign-v1/05-ask.html.

A *plan* is a plain dict (no classes, so it round-trips through JSON):

    {"request": str, "steps": [step...], "repeat": None | {...}}

with each step ``{"id", "label", "icon", "role", "instructions",
"depends_on", "gate", "note"}``. The tweaks people are allowed are light:
remove a step, always ask me at the end, make it repeat. Anything bigger means
editing the request and drafting again, so the planner stays deterministic and
the console can send the tweaks back with the request instead of the server
remembering state.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

MAX_STEPS = 8

MAX_REQUEST_CHARS = 2000

# No \s* around the separators: a leading \s* is retried at every position of a
# long run of spaces (polynomial time). Clauses are .strip()ped after the split.
_SPLIT = re.compile(
    r"(?:,|;|\bthen\b|\band\b(?=\s+(?:ask me|check with me|confirm with me|get my ok|wait for me)\b))", re.I)
_LEAD_AND = re.compile(r"^(?:and|also|finally)\s+", re.I)
_PASS_WORDS = r"(?:green|passing|passes|pass|ok|clean|good|successful)"
_CONDITION = re.compile(rf"^if\s+(?:everything\s+|it\s+|they\s+|all\s+)?(?:is\s+|are\s+)?{_PASS_WORDS}\b[\s,]*", re.I)
# Only the fixed lead phrase is matched by regex; _gate_rest() trims the rest in
# plain Python, so no \s* sits next to a (.*) that could backtrack against it.
_ASK_ME = re.compile(r"^(?:ask me|check with me|confirm with me|get my ok|wait for me)\b", re.I)
_GATE_JOINERS = ("to ", "before ", "if ")


def _gate_rest(clause: str, lead_end: int) -> str:
    rest = clause[lead_end:].lstrip()
    for joiner in _GATE_JOINERS:
        if rest.lower().startswith(joiner):
            return rest[len(joiner):].lstrip()
    return rest

_ICONS = (
    (("research", "look", "find", "check", "review", "read", "search", "scan", "list"), "🔎"),
    (("test", "run the test", "verify", "validate"), "🧪"),
    (("write", "draft", "summarize", "summarise", "compose", "document"), "📝"),
    (("publish", "release", "deploy", "send", "post", "email"), "🚀"),
    (("fix", "repair", "update", "change", "clean", "tidy"), "🛠️"),
)
_PUBLISH = {"publish": "publishing", "release": "releasing", "send": "sending", "post": "posting",
            "deploy": "deploying", "email": "emailing", "merge": "merging", "delete": "deleting"}
_DAYS = {"monday": 1, "tuesday": 2, "wednesday": 3, "thursday": 4, "friday": 5, "saturday": 6, "sunday": 0}


class PlanError(ValueError):
    """A tweak or request that cannot be applied. The message is plain words."""


def _icon_for(text: str) -> str:
    lowered = text.lower()
    for words, icon in _ICONS:
        if any(re.search(rf"\b{re.escape(w)}", lowered) for w in words):
            return icon
    return "⚙️"


def _sentence(text: str) -> str:
    text = text.strip().rstrip(".")
    return text[:1].upper() + text[1:] if text else text


def _label_for(clause: str) -> str:
    # "Research open PRs" reads better to a person as "Look at open pull requests".
    clause = re.sub(r"^research\b", "look at", clause.strip(), flags=re.I)
    clause = re.sub(r"\bPRs\b", "pull requests", clause)
    clause = re.sub(r"\bPR\b", "pull request", clause)
    return _sentence(clause)


def _gate_label(rest: str) -> str:
    rest = rest.strip().rstrip(".")
    first, _, tail = rest.partition(" ")
    if first.lower() in _PUBLISH:
        return f"Ask you before {_PUBLISH[first.lower()]}" + (f" {tail}" if tail else "")
    if rest:
        return f"Ask you first: {rest}"
    return "Ask you before finishing"


def draft_plan(request: str, role: str = "claude") -> Dict[str, Any]:
    """Turn a request into a short chain of steps. One clause is one step."""
    request = " ".join((request or "").split())
    if not request:
        raise PlanError("Tell me what you want done.")
    if len(request) > MAX_REQUEST_CHARS:
        raise PlanError(f"That's too long. Keep it under {MAX_REQUEST_CHARS} characters.")
    clauses = [_LEAD_AND.sub("", c).strip() for c in _SPLIT.split(request)]
    clauses = [c for c in clauses if c][:MAX_STEPS]
    steps: List[dict] = []
    for clause in clauses:
        note = ""
        condition = _CONDITION.match(clause)
        if condition:
            note = "If everything passes"
            clause = clause[condition.end():].strip() or clause
        gate_match = _ASK_ME.match(clause)
        step_id = f"step-{len(steps) + 1}"
        if gate_match:
            rest = _gate_rest(clause, gate_match.end())
            steps.append({"id": step_id, "label": _gate_label(rest), "icon": "✋", "role": role,
                          "instructions": "Wait for the owner's OK" + (f" to {rest.strip().rstrip('.')}." if rest.strip() else "."), "depends_on": [],
                          "gate": True, "note": note})
        else:
            steps.append({"id": step_id, "label": _label_for(clause), "icon": _icon_for(clause), "role": role,
                          "instructions": clause if len(clauses) > 1 else request, "depends_on": [],
                          "gate": False, "note": note})
        if len(steps) > 1:
            steps[-1]["depends_on"] = [steps[-2]["id"]]
    return {"request": request, "steps": steps, "repeat": None}


def remove_step(plan: dict, step_id: str) -> dict:
    steps = plan["steps"]
    victim = next((s for s in steps if s["id"] == step_id), None)
    if victim is None:
        raise PlanError("That step is not in the plan.")
    if len(steps) == 1:
        raise PlanError("A plan needs at least one step. Change your request instead.")
    kept = [s for s in steps if s["id"] != step_id]
    for step in kept:
        deps: List[str] = []
        for dep in step["depends_on"]:
            deps.extend(victim["depends_on"] if dep == step_id else [dep])
        step["depends_on"] = list(dict.fromkeys(deps))
    return dict(plan, steps=kept)


def ask_at_end(plan: dict) -> dict:
    """Always ask me before it finishes. Safe to apply twice."""
    steps = plan["steps"]
    if steps[-1]["gate"]:
        return plan
    last = steps[-1]
    taken = [int(m.group(1)) for s in steps if (m := re.fullmatch(r"step-(\d+)", s["id"]))]
    gate = {"id": f"step-{max(taken, default=0) + 1}", "label": "Ask you before finishing", "icon": "✋",
            "role": last["role"], "instructions": "Wait for the owner's OK before this counts as done.",
            "depends_on": [last["id"]], "gate": True, "note": ""}
    return dict(plan, steps=steps + [gate])


def parse_repeat(phrase: str) -> Dict[str, str]:
    """"every Friday at 9 AM" -> {"cron": "0 9 * * 5", "words": "Every Friday at 9:00 AM"}."""
    text = " ".join((phrase or "").lower().split())
    clock = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", text)
    hour, minute = 9, 0
    if clock:
        hour = int(clock.group(1))
        minute = int(clock.group(2) or 0)
        meridiem = clock.group(3)
        if meridiem == "pm" and hour < 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        if hour > 23 or minute > 59:
            raise PlanError("That time of day is not valid. Try: every Friday at 9 AM.")
    shown = f"{(hour % 12) or 12}:{minute:02d} {'AM' if hour < 12 else 'PM'}"
    day = next((name for name in _DAYS if name in text), None)
    if day:
        return {"cron": f"{minute} {hour} * * {_DAYS[day]}", "words": f"Every {day.title()} at {shown}"}
    if "weekday" in text:
        return {"cron": f"{minute} {hour} * * 1-5", "words": f"Every weekday at {shown}"}
    if re.search(r"\b(every ?day|daily|each day)\b", text):
        return {"cron": f"{minute} {hour} * * *", "words": f"Every day at {shown}"}
    raise PlanError("Say how often, for example: every Friday at 9 AM, every weekday, or every day at 7 AM.")


def make_repeat(plan: dict, phrase: str) -> dict:
    return dict(plan, repeat=dict(parse_repeat(phrase), phrase=phrase))


def apply_tweaks(plan: dict, *, remove: Optional[List[str]] = None, ask_end: bool = False,
                 repeat: str = "") -> dict:
    """Apply the three light tweaks in a fixed order, so the same inputs always draw the same plan."""
    for step_id in remove or []:
        plan = remove_step(plan, step_id)
    if ask_end:
        plan = ask_at_end(plan)
    if repeat:
        plan = make_repeat(plan, repeat)
    return plan


def plan_lines(plan: dict) -> List[str]:
    """The plan as plain text, for the terminal (no icons: not every terminal can show them)."""
    lines: List[str] = []
    for number, step in enumerate(plan["steps"], 1):
        if step.get("note"):
            lines.append(f"      ({step['note'].lower()})")
        lines.append(f"  {number}. {step['label']}")
    if plan.get("repeat"):
        lines.append(f"  Repeats: {plan['repeat']['words']}")
    return lines


def new_run() -> str:
    return uuid.uuid4().hex[:12]


def step_job(plan: dict, index: int, ids: Dict[str, str], run: str, *, first_step_waits: bool) -> Dict[str, Any]:
    """The job to create for step ``index``, given the jobs made for earlier steps.

    Shared by the terminal (submit_plan) and the gateway's /api/ask/start so both
    create identical jobs.
    """
    step = plan["steps"][index]
    request = plan["request"]
    name = request if len(request) <= 70 else request[:67] + "..."
    return {
        "to_role": step["role"], "title": step["label"] if len(plan["steps"]) > 1 else name,
        "instructions": step["instructions"],
        "depends_on": [ids[d] for d in step["depends_on"]],
        "requires_approval": bool(step["gate"] or (index == 0 and first_step_waits)),
        "max_retries": 1,
        "extra_payload": {"workflow": {"name": name, "run": run, "step": step["id"]}},
    }


def submit_plan(send: Callable[..., dict], plan: dict, *, first_step_waits: bool) -> Dict[str, str]:
    """Create one job per step, chained with depends_on, through ``send``.

    ``send`` is GatewayClient.send-shaped. ``first_step_waits`` keeps the CLI's
    "wait for my OK" on the first job; the console passes False because the
    Approve button was that OK. Gate steps always wait.
    """
    run = new_run()
    ids: Dict[str, str] = {}
    for index, step in enumerate(plan["steps"]):
        res = send(**step_job(plan, index, ids, run, first_step_waits=first_step_waits))
        job = (res or {}).get("job") or {}
        if not (res or {}).get("success") or not job.get("id"):
            raise PlanError("That didn't go through.")
        ids[step["id"]] = job["id"]
    return ids


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "request"


def save_repeat(plan: dict, home: Optional[Path] = None) -> str:
    """Save the plan as a workflow and schedule it. Returns the schedule name.

    The schedule uses the same files `mco schedule` reads, so the plan shows up
    in `bitcadence schedule` and fires through the governed job board.
    """
    import yaml
    from mco import scheduler

    repeat = plan.get("repeat")
    if not repeat:
        raise PlanError("There is no repeat to save.")
    home = Path(home) if home else Path.home() / ".mco"
    name = f"ask-{_slug(plan['request'])}"
    workflow = {"name": name, "steps": [
        {"id": s["id"], "role": s["role"], "title": s["label"], "instructions": s["instructions"],
         **({"depends_on": s["depends_on"]} if s["depends_on"] else {}),
         **({"requires_approval": True} if s["gate"] else {})} for s in plan["steps"]]}
    config_path = home / "schedules.yaml"
    config: dict = {}
    if config_path.exists():
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(config, dict):
            raise PlanError("Your schedules file could not be read, so nothing was changed.")
    workflow_path = home / "workflows" / f"{name}.yaml"
    config.setdefault("launchers", {})[name] = {"workflow": str(workflow_path)}
    config.setdefault("schedules", {})[name] = {"launcher": name, "cron": repeat["cron"]}
    scheduler.parse_config(config)  # reject anything the scheduler would refuse, before writing
    workflow_path.parent.mkdir(parents=True, exist_ok=True)
    workflow_path.write_text(yaml.safe_dump(workflow, sort_keys=False), encoding="utf-8")
    if config_path.exists():
        config_path.with_suffix(".yaml.bak").write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return name
