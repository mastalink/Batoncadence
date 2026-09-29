"""Score v2 extension points: pluggable store, evidence verifier and lane.

Generic protocols only, no cloud, provider or transport specifics. A v2
conductor (in-process, or a separate package such as a private cloud
extension) implements these and registers itself under the entry-point
groups below; core BitCadence never imports an implementation directly.

Entry-point groups (see a package's own pyproject.toml `[project.entry-points]`):
    mco.score_store       -> a ScoreStore factory (zero-arg callable)
    mco.evidence_verifier  -> an EvidenceVerifier factory (zero-arg callable)
    mco.lane_adapter       -> a LaneAdapter factory (zero-arg callable)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


class ScoreExtensionError(ValueError):
    """An extension point contract violation, or no implementation registered."""


@dataclass(frozen=True)
class ScoreRunRecord:
    run_id: str
    org_id: str
    score_id: str
    score_digest: str
    status: str
    definition: Mapping[str, Any]


@dataclass(frozen=True)
class ScoreEventRecord:
    seq: int
    run_id: str
    event_type: str
    detail: Mapping[str, Any]


@dataclass(frozen=True)
class ScoreTaskRecord:
    run_id: str
    task_id: str
    status: str
    attempt: int
    detail: Mapping[str, Any]


class ScoreStore(ABC):
    """One durable-store interface a Score conductor can be built against.

    Core ships no implementation. `SandboxRun`/the local sweep keep using
    their own in-process state; this exists so an out-of-tree conductor
    (cloud or otherwise) can implement one store and stay swappable.
    """

    @abstractmethod
    def create_run(self, record: ScoreRunRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_run(self, run_id: str) -> ScoreRunRecord | None:
        raise NotImplementedError

    @abstractmethod
    def upsert_task(self, record: ScoreTaskRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_task(self, run_id: str, task_id: str) -> ScoreTaskRecord | None:
        raise NotImplementedError

    @abstractmethod
    def append_event(self, run_id: str, event_type: str, detail: Mapping[str, Any]) -> ScoreEventRecord:
        raise NotImplementedError

    @abstractmethod
    def list_events(self, run_id: str) -> Sequence[ScoreEventRecord]:
        raise NotImplementedError


@runtime_checkable
class EvidenceVerifier(Protocol):
    """Checks a completion claim against independent evidence before accept.

    No transport is specified here: an implementation may check a PR host,
    a CI provider, a signed artifact, or a fixture file. It must never
    mutate the thing it is verifying.
    """

    def verify(self, *, task_id: str, claim: Mapping[str, Any]) -> "EvidenceVerdict":
        ...


@dataclass(frozen=True)
class EvidenceVerdict:
    accepted: bool
    would_refuse: tuple[str, ...] = ()
    checked: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@runtime_checkable
class LaneAdapter(Protocol):
    """Dispatches one task to wherever a lane runs work and reports back.

    A lane is an abstract place work happens (a worker pool, a hosted agent
    session, a human queue, ...); this protocol only describes the
    dispatch/poll contract a conductor needs, not any lane's internals.
    """

    def dispatch(self, *, task_id: str, payload: Mapping[str, Any]) -> str:
        """Hand off one task; returns an opaque lane receipt id."""
        ...

    def poll(self, receipt: str) -> "LaneStatus":
        """Report the current state of a previously dispatched receipt."""
        ...


@dataclass(frozen=True)
class LaneStatus:
    receipt: str
    state: str  # one of: "pending", "running", "done", "failed"
    detail: Mapping[str, Any]


def _load_group(group: str):
    try:
        eps = entry_points(group=group)
    except TypeError:  # pragma: no cover - py<3.10 entry_points signature
        eps = entry_points().get(group, [])
    return list(eps)


def load_score_store(name: str | None = None) -> ScoreStore:
    """Instantiate a registered `mco.score_store` implementation.

    Raises ScoreExtensionError if none is registered, or if `name` is given
    and no entry point matches it.
    """
    return _load_one("mco.score_store", name)


def load_evidence_verifier(name: str | None = None) -> EvidenceVerifier:
    return _load_one("mco.evidence_verifier", name)


def load_lane_adapter(name: str | None = None) -> LaneAdapter:
    return _load_one("mco.lane_adapter", name)


def _load_one(group: str, name: str | None):
    candidates = _load_group(group)
    if name is not None:
        candidates = [ep for ep in candidates if ep.name == name]
    if not candidates:
        raise ScoreExtensionError(f"No implementation registered for entry-point group {group!r}"
                                   + (f" named {name!r}" if name else ""))
    factory = candidates[0].load()
    return factory()
