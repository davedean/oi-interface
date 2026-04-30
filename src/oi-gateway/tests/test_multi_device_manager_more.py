from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from multi_device.manager import (
    DeviceAffinity,
    DeviceLoad,
    LoadBalancer,
    LoadBalancerConfig,
    LoadBalanceStrategy,
    MultiDeviceManager,
    get_multi_device_manager,
    reset_multi_device_manager,
)


def test_load_balancer_weighted_random_affinity_and_default_paths():
    lb = LoadBalancer(LoadBalancerConfig(strategy=LoadBalanceStrategy.WEIGHTED, max_load_threshold=0.9))
    lb.update_load("a", DeviceLoad(device_id="a", cpu_load=0.9, memory_load=0.9, network_load=0.9))
    lb.update_load("b", DeviceLoad(device_id="b", cpu_load=0.0, memory_load=0.0, network_load=0.0))
    with patch("random.random", return_value=0.0):
        assert lb.select_device(["a", "b"]) == "b"

    lb = LoadBalancer(LoadBalancerConfig(strategy=LoadBalanceStrategy.AFFINITY, affinity_weight=0.0))
    affinities = {"a": [DeviceAffinity(source_id="a", target_id="b", strength=0.9)]}
    assert lb.select_device(["a", "b"], affinities=affinities) == "a"
    assert lb.select_device(["a", "b"], affinities=None) in {"a", "b"}

    lb = LoadBalancer(LoadBalancerConfig(strategy=LoadBalanceStrategy.RANDOM))
    with patch("random.choice", return_value="b"):
        assert lb.select_device(["a", "b"]) == "b"

    lb._config.strategy = "unknown"  # type: ignore[assignment]
    assert lb.select_device(["a", "b"]) in {"a", "b"}


def test_singleton_and_manager_affinity_group_load_and_summary_paths():
    reset_multi_device_manager()
    manager = get_multi_device_manager()
    assert manager is get_multi_device_manager()
    reset_multi_device_manager()

    events = []
    event_bus = MagicMock()
    event_bus.emit.side_effect = lambda event_type, subject, payload: events.append((event_type, subject, payload))
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    manager = MultiDeviceManager(event_bus=event_bus, get_current_time=lambda: now)

    affinity = manager.set_affinity("user", "dev1", expires_seconds=30, reason="preferred")
    assert affinity.expires_at is not None
    assert manager.remove_affinity("missing", "dev1") is False
    manager.set_affinity("dev2", "dev1", strength=0.8)
    manager._load_balancer.select_device = MagicMock(return_value="dev1")
    assert manager.get_best_device_for_task("voice", ["dev1", "dev2"], user_id="user") == "dev1"

    group = manager.create_group("g1", "Group 1", device_ids=["dev1"])
    assert manager.broadcast_to_group("missing", {"x": 1}) == {"error": "Group not found: missing"}
    assert manager.broadcast_to_group("g1", {"x": 1}) == {"dev1": {"status": "sent", "message": {"x": 1}}}

    manager.update_device_load("dev1", cpu_load=0.2)
    manager.update_device_load("dev2", cpu_load=0.1)
    assert manager.get_least_loaded_device(["dev1", "dev2"], max_load=0.9) == "dev2"
    assert manager.get_least_loaded_device(["dev1"], max_load=0.05) is None

    results = manager.distribute_task("task-1", ["dev1", "dev2"], {"kind": "tts"})
    assert results["dev1"]["status"] == "dispatched"

    summary = manager.get_state_summary()
    assert summary["affinity_count"] >= 2
    assert summary["group_count"] == 1
    assert summary["tracked_devices"] == 2
    assert summary["load_balancer_strategy"] == "least_loaded"
    assert events
