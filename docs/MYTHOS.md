# Mythos - The Shared Context Substrate

Every agent on the mesh - Claude, Codex, Gemini, connector workers - reads
from and writes to **one collective memory**. Knowledge stops dying with the
job that produced it: what one agent learns, every agent knows.

Apply [`migrations/2026-06_mythos_shared_context.sql`](migrations/2026-06_mythos_shared_context.sql)
(idempotent) to enable it.

---

## How memory gets in

**1. Auto-distillation (the audit log becomes living memory).**
When any job completes, its essence - what was asked, what came back - is
distilled into a `handoff` entry, tagged with the roles and connector
involved, and recorded in the audit trail as `context_distilled`. The
*evidence* stays immutable in `agent_job_events`; the *essence* becomes
recallable context. Opt out with `MCO_MYTHOS_DISTILL=false`.

**2. Deliberate memory.**
Agents record durable knowledge - decisions, gotchas, environment facts:

```
mco_remember(title="Prod DB read-only on Sundays",
             content="Maintenance window 02:00-06:00 UTC.",
             kind="fact", tags="ops,postgres")
```

REST: `POST /api/context` `{"title", "content", "kind", "tags", "role", "weight"}`.
Kinds: `fact | decision | lesson | handoff | artifact`. Any authenticated
agent may write; entries are stamped with the author for accountability.

## How memory gets out

**1. Automatic prompt injection (the tap).**
Before a worker executes a leased job, it recalls the most relevant entries
(scored against the job's title/description and the worker's role) and
prepends them to the prompt:

```
=== SHARED CONTEXT (Mythos) ===
Collective memory from prior agent work. Use it; correct it via mco_remember if wrong.
- [handoff] Job outcome: Triage P-99 (claude-worker-1, 2026-06-10)
  Asked: Investigate high CPU on web-01
  Outcome: Root cause: runaway cron. Disabled job foo.
- [fact] Prod DB read-only on Sundays (joe, 2026-06-08)
  Maintenance window 02:00-06:00 UTC.
=== END SHARED CONTEXT ===

Task Title: ...
```

Opt out with `MCO_MYTHOS_INJECT=false`. Injection is best-effort: if the
gateway is unreachable, the job still runs.

**2. Explicit recall.**
GUI agents (Claude Desktop / Codex / Antigravity via MCP) dip in on demand:

```
mco_recall(query="dynatrace token", tags="ops", limit=5)
```

REST: `GET /api/context?query=...&role=...&tags=a,b&limit=5`.

## Recall scoring (deterministic by design)

`score = (query-term hits x entry weight) + role affinity (+0.75) + recency (0..0.5)`

- Tag filters are hard; the query is soft-scored; with no query you get the
  freshest entries.
- No embeddings, no external model: the substrate stays standalone, cheap,
  explainable in an audit, and testable. The scorer is one function
  (`mythos.score_entry`) - swap in an embedding back-end later without
  changing any caller.
- `weight` (0.1-5.0) lets important entries punch above their age.

## Design notes

- **Memory is governed like everything else**: writes require agent auth and
  are author-stamped; distillation events land in the immutable audit trail;
  a wrong memory is corrected by writing a better one (append-mostly), not by
  silently editing history.
- **Cross-vendor by construction**: a Dynatrace triage done by Claude becomes
  context for the Codex job that ships the fix and the ServiceNow closure
  that follows - the substrate is what makes the mesh more than a job queue.
