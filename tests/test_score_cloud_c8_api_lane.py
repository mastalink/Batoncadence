"""C8 API lane + cost reservations — acceptance stub."""
import pytest

API_LANE_INTERFACE_NAMES = (
    "ApiLaneWorker",
    "reserve_cost_cents",
    "CostReservation",
)

pytestmark = pytest.mark.skip(reason="C8 API lane not implemented yet")


def test_c8_api_lane_placeholders():
    assert "reserve_cost_cents" in API_LANE_INTERFACE_NAMES
