"""Normalized dashboard event payloads shared across gateway and dashboard seams."""
from __future__ import annotations

from typing import TypedDict


class NormalizedTranscriptPayload(TypedDict):
    transcript: str
    stream_id: str
    conversation_id: str


class NormalizedAgentResponsePayload(TypedDict):
    transcript: str
    response: str
    stream_id: str
    conversation_id: str


def _normalize_conversation_id(payload: dict[str, object]) -> str:
    return str(
        payload.get("conversation_id")
        or payload.get("correlation_id")
        or payload.get("stream_id")
        or ""
    )


def normalize_transcript_payload(payload: dict[str, object]) -> NormalizedTranscriptPayload:
    """Normalize a gateway transcript payload for dashboard use."""
    return {
        "transcript": str(payload.get("cleaned") or payload.get("text") or payload.get("transcript") or ""),
        "stream_id": str(payload.get("stream_id") or ""),
        "conversation_id": _normalize_conversation_id(payload),
    }


def normalize_agent_response_payload(payload: dict[str, object]) -> NormalizedAgentResponsePayload:
    """Normalize a gateway agent response payload for dashboard use."""
    return {
        "transcript": str(payload.get("transcript") or ""),
        "response": str(payload.get("response") or payload.get("response_text") or ""),
        "stream_id": str(payload.get("stream_id") or ""),
        "conversation_id": _normalize_conversation_id(payload),
    }
