"""Unit tests for configuration manager and profiles."""

import tempfile
from pathlib import Path
import pytest

from mco.config import ConfigManager, EnvironmentProfile


def test_config_profiles():
    """Verify standard environment profile constants."""
    assert EnvironmentProfile.LOCAL_ONLY == "Local-Only"
    assert EnvironmentProfile.CLOUD_HEAVY == "Cloud-Heavy"
    assert EnvironmentProfile.HYBRID == "Hybrid"
    assert len(EnvironmentProfile.all_profiles()) == 3


def test_config_manager_file_io():
    """Verify that writing settings writes to the underlying file, and overlays read correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        env_file = Path(tmpdir) / ".env"
        store_file = Path(tmpdir) / "secrets.enc"
        
        manager = ConfigManager(env_path=env_file, store_path=store_file)
        
        # Initial is empty
        assert manager.get("OPERATOR_NAME") is None
        
        # Plain write
        manager.set("OPERATOR_NAME", "Jane Doe")
        assert manager.get("OPERATOR_NAME") == "Jane Doe"
        
        # Verify it was written to disk
        content = env_file.read_text(encoding="utf-8")
        assert "OPERATOR_NAME=Jane Doe" in content

        # Reload manager and verify it retrieves the key
        new_manager = ConfigManager(env_path=env_file, store_path=store_file)
        assert new_manager.get("OPERATOR_NAME") == "Jane Doe"


def test_masked_config():
    """Verify that sensitive keys are masked in output."""
    with tempfile.TemporaryDirectory() as tmpdir:
        env_file = Path(tmpdir) / ".env"
        
        manager = ConfigManager(env_path=env_file)
        manager.set("SUPABASE_KEY", "sb_key_123456789")
        manager.set("OPERATOR_NAME", "Alice")
        
        masked = manager.get_masked_config()
        
        # Plain setting remains plain
        assert masked["OPERATOR_NAME"] == "Alice"
        # Sensitive setting is masked
        assert masked["SUPABASE_KEY"].startswith("sb")
        assert "*" in masked["SUPABASE_KEY"]
        assert "123456789" not in masked["SUPABASE_KEY"]


def test_config_manager_encryption():
    """Verify that ConfigManager.set(..., encrypt=True) behaves correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        env_file = Path(tmpdir) / ".env"
        store_file = Path(tmpdir) / "secrets.enc"
        
        manager = ConfigManager(env_path=env_file, store_path=store_file)
        
        # Reset and prepare the store state
        store = manager._store
        store.lock()
        try:
            Path(store._path).unlink(missing_ok=True)
        except Exception:
            pass
        store._secrets = None
        store._master_key = None
        store._envelope = None
        
        master_key = b"A" * 32
        store.initialize(master_key)
        
        # Verify store is unlocked initially
        assert store.is_unlocked
        
        # Use manager to set an encrypted value
        manager.set("SUPABASE_KEY", "super_secret_supabase_key", encrypt=True)
        
        # 1. Plain setting in .env must be the placeholder string
        assert env_file.is_file()
        content = env_file.read_text(encoding="utf-8")
        assert "SUPABASE_KEY=encrypted_in_secret_store" in content
        
        # 2. Getting from unlocked manager must return the real key
        assert manager.get("SUPABASE_KEY") == "super_secret_supabase_key"
        
        # 3. Lock store and confirm it returns the placeholder
        store.lock()
        assert not store.is_unlocked
        assert manager.get("SUPABASE_KEY") == "encrypted_in_secret_store"
        
        # 4. Unlock store and confirm it returns the real key again
        assert store.unlock(master_key)
        assert store.is_unlocked
        assert manager.get("SUPABASE_KEY") == "super_secret_supabase_key"

