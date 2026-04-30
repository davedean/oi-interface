"""Tests for gateway TOML config loading."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


gateway_src = Path(__file__).parent.parent / "src"
if str(gateway_src) not in sys.path:
    sys.path.insert(0, str(gateway_src))

import config_loader


@pytest.fixture
def clean_env(monkeypatch):
    for key in [
        "TOP_LEVEL",
        "FROM_ENV_TABLE",
        "SHARED",
        "SECRET_ONLY",
        "BACKEND_ONLY",
        "OI_AGENT_BACKEND",
        "EXISTING",
    ]:
        monkeypatch.delenv(key, raising=False)


def test_merge_toml_into_env_ignores_missing_file(tmp_path: Path, clean_env) -> None:
    config_loader._merge_toml_into_env(tmp_path / "missing.toml")
    assert "TOP_LEVEL" not in os.environ


def test_merge_toml_into_env_loads_scalars_and_env_table(tmp_path: Path, clean_env) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
TOP_LEVEL = "root"
COUNT = 3
ENABLED = true
IGNORED_LIST = [1, 2]
IGNORED_TABLE = { nested = "value" }

[env]
FROM_ENV_TABLE = "yes"
SHARED = "from-env"
IGNORED_SUBTABLE = { nope = "x" }
""".strip()
    )

    config_loader._merge_toml_into_env(config_path)

    assert os.environ["TOP_LEVEL"] == "root"
    assert os.environ["COUNT"] == "3"
    assert os.environ["ENABLED"] == "True"
    assert os.environ["FROM_ENV_TABLE"] == "yes"
    assert os.environ["SHARED"] == "from-env"
    assert "IGNORED_LIST" not in os.environ
    assert "IGNORED_TABLE" not in os.environ
    assert "IGNORED_SUBTABLE" not in os.environ


def test_merge_toml_into_env_does_not_override_existing_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EXISTING", "shell-wins")
    config_path = tmp_path / "config.toml"
    config_path.write_text('EXISTING = "config-loses"')

    config_loader._merge_toml_into_env(config_path)

    assert os.environ["EXISTING"] == "shell-wins"


def test_load_gateway_toml_config_loads_base_secret_and_backend_files(
    tmp_path: Path,
    monkeypatch,
    clean_env,
) -> None:
    config_dir = tmp_path / "config"
    secrets_dir = tmp_path / "secrets"
    config_dir.mkdir()
    secrets_dir.mkdir()

    (config_dir / "config.toml").write_text(
        'TOP_LEVEL = "config"\nSHARED = "config"\nOI_AGENT_BACKEND = "hermes"\n'
    )
    (secrets_dir / "secrets.toml").write_text(
        'SECRET_ONLY = "secret"\nSHARED = "secret-should-not-win"\n'
    )
    (config_dir / "hermes.toml").write_text('BACKEND_ONLY = "from-backend"\n')
    (secrets_dir / "hermes.toml").write_text('EXISTING = "backend-secret"\n')

    monkeypatch.setattr(config_loader, "gateway_config_dir", lambda: config_dir)
    monkeypatch.setattr(config_loader, "gateway_secrets_dir", lambda: secrets_dir)
    monkeypatch.setenv("EXISTING", "already-set")

    config_loader.load_gateway_toml_config()

    assert os.environ["TOP_LEVEL"] == "config"
    assert os.environ["SECRET_ONLY"] == "secret"
    assert os.environ["BACKEND_ONLY"] == "from-backend"
    assert os.environ["OI_AGENT_BACKEND"] == "hermes"
    assert os.environ["SHARED"] == "config"
    assert os.environ["EXISTING"] == "already-set"


def test_load_gateway_toml_config_uses_existing_backend_env_over_file(
    tmp_path: Path,
    monkeypatch,
    clean_env,
) -> None:
    config_dir = tmp_path / "config"
    secrets_dir = tmp_path / "secrets"
    config_dir.mkdir()
    secrets_dir.mkdir()

    (config_dir / "config.toml").write_text('OI_AGENT_BACKEND = "pi"\n')
    (config_dir / "openclaw.toml").write_text('BACKEND_ONLY = "openclaw"\n')
    (config_dir / "pi.toml").write_text('BACKEND_ONLY = "pi"\n')

    monkeypatch.setattr(config_loader, "gateway_config_dir", lambda: config_dir)
    monkeypatch.setattr(config_loader, "gateway_secrets_dir", lambda: secrets_dir)
    monkeypatch.setenv("OI_AGENT_BACKEND", "openclaw")

    config_loader.load_gateway_toml_config()

    assert os.environ["OI_AGENT_BACKEND"] == "openclaw"
    assert os.environ["BACKEND_ONLY"] == "openclaw"
