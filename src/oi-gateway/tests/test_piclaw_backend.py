from __future__ import annotations

from pathlib import Path
import sys

import pytest


gateway_src = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(gateway_src))

from channel.backend import AgentBackendError, AgentRequest, AgentStreamChunk
from channel.piclaw_backend import PiclawBackend


class FakeResponse:
    def __init__(self, *, status: int = 200, lines: list[bytes] | None = None, text: str = "") -> None:
        self.status = status
        self.content = _AsyncBytes(lines or [])
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def text(self) -> str:
        return self._text


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.post_calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def post(self, url: str, *, headers: dict, json: dict, timeout):
        self.post_calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return self.response


class _AsyncBytes:
    def __init__(self, lines: list[bytes]) -> None:
        self._iter = iter(lines)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


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


def make_backend(response: FakeResponse, **kwargs) -> tuple[PiclawBackend, FakeSession]:
    session = FakeSession(response)
    backend = PiclawBackend(
        base_url="http://127.0.0.1:8080",
        timeout_seconds=45.0,
        session_factory=lambda: session,
        **kwargs,
    )
    return backend, session


@pytest.mark.asyncio
async def test_piclaw_backend_send_request_streaming_yields_deltas_and_final():
    response = FakeResponse(
        lines=[
            b"event: side_prompt_start\n",
            b"data: {\"chat_jid\":\"oi-device-test-device\"}\n\n",
            b"event: side_prompt_thinking_delta\n",
            b"data: {\"delta\":\"Thinking...\"}\n\n",
            b"event: side_prompt_text_delta\n",
            b"data: {\"delta\":\"Hello \"}\n\n",
            b"event: side_prompt_text_delta\n",
            b"data: {\"delta\":\"world\"}\n\n",
            b"event: side_prompt_done\n",
            b"data: {\"status\":\"success\",\"result\":{\"text\":\"Hello world\"}}\n\n",
        ]
    )
    backend, session = make_backend(response, internal_secret="secret-token", system_prompt="be concise")

    chunks = [chunk async for chunk in backend.send_request_streaming(make_request())]

    assert chunks == [
        AgentStreamChunk(text_delta="", is_final=False, metadata={"event_type": "side_prompt_thinking_delta", "progress_text": "[thinking] working"}),
        AgentStreamChunk(text_delta="Hello ", is_final=False, metadata={"event_type": "side_prompt_text_delta"}),
        AgentStreamChunk(text_delta="world", is_final=False, metadata={"event_type": "side_prompt_text_delta"}),
        AgentStreamChunk(text_delta="", is_final=True, metadata={"event_type": "side_prompt_done"}),
        AgentStreamChunk(text_delta="", is_final=True, metadata={}),
    ]

    assert len(session.post_calls) == 1
    call = session.post_calls[0]
    assert call["url"] == "http://127.0.0.1:8080/agent/side-prompt/stream"
    assert call["headers"]["Authorization"] == "Bearer secret-token"
    assert call["headers"]["x-piclaw-internal-secret"] == "secret-token"
    assert call["json"]["chat_jid"] == "oi-device-test-device"
    assert call["json"]["system_prompt"] == "be concise"
    assert "mute for 30 minutes." in call["json"]["prompt"]


@pytest.mark.asyncio
async def test_piclaw_backend_send_request_uses_final_replacement_text_when_done_differs():
    response = FakeResponse(
        lines=[
            b"event: side_prompt_text_delta\n",
            b"data: {\"delta\":\"Hello \"}\n\n",
            b"event: side_prompt_done\n",
            b"data: {\"status\":\"success\",\"result\":{\"text\":\"Hi world\"}}\n\n",
        ]
    )
    backend, _session = make_backend(response)

    result = await backend.send_request(make_request())

    assert result.response_text == "Hi world"


@pytest.mark.asyncio
async def test_piclaw_backend_send_request_collects_streamed_text():
    response = FakeResponse(
        lines=[
            b"event: side_prompt_text_delta\n",
            b"data: {\"delta\":\"Muted for \"}\n\n",
            b"event: side_prompt_text_delta\n",
            b"data: {\"delta\":\"30 minutes.\"}\n\n",
            b"event: side_prompt_done\n",
            b"data: {\"status\":\"success\",\"result\":{\"text\":\"Muted for 30 minutes.\"}}\n\n",
        ]
    )
    backend, _session = make_backend(response, session_cookie="abc123")

    result = await backend.send_request(make_request())

    assert result.response_text == "Muted for 30 minutes."
    assert result.backend_name == "piclaw"
    assert result.session_key == "oi-device-test-device"
    assert result.correlation_id == "rec_001"


@pytest.mark.asyncio
async def test_piclaw_backend_raises_on_http_error():
    response = FakeResponse(status=403, text="forbidden")
    backend, _session = make_backend(response)

    with pytest.raises(AgentBackendError, match="HTTP 403: forbidden"):
        await backend.send_request(make_request())


@pytest.mark.asyncio
async def test_piclaw_backend_raises_on_side_prompt_error_event():
    response = FakeResponse(
        lines=[
            b"event: side_prompt_error\n",
            b"data: {\"error\":\"auth failed\"}\n\n",
        ]
    )
    backend, _session = make_backend(response)

    with pytest.raises(AgentBackendError, match="auth failed"):
        await backend.send_request(make_request())


@pytest.mark.asyncio
async def test_piclaw_backend_raises_when_no_assistant_text_found():
    response = FakeResponse(
        lines=[
            b"event: side_prompt_start\n",
            b"data: {\"chat_jid\":\"oi-device-test-device\"}\n\n",
            b"event: side_prompt_done\n",
            b"data: {\"status\":\"success\",\"result\":{\"text\":\"\"}}\n\n",
        ]
    )
    backend, _session = make_backend(response)

    with pytest.raises(AgentBackendError, match="no assistant text"):
        await backend.send_request(make_request())


def test_piclaw_backend_helpers_cover_cookie_session_and_sse_parsing():
    backend, _session = make_backend(FakeResponse(), chat_jid_prefix="device-")

    assert backend._map_session_key("oi:device:frontdoor", "ignored") == "device-frontdoor"
    assert backend._map_session_key("custom-chat", "ignored") == "custom-chat"
    assert backend._map_session_key(None, "dev") == "device-dev"

    assert backend._build_cookie_header("abc123") == "piclaw_session=abc123"
    assert backend._build_cookie_header("abc123==") == "piclaw_session=abc123=="
    assert backend._build_cookie_header("piclaw_session=abc123") == "piclaw_session=abc123"

    assert backend._extract_text_delta({"delta": "x"}) == "x"
    assert backend._extract_text_delta("y") == "y"
    assert backend._extract_done_text({"result": {"text": "done"}}) == "done"
    assert backend._extract_done_text({"response_text": "done"}) == "done"
    assert backend._extract_error_message({"message": "boom"}) == "PiClaw backend error: boom"

    event = backend._decode_sse_event("side_prompt_done", ['{"result":{"text":"ok"}}'])
    assert event == {"event": "side_prompt_done", "data": {"result": {"text": "ok"}}}


@pytest.mark.asyncio
async def test_piclaw_backend_sse_parser_handles_comments_multiline_and_trailing_event():
    response = FakeResponse(
        lines=[
            b": heartbeat\n",
            b"event: side_prompt_text_delta\n",
            b"data: hello\n",
            b"data: world\n\n",
            b"event: side_prompt_done\n",
            b"data: {\"result\":\"hello\\nworld\"}\n",
        ]
    )
    backend, _session = make_backend(response)

    chunks = [chunk async for chunk in backend.send_request_streaming(make_request())]

    assert chunks == [
        AgentStreamChunk(text_delta="hello\nworld", is_final=False, metadata={"event_type": "side_prompt_text_delta"}),
        AgentStreamChunk(text_delta="", is_final=True, metadata={"event_type": "side_prompt_done"}),
        AgentStreamChunk(text_delta="", is_final=True, metadata={}),
    ]
