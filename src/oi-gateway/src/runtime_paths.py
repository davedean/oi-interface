"""Centralized runtime path helpers for oi-gateway and launcher scripts."""
from __future__ import annotations

import os
from pathlib import Path

_OI_DIR_NAME = "oi"
_GATEWAY_DIR_NAME = "oi-gateway"


def _oi_subdir(directory: str, *parts: str) -> Path:
    """Build a path under the base Oi runtime directory."""
    return oi_home().joinpath(directory, *parts)


def _gateway_subdir(directory: str) -> Path:
    """Build a gateway-owned path under an Oi runtime subdirectory."""
    return _oi_subdir(directory, _GATEWAY_DIR_NAME)


def oi_home() -> Path:
    """Return the base runtime directory for Oi."""
    oi_home_env = os.getenv("OI_HOME", "").strip()
    if oi_home_env:
        return Path(oi_home_env).expanduser()

    xdg_config_home = os.getenv("XDG_CONFIG_HOME", "").strip()
    if xdg_config_home:
        return Path(xdg_config_home).expanduser() / _OI_DIR_NAME

    return Path.home() / ".oi"


def config_dir(*parts: str) -> Path:
    return _oi_subdir("config", *parts)


def secrets_dir(*parts: str) -> Path:
    return _oi_subdir("secrets", *parts)


def state_dir(*parts: str) -> Path:
    return _oi_subdir("state", *parts)


def logs_dir(*parts: str) -> Path:
    return _oi_subdir("logs", *parts)


def cache_dir(*parts: str) -> Path:
    return _oi_subdir("cache", *parts)


def gateway_config_dir() -> Path:
    return _gateway_subdir("config")


def gateway_secrets_dir() -> Path:
    return _gateway_subdir("secrets")


def gateway_state_dir() -> Path:
    return _gateway_subdir("state")


def gateway_logs_dir() -> Path:
    return _gateway_subdir("logs")


def gateway_cache_dir() -> Path:
    return _gateway_subdir("cache")


def gateway_db_path() -> Path:
    return gateway_state_dir() / "oi-gateway.db"


def openclaw_device_identity_path() -> Path:
    return gateway_state_dir() / "openclaw-device-identity.json"
