from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from oi_client.delight import (  # noqa: E402
    SECRET_SEQUENCE,
    SURPRISE_PROMPTS,
    SecretTracker,
    format_gateway_about,
    pick_surprise_prompt,
)


def test_surprise_prompt_cycles() -> None:
    assert pick_surprise_prompt(0) == SURPRISE_PROMPTS[0]
    assert pick_surprise_prompt(len(SURPRISE_PROMPTS)) == SURPRISE_PROMPTS[0]


def test_secret_tracker_detects_full_code() -> None:
    tracker = SecretTracker()
    for button in SECRET_SEQUENCE[:-1]:
        assert tracker.push(button) is False
    assert tracker.push(SECRET_SEQUENCE[-1]) is True


def test_format_gateway_about_uses_hello_ack_metadata() -> None:
    lines = format_gateway_about({
        "payload": {
            "server_name": "Oi Gateway",
            "session_id": "sess-123",
            "accepted_protocol": "datp",
            "default_agent": {"name": "helper"},
            "available_agents": [{"name": "helper"}, {"name": "oracle"}],
        }
    })
    joined = "\n".join(lines)
    assert "Oi Gateway" in joined
    assert "sess-123" in joined
    assert "helper" in joined
    assert "oracle" in joined
