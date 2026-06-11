# Goal: Mythos is original — first-class in every edition, no rented dependency

**Status:** Embedded local store shipped 2026-06-10. Pluggable backends open.

## The decision (2026-06-10)

Mythos is BatonCadence's differentiator and cannot be bent around someone
else's database. The free Local-Only edition must have the *full* shared
memory — auto-distillation, deliberate memory, prompt injection — with zero
cloud dependencies. We do not ship an edition where the core feature is
missing.

## What shipped

`src/mco/localstore.py` — an embedded SQLite data plane (stdlib only, no new
dependencies) that speaks the same PostgREST builder dialect the routes
already use, so **zero changes to routes/handlers/mythos** were needed:

- `get_db_client()` returns it automatically when no Supabase credentials
  are configured (opt out with `MCO_DISABLE_LOCAL_DB`).
- Jobs, agent registry, **immutable audit trail** (append-only enforced in
  code, mirroring the cloud DB trigger), and **Mythos** all persist to
  `~/.mco/local.db`.
- `lease_task` implemented as an atomic compare-and-set under the store
  lock — same single-winner contract as the Postgres function.
- `MCO_LOCAL_TOKEN` from `.env` seeds a real `agent_registry` row
  (`local-operator`, role `admin`) so the console connects through the
  exact same token path as cloud deployments. No special cases.
- `/healthz` reports `"backend": "local" | "supabase"`.
- Covered by `tests/test_localstore.py` including a full create → lease →
  complete → audit → distill lifecycle through the real FastAPI app
  (suite: 200 tests).

## Why this design

A Supabase-compatible shim instead of a storage-interface refactor: the
query surface was only ~10 builder methods across 6 files, so mimicking it
gives every feature (jobs, audit, approvals, Mythos, registry) local
persistence at once, with no churn in reviewed governance code.

## Remaining work

- [ ] Plain-Postgres backend (same shim approach: psycopg + SQL) — unlocks
      "custom data source" for enterprises who won't use Supabase
- [ ] Document the embedded store's limits (single node, no row-level
      security; multi-tenant SaaS still needs Postgres)
- [x] LICENSE file — done 2026-06-10 (MIT, copyright Joe Arroyo)
- [ ] Optional: `mco export` / `mco import` for moving a local mesh's
      memory into a cloud deployment (local → hybrid upgrade path)
