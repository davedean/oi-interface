"""Unit tests for dashboard projection state."""
from __future__ import annotations

from oi_dashboard.state import DashboardState


def test_snapshot_serializes_devices_and_transcripts() -> None:
    state = DashboardState(max_transcripts=5)

    state.record_device_online("device1", {"device_id": "device1", "device_type": "stick"})
    state.record_transcript("device1", {"cleaned": "Hello"})

    snapshot = state.snapshot()

    assert snapshot["devices"]["device1"]["device_type"] == "stick"
    assert snapshot["transcripts"][0]["device_id"] == "device1"
    assert snapshot["transcripts"][0]["transcript"] == "Hello"
    assert "timestamp" in snapshot


def test_apply_polled_device_reports_online_transitions() -> None:
    state = DashboardState()

    assert state.apply_polled_device("device1", {"device_id": "device1", "online": True}) == (
        "device_online",
        {"device_id": "device1", "online": True},
    )
    assert state.apply_polled_device("device1", {"device_id": "device1", "online": True}) is None
    assert state.apply_polled_device("device1", {"device_id": "device1", "online": False}) == (
        "device_offline",
        {"device_id": "device1"},
    )


def test_mark_missing_devices_offline_returns_events() -> None:
    state = DashboardState()
    state.record_device_online("device1", {"device_id": "device1"})
    state.record_device_online("device2", {"device_id": "device2"})

    events = state.mark_missing_devices_offline({"device1"})

    assert events == [("device_offline", {"device_id": "device2"})]
    assert state.devices["device2"].online is False


def test_record_transcript_trims_and_returns_payload() -> None:
    state = DashboardState(max_transcripts=2)

    first_payload = state.record_transcript("device1", {"cleaned": "one"})
    state.record_transcript("device1", {"cleaned": "two"})
    third_payload = state.record_transcript("device1", {"cleaned": "three"})

    assert first_payload is not None
    assert third_payload is not None
    assert [entry.transcript for entry in state.transcripts] == ["two", "three"]
    assert third_payload["transcript"] == "three"
    assert "timestamp" in third_payload


def test_record_agent_response_updates_matching_transcript() -> None:
    state = DashboardState()
    state.record_transcript("device1", {"cleaned": "Hello"})

    payload = state.record_agent_response(
        "device1",
        {"transcript": "Hello", "response_text": "Hi there!"},
    )

    assert state.transcripts[0].response == "Hi there!"
    assert payload["response"] == "Hi there!"


def test_record_state_update_merges_existing_device_state() -> None:
    state = DashboardState()
    state.record_device_online("device1", {"device_id": "device1"})

    payload = state.record_state_updated("device1", {"mode": "listening", "battery_percent": 80})

    assert state.devices["device1"].state == {"mode": "listening", "battery_percent": 80}
    assert payload == {"device_id": "device1", "state": {"mode": "listening", "battery_percent": 80}}


def test_transcript_windows_live_behind_state_interface() -> None:
    state = DashboardState(max_transcripts=10, snapshot_transcript_limit=2, api_transcript_limit=3)
    for index in range(4):
        state.record_transcript("device1", {"cleaned": f"Transcript {index}"})

    snapshot = state.snapshot()
    api_payload = state.transcript_listing()

    assert [entry["transcript"] for entry in snapshot["transcripts"]] == ["Transcript 2", "Transcript 3"]
    assert [entry["transcript"] for entry in api_payload["transcripts"]] == [
        "Transcript 1",
        "Transcript 2",
        "Transcript 3",
    ]
    assert api_payload["count"] == 4
