"""C9 cross-lane canary — acceptance stub."""
import pytest

CROSS_LANE_INTERFACE_NAMES = (
    "CrossLaneCanary",
    "complete_evidence_trail",
)

pytestmark = pytest.mark.skip(reason="C9 cross-lane canary not implemented yet")


def test_c9_cross_lane_placeholders():
    assert "complete_evidence_trail" in CROSS_LANE_INTERFACE_NAMES
