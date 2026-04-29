"""Centralized runtime path helpers for oi-gateway and launcher scripts."""
from __future__ import annotations

import os
from pathlib import Path

_OI_DIR_NAME = "oi"
_GATEWAY_DIR_NAME = "oi-gateway"


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
    return oi_home().joinpath("config", *parts)


def secrets_dir(*parts: str) -> Path:
    return oi_home().joinpath("secrets", *parts)


def state_dir(*parts: str) -> Path:
    return oi_home().joinpath("state", *parts)


def logs_dir(*parts: str) -> Path:
    return oi_home().joinpath("logs", *parts)


def cache_dir(*parts: str) -> Path:
    return oi_home().joinpath("cache", *parts)


def gateway_config_dir() -> Path:
    return config_dir(_GATEWAY_DIR_NAME)


def gateway_secrets_dir() -> Path:
    return secrets_dir(_GATEWAY_DIR_NAME)


def gateway_state_dir() -> Path:
    return state_dir(_GATEWAY_DIR_NAME)


def gateway_logs_dir() -> Path:
    return logs_dir(_GATEWAY_DIR_NAME)


def gateway_cache_dir() -> Path:
    return cache_dir(_GATEWAY_DIR_NAME)


def gateway_db_path() -> Path:
    return gateway_state_dir() / "oi-gateway.db"


def openclaw_device_identity_path() -> Path:
    return gateway_state_dir() / "openclaw-device-identity.json"
