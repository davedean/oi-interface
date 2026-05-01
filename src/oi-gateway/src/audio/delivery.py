"""Audio delivery pipeline: receive agent response, run TTS, send chunks to device."""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .tts import TtsBackend, generate_response_id, _wav_to_pcm_chunks, encode_pcm_to_base64

if TYPE_CHECKING:
    from datp import EventBus
    from datp.commands import CommandDispatcher

logger = logging.getLogger(__name__)

# Default chunk size for audio cache transfer (bytes)
DEFAULT_CHUNK_SIZE = 1024
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+|(?<=,)\s+")


@dataclass
class ResponseTextSegmenter:
    """Incrementally split streamed text into stable TTS-sized speech units."""

    min_chars: int = 48
    max_buffer_chars: int = 180
    _buffer: str = ""

    def push(self, text_delta: str) -> list[str]:
        """Append a text delta and return complete segments ready for TTS."""
        if not text_delta:
            return []
        self._buffer += text_delta
        return self._pop_ready_segments()

    def flush(self) -> str:
        """Return any remaining buffered text."""
        text = self._buffer.strip()
        self._buffer = ""
        return text

    def _pop_ready_segments(self) -> list[str]:
        segments: list[str] = []
        while True:
            boundary = self._find_boundary()
            if boundary is None:
                if len(self._buffer) <= self.max_buffer_chars:
                    break
                boundary = self._fallback_boundary()
            segment = self._buffer[:boundary].strip()
            self._buffer = self._buffer[boundary:].lstrip()
            if segment:
                segments.append(segment)
        return segments

    def _find_boundary(self) -> int | None:
        for match in _SENTENCE_BOUNDARY_RE.finditer(self._buffer):
            end = match.end()
            if end >= self.min_chars:
                return end
        return None

    def _fallback_boundary(self) -> int:
        window = self._buffer[: self.max_buffer_chars]
        split_at = max(window.rfind(" "), window.rfind("\n"))
        if split_at < self.min_chars:
            return min(len(self._buffer), self.max_buffer_chars)
        return split_at + 1


@dataclass
class _StreamSpeechState:
    segmenter: ResponseTextSegmenter
    tasks: list[asyncio.Task] = field(default_factory=list)


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
        min_stream_segment_chars: int = 48,
        max_stream_segment_chars: int = 180,
    ) -> None:
        if dispatcher is None:
            raise TypeError("dispatcher is required")
        if tts is None:
            raise TypeError("tts backend is required")

        self._event_bus = event_bus
        self._dispatcher = dispatcher
        self._tts = tts
        self._chunk_size = chunk_size
        self._min_stream_segment_chars = min_stream_segment_chars
        self._max_stream_segment_chars = max_stream_segment_chars
        self._device_locks: dict[str, asyncio.Lock] = {}
        self._lock_creation_lock = asyncio.Lock()
        self._stream_states: dict[tuple[str, str], _StreamSpeechState] = {}

        event_bus.subscribe(self._on_event)
        logger.info("AudioDeliveryPipeline started (chunk_size=%d)", chunk_size)

    def _on_event(self, event_type: str, device_id: str, payload: dict[str, Any]) -> None:
        """Handle incoming DATP events.

        Routes ``agent_response`` events to the async handler.
        """
        if event_type == "agent_response":
            if payload.get("streaming_used"):
                logger.debug("Skipping final agent_response audio because streaming deltas handled TTS")
                return
            response_text = payload.get("response_text", "").strip()
            if not response_text:
                logger.debug("Skipping agent_response with empty response_text")
                return
            self._schedule_delivery(device_id, payload, response_text)
            return

        if event_type in {"agent_response_stream", "agent_response_delta"}:
            self._handle_stream_delta(device_id, payload)
            return

    def _schedule_delivery(self, device_id: str, payload: dict[str, Any], response_text: str) -> asyncio.Task | None:
        """Schedule TTS delivery if an event loop is available."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("No event loop running; cannot schedule audio delivery")
            return None

        if not loop.is_running():
            logger.warning("Event loop not running; cannot schedule audio delivery")
            return None

        task = asyncio.ensure_future(self._deliver_audio(device_id, payload, response_text))
        return task

    def _handle_stream_delta(self, device_id: str, payload: dict[str, Any]) -> None:
        """Turn streamed agent text into small TTS deliveries as soon as stable."""
        text_delta = payload.get("text_delta", "") or ""
        is_final = bool(payload.get("is_final", False))
        stream_id = str(payload.get("stream_id") or payload.get("correlation_id") or "default")
        key = (device_id, stream_id)
        state = self._stream_states.get(key)
        if state is None:
            state = _StreamSpeechState(
                segmenter=ResponseTextSegmenter(
                    min_chars=self._min_stream_segment_chars,
                    max_buffer_chars=self._max_stream_segment_chars,
                )
            )
            self._stream_states[key] = state

        segments = state.segmenter.push(text_delta)
        if is_final:
            final_segment = state.segmenter.flush()
            if final_segment:
                segments.append(final_segment)
            self._stream_states.pop(key, None)

        for segment in segments:
            task = self._schedule_delivery(device_id, {**payload, "response_text": segment, "streaming_segment": True}, segment)
            if task is not None:
                state.tasks.append(task)

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

        tts_start = time.perf_counter()

        # Step 1: Send cache_put_begin first so we can stream chunks as soon as available.
        ok = await self._dispatcher.cache_put_begin(device_id, response_id)
        if not ok:
            logger.warning(
                "audio.cache.put_begin failed for device %s, response %s",
                device_id,
                response_id,
            )
            return

        # Step 2: Stream PCM directly when backend supports it (OpenAI), else synthesize full WAV.
        first_chunk_sent_ms: float | None = None
        chunk_count = 0
        tts_total_ms: float | None = None

        if hasattr(self._tts, "synthesize_pcm_stream"):
            try:
                stream_iter = await asyncio.to_thread(self._tts.synthesize_pcm_stream, response_text, self._chunk_size)
                seq = 0
                for pcm_chunk in stream_iter:
                    data_b64 = encode_pcm_to_base64(pcm_chunk)
                    ok = await self._dispatcher.cache_put_chunk(device_id, response_id, seq, data_b64)
                    if not ok:
                        logger.warning(
                            "audio.cache.chunk (seq=%d) failed for device %s, response %s",
                            seq,
                            device_id,
                            response_id,
                        )
                        return
                    if seq == 0:
                        first_chunk_sent_ms = (time.perf_counter() - tts_start) * 1000
                    seq += 1
                chunk_count = seq
                tts_total_ms = (time.perf_counter() - tts_start) * 1000
            except Exception as exc:
                logger.exception("TTS streaming failed for response %s: %s", response_id, exc)
                return
        else:
            try:
                wav_bytes = await asyncio.to_thread(self._tts.synthesize, response_text)
            except Exception as exc:
                logger.exception("TTS synthesis failed for response %s: %s", response_id, exc)
                return
            tts_total_ms = (time.perf_counter() - tts_start) * 1000

            if not wav_bytes:
                logger.warning("TTS returned empty audio for response %s", response_id)
                return

            pcm_chunks = _wav_to_pcm_chunks(wav_bytes, self._chunk_size)
            if not pcm_chunks:
                logger.warning("No PCM data extracted from WAV for response %s", response_id)
                return

            try:
                for seq, pcm_chunk in enumerate(pcm_chunks):
                    data_b64 = encode_pcm_to_base64(pcm_chunk)
                    ok = await self._dispatcher.cache_put_chunk(device_id, response_id, seq, data_b64)
                    if not ok:
                        logger.warning(
                            "audio.cache.chunk (seq=%d) failed for device %s, response %s",
                            seq,
                            device_id,
                            response_id,
                        )
                        return
                    if seq == 0:
                        first_chunk_sent_ms = (time.perf_counter() - tts_start) * 1000
                chunk_count = len(pcm_chunks)
            except Exception as exc:
                logger.exception(
                    "Error sending chunks to device %s, response %s: %s",
                    device_id,
                    response_id,
                    exc,
                )
                return

        if chunk_count == 0:
            logger.warning("No PCM chunks produced for response %s", response_id)
            return

        # Step 3: Send cache_put_end
        ok = await self._dispatcher.cache_put_end(device_id, response_id, sha256=None)
        if not ok:
            logger.warning(
                "audio.cache.put_end failed for device %s, response %s",
                device_id,
                response_id,
            )
            return

        # Step 6: Emit audio_delivered event
        total_gateway_ms = (time.perf_counter() - tts_start) * 1000
        logger.info(
            "Audio delivered to device %s (response_id=%s, chunks=%d)",
            device_id,
            response_id,
            chunk_count,
        )
        logger.info(
            "TTS pipeline timing: response_id=%s chars=%d tts_total_ms=%.0f first_chunk_sent_ms=%.0f gateway_total_ms=%.0f chunks=%d",
            response_id,
            len(response_text),
            tts_total_ms or -1,
            first_chunk_sent_ms or -1,
            total_gateway_ms,
            chunk_count,
        )

        self._event_bus.emit("audio_delivered", device_id, {
            "response_id": response_id,
            "response_text": response_text,
            "stream_id": payload.get("stream_id"),
            "transcript": payload.get("transcript"),
            "device_context": payload.get("device_context"),
            "chunk_count": chunk_count,
        })
