"""Audio streaming pipeline: buffer PCM chunks, trigger STT on recording_finished."""
from __future__ import annotations

import asyncio
import base64
import logging
import time
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
    channels: int = 1
    chunks: dict[int, bytes] = field(default_factory=dict)  # seq → mono PCM bytes
    first_chunk_at: float | None = None
    last_chunk_at: float | None = None
    finished_at: float | None = None
    reported_duration_ms: int | None = None

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
        return b"".join(self.chunks[seq] for seq in sorted(self.chunks.keys()))

    def metrics(self) -> dict[str, Any]:
        """Return lightweight timing/size metrics for this stream."""
        byte_count = sum(len(chunk) for chunk in self.chunks.values())
        upload_span_ms = None
        if self.first_chunk_at is not None and self.last_chunk_at is not None:
            upload_span_ms = max(0.0, (self.last_chunk_at - self.first_chunk_at) * 1000)
        finish_after_first_chunk_ms = None
        if self.first_chunk_at is not None and self.finished_at is not None:
            finish_after_first_chunk_ms = max(0.0, (self.finished_at - self.first_chunk_at) * 1000)
        return {
            "chunk_count": len(self.chunks),
            "byte_count": byte_count,
            "upload_span_ms": upload_span_ms,
            "finish_after_first_chunk_ms": finish_after_first_chunk_ms,
            "duration_ms": self.reported_duration_ms,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
        }


def pcm16_to_mono(pcm_bytes: bytes, channels: int) -> bytes:
    """Normalize interleaved PCM16 audio to mono by taking the first channel."""
    if channels <= 1:
        return pcm_bytes
    frame_width = channels * 2
    if len(pcm_bytes) < frame_width:
        return b""
    usable_len = len(pcm_bytes) - (len(pcm_bytes) % frame_width)
    pcm_bytes = pcm_bytes[:usable_len]
    mono = bytearray(usable_len // channels)
    out = 0
    for idx in range(0, usable_len, frame_width):
        mono[out:out + 2] = pcm_bytes[idx:idx + 2]
        out += 2
    return bytes(mono)


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
                stream = self._streams.get(stream_id)
                if stream is not None:
                    stream.finished_at = time.perf_counter()
                    duration_ms = payload.get("duration_ms")
                    if duration_ms is not None:
                        try:
                            stream.reported_duration_ms = int(duration_ms)
                        except (TypeError, ValueError):
                            logger.debug("Invalid recording duration_ms for stream %s: %r", stream_id, duration_ms)
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
        channels = payload.get("channels", 1)
        try:
            channels = max(1, int(channels))
        except (TypeError, ValueError):
            channels = 1

        if not stream_id or seq < 0 or not data_b64:
            logger.warning("Invalid audio chunk: missing required fields")
            return

        # Create stream entry if needed
        if stream_id not in self._streams:
            self._streams[stream_id] = AudioStream(
                device_id=device_id,
                stream_id=stream_id,
                sample_rate=sample_rate,
                channels=channels,
            )

        # Decode and buffer the chunk
        try:
            pcm_bytes = pcm16_to_mono(base64.b64decode(data_b64), channels)
        except Exception as exc:
            logger.warning("Failed to decode audio chunk %d for stream %s: %s", seq, stream_id, exc)
            return

        stream = self._streams[stream_id]
        now = time.perf_counter()
        if stream.first_chunk_at is None:
            stream.first_chunk_at = now
        stream.last_chunk_at = now
        stream.chunks[seq] = pcm_bytes
        logger.debug("Buffered audio chunk seq=%d for stream %s (total %d chunks)", seq, stream_id, len(stream.chunks))
        self._event_bus.emit("audio_stream_chunk_received", device_id, {
            "stream_id": stream_id,
            "seq": seq,
            "sample_rate": sample_rate,
            "channels": channels,
            "bytes": len(pcm_bytes),
            "chunk_count": len(stream.chunks),
        })
        self._maybe_emit_partial_transcript(device_id, stream_id, seq, pcm_bytes, sample_rate)

    def _maybe_emit_partial_transcript(self, device_id: str, stream_id: str, seq: int, pcm_bytes: bytes, sample_rate: int) -> None:
        """Feed optional streaming STT hooks and emit partial transcripts."""
        accept_chunk = getattr(self._stt, "accept_audio_chunk", None)
        if not callable(accept_chunk):
            return
        try:
            partial = accept_chunk(stream_id, pcm_bytes, sample_rate, seq)
        except Exception as exc:
            logger.warning("Streaming STT chunk hook failed for stream %s seq=%d: %s", stream_id, seq, exc)
            return
        if not partial:
            return
        if isinstance(partial, tuple):
            text = partial[0]
        else:
            text = partial
        cleaned = clean_transcript(str(text))
        if cleaned:
            self._event_bus.emit("transcript_partial", device_id, {
                "stream_id": stream_id,
                "text": str(text),
                "cleaned": cleaned,
                "seq": seq,
            })

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

        # Run STT (blocking call in a thread to not block the event loop).
        # Prefer a streaming backend's finish hook when present; otherwise fall
        # back to whole-buffer transcription. This lets upload/STT overlap while
        # keeping existing batch backends compatible.
        try:
            finish_stream = getattr(self._stt, "finish_stream", None)
            if callable(finish_stream):
                result = await asyncio.to_thread(
                    finish_stream,
                    stream_id,
                    pcm_bytes,
                    stream.sample_rate,
                )
            else:
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
            if all(hasattr(metrics, name) for name in ("duration_seconds", "word_count", "inference_time_ms")):
                logger.debug(
                    "STT metrics for stream %s: duration=%.2fs, words=%d, inference_time=%.0fms",
                    stream_id,
                    metrics.duration_seconds,
                    metrics.word_count,
                    metrics.inference_time_ms,
                )
            else:
                logger.debug("STT metrics for stream %s: %r", stream_id, metrics)

        # Emit transcript event downstream
        logger.info("Transcribed stream %s: %r → %r", stream_id, text, cleaned)
        self._event_bus.emit("transcript", device_id, {
            "stream_id": stream_id,
            "text": text,
            "cleaned": cleaned,
            "audio_metrics": stream.metrics(),
        })
