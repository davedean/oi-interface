"""Backend-neutral agent request/response contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class AgentBackendError(Exception):
    """Raised when an agent backend fails to return a valid response."""


@dataclass(frozen=True)
class AgentRequest:
    """Normalized request from Oi to an agent backend."""

    user_text: str
    source_device_id: str
    input_kind: str
    stream_id: str | None = None
    prompt_text: str | None = None
    transcript: str | None = None
    session_key: str | None = None
    correlation_id: str | None = None
    idempotency_key: str | None = None
    device_context: dict[str, Any] = field(default_factory=dict)
    reply_constraints: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentResponse:
    """Normalized response from an agent backend to Oi."""

    response_text: str
    backend_name: str
    session_key: str | None = None
    correlation_id: str | None = None
    raw_response: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentBackend(Protocol):
    """Abstract interface for agent backends."""

    @property
    def name(self) -> str:
        """Return a stable backend name for logs and payloads."""

    async def send_request(self, request: AgentRequest) -> AgentResponse:
        """Send a normalized request and return a normalized response."""
