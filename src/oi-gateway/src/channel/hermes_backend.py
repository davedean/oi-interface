"""Hermes agent backend over the local/remote HTTP API server."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from typing import Any, AsyncGenerator

import aiohttp

from .backend import AgentBackendError, AgentRequest, AgentResponse, AgentStreamChunk
from .request_builder import render_text_prompt


class HermesBackend:
    """Send requests to Hermes via its OpenAI-compatible API server."""

    mode = "hermes"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str = "hermes",
        session_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._session_factory = session_factory or aiohttp.ClientSession

    @property
    def name(self) -> str:
        return "hermes"

    async def send_request_streaming(self, request: AgentRequest) -> AsyncGenerator[AgentStreamChunk, None]:
        """Send a request and stream response chunks using OpenAI-compatible streaming."""
        async with self._session_factory() as session:
            async with session.post(
                f"{self._base_url}/v1/chat/completions",
                headers=self._build_headers(request),
                json=self._build_request_body(request),
            ) as response:
                await self._raise_for_http_error(response)
                if hasattr(response, "content"):
                    async for chunk in self._stream_sse_chunks(response.content):
                        yield chunk
                    return

                payload = await response.json()
                text = self._extract_response_text(payload)
                if text:
                    yield AgentStreamChunk(text_delta=text, is_final=True, metadata={})

    async def send_request(self, request: AgentRequest) -> AgentResponse:
        response_text = await self._collect_stream_text(request)
        if not response_text.strip():
            raise AgentBackendError("Hermes backend returned no assistant text")

        hermes_session_id = self._map_session_key(request)
        return AgentResponse(
            response_text=response_text,
            backend_name=self.name,
            session_key=hermes_session_id,
            correlation_id=request.correlation_id,
            raw_response={},
        )

    def _build_headers(self, request: AgentRequest) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        hermes_session_id = self._map_session_key(request)
        if hermes_session_id:
            headers["X-Hermes-Session-Id"] = hermes_session_id
        if request.idempotency_key:
            headers["Idempotency-Key"] = request.idempotency_key
        return headers

    def _build_request_body(self, request: AgentRequest) -> dict[str, Any]:
        return {
            "model": self._model,
            "messages": [{"role": "user", "content": render_text_prompt(request)}],
            "stream": True,
        }

    async def _raise_for_http_error(self, response: Any) -> None:
        if response.status < 400:
            return
        raise AgentBackendError(
            f"Hermes backend returned HTTP {response.status}: {await response.text()}"
        )

    async def _stream_sse_chunks(self, content: AsyncIterator[bytes]) -> AsyncGenerator[AgentStreamChunk, None]:
        saw_text = False
        async for payload in self._iter_sse_payloads(content):
            for chunk in self._chunks_from_sse_payload(payload):
                if chunk.text_delta:
                    saw_text = True
                yield chunk
        if saw_text:
            yield AgentStreamChunk(text_delta="", is_final=True, metadata={})

    async def _iter_sse_payloads(self, content: AsyncIterator[bytes]) -> AsyncIterator[dict[str, Any]]:
        async for line_bytes in content:
            line = line_bytes.decode("utf-8").strip()
            if not line or not line.startswith("data: "):
                continue

            data = line[6:]
            if data == "[DONE]":
                break

            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                yield payload

    def _chunks_from_sse_payload(self, payload: dict[str, Any]) -> list[AgentStreamChunk]:
        chunks: list[AgentStreamChunk] = []
        choices = payload.get("choices", [])
        for choice in choices:
            if not isinstance(choice, dict):
                continue

            finish_reason = choice.get("finish_reason")
            delta = choice.get("delta", {})
            content = delta.get("content", "") if isinstance(delta, dict) else ""
            if content:
                chunks.append(
                    AgentStreamChunk(
                        text_delta=content,
                        is_final=False,
                        metadata={"finish_reason": finish_reason},
                    )
                )
                continue

            if finish_reason:
                chunks.append(
                    AgentStreamChunk(
                        text_delta="",
                        is_final=True,
                        metadata={"finish_reason": finish_reason},
                    )
                )
        return chunks

    async def _collect_stream_text(self, request: AgentRequest) -> str:
        parts: list[str] = []
        async for chunk in self.send_request_streaming(request):
            if chunk.text_delta:
                parts.append(chunk.text_delta)
        return "".join(parts)

    def _map_session_key(self, request: AgentRequest) -> str | None:
        if not request.session_key:
            return None
        suffix = request.session_key.removeprefix("oi:device:")
        return f"oi-device-{suffix}"

    def _extract_response_text(self, payload: dict[str, Any]) -> str | None:
        choices = payload.get("choices")
        if not isinstance(choices, list):
            return None
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if not isinstance(message, dict):
                continue
            text = self._extract_text_content(message.get("content"))
            if text:
                return text
        return None

    def _extract_text_content(self, content: Any) -> str | None:
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str) and item:
                    parts.append(item)
                    continue
                if not isinstance(item, dict):
                    continue
                if item.get("type") not in (None, "text", "output_text"):
                    continue
                text = item.get("text") or item.get("content")
                if isinstance(text, str) and text:
                    parts.append(text)
            if parts:
                return "".join(parts)
        return None
