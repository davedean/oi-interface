"""Tests for attention policy module."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

# Import the modules under test
from attention.policy import (
    AttentionPolicy,
    AttentionState,
    AttentionTransition,
    AttentionConfig,
    create_attention_policy,
    get_attention_policy,
    reset_attention_policy,
)
from attention.events import (
    ATTENTION_CHANGED,
    ATTENTION_ACQUIRED,
    ATTENTION_RELEASED,
    ATTENTION_PRIORITY_UPDATED,
    ATTENTION_IDLE,
    ATTENTION_ACTIVE,
)


class TestAttentionState:
    """Tests for AttentionState dataclass."""

    def test_defaults(self):
        """Test default values."""
        state = AttentionState(device_id="test-device")
        assert state.device_id == "test-device"
        assert state.state == ATTENTION_IDLE
        assert state.acquired_at is None
        assert state.last_activity is None
        assert state.auto_release_after_seconds is None
        assert state.priority == 0
        assert state.reason == ""

    def test_custom_values(self):
        """Test custom values."""
        now = datetime.now(timezone.utc)
        state = AttentionState(
            device_id="test-device",
            state=ATTENTION_ACTIVE,
            acquired_at=now,
            priority=10,
            reason="testing",
        )
        assert state.state == ATTENTION_ACTIVE
        assert state.priority == 10
        assert state.reason == "testing"


class TestAttentionConfig:
    """Tests for AttentionConfig dataclass."""

    def test_defaults(self):
        """Test default configuration."""
        config = AttentionConfig()
        assert config.auto_release_timeout == 300.0
        assert config.activity_timeout == 60.0
        assert config.require_explicit_release is False
        assert config.enable_priority is True
        assert config.default_priority == 0


class TestAttentionPolicy:
    """Tests for AttentionPolicy class."""

    def setup_method(self):
        """Reset singleton before each test."""
        reset_attention_policy()

    def test_initial_state(self):
        """Test initial attention state."""
        policy = AttentionPolicy()
        assert policy.current_attention is None
        assert policy.has_attention is False

    def test_acquire_attention(self):
        """Test acquiring attention for a device."""
        policy = AttentionPolicy()

        result = policy.acquire_attention(
            device_id="stick-001",
            reason="user interaction",
        )

        assert result is True
        assert policy.current_attention == "stick-001"
        assert policy.has_attention is True

    def test_acquire_attention_twice_same_device(self):
        """Test acquiring attention twice for same device."""
        policy = AttentionPolicy()

        policy.acquire_attention(device_id="stick-001")
        result = policy.acquire_attention(device_id="stick-001", reason="again")

        assert result is True
        assert policy.current_attention == "stick-001"

    def test_acquire_attention_different_device(self):
        """Test attention moves to new device."""
        policy = AttentionPolicy()

        policy.acquire_attention(device_id="stick-001")
        result = policy.acquire_attention(device_id="stick-002")

        assert result is True
        assert policy.current_attention == "stick-002"

        # Check old device state
        state = policy.get_attention_state("stick-001")
        assert state is not None
        assert state.state == ATTENTION_IDLE

    def test_acquire_attention_priority_prevents_overtake(self):
        """Test that higher priority prevents takeover."""
        policy = AttentionPolicy(config=AttentionConfig(enable_priority=True))

        # Acquire attention with high priority
        policy.acquire_attention(device_id="stick-001", priority=10)

        # Try to acquire with lower priority - should fail
        result = policy.acquire_attention(device_id="stick-002", priority=5)

        assert result is False
        assert policy.current_attention == "stick-001"

    def test_acquire_attention_priority_success(self):
        """Test that higher priority can overtake."""
        policy = AttentionPolicy(config=AttentionConfig(enable_priority=True))

        # Acquire attention with low priority
        policy.acquire_attention(device_id="stick-001", priority=5)

        # Try to acquire with higher priority - should succeed
        result = policy.acquire_attention(device_id="stick-002", priority=15)

        assert result is True
        assert policy.current_attention == "stick-002"

    def test_release_attention(self):
        """Test releasing attention."""
        policy = AttentionPolicy()
        policy.acquire_attention(device_id="stick-001")

        result = policy.release_attention(device_id="stick-001", reason="done")

        assert result is True
        assert policy.current_attention is None
        assert policy.has_attention is False

    def test_release_attention_not_current_device(self):
        """Test releasing attention from non-attended device."""
        policy = AttentionPolicy()
        policy.acquire_attention(device_id="stick-001")

        result = policy.release_attention(device_id="stick-002")

        assert result is False
        assert policy.current_attention == "stick-001"

    def test_get_attention_state(self):
        """Test getting attention state for device."""
        policy = AttentionPolicy()
        policy.acquire_attention(device_id="stick-001", priority=5)

        state = policy.get_attention_state("stick-001")

        assert state is not None
        assert state.device_id == "stick-001"
        assert state.priority == 5

    def test_get_attention_state_unknown_device(self):
        """Test getting state for unknown device."""
        policy = AttentionPolicy()

        state = policy.get_attention_state("unknown-device")

        assert state is None

    def test_record_activity(self):
        """Test recording activity on device."""
        policy = AttentionPolicy()
        policy.acquire_attention(device_id="stick-001")

        policy.record_activity("stick-001", "button_press")

        state = policy.get_attention_state("stick-001")
        assert state.last_activity is not None

    def test_set_priority(self):
        """Test setting device priority."""
        policy = AttentionPolicy()

        policy.set_priority("stick-001", priority=10, reason="favored")

        state = policy.get_attention_state("stick-001")
        assert state is not None
        assert state.priority == 10

    def test_set_priority_existing_device(self):
        """Test updating priority on existing device."""
        policy = AttentionPolicy()
        policy.set_priority("stick-001", priority=5)

        policy.set_priority("stick-001", priority=10, reason="updated")

        state = policy.get_attention_state("stick-001")
        assert state.priority == 10

    def test_get_attention_candidates(self):
        """Test getting attention candidates."""
        policy = AttentionPolicy()

        policy.set_priority("stick-001", priority=5)
        policy.set_priority("stick-002", priority=10)
        policy.set_priority("stick-003", priority=3)

        policy.acquire_attention(device_id="stick-001")

        # Get all candidates including current
        all_candidates = policy.get_attention_candidates(include_current=True)
        assert "stick-001" in all_candidates
        assert "stick-002" in all_candidates
        assert "stick-003" in all_candidates

        # Get candidates excluding current
        candidates = policy.get_attention_candidates(include_current=False)
        assert "stick-001" not in candidates
        assert "stick-002" in candidates
        assert "stick-003" in candidates

    def test_get_attention_candidates_min_priority(self):
        """Test filtering candidates by priority."""
        policy = AttentionPolicy()

        policy.set_priority("stick-001", priority=5)
        policy.set_priority("stick-002", priority=10)
        policy.set_priority("stick-003", priority=3)

        candidates = policy.get_attention_candidates(min_priority=5)

        assert "stick-001" in candidates
        assert "stick-002" in candidates
        assert "stick-003" not in candidates

    def test_handle_device_offline(self):
        """Test handling device going offline."""
        policy = AttentionPolicy()
        policy.acquire_attention(device_id="stick-001")

        result = policy.handle_device_offline("stick-001")

        assert result is True
        assert policy.current_attention is None

    def test_handle_device_offline_not_attended(self):
        """Test handling offline for non-attended device."""
        policy = AttentionPolicy()
        policy.acquire_attention(device_id="stick-001")

        result = policy.handle_device_offline("stick-002")

        assert result is False
        assert policy.current_attention == "stick-001"

    def test_check_timeouts_no_timeout(self):
        """Test that no timeouts when not configured."""
        config = AttentionConfig(auto_release_timeout=0)  # Disabled
        policy = AttentionPolicy(config=config)
        policy.acquire_attention(device_id="stick-001")

        released = policy.check_timeouts()

        assert released == []

    def test_check_timeouts_with_timeout(self):
        """Test timeout releases attention."""
        now = datetime.now(timezone.utc)

        # Create mock that returns controlled times
        time_offset = [0]

        def mock_time():
            return now + timedelta(seconds=time_offset[0])

        config = AttentionConfig(auto_release_timeout=60.0)
        policy = AttentionPolicy(config=config, get_current_time=mock_time)
        policy.acquire_attention(device_id="stick-001", auto_release_seconds=30.0)

        # Advance time past timeout
        time_offset[0] = 35

        released = policy.check_timeouts()

        assert "stick-001" in released
        assert policy.current_attention is None

    def test_get_state_summary(self):
        """Test getting state summary."""
        policy = AttentionPolicy(config=AttentionConfig(auto_release_timeout=120.0))
        policy.set_priority("stick-001", priority=5)
        policy.acquire_attention(device_id="stick-001")

        summary = policy.get_state_summary()

        assert summary["current_attention"] == "stick-001"
        assert summary["has_attention"] is True
        assert "stick-001" in summary["tracked_devices"]
        assert summary["config"]["auto_release_timeout"] == 120.0

    def test_require_explicit_release(self):
        """Test explicit release requirement."""
        config = AttentionConfig(require_explicit_release=True)
        policy = AttentionPolicy(config=config)

        policy.acquire_attention(device_id="stick-001")

        # Try to acquire on another device - should fail because explicit release required
        result = policy.acquire_attention(device_id="stick-002")

        assert result is False
        assert policy.current_attention == "stick-001"

        # Now explicitly release
        policy.release_attention("stick-001")

        # Now acquire should work
        result = policy.acquire_attention(device_id="stick-002")

        assert result is True
        assert policy.current_attention == "stick-002"

    def test_transition_types(self):
        """Test different transition types."""
        policy = AttentionPolicy()

        policy.acquire_attention(
            device_id="stick-001",
            transition=AttentionTransition.EXPLICIT,
        )
        assert policy.current_attention == "stick-001"

        policy.release_attention("stick-001", transition=AttentionTransition.EXPLICIT)

        policy.acquire_attention(device_id="stick-002", transition=AttentionTransition.IMPLICIT)
        assert policy.current_attention == "stick-002"


class TestAttentionPolicyEvents:
    """Tests for attention event emission."""

    def setup_method(self):
        """Reset singleton before each test."""
        reset_attention_policy()

    def test_events_emitted_on_acquire(self):
        """Test that events are emitted when acquiring attention."""
        mock_bus = MagicMock()
        policy = AttentionPolicy(event_bus=mock_bus)

        policy.acquire_attention(device_id="stick-001", reason="test")

        # Check that emit was called for acquired and changed events
        calls = mock_bus.emit.call_args_list
        event_types = [call[0][0] for call in calls]

        assert ATTENTION_ACQUIRED in event_types
        assert ATTENTION_CHANGED in event_types

    def test_events_emitted_on_release(self):
        """Test that events are emitted when releasing attention."""
        mock_bus = MagicMock()
        policy = AttentionPolicy(event_bus=mock_bus)

        policy.acquire_attention(device_id="stick-001")
        policy.release_attention("stick-001")

        # Check that release event was emitted
        calls = mock_bus.emit.call_args_list
        event_types = [call[0][0] for call in calls]

        assert ATTENTION_RELEASED in event_types


class TestAttentionPolicyEdgeCases:
    """Edge case tests for attention policy."""

    def setup_method(self):
        """Reset singleton before each test."""
        reset_attention_policy()

    def test_acquire_after_release(self):
        """Test acquiring attention after releasing."""
        policy = AttentionPolicy()

        policy.acquire_attention(device_id="stick-001")
        policy.release_attention("stick-001")
        result = policy.acquire_attention(device_id="stick-002")

        assert result is True
        assert policy.current_attention == "stick-002"

    def test_multiple_sequential_acquires(self):
        """Test multiple sequential attention acquisitions."""
        policy = AttentionPolicy()

        for i in range(5):
            result = policy.acquire_attention(device_id=f"stick-{i:03d}")
            assert result is True

        assert policy.current_attention == "stick-004"

    def test_attention_state_tracking(self):
        """Test that attention state is properly tracked."""
        policy = AttentionPolicy()

        policy.acquire_attention(device_id="stick-001")

        state = policy.get_attention_state("stick-001")
        assert state is not None
        assert state.state == ATTENTION_ACTIVE

    def test_empty_device_list_candidates(self):
        """Test candidates with no devices."""
        policy = AttentionPolicy()

        candidates = policy.get_attention_candidates()

        assert candidates == []


class TestCreateAttentionPolicy:
    """Tests for create_attention_policy factory function."""

    def test_creates_new_instance(self):
        """Test that factory creates new instance."""
        policy1 = create_attention_policy()
        policy2 = create_attention_policy()

        assert policy1 is not policy2


class TestGetAttentionPolicy:
    """Tests for get_attention_policy singleton."""

    def setup_method(self):
        """Reset before each test."""
        reset_attention_policy()

    def test_returns_singleton(self):
        """Test that singleton is returned."""
        policy = get_attention_policy()
        same = get_attention_policy()

        assert policy is same

    def test_singleton_is_attention_policy(self):
        """Test that singleton is an AttentionPolicy."""
        policy = get_attention_policy()

        assert isinstance(policy, AttentionPolicy)