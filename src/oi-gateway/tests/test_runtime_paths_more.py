from __future__ import annotations

from runtime_paths import (
    cache_dir,
    config_dir,
    gateway_cache_dir,
    gateway_config_dir,
    gateway_logs_dir,
    gateway_secrets_dir,
    gateway_state_dir,
    logs_dir,
    openclaw_device_identity_path,
    secrets_dir,
    state_dir,
)


def test_runtime_path_helpers_build_expected_subpaths(tmp_path, monkeypatch):
    monkeypatch.setenv("OI_HOME", str(tmp_path / "oi-home"))

    assert config_dir("a", "b") == tmp_path / "oi-home" / "config" / "a" / "b"
    assert secrets_dir("x") == tmp_path / "oi-home" / "secrets" / "x"
    assert state_dir("y") == tmp_path / "oi-home" / "state" / "y"
    assert logs_dir("z") == tmp_path / "oi-home" / "logs" / "z"
    assert cache_dir("c") == tmp_path / "oi-home" / "cache" / "c"

    assert gateway_config_dir() == tmp_path / "oi-home" / "config" / "oi-gateway"
    assert gateway_secrets_dir() == tmp_path / "oi-home" / "secrets" / "oi-gateway"
    assert gateway_state_dir() == tmp_path / "oi-home" / "state" / "oi-gateway"
    assert gateway_logs_dir() == tmp_path / "oi-home" / "logs" / "oi-gateway"
    assert gateway_cache_dir() == tmp_path / "oi-home" / "cache" / "oi-gateway"
    assert openclaw_device_identity_path() == (
        tmp_path / "oi-home" / "state" / "oi-gateway" / "openclaw-device-identity.json"
    )
