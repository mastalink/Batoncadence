"""C0 human prerequisites — checklist stub (no cloud deploy)."""
from pathlib import Path

import pytest

pytestmark = pytest.mark.skip(reason="C0 is a human packet (Via billing + Postgres host choice); not automatable offline")


def test_c0_checklist_documented():
    root = Path(__file__).parents[1]
    assert (root / "docs/SCORE-CLOUD-V2-PACKETS.md").is_file()
    assert (root / "docs/SCORE-CLOUD-V2.md").is_file()
