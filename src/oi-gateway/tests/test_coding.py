"""Tests for coding workflow module."""
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add the gateway source to path for imports
import sys

gateway_src = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(gateway_src))

from coding import (
    CodingWorkflowService,
    CodingWorkflowState,
    CodingWorkflowStatus,
    is_coding_request,
    CodingRequest,
    RepoAssessment,
    DiffResult,
)
from coding.models import CODING_KEYWORDS
from datp import EventBus
from registry.models import DeviceInfo


# ------------------------------------------------------------------
# Test Fixtures and Helpers
# ------------------------------------------------------------------


class StubRegistry:
    """Minimal registry stub for testing CodingWorkflowService."""

    def __init__(self, devices=None, foreground=None):
        self._devices = devices or []
        self._foreground = foreground

    def get_online_devices(self):
        return self._devices

    def get_capabilities(self, device_id: str):
        for device in self._devices:
            if device.device_id == device_id:
                return device.capabilities
        return None

    def get_foreground_device(self):
        return self._foreground


@pytest.fixture
def event_bus():
    """Create a fresh event bus."""
    return EventBus()


@pytest.fixture
def stub_device():
    """Create a stub device for testing."""
    return DeviceInfo(
        device_id="test-device",
        device_type="test",
        session_id="sess_001",
        connected_at=None,
        last_seen=None,
        capabilities={"max_spoken_seconds": 12, "supports_confirm_buttons": True},
        resume_token=None,
        nonce=None,
        state={},
        audio_cache_bytes=0,
        muted_until=None,
    )


@pytest.fixture
def stub_device_large():
    """Create a stub device with large display capabilities."""
    return DeviceInfo(
        device_id="pi-screen",
        device_type="pi",
        session_id="sess_002",
        connected_at=None,
        last_seen=None,
        capabilities={"max_spoken_seconds": 120, "supports_markdown": True},
        resume_token=None,
        nonce=None,
        state={},
        audio_cache_bytes=0,
        muted_until=None,
    )


# ------------------------------------------------------------------
# Tests: Coding Request Detection
# ------------------------------------------------------------------


def test_is_coding_request_with_check_code():
    """Verify 'check code' triggers coding workflow."""
    assert is_coding_request("check code for bugs")
    assert is_coding_request("check the code in main.py")


def test_is_coding_request_with_review_changes():
    """Verify 'review changes' triggers coding workflow."""
    assert is_coding_request("review changes")
    assert is_coding_request("review the changes in the repo")


def test_is_coding_request_with_git_diff():
    """Verify 'git diff' triggers coding workflow."""
    assert is_coding_request("show me git diff")
    assert is_coding_request("run git diff for the last commit")


def test_is_coding_request_with_assess():
    """Verify 'assess repo' triggers coding workflow."""
    assert is_coding_request("assess repo")
    assert is_coding_request("assess repository for changes")


def test_is_coding_request_with_modified():
    """Verify 'modified files' triggers coding workflow."""
    assert is_coding_request("show modified files")
    assert is_coding_request("what files are modified")


def test_is_coding_request_negative():
    """Verify non-coding requests return False."""
    assert not is_coding_request("what's the weather")
    assert not is_coding_request("play some music")
    assert not is_coding_request("set a timer for 10 minutes")


def test_is_coding_request_case_insensitive():
    """Verify detection is case insensitive."""
    assert is_coding_request("CHECK CODE")
    assert is_coding_request("Git Diff")
    assert is_coding_request("REVIEW CHANGES")


# ------------------------------------------------------------------
# Tests: Coding Workflow State
# ------------------------------------------------------------------


def test_coding_workflow_state_to_dict_empty():
    """Verify empty state serializes correctly."""
    state = CodingWorkflowState()
    result = state.to_dict()

    assert result["active_request"] is None
    assert result["current_assessment"] is None
    assert result["current_diff"] is None
    assert result["history_count"] == 0


def test_coding_workflow_state_to_dict_with_request():
    """Verify state with active request serializes correctly."""
    from datetime import datetime, timezone

    request = CodingRequest(
        request_id="test_001",
        transcript="check code",
        source_device_id="test-device",
        timestamp=datetime.now(timezone.utc),
        status=CodingWorkflowStatus.COMPLETED,
    )

    state = CodingWorkflowState()
    state.active_request = request

    result = state.to_dict()

    assert result["active_request"] is not None
    assert result["active_request"]["request_id"] == "test_001"
    assert result["active_request"]["transcript"] == "check code"
    assert result["history_count"] == 0


# ------------------------------------------------------------------
# Tests: Coding Workflow Service
# ------------------------------------------------------------------


def test_coding_service_initialization(event_bus, stub_device):
    """Verify service initializes correctly."""
    registry = StubRegistry(devices=[stub_device])
    service = CodingWorkflowService(event_bus, registry)

    assert service.enabled is True
    assert service.state is not None
    assert service.state.active_request is None


def test_coding_service_disable_enable(event_bus, stub_device):
    """Verify service can be disabled and re-enabled."""
    registry = StubRegistry(devices=[stub_device])
    service = CodingWorkflowService(event_bus, registry)

    service.disable()
    assert service.enabled is False

    service.enable()
    assert service.enabled is True


def test_coding_service_get_status_empty(event_bus, stub_device):
    """Verify get_status returns correct structure when empty."""
    registry = StubRegistry(devices=[stub_device])
    service = CodingWorkflowService(event_bus, registry)

    status = service.get_status()

    assert "active_request" in status
    assert "current_assessment" in status
    assert "current_diff" in status
    assert "history_count" in status


def test_coding_service_get_last_result_none_when_no_completed(event_bus, stub_device):
    """Verify get_last_result returns None when no completed request."""
    registry = StubRegistry(devices=[stub_device])
    service = CodingWorkflowService(event_bus, registry)

    result = service.get_last_result()

    assert result is None


def test_coding_service_clear_history(event_bus, stub_device):
    """Verify clear_history removes history."""
    from datetime import datetime, timezone

    registry = StubRegistry(devices=[stub_device])
    service = CodingWorkflowService(event_bus, registry)

    # Add a request to history
    request = CodingRequest(
        request_id="test_001",
        transcript="check code",
        source_device_id="test-device",
        timestamp=datetime.now(timezone.utc),
        status=CodingWorkflowStatus.COMPLETED,
    )
    service._add_to_history(request)

    assert len(service.state.request_history) == 1

    service.clear_history()

    assert len(service.state.request_history) == 0


def test_coding_service_build_device_context_single_small(event_bus, stub_device):
    """Verify device context for single small device."""
    registry = StubRegistry(devices=[stub_device], foreground=stub_device)
    service = CodingWorkflowService(event_bus, registry)

    context = service._build_device_context()

    assert context["foreground"] == "test-device"
    assert "test-device" in context["small_devices"]
    assert context["large_devices"] == []


def test_coding_service_build_device_context_mixed(event_bus, stub_device, stub_device_large):
    """Verify device context with both small and large devices."""
    registry = StubRegistry(devices=[stub_device, stub_device_large], foreground=stub_device)
    service = CodingWorkflowService(event_bus, registry)

    context = service._build_device_context()

    assert "test-device" in context["small_devices"]
    assert "pi-screen" in context["large_devices"]
    assert context["foreground"] == "test-device"


# ------------------------------------------------------------------
# Tests: Coding Workflow Event Flow
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_coding_transcript_ignored(event_bus, stub_device):
    """Verify non-coding transcripts don't trigger workflow."""
    registry = StubRegistry(devices=[stub_device], foreground=stub_device)
    service = CodingWorkflowService(event_bus, registry)

    # Track events
    events_received = []

    def capture_event(event_type, device_id, payload):
        events_received.append(event_type)

    event_bus.subscribe(capture_event)

    # Emit non-coding transcript
    event_bus.emit("transcript", "test-device", {
        "stream_id": "rec_001",
        "text": "what's the weather",
        "cleaned": "what's the weather",
    })

    await asyncio.sleep(0.1)

    # Verify no coding events were emitted
    assert "coding.workflow_started" not in events_received


@pytest.mark.asyncio
async def test_coding_transcript_triggers_workflow(event_bus, stub_device):
    """Verify coding transcripts trigger workflow events."""
    registry = StubRegistry(devices=[stub_device], foreground=stub_device)
    service = CodingWorkflowService(event_bus, registry)

    # Track coding events
    coding_events = []

    def capture_event(event_type, device_id, payload):
        if event_type.startswith("coding."):
            coding_events.append(event_type)

    event_bus.subscribe(capture_event)

    # Emit coding transcript
    event_bus.emit("transcript", "test-device", {
        "stream_id": "rec_001",
        "text": "check the code",
        "cleaned": "check the code",
    })

    await asyncio.sleep(0.1)

    # Verify coding workflow was triggered
    assert "coding.workflow_started" in coding_events


@pytest.mark.asyncio
async def test_disabled_service_ignores_transcripts(event_bus, stub_device):
    """Verify disabled service ignores all transcripts."""
    registry = StubRegistry(devices=[stub_device], foreground=stub_device)
    service = CodingWorkflowService(event_bus, registry)

    service.disable()

    # Track coding events
    coding_events = []

    def capture_event(event_type, device_id, payload):
        if event_type.startswith("coding."):
            coding_events.append(event_type)

    event_bus.subscribe(capture_event)

    # Emit coding transcript
    event_bus.emit("transcript", "test-device", {
        "stream_id": "rec_001",
        "text": "check the code",
        "cleaned": "check the code",
    })

    await asyncio.sleep(0.1)

    # Verify no coding events were emitted
    assert len(coding_events) == 0


# ------------------------------------------------------------------
# Tests: Git Assessment (Mocked)
# ------------------------------------------------------------------


def test_assess_repository_not_git():
    """Verify assessment returns error for non-git directory."""
    from coding.git import assess_repository

    # Use a temp directory that's not a git repo
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        result = assess_repository(tmpdir)

        assert result.is_git_repo is False
        assert result.branch is None
        assert result.error is not None


def test_is_coding_keywords_list():
    """Verify CODING_KEYWORDS is a non-empty list."""
    assert isinstance(CODING_KEYWORDS, list)
    assert len(CODING_KEYWORDS) > 0
    # Verify all keywords are strings
    assert all(isinstance(k, str) for k in CODING_KEYWORDS)


# ------------------------------------------------------------------
# Tests: Diff Generation (Mocked)
# ------------------------------------------------------------------


def test_generate_diff_non_git():
    """Verify diff generation handles non-git directory."""
    from coding.git import generate_diff

    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        result = generate_diff(tmpdir)

        assert result.summary == "Not a git repository"
        assert result.error == "Not a git repository"


# ------------------------------------------------------------------
# Tests: RepoAssessment Model
# ------------------------------------------------------------------


def test_repo_assessment_defaults():
    """Verify RepoAssessment has correct defaults."""
    assessment = RepoAssessment(
        repo_path="/test/path",
        is_git_repo=True,
        branch="main",
        has_uncommitted_changes=False,
    )

    assert assessment.staged_files == []
    assert assessment.unstaged_files == []
    assert assessment.untracked_files == []
    assert assessment.recent_commits == []
    assert assessment.modified_files == []


def test_diff_result_model():
    """Verify DiffResult model fields."""
    diff = DiffResult(
        summary="2 files changed",
        full_diff="diff content",
        files_changed=["file1.py", "file2.py"],
        insertions=10,
        deletions=5,
    )

    assert diff.summary == "2 files changed"
    assert diff.files_changed == ["file1.py", "file2.py"]
    assert diff.insertions == 10
    assert diff.deletions == 5


# ------------------------------------------------------------------
# Tests: CodingRequest Model
# ------------------------------------------------------------------


def test_coding_request_defaults():
    """Verify CodingRequest has correct defaults."""
    from datetime import datetime, timezone

    request = CodingRequest(
        request_id="req_001",
        transcript="check code",
        source_device_id="test-device",
        timestamp=datetime.now(timezone.utc),
    )

    assert request.status == CodingWorkflowStatus.PENDING
    assert request.error_message is None


def test_coding_request_status_transitions():
    """Verify CodingRequest status can transition."""
    from datetime import datetime, timezone

    request = CodingRequest(
        request_id="req_001",
        transcript="check code",
        source_device_id="test-device",
        timestamp=datetime.now(timezone.utc),
    )

    request.status = CodingWorkflowStatus.ASSESSING_REPO
    assert request.status == CodingWorkflowStatus.ASSESSING_REPO

    request.status = CodingWorkflowStatus.COMPLETED
    assert request.status == CodingWorkflowStatus.COMPLETED

    request.status = CodingWorkflowStatus.FAILED
    request.error_message = "Test error"
    assert request.status == CodingWorkflowStatus.FAILED
    assert request.error_message == "Test error"