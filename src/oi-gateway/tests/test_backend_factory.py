from pathlib import Path
import sys

import pytest


gateway_src = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(gateway_src))

from channel.factory import create_backend_catalog_from_env, create_backend_from_env
from channel.codex_backend import CodexBackend
from channel.hermes_backend import HermesBackend
from channel.openclaw_backend import OpenClawBackend
from channel.opencode_backend import OpenCodeBackend
from channel.pi_backend import SubprocessPiBackend
from channel.piclaw_backend import PiclawBackend


def test_factory_defaults_to_pi_backend(monkeypatch):
    monkeypatch.delenv("OI_AGENT_BACKEND", raising=False)

    backend = create_backend_from_env()

    assert isinstance(backend, SubprocessPiBackend)


def test_factory_builds_hermes_backend(monkeypatch):
    monkeypatch.setenv("OI_AGENT_BACKEND", "hermes")
    monkeypatch.setenv("OI_HERMES_BASE_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("OI_HERMES_API_KEY", "secret-key")

    backend = create_backend_from_env()

    assert isinstance(backend, HermesBackend)


def test_factory_raises_for_hermes_without_required_config(monkeypatch):
    monkeypatch.setenv("OI_AGENT_BACKEND", "hermes")
    monkeypatch.delenv("OI_HERMES_BASE_URL", raising=False)
    monkeypatch.delenv("OI_HERMES_API_KEY", raising=False)

    with pytest.raises(ValueError, match="OI_HERMES_BASE_URL"):
        create_backend_from_env()


def test_factory_builds_openclaw_backend(monkeypatch):
    monkeypatch.setenv("OI_AGENT_BACKEND", "openclaw")
    monkeypatch.setenv("OI_OPENCLAW_URL", "ws://127.0.0.1:18789")
    monkeypatch.setenv("OI_OPENCLAW_TOKEN", "secret-token")

    backend = create_backend_from_env()

    assert isinstance(backend, OpenClawBackend)


def test_factory_raises_for_openclaw_without_required_token(monkeypatch):
    monkeypatch.setenv("OI_AGENT_BACKEND", "openclaw")
    monkeypatch.delenv("OI_OPENCLAW_TOKEN", raising=False)

    with pytest.raises(ValueError, match="OI_OPENCLAW_TOKEN"):
        create_backend_from_env()


def test_factory_builds_piclaw_backend(monkeypatch):
    monkeypatch.setenv("OI_AGENT_BACKEND", "piclaw")
    monkeypatch.setenv("OI_PICLAW_BASE_URL", "http://127.0.0.1:8080")
    monkeypatch.setenv("OI_PICLAW_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("OI_PICLAW_SESSION_COOKIE", "piclaw_session=abc123")
    monkeypatch.setenv("OI_PICLAW_INTERNAL_SECRET", "secret-token")
    monkeypatch.setenv("OI_PICLAW_CHAT_JID_PREFIX", "device-")
    monkeypatch.setenv("OI_PICLAW_SYSTEM_PROMPT", "be concise")

    backend = create_backend_from_env()

    assert isinstance(backend, PiclawBackend)
    assert backend._base_url == "http://127.0.0.1:8080"
    assert backend._timeout_seconds == 45.0
    assert backend._session_cookie == "piclaw_session=abc123"
    assert backend._internal_secret == "secret-token"
    assert backend._chat_jid_prefix == "device-"
    assert backend._system_prompt == "be concise"


def test_factory_raises_for_piclaw_without_required_base_url(monkeypatch):
    monkeypatch.setenv("OI_AGENT_BACKEND", "piclaw")
    monkeypatch.delenv("OI_PICLAW_BASE_URL", raising=False)

    with pytest.raises(ValueError, match="OI_PICLAW_BASE_URL"):
        create_backend_from_env()


def test_factory_builds_opencode_backend(monkeypatch):
    monkeypatch.setenv("OI_AGENT_BACKEND", "opencode")
    monkeypatch.setenv("OI_OPENCODE_COMMAND", "opencode run -m opencode/big-pickle --agent build")
    monkeypatch.setenv("OI_OPENCODE_TIMEOUT_SECONDS", "90")

    backend = create_backend_from_env()

    assert isinstance(backend, OpenCodeBackend)
    assert backend.command == ["opencode", "run", "-m", "opencode/big-pickle", "--agent", "build"]
    assert backend.timeout_seconds == 90.0


def test_factory_builds_codex_backend(monkeypatch):
    monkeypatch.setenv("OI_AGENT_BACKEND", "codex")
    monkeypatch.setenv("OI_CODEX_COMMAND", "codex exec --json -m gpt-5")
    monkeypatch.setenv("OI_CODEX_TIMEOUT_SECONDS", "150")

    backend = create_backend_from_env()

    assert isinstance(backend, CodexBackend)
    assert backend.command == ["codex", "exec", "--json", "-m", "gpt-5"]
    assert backend.timeout_seconds == 150.0


def test_factory_builds_catalog_from_json(monkeypatch):
    monkeypatch.setenv(
        "OI_AGENT_BACKENDS_JSON",
        '[{"id":"pi-fast","backend":"pi","label":"Pi Fast","command":"pi --mode rpc --no-session"},{"id":"codex-main","backend":"codex","command":"codex exec --json -m gpt-5"}]',
    )
    monkeypatch.setenv("OI_DEFAULT_AGENT_BACKEND_ID", "codex-main")

    catalog = create_backend_catalog_from_env()

    assert catalog.default_backend_id == "codex-main"
    assert [item["id"] for item in catalog.available_backends()] == ["pi-fast", "codex-main"]
    assert isinstance(catalog.get("pi-fast"), SubprocessPiBackend)
    assert isinstance(catalog.get("codex-main"), CodexBackend)


def test_factory_raises_for_unknown_backend(monkeypatch):
    monkeypatch.setenv("OI_AGENT_BACKEND", "unknown")

    with pytest.raises(ValueError, match="Unsupported"):
        create_backend_from_env()
