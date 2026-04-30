from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from channel.backend import AgentBackendError, AgentRequest
from channel.factory import create_backend_from_env
from channel.opencode_backend import OpenCodeBackend


def make_request() -> AgentRequest:
    return AgentRequest(
        user_text="hello",
        source_device_id="dev1",
        input_kind="transcript",
        stream_id="s1",
        transcript="hello",
        session_key="oi:device:dev1",
        correlation_id="c1",
    )


class Proc:
    def __init__(self, *, stdout=b"ok\n", stderr=b"", returncode=0):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self.killed = False

    async def communicate(self):
        return self._stdout, self._stderr

    def kill(self):
        self.killed = True

    async def wait(self):
        return None


def test_channel_init_exports_expected_symbols():
    channel = importlib.import_module("channel")
    assert "OpenCodeBackend" in channel.__all__
    assert channel.OpenCodeBackend is OpenCodeBackend


def test_factory_selects_backends_from_env(monkeypatch):
    monkeypatch.setenv("OI_AGENT_BACKEND", "pi")
    monkeypatch.setenv("OI_PI_COMMAND", "pi --mode rpc")
    pi_backend = create_backend_from_env()
    assert pi_backend.mode == "subprocess"
    assert pi_backend._pi_command == ["pi", "--mode", "rpc"]

    monkeypatch.setenv("OI_AGENT_BACKEND", "hermes")
    monkeypatch.setenv("OI_HERMES_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("OI_HERMES_API_KEY", "secret")
    monkeypatch.setenv("OI_HERMES_MODEL", "m")
    hermes = create_backend_from_env()
    assert hermes.name == "hermes"

    monkeypatch.setenv("OI_AGENT_BACKEND", "openclaw")
    monkeypatch.setenv("OI_OPENCLAW_TOKEN", "tok")
    monkeypatch.setenv("OI_OPENCLAW_TIMEOUT_SECONDS", "12")
    openclaw = create_backend_from_env()
    assert openclaw.name == "openclaw"
    assert openclaw._timeout_seconds == 12.0

    monkeypatch.setenv("OI_AGENT_BACKEND", "opencode")
    monkeypatch.setenv("OI_OPENCODE_COMMAND", "opencode run --fast")
    monkeypatch.setenv("OI_OPENCODE_TIMEOUT_SECONDS", "9")
    opencode = create_backend_from_env()
    assert opencode.command == ["opencode", "run", "--fast"]
    assert opencode.timeout_seconds == 9.0

    monkeypatch.setenv("OI_AGENT_BACKEND", "unknown")
    with pytest.raises(ValueError, match="Unsupported"):
        create_backend_from_env()


@pytest.mark.asyncio
async def test_opencode_backend_success_failure_timeout_and_empty_output():
    backend = OpenCodeBackend.from_command_text("opencode run --fast", timeout_seconds=5)
    assert backend.command == ["opencode", "run", "--fast"]

    with patch("channel.opencode_backend.asyncio.create_subprocess_exec", return_value=Proc(stdout=b"hello\n", stderr=b"", returncode=0)):
        response = await backend.send_request(make_request())
        assert response.response_text == "hello"
        assert response.backend_name == "opencode"
        assert response.raw_response["command"] == ["opencode", "run", "--fast"]

    with patch("channel.opencode_backend.asyncio.create_subprocess_exec", return_value=Proc(stdout=b"", stderr=b"boom", returncode=1)):
        with pytest.raises(AgentBackendError, match="boom"):
            await backend.send_request(make_request())

    with patch("channel.opencode_backend.asyncio.create_subprocess_exec", return_value=Proc(stdout=b"", stderr=b"", returncode=0)):
        with pytest.raises(AgentBackendError, match="no assistant text"):
            await backend.send_request(make_request())

    proc = Proc()

    async def fake_wait_for(coro, timeout):
        coro.close()
        raise asyncio.TimeoutError

    with patch("channel.opencode_backend.asyncio.create_subprocess_exec", return_value=proc), patch("channel.opencode_backend.asyncio.wait_for", side_effect=fake_wait_for):
        with pytest.raises(AgentBackendError, match="timed out"):
            await backend.send_request(make_request())
        assert proc.killed is True
