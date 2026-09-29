"""C1 Postgres Score store interface — acceptance stub."""
import pytest

# Interface placeholders the packet must introduce (names only until implemented).
SCORE_STORE_INTERFACE_NAMES = (
    "ScoreStore",
    "SqliteScoreStore",
    "PostgresScoreStore",
    "score_store_parity_events",
)

pytestmark = pytest.mark.skip(reason="C1 store interface not implemented yet; placeholder keeps CI green")


def test_c1_store_interface_placeholders():
    assert "ScoreStore" in SCORE_STORE_INTERFACE_NAMES
    assert "score_store_parity_events" in SCORE_STORE_INTERFACE_NAMES
