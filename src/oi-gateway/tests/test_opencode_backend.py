from __future__ import annotations

import asyncio
from pathlib import Path
import sys

import pytest


gateway_src = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(gateway_src))

from channel.backend import AgentBackendError, AgentRequest
from channel.opencode_backend import OpenCodeBackend


def make_request() -> AgentRequest:
    return AgentRequest(
        user_text="mute for 30 minutes.",
        source_device_id="test-device",
        input_kind="transcript",
        stream_id="rec_001",
        transcript="mute for 30 minutes.",
        session_key="oi:device:test-device",
        correlation_id="rec_001",
        idempotency_key="idem-001",
        device_context={
            "source_device": "test-device",
            "foreground": "test-device",
            "online": ["test-device"],
            "capabilities": {"test-device": {"max_spoken_seconds": 12, "supports_confirm_buttons": True}},
        },
        reply_constraints={"max_spoken_seconds": 12, "supports_confirm_buttons": True},
    )


class FakeProc:
    def __init__(self, *, returncode: int, stdout: bytes = b"", stderr: bytes = b"") -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.killed = False

    async def communicate(self):
        return self._stdout, self._stderr

    def kill(self):
        self.killed = True

    async def wait(self):
        return self.returncode


@pytest.mark.asyncio
async def test_opencode_backend_success(monkeypatch):
    calls: list[list[str]] = []
    fake_proc = FakeProc(
        returncode=0,
        stdout=(
            b'{"type":"step_start","timestamp":1,"sessionID":"s","part":{"type":"step-start"}}\n'
            b'{"type":"text","timestamp":2,"sessionID":"s","part":{"type":"text","text":"Muted for 30 minutes.","time":{"end":1}}}\n'
            b'{"type":"step_finish","timestamp":3,"sessionID":"s","part":{"type":"step-finish"}}\n'
        ),
    )

    async def fake_create(*args, **kwargs):
        calls.append(list(args))
        return fake_proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)

    backend = OpenCodeBackend(timeout_seconds=45.0)
    response = await backend.send_request(make_request())

    assert response.response_text == "Muted for 30 minutes."
    assert response.backend_name == "opencode"
    assert response.session_key == "oi:device:test-device"
    assert response.correlation_id == "rec_001"
    assert calls and calls[0][0:4] == ["opencode", "run", "--format", "json"]
    assert "The user said: 'mute for 30 minutes.'" in calls[0][-1]


@pytest.mark.asyncio
async def test_opencode_backend_raises_on_nonzero_exit(monkeypatch):
    fake_proc = FakeProc(returncode=2, stderr=b"unknown option")

    async def fake_create(*_args, **_kwargs):
        return fake_proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)
    backend = OpenCodeBackend(command=["opencode", "run"])

    with pytest.raises(AgentBackendError, match="unknown option"):
        await backend.send_request(make_request())


@pytest.mark.asyncio
async def test_opencode_backend_raises_on_empty_output(monkeypatch):
    fake_proc = FakeProc(returncode=0, stdout=b"\n")

    async def fake_create(*_args, **_kwargs):
        return fake_proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)
    backend = OpenCodeBackend(command=["opencode", "run"])

    with pytest.raises(AgentBackendError, match="no assistant text"):
        await backend.send_request(make_request())


@pytest.mark.asyncio
async def test_opencode_backend_falls_back_to_plain_text_when_not_json(monkeypatch):
    fake_proc = FakeProc(returncode=0, stdout=b"Muted for 30 minutes.\n")

    async def fake_create(*_args, **_kwargs):
        return fake_proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)
    backend = OpenCodeBackend(command=["opencode", "run", "--format", "default"])
    response = await backend.send_request(make_request())

    assert response.response_text == "Muted for 30 minutes."
