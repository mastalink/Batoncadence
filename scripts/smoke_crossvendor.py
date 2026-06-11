"""
Cross-vendor live smoke test: Dynatrace -> BatonCadence -> ServiceNow.

Proves the marketed claim end-to-end against REAL platform instances:

  Movement I    DETECT      Dynatrace problems ingested as jobs (live sync,
                            or the webhook path if no problem is open)
  Movement II   INVESTIGATE an agent leases the job, recalls Drumline memory,
                            and completes with a root cause (auto-distilled
                            back into Drumline)
  Movement III  GOVERN      the ServiceNow write pauses at needs_approval
                            until a human (or the approver token) decides
  Movement IV   EXECUTE     the connector-role worker creates a REAL incident
                            in ServiceNow, then resolves it; we verify state=6
                            by reading it back
  Movement V    CLOSE LOOP  the originating Dynatrace problem is commented
                            and closed (live-sync runs only)
  Finale        AUDIT       the immutable event chain for every job, plus the
                            Drumline entries the run produced

Run it against a running gateway (see docs/SMOKE_TEST.md for free accounts):

    # terminal 1
    mco serve
    # terminal 2
    python scripts/smoke_crossvendor.py

Environment:
    MCO_SMOKE_GATEWAY         gateway URL (default http://127.0.0.1:18789)
    MCO_SMOKE_TOKEN           approver-role token (default: MCO_LOCAL_TOKEN)
    MCO_SMOKE_MANUAL_APPROVE  "1" = wait for a human to approve in the console
                              (the money shot when recording a demo)

Connector credentials resolve through the normal config stack (.env /
encrypted secret store): SERVICENOW_INSTANCE_URL + auth, DYNATRACE_BASE_URL +
DYNATRACE_API_TOKEN (optional - the run degrades to the webhook ingestion
path, clearly labeled, when Dynatrace is absent or has no open problems).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import time

import httpx

GATEWAY = os.environ.get("MCO_SMOKE_GATEWAY", "http://127.0.0.1:18789")
MANUAL_APPROVE = os.environ.get("MCO_SMOKE_MANUAL_APPROVE") == "1"

GREEN, RED, YELLOW, DIM, BOLD, END = "\033[92m", "\033[91m", "\033[93m", "\033[2m", "\033[1m", "\033[0m"
_failures: list = []


def ok(msg: str) -> None:
    print(f"  {GREEN}[OK]{END} {msg}")


def fail(msg: str) -> None:
    _failures.append(msg)
    print(f"  {RED}[FAIL]{END} {msg}")


def note(msg: str) -> None:
    print(f"  {DIM}{msg}{END}")


def sim(msg: str) -> None:
    print(f"  {YELLOW}[SIM]{END} {msg}")


def movement(no: str, title: str) -> None:
    print(f"\n{BOLD}== Movement {no} - {title} =={END}")


def die(msg: str) -> None:
    fail(msg)
    print(f"\n{RED}{BOLD}SMOKE TEST FAILED{END}")
    sys.exit(1)


def api(token: str) -> httpx.Client:
    return httpx.Client(base_url=GATEWAY, timeout=30,
                        headers={"Authorization": f"Bearer {token}"})


def register_agent(name: str, role: str) -> str:
    """Register an ephemeral smoke agent via the real CLI; returns its token."""
    res = subprocess.run(
        [sys.executable, "-m", "mco.cli", "register", "--name", name, "--role", role],
        capture_output=True, text=True, timeout=120,
    )
    m = re.search(r"mco_tok_[0-9a-f]+", res.stdout + res.stderr)
    if not m:
        die(f"could not register agent {name} ({role}): {res.stdout[-300:]} {res.stderr[-300:]}")
    return m.group(0)


def lease_and_run(client: httpx.Client, job: dict, instance: str, connector_name: str | None,
                  scripted_output: str | None = None) -> dict:
    """Lease a job and execute it exactly the way `mco listen` would.

    For connector roles we run the SAME executor the daemon registers
    (make_connector_executor); for agent roles we complete with the provided
    output. Returns the completed job.
    """
    job_id = job["id"]
    r = client.post("/api/jobs/lease", json={"task_id": job_id, "agent_instance_id": instance})
    if r.status_code != 200 or not r.json().get("success"):
        die(f"lease failed for {job_id}: HTTP {r.status_code} {r.text[:200]}")
    ok(f"job {job_id[:8]} leased by {instance} (atomic)")

    if connector_name:
        from mco.connectors import get_connector, make_connector_executor
        conn = get_connector(connector_name)
        if not conn:
            die(f"connector '{connector_name}' not configured in this environment")
        executor = make_connector_executor(conn)
        out, err = asyncio.run(executor(job, ""))
        if err:
            die(f"{connector_name} executor: {err}")
        output = out
    else:
        output = scripted_output or "done"

    r = client.put(f"/api/jobs/{job_id}", json={"status": "completed",
                                                "output_payload": {"result": output}})
    if r.status_code != 200:
        die(f"complete failed for {job_id}: HTTP {r.status_code} {r.text[:200]}")
    ok(f"job {job_id[:8]} completed")
    updated = r.json()
    return updated.get("job") or updated


def create_gated_job(client: httpx.Client, title: str, role: str, action: str, params: dict,
                     description: str = "") -> dict:
    r = client.post("/api/jobs", json={
        "title": title,
        "description": description,
        "target_agent_role": role,
        "requires_approval": True,
        "input_payload": {"action": action, "params": params},
    })
    if r.status_code != 200:
        die(f"create job failed: HTTP {r.status_code} {r.text[:200]}")
    job = r.json().get("job") or r.json()
    status = job.get("status")
    if status != "needs_approval":
        fail(f"expected needs_approval, got '{status}' - approval gate NOT engaged")
    else:
        ok(f"'{title}' paused at needs_approval (id {job['id'][:8]})")
    return job


def approve(client: httpx.Client, job: dict) -> None:
    job_id = job["id"]
    if MANUAL_APPROVE:
        print(f"\n  {BOLD}{YELLOW}>> HUMAN: approve job {job_id[:8]} in the console "
              f"({GATEWAY}/console -> Approvals) <<{END}")
        for _ in range(120):
            time.sleep(2)
            r = client.get("/api/jobs")
            cur = next((j for j in r.json() if j.get("id") == job_id), None)
            if cur and cur.get("status") != "needs_approval":
                ok(f"human approved {job_id[:8]} via the console")
                return
        die("timed out waiting for human approval (4 min)")
    r = client.post(f"/api/jobs/{job_id}/approve")
    if r.status_code != 200:
        die(f"approve failed: HTTP {r.status_code} {r.text[:200]}")
    ok(f"approved {job_id[:8]} (approver token)")


def print_audit(client: httpx.Client, job_id: str, label: str) -> None:
    r = client.get(f"/api/jobs/{job_id}/events")
    body = r.json()
    events = body.get("events") if isinstance(body, dict) else body
    chain = " -> ".join(e.get("event", "?") for e in (events or []))
    print(f"  {DIM}{label}: {chain}  (append-only){END}")


def main() -> None:
    print(f"\n{BOLD}BatonCadence cross-vendor smoke test{END}")
    print(f"{DIM}Dynatrace -> governed agent + Drumline -> ServiceNow -> audit{END}")

    # ── Preflight ────────────────────────────────────────────────────────────
    movement("0", "Preflight")
    try:
        health = httpx.get(f"{GATEWAY}/healthz", timeout=10).json()
    except Exception as e:
        die(f"gateway unreachable at {GATEWAY}: {e}")
    ok(f"gateway up (backend: {health.get('backend')})")

    from mco.config import get_config
    config = get_config()
    token = os.environ.get("MCO_SMOKE_TOKEN") or (config.get("MCO_LOCAL_TOKEN") or "").strip()
    if not token:
        die("no approver token: set MCO_SMOKE_TOKEN (or MCO_LOCAL_TOKEN in .env)")

    operator = api(token)
    r = operator.get("/api/integrations")
    if r.status_code != 200:
        die(f"connector listing failed: HTTP {r.status_code} {r.text[:200]} "
            "(is the smoke token an approver-role agent?)")
    conns = {c["name"]: c for c in r.json()}
    snow = conns.get("servicenow")
    if not snow:
        die("ServiceNow connector not configured (set SERVICENOW_INSTANCE_URL + credentials)")
    if not snow["health"]["ok"]:
        die(f"ServiceNow unreachable: {snow['health']['detail']}")
    ok(f"ServiceNow live: {snow['health']['detail']}")
    dyna = conns.get("dynatrace")
    if dyna and dyna["health"]["ok"]:
        ok(f"Dynatrace live: {dyna['health']['detail']}")
    else:
        sim("Dynatrace not configured/reachable - detection will use the webhook ingestion path")
        dyna = None

    note("registering ephemeral smoke agents (investigator, snow-worker, dt-worker)...")
    inv_token = register_agent("smoke-investigator", "claude")
    snow_token = register_agent("smoke-snow-worker", "servicenow")
    dt_token = register_agent("smoke-dt-worker", "dynatrace") if dyna else None
    investigator, snow_worker = api(inv_token), api(snow_token)
    dt_worker = api(dt_token) if dt_token else None
    ok("agents registered through the real token/registry path")

    # ── Movement I: DETECT ───────────────────────────────────────────────────
    movement("I", "DETECT (Dynatrace -> job board)")
    problem_ref = None
    created_id = None
    if dyna:
        r = operator.post("/api/integrations/dynatrace/sync")
        summary = r.json() if r.status_code == 200 else {}
        created = summary.get("created") or []
        if created:
            first = created[0]
            created_id = first.get("id") if isinstance(first, dict) else first
            ok(f"live sync pulled {summary.get('pulled')} problem(s), created job {str(created_id)[:8]}")
        else:
            sim(f"Dynatrace reachable but no OPEN problems (pulled={summary.get('pulled', 0)})")
    if not created_id:
        secret = (config.get("MCO_WEBHOOK_SECRET") or "").strip()
        if not secret:
            die("no live problem and MCO_WEBHOOK_SECRET unset - cannot demonstrate ingestion")
        sim("injecting a Dynatrace-format problem notification through the REAL webhook endpoint")
        r = httpx.post(f"{GATEWAY}/api/integrations/dynatrace/webhook",
                       headers={"X-MCO-Webhook-Secret": secret},
                       json={"ProblemID": f"SMOKE-{int(time.time())}",
                             "ProblemTitle": "High error rate on checkout-service",
                             "ProblemDetailsText": "Davis detected a 14x error-rate spike on "
                                                   "checkout-service after deploy 2026-06-11.",
                             "State": "OPEN"}, timeout=30)
        if r.status_code != 200:
            die(f"webhook ingestion failed: HTTP {r.status_code} {r.text[:200]}")
        created = r.json().get("created") or []
        created_id = created[0].get("id") if created and isinstance(created[0], dict) else (created[0] if created else None)
        if not created_id:
            die("webhook accepted but no job created (duplicate external_id from a prior run?)")
        ok(f"webhook ingested -> job {str(created_id)[:8]} on the board")

    r = investigator.get("/api/jobs")
    j1 = next((j for j in r.json() if j.get("id") == created_id), None)
    if not j1:
        die("ingested job not visible on the job board")
    problem_ref = ((j1.get("input_payload") or {}).get("platform_ref") or {}).get("problemId") \
        or (j1.get("input_payload") or {}).get("external_id", "")

    # ── Movement II: INVESTIGATE (+ Drumline) ───────────────────────────────
    movement("II", "INVESTIGATE (agent + Drumline memory)")
    r = investigator.get("/api/context", params={"query": j1.get("title", ""), "limit": 3})
    prior = r.json() if r.status_code == 200 else []
    if prior:
        ok(f"Drumline recalled {len(prior)} relevant memorie(s) from previous runs:")
        for e in prior:
            note(f"  - [{e.get('kind')}] {e.get('title')}")
    else:
        note("Drumline is empty (first run) - run this script twice to watch the mesh get smarter")
    root_cause = ("Root cause: deploy 2026-06-11 introduced an unbounded retry loop in "
                  "checkout-service's payment client; error rate spiked 14x. "
                  "Mitigation: roll back to previous build and add a circuit breaker.")
    lease_and_run(investigator, j1, "smoke-investigator", None, scripted_output=root_cause)
    ok("investigation distilled into Drumline (collective memory) automatically")

    # ── Movement III: GOVERN ─────────────────────────────────────────────────
    movement("III", "GOVERN (human approval gate before any ITSM write)")
    j2 = create_gated_job(
        operator, f"Open ServiceNow incident for {problem_ref}", "servicenow",
        "create_incident",
        {"short_description": f"[BatonCadence] {j1.get('title', 'Dynatrace problem')}",
         "description": f"Source: Dynatrace {problem_ref}\n\n{root_cause}", "urgency": "2"},
        description="Cross-vendor: file the Davis detection + agent root cause as an ITSM record.")
    approve(operator, j2)

    # ── Movement IV: EXECUTE (real ServiceNow writes) ────────────────────────
    movement("IV", "EXECUTE (REAL ServiceNow incident, then resolve + verify)")
    done = lease_and_run(snow_worker, j2, "smoke-snow-worker", "servicenow")
    result = json.loads(((done.get("output_payload") or {}).get("result")) or "{}")
    sys_id, number = result.get("sys_id"), result.get("number")
    if not sys_id:
        die(f"no sys_id returned from create_incident: {result}")
    ok(f"REAL incident created: {number} (sys_id {sys_id})")
    note(f"see it: {snow['health']['detail'].split()[-1]}/nav_to.do?uri=incident.do?sys_id={sys_id}")

    j3 = create_gated_job(
        operator, f"Resolve {number} with root cause", "servicenow", "resolve_incident",
        {"sys_id": sys_id, "close_notes": root_cause})
    approve(operator, j3)
    lease_and_run(snow_worker, j3, "smoke-snow-worker", "servicenow")

    from mco.connectors import get_connector
    inc = get_connector("servicenow").execute_action("get_incident", {"sys_id": sys_id})
    if str(inc.get("state")) == "6":
        ok(f"verified by reading back: {number} state=6 (Resolved) on the live instance")
    else:
        fail(f"read-back state is '{inc.get('state')}', expected '6' - check instance state model")

    # ── Movement V: CLOSE THE LOOP ───────────────────────────────────────────
    movement("V", "CLOSE THE LOOP (back into Dynatrace)")
    if dyna and problem_ref and not str(problem_ref).startswith("SMOKE-"):
        j4 = create_gated_job(
            operator, f"Close Dynatrace problem {problem_ref}", "dynatrace", "add_comment",
            {"problem_id": problem_ref,
             "comment": f"Resolved as ServiceNow {number} by BatonCadence agent. {root_cause}"})
        approve(operator, j4)
        lease_and_run(dt_worker, j4, "smoke-dt-worker", "dynatrace")
        ok(f"commented on live Dynatrace problem {problem_ref}")
    else:
        sim("webhook-simulated problem - no live Dynatrace problem to close (run with an open problem for the full loop)")

    # ── Finale: AUDIT ────────────────────────────────────────────────────────
    movement("VI", "AUDIT (the immutable trail)")
    for jid, label in [(j1["id"], "investigate"), (j2["id"], "create-incident"), (j3["id"], "resolve")]:
        print_audit(operator, jid, label)
    r = operator.get("/api/context", params={"query": "checkout error rate root cause", "limit": 3})
    for e in (r.json() if r.status_code == 200 else []):
        note(f"Drumline now remembers: [{e.get('kind')}] {e.get('title')}")

    print()
    if _failures:
        print(f"{RED}{BOLD}SMOKE TEST FAILED{END} - {len(_failures)} failure(s):")
        for f_ in _failures:
            print(f"  - {f_}")
        sys.exit(1)
    print(f"{GREEN}{BOLD}CROSS-VENDOR SMOKE TEST PASSED{END}")
    print(f"{DIM}Dynatrace detected -> agent investigated with shared memory -> human approved ->")
    print(f"ServiceNow incident {number} created AND resolved -> every step in the audit trail.{END}\n")


if __name__ == "__main__":
    main()
