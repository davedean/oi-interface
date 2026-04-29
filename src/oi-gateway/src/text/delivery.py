"""Text delivery pipeline: forward streaming text deltas to devices."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datp import EventBus
    from datp.commands import CommandDispatcher

logger = logging.getLogger(__name__)


class TextDeliveryPipeline:
    """Forward response/progress stream events to DATP display commands.

    Listens for ``agent_response_stream`` and ``agent_progress`` events and sends
    ``display.show_response_delta`` / ``display.show_progress`` commands.
    per-device sequence numbering and state management.

    Parameters
    ----------
    event_bus : EventBus
        The DATP event bus.
    dispatcher : CommandDispatcher
        Command dispatcher for sending text delta commands to devices.
    """

    def __init__(
        self,
        event_bus: EventBus,
        dispatcher: CommandDispatcher,
    ) -> None:
        if dispatcher is None:
            raise TypeError("dispatcher is required")

        self._event_bus = event_bus
        self._dispatcher = dispatcher
        self._sequence_counters: dict[str, int] = {}
        self._device_locks: dict[str, asyncio.Lock] = {}
        self._lock_creation_lock = asyncio.Lock()

        event_bus.subscribe(self._on_event)
        logger.info("TextDeliveryPipeline STARTED and subscribed to events")

    def _on_event(self, event_type: str, device_id: str, payload: dict[str, Any]) -> None:
        """Handle incoming DATP events."""
        if event_type not in {"agent_response_stream", "agent_progress"}:
            return

        if event_type == "agent_response_stream":
            text_delta = payload.get("text_delta", "")
            is_final = payload.get("is_final", False)
            if not text_delta and not is_final:
                logger.debug("Skipping empty non-final text_delta for device %s", device_id)
                return

        if event_type == "agent_progress":
            text = payload.get("text", "")
            if not text:
                return

        # Schedule async processing
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("No event loop running; cannot schedule text delivery")
            return

        if loop.is_running():
            asyncio.ensure_future(
                self._deliver_text_delta(event_type, device_id, payload)
            )
        else:
            logger.warning("Event loop not running; cannot schedule text delivery")

    async def _deliver_text_delta(
        self,
        event_type: str,
        device_id: str,
        payload: dict[str, Any],
    ) -> None:
        """Send text delta to device (handles per-device sequencing)."""
        # Serialize per-device to prevent interleaving deltas
        async with self._lock_creation_lock:
            if device_id not in self._device_locks:
                self._device_locks[device_id] = asyncio.Lock()

        async with self._device_locks[device_id]:
            await self._do_deliver_text_delta(event_type, device_id, payload)

    async def _do_deliver_text_delta(
        self,
        event_type: str,
        device_id: str,
        payload: dict[str, Any],
    ) -> None:
        """Internal: send response/progress command."""

        # Track sequence per device
        if device_id not in self._sequence_counters:
            self._sequence_counters[device_id] = 0

        seq = self._sequence_counters[device_id]
        self._sequence_counters[device_id] += 1

        # Send delta to device
        if event_type == "agent_progress":
            text = payload.get("text", "")
            kind = payload.get("kind")
            logger.info("TextDeliveryPipeline SENDING progress: device=%s seq=%d kind=%s text=%r",
                        device_id, seq, kind, text[:50])
            ok = await self._dispatcher.show_progress(device_id, text, kind, seq)
            is_final = False
        else:
            text_delta = payload.get("text_delta", "")
            is_final = payload.get("is_final", False)
            logger.info("TextDeliveryPipeline SENDING response delta: device=%s seq=%d final=%s text=%r",
                        device_id, seq, is_final, text_delta[:50])
            ok = await self._dispatcher.show_response_delta(device_id, text_delta, is_final, seq)

        if not ok:
            logger.warning(
                "display stream command failed for device %s (seq=%d)",                device_id,
                seq,
            )
            return

        logger.debug(
            "Text delta sent to device %s (seq=%d, final=%s)",
            device_id,
            seq,
            is_final,
        )

        # Reset sequence on final
        if is_final:
            self._sequence_counters[device_id] = 0
            logger.info(
                "Text streaming complete for device %s (response_id=%s)",
                device_id,
                payload.get("correlation_id", "unknown"),
            )
