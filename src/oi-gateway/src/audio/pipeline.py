"""Audio streaming pipeline: buffer PCM chunks, trigger STT on recording_finished."""
from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .stt import SttBackend, clean_transcript

if TYPE_CHECKING:
    from datp import EventBus

logger = logging.getLogger(__name__)


@dataclass
class AudioStream:
    """In-flight audio stream being buffered."""

    device_id: str
    stream_id: str
    sample_rate: int = 16000
    chunks: dict[int, bytes] = field(default_factory=dict)  # seq → raw PCM bytes

    def is_complete(self) -> bool:
        """Check if all chunks are present (seq from 0 to max with no gaps)."""
        if not self.chunks:
            return False
        expected_seqs = set(range(max(self.chunks.keys()) + 1))
        return set(self.chunks.keys()) == expected_seqs

    def reassemble_pcm(self) -> bytes:
        """Concatenate all chunks in order to recover the full PCM audio."""
        if not self.is_complete():
            logger.warning("Stream %s not complete; reassembling with gaps", self.stream_id)
        pcm = b""
        for seq in sorted(self.chunks.keys()):
            pcm += self.chunks[seq]
        return pcm


class StreamAccumulator:
    """Listens for audio_chunk events, buffers them, and triggers STT on recording_finished.

    Parameters
    ----------
    event_bus : EventBus
        The DATP event bus.
    stt : SttBackend
        The STT backend to use for transcription.
    """

    def __init__(self, event_bus: EventBus, stt: SttBackend) -> None:
        self._event_bus = event_bus
        self._stt = stt
        self._streams: dict[str, AudioStream] = {}
        event_bus.subscribe(self._on_event)

    def _on_event(self, event_type: str, device_id: str, payload: dict[str, Any]) -> None:
        """Handle incoming DATP events.

        Routes to:
        - _buffer_chunk() for audio_chunk events
        - _schedule_transcribe() for audio.recording_finished events
        """
        if event_type == "audio_chunk":
            self._buffer_chunk(device_id, payload)

        elif event_type == "event" and payload.get("event") == "audio.recording_finished":
            stream_id = payload.get("stream_id")
            if stream_id:
                # Schedule the async transcription to run on the event loop.
                # Since this callback is sync and called from the event loop,
                # we use create_task to schedule the coroutine.
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(self._transcribe(device_id, stream_id))
                else:
                    logger.warning("Event loop not running; cannot schedule transcription")

    def _buffer_chunk(self, device_id: str, payload: dict[str, Any]) -> None:
        """Buffer an incoming audio chunk.

        Parameters
        ----------
        device_id : str
            Source device.
        payload : dict
            DATP audio_chunk payload: stream_id, seq, format, sample_rate, channels, data_b64.
        """
        stream_id = payload.get("stream_id", "")
        seq = payload.get("seq", -1)
        data_b64 = payload.get("data_b64", "")
        sample_rate = payload.get("sample_rate", 16000)

        if not stream_id or seq < 0 or not data_b64:
            logger.warning("Invalid audio chunk: missing required fields")
            return

        # Create stream entry if needed
        if stream_id not in self._streams:
            self._streams[stream_id] = AudioStream(
                device_id=device_id,
                stream_id=stream_id,
                sample_rate=sample_rate,
            )

        # Decode and buffer the chunk
        try:
            pcm_bytes = base64.b64decode(data_b64)
        except Exception as exc:
            logger.warning("Failed to decode audio chunk %d for stream %s: %s", seq, stream_id, exc)
            return

        self._streams[stream_id].chunks[seq] = pcm_bytes
        logger.debug("Buffered audio chunk seq=%d for stream %s (total %d chunks)", seq, stream_id, len(self._streams[stream_id].chunks))

    async def _transcribe(self, device_id: str, stream_id: str) -> None:
        """Transcribe a complete audio stream.

        Parameters
        ----------
        device_id : str
            Source device.
        stream_id : str
            Stream to transcribe.
        """
        stream = self._streams.pop(stream_id, None)
        if stream is None:
            logger.warning("Stream %s not found for transcription", stream_id)
            return

        # Reassemble PCM
        pcm_bytes = stream.reassemble_pcm()
        if not pcm_bytes:
            logger.warning("Stream %s has no audio data", stream_id)
            return

        # Run STT (blocking call in a thread to not block the event loop)
        try:
            result = await asyncio.to_thread(
                self._stt.transcribe,
                pcm_bytes,
                stream.sample_rate,
            )
            # Handle both old (str) and new (tuple) return types for backward compatibility
            if isinstance(result, tuple):
                text, metrics = result
            else:
                text = result
                metrics = None
        except Exception as exc:
            logger.exception("STT transcription failed for stream %s: %s", stream_id, exc)
            return

        # Clean transcript
        cleaned = clean_transcript(text)

        # Log metrics if available
        if metrics:
            logger.debug(
                "STT metrics for stream %s: duration=%.2fs, words=%d, inference_time=%.0fms",
                stream_id,
                metrics.duration_seconds,
                metrics.word_count,
                metrics.inference_time_ms,
            )

        # Emit transcript event downstream
        logger.info("Transcribed stream %s: %r → %r", stream_id, text, cleaned)
        self._event_bus.emit("transcript", device_id, {
            "stream_id": stream_id,
            "text": text,
            "cleaned": cleaned,
        })
