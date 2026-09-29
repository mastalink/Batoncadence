"""H / C8 — Cost reservation mocks: atomic reserve/settle/keep-on-unknown."""

from __future__ import annotations

import threading

import pytest

from mco.orchestrator.score_cloud.cost_reservation import (
    CostReservationError,
    CostReservationLedger,
    InMemoryCostKillSwitch,
    PerScoreCostCeiling,
    reserve_cost_cents,
)


def test_reserve_settle_and_keep_on_unknown():
    ledger = CostReservationLedger(budget_cents=100, ceiling=PerScoreCostCeiling({"s1": 100}))
    reserved = ledger.reserve_cost_cents(
        score_id="s1", run_id="r1", task_id="api-triage", attempt=1, cents=40
    )
    assert reserved.state == "reserved"
    assert ledger.reserved_total == 40

    kept = ledger.keep_on_unknown(reserved.reservation_id)
    assert kept.state == "kept_unknown"
    assert ledger.reserved_total == 40  # still held

    other = ledger.reserve_cost_cents(
        score_id="s1", run_id="r1", task_id="api-triage", attempt=2, cents=30,
        reservation_id="explicit-2",
    )
    settled = ledger.settle(other.reservation_id, actual_cents=25)
    assert settled.state == "settled" and settled.cents == 25
    assert ledger.reserved_total == 40  # only the kept-unknown remains open in total accounting
    # After settle, open reserved excludes settled; kept_unknown still counts.
    assert ledger.get(reserved.reservation_id).state == "kept_unknown"


def test_kill_switch_and_ceiling_refuse():
    kill = InMemoryCostKillSwitch(False)
    ceiling = PerScoreCostCeiling({"s1": 50})
    ledger = CostReservationLedger(kill_switch=kill, ceiling=ceiling, budget_cents=1000)
    reserve_cost_cents(ledger, score_id="s1", run_id="r", task_id="t", attempt=1, cents=40)
    with pytest.raises(CostReservationError, match="score_ceiling_exceeded"):
        ledger.reserve_cost_cents(score_id="s1", run_id="r", task_id="t", attempt=2, cents=20)
    kill.set_active(True)
    with pytest.raises(CostReservationError, match="kill_switch_active"):
        ledger.reserve_cost_cents(score_id="s1", run_id="r", task_id="t", attempt=3, cents=1)


def test_budget_exceeded():
    ledger = CostReservationLedger(budget_cents=10, ceiling=PerScoreCostCeiling(default_ceiling=1000))
    ledger.reserve_cost_cents(score_id="s", run_id="r", task_id="t", attempt=1, cents=10)
    with pytest.raises(CostReservationError, match="budget_exceeded"):
        ledger.reserve_cost_cents(score_id="s", run_id="r", task_id="t", attempt=2, cents=1)


def test_concurrent_reserves_never_exceed_budget():
    ledger = CostReservationLedger(
        budget_cents=100,
        ceiling=PerScoreCostCeiling(default_ceiling=10**9),
    )
    errors: list[str] = []
    ok = []

    def worker(n: int) -> None:
        try:
            r = ledger.reserve_cost_cents(
                score_id="s",
                run_id="r",
                task_id=f"t-{n}",
                attempt=1,
                cents=10,
                reservation_id=f"r-{n}",
            )
            ok.append(r.reservation_id)
        except CostReservationError as exc:
            errors.append(str(exc))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(ok) == 10
    assert ledger.reserved_total == 100
    assert all(e == "budget_exceeded" for e in errors)
    assert len(errors) == 10


def test_release_frees_budget():
    ledger = CostReservationLedger(budget_cents=50, ceiling=PerScoreCostCeiling(default_ceiling=50))
    r = ledger.reserve_cost_cents(score_id="s", run_id="r", task_id="t", attempt=1, cents=50)
    ledger.release(r.reservation_id)
    assert ledger.reserved_total == 0
    again = ledger.reserve_cost_cents(score_id="s", run_id="r", task_id="t", attempt=2, cents=50)
    assert again.state == "reserved"


def test_no_provider_key_literals():
    from pathlib import Path

    src = Path(__file__).parents[1] / "src/mco/orchestrator/score_cloud/cost_reservation.py"
    text = src.read_text(encoding="utf-8").lower()
    for banned in ("sk-", "api_key", "openai", "anthropic", "bearer "):
        assert banned not in text
