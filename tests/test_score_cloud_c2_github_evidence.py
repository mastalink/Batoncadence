"""C2 GitHub evidence verifier shadow mode — acceptance stub."""
import pytest

GITHUB_EVIDENCE_INTERFACE_NAMES = (
    "GitHubEvidenceVerifier",
    "ShadowVerifyReport",
    "verify_pull_request_evidence",
)

pytestmark = pytest.mark.skip(reason="C2 GitHub evidence verifier not implemented yet")


def test_c2_github_evidence_placeholders():
    assert "GitHubEvidenceVerifier" in GITHUB_EVIDENCE_INTERFACE_NAMES
