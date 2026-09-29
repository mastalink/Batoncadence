"""C5 conductor-owned merge — acceptance stub."""
import pytest

CONDUCTOR_MERGE_INTERFACE_NAMES = (
    "ConductorMergeEffect",
    "required_score_status",
    "void_acceptance_on_new_head",
)

pytestmark = pytest.mark.skip(reason="C5 conductor-owned merge not implemented yet")


def test_c5_conductor_merge_placeholders():
    assert "required_score_status" in CONDUCTOR_MERGE_INTERFACE_NAMES
