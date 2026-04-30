from __future__ import annotations

import asyncio

import pytest

from channel.backend import AgentRequest, AgentStreamChunk
from channel.pi_backend import PiBackendError, SubprocessPiBackend


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


def test_extract_message_text_and_text_variants():
    backend = SubprocessPiBackend(pi_command=["pi"], timeout_seconds=1)

    assert backend._extract_message_text({"role": "assistant", "content": "hello"}) == "hello"
    assert backend._extract_message_text({"role": "assistant", "content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}) == "ab"
    assert backend._extract_message_text({"role": "user", "content": "hello"}) is None
    assert backend._extract_message_text("bad") is None

    assert backend._extract_text({"type": "agent_end", "messages": [{"role": "assistant", "content": "final"}]}) == ("final", False)
    assert backend._extract_text({"type": "message_end", "message": {"role": "assistant", "content": "done"}}) == ("done", False)
    assert backend._extract_text({"assistantMessageEvent": {"type": "text_delta", "delta": "x"}}) == ("x", True)
    assert backend._extract_text({"assistantMessageEvent": {"type": "text_end", "content": {"role": "assistant", "content": "nested"}}}) == ("nested", False)
    assert backend._extract_text({"assistantMessageEvent": {"type": "text_start", "partial": {"role": "assistant", "content": "partial"}}}) == ("partial", False)
    assert backend._extract_text({"text": "root"}) == ("root", False)
    assert backend._extract_text({"response": "resp"}) == ("resp", False)
    assert backend._extract_text({"content": "content"}) == ("content", False)


def test_extract_progress_text_and_timeout_env(monkeypatch):
    backend = SubprocessPiBackend(pi_command=["pi"], timeout_seconds=1)
    assert backend._extract_progress_text({"type": "agent_start"}) == "[thinking] starting"
    assert backend._extract_progress_text({"type": "turn_end"}) == "[thinking] wrapping up"
    assert backend._extract_progress_text({"type": "extension_ui_request", "method": "setWidget", "message": "Model Tagger ready"}) == "[extension] Model Tagger ready"
    assert backend._extract_progress_text({"type": "extension_ui_request", "method": "runThing"}) == "[extension] runThing"
    assert backend._extract_progress_text({"type": "extension_ui_request", "message": "hello"}) == "[extension] hello"
    assert backend._extract_progress_text({"type": "message_update", "assistantMessageEvent": {"type": "toolcall_start", "name": "grep"}}) == "[tool] grep"
    assert backend._extract_progress_text({"type": "message_update", "assistantMessageEvent": {"type": "toolcall_start"}}) == "[tool] working"

    monkeypatch.setenv("OI_GATEWAY_PI_TIMEOUT_SECONDS", "abc")
    assert SubprocessPiBackend._read_timeout_from_env() == 60.0
    monkeypatch.setenv("OI_GATEWAY_PI_TIMEOUT_SECONDS", "-1")
    assert SubprocessPiBackend._read_timeout_from_env() == 60.0
    monkeypatch.setenv("OI_GATEWAY_PI_TIMEOUT_SECONDS", "12.5")
    assert SubprocessPiBackend._read_timeout_from_env() == 12.5


@pytest.mark.asyncio
async def test_send_prompt_send_request_and_streaming_use_event_generator():
    backend = SubprocessPiBackend(pi_command=["pi"], timeout_seconds=1)

    async def fake_events(_message):
        yield AgentStreamChunk(text_delta="Hello ", is_final=False, metadata={})
        yield AgentStreamChunk(text_delta="world", is_final=False, metadata={})
        yield AgentStreamChunk(text_delta="", is_final=True, metadata={})

    backend._read_events_from_prompt = fake_events
    assert await backend.send_prompt("prompt") == "Hello world"

    async def fake_final(_message):
        yield AgentStreamChunk(text_delta="Done", is_final=True, metadata={})

    backend._read_events_from_prompt = fake_final
    response = await backend.send_request(make_request())
    assert response.response_text == "Done"
    assert response.backend_name == "pi"

    chunks = []
    async for chunk in backend.send_request_streaming(make_request()):
        chunks.append(chunk)
    assert chunks == [AgentStreamChunk(text_delta="Done", is_final=True, metadata={})]


@pytest.mark.asyncio
async def test_send_prompt_raises_when_generator_returns_no_text():
    backend = SubprocessPiBackend(pi_command=["pi"], timeout_seconds=1)

    async def empty_events(_message):
        if False:
            yield None

    backend._read_events_from_prompt = empty_events
    with pytest.raises(PiBackendError, match="without usable response text"):
        await backend.send_prompt("prompt")
