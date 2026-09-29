"""C4 issue-dispatch lane — acceptance stub."""
import pytest

ISSUE_DISPATCH_INTERFACE_NAMES = (
    "IssueDispatchAdapter",
    "DispatchReceipt",
    "vendor_canary_fixture",
)

pytestmark = pytest.mark.skip(reason="C4 issue-dispatch adapter not implemented yet")


def test_c4_issue_dispatch_placeholders():
    assert "IssueDispatchAdapter" in ISSUE_DISPATCH_INTERFACE_NAMES
