"""C8 — Cost reservation mocks (atomic reserve / settle / keep-on-unknown).

No real provider keys. Kill-switch and per-Score ceiling interfaces are stubbed
for unit tests under concurrency.
"""

from __future__ import annotations

import threading
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal


class CostReservationError(ValueError):
    """Reservation refused or unknown id."""


ReservationState = Literal["reserved", "settled", "kept_unknown", "released"]


@dataclass(frozen=True)
class CostReservation:
    reservation_id: str
    score_id: str
    run_id: str
    task_id: str
    attempt: int
    cents: int
    state: ReservationState


class CostKillSwitch(ABC):
    @abstractmethod
    def is_active(self) -> bool:
        raise NotImplementedError


class InMemoryCostKillSwitch(CostKillSwitch):
    def __init__(self, active: bool = False) -> None:
        self._active = bool(active)
        self._lock = threading.Lock()

    def is_active(self) -> bool:
        with self._lock:
            return self._active

    def set_active(self, active: bool) -> None:
        with self._lock:
            self._active = bool(active)


class CostCeilingPolicy(ABC):
    @abstractmethod
    def remaining_cents(self, score_id: str) -> int:
        raise NotImplementedError

    @abstractmethod
    def note_spend(self, score_id: str, cents: int) -> None:
        raise NotImplementedError


class PerScoreCostCeiling(CostCeilingPolicy):
    """Stub monthly/per-Score ceiling tracked in-process."""

    def __init__(self, ceilings: dict[str, int] | None = None, default_ceiling: int = 0) -> None:
        self._ceilings = dict(ceilings or {})
        self._spent: dict[str, int] = {}
        self._default = int(default_ceiling)
        self._lock = threading.Lock()

    def remaining_cents(self, score_id: str) -> int:
        with self._lock:
            ceiling = self._ceilings.get(score_id, self._default)
            spent = self._spent.get(score_id, 0)
            return max(0, ceiling - spent)

    def note_spend(self, score_id: str, cents: int) -> None:
        if cents < 0:
            raise CostReservationError("negative_spend")
        with self._lock:
            self._spent[score_id] = self._spent.get(score_id, 0) + int(cents)

    def set_ceiling(self, score_id: str, cents: int) -> None:
        with self._lock:
            self._ceilings[score_id] = int(cents)


class CostReservationLedger:
    """Atomic in-memory ledger: reserve before dispatch, settle on receipt,
    keep reservation when outcome is unknown."""

    def __init__(
        self,
        *,
        kill_switch: CostKillSwitch | None = None,
        ceiling: CostCeilingPolicy | None = None,
        budget_cents: int | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._reservations: dict[str, CostReservation] = {}
        self._reserved_total = 0
        self._kill_switch = kill_switch or InMemoryCostKillSwitch(False)
        self._ceiling = ceiling or PerScoreCostCeiling(default_ceiling=10**9)
        self._budget_cents = budget_cents  # optional run-level budget

    @property
    def reserved_total(self) -> int:
        with self._lock:
            return self._reserved_total

    def get(self, reservation_id: str) -> CostReservation | None:
        with self._lock:
            return self._reservations.get(reservation_id)

    def reserve_cost_cents(
        self,
        *,
        score_id: str,
        run_id: str,
        task_id: str,
        attempt: int,
        cents: int,
        reservation_id: str | None = None,
    ) -> CostReservation:
        if cents < 0:
            raise CostReservationError("negative_reservation")
        with self._lock:
            if self._kill_switch.is_active():
                raise CostReservationError("kill_switch_active")
            if self._budget_cents is not None and self._reserved_total + cents > self._budget_cents:
                raise CostReservationError("budget_exceeded")
            remaining = self._ceiling.remaining_cents(score_id)
            # Open reserved amounts against this score also consume remaining.
            open_for_score = sum(
                r.cents
                for r in self._reservations.values()
                if r.score_id == score_id and r.state == "reserved"
            )
            if open_for_score + cents > remaining:
                raise CostReservationError("score_ceiling_exceeded")
            rid = reservation_id or uuid.uuid4().hex
            if rid in self._reservations:
                raise CostReservationError("reservation_id_conflict")
            reservation = CostReservation(
                reservation_id=rid,
                score_id=score_id,
                run_id=run_id,
                task_id=task_id,
                attempt=attempt,
                cents=int(cents),
                state="reserved",
            )
            self._reservations[rid] = reservation
            self._reserved_total += int(cents)
            return reservation

    def settle(self, reservation_id: str, *, actual_cents: int | None = None) -> CostReservation:
        with self._lock:
            current = self._require_reserved(reservation_id)
            spent = current.cents if actual_cents is None else int(actual_cents)
            if spent < 0:
                raise CostReservationError("negative_settle")
            # Release unused reserved headroom; charge ceiling for actual spend.
            delta = current.cents - spent
            self._reserved_total -= current.cents
            if spent:
                self._ceiling.note_spend(current.score_id, spent)
            # Keep ledger reserved_total as currently-open reserved only.
            if delta < 0:
                # Actual exceeded reserve: still settle, but record spill as spend only.
                pass
            settled = CostReservation(
                reservation_id=current.reservation_id,
                score_id=current.score_id,
                run_id=current.run_id,
                task_id=current.task_id,
                attempt=current.attempt,
                cents=spent,
                state="settled",
            )
            self._reservations[reservation_id] = settled
            return settled

    def keep_on_unknown(self, reservation_id: str) -> CostReservation:
        """Unknown outcome keeps its reservation (does not free budget)."""
        with self._lock:
            current = self._require_reserved(reservation_id)
            kept = CostReservation(
                reservation_id=current.reservation_id,
                score_id=current.score_id,
                run_id=current.run_id,
                task_id=current.task_id,
                attempt=current.attempt,
                cents=current.cents,
                state="kept_unknown",
            )
            self._reservations[reservation_id] = kept
            # reserved_total unchanged — budget stays held.
            return kept

    def release(self, reservation_id: str) -> CostReservation:
        with self._lock:
            current = self._require_reserved(reservation_id)
            self._reserved_total -= current.cents
            released = CostReservation(
                reservation_id=current.reservation_id,
                score_id=current.score_id,
                run_id=current.run_id,
                task_id=current.task_id,
                attempt=current.attempt,
                cents=current.cents,
                state="released",
            )
            self._reservations[reservation_id] = released
            return released

    def _require_reserved(self, reservation_id: str) -> CostReservation:
        current = self._reservations.get(reservation_id)
        if current is None:
            raise CostReservationError("reservation_missing")
        if current.state != "reserved":
            raise CostReservationError(f"reservation_not_open:{current.state}")
        return current


# Convenience alias matching packet placeholder name.
def reserve_cost_cents(ledger: CostReservationLedger, **kwargs) -> CostReservation:
    return ledger.reserve_cost_cents(**kwargs)
