"""Unit tests for normalized dashboard event payloads."""
from __future__ import annotations

from oi_dashboard.event_payloads import normalize_agent_response_payload, normalize_transcript_payload


def test_normalize_transcript_payload_prefers_explicit_conversation_id() -> None:
    payload = normalize_transcript_payload(
        {
            "cleaned": "Hello",
            "stream_id": "stream-1",
            "conversation_id": "conversation-1",
        }
    )

    assert payload["transcript"] == "Hello"
    assert payload["stream_id"] == "stream-1"
    assert payload["conversation_id"] == "conversation-1"


def test_normalize_agent_response_payload_uses_correlation_id_as_conversation_id() -> None:
    payload = normalize_agent_response_payload(
        {
            "transcript": "Hello",
            "response_text": "Hi there!",
            "correlation_id": "conversation-1",
        }
    )

    assert payload["response"] == "Hi there!"
    assert payload["conversation_id"] == "conversation-1"
    assert payload["stream_id"] == ""
