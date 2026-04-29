"""Hermes agent backend over the local/remote HTTP API server."""
from __future__ import annotations

from collections.abc import Callable
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
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        hermes_session_id = self._map_session_key(request)
        if hermes_session_id:
            headers["X-Hermes-Session-Id"] = hermes_session_id

        body = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": render_text_prompt(request),
                }
            ],
            "stream": True,
        }

        async with self._session_factory() as session:
            async with session.post(
                f"{self._base_url}/v1/chat/completions",
                headers=headers,
                json=body,
            ) as response:
                if response.status >= 400:
                    raise AgentBackendError(
                        f"Hermes backend returned HTTP {response.status}: {await response.text()}"
                    )

                # Parse SSE (Server-Sent Events) stream
                last_text = ""
                async for line_bytes in response.content:
                    line = line_bytes.decode("utf-8").strip()
                    if not line:
                        continue
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        try:
                            payload = __import__("json").loads(data)
                            choices = payload.get("choices", [])
                            for choice in choices:
                                delta = choice.get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    last_text += content
                                    yield AgentStreamChunk(
                                        text_delta=content,
                                        is_final=False,
                                        metadata={
                                            "finish_reason": choice.get("finish_reason"),
                                        },
                                    )
                                elif choice.get("finish_reason"):
                                    yield AgentStreamChunk(
                                        text_delta="",
                                        is_final=True,
                                        metadata={
                                            "finish_reason": choice.get("finish_reason"),
                                        },
                                    )
                        except __import__("json").JSONDecodeError:
                            continue

    async def send_request(self, request: AgentRequest) -> AgentResponse:
        # Accumulate streaming chunks into final response
        last_text = ""
        async for chunk in self.send_request_streaming(request):
            if chunk.text_delta:
                last_text += chunk.text_delta

        if not last_text.strip():
            raise AgentBackendError("Hermes backend returned no assistant text")

        hermes_session_id = self._map_session_key(request)
        return AgentResponse(
            response_text=last_text,
            backend_name=self.name,
            session_key=hermes_session_id,
            correlation_id=request.correlation_id,
            raw_response={},
        )

