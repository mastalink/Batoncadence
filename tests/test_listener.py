"""Tests for the Agent Listener Worker (src/mco/orchestrator/listener.py)"""

import pytest
from unittest.mock import patch, MagicMock
from mco.orchestrator.listener import AgentListener, _shell_executor_enabled


def test_shell_executor_disabled_by_default():
    """Shell executor must be opt-in."""
    assert _shell_executor_enabled() is False


@patch("mco.config.get_config")
@patch("os.environ.get")
def test_shell_executor_enabled_via_env(mock_env, mock_config):
    """MCO_ENABLE_SHELL_EXECUTOR=1 enables shell commands."""
    mock_config.return_value = {}
    mock_env.return_value = "1"
    assert _shell_executor_enabled() is True


@pytest.mark.asyncio
@patch("mco.orchestrator.listener.AgentListener._websocket_loop")
@patch("mco.orchestrator.listener.AgentListener._periodic_poll_loop")
async def test_start_loops(mock_poll, mock_ws):
    """Start method launches both loops."""
    listener = AgentListener()
    await listener.start()
    mock_poll.assert_called_once()
    mock_ws.assert_called_once()


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_poll_and_execute_no_jobs(mock_get):
    """Empty poll response doesn't crash."""
    mock_get.return_value = MagicMock(status_code=200, json=lambda: [])
    listener = AgentListener()
    await listener.poll_and_execute()  # Should not raise


@pytest.mark.asyncio
@patch("mco.orchestrator.listener.AgentListener._process_single_job")
@patch("httpx.AsyncClient.get")
async def test_poll_and_execute_with_jobs(mock_get, mock_process):
    """Pending jobs trigger processing."""
    mock_get.return_value = MagicMock(status_code=200, json=lambda: [{"id": "job1"}])
    listener = AgentListener()
    await listener.poll_and_execute()
    mock_process.assert_called_once()