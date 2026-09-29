"""C3 scoped task credentials — acceptance stub."""
import pytest

SCOPED_CREDENTIAL_INTERFACE_NAMES = (
    "mint_task_credential",
    "verify_task_credential",
    "TaskCredentialClaims",
)

pytestmark = pytest.mark.skip(reason="C3 scoped credentials not implemented yet")


def test_c3_scoped_credential_placeholders():
    assert "mint_task_credential" in SCOPED_CREDENTIAL_INTERFACE_NAMES
