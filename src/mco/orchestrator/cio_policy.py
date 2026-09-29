"""Deterministic policy checks for the claude-cio sidecar.

The sidecar itself is an LLM reading `ops/CIO_BRIEF.md` - free-form proposals
need judgment a fixed function cannot supply. But a handful of the brief's
rules ARE mechanical (a dollar figure against a cap, a category against a
prohibited list, "did the proposer also plan this"), and those are exactly
the rules an LLM under time pressure is most likely to round in its own
favor. This module makes them a function call instead of a vibe, so the
worker loop (or a test) can check a proposal the same way twice.

This is a policy boundary, not a dispatch adapter: it returns a verdict and
reasons, and never itself calls a notifier, the gateway, or Exchange.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

APPROVE = "approve"
REJECT = "reject"
ESCALATE = "escalate"

CHIEF_ONLINE_THRESHOLD_SECONDS = 300

# Cents, to avoid float comparison on money. `None` cap = no automatic figure
# (Operate has "new spend under $10" with no monthly total defined here).
SPEND_CAPS_CENTS: dict[str, Optional[int]] = {
    "via": 15_000,
    "mymeals": 1_500,
    "sim_lab": 2_500,
    "operate": 1_000,
}
SIM_LAB_HARD_STOP_CENTS = 4_000

PROHIBITED_CATEGORIES = frozenset({
    "bank_client",
    "finance_client",
    "live_trading",
    "bypass_bot_check",
    "paid_github",
    "mac_claude",
    "codex_mac",
    "automated_client_messaging",
    "print_secret",
})

ESCALATE_CATEGORIES = frozenset({
    "security_credential_change",
    "legal_trademark_licensing",
    "real_money_finance",
    "delete_data",
} | PROHIBITED_CATEGORIES)


@dataclass(frozen=True)
class Proposal:
    """The minimum a proposal must state for policy to be checkable at all."""
    project: str = ""
    spend_cents: int = 0
    categories: frozenset[str] = field(default_factory=frozenset)
    proposed_by: str = ""


@dataclass(frozen=True)
class Decision:
    verdict: str
    reasons: tuple[str, ...]

    @property
    def approved(self) -> bool:
        return self.verdict == APPROVE


def chief_is_online(claude_desktop_last_seen_seconds: Optional[float]) -> bool:
    """True when claude-desktop's own heartbeat means it - not the sidecar -
    holds the Chief seat right now."""
    if claude_desktop_last_seen_seconds is None:
        return False
    return claude_desktop_last_seen_seconds < CHIEF_ONLINE_THRESHOLD_SECONDS


def over_spend_cap(project: str, spend_cents: int) -> bool:
    key = (project or "").strip().lower().replace(" ", "_").replace("-", "_")
    cap = SPEND_CAPS_CENTS.get(key)
    if cap is None:
        return False
    if key == "sim_lab" and spend_cents >= SIM_LAB_HARD_STOP_CENTS:
        return True
    return spend_cents >= cap


def evaluate(proposal: Proposal, *, decider: str) -> Decision:
    """Check one proposal against the brief's mechanical rules.

    `decider` is the identity about to render the verdict - passed
    explicitly (never inferred) so a self-approval check cannot be skipped
    by a caller who forgot to set it.
    """
    reasons: list[str] = []

    if proposal.proposed_by and decider and proposal.proposed_by == decider:
        return Decision(
            ESCALATE,
            (f"{decider} proposed this and may not also approve it (self-approval "
             "is never permitted; route to Grok or to Joseph)",),
        )

    blocking = sorted(proposal.categories & PROHIBITED_CATEGORIES)
    if blocking:
        return Decision(
            REJECT,
            tuple(f"prohibited: {category}" for category in blocking),
        )

    escalating = sorted(proposal.categories & ESCALATE_CATEGORIES)
    if escalating:
        reasons.extend(f"escalation category: {category}" for category in escalating)

    if over_spend_cap(proposal.project, proposal.spend_cents):
        reasons.append(
            f"spend ${proposal.spend_cents / 100:.2f} is at or over the "
            f"{proposal.project or 'unspecified'} cap"
        )

    if reasons:
        return Decision(ESCALATE, tuple(reasons))

    return Decision(
        APPROVE,
        (f"no prohibited or escalation category matched; spend "
         f"${proposal.spend_cents / 100:.2f} is within the {proposal.project or 'unspecified'} "
         "cap" if proposal.project else "no prohibited or escalation category matched",),
    )
