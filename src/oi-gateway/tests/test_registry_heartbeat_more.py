from __future__ import annotations

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from registry.heartbeat import HeartbeatMonitor
from registry.models import DeviceInfo
from utils import utcnow


@pytest.fixture
def store_and_device():
    info = DeviceInfo(
        device_id="dev1",
        device_type="speaker",
        session_id="sess1",
        connected_at=utcnow(),
        last_seen=utcnow(),
        capabilities={},
        resume_token=None,
        nonce=None,
        state={},
        audio_cache_bytes=0,
        muted_until=None,
        heartbeat_timeout=1.0,
    )
    store = MagicMock()
    store.get_device.return_value = info
    return store, info


@pytest.mark.asyncio
async def test_heartbeat_start_stop_and_remove_device(store_and_device):
    store, info = store_and_device
    registry = SimpleNamespace(_store=store)
    event_bus = MagicMock()
    monitor = HeartbeatMonitor(registry, event_bus, check_interval=0.01)

    await monitor.start()
    first_task = monitor._task
    await monitor.start()
    assert monitor._task is first_task
    monitor.record_heartbeat("dev1")
    assert monitor.is_device_tracked("dev1") is True
    monitor.remove_device("dev1")
    assert monitor.is_device_tracked("dev1") is False
    await monitor.stop()
    assert monitor._task is None


def test_heartbeat_check_health_and_marking(store_and_device):
    store, info = store_and_device
    registry = SimpleNamespace(_store=store)
    event_bus = MagicMock()
    monitor = HeartbeatMonitor(registry, event_bus, check_interval=1.0)

    stale = utcnow() - timedelta(seconds=5)
    with patch("registry.heartbeat.utcnow", return_value=stale + timedelta(seconds=5)):
        monitor._heartbeats["dev1"] = stale
        monitor.check_health()

    assert monitor.is_device_unhealthy("dev1") is True
    event_bus.emit.assert_called_once()
    assert info.is_healthy is False
    store.upsert_device.assert_called()

    monitor.record_heartbeat("dev1")
    assert monitor.is_device_unhealthy("dev1") is False
    assert info.is_healthy is True


@pytest.mark.asyncio
async def test_heartbeat_monitor_loop_handles_check_and_exception(store_and_device):
    store, info = store_and_device
    registry = SimpleNamespace(_store=store)
    event_bus = MagicMock()
    monitor = HeartbeatMonitor(registry, event_bus, check_interval=0.01)

    called = []

    def fake_check_health():
        called.append(True)
        monitor._cancelled = True

    monitor.check_health = fake_check_health
    await monitor._monitor_loop()
    assert called == [True]

    monitor = HeartbeatMonitor(registry, event_bus, check_interval=0.01)
    async def fake_sleep(_interval):
        monitor._cancelled = True
        raise RuntimeError("boom")

    with patch("registry.heartbeat.asyncio.sleep", side_effect=fake_sleep):
        await monitor._monitor_loop()
