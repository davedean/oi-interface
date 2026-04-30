from __future__ import annotations

from pathlib import Path
import sys

import pytest


gateway_src = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(gateway_src))

from channel.backend import AgentRequest, AgentBackendError
from channel.hermes_backend import HermesBackend


class FakeResponse:
    def __init__(self, *, status: int = 200, payload: dict | None = None, text: str = "") -> None:
        self.status = status
        self._payload = payload or {}
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def json(self) -> dict:
        return self._payload

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

    def post(self, url: str, *, headers: dict, json: dict):
        self.post_calls.append({"url": url, "headers": headers, "json": json})
        return self.response


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


@pytest.mark.asyncio
async def test_hermes_backend_builds_expected_request():
    response = FakeResponse(
        payload={
            "choices": [
                {"message": {"content": "Muted for 30 minutes."}}
            ]
        }
    )
    session = FakeSession(response)
    backend = HermesBackend(
        base_url="http://127.0.0.1:8000",
        api_key="secret-key",
        session_factory=lambda: session,
    )

    result = await backend.send_request(make_request())

    assert result.response_text == "Muted for 30 minutes."
    assert result.backend_name == "hermes"
    assert result.session_key == "oi-device-test-device"
    assert result.correlation_id == "rec_001"

    assert len(session.post_calls) == 1
    call = session.post_calls[0]
    assert call["url"] == "http://127.0.0.1:8000/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer secret-key"
    assert call["headers"]["X-Hermes-Session-Id"] == "oi-device-test-device"
    assert call["headers"]["Idempotency-Key"] == "idem-001"
    assert call["json"]["model"] == "hermes"
    assert call["json"]["messages"][0]["role"] == "user"
    prompt = call["json"]["messages"][0]["content"]
    assert "mute for 30 minutes." in prompt
    assert "test-device" in prompt
    assert "max_spoken_seconds=12" in prompt


@pytest.mark.asyncio
async def test_hermes_backend_raises_on_http_error():
    response = FakeResponse(status=500, text="boom")
    session = FakeSession(response)
    backend = HermesBackend(
        base_url="http://127.0.0.1:8000",
        api_key="secret-key",
        session_factory=lambda: session,
    )

    with pytest.raises(AgentBackendError, match="500"):
        await backend.send_request(make_request())


@pytest.mark.asyncio
async def test_hermes_backend_raises_when_no_assistant_text_found():
    response = FakeResponse(payload={"choices": [{"message": {"content": []}}]})
    session = FakeSession(response)
    backend = HermesBackend(
        base_url="http://127.0.0.1:8000",
        api_key="secret-key",
        session_factory=lambda: session,
    )

    with pytest.raises(AgentBackendError, match="assistant text"):
        await backend.send_request(make_request())


class FakeStreamResponse(FakeResponse):
    def __init__(self, lines: list[bytes], **kwargs) -> None:
        super().__init__(**kwargs)
        self.content = _AsyncBytes(lines)


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


@pytest.mark.asyncio
async def test_hermes_backend_streaming_sse_yields_deltas_and_final():
    response = FakeStreamResponse(
        [
            b"data: {\"choices\":[{\"delta\":{\"content\":\"Hello \"},\"finish_reason\":null}]}\n",
            b"data: {\"choices\":[{\"delta\":{\"content\":\"world\"},\"finish_reason\":null}]}\n",
            b"data: {\"choices\":[{\"delta\":{},\"finish_reason\":\"stop\"}]}\n",
            b"data: [DONE]\n",
        ]
    )
    session = FakeSession(response)
    backend = HermesBackend(base_url="http://127.0.0.1:8000", api_key="secret-key", session_factory=lambda: session)

    chunks = [chunk async for chunk in backend.send_request_streaming(make_request())]

    assert [chunk.text_delta for chunk in chunks] == ["Hello ", "world", "", ""]
    assert [chunk.is_final for chunk in chunks] == [False, False, True, True]
    assert chunks[2].metadata == {"finish_reason": "stop"}


def test_hermes_backend_text_helpers_cover_list_and_invalid_content():
    backend = HermesBackend(base_url="http://127.0.0.1:8000", api_key="secret-key")

    assert backend._map_session_key(make_request()) == "oi-device-test-device"
    req = AgentRequest(
        user_text="hello",
        source_device_id="test-device",
        input_kind="transcript",
        stream_id="rec_001",
        transcript="hello",
        session_key=None,
    )
    assert backend._map_session_key(req) is None

    assert backend._extract_text_content("hello") == "hello"
    assert backend._extract_text_content([
        "a",
        {"type": "text", "text": "b"},
        {"type": "output_text", "content": "c"},
        {"type": "image", "text": "ignore"},
    ]) == "abc"
    assert backend._extract_text_content([{"type": "image"}]) is None
    assert backend._extract_response_text({"choices": [{"message": {"content": [{"type": "text", "text": "ok"}]}}]}) == "ok"
    assert backend._extract_response_text({"choices": ["bad"]}) is None
