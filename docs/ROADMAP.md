# BatonCadence - Current State, Gap Analysis & Close-Out Roadmap

**Status date:** June 2026
**Origin:** December 2025 "AgentMesh" validation plan (see [VALIDATION_SUMMARY.md](VALIDATION_SUMMARY.md))

This document maps the original AgentMesh plan against what BatonCadence has
actually shipped, identifies the remaining gaps, and defines the work needed
to close out the MVP phase.

---

## 1. Where We Are Today

BatonCadence is a working, tested orchestration MVP:

| Capability | Status | Where |
|---|---|---|
| Job board (create/lease/execute/complete with dependency resolution) | **Shipped** | `src/mco/orchestrator/routes.py`, `contracts.py` |
| Multi-vendor role executors (codex, claude, gemini CLIs) | **Shipped** | `src/mco/orchestrator/executors.py` |
| Background worker daemon (`mco listen`) with lease polling | **Shipped** | `src/mco/orchestrator/listener.py`, `client.py` |
| Bearer-token agent authentication + agent registry | **Shipped** | `src/mco/orchestrator/auth.py` |
| AES-256-GCM secret vault with Windows Credential Manager unlock | **Shipped** | `src/mco/security.py` |
| MCP server exposing inbox/lease/complete/fail/send/agents tools | **Shipped** | `src/mco/mcp_server.py` |
| GUI agent configs (Claude Desktop, Codex, Antigravity) | **Shipped** | `configs/` |
| Push notifications (ntfy.sh) on job lifecycle events | **Shipped** | `src/mco/notifiers/ntfy.py` |
| Supabase persistence with memoized/pre-warmed client | **Shipped** | `routes.py` |
| WebSocket gateway broadcasts | **Shipped** | `routes.py`, `handlers.py` |
| Test suite (52 unit + E2E tests) | **Shipped** | `tests/` |
| CLI (`setup`, `serve`, `listen`, `status`) + setup guide | **Shipped** | `src/mco/cli.py`, `docs/SETUP_GUIDE.md` |

## 2. Gap Analysis vs. the Original Plan

The AgentMesh plan named five core components. Current coverage:

| Planned component | Coverage | Gap |
|---|---|---|
| Agent SDK | **~80%** | `GatewayClient` + MCP tools exist; no published package or docs for third-party agent authors |
| Workflow Engine | **~50%** | Dependency chains (`WAITING` -> `PENDING`) work; no declarative workflow DSL, retries, or fan-out/fan-in |
| Control Plane | **~60%** | REST/WS gateway, auth, agent registry, CLI status; no dashboard/UI, no RBAC beyond bearer tokens |
| Audit System | **~20%** | ntfy notifications and logs exist; **no immutable, queryable audit trail** - the #1 validated requirement |
| Knowledge Graph | **0%** | Not started (deliberately deferred; lowest validated demand) |

Cross-cutting validated requirements still open:

- **Human-in-the-loop approval gates** - the market explicitly asked for
  guardrails where a human approves an agent action before execution. The job
  state machine has no `NEEDS_APPROVAL` state or approve/reject endpoint.
- **Immutable traceability logs** - job mutations are not recorded to an
  append-only `agent_job_events` table.
- **Escalation paths** - failed jobs terminate at `FAILED`; there is no
  structured escalation (notify -> reassign -> human takeover).

## 3. Close-Out Plan

### Phase A - MVP Close-Out (governance core) — **SHIPPED (June 2026)**

1. **Immutable audit trail** — DONE
   - Append-only `agent_job_events` table with a DB trigger rejecting
     UPDATE/DELETE (`docs/migrations/2026-06_phase_a_governance.sql`); written
     on every create/lease/status/approval/retry/escalation mutation
     (`src/mco/orchestrator/audit.py`).
   - `GET /api/jobs/{id}/events` endpoint, `mco audit <job_id>` CLI command,
     and `mco_audit` MCP tool.
2. **Human-in-the-loop approval gates** — DONE
   - `needs_approval` status; jobs flagged `requires_approval` pause there
     (including after dependency unlock).
   - `POST /api/jobs/{id}/approve` / `reject` endpoints, restricted to
     approver roles (`MCO_APPROVER_ROLES`, default `human,admin,operator`).
   - CLI (`mco approve`/`mco reject`), MCP tools (`mco_approve`/`mco_reject`),
     and ntfy alerts when a job awaits approval.
3. **Escalation paths** — DONE
   - `max_retries`/`retry_count` re-queue failed jobs; once exhausted,
     `escalate_to_role` auto-creates an escalation job with the failure
     context and fires a priority-5 ntfy alert.
4. **Tests + docs** — DONE: governance + workflow test suites added (114
   tests total), README and SETUP_GUIDE updated.

### Phase B - Alpha Hardening — **PARTIALLY SHIPPED**
- ~~Declarative workflow DSL (YAML)~~ DONE: DAG workflows with per-step
  governance (`mco workflow`, `src/mco/orchestrator/workflows.py`).
- ~~Minimal web dashboard~~ DONE: `/dashboard` control plane (job board,
  approval queue, agent fleet, audit viewer).
- RBAC: approver-role gating shipped; full per-scope token permissions still open.
- Packaged Agent SDK with quickstart for third-party agents — still open.

### Phase B+ - Enterprise Integrations — **SHIPPED (June 2026)**
The cross-vendor control capability named explicitly in the Gartner action
item ("centralized orchestration ... across vendors, including ServiceNow
control towers"):
- **Connector framework** (`src/mco/connectors/`) with a registry, health
  probes, and a connector-as-worker-role pattern.
- **ServiceNow** (ITSM): ingest incidents as agent jobs; create/update/
  comment/resolve incidents from agents or approver-gated direct actions.
- **Dynatrace** (observability): ingest OPEN problems; comment/close from
  agent workflows.
- **Generic webhook contract** for any other platform (PagerDuty,
  LogicMonitor, Datadog, custom apps) secured by `MCO_WEBHOOK_SECRET`.
- **Idempotent sync engine** (dedupe by external id) - on-demand
  (`mco sync`, REST, MCP) or background (`MCO_SYNC_INTERVAL`).
- **Escalation bridge** (`MCO_ESCALATION_CONNECTOR`): terminal job failures
  mirrored into ITSM with full audit (`escalated_external` events).
- Credentials ride the AES-256-GCM secret store; docs in
  `docs/INTEGRATIONS.md`; suite at 151 tests.

### Phase C - Pilot / Beta <- WE ARE HERE
- Re-engage Gartner conference contacts; target 3-5 pilot deployments.
- One-pager + demo script built from the working approval-gate + audit demo.
- Pilot feedback loop drives the 1.0 scope.

### Deferred (revisit after pilots)
- Knowledge Graph component.
- Hosted/multi-tenant SaaS deployment.

## 4. Original Plan Cross-Reference

| Original AgentMesh artifact | Disposition |
|---|---|
| VALIDATION_SUMMARY.md | Done - `docs/VALIDATION_SUMMARY.md` |
| TECHNICAL_SPEC.md | Superseded by working code + `README.md` + `docs/SETUP_GUIDE.md` |
| ROADMAP.md | Done - this document |
| BUSINESS_PLAN.md / pitch deck / one-pager | Deferred to Phase C (build from a working governance demo, not slideware) |
| 6-month MVP plan | Achieved in substance; Phase A closes the governance gap |
