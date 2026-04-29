"""Audio delivery pipeline: receive agent response, run TTS, send chunks to device."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from .tts import TtsBackend, generate_response_id, _wav_to_pcm_chunks, encode_pcm_to_base64

if TYPE_CHECKING:
    from datp import EventBus
    from datp.commands import CommandDispatcher

logger = logging.getLogger(__name__)

# Default chunk size for audio cache transfer (bytes)
DEFAULT_CHUNK_SIZE = 1024


class AudioDeliveryPipeline:
    """Deliver TTS audio to devices via cache commands.

    Listens for ``agent_response`` events on the EventBus, synthesizes the response
    text to WAV using a TTS backend, and sends the audio data to the device via
    ``audio.cache.put_begin/chunk/end`` commands.

    After successful delivery, emits an ``audio_delivered`` event downstream.

    Parameters
    ----------
    event_bus : EventBus
        The DATP event bus.
    dispatcher : CommandDispatcher
        Command dispatcher for sending cache commands to devices.
    tts : TtsBackend
        TTS backend for synthesizing text to audio.
    chunk_size : int, optional
        Bytes per cache chunk. Default 1024.
    """

    def __init__(
        self,
        event_bus: EventBus,
        dispatcher: CommandDispatcher,
        tts: TtsBackend,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> None:
        if dispatcher is None:
            raise TypeError("dispatcher is required")
        if tts is None:
            raise TypeError("tts backend is required")

        self._event_bus = event_bus
        self._dispatcher = dispatcher
        self._tts = tts
        self._chunk_size = chunk_size
        self._device_locks: dict[str, asyncio.Lock] = {}
        self._lock_creation_lock = asyncio.Lock()

        event_bus.subscribe(self._on_event)
        logger.info("AudioDeliveryPipeline started (chunk_size=%d)", chunk_size)

    def _on_event(self, event_type: str, device_id: str, payload: dict[str, Any]) -> None:
        """Handle incoming DATP events.

        Routes ``agent_response`` events to the async handler.
        """
        if event_type != "agent_response":
            return

        response_text = payload.get("response_text", "").strip()
        if not response_text:
            logger.debug("Skipping agent_response with empty response_text")
            return

        # Schedule async processing
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("No event loop running; cannot schedule audio delivery")
            return

        if loop.is_running():
            asyncio.ensure_future(
                self._deliver_audio(device_id, payload, response_text)
            )
        else:
            logger.warning("Event loop not running; cannot schedule audio delivery")

    async def _deliver_audio(
        self,
        device_id: str,
        payload: dict[str, Any],
        response_text: str,
    ) -> None:
        """Run TTS and deliver audio to device.

        Concurrent deliveries to the same device are serialized so that
        cache sequences do not interleave and corrupt device state.

        Parameters
        ----------
        device_id : str
            Target device ID.
        payload : dict
            Original agent_response payload.
        response_text : str
            Text to synthesize.
        """
        # Serialize per-device cache sequences to prevent interleaving.
        async with self._lock_creation_lock:
            if device_id not in self._device_locks:
                self._device_locks[device_id] = asyncio.Lock()
        async with self._device_locks[device_id]:
            await self._do_deliver_audio(device_id, payload, response_text)

    async def _do_deliver_audio(
        self,
        device_id: str,
        payload: dict[str, Any],
        response_text: str,
    ) -> None:
        """Internal: run TTS and deliver audio to device (assumes caller holds device lock)."""
        response_id = generate_response_id()

        # Step 1: Run TTS synthesis (blocking, run in thread)
        try:
            wav_bytes = await asyncio.to_thread(self._tts.synthesize, response_text)
        except Exception as exc:
            logger.exception("TTS synthesis failed for response %s: %s", response_id, exc)
            return

        if not wav_bytes:
            logger.warning("TTS returned empty audio for response %s", response_id)
            return

        # Step 2: Extract PCM chunks from WAV
        pcm_chunks = _wav_to_pcm_chunks(wav_bytes, self._chunk_size)
        if not pcm_chunks:
            logger.warning("No PCM data extracted from WAV for response %s", response_id)
            return

        # Step 3: Send cache_put_begin
        ok = await self._dispatcher.cache_put_begin(device_id, response_id)
        if not ok:
            logger.warning(
                "audio.cache.put_begin failed for device %s, response %s",
                device_id,
                response_id,
            )
            return

        # Step 4: Send cache_put_chunk for each chunk
        try:
            for seq, pcm_chunk in enumerate(pcm_chunks):
                data_b64 = encode_pcm_to_base64(pcm_chunk)
                ok = await self._dispatcher.cache_put_chunk(
                    device_id,
                    response_id,
                    seq,
                    data_b64,
                )
                if not ok:
                    logger.warning(
                        "audio.cache.chunk (seq=%d) failed for device %s, response %s",
                        seq,
                        device_id,
                        response_id,
                    )
                    return
        except Exception as exc:
            logger.exception(
                "Error sending chunks to device %s, response %s: %s",
                device_id,
                response_id,
                exc,
            )
            return

        # Step 5: Send cache_put_end
        # Note: SHA256 is currently not calculated; pass None (optional per spec)
        ok = await self._dispatcher.cache_put_end(device_id, response_id, sha256=None)
        if not ok:
            logger.warning(
                "audio.cache.put_end failed for device %s, response %s",
                device_id,
                response_id,
            )
            return

        # Step 6: Emit audio_delivered event
        logger.info(
            "Audio delivered to device %s (response_id=%s, chunks=%d)",
            device_id,
            response_id,
            len(pcm_chunks),
        )

        self._event_bus.emit("audio_delivered", device_id, {
            "response_id": response_id,
            "response_text": response_text,
            "stream_id": payload.get("stream_id"),
            "transcript": payload.get("transcript"),
            "device_context": payload.get("device_context"),
            "chunk_count": len(pcm_chunks),
        })
