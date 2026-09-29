# Packet C1 (offline) — Fake Score store

**Status:** offline interface + in-memory / SQLite fakes + parity tests.
**Out of scope:** live Postgres hosts, connection strings, cloud deploy.

## Delivers

- `ScoreStore` abstract interface (`create_run`, `get_run`, `upsert_task`,
  `get_task`, `append_event`, `list_events`, `transition_task`).
- `InMemoryScoreStore` and `SqliteScoreStore` fakes under
  `mco.orchestrator.score_cloud.store`.
- `score_store_parity_events` replay helper for identical event sequences.

## Acceptance (this PR)

- [x] One store interface; no Appliance behavior change until wired later.
- [x] Parity: Memory and SQLite fakes produce the same event sequence.
- [x] Unit tests only; no Postgres DSN / host literals.

## Merge note

Intentionally does **not** touch `docs/SCORE-CLOUD-V2.md` or
`docs/SCORE-CLOUD-V2-PACKETS.md` (open on #119 / #120). Companion packet notes
live under `docs/packets/`.
