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
def mco_send(to_role: str, title: str, instructions: str, to_instance: str = "",
             requires_approval: bool = False, max_retries: int = 0,
             escalate_to_role: str = "") -> dict:
    """Drop a task/message into another agent's dropbox. to_instance is optional
    (omit to address the whole role). Set requires_approval=True to pause the job
    at a human approval gate; max_retries/escalate_to_role control what happens
    when the job fails."""
    return _client().send(to_role, title, instructions, to_instance or None,
                          requires_approval=requires_approval, max_retries=max_retries,
                          escalate_to_role=escalate_to_role or None)


@mcp.tool()
def mco_approve(task_id: str) -> dict:
    """Approve a job paused at the human-in-the-loop gate, releasing it for
    execution. Only approver roles (MCO_APPROVER_ROLES) may call this."""
    return _client().approve(task_id)


@mcp.tool()
def mco_reject(task_id: str, reason: str = "") -> dict:
    """Reject a job paused at the human-in-the-loop gate (terminal). Only
    approver roles (MCO_APPROVER_ROLES) may call this."""
    return _client().reject(task_id, reason)


@mcp.tool()
def mco_audit(task_id: str) -> List[dict]:
    """Read a job's immutable audit trail (create/lease/status/approval/retry/
    escalation events), oldest first."""
    return _client().events(task_id)


@mcp.tool()
def mco_agents() -> List[dict]:
    """List registered agents and their online/offline presence."""
    return _client().agents()


@mcp.tool()
def mco_integrations() -> List[dict]:
    """List configured enterprise connectors (ServiceNow, Dynatrace, ...) with
    health status and the platform actions each one supports."""
    return _client().integrations()


@mcp.tool()
def mco_sync_connector(name: str) -> dict:
    """Pull open platform objects (ServiceNow incidents / Dynatrace problems)
    onto the job board as agent jobs. Idempotent - already-ingested objects are
    skipped via their external_id."""
    return _client().sync_connector(name)


@mcp.tool()
def mco_platform_action(name: str, action: str, params: dict = None) -> dict:
    """Run an enterprise platform action through a connector (e.g.
    servicenow create_incident / resolve_incident, dynatrace add_comment /
    close_problem). Requires an approver-role token."""
    return _client().platform_action(name, action, params or {})


def run() -> None:
    """Run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    run()
