"""
MCOrchestr8 Configuration Management
====================================
Handles environment profile selections and loading/writing settings
from local .env files and the encrypted SecretStore.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Any, Optional
from loguru import logger
from dotenv import load_dotenv, dotenv_values

from mco.security import get_secret_store

# Profiles
class EnvironmentProfile:
    LOCAL_ONLY = "Local-Only"
    CLOUD_HEAVY = "Cloud-Heavy"
    HYBRID = "Hybrid"

    @classmethod
    def all_profiles(cls) -> list[str]:
        return [cls.LOCAL_ONLY, cls.CLOUD_HEAVY, cls.HYBRID]


# Sensitive keys that should be encrypted in the secret store rather than plaintext .env
SENSITIVE_KEYS = {
    "SUPABASE_KEY",
    "SUPABASE_URL",
}


class ConfigManager:
    """Manages system configuration settings.

    Resolves values by combining standard .env variables
    with decrypted credentials in the SecretStore if available.
    """

    def __init__(self, env_path: Optional[Path] = None, store_path: Optional[Path] = None):
        self._env_path = env_path or Path(".env")
        self._store = get_secret_store(store_path)
        self._cached_config: Dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """Load configuration from environment, .env file, and secret store overlay."""
        # 1. Start with system env vars
        config = dict(os.environ)

        # 2. Overlay values from .env if present
        if self._env_path.is_file():
            dotenv_vals = dotenv_values(self._env_path)
            for k, v in dotenv_vals.items():
                if v is not None:
                    config[k] = v

        # 3. Attempt to auto-unlock secret store and overlay secrets
        if self._store.is_initialized():
            if not self._store.is_unlocked:
                self._store.auto_unlock()
            
            if self._store.is_unlocked:
                for key in self._store.list_keys():
                    secret_val = self._store.get(key)
                    if secret_val:
                        config[key] = secret_val

        self._cached_config = config

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a configuration value."""
        # Check if the secret store is unlocked and has the key
        if key in SENSITIVE_KEYS and self._store.is_unlocked:
            secret_val = self._store.get(key)
            if secret_val is not None:
                return secret_val

        return self._cached_config.get(key, default)

    def set(self, key: str, value: str, encrypt: bool = False) -> None:
        """Set a configuration parameter.

        If encrypt is True, stores it in the encrypted SecretStore.
        Otherwise, writes it as a plaintext entry in the local .env.
        """
        if encrypt:
            if not self._store.is_unlocked:
                raise RuntimeError("Secret store must be unlocked to set encrypted values.")
            self._store.set(key, value)
            # Remove any plaintext entry in local .env to prevent leaks
            self._update_dotenv_file(key, "encrypted_in_secret_store")
        else:
            self._update_dotenv_file(key, value)

        self._cached_config[key] = value

    def delete(self, key: str) -> None:
        """Delete a configuration parameter."""
        if self._store.is_unlocked and key in self._store.list_keys():
            self._store.delete(key)

        self._update_dotenv_file(key, None)
        self._cached_config.pop(key, None)

    def _update_dotenv_file(self, key: str, value: Optional[str]) -> None:
        """Write or remove a key in the local .env file atomically."""
        lines = []
        if self._env_path.is_file():
            lines = self._env_path.read_text(encoding="utf-8").splitlines()

        found = False
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#") or not stripped or "=" not in stripped:
                new_lines.append(line)
                continue
            
            k, v = stripped.split("=", 1)
            if k.strip() == key:
                found = True
                if value is not None:
                    new_lines.append(f"{key}={value}")
            else:
                new_lines.append(line)

        if not found and value is not None:
            new_lines.append(f"{key}={value}")

        self._env_path.parent.mkdir(parents=True, exist_ok=True)
        self._env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    def list_keys(self) -> list[str]:
        """List all loaded configuration keys."""
        keys = set(self._cached_config.keys())
        if self._store.is_unlocked:
            keys.update(self._store.list_keys())
        return sorted(list(keys))

    def get_masked_config(self) -> Dict[str, str]:
        """Return config dict with sensitive keys masked for safety."""
        masked = {}
        for k in self.list_keys():
            val = self.get(k)
            if not val:
                continue
            if k in SENSITIVE_KEYS or "API_KEY" in k or "PASSWORD" in k or "SECRET" in k:
                if val == "encrypted_in_secret_store":
                    masked[k] = "[ENCRYPTED]"
                elif len(val) <= 4:
                    masked[k] = "****"
                else:
                    masked[k] = val[:2] + "*" * (len(val) - 2)
            else:
                masked[k] = str(val)
        return masked


_config_manager: Optional[ConfigManager] = None


def get_config(env_path: Optional[Path] = None, store_path: Optional[Path] = None) -> ConfigManager:
    """Get the active ConfigManager singleton."""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager(env_path, store_path)
    return _config_manager
