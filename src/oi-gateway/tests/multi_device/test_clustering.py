"""Tests for multi_device module - clustering and grouping."""
from __future__ import annotations

import pytest

from multi_device.clustering import (
    DeviceCluster,
    ClusterStrategy,
    group_by_capability,
    group_by_location,
    group_by_type,
    cluster_devices,
    find_cluster_for_device,
    merge_clusters,
)


class TestDeviceCluster:
    """Tests for DeviceCluster dataclass."""

    def test_defaults(self):
        """Test default values."""
        cluster = DeviceCluster(
            cluster_id="test-1",
            name="Test Cluster",
            strategy=ClusterStrategy.TYPE,
        )
        assert cluster.cluster_id == "test-1"
        assert cluster.name == "Test Cluster"
        assert cluster.strategy == ClusterStrategy.TYPE
        assert cluster.device_ids == []
        assert cluster.attributes == {}
        assert cluster.metadata == {}

    def test_size_property(self):
        """Test size property."""
        cluster = DeviceCluster(
            cluster_id="test-1",
            name="Test",
            strategy=ClusterStrategy.TYPE,
            device_ids=["a", "b", "c"],
        )
        assert cluster.size == 3

    def test_is_empty_property(self):
        """Test is_empty property."""
        empty_cluster = DeviceCluster(
            cluster_id="test-1",
            name="Empty",
            strategy=ClusterStrategy.TYPE,
        )
        assert empty_cluster.is_empty is True

        non_empty = DeviceCluster(
            cluster_id="test-2",
            name="Non-empty",
            strategy=ClusterStrategy.TYPE,
            device_ids=["a"],
        )
        assert non_empty.is_empty is False

    def test_add_device(self):
        """Test adding device to cluster."""
        cluster = DeviceCluster(
            cluster_id="test-1",
            name="Test",
            strategy=ClusterStrategy.TYPE,
        )
        cluster.add_device("stick-001")
        assert "stick-001" in cluster.device_ids

    def test_add_device_no_duplicate(self):
        """Test that duplicate devices are not added."""
        cluster = DeviceCluster(
            cluster_id="test-1",
            name="Test",
            strategy=ClusterStrategy.TYPE,
            device_ids=["stick-001"],
        )
        cluster.add_device("stick-001")
        assert cluster.device_ids.count("stick-001") == 1

    def test_remove_device(self):
        """Test removing device from cluster."""
        cluster = DeviceCluster(
            cluster_id="test-1",
            name="Test",
            strategy=ClusterStrategy.TYPE,
            device_ids=["stick-001", "stick-002"],
        )
        result = cluster.remove_device("stick-001")
        assert result is True
        assert "stick-001" not in cluster.device_ids

    def test_remove_device_not_found(self):
        """Test removing non-existent device."""
        cluster = DeviceCluster(
            cluster_id="test-1",
            name="Test",
            strategy=ClusterStrategy.TYPE,
            device_ids=["stick-001"],
        )
        result = cluster.remove_device("stick-002")
        assert result is False

    def test_has_device(self):
        """Test has_device method."""
        cluster = DeviceCluster(
            cluster_id="test-1",
            name="Test",
            strategy=ClusterStrategy.TYPE,
            device_ids=["stick-001"],
        )
        assert cluster.has_device("stick-001") is True
        assert cluster.has_device("stick-002") is False


class TestGroupByCapability:
    """Tests for group_by_capability function."""

    def test_groups_by_capability(self):
        """Test basic capability grouping."""
        devices = {
            "stick-001": {"max_spoken_seconds": 12},
            "stick-002": {"max_spoken_seconds": 12},
            "pi-screen": {"max_spoken_seconds": 120},
        }
        result = group_by_capability(devices, "max_spoken_seconds")

        assert "12" in result
        assert "120" in result
        assert "stick-001" in result["12"]
        assert "stick-002" in result["12"]
        assert "pi-screen" in result["120"]

    def test_groups_devices_without_capability(self):
        """Test devices without the capability."""
        devices = {
            "stick-001": {"max_spoken_seconds": 12},
            "stick-002": {},  # No capability
        }
        result = group_by_capability(devices, "max_spoken_seconds")

        assert "12" in result
        assert "none" in result
        assert "stick-002" in result["none"]

    def test_empty_devices(self):
        """Test with empty device dict."""
        result = group_by_capability({}, "capability")
        assert result == {}


class TestGroupByLocation:
    """Tests for group_by_location function."""

    def test_groups_by_location(self):
        """Test basic location grouping."""
        devices = {
            "stick-001": {"location": "kitchen"},
            "stick-002": {"location": "kitchen"},
            "pi-screen": {"location": "office"},
        }
        result = group_by_location(devices)

        assert "kitchen" in result
        assert "office" in result
        assert "stick-001" in result["kitchen"]
        assert "stick-002" in result["kitchen"]
        assert "pi-screen" in result["office"]

    def test_handles_unknown_location(self):
        """Test devices without location."""
        devices = {
            "stick-001": {"location": "kitchen"},
            "stick-002": {},  # No location
        }
        result = group_by_location(devices)

        assert "unknown" in result
        assert "stick-002" in result["unknown"]

    def test_removes_empty_unknown(self):
        """Test that empty unknown group is removed."""
        devices = {
            "stick-001": {"location": "kitchen"},
        }
        result = group_by_location(devices)

        assert "unknown" not in result


class TestGroupByType:
    """Tests for group_by_type function."""

    def test_groups_by_type(self):
        """Test basic type grouping."""
        devices = {
            "stick-001": {"device_type": "m5stick"},
            "stick-002": {"device_type": "m5stick"},
            "pi-screen": {"device_type": "rpi"},
        }
        result = group_by_type(devices)

        assert "m5stick" in result
        assert "rpi" in result
        assert len(result["m5stick"]) == 2
        assert len(result["rpi"]) == 1

    def test_handles_unknown_type(self):
        """Test devices without type."""
        devices = {
            "stick-001": {"device_type": "m5stick"},
            "stick-002": {},
        }
        result = group_by_type(devices)

        assert "unknown" in result
        assert "stick-002" in result["unknown"]


class TestClusterDevices:
    """Tests for cluster_devices function."""

    def test_cluster_by_type(self):
        """Test clustering by device type."""
        devices = ["stick-001", "stick-002", "pi-screen"]
        info = {
            "stick-001": {"device_type": "m5stick"},
            "stick-002": {"device_type": "m5stick"},
            "pi-screen": {"device_type": "rpi"},
        }
        result = cluster_devices(devices, info, ClusterStrategy.TYPE)

        assert len(result) == 2  # Two clusters

        # Find the clusters
        m5stick_cluster = None
        rpi_cluster = None
        for c in result:
            if "m5stick" in c.name:
                m5stick_cluster = c
            elif "rpi" in c.name:
                rpi_cluster = c

        assert m5stick_cluster is not None
        assert len(m5stick_cluster.device_ids) == 2
        assert rpi_cluster is not None
        assert len(rpi_cluster.device_ids) == 1

    def test_cluster_by_capability(self):
        """Test clustering by capabilities."""
        devices = ["stick-001", "stick-002", "pi-screen"]
        info = {
            "stick-001": {"capabilities": {"audio": True, "display": True}},
            "stick-002": {"capabilities": {"audio": True, "display": True}},
            "pi-screen": {"capabilities": {"audio": True, "display": True, "markdown": True}},
        }
        result = cluster_devices(devices, info, ClusterStrategy.CAPABILITY)

        # Should have at least one cluster
        assert len(result) >= 1

    def test_cluster_by_location(self):
        """Test clustering by location."""
        devices = ["stick-001", "stick-002", "pi-screen"]
        info = {
            "stick-001": {"location": "kitchen"},
            "stick-002": {"location": "kitchen"},
            "pi-screen": {"location": "office"},
        }
        result = cluster_devices(devices, info, ClusterStrategy.LOCATION)

        assert len(result) == 2  # Two locations

    def test_cluster_empty_devices(self):
        """Test clustering with empty device list."""
        result = cluster_devices([], {}, ClusterStrategy.TYPE)
        assert result == []

    def test_cluster_weighted_strategy(self):
        """Test weighted clustering."""
        devices = ["stick-001", "stick-002"]
        info = {
            "stick-001": {"device_type": "m5stick", "location": "kitchen"},
            "stick-002": {"device_type": "m5stick", "location": "office"},
        }
        result = cluster_devices(
            devices,
            info,
            ClusterStrategy.WEIGHTED,
            weights={"type": 0.5, "location": 0.5},
        )

        assert len(result) >= 1


class TestFindClusterForDevice:
    """Tests for find_cluster_for_device function."""

    def test_finds_device_in_cluster(self):
        """Test finding device in cluster."""
        clusters = [
            DeviceCluster(
                cluster_id="c1",
                name="Cluster 1",
                strategy=ClusterStrategy.TYPE,
                device_ids=["a", "b"],
            ),
            DeviceCluster(
                cluster_id="c2",
                name="Cluster 2",
                strategy=ClusterStrategy.TYPE,
                device_ids=["c", "d"],
            ),
        ]
        result = find_cluster_for_device(clusters, "b")
        assert result is not None
        assert result.cluster_id == "c1"

    def test_returns_none_for_unknown(self):
        """Test returns none for unknown device."""
        clusters = [
            DeviceCluster(
                cluster_id="c1",
                name="Cluster 1",
                strategy=ClusterStrategy.TYPE,
                device_ids=["a", "b"],
            ),
        ]
        result = find_cluster_for_device(clusters, "z")
        assert result is None


class TestMergeClusters:
    """Tests for merge_clusters function."""

    def test_merges_clusters(self):
        """Test merging multiple clusters."""
        clusters = [
            DeviceCluster(
                cluster_id="c1",
                name="Cluster 1",
                strategy=ClusterStrategy.TYPE,
                device_ids=["a", "b"],
            ),
            DeviceCluster(
                cluster_id="c2",
                name="Cluster 2",
                strategy=ClusterStrategy.TYPE,
                device_ids=["c", "d"],
            ),
        ]
        result = merge_clusters(clusters, ["c1", "c2"], "Merged")

        assert result is not None
        assert len(result.device_ids) == 4
        assert "a" in result.device_ids
        assert "d" in result.device_ids

    def test_merges_with_deduplication(self):
        """Test that duplicates are removed."""
        clusters = [
            DeviceCluster(
                cluster_id="c1",
                name="Cluster 1",
                strategy=ClusterStrategy.TYPE,
                device_ids=["a", "b"],
            ),
            DeviceCluster(
                cluster_id="c2",
                name="Cluster 2",
                strategy=ClusterStrategy.TYPE,
                device_ids=["b", "c"],
            ),
        ]
        result = merge_clusters(clusters, ["c1", "c2"], "Merged")

        assert result is not None
        assert len(result.device_ids) == 3
        # b should only appear once
        assert result.device_ids.count("b") == 1

    def test_returns_none_for_empty_ids(self):
        """Test returns none for empty cluster IDs."""
        clusters = [
            DeviceCluster(
                cluster_id="c1",
                name="Cluster 1",
                strategy=ClusterStrategy.TYPE,
                device_ids=["a", "b"],
            ),
        ]
        result = merge_clusters(clusters, [], "Empty")

        assert result is None

    def test_returns_none_for_unknown_ids(self):
        """Test returns none for unknown cluster IDs."""
        clusters = [
            DeviceCluster(
                cluster_id="c1",
                name="Cluster 1",
                strategy=ClusterStrategy.TYPE,
                device_ids=["a", "b"],
            ),
        ]
        result = merge_clusters(clusters, ["nonexistent"], "Bad")

        assert result is None