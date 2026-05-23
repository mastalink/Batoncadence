# MCO scheduler prompts (one per agent)

Each agent's GUI runs a recurring prompt that works its MCO inbox. The MCP env
already identifies the agent (its `role` + `instance`), and the **recurrence is
owned by the scheduler** (`/loop`, a cron, or a scheduled task) — so the prompt
describes ONLY the work.

> ⚠️ CRITICAL: never put control-flow words ("stop", "do not loop", "one pass")
> in a scheduled/looped prompt. A looping agent reads "stop" and cancels its own
> loop (this killed an early Claude `/loop`). The prompt does one inbox sweep and
> ends its turn naturally; the scheduler re-runs it.

Prereqs: the gateway (`mco serve`) must be running and reachable at
`http://127.0.0.1:18789`, and each app must be able to reach it (i.e. running on
this machine, not a cloud-only runner).

---

## Claude — `/loop` (sub-hour; GUI Routines floor at 1h)
Run inside a Claude session you leave open:

```
/loop 10m Check your MCO inbox: call mco_inbox. For each job addressed to you (up to 3), call mco_lease(task_id); if the lease succeeds, carry out its input_payload.prompt using your tools, then mco_complete(task_id, <concise result>) — or mco_fail(task_id, <error>). If the inbox is empty, there is nothing to do this run.
```

Note: each `/loop` tick costs a small Claude turn even when the inbox is empty.
10m is a sane default; tighten only if you need faster pickup.

## Codex — custom cron / Automation (role: implementer)
Cron example (every 5 min): `*/5 * * * *`

```
Check your MCO inbox: call mco_inbox. For each job (up to 3): mco_lease(task_id); if the lease succeeds, implement what its input_payload.prompt asks in the workspace, then mco_complete(task_id, <summary of files changed>) — or mco_fail(task_id, <error>) — and hand off: mco_send(to_role="antigravity", title="Review & test: <feature>", instructions="<what to verify / how to run tests>"). If the inbox is empty, there is nothing to do.
```

## Antigravity — custom cron / Scheduled Task (role: reviewer/tester)
Cron example (every 5 min): `*/5 * * * *`

```
Check your MCO inbox: call mco_inbox. For each job (up to 3): mco_lease(task_id); if the lease succeeds, review/test what the job points to (run the tests). If it passes: mco_complete(task_id, <verdict>). If it needs fixes: mco_complete(task_id, <findings>) and mco_send(to_role="codex", title="Fix: <issue>", instructions="<what to fix>"). If the inbox is empty, there is nothing to do.
```

---

## Cron quick reference
| Interval | Expression |
|----------|------------|
| 5 min  | `*/5 * * * *` |
| 10 min | `*/10 * * * *` |
| 15 min | `*/15 * * * *` |
| hourly | `0 * * * *` |

## Topology (plan → build → review)
- **claude** (planner): turns a goal into a plan, `mco_send` → `codex`.
- **codex** (implementer): writes code, `mco_send` → `antigravity`.
- **antigravity** (reviewer): tests; on failure `mco_send` → `codex` (fix loop); else done.

Change the `mco_send` targets to re-wire the pipeline (or drop them for a flat
peer model where each agent only does what it's explicitly sent).
