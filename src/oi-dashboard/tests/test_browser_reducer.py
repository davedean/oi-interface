"""Contract tests for the shared browser reducer seam."""
from __future__ import annotations

import json
import subprocess

from oi_dashboard.browser_reducer import DASHBOARD_REDUCER_JS


def run_reducer(events: list[dict[str, object]], initial_state: dict[str, object] | None = None) -> dict[str, object]:
    script = f"""
{DASHBOARD_REDUCER_JS}
state = {json.dumps(initial_state or {'devices': {}, 'transcripts': []})};
for (const event of {json.dumps(events)}) {{
  state = reduceEvent(state, event);
}}
console.log(JSON.stringify(state));
"""
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def test_reducer_merges_full_device_payload_on_device_online() -> None:
    state = run_reducer([
        {
            "type": "device_online",
            "data": {
                "device_id": "device-1",
                "device_type": "stick",
                "online": True,
                "state": {"mode": "listening"},
            },
        }
    ])

    assert state["devices"]["device-1"]["device_type"] == "stick"
    assert state["devices"]["device-1"]["state"]["mode"] == "listening"


def test_reducer_materializes_state_updates_for_unknown_devices() -> None:
    state = run_reducer([
        {
            "type": "state_updated",
            "data": {
                "device_id": "device-1",
                "state": {"mode": "thinking"},
            },
        }
    ])

    assert state["devices"]["device-1"]["state"]["mode"] == "thinking"


def test_reducer_preserves_transcript_contract_fields() -> None:
    state = run_reducer([
        {
            "type": "transcript",
            "data": {
                "timestamp": "2026-04-30T00:00:00+00:00",
                "device_id": "device-1",
                "transcript": "Hello",
                "response": "",
                "stream_id": "stream-1",
                "conversation_id": "stream-1",
            },
        }
    ])

    assert state["transcripts"][0]["timestamp"] == "2026-04-30T00:00:00+00:00"
    assert state["transcripts"][0]["stream_id"] == "stream-1"
    assert state["transcripts"][0]["conversation_id"] == "stream-1"


def test_reducer_matches_agent_responses_by_stream_id() -> None:
    state = run_reducer([
        {
            "type": "transcript",
            "data": {
                "timestamp": "2026-04-30T00:00:00+00:00",
                "device_id": "device-1",
                "transcript": "Hello",
                "response": "",
                "stream_id": "stream-1",
                "conversation_id": "stream-1",
            },
        },
        {
            "type": "agent_response",
            "data": {
                "device_id": "device-1",
                "transcript": "Hello",
                "response": "Hi there!",
                "stream_id": "stream-1",
                "conversation_id": "stream-1",
            },
        },
    ])

    assert state["transcripts"][0]["response"] == "Hi there!"


def test_reducer_overwrites_existing_agent_response_for_same_conversation() -> None:
    state = run_reducer([
        {
            "type": "transcript",
            "data": {
                "timestamp": "2026-04-30T00:00:00+00:00",
                "device_id": "device-1",
                "transcript": "Hello",
                "response": "Draft",
                "stream_id": "stream-1",
                "conversation_id": "stream-1",
            },
        },
        {
            "type": "agent_response",
            "data": {
                "device_id": "device-1",
                "transcript": "Hello",
                "response": "Final",
                "stream_id": "stream-1",
                "conversation_id": "stream-1",
            },
        },
    ])

    assert state["transcripts"][0]["response"] == "Final"
