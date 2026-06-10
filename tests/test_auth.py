"""Unit tests for gateway bearer-token auth and the dropbox authorization model."""

import pytest
from fastapi import HTTPException

import mco.orchestrator.routes as routes_mod
from mco.orchestrator.auth import hash_token, verify_token, extract_bearer, require_agent


class FakeAgentDB:
    """Minimal fake resolving agent_registry rows by auth_token_hash."""

    def __init__(self, agents):
        self._agents = agents
        self._table = None
        self._filters = {}

    def table(self, name):
        self._table = name
        self._filters = {}
        return self

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def order(self, *a, **k):
        return self

    def execute(self):
        class R:
            def __init__(self, data):
                self.data = data

        if self._table == "agent_registry":
            th = self._filters.get("auth_token_hash")
            rows = [a for a in self._agents if a.get("auth_token_hash") == th]
            # API/contract never returns the hash column.
            return R([{k: v for k, v in a.items() if k != "auth_token_hash"} for a in rows])
        return R([])


def test_hash_token_stable_and_distinct():
    assert hash_token("abc") == hash_token("abc")
    assert hash_token("abc") != hash_token("abd")


def test_extract_bearer():
    assert extract_bearer("Bearer xyz") == "xyz"
    assert extract_bearer("bearer  xyz ") == "xyz"
    assert extract_bearer("Token xyz") == ""
    assert extract_bearer("") == ""


def test_verify_token_matches_and_rejects():
    tok = "mco_tok_secret"
    db = FakeAgentDB([{"instance_id": "w1", "role": "codex", "auth_token_hash": hash_token(tok)}])
    agent = verify_token(db, tok)
    assert agent is not None
    assert agent["instance_id"] == "w1" and agent["role"] == "codex"
    assert "auth_token_hash" not in agent  # never leaked back
    assert verify_token(db, "wrong-token") is None
    assert verify_token(db, "") is None


@pytest.mark.asyncio
async def test_require_agent_auth_paths(monkeypatch):
    tok = "mco_tok_secret"
    db = FakeAgentDB([{"instance_id": "w1", "role": "codex", "auth_token_hash": hash_token(tok)}])
    monkeypatch.setattr(routes_mod, "get_db_client", lambda: db)

    agent = await require_agent(authorization=f"Bearer {tok}")
    assert agent["role"] == "codex"

    with pytest.raises(HTTPException) as missing:
        await require_agent(authorization="")
    assert missing.value.status_code == 401

    with pytest.raises(HTTPException) as bad:
        await require_agent(authorization="Bearer not-a-real-token")
    assert bad.value.status_code == 401

    # Local-Only mode: no DB, no MCO_LOCAL_TOKEN configured -> any bearer accepted.
    import mco.orchestrator.auth as auth_mod

    class _NullCfg:
        def get(self, key):
            return None

    monkeypatch.setattr(routes_mod, "get_db_client", lambda: None)
    monkeypatch.setattr(auth_mod, "get_config", lambda: _NullCfg())
    agent_local = await require_agent(authorization=f"Bearer {tok}")
    assert agent_local["instance_id"] == "local"
    assert agent_local["role"] == "admin"

    # Local-Only with MCO_LOCAL_TOKEN set: wrong token -> 401.
    class _TokenCfg:
        def get(self, key):
            return "correct-local-token" if key == "MCO_LOCAL_TOKEN" else None

    monkeypatch.setattr(auth_mod, "get_config", lambda: _TokenCfg())
    with pytest.raises(HTTPException) as bad_local:
        await require_agent(authorization="Bearer wrong-local-token")
    assert bad_local.value.status_code == 401

    # Correct local token accepted.
    agent_local2 = await require_agent(authorization="Bearer correct-local-token")
    assert agent_local2["instance_id"] == "local"
