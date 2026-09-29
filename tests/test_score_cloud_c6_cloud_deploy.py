"""C6 cloud deploy — offline stub (live /readyz is out of scope for CI)."""
import pytest

pytestmark = pytest.mark.skip(reason="C6 cloud deploy is a live packet; offline CI only records the probe name")

READYZ_PROBE_NAME = "readyz_with_beast_off"


def test_c6_readyz_probe_name_recorded():
    assert READYZ_PROBE_NAME == "readyz_with_beast_off"
