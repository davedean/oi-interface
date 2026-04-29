"""Hermes agent backend over the local/remote HTTP API server."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import aiohttp

from .backend import AgentBackendError, AgentRequest, AgentResponse
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

    async def send_request(self, request: AgentRequest) -> AgentResponse:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        hermes_session_id = self._map_session_key(request)
        if hermes_session_id:
            headers["X-Hermes-Session-Id"] = hermes_session_id
        if request.idempotency_key:
            headers["Idempotency-Key"] = request.idempotency_key

        body = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": render_text_prompt(request),
                }
            ],
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
                payload = await response.json()

        response_text = self._extract_response_text(payload)
        if not response_text:
            raise AgentBackendError("Hermes backend returned no assistant text")

        return AgentResponse(
            response_text=response_text,
            backend_name=self.name,
            session_key=hermes_session_id,
            correlation_id=request.correlation_id,
            raw_response=payload,
        )

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
            content = message.get("content")
            text = self._extract_text_content(content)
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
