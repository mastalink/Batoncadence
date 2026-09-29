"""Score v2 extension points: generic contracts, no cloud specifics."""
import pytest

from mco.orchestrator.score_extensions import (
    EvidenceVerdict,
    EvidenceVerifier,
    LaneAdapter,
    LaneStatus,
    ScoreEventRecord,
    ScoreExtensionError,
    ScoreRunRecord,
    ScoreStore,
    ScoreTaskRecord,
    load_evidence_verifier,
    load_lane_adapter,
    load_score_store,
)


def test_score_store_is_abstract_with_no_bundled_implementation():
    with pytest.raises(TypeError):
        ScoreStore()  # abstract: core ships no store implementation


def test_score_store_subclass_must_implement_full_contract():
    class Incomplete(ScoreStore):
        def create_run(self, record):
            return None

    with pytest.raises(TypeError):
        Incomplete()


def test_score_store_full_subclass_instantiates():
    class Fake(ScoreStore):
        def create_run(self, record):
            self.record = record

        def get_run(self, run_id):
            return None

        def upsert_task(self, record):
            return None

        def get_task(self, run_id, task_id):
            return None

        def append_event(self, run_id, event_type, detail):
            return ScoreEventRecord(seq=1, run_id=run_id, event_type=event_type, detail=detail)

        def list_events(self, run_id):
            return []

    store = Fake()
    store.create_run(ScoreRunRecord(run_id="r1", org_id="o1", score_id="s1", score_digest="d", status="pending", definition={}))
    assert store.record.run_id == "r1"


def test_evidence_verifier_is_a_runtime_checkable_protocol():
    class Fake:
        def verify(self, *, task_id, claim):
            return EvidenceVerdict(accepted=True, checked=("x",))

    assert isinstance(Fake(), EvidenceVerifier)
    assert Fake().verify(task_id="t1", claim={}).accepted is True


def test_lane_adapter_is_a_runtime_checkable_protocol():
    class Fake:
        def dispatch(self, *, task_id, payload):
            return "receipt-1"

        def poll(self, receipt):
            return LaneStatus(receipt=receipt, state="done", detail={})

    fake = Fake()
    assert isinstance(fake, LaneAdapter)
    assert fake.poll(fake.dispatch(task_id="t1", payload={})).state == "done"


def test_score_task_record_is_a_plain_value_object():
    record = ScoreTaskRecord(run_id="r1", task_id="t1", status="pending", attempt=1, detail={})
    assert record.task_id == "t1"


@pytest.mark.parametrize("loader", [load_score_store, load_evidence_verifier, load_lane_adapter])
def test_loaders_refuse_when_nothing_is_registered(loader):
    with pytest.raises(ScoreExtensionError):
        loader(name="nonexistent-extension-for-tests")
