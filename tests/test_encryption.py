"""Unit tests for AES-256-GCM secret store."""

import tempfile
import base64
import json
from pathlib import Path
import pytest
from mco.security import SecretStore, PasswordKeyProvider, get_secret_store


def test_derive_key():
    """Verify that key derivation produces a reliable 32-byte key."""
    password = "SuperSecurePassword123"
    salt = b"0" * 32
    key1 = SecretStore.derive_key(password, salt, iterations=1000)
    key2 = SecretStore.derive_key(password, salt, iterations=1000)
    assert len(key1) == 32
    assert key1 == key2

    # Different iterations -> different key
    key3 = SecretStore.derive_key(password, salt, iterations=2000)
    assert key1 != key3


def test_secret_store_lifecycle():
    """Test standard initialize, set, get, lock, unlock flow."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store_path = Path(tmpdir) / "secrets.enc"
        store = SecretStore(store_path=store_path)
        
        # 1. State queries on uninitialized
        assert not store.is_initialized()
        assert not store.is_unlocked
        
        # 2. Initialize
        master_key = b"A" * 32
        store.initialize(master_key)
        assert store.is_initialized()
        assert store.is_unlocked
        
        # 3. Insert and retrieve key
        store.set("GEMINI_API_KEY", "gemini_secret_123")
        assert store.get("GEMINI_API_KEY") == "gemini_secret_123"
        
        # 4. Lock
        store.lock()
        assert not store.is_unlocked
        with pytest.raises(RuntimeError):
            store.get("GEMINI_API_KEY")
            
        # 5. Unlock with WRONG key
        wrong_key = b"B" * 32
        success = store.unlock(wrong_key)
        assert not success
        assert not store.is_unlocked
        
        # 6. Unlock with CORRECT key
        success = store.unlock(master_key)
        assert success
        assert store.is_unlocked
        assert store.get("GEMINI_API_KEY") == "gemini_secret_123"
        
        # 7. Check file envelope structure
        raw_content = store_path.read_text(encoding="utf-8")
        envelope = json.loads(raw_content)
        assert envelope["version"] == 1
        assert "salt" in envelope
        assert "nonce" in envelope
        assert "tag" in envelope
        assert "ciphertext" in envelope


def test_windows_credential_provider_mock(monkeypatch):
    """Verify WindowsCredentialProvider behavior and mock integration."""
    from mco.security import WindowsCredentialProvider

    # Mock the win32cred library
    mock_creds = {}

    class MockWin32Cred:
        CRED_TYPE_GENERIC = 1
        CRED_PERSIST_LOCAL_MACHINE = 2

        @staticmethod
        def CredWrite(credential, flags):
            mock_creds[credential["TargetName"]] = credential["CredentialBlob"]

        @staticmethod
        def CredRead(target_name, type_):
            if target_name in mock_creds:
                return {
                    "CredentialBlob": mock_creds[target_name]
                }
            return None

    monkeypatch.setattr("sys.platform", "win32")
    import sys
    sys.modules["win32cred"] = MockWin32Cred  # type: ignore

    # Store key
    test_key = b"C" * 32
    WindowsCredentialProvider.store_key(test_key)
    
    # Read key
    provider = WindowsCredentialProvider()
    retrieved_key = provider.get_key()
    assert retrieved_key == test_key
