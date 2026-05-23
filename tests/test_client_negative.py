"""Client negative-path tests: HTTP errors and timeouts propagate cleanly."""

import pytest
import httpx

from mco.orchestrator.client import GatewayClient

BASE = "http://127.0.0.1:18789"


def _client_with_status(status: int) -> GatewayClient:
    """GatewayClient whose every request returns a fixed HTTP error status."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": "test-error"})

    return GatewayClient(
        base_url=BASE, token="tok", role="codex", instance_id="agent-1",
        transport=httpx.MockTransport(handler),
    )


def _client_with_read_timeout() -> GatewayClient:
    """GatewayClient whose every request raises ReadTimeout."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated timeout", request=request)

    return GatewayClient(
        base_url=BASE, token="tok", role="codex", instance_id="agent-1",
        transport=httpx.MockTransport(handler),
    )


# ── HTTP status error paths ───────────────────────────────────────────────────

def test_inbox_raises_on_401():
    with pytest.raises(httpx.HTTPStatusError) as exc:
        _client_with_status(401).inbox()
    assert exc.value.response.status_code == 401


def test_lease_raises_on_403():
    with pytest.raises(httpx.HTTPStatusError) as exc:
        _client_with_status(403).lease("j1")
    assert exc.value.response.status_code == 403


def test_complete_raises_on_500():
    with pytest.raises(httpx.HTTPStatusError) as exc:
        _client_with_status(500).complete("j1", "result")
    assert exc.value.response.status_code == 500


def test_fail_raises_on_503():
    with pytest.raises(httpx.HTTPStatusError) as exc:
        _client_with_status(503).fail("j1", "error msg")
    assert exc.value.response.status_code == 503


def test_send_raises_on_400():
    with pytest.raises(httpx.HTTPStatusError) as exc:
        _client_with_status(400).send("claude", "title", "instructions")
    assert exc.value.response.status_code == 400


def test_agents_raises_on_503():
    with pytest.raises(httpx.HTTPStatusError) as exc:
        _client_with_status(503).agents()
    assert exc.value.response.status_code == 503


def test_all_methods_raise_http_status_error_not_generic_exception():
    """Every client method surfaces HTTPStatusError (not a bare Exception) for 4xx/5xx."""
    c = _client_with_status(404)
    for call in [
        lambda: c.inbox(),
        lambda: c.lease("j"),
        lambda: c.complete("j", "out"),
        lambda: c.fail("j", "err"),
        lambda: c.send("r", "t", "i"),
        lambda: c.agents(),
    ]:
        with pytest.raises(httpx.HTTPStatusError):
            call()


# ── Timeout paths ─────────────────────────────────────────────────────────────

def test_inbox_raises_on_read_timeout():
    with pytest.raises(httpx.ReadTimeout):
        _client_with_read_timeout().inbox()


def test_lease_raises_on_read_timeout():
    with pytest.raises(httpx.ReadTimeout):
        _client_with_read_timeout().lease("j2")


def test_complete_raises_on_read_timeout():
    with pytest.raises(httpx.ReadTimeout):
        _client_with_read_timeout().complete("j3", "output")


def test_fail_raises_on_read_timeout():
    with pytest.raises(httpx.ReadTimeout):
        _client_with_read_timeout().fail("j4", "error")


def test_send_raises_on_read_timeout():
    with pytest.raises(httpx.ReadTimeout):
        _client_with_read_timeout().send("claude", "title", "instructions")


def test_agents_raises_on_read_timeout():
    with pytest.raises(httpx.ReadTimeout):
        _client_with_read_timeout().agents()
