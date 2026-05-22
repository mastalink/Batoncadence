"""
MCO dropbox as an MCP stdio server.

Lets an IDE/agent (Claude, Codex, Antigravity) work the dropbox on its own
scheduler instead of running a `mco listen` daemon. Identity comes from env
(MCO_AGENT_TOKEN / AGENT_ROLE / AGENT_INSTANCE_ID / MCO_GATEWAY_URL).

IMPORTANT: stdio is the MCP transport — never print to stdout here.
"""

from typing import List

from mcp.server.fastmcp import FastMCP

from mco.orchestrator.client import GatewayClient

mcp = FastMCP("mco")


def _client() -> GatewayClient:
    # Built per-call so env changes are picked up and there's no shared HTTP state.
    return GatewayClient()


@mcp.tool()
def mco_inbox() -> List[dict]:
    """List the jobs/messages addressed to you (your dropbox) that are pending."""
    return _client().inbox()


@mcp.tool()
def mco_lease(task_id: str) -> dict:
    """Atomically claim a job before working it. Returns {'success': bool}."""
    return _client().lease(task_id)


@mcp.tool()
def mco_complete(task_id: str, output: str) -> dict:
    """Mark a leased job completed and attach its result text."""
    return _client().complete(task_id, output)


@mcp.tool()
def mco_fail(task_id: str, error: str) -> dict:
    """Mark a leased job failed with an error message."""
    return _client().fail(task_id, error)


@mcp.tool()
def mco_send(to_role: str, title: str, instructions: str, to_instance: str = "") -> dict:
    """Drop a task/message into another agent's dropbox. to_instance is optional
    (omit to address the whole role)."""
    return _client().send(to_role, title, instructions, to_instance or None)


@mcp.tool()
def mco_agents() -> List[dict]:
    """List registered agents and their online/offline presence."""
    return _client().agents()


def run() -> None:
    """Run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    run()
