"""C7 Beast site agent — acceptance stub."""
import pytest

SITE_AGENT_INTERFACE_NAMES = (
    "SiteAgentSession",
    "resume_without_duplicate_effects",
)

pytestmark = pytest.mark.skip(reason="C7 site agent not implemented yet")


def test_c7_site_agent_placeholders():
    assert "SiteAgentSession" in SITE_AGENT_INTERFACE_NAMES
