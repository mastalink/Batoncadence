# Gateway perf #2 evidence — 2026-10-05

Baseline: `70ebfffd7d08d371a5d386970538124792120f07` (PR #134). The installed baseline LocalStore source was verified byte-equivalent after line-ending normalization.

## Controlled load reproduction

`tests/test_gateway_responsiveness.py::test_twenty_fleet_reads_six_boards_and_atomic_write_p95_under_two_seconds` issues 20 simultaneous authenticated `/api/agents` requests, 6 `/api/jobs?limit=20` requests, and a job write against a 1,000-job store. Each job select includes a deliberate 100 ms delay, exposing serialization without a large fixture. All 26 responses must succeed and p95 must remain below two seconds. The concurrent job write must have its matching audit outbox entry.

| Measurement | Baseline | Changed code |
| --- | ---: | ---: |
| 26-request p95 | 4.926 s (test fails) | 0.251 s (test passes) |
| Maximum request | 4.928 s | 0.251 s |

An intermediate run with concurrent readers and no cache measured p95 0.556 s. These are controlled test numbers, not post-deployment live measurements.

Separate tests prove same-store readers complete during an uncommitted writer transaction, see committed state and audit only, and see both after commit. The writer retains read-your-writes semantics. Injecting an outbox failure rolls back the state update. Reader connections are distinct per thread, read-only, and closed with the store.

Five-second caches coalesce concurrent refreshes, return copies, filter tenant visibility after copying a shared sanitized roster, and bypass transactional reads. The API refresh bypasses the evidence cache to avoid stacking TTLs. Explicit-time presence calculations bypass caching.

## Verification

The focused LocalStore/gateway/presence/delivery/auth/tenancy/creation/acceptance run passed **116 tests**, with **11 PostgreSQL tests skipped locally** (the disposable acceptance services are provided by CI). See the PR's PostgreSQL acceptance check for real database validation.

The full Windows run reached all tests but encountered two unrelated failures: `test_websocket_bypass_auth` races handshake acceptance against connection registration (passed on rerun), and `test_pipe_no_prompt_survives` times out starting the shell probe (reproduced independently). No installer or WebSocket behavior was changed. Linux CI is the full-suite release signal.

## Live observations and deployment-dependent work

The Chief's supplied pre-change live observations: `/healthz` 89 ms, `/api/agents` 56,225 ms, `/api/jobs?limit=20` 2.9 s, pending jobs 1.5 s; uncontended `describe_fleet` 0.26 s. These were supplied by the job, not remeasured in this run.

A read-only inspection of the live `~/.mco/local.db` verified `journal_mode=wal` and 943 jobs. Registry instance names containing `mac`: `claude-mac-studio` (claude), `mac-studio-codex` (codex), `antigravity-mac` (antigravity), and `codex-mac` (codex). Registration alone does not identify which callers dominate slow requests.

The new rotating logger emits timestamp, method, route path template, authenticated instance ID, total milliseconds and cumulative LocalStore writer RLock wait milliseconds. It writes requests exceeding 1,000 ms to `~/.mco/logs/gateway-slow.log`, with three 5 MiB backups. Route parameters, query strings, headers and bodies are excluded. Lock-wait timing is process-local RLock wait, not PostgreSQL lock timing or SQLite inter-process busy wait.

**Blocked:** running this new middleware against live traffic for ten minutes requires deployment. The job expressly forbids merging or restarting the live gateway, and no existing `gateway-slow.log` is present. No gateway was merged, restarted, hot-patched or reconfigured, and no top-caller ranking is fabricated.

After the Chief deploys, collect ten minutes of normal live traffic, then run:

```text
python scripts/gateway_slow_report.py --minutes 10
```

The report reads rotated logs and ranks authenticated callers by count and cumulative request time, retaining their actual instance names. Compare live endpoint timings again after deployment.
