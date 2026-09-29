"""F / C2 — Shadow GitHub evidence verifier against fixtures (no live App tokens)."""

from __future__ import annotations

from pathlib import Path

import pytest

from mco.orchestrator.score_cloud.github_evidence import (
    GitHubEvidenceVerifier,
    load_github_fixtures,
    verify_pull_request_evidence,
)

FIXTURES = Path(__file__).parent / "fixtures" / "github_evidence"


@pytest.fixture(scope="module")
def fixtures():
    return load_github_fixtures(FIXTURES)


def _claim(number: int, head_sha: str, **extra):
    base = {
        "repo": "mastalink/via",
        "number": number,
        "head_sha": head_sha,
        "base_ref": "codex/via-foundation",
        "required_checks": ["Verify Via"],
    }
    base.update(extra)
    return base


def test_missing_ci_refuses_pr_41_and_46(fixtures):
    verifier = GitHubEvidenceVerifier(fixtures)
    r41 = verifier.verify_pull_request_evidence(
        claim=_claim(41, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    )
    assert r41.accepted is False
    assert "missing_ci" in r41.would_refuse
    assert r41.as_dict()["mutates_github"] is False
    assert r41.as_dict()["mode"] == "shadow"

    r46 = verify_pull_request_evidence(
        _claim(46, "1111111111111111111111111111111111111111"),
        fixtures=fixtures,
    )
    assert r46.accepted is False
    assert "missing_ci" in r46.would_refuse


def test_green_ci_and_review_accepts_pr_42_and_44(fixtures):
    verifier = GitHubEvidenceVerifier(fixtures)
    r42 = verifier.verify_pull_request_evidence(
        claim=_claim(42, "cccccccccccccccccccccccccccccccccccccccc")
    )
    assert r42.accepted is True
    assert r42.would_refuse == ()
    assert "check_runs" in r42.checked and "review" in r42.checked

    r44 = verifier.verify_pull_request_evidence(
        claim=_claim(44, "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee")
    )
    assert r44.accepted is True


def test_fork_and_unallowlisted_app_refuse_pr_43(fixtures):
    report = GitHubEvidenceVerifier(fixtures).verify_pull_request_evidence(
        claim=_claim(43, "dddddddddddddddddddddddddddddddddddddddd")
    )
    assert report.accepted is False
    assert "fork_head_ignored" in report.would_refuse
    assert any(r.startswith("unallowlisted_app:") for r in report.would_refuse) or any(
        r.startswith("missing_check:") for r in report.would_refuse
    )


def test_wrong_check_head_refuses_pr_45(fixtures):
    report = GitHubEvidenceVerifier(fixtures).verify_pull_request_evidence(
        claim=_claim(45, "ffffffffffffffffffffffffffffffffffffffff")
    )
    assert report.accepted is False
    assert "check_wrong_head:Verify Via" in report.would_refuse


def test_same_author_reviewer_refuses(fixtures):
    report = GitHubEvidenceVerifier(fixtures).verify_pull_request_evidence(
        claim=_claim(
            44,
            "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
            author_login="copilot-swe-agent[bot]",
            reviewer_login="copilot-swe-agent[bot]",
        )
    )
    assert report.accepted is False
    assert "reviewer_same_as_author" in report.would_refuse


def test_no_live_token_literals_in_module():
    src = Path(__file__).parents[1] / "src/mco/orchestrator/score_cloud/github_evidence.py"
    text = src.read_text(encoding="utf-8").lower()
    for banned in ("ghp_", "github_pat_", "private_key", "-----begin", "app_id"):
        assert banned not in text
