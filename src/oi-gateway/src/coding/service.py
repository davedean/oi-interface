"""Coding workflow service for oi-gateway.

This service listens for coding-related transcripts, assesses the repository
using git/filesystem tools, and generates output for different device types:
- Short summary for Stick (small device)
- Detailed diff for Pi screen (larger display device)
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from datp.events import EventBus

from .models import (
    CodingRequest,
    CodingWorkflowState,
    CodingWorkflowStatus,
    is_coding_request,
)
from .git import assess_repository, generate_diff

if TYPE_CHECKING:
    from registry import RegistryService

logger = logging.getLogger(__name__)

# Event types emitted by this service
CODING_WORKFLOW_STARTED = "coding.workflow_started"
CODING_WORKFLOW_COMPLETED = "coding.workflow_completed"
CODING_WORKFLOW_FAILED = "coding.workflow_failed"
CODING_ASSESSMENT_READY = "coding.assessment_ready"
CODING_DIFF_READY = "coding.diff_ready"


class CodingWorkflowService:
    """Service that handles coding workflow requests.

    Subscribes to "transcript" events from the STT pipeline. When a coding-related
    transcript is detected, it assesses the repository state and generates
    output appropriate for different device types.

    Parameters
    ----------
    event_bus : EventBus
        The DATP event bus for subscribing and emitting events.
    registry : RegistryService
        Device registry for querying device info and capabilities.
    repo_path : str, optional
        Path to the repository to assess. Defaults to cwd.
    """

    def __init__(
        self,
        event_bus: EventBus,
        registry: RegistryService,
        repo_path: str | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._registry = registry
        self._repo_path = repo_path
        self._state = CodingWorkflowState()
        self._enabled = True

        # Subscribe to transcript events
        event_bus.subscribe(self._on_event)
        logger.info("CodingWorkflowService started")

    @property
    def state(self) -> CodingWorkflowState:
        """Get the current state of the coding workflow."""
        return self._state

    @property
    def enabled(self) -> bool:
        """Check if the service is enabled."""
        return self._enabled

    def enable(self) -> None:
        """Enable the coding workflow service."""
        self._enabled = True
        logger.info("CodingWorkflowService enabled")

    def disable(self) -> None:
        """Disable the coding workflow service."""
        self._enabled = False
        logger.info("CodingWorkflowService disabled")

    def start(self) -> None:
        """No-op for backward compatibility (subscription happens in __init__)."""

    def stop(self) -> None:
        """No-op for backward compatibility (unsubscription not needed)."""

    def _on_event(self, event_type: str, device_id: str, payload: dict[str, Any]) -> None:
        """Handle incoming DATP events.

        Routes transcript events to the async handler.
        """
        if event_type != "transcript":
            return

        if not self._enabled:
            return

        import asyncio

        cleaned = payload.get("cleaned", "").strip()
        if not cleaned:
            return

        # Check if this is a coding request
        if not is_coding_request(cleaned):
            return

        # Process as coding workflow
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(self._handle_coding_request(device_id, payload))
        else:
            logger.warning("Event loop not running; cannot schedule coding workflow")

    async def _handle_coding_request(
        self,
        device_id: str,
        payload: dict[str, Any],
    ) -> None:
        """Process a coding-related transcript.

        Parameters
        ----------
        device_id : str
            Source device ID.
        payload : dict
            Transcript event payload: stream_id, text, cleaned.
        """
        cleaned = payload.get("cleaned", "").strip()
        stream_id = payload.get("stream_id", "unknown")

        logger.info(
            "Coding workflow triggered: device=%s stream=%s transcript='%s...'",
            device_id,
            stream_id,
            cleaned[:50],
        )

        # Create request
        request = CodingRequest(
            request_id=f"coding_{uuid.uuid4().hex[:8]}",
            transcript=cleaned,
            source_device_id=device_id,
            timestamp=datetime.now(timezone.utc),
            status=CodingWorkflowStatus.ASSESSING_REPO,
        )

        # Update state
        self._state.active_request = request

        # Emit workflow started event
        self._event_bus.emit(CODING_WORKFLOW_STARTED, device_id, {
            "request_id": request.request_id,
            "transcript": cleaned,
            "stream_id": stream_id,
        })

        try:
            # Step 1: Assess repository
            assessment = await self._assess_repository()

            request.status = CodingWorkflowStatus.GENERATING_DIFF
            self._state.current_assessment = assessment

            # Emit assessment ready event
            self._event_bus.emit(CODING_ASSESSMENT_READY, device_id, {
                "request_id": request.request_id,
                "assessment": {
                    "is_git_repo": assessment.is_git_repo,
                    "branch": assessment.branch,
                    "has_uncommitted_changes": assessment.has_uncommitted_changes,
                    "staged_files": assessment.staged_files,
                    "unstaged_files": assessment.unstaged_files,
                    "modified_files": assessment.modified_files,
                },
            })

            # Step 2: Generate diff
            diff_result = await self._generate_diff()

            request.status = CodingWorkflowStatus.COMPLETED
            self._state.current_diff = diff_result

            # Emit diff ready event
            self._event_bus.emit(CODING_DIFF_READY, device_id, {
                "request_id": request.request_id,
                "summary": diff_result.summary,
                "files_changed": diff_result.files_changed,
                "insertions": diff_result.insertions,
                "deletions": diff_result.deletions,
            })

            # Emit workflow completed event
            self._event_bus.emit(CODING_WORKFLOW_COMPLETED, device_id, {
                "request_id": request.request_id,
                "transcript": cleaned,
                "stream_id": stream_id,
                "summary": diff_result.summary,
                "full_diff": diff_result.full_diff,
                "files_changed": diff_result.files_changed,
                "device_context": self._build_device_context(),
            })

            logger.info(
                "Coding workflow completed: request_id=%s files=%d",
                request.request_id,
                len(diff_result.files_changed),
            )

        except Exception as exc:
            logger.exception("Coding workflow failed: %s", exc)
            request.status = CodingWorkflowStatus.FAILED
            request.error_message = str(exc)

            self._event_bus.emit(CODING_WORKFLOW_FAILED, device_id, {
                "request_id": request.request_id,
                "error": str(exc),
            })

        # Add to history
        self._add_to_history(request)

    async def _assess_repository(self):
        """Assess the repository state (async wrapper)."""
        import asyncio

        # Run in executor to avoid blocking
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, assess_repository, self._repo_path
        )

    async def _generate_diff(self):
        """Generate diff output (async wrapper)."""
        import asyncio

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, generate_diff, self._repo_path
        )

    def _build_device_context(self) -> dict[str, Any]:
        """Build device context for routing decisions.

        Returns
        -------
        dict
            Device context with devices categorized by capability.
        """
        online_devices = self._registry.get_online_devices()
        foreground = self._registry.get_foreground_device()

        # Categorize devices
        small_devices = []  # Stick-like devices
        large_devices = []  # Pi screen-like devices

        for device in online_devices:
            caps = self._registry.get_capabilities(device.device_id) or {}
            max_spoken = caps.get("max_spoken_seconds", 0)
            supports_markdown = caps.get("supports_markdown", False)

            # Small devices: short spoken time, no markdown
            if max_spoken <= 20 and not supports_markdown:
                small_devices.append(device.device_id)
            else:
                large_devices.append(device.device_id)

        return {
            "foreground": foreground.device_id if foreground else None,
            "small_devices": small_devices,  # For summary (Stick)
            "large_devices": large_devices,  # For full diff (Pi screen)
            "all_online": [d.device_id for d in online_devices],
        }

    def _add_to_history(self, request: CodingRequest) -> None:
        """Add request to history, maintaining max size."""
        self._state.request_history.append(request)
        if len(self._state.request_history) > self._state.max_history:
            self._state.request_history = self._state.request_history[-self._state.max_history:]

    # ------------------------------------------------------------------
    # API Methods
    # ------------------------------------------------------------------

    def get_status(self) -> dict[str, Any]:
        """Get coding workflow status for API.

        Returns
        -------
        dict
            Status information including active request and history.
        """
        return self._state.to_dict()

    def get_last_result(self) -> dict[str, Any] | None:
        """Get the last completed workflow result.

        Returns
        -------
        dict or None
            Last result with summary and diff, or None if no completed request.
        """
        if not self._state.active_request:
            return None

        if self._state.active_request.status != CodingWorkflowStatus.COMPLETED:
            return None

        return {
            "request_id": self._state.active_request.request_id,
            "transcript": self._state.active_request.transcript,
            "timestamp": self._state.active_request.timestamp.isoformat(),
            "summary": self._state.current_diff.summary if self._state.current_diff else None,
            "full_diff": self._state.current_diff.full_diff if self._state.current_diff else None,
            "files_changed": self._state.current_diff.files_changed if self._state.current_diff else [],
            "device_context": self._build_device_context(),
        }

    def clear_history(self) -> None:
        """Clear the workflow history."""
        self._state.request_history = []
        logger.info("Coding workflow history cleared")