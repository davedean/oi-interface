"""PiClaw agent backend over the web side-prompt SSE API."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from typing import Any, AsyncGenerator

import aiohttp

from .backend import AgentBackendError, AgentRequest, AgentResponse, AgentStreamChunk
from .request_builder import render_text_prompt


class PiclawBackend:
    """Send requests to a running PiClaw instance via HTTP/SSE."""

    mode = "piclaw"

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float = 120.0,
        session_cookie: str | None = None,
        internal_secret: str | None = None,
        chat_jid_prefix: str = "oi-device-",
        system_prompt: str | None = None,
        session_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._session_cookie = (session_cookie or "").strip() or None
        self._internal_secret = (internal_secret or "").strip() or None
        self._chat_jid_prefix = chat_jid_prefix
        self._system_prompt = system_prompt
        self._session_factory = session_factory or aiohttp.ClientSession

    @property
    def name(self) -> str:
        return "piclaw"

    async def send_request_streaming(self, request: AgentRequest) -> AsyncGenerator[AgentStreamChunk, None]:
        timeout = aiohttp.ClientTimeout(total=self._timeout_seconds)
        last_text = ""
        async with self._session_factory() as session:
            async with session.post(
                f"{self._base_url}/agent/side-prompt/stream",
                headers=self._build_headers(),
                json=self._build_request_body(request),
                timeout=timeout,
            ) as response:
                await self._raise_for_http_error(response)
                saw_text = False
                async for event in self._iter_sse_events(response.content):
                    chunk = self._chunk_from_sse_event(event, last_text)
                    if chunk is None:
                        continue
                    if chunk.text_delta:
                        saw_text = True
                        last_text += chunk.text_delta if not chunk.is_final else chunk.text_delta
                    yield chunk
                if saw_text:
                    yield AgentStreamChunk(text_delta="", is_final=True, metadata={})

    async def send_request(self, request: AgentRequest) -> AgentResponse:
        response_text = ""
        async for chunk in self.send_request_streaming(request):
            if chunk.text_delta:
                response_text = chunk.text_delta if chunk.is_final else response_text + chunk.text_delta
        if not response_text.strip():
            raise AgentBackendError("PiClaw backend returned no assistant text")
        return AgentResponse(
            response_text=response_text,
            backend_name=self.name,
            session_key=self.map_session_key(request),
            correlation_id=request.correlation_id,
            raw_response={},
        )

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._session_cookie:
            headers["Cookie"] = self._build_cookie_header(self._session_cookie)
        if self._internal_secret:
            headers["Authorization"] = f"Bearer {self._internal_secret}"
            headers["x-piclaw-internal-secret"] = self._internal_secret
        return headers

    def _build_request_body(self, request: AgentRequest) -> dict[str, Any]:
        body: dict[str, Any] = {
            "prompt": render_text_prompt(request),
            "chat_jid": self.map_session_key(request),
        }
        if self._system_prompt:
            body["system_prompt"] = self._system_prompt
        return body

    async def _raise_for_http_error(self, response: Any) -> None:
        if response.status < 400:
            return
        raise AgentBackendError(
            f"PiClaw backend returned HTTP {response.status}: {await response.text()}"
        )

    async def _iter_sse_events(self, content: AsyncIterator[bytes]) -> AsyncIterator[dict[str, Any]]:
        event_type: str | None = None
        data_lines: list[str] = []
        buffer = ""
        async for line_bytes in content:
            buffer += line_bytes.decode("utf-8", errors="replace")
            while True:
                newline_index = buffer.find("\n")
                if newline_index < 0:
                    break
                raw_line = buffer[:newline_index]
                buffer = buffer[newline_index + 1 :]
                line = raw_line.rstrip("\r")
                if not line:
                    event = self._decode_sse_event(event_type, data_lines)
                    event_type = None
                    data_lines = []
                    if event is not None:
                        yield event
                    continue
                if line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    event_type = line[6:].strip() or None
                    continue
                if line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
        if buffer:
            line = buffer.rstrip("\r")
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
            elif line.startswith("event:"):
                event_type = line[6:].strip() or None
        trailing = self._decode_sse_event(event_type, data_lines)
        if trailing is not None:
            yield trailing

    def _decode_sse_event(self, event_type: str | None, data_lines: list[str]) -> dict[str, Any] | None:
        if not event_type and not data_lines:
            return None
        payload: dict[str, Any] = {"event": event_type}
        raw_data = "\n".join(data_lines)
        if raw_data:
            try:
                decoded = json.loads(raw_data)
            except json.JSONDecodeError:
                decoded = raw_data
            payload["data"] = decoded
        return payload

    def _chunk_from_sse_event(self, event: dict[str, Any], streamed_text: str) -> AgentStreamChunk | None:
        event_type = event.get("event")
        data = event.get("data")
        if event_type == "side_prompt_text_delta":
            delta = self._extract_text_delta(data)
            if delta:
                return AgentStreamChunk(text_delta=delta, is_final=False, metadata={"event_type": event_type})
            return None
        if event_type == "side_prompt_thinking_delta":
            return AgentStreamChunk(
                text_delta="",
                is_final=False,
                metadata={"event_type": event_type, "progress_text": "[thinking] working"},
            )
        if event_type == "side_prompt_done":
            final_text = self._extract_done_text(data)
            if final_text.startswith(streamed_text):
                final_text = final_text[len(streamed_text) :]
            return AgentStreamChunk(text_delta=final_text, is_final=True, metadata={"event_type": event_type})
        if event_type == "side_prompt_error":
            raise AgentBackendError(self._extract_error_message(data))
        return None

    def _extract_text_delta(self, payload: Any) -> str:
        if isinstance(payload, dict):
            delta = payload.get("delta")
            if isinstance(delta, str):
                return delta
        if isinstance(payload, str):
            return payload
        return ""

    def _extract_done_text(self, payload: Any) -> str:
        if not isinstance(payload, dict):
            return ""
        result = payload.get("result")
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            for key in ("text", "response_text", "content"):
                value = result.get(key)
                if isinstance(value, str) and value.strip():
                    return value
        for key in ("text", "response_text", "content"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return ""

    def _extract_error_message(self, payload: Any) -> str:
        if isinstance(payload, dict):
            for key in ("error", "message", "detail"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return f"PiClaw backend error: {value.strip()}"
        return "PiClaw backend returned an error"

    def map_session_key(self, request: AgentRequest) -> str:
        return self._map_session_key(request.session_key, request.source_device_id)

    def _map_session_key(self, session_key: str | None, source_device_id: str) -> str:
        if session_key and session_key.startswith("oi:device:"):
            return f"{self._chat_jid_prefix}{session_key.removeprefix('oi:device:')}"
        if session_key:
            return session_key
        return f"{self._chat_jid_prefix}{source_device_id}"

    @staticmethod
    def _build_cookie_header(session_cookie: str) -> str:
        if session_cookie.startswith("piclaw_session=") or ";" in session_cookie:
            return session_cookie
        return f"piclaw_session={session_cookie}"
