"""Tests for multi_device manager module."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from multi_device.manager import (
    MultiDeviceManager,
    DeviceAffinity,
    DeviceGroup,
    DeviceLoad,
    LoadBalancer,
    LoadBalancerConfig,
    LoadBalanceStrategy,
    get_multi_device_manager,
    reset_multi_device_manager,
)
from multi_device.clustering import ClusterStrategy


class TestDeviceAffinity:
    """Tests for DeviceAffinity dataclass."""

    def test_defaults(self):
        """Test default values."""
        affinity = DeviceAffinity(
            source_id="user-001",
            target_id="stick-001",
        )
        assert affinity.source_id == "user-001"
        assert affinity.target_id == "stick-001"
        assert affinity.strength == 1.0
        assert isinstance(affinity.created_at, datetime)
        assert affinity.expires_at is None
        assert affinity.reason == ""

    def test_with_expiry(self):
        """Test affinity with expiry."""
        expires = datetime.now(timezone.utc) + timedelta(hours=1)
        affinity = DeviceAffinity(
            source_id="user-001",
            target_id="stick-001",
            expires_at=expires,
        )
        assert affinity.expires_at is not None


class TestDeviceGroup:
    """Tests for DeviceGroup dataclass."""

    def test_defaults(self):
        """Test default values."""
        group = DeviceGroup(
            group_id="group-1",
            name="Test Group",
        )
        assert group.group_id == "group-1"
        assert group.name == "Test Group"
        assert group.description == ""
        assert group.device_ids == []
        assert group.metadata == {}

    def test_add_device(self):
        """Test adding device to group."""
        group = DeviceGroup(
            group_id="group-1",
            name="Test",
        )
        result = group.add_device("stick-001")
        assert result is True
        assert "stick-001" in group.device_ids

    def test_add_device_no_duplicate(self):
        """Test duplicate device not added."""
        group = DeviceGroup(
            group_id="group-1",
            name="Test",
            device_ids=["stick-001"],
        )
        result = group.add_device("stick-001")
        assert result is False
        assert len(group.device_ids) == 1

    def test_remove_device(self):
        """Test removing device from group."""
        group = DeviceGroup(
            group_id="group-1",
            name="Test",
            device_ids=["stick-001", "stick-002"],
        )
        result = group.remove_device("stick-001")
        assert result is True
        assert "stick-001" not in group.device_ids
        assert "stick-002" in group.device_ids

    def test_remove_device_not_found(self):
        """Test removing non-existent device."""
        group = DeviceGroup(
            group_id="group-1",
            name="Test",
            device_ids=["stick-001"],
        )
        result = group.remove_device("stick-002")
        assert result is False


class TestDeviceLoad:
    """Tests for DeviceLoad dataclass."""

    def test_defaults(self):
        """Test default values."""
        load = DeviceLoad(device_id="stick-001")
        assert load.device_id == "stick-001"
        assert load.active_operations == 0
        assert load.queued_operations == 0
        assert load.cpu_load == 0.0
        assert load.memory_load == 0.0
        assert load.network_load == 0.0
        assert isinstance(load.last_updated, datetime)

    def test_total_load(self):
        """Test total load calculation."""
        load = DeviceLoad(
            device_id="stick-001",
            cpu_load=0.3,
            memory_load=0.6,
            network_load=0.3,
        )
        expected = (0.3 + 0.6 + 0.3) / 3.0
        assert load.total_load == expected


class TestLoadBalancerConfig:
    """Tests for LoadBalancerConfig."""

    def test_defaults(self):
        """Test default values."""
        config = LoadBalancerConfig()
        assert config.strategy == LoadBalanceStrategy.LEAST_LOADED
        assert config.max_load_threshold == 0.9
        assert config.min_load_threshold == 0.1
        assert config.affinity_weight == 0.3
        assert config.enable_failover is True
        assert config.failover_timeout == 30.0


class TestLoadBalancer:
    """Tests for LoadBalancer class."""

    def test_defaults(self):
        """Test default configuration."""
        lb = LoadBalancer()
        assert isinstance(lb._config, LoadBalancerConfig)

    def test_update_load(self):
        """Test updating device load."""
        lb = LoadBalancer()
        load = DeviceLoad(
            device_id="stick-001",
            cpu_load=0.5,
            memory_load=0.3,
            network_load=0.2,
        )
        lb.update_load("stick-001", load)

        retrieved = lb.get_load("stick-001")
        assert retrieved is not None
        assert retrieved.cpu_load == 0.5

    def test_get_load_unknown_device(self):
        """Test getting load for unknown device."""
        lb = LoadBalancer()
        result = lb.get_load("unknown")
        assert result is None

    def test_select_device_round_robin(self):
        """Test round-robin selection."""
        config = LoadBalancerConfig(strategy=LoadBalanceStrategy.ROUND_ROBIN)
        lb = LoadBalancer(config)
        devices = ["a", "b", "c"]

        selected1 = lb.select_device(devices)
        selected2 = lb.select_device(devices)
        selected3 = lb.select_device(devices)
        selected4 = lb.select_device(devices)

        # Should cycle through
        assert selected1 != selected2 != selected3
        assert selected4 == selected1  # Wrapped around

    def test_select_device_least_loaded(self):
        """Test least loaded selection."""
        config = LoadBalancerConfig(strategy=LoadBalanceStrategy.LEAST_LOADED)
        lb = LoadBalancer(config)

        # Add load to devices
        lb.update_load("stick-001", DeviceLoad(device_id="stick-001", cpu_load=0.5))
        lb.update_load("stick-002", DeviceLoad(device_id="stick-002", cpu_load=0.1))  # Lowest
        lb.update_load("stick-003", DeviceLoad(device_id="stick-003", cpu_load=0.8))

        devices = ["stick-001", "stick-002", "stick-003"]
        selected = lb.select_device(devices)

        assert selected == "stick-002"  # Should select lowest load

    def test_select_device_preferred_first(self):
        """Test that preferred device is selected first if load allows."""
        lb = LoadBalancer()

        lb.update_load("stick-001", DeviceLoad(device_id="stick-001", cpu_load=0.8))
        lb.update_load("stick-002", DeviceLoad(device_id="stick-002", cpu_load=0.5))

        devices = ["stick-001", "stick-002"]
        selected = lb.select_device(devices, preferred_device="stick-002")

        assert selected == "stick-002"

    def test_select_device_empty_list(self):
        """Test selecting from empty list."""
        lb = LoadBalancer()
        result = lb.select_device([])
        assert result is None

    def test_select_device_all_overloaded(self):
        """Test selection when all devices overloaded."""
        config = LoadBalancerConfig(max_load_threshold=0.5)
        lb = LoadBalancer(config)

        lb.update_load("stick-001", DeviceLoad(device_id="stick-001", cpu_load=0.8))
        lb.update_load("stick-002", DeviceLoad(device_id="stick-002", cpu_load=0.9))

        devices = ["stick-001", "stick-002"]
        selected = lb.select_device(devices)

        # Should still return one (unknown load treated as available)
        assert selected in devices


class TestMultiDeviceManager:
    """Tests for MultiDeviceManager class."""

    def setup_method(self):
        """Reset singleton before each test."""
        reset_multi_device_manager()

    def test_initial_state(self):
        """Test initial manager state."""
        manager = MultiDeviceManager()
        assert len(manager._affinities) == 0
        assert len(manager._groups) == 0

    # Affinity tests
    def test_set_affinity(self):
        """Test setting affinity."""
        manager = MultiDeviceManager()
        affinity = manager.set_affinity(
            source_id="user-001",
            target_id="stick-001",
            strength=0.8,
            reason="preferred",
        )

        assert affinity.source_id == "user-001"
        assert affinity.target_id == "stick-001"
        assert affinity.strength == 0.8
        assert affinity.reason == "preferred"

    def test_get_affinities(self):
        """Test getting affinities."""
        manager = MultiDeviceManager()
        manager.set_affinity("user-001", "stick-001")
        manager.set_affinity("user-001", "stick-002")

        affinities = manager.get_affinities("user-001")
        assert len(affinities) == 2

    def test_get_affinity_for_target(self):
        """Test getting specific affinity."""
        manager = MultiDeviceManager()
        manager.set_affinity("user-001", "stick-001")

        affinity = manager.get_affinity_for_target("user-001", "stick-001")
        assert affinity is not None
        assert affinity.target_id == "stick-001"

    def test_get_affinity_for_target_not_found(self):
        """Test getting non-existent affinity."""
        manager = MultiDeviceManager()
        manager.set_affinity("user-001", "stick-001")

        affinity = manager.get_affinity_for_target("user-001", "stick-999")
        assert affinity is None

    def test_remove_affinity(self):
        """Test removing affinity."""
        manager = MultiDeviceManager()
        manager.set_affinity("user-001", "stick-001")
        manager.set_affinity("user-001", "stick-002")

        result = manager.remove_affinity("user-001", "stick-001")
        assert result is True

        affinities = manager.get_affinities("user-001")
        assert len(affinities) == 1
        assert affinities[0].target_id == "stick-002"

    def test_get_best_device_for_task(self):
        """Test getting best device for task."""
        manager = MultiDeviceManager()
        manager.update_device_load("stick-001", cpu_load=0.5)
        manager.update_device_load("stick-002", cpu_load=0.2)

        best = manager.get_best_device_for_task(
            task_type="voice_input",
            available_devices=["stick-001", "stick-002"],
        )

        # Should select stick-002 (lowest load)
        assert best == "stick-002"

    # Group tests
    def test_create_group(self):
        """Test creating device group."""
        manager = MultiDeviceManager()
        group = manager.create_group(
            group_id="home-devices",
            name="Home Devices",
            description="Devices at home",
        )

        assert group.group_id == "home-devices"
        assert group.name == "Home Devices"

        retrieved = manager.get_group("home-devices")
        assert retrieved is group

    def test_get_all_groups(self):
        """Test getting all groups."""
        manager = MultiDeviceManager()
        manager.create_group("group-1", "Group 1")
        manager.create_group("group-2", "Group 2")

        groups = manager.get_all_groups()
        assert len(groups) == 2

    def test_add_to_group(self):
        """Test adding device to group."""
        manager = MultiDeviceManager()
        manager.create_group("group-1", "Group 1")

        result = manager.add_to_group("group-1", "stick-001")
        assert result is True

        group = manager.get_group("group-1")
        assert "stick-001" in group.device_ids

    def test_add_to_nonexistent_group(self):
        """Test adding to non-existent group."""
        manager = MultiDeviceManager()
        result = manager.add_to_group("nonexistent", "stick-001")
        assert result is False

    def test_remove_from_group(self):
        """Test removing device from group."""
        manager = MultiDeviceManager()
        manager.create_group("group-1", "Group 1")
        manager.add_to_group("group-1", "stick-001")

        result = manager.remove_from_group("group-1", "stick-001")
        assert result is True

        group = manager.get_group("group-1")
        assert "stick-001" not in group.device_ids

    def test_delete_group(self):
        """Test deleting group."""
        manager = MultiDeviceManager()
        manager.create_group("group-1", "Group 1")

        result = manager.delete_group("group-1")
        assert result is True

        assert manager.get_group("group-1") is None

    def test_get_groups_for_device(self):
        """Test getting groups for a device."""
        manager = MultiDeviceManager()
        manager.create_group("group-1", "Group 1")
        manager.create_group("group-2", "Group 2")
        manager.add_to_group("group-1", "stick-001")
        manager.add_to_group("group-2", "stick-001")

        groups = manager.get_groups_for_device("stick-001")
        assert len(groups) == 2

    # Load tests
    def test_update_device_load(self):
        """Test updating device load."""
        manager = MultiDeviceManager()
        manager.update_device_load(
            device_id="stick-001",
            active_operations=2,
            cpu_load=0.5,
        )

        load = manager.get_device_load("stick-001")
        assert load is not None
        assert load.active_operations == 2
        assert load.cpu_load == 0.5

    def test_get_all_loads(self):
        """Test getting all load metrics."""
        manager = MultiDeviceManager()
        manager.update_device_load("stick-001")
        manager.update_device_load("stick-002")

        loads = manager.get_all_loads()
        assert len(loads) == 2

    def test_get_least_loaded_device(self):
        """Test getting least loaded device."""
        manager = MultiDeviceManager()
        manager.update_device_load("stick-001", cpu_load=0.7)
        manager.update_device_load("stick-002", cpu_load=0.2)

        result = manager.get_least_loaded_device(["stick-001", "stick-002"])
        assert result == "stick-002"

    def test_get_least_loaded_device_max_load_filter(self):
        """Test max load filter."""
        manager = MultiDeviceManager()
        manager.update_device_load("stick-001", cpu_load=0.9)
        manager.update_device_load("stick-002", cpu_load=0.5)

        result = manager.get_least_loaded_device(
            ["stick-001", "stick-002"],
            max_load=0.6,
        )
        # Only stick-002 is under 0.6
        assert result == "stick-002"

    # Multi-device operations
    def test_distribute_task(self):
        """Test distributing task across devices."""
        manager = MultiDeviceManager()
        results = manager.distribute_task(
            task_id="task-001",
            device_ids=["stick-001", "stick-002"],
            task_data={"action": "display"},
        )

        assert len(results) == 2
        assert "stick-001" in results
        assert "stick-002" in results

    def test_broadcast_to_group(self):
        """Test broadcasting to group."""
        manager = MultiDeviceManager()
        manager.create_group("group-1", "Group 1")
        manager.add_to_group("group-1", "stick-001")
        manager.add_to_group("group-1", "stick-002")

        results = manager.broadcast_to_group(
            group_id="group-1",
            message={"type": "display_update"},
        )

        assert len(results) == 2

    def test_broadcast_to_nonexistent_group(self):
        """Test broadcasting to non-existent group."""
        manager = MultiDeviceManager()
        result = manager.broadcast_to_group("nonexistent", {})

        assert "error" in result

    def test_get_state_summary(self):
        """Test getting state summary."""
        manager = MultiDeviceManager()
        manager.create_group("group-1", "Group 1")
        manager.set_affinity("user-001", "stick-001")
        manager.update_device_load("stick-001")

        summary = manager.get_state_summary()

        assert summary["affinity_count"] == 1
        assert summary["group_count"] == 1
        assert summary["tracked_devices"] == 1


class TestGetMultiDeviceManager:
    """Tests for get_multi_device_manager singleton."""

    def setup_method(self):
        reset_multi_device_manager()

    def test_returns_singleton(self):
        """Test singleton is returned."""
        manager1 = get_multi_device_manager()
        manager2 = get_multi_device_manager()

        assert manager1 is manager2

    def test_singleton_is_multi_device_manager(self):
        """Test singleton type."""
        manager = get_multi_device_manager()
        assert isinstance(manager, MultiDeviceManager)


class TestMultiDeviceManagerEdgeCases:
    """Edge case tests for MultiDeviceManager."""

    def setup_method(self):
        reset_multi_device_manager()

    def test_set_affinity_replaces_existing(self):
        """Test that setting affinity replaces existing to same target."""
        manager = MultiDeviceManager()
        manager.set_affinity("user-001", "stick-001", strength=0.5)
        manager.set_affinity("user-001", "stick-001", strength=0.9)

        affinities = manager.get_affinities("user-001")
        assert len(affinities) == 1
        assert affinities[0].strength == 0.9

    def test_set_affinity_with_expiry(self):
        """Test affinity with expiration."""
        manager = MultiDeviceManager()
        affinity = manager.set_affinity(
            "user-001",
            "stick-001",
            expires_seconds=3600,
        )
        assert affinity.expires_at is not None

    def test_get_all_groups_empty(self):
        """Test get_all_groups when no groups."""
        manager = MultiDeviceManager()
        groups = manager.get_all_groups()
        assert groups == []

    def test_remove_from_nonexistent_group(self):
        """Test removing from non-existent group."""
        manager = MultiDeviceManager()
        result = manager.remove_from_group("nonexistent", "stick-001")
        assert result is False

    def test_delete_nonexistent_group(self):
        """Test deleting non-existent group."""
        manager = MultiDeviceManager()
        result = manager.delete_group("nonexistent")
        assert result is False

    def test_get_device_load_unknown(self):
        """Test getting load for unknown device."""
        manager = MultiDeviceManager()
        load = manager.get_device_load("unknown")
        assert load is None