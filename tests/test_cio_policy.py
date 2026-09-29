from mco.orchestrator import cio_policy
from mco.orchestrator.cio_policy import Proposal


def test_synthetic_clean_plan_is_approved_with_reasons():
    proposal = Proposal(
        project="via",
        spend_cents=500,
        categories=frozenset(),
        proposed_by="chief-beast",
    )

    decision = cio_policy.evaluate(proposal, decider="claude-cio")

    assert decision.approved
    assert decision.verdict == cio_policy.APPROVE
    assert decision.reasons  # approval always carries its own justification
    assert "cap" in decision.reasons[0]


def test_over_cap_spend_is_escalated_not_approved():
    proposal = Proposal(
        project="mymeals",
        spend_cents=1_500,  # at the $15 cap
        categories=frozenset(),
        proposed_by="chief-beast",
    )

    decision = cio_policy.evaluate(proposal, decider="claude-cio")

    assert decision.verdict == cio_policy.ESCALATE
    assert any("spend" in reason for reason in decision.reasons)


def test_sim_lab_hard_stop_escalates_even_under_the_soft_cap_label():
    proposal = Proposal(
        project="sim_lab",
        spend_cents=4_000,
        categories=frozenset(),
        proposed_by="chief-beast",
    )

    decision = cio_policy.evaluate(proposal, decider="claude-cio")

    assert decision.verdict == cio_policy.ESCALATE


def test_prohibited_category_is_rejected_outright():
    proposal = Proposal(
        project="operations",
        spend_cents=0,
        categories=frozenset({"live_trading"}),
        proposed_by="chief-beast",
    )

    decision = cio_policy.evaluate(proposal, decider="claude-cio")

    assert decision.verdict == cio_policy.REJECT
    assert any("live_trading" in reason for reason in decision.reasons)


def test_security_credential_change_is_escalated():
    proposal = Proposal(
        project="operations",
        spend_cents=0,
        categories=frozenset({"security_credential_change"}),
        proposed_by="chief-beast",
    )

    decision = cio_policy.evaluate(proposal, decider="claude-cio")

    assert decision.verdict == cio_policy.ESCALATE


def test_sidecar_cannot_approve_its_own_proposal():
    proposal = Proposal(
        project="via",
        spend_cents=100,
        categories=frozenset(),
        proposed_by="claude-cio",
    )

    decision = cio_policy.evaluate(proposal, decider="claude-cio")

    assert decision.verdict == cio_policy.ESCALATE
    assert "self-approval" in decision.reasons[0]


def test_chief_online_threshold_uses_five_minute_heartbeat():
    assert cio_policy.chief_is_online(0) is True
    assert cio_policy.chief_is_online(299) is True
    assert cio_policy.chief_is_online(300) is False
    assert cio_policy.chief_is_online(None) is False


def test_missing_proposed_by_fails_closed_to_escalate():
    proposal = Proposal(
        project="via",
        spend_cents=100,
        categories=frozenset(),
        proposed_by="",
    )

    decision = cio_policy.evaluate(proposal, decider="claude-cio")

    assert decision.verdict == cio_policy.ESCALATE
    assert "proposed_by" in decision.reasons[0]


def test_whitespace_only_proposed_by_fails_closed_to_escalate():
    proposal = Proposal(
        project="via",
        spend_cents=100,
        categories=frozenset(),
        proposed_by="   ",
    )

    decision = cio_policy.evaluate(proposal, decider="claude-cio")

    assert decision.verdict == cio_policy.ESCALATE
    assert "proposed_by" in decision.reasons[0]


def test_blank_decider_fails_closed_to_escalate():
    proposal = Proposal(
        project="via",
        spend_cents=100,
        categories=frozenset(),
        proposed_by="claude-cio",
    )

    decision = cio_policy.evaluate(proposal, decider="")

    assert decision.verdict == cio_policy.ESCALATE
    assert "decider" in decision.reasons[0]


def test_case_mismatched_self_approval_still_escalates():
    proposal = Proposal(
        project="via",
        spend_cents=100,
        categories=frozenset(),
        proposed_by="Claude-CIO",
    )

    decision = cio_policy.evaluate(proposal, decider="claude-cio")

    assert decision.verdict == cio_policy.ESCALATE
    assert "self-approval" in decision.reasons[0]


def test_unknown_project_spend_fails_closed_to_escalate():
    proposal = Proposal(
        project="a-new-client-nobody-defined-a-cap-for",
        spend_cents=100,
        categories=frozenset(),
        proposed_by="chief-beast",
    )

    decision = cio_policy.evaluate(proposal, decider="claude-cio")

    assert decision.verdict == cio_policy.ESCALATE
    assert any("no defined spend cap" in reason for reason in decision.reasons)


def test_unknown_project_with_zero_spend_is_not_penalized():
    proposal = Proposal(
        project="a-new-client-nobody-defined-a-cap-for",
        spend_cents=0,
        categories=frozenset(),
        proposed_by="chief-beast",
    )

    decision = cio_policy.evaluate(proposal, decider="claude-cio")

    assert decision.verdict == cio_policy.APPROVE
