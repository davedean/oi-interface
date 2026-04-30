"""TOML configuration loader for oi-gateway runtime."""
from __future__ import annotations

import os
from pathlib import Path
import tomllib

from runtime_paths import gateway_config_dir, gateway_secrets_dir


_ALLOWED_SCALARS = (str, int, float, bool)


def _merge_toml_into_env(path: Path) -> None:
    if not path.exists():
        return

    data = tomllib.loads(path.read_text())
    merged: dict[str, str] = {}

    for key, value in data.items():
        if isinstance(value, _ALLOWED_SCALARS):
            merged[key] = str(value)

    env_table = data.get("env")
    if isinstance(env_table, dict):
        for key, value in env_table.items():
            if isinstance(value, _ALLOWED_SCALARS):
                merged[key] = str(value)

    for key, value in merged.items():
        os.environ.setdefault(key, value)


def load_gateway_toml_config() -> None:
    """Load canonical gateway TOML config into process environment.

    Precedence: existing process env wins.
    Files are loaded in this order (later files can fill unset keys only):
    1. ~/.oi/config/oi-gateway/config.toml
    2. ~/.oi/secrets/oi-gateway/secrets.toml
    3. ~/.oi/config/oi-gateway/<backend>.toml
    4. ~/.oi/secrets/oi-gateway/<backend>.toml
    """
    config_file = gateway_config_dir() / "config.toml"
    secrets_file = gateway_secrets_dir() / "secrets.toml"

    _merge_toml_into_env(config_file)
    _merge_toml_into_env(secrets_file)

    backend = os.getenv("OI_AGENT_BACKEND", "pi").strip().lower()
    _merge_toml_into_env(gateway_config_dir() / f"{backend}.toml")
    _merge_toml_into_env(gateway_secrets_dir() / f"{backend}.toml")
