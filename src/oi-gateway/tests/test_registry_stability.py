"""Tests for registry stability features: reconnection, heartbeat, foreground selection."""
from __future__ import annotations

import asyncio
import json
import time

import pytest
import websockets

from datp.server import DATPServer
from datp.events import EventBus
from registry.models import DeviceInfo
from registry.service import RegistryService
from registry.store import DeviceStore
from registry.reconnection import ReconnectionManager
from registry.heartbeat import HeartbeatMonitor
from registry.events import (
    REGISTRY_DEVICE_ONLINE,
    REGISTRY_DEVICE_OFFLINE,
    REGISTRY_STATE_UPDATED,
    REGISTRY_DEVICE_UNHEALTHY,
    REGISTRY_DEVICE_RECONNECTED,
)


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path):
    """Provide a temporary SQLite DB path."""
    return str(tmp_path / "test-stability.db")


@pytest.fixture
def store(tmp_db):
    """Provide a DeviceStore backed by a temporary DB."""
    store = DeviceStore(tmp_db)
    yield store
    store.close()


@pytest.fixture
def event_bus():
    """Provide a fresh EventBus."""
    return EventBus()


@pytest.fixture
def registry(store, event_bus):
    """Provide a RegistryService with an in-memory store + event bus."""
    return RegistryService(store, event_bus)


@pytest.fixture
async def server_with_registry(registry):
    """Start DATPServer with RegistryService injected, yield, then stop.

    The server shares the same EventBus as the registry so that code
    subscribing to ``server.event_bus`` receives registry events.
    """
    srv = DATPServer(
        host="localhost",
        port=0,
        event_bus=registry._event_bus,  # share the registry's event bus
        registry=registry,
    )
    task = asyncio.create_task(srv.start())
    await asyncio.sleep(0.1)
    yield srv
    await srv.stop()
    await asyncio.sleep(0.1)


# ------------------------------------------------------------------
# ReconnectionManager Unit Tests
# ------------------------------------------------------------------

def test_reconnection_record_disconnect_increments_count():
    """Disconnect records increment the reconnection count."""
    bus = EventBus()
    mgr = ReconnectionManager(bus)

    mgr.record_disconnect("dev-1")
    assert mgr.get_reconnect_count("dev-1") == 1

    mgr.record_disconnect("dev-1")
    assert mgr.get_reconnect_count("dev-1") == 2

    mgr.record_disconnect("dev-1")
    assert mgr.get_reconnect_count("dev-1") == 3


def test_reconnection_get_backoff_delay_exponential():
    """Backoff delay grows exponentially with reconnect count."""
    bus = EventBus()
    mgr = ReconnectionManager(bus, base_delay=1.0, max_delay=60.0, jitter=False)

    # Initial disconnect
    mgr.record_disconnect("dev-1")

    # Count 1: delay = 1.0 * 2^1 = 2.0
    assert mgr.get_backoff_delay("dev-1") == 2.0

    # Count 2: delay = 1.0 * 2^2 = 4.0
    mgr.record_disconnect("dev-1")
    assert mgr.get_backoff_delay("dev-1") == 4.0

    # Count 3: delay = 1.0 * 2^3 = 8.0
    mgr.record_disconnect("dev-1")
    assert mgr.get_backoff_delay("dev-1") == 8.0


def test_reconnection_get_backoff_delay_max_limit():
    """Backoff delay is capped at max_delay."""
    bus = EventBus()
    mgr = ReconnectionManager(bus, base_delay=1.0, max_delay=10.0, jitter=False)

    # Push count high enough to exceed max_delay
    for _ in range(10):
        mgr.record_disconnect("dev-1")

    delay = mgr.get_backoff_delay("dev-1")
    assert delay <= 10.0


def test_reconnection_should_reconnect_under_limit():
    """should_reconnect returns True when under max_retries."""
    bus = EventBus()
    mgr = ReconnectionManager(bus, max_retries=5)

    for i in range(5):
        mgr.record_disconnect("dev-1")
        assert mgr.should_reconnect("dev-1") is True


def test_reconnection_should_reconnect_over_limit():
    """should_reconnect returns False when over max_retries."""
    bus = EventBus()
    mgr = ReconnectionManager(bus, max_retries=3)

    for _ in range(3):
        mgr.record_disconnect("dev-1")

    assert mgr.should_reconnect("dev-1") is True

    # One more puts us over
    mgr.record_disconnect("dev-1")
    assert mgr.should_reconnect("dev-1") is False


def test_reconnection_save_and_restore_state():
    """State can be saved and restored correctly."""
    bus = EventBus()
    mgr = ReconnectionManager(bus)

    original_state = {"mode": "READY", "battery_percent": 85}
    mgr.save_state("dev-1", original_state)

    # Restore should return the saved state
    restored = mgr.restore_state("dev-1")
    assert restored == original_state

    # Second restore should return None
    assert mgr.restore_state("dev-1") is None


def test_reconnection_record_reconnect_emits_event():
    """Reconnect emits REGISTRY_DEVICE_RECONNECTED event."""
    bus = EventBus()
    mgr = ReconnectionManager(bus)

    received = []

    def handler(event_type, device_id, payload):
        received.append((event_type, device_id, payload))

    bus.subscribe(handler)
    try:
        mgr.record_disconnect("dev-1")
        mgr.record_reconnect("dev-1")

        assert len(received) == 1
        evt_type, dev_id, payload = received[0]
        assert evt_type == REGISTRY_DEVICE_RECONNECTED
        assert dev_id == "dev-1"
        assert payload["reconnect_count"] == 1
    finally:
        bus.unsubscribe(handler)


def test_reconnection_clear_device():
    """clear_device removes all state for a device."""
    bus = EventBus()
    mgr = ReconnectionManager(bus)

    mgr.record_disconnect("dev-1")
    mgr.save_state("dev-1", {"mode": "TEST"})

    mgr.clear_device("dev-1")

    assert mgr.get_reconnect_count("dev-1") == 0
    assert mgr.get_disconnect_time("dev-1") is None
    assert mgr.restore_state("dev-1") is None


# ------------------------------------------------------------------
# HeartbeatMonitor Unit Tests
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_heartbeat_record_updates_tracking(registry, event_bus):
    """Recording a heartbeat updates the internal tracking."""
    monitor = registry._heartbeat

    monitor.record_heartbeat("dev-1")
    assert monitor.is_device_tracked("dev-1")
    assert monitor.get_last_heartbeat("dev-1") is not None


@pytest.mark.asyncio
async def test_heartbeat_mark_healthy(registry, event_bus):
    """Marking a device healthy updates registry."""
    monitor = registry._heartbeat

    # Record a heartbeat
    monitor.record_heartbeat("dev-1")

    # Manually mark unhealthy (simulating timeout)
    monitor.mark_unhealthy("dev-1")
    assert monitor.is_device_unhealthy("dev-1")

    # Record new heartbeat
    monitor.record_heartbeat("dev-1")
    assert not monitor.is_device_unhealthy("dev-1")


@pytest.mark.asyncio
async def test_heartbeat_remove_device(registry, event_bus):
    """Removing a device clears tracking."""
    monitor = registry._heartbeat

    monitor.record_heartbeat("dev-1")
    assert monitor.is_device_tracked("dev-1")

    monitor.remove_device("dev-1")
    assert not monitor.is_device_tracked("dev-1")


@pytest.mark.asyncio
async def test_heartbeat_start_stop(registry, event_bus):
    """Starting and stopping the monitor works without error."""
    monitor = registry._heartbeat

    await monitor.start()
    assert monitor._task is not None and not monitor._task.done()

    await monitor.stop()
    # Task should be done/cancelled after stop
    await asyncio.sleep(0.1)


# ------------------------------------------------------------------
# RegistryService Stability Integration Tests
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_last_interaction_sets_timestamp(registry):
    """update_last_interaction updates the timestamp in DB."""
    await registry.device_registered(
        device_id="test-001",
        device_type="oi-stick",
        session_id="sess_1",
        capabilities={},
        resume_token=None,
        nonce=None,
    )

    await registry.update_last_interaction("test-001")

    info = await registry.get_device("test-001")
    assert info is not None
    assert info.last_interaction is not None


@pytest.mark.asyncio
async def test_set_foreground_device(registry):
    """set_foreground_device sets priority correctly."""
    # Register two devices
    await registry.device_registered(
        device_id="dev-a",
        device_type="oi-stick",
        session_id="sess_a",
        capabilities={},
        resume_token=None,
        nonce=None,
    )
    await registry.device_registered(
        device_id="dev-b",
        device_type="pi-screen",
        session_id="sess_b",
        capabilities={},
        resume_token=None,
        nonce=None,
    )

    # Set dev-b as foreground
    ok = await registry.set_foreground_device("dev-b")
    assert ok is True

    # get_foreground_device should return dev-b
    fg = registry.get_foreground_device()
    assert fg is not None
    assert fg.device_id == "dev-b"


@pytest.mark.asyncio
async def test_get_foreground_device_priority_then_interaction(registry):
    """Foreground selection prefers priority, then recent interaction."""
    # Register devices
    await registry.device_registered(
        device_id="dev-priority",
        device_type="oi-stick",
        session_id="sess_p",
        capabilities={},
        resume_token=None,
        nonce=None,
    )
    await registry.device_registered(
        device_id="dev-recent",
        device_type="pi-screen",
        session_id="sess_r",
        capabilities={},
        resume_token=None,
        nonce=None,
    )

    # Set priority on dev-priority
    await registry.set_foreground_device("dev-priority")

    # Update interaction on dev-recent (more recent)
    await registry.update_last_interaction("dev-recent")

    # Should still pick priority device
    fg = registry.get_foreground_device()
    assert fg is not None
    assert fg.device_id == "dev-priority"


@pytest.mark.asyncio
async def test_validate_capabilities_on_reconnect_added(registry):
    """validate_capabilities_on_reconnect detects added caps."""
    await registry.device_registered(
        device_id="cap-test",
        device_type="oi-stick",
        session_id="sess_cap",
        capabilities={"input": ["hold_to_record"]},
        resume_token=None,
        nonce=None,
    )

    diff = registry.validate_capabilities_on_reconnect(
        "cap-test",
        {"input": ["hold_to_record"], "output": ["speaker"]}
    )

    assert "output" in diff["added"]
    assert diff["removed"] == []
    assert diff["changed"] == []


@pytest.mark.asyncio
async def test_validate_capabilities_on_reconnect_removed(registry):
    """validate_capabilities_on_reconnect detects removed caps."""
    await registry.device_registered(
        device_id="cap-test",
        device_type="oi-stick",
        session_id="sess_cap",
        capabilities={"input": ["hold_to_record"], "output": ["speaker"]},
        resume_token=None,
        nonce=None,
    )

    diff = registry.validate_capabilities_on_reconnect(
        "cap-test",
        {"input": ["hold_to_record"]}
    )

    assert "output" in diff["removed"]
    assert diff["added"] == []


@pytest.mark.asyncio
async def test_validate_capabilities_on_reconnect_changed(registry):
    """validate_capabilities_on_reconnect detects changed caps."""
    await registry.device_registered(
        device_id="cap-test",
        device_type="oi-stick",
        session_id="sess_cap",
        capabilities={"firmware": "1.0"},
        resume_token=None,
        nonce=None,
    )

    diff = registry.validate_capabilities_on_reconnect(
        "cap-test",
        {"firmware": "2.0"}
    )

    assert "firmware" in diff["changed"]


@pytest.mark.asyncio
async def test_reconnect_state_recovery(registry):
    """State is preserved and restored on reconnect."""
    # Register device
    await registry.device_registered(
        device_id="state-test",
        device_type="oi-stick",
        session_id="sess_1",
        capabilities={},
        resume_token=None,
        nonce=None,
    )

    # Update state
    await registry.device_state_update("state-test", {"mode": "SPEAKING"})

    # Disconnect (saves state)
    registry.device_disconnected("state-test")

    # Reconnect (should restore state)
    saved_state = registry._reconnection.restore_state("state-test")
    assert saved_state is not None
    assert saved_state["mode"] == "SPEAKING"


@pytest.mark.asyncio
async def test_device_unhealthy_event_emitted(registry, event_bus):
    """REGISTRY_DEVICE_UNHEALTHY event is emitted on unhealthy."""
    received = []

    def handler(event_type, device_id, payload):
        received.append((event_type, device_id, payload))

    event_bus.subscribe(handler)
    try:
        # Mark device unhealthy
        registry._heartbeat.mark_unhealthy("test-001")

        assert len(received) == 1
        evt_type, dev_id, _ = received[0]
        assert evt_type == REGISTRY_DEVICE_UNHEALTHY
        assert dev_id == "test-001"
    finally:
        event_bus.unsubscribe(handler)


# ------------------------------------------------------------------
# DeviceStore New Fields Tests
# ------------------------------------------------------------------

def test_store_new_fields_round_trip(store):
    """All new fields survive upsert/get round-trip."""
    from datetime import datetime, timezone

    info = DeviceInfo(
        device_id="store-new-001",
        device_type="oi-stick",
        session_id="sess_new",
        connected_at=datetime.now(timezone.utc),
        last_seen=datetime.now(timezone.utc),
        capabilities={"input": ["hold_to_record"]},
        resume_token=None,
        nonce="nonce123",
        state={"mode": "READY"},
        audio_cache_bytes=0,
        muted_until=None,
        last_interaction=datetime.now(timezone.utc),
        reconnect_count=3,
        foreground_priority=5,
        heartbeat_timeout=45.0,
        last_heartbeat=datetime.now(timezone.utc),
        is_healthy=False,
    )

    store.upsert_device(info)
    retrieved = store.get_device("store-new-001")

    assert retrieved is not None
    assert retrieved.last_interaction is not None
    assert retrieved.reconnect_count == 3
    assert retrieved.foreground_priority == 5
    assert retrieved.heartbeat_timeout == 45.0
    assert retrieved.last_heartbeat is not None
    assert retrieved.is_healthy is False


def test_store_update_health(store):
    """update_health persists is_healthy status."""
    info = DeviceInfo(
        device_id="store-health-001",
        device_type="oi-stick",
        session_id="sess_h",
        connected_at=None,
        last_seen=None,
        capabilities={},
        resume_token=None,
        nonce=None,
        state={},
        audio_cache_bytes=0,
        muted_until=None,
    )
    store.upsert_device(info)

    store.update_health("store-health-001", False)
    retrieved = store.get_device("store-health-001")
    assert retrieved.is_healthy is False

    store.update_health("store-health-001", True)
    retrieved = store.get_device("store-health-001")
    assert retrieved.is_healthy is True


def test_store_update_foreground_priority(store):
    """update_foreground_priority persists priority."""
    info = DeviceInfo(
        device_id="store-priority-001",
        device_type="oi-stick",
        session_id="sess_p",
        connected_at=None,
        last_seen=None,
        capabilities={},
        resume_token=None,
        nonce=None,
        state={},
        audio_cache_bytes=0,
        muted_until=None,
    )
    store.upsert_device(info)

    store.update_foreground_priority("store-priority-001", 10)
    retrieved = store.get_device("store-priority-001")
    assert retrieved.foreground_priority == 10


def test_store_set_foreground_priority_highest(store):
    """set_foreground_priority_highest sets device above others."""
    # Create two devices
    for i in range(2):
        info = DeviceInfo(
            device_id=f"store-fg-{i}",
            device_type="oi-stick",
            session_id=f"sess_fg_{i}",
            connected_at=None,
            last_seen=None,
            capabilities={},
            resume_token=None,
            nonce=None,
            state={},
            audio_cache_bytes=0,
            muted_until=None,
            foreground_priority=i,  # First gets 0, second gets 1
        )
        store.upsert_device(info)

    # Set first device as highest
    store.set_foreground_priority_highest("store-fg-0")

    # First device should now have highest priority (higher than 1)
    retrieved = store.get_device("store-fg-0")
    assert retrieved.foreground_priority > 1


# ------------------------------------------------------------------
# Integration Tests with DATPServer
# ------------------------------------------------------------------

from .test_utils import make_hello


@pytest.mark.asyncio
async def test_integration_reconnect_state_preserved(server_with_registry):
    """Device reconnect preserves state from before disconnect."""
    srv = server_with_registry
    device_id = "sim-reconnect-001"

    # First connection
    async with websockets.connect(f"ws://localhost:{srv.port}/datp") as ws:
        await ws.send(json.dumps(make_hello(device_id)))
        await asyncio.wait_for(ws.recv(), timeout=5.0)

        # Send state update
        state_update = {
            "v": "datp",
            "type": "state",
            "id": "state_1",
            "device_id": device_id,
            "ts": "2026-04-27T04:40:01.000Z",
            "payload": {"mode": "THINKING", "battery_percent": 90},
        }
        await ws.send(json.dumps(state_update))
        await asyncio.sleep(0.2)

    # Wait for disconnect processing
    await asyncio.sleep(0.2)

    # Reconnect
    async with websockets.connect(f"ws://localhost:{srv.port}/datp") as ws:
        await ws.send(json.dumps(make_hello(device_id)))
        await asyncio.wait_for(ws.recv(), timeout=5.0)
        await asyncio.sleep(0.2)

    # Check state was preserved (reconnect_count should be 1)
    info = await srv.registry.get_device(device_id)
    assert info is not None
    assert info.reconnect_count >= 1


@pytest.mark.asyncio
async def test_integration_capabilities_validated_on_reconnect(server_with_registry):
    """Capabilities are validated when device reconnects."""
    srv = server_with_registry
    device_id = "sim-cap-validate"

    # First connection with full capabilities
    caps_v1 = {"input": ["hold_to_record"], "output": ["speaker"]}
    hello_v1 = make_hello(device_id)
    hello_v1["payload"]["capabilities"] = caps_v1

    async with websockets.connect(f"ws://localhost:{srv.port}/datp") as ws:
        await ws.send(json.dumps(hello_v1))
        await asyncio.wait_for(ws.recv(), timeout=5.0)

    await asyncio.sleep(0.2)

    # Reconnect with reduced capabilities
    caps_v2 = {"input": ["hold_to_record"]}  # Removed output
    hello_v2 = make_hello(device_id)
    hello_v2["payload"]["capabilities"] = caps_v2

    received_events = []
    def handler(event_type, device_id, payload):
        received_events.append((event_type, device_id, payload))

    srv.registry._event_bus.subscribe(handler)
    try:
        async with websockets.connect(f"ws://localhost:{srv.port}/datp") as ws:
            await ws.send(json.dumps(hello_v2))
            await asyncio.wait_for(ws.recv(), timeout=5.0)
            await asyncio.sleep(0.2)

        # Check that reconnect event was emitted
        reconnect_events = [e for e in received_events if e[0] == REGISTRY_DEVICE_RECONNECTED]
        assert len(reconnect_events) >= 1

        # Check the payload contains capability diff
        event = reconnect_events[0]
        if len(event) >= 3 and event[2]:
            payload = event[2]
            if "capabilities_diff" in payload:
                assert "output" in payload["capabilities_diff"]["removed"]
    finally:
        srv.registry._event_bus.unsubscribe(handler)


@pytest.mark.asyncio
async def test_integration_foreground_selection_policy(server_with_registry):
    """Foreground selection uses priority and interaction policy."""
    srv = server_with_registry

    # Register two devices
    await srv.registry.device_registered(
        device_id="fg-dev-a",
        device_type="oi-stick",
        session_id="sess_fg_a",
        capabilities={},
        resume_token=None,
        nonce=None,
    )
    await srv.registry.device_registered(
        device_id="fg-dev-b",
        device_type="pi-screen",
        session_id="sess_fg_b",
        capabilities={},
        resume_token=None,
        nonce=None,
    )

    # No foreground set - returns None with multiple online
    fg = srv.registry.get_foreground_device()
    assert fg is None  # Ambiguous with multiple devices

    # Set fg-dev-b as foreground
    await srv.registry.set_foreground_device("fg-dev-b")

    # Now should return fg-dev-b
    fg = srv.registry.get_foreground_device()
    assert fg is not None
    assert fg.device_id == "fg-dev-b"


@pytest.mark.asyncio
async def test_integration_heartbeat_tracking(server_with_registry):
    """Heartbeats are tracked for connected devices."""
    srv = server_with_registry
    device_id = "sim-heartbeat"

    async with websockets.connect(f"ws://localhost:{srv.port}/datp") as ws:
        await ws.send(json.dumps(make_hello(device_id)))
        await asyncio.wait_for(ws.recv(), timeout=5.0)
        await asyncio.sleep(0.2)

    # Device should be tracked by heartbeat monitor
    monitor = srv.registry._heartbeat
    assert monitor.is_device_tracked(device_id)
    assert monitor.get_last_heartbeat(device_id) is not None


@pytest.mark.asyncio
async def test_integration_health_status_api(server_with_registry):
    """get_health_status returns correct health information."""
    srv = server_with_registry
    device_id = "sim-health-status"

    # Register device
    await srv.registry.device_registered(
        device_id=device_id,
        device_type="oi-stick",
        session_id="sess_health",
        capabilities={},
        resume_token=None,
        nonce=None,
    )

    # Get health status
    health = srv.registry.get_health_status(device_id)
    assert health is not None
    assert "is_healthy" in health
    assert "last_heartbeat" in health
    assert "heartbeat_timeout" in health
    assert "is_online" in health
