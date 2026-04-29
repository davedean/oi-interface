from pathlib import Path
import sys

import pytest


gateway_src = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(gateway_src))

from channel.backend import AgentRequest
from channel.request_builder import (
    build_agent_request_from_text_prompt,
    build_agent_request_from_transcript,
    build_session_key,
    render_text_prompt,
)


def test_build_session_key_uses_device_identity():
    assert build_session_key("test-device") == "oi:device:test-device"


def test_build_agent_request_from_transcript_populates_fields():
    device_context = {
        "source_device": "test-device",
        "foreground": "test-device",
        "online": ["test-device"],
        "capabilities": {"test-device": {"max_spoken_seconds": 12, "supports_confirm_buttons": True}},
    }

    request = build_agent_request_from_transcript(
        device_id="test-device",
        stream_id="rec_001",
        transcript="mute for 30 minutes.",
        device_context=device_context,
    )

    assert request.user_text == "mute for 30 minutes."
    assert request.source_device_id == "test-device"
    assert request.input_kind == "transcript"
    assert request.stream_id == "rec_001"
    assert request.transcript == "mute for 30 minutes."
    assert request.prompt_text is None
    assert request.session_key == "oi:device:test-device"
    assert request.correlation_id == "rec_001"
    assert request.idempotency_key == "rec_001"
    assert request.device_context == device_context
    assert request.reply_constraints == {"max_spoken_seconds": 12, "supports_confirm_buttons": True}


def test_build_agent_request_from_text_prompt_populates_fields():
    device_context = {
        "source_device": "test-device",
        "foreground": None,
        "online": ["test-device", "other-device"],
        "capabilities": {"test-device": {"max_spoken_seconds": 12}},
    }

    request = build_agent_request_from_text_prompt(
        device_id="test-device",
        text="what time is it?",
        device_context=device_context,
    )

    assert request.user_text == "what time is it?"
    assert request.source_device_id == "test-device"
    assert request.input_kind == "text_prompt"
    assert request.stream_id is None
    assert request.transcript is None
    assert request.prompt_text == "what time is it?"
    assert request.session_key == "oi:device:test-device"
    assert request.correlation_id == "text:test-device:what time is it?"
    assert request.idempotency_key == "text:test-device:what time is it?"
    assert request.reply_constraints == {"max_spoken_seconds": 12}


@pytest.mark.parametrize(
    ("agent_request", "expected"),
    [
        (
            AgentRequest(
                user_text="mute for 30 minutes.",
                source_device_id="test-device",
                input_kind="transcript",
                transcript="mute for 30 minutes.",
                device_context={
                    "source_device": "test-device",
                    "foreground": "test-device",
                    "online": ["test-device"],
                    "capabilities": {"test-device": {"max_spoken_seconds": 12}},
                },
            ),
            "The user said: 'mute for 30 minutes.'. Device: test-device (foreground), max_spoken_seconds=12.",
        ),
        (
            AgentRequest(
                user_text="what time is it?",
                source_device_id="test-device",
                input_kind="text_prompt",
                prompt_text="what time is it?",
                device_context={
                    "source_device": "test-device",
                    "foreground": None,
                    "online": ["test-device"],
                    "capabilities": {"test-device": {"max_spoken_seconds": 12}},
                },
            ),
            "User text: 'what time is it?'. Device: test-device, max_spoken_seconds=12.",
        ),
    ],
)
def test_render_text_prompt_matches_existing_message_shapes(agent_request, expected):
    assert render_text_prompt(agent_request) == expected
