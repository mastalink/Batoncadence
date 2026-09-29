# Packet C8 (offline) — Cost reservation mocks

**Status:** in-memory atomic ledger with kill-switch + per-Score ceiling stubs.
**Out of scope:** real provider keys, live API lane dispatch.

## API

- `CostReservationLedger.reserve_cost_cents(...)` → `CostReservation`
- `settle(id, actual_cents=?)` — frees unused reserve; records spend
- `keep_on_unknown(id)` — holds budget when outcome is unknown
- `release(id)` — free without spend
- `InMemoryCostKillSwitch` / `PerScoreCostCeiling` interfaces stubbed

## Acceptance (this PR)

- [x] Reservation atomic under concurrency tests.
- [x] Unknown outcome keeps its reservation.
- [x] Kill-switch and per-Score ceiling refuse overspend.
- [x] No real provider keys.
