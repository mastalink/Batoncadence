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
