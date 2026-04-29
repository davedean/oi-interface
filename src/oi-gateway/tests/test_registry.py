"""Tests for the device registry (Step 3)."""
from __future__ import annotations

import asyncio
import json

import pytest
import websockets

from datp.server import DATPServer
from datp.events import EventBus
from registry.models import DeviceInfo
from registry.service import RegistryService
from registry.store import DeviceStore
from registry.events import (
    REGISTRY_DEVICE_ONLINE,
    REGISTRY_DEVICE_OFFLINE,
    REGISTRY_STATE_UPDATED,
)


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path):
    """Provide a temporary SQLite DB path."""
    return str(tmp_path / "test-oi.db")


@pytest.fixture
def store(tmp_db):
    """Provide a DeviceStore backed by a temporary DB."""
    return DeviceStore(tmp_db)


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
# RegistryService unit tests
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_device_registered_creates_entry(registry):
    """device_registered creates a DeviceInfo entry."""
    info = await registry.device_registered(
        device_id="test-001",
        device_type="oi-stick",
        session_id="sess_abc",
        capabilities={"input": ["hold_to_record"]},
        resume_token=None,
        nonce="nonce123",
    )
    assert info.device_id == "test-001"
    assert info.device_type == "oi-stick"
    assert info.session_id == "sess_abc"
    assert info.capabilities == {"input": ["hold_to_record"]}
    assert info.nonce == "nonce123"

    # Query back
    stored = await registry.get_device("test-001")
    assert stored is not None
    assert stored.device_id == "test-001"


@pytest.mark.asyncio
async def test_device_registered_updates_existing(registry):
    """Calling device_registered twice updates the existing entry."""
    await registry.device_registered(
        device_id="test-002",
        device_type="oi-stick",
        session_id="sess_first",
        capabilities={},
        resume_token=None,
        nonce=None,
    )
    info2 = await registry.device_registered(
        device_id="test-002",
        device_type="oi-stick",
        session_id="sess_second",
        capabilities={"updated": True},
        resume_token="tok",
        nonce=None,
    )
    assert info2.session_id == "sess_second"
    assert info2.capabilities == {"updated": True}
    assert info2.resume_token == "tok"


@pytest.mark.asyncio
async def test_device_disconnected_marks_offline(registry):
    """device_disconnected marks the device offline but keeps DB entry."""
    await registry.device_registered(
        device_id="test-003",
        device_type="oi-stick",
        session_id="sess_xyz",
        capabilities={},
        resume_token=None,
        nonce=None,
    )
    assert await registry.get_device("test-003") is not None
    assert len(registry.get_online_devices()) == 1

    registry.device_disconnected("test-003")

    # Still in DB
    assert await registry.get_device("test-003") is not None
    # Not online
    assert len(registry.get_online_devices()) == 0


@pytest.mark.asyncio
async def test_device_state_update(registry):
    """device_state_update stores the reported state."""
    await registry.device_registered(
        device_id="test-004",
        device_type="oi-stick",
        session_id="sess_4",
        capabilities={},
        resume_token=None,
        nonce=None,
    )
    test_state = {"mode": "THINKING", "battery_percent": 80}
    await registry.device_state_update("test-004", test_state)

    info = await registry.get_device("test-004")
    assert info is not None
    assert info.state == test_state


@pytest.mark.asyncio
async def test_get_online_devices(registry):
    """Only currently connected devices appear in get_online_devices."""
    await registry.device_registered(
        device_id="sim-a",
        device_type="oi-stick",
        session_id="sess_a",
        capabilities={},
        resume_token=None,
        nonce=None,
    )
    await registry.device_registered(
        device_id="sim-b",
        device_type="oi-stick",
        session_id="sess_b",
        capabilities={},
        resume_token=None,
        nonce=None,
    )
    assert len(registry.get_online_devices()) == 2

    registry.device_disconnected("sim-b")
    assert len(registry.get_online_devices()) == 1
    assert registry.get_online_devices()[0].device_id == "sim-a"


@pytest.mark.asyncio
async def test_get_all_devices(registry):
    """get_all_devices returns both online and offline devices."""
    await registry.device_registered(
        device_id="online-1",
        device_type="oi-stick",
        session_id="s1",
        capabilities={},
        resume_token=None,
        nonce=None,
    )
    await registry.device_registered(
        device_id="online-2",
        device_type="pi-screen",
        session_id="s2",
        capabilities={},
        resume_token=None,
        nonce=None,
    )
    all_devs = await registry.get_all_devices()
    assert len(all_devs) == 2

    registry.device_disconnected("online-2")
    all_devs = await registry.get_all_devices()
    assert len(all_devs) == 2  # offline but still in DB


@pytest.mark.asyncio
async def test_get_foreground_device_single(registry):
    """With one online device, it is the foreground device."""
    await registry.device_registered(
        device_id="solo",
        device_type="oi-stick",
        session_id="sess_solo",
        capabilities={},
        resume_token=None,
        nonce=None,
    )
    fg = registry.get_foreground_device()
    assert fg is not None
    assert fg.device_id == "solo"


@pytest.mark.asyncio
async def test_get_foreground_device_multiple(registry):
    """With multiple online devices, foreground is ambiguous → None."""
    await registry.device_registered(
        device_id="multi-a",
        device_type="oi-stick",
        session_id="sess_ma",
        capabilities={},
        resume_token=None,
        nonce=None,
    )
    await registry.device_registered(
        device_id="multi-b",
        device_type="pi-screen",
        session_id="sess_mb",
        capabilities={},
        resume_token=None,
        nonce=None,
    )
    fg = registry.get_foreground_device()
    assert fg is None


@pytest.mark.asyncio
async def test_capabilities_stored(registry):
    """Capabilities from hello are persisted and queryable."""
    caps = {
        "input": ["hold_to_record", "double_tap"],
        "output": ["tiny_screen", "cached_audio"],
        "commands_supported": ["display.show_status", "audio.play"],
    }
    await registry.device_registered(
        device_id="cap-test",
        device_type="oi-stick",
        session_id="sess_cap",
        capabilities=caps,
        resume_token=None,
        nonce=None,
    )
    stored_caps = registry.get_capabilities("cap-test")
    assert stored_caps == caps

    # Reconnect updates capabilities
    updated_caps = {"input": ["hold_to_record"], "output": ["speaker"]}
    await registry.device_registered(
        device_id="cap-test",
        device_type="oi-stick",
        session_id="sess_cap2",
        capabilities=updated_caps,
        resume_token=None,
        nonce=None,
    )
    assert registry.get_capabilities("cap-test") == updated_caps


@pytest.mark.asyncio
async def test_offline_device_still_queryable(registry):
    """After disconnection, get_device still returns full info from DB."""
    await registry.device_registered(
        device_id="offline-query",
        device_type="oi-stick",
        session_id="sess_oq",
        capabilities={"test": True},
        resume_token=None,
        nonce=None,
    )
    await registry.device_state_update("offline-query", {"mode": "MUTED"})

    registry.device_disconnected("offline-query")

    info = await registry.get_device("offline-query")
    assert info is not None
    assert info.device_id == "offline-query"
    assert info.capabilities == {"test": True}
    assert info.state == {"mode": "MUTED"}


@pytest.mark.asyncio
async def test_online_count(registry):
    """online_count reflects current online device count."""
    assert registry.online_count == 0
    await registry.device_registered(
        device_id="count-1",
        device_type="oi-stick",
        session_id="s1",
        capabilities={},
        resume_token=None,
        nonce=None,
    )
    assert registry.online_count == 1
    await registry.device_registered(
        device_id="count-2",
        device_type="oi-stick",
        session_id="s2",
        capabilities={},
        resume_token=None,
        nonce=None,
    )
    assert registry.online_count == 2
    registry.device_disconnected("count-1")
    assert registry.online_count == 1


# ------------------------------------------------------------------
# Registry events emitted on event bus
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_registry_emits_device_online_event(registry, event_bus):
    """device_registered emits registry.device_online on the event bus."""
    received = []

    def handler(event_type, device_id, payload):
        received.append((event_type, device_id, payload))

    event_bus.subscribe(handler)
    try:
        await registry.device_registered(
            device_id="evt-online",
            device_type="oi-stick",
            session_id="sess_evto",
            capabilities={},
            resume_token=None,
            nonce=None,
        )
        assert len(received) == 1
        evt_type, dev_id, payload = received[0]
        assert evt_type == REGISTRY_DEVICE_ONLINE
        assert dev_id == "evt-online"
        assert payload["device_id"] == "evt-online"
    finally:
        event_bus.unsubscribe(handler)


@pytest.mark.asyncio
async def test_registry_emits_device_offline_event(registry, event_bus):
    """device_disconnected emits registry.device_offline on the event bus."""
    await registry.device_registered(
        device_id="evt-offline",
        device_type="oi-stick",
        session_id="sess_evtoff",
        capabilities={},
        resume_token=None,
        nonce=None,
    )
    received = []

    def handler(event_type, device_id, payload):
        received.append((event_type, device_id, payload))

    event_bus.subscribe(handler)
    try:
        registry.device_disconnected("evt-offline")
        assert len(received) == 1
        evt_type, dev_id, payload = received[0]
        assert evt_type == REGISTRY_DEVICE_OFFLINE
        assert dev_id == "evt-offline"
    finally:
        event_bus.unsubscribe(handler)


@pytest.mark.asyncio
async def test_registry_emits_state_updated_event(registry, event_bus):
    """device_state_update emits registry.state_updated on the event bus."""
    await registry.device_registered(
        device_id="evt-state",
        device_type="oi-stick",
        session_id="sess_evts",
        capabilities={},
        resume_token=None,
        nonce=None,
    )
    received = []

    def handler(event_type, device_id, payload):
        received.append((event_type, device_id, payload))

    event_bus.subscribe(handler)
    try:
        await registry.device_state_update("evt-state", {"mode": "THINKING", "battery_percent": 95})
        assert len(received) == 1
        evt_type, dev_id, payload = received[0]
        assert evt_type == REGISTRY_STATE_UPDATED
        assert dev_id == "evt-state"
        assert payload["state"]["mode"] == "THINKING"
    finally:
        event_bus.unsubscribe(handler)


# ------------------------------------------------------------------
# DeviceStore unit tests (sync API)
# ------------------------------------------------------------------

def test_store_upsert_and_get_device(store):
    """upsert_device stores; get_device retrieves."""
    info = DeviceInfo(
        device_id="store-001",
        device_type="oi-stick",
        session_id="sess_store",
        connected_at=None,
        last_seen=None,
        capabilities={"input": ["hold_to_record"]},
        resume_token=None,
        nonce=None,
        state={},
        audio_cache_bytes=0,
        muted_until=None,
    )
    store.upsert_device(info)
    retrieved = store.get_device("store-001")
    assert retrieved is not None
    assert retrieved.device_id == "store-001"
    assert retrieved.device_type == "oi-stick"


def test_store_update_state(store):
    """update_state persists state dict."""
    info = DeviceInfo(
        device_id="store-002",
        device_type="oi-stick",
        session_id="sess_s2",
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
    store.update_state("store-002", {"mode": "THINKING", "battery_percent": 75})
    retrieved = store.get_device("store-002")
    assert retrieved.state == {"mode": "THINKING", "battery_percent": 75}


def test_store_get_all_devices(store):
    """get_all_devices returns all stored devices."""
    for i in range(3):
        info = DeviceInfo(
            device_id=f"store-all-{i}",
            device_type="oi-stick",
            session_id=f"sess_{i}",
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
    all_devs = store.get_all_devices()
    assert len(all_devs) == 3


def test_store_remove_device(store):
    """remove_device deletes the device from DB."""
    info = DeviceInfo(
        device_id="store-remove",
        device_type="oi-stick",
        session_id="sess_sr",
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
    assert store.get_device("store-remove") is not None
    store.remove_device("store-remove")
    assert store.get_device("store-remove") is None


def test_store_device_seen(store):
    """device_seen updates last_seen timestamp."""
    info = DeviceInfo(
        device_id="store-seen",
        device_type="oi-stick",
        session_id="sess_ss",
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
    store.device_seen("store-seen")
    retrieved = store.get_device("store-seen")
    assert retrieved.last_seen is not None


# ------------------------------------------------------------------
# Async API tests (DeviceStore async wrappers)
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_store_async_upsert_and_get(tmp_db):
    """upsert_device_async + get_device_async round-trip."""
    store = DeviceStore(tmp_db)
    try:
        info = DeviceInfo(
            device_id="async-001",
            device_type="oi-stick",
            session_id="sess_async",
            connected_at=None,
            last_seen=None,
            capabilities={"input": ["hold_to_record"]},
            resume_token=None,
            nonce=None,
            state={},
            audio_cache_bytes=0,
            muted_until=None,
        )
        await store.upsert_device_async(info)
        retrieved = await store.get_device_async("async-001")
        assert retrieved is not None
        assert retrieved.device_id == "async-001"
    finally:
        store.close()


@pytest.mark.asyncio
async def test_store_async_update_state(tmp_db):
    """update_state_async persists state dict."""
    store = DeviceStore(tmp_db)
    try:
        info = DeviceInfo(
            device_id="async-state-001",
            device_type="oi-stick",
            session_id="sess_as",
            connected_at=None,
            last_seen=None,
            capabilities={},
            resume_token=None,
            nonce=None,
            state={},
            audio_cache_bytes=0,
            muted_until=None,
        )
        await store.upsert_device_async(info)
        await store.update_state_async("async-state-001", {"mode": "THINKING", "battery_percent": 75})
        retrieved = await store.get_device_async("async-state-001")
        assert retrieved.state == {"mode": "THINKING", "battery_percent": 75}
    finally:
        store.close()


# ------------------------------------------------------------------
# Integration tests: DATPServer + RegistryService via oi-sim
# ------------------------------------------------------------------

from .test_utils import make_hello


def make_state_report(device_id: str) -> dict:
    return {
        "v": "datp",
        "type": "state",
        "id": f"state_{device_id}",
        "device_id": device_id,
        "ts": "2026-04-27T04:40:01.000Z",
        "payload": {
            "mode": "THINKING",
            "battery_percent": 88,
            "charging": False,
            "wifi_rssi": -60,
            "heap_free": 180000,
            "uptime_s": 3600,
            "audio_cache_used_bytes": 0,
            "muted_until": None,
        },
    }


@pytest.mark.asyncio
async def test_integration_device_registered_creates_entry(server_with_registry):
    """oi-sim connects → registry entry is created."""
    srv = server_with_registry
    device_id = "sim-reg-001"

    async with websockets.connect(f"ws://localhost:{srv.port}/datp") as ws:
        await ws.send(json.dumps(make_hello(device_id)))
        resp_raw = await asyncio.wait_for(ws.recv(), timeout=5.0)

    resp = json.loads(resp_raw)
    assert resp["type"] == "hello_ack"
    assert resp["payload"]["session_id"]

    # Registry has the device
    info = await srv.registry.get_device(device_id)
    assert info is not None
    assert info.device_id == device_id
    assert info.device_type == "oi-stick"
    assert info.capabilities["input"] == ["hold_to_record"]


@pytest.mark.asyncio
async def test_integration_device_disconnected_marks_offline(server_with_registry):
    """oi-sim disconnects → registry marks device offline but keeps DB entry."""
    srv = server_with_registry
    device_id = "sim-reg-002"

    # Inside the async with: device is connected and online.
    async with websockets.connect(f"ws://localhost:{srv.port}/datp") as ws:
        await ws.send(json.dumps(make_hello(device_id)))
        await asyncio.wait_for(ws.recv(), timeout=5.0)
        await asyncio.sleep(0.05)
        # Device is online while connected.
        assert len(srv.registry.get_online_devices()) == 1

    # After the with block exits, give the server a moment to process the
    # close handshake and run the disconnect callback.
    await asyncio.sleep(0.1)
    assert len(srv.registry.get_online_devices()) == 0
    # But the DB record is still there — queryable after disconnect.
    assert await srv.registry.get_device(device_id) is not None


@pytest.mark.asyncio
async def test_integration_device_state_update(server_with_registry):
    """oi-sim sends state → registry stores it."""
    srv = server_with_registry
    device_id = "sim-reg-003"

    async with websockets.connect(f"ws://localhost:{srv.port}/datp") as ws:
        await ws.send(json.dumps(make_hello(device_id)))
        await asyncio.wait_for(ws.recv(), timeout=5.0)
        await ws.send(json.dumps(make_state_report(device_id)))
        await asyncio.sleep(0.3)

    info = await srv.registry.get_device(device_id)
    assert info is not None
    assert info.state["mode"] == "THINKING"
    assert info.state["battery_percent"] == 88


@pytest.mark.asyncio
async def test_integration_get_online_devices(server_with_registry):
    """Two sims connect; one disconnects; only one in online list."""
    srv = server_with_registry

    # Connect first sim
    async with websockets.connect(f"ws://localhost:{srv.port}/datp") as ws_a:
        await ws_a.send(json.dumps(make_hello("sim-online-a")))
        await asyncio.wait_for(ws_a.recv(), timeout=5.0)

        # Connect second sim
        async with websockets.connect(f"ws://localhost:{srv.port}/datp") as ws_b:
            await ws_b.send(json.dumps(make_hello("sim-online-b")))
            await asyncio.wait_for(ws_b.recv(), timeout=5.0)

            assert len(srv.registry.get_online_devices()) == 2

        # ws_b closed, wait for cleanup
        await asyncio.sleep(0.2)

    # ws_a closed
    await asyncio.sleep(0.2)
    assert len(srv.registry.get_online_devices()) == 0


@pytest.mark.asyncio
async def test_integration_capabilities_stored(server_with_registry):
    """hello with capabilities → stored and queryable."""
    srv = server_with_registry
    device_id = "sim-reg-cap"

    caps = {
        "input": ["hold_to_record", "double_tap"],
        "output": ["tiny_screen", "cached_audio"],
        "commands_supported": ["display.show_status", "audio.play"],
    }

    async with websockets.connect(f"ws://localhost:{srv.port}/datp") as ws:
        hello = make_hello(device_id)
        hello["payload"]["capabilities"] = caps
        await ws.send(json.dumps(hello))
        await asyncio.wait_for(ws.recv(), timeout=5.0)
        # Small sleep to allow async persistence to complete
        await asyncio.sleep(0.1)

    stored_caps = srv.registry.get_capabilities(device_id)
    assert stored_caps == caps


@pytest.mark.asyncio
async def test_integration_offline_device_still_queryable(server_with_registry):
    """After disconnect, get_device returns full info from DB."""
    srv = server_with_registry
    device_id = "sim-reg-offline"

    async with websockets.connect(f"ws://localhost:{srv.port}/datp") as ws:
        await ws.send(json.dumps(make_hello(device_id)))
        await asyncio.wait_for(ws.recv(), timeout=5.0)
        await ws.send(json.dumps(make_state_report(device_id)))
        await asyncio.sleep(0.3)

    # Confirm info is stored
    assert await srv.registry.get_device(device_id) is not None

    # Connection drops
    await asyncio.sleep(0.1)

    # Still queryable
    info = await srv.registry.get_device(device_id)
    assert info is not None
    assert info.device_id == device_id
    assert info.state["mode"] == "THINKING"