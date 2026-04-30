"""Speech-to-text backend abstraction and implementations."""
from __future__ import annotations

import io
import json
import logging
import re
import struct
import time
import urllib.request
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass
class SttMetrics:
    """Metrics from an STT transcription operation."""
    duration_seconds: float
    text_length: int
    word_count: int
    language: str
    model: str
    inference_time_ms: float

    def to_dict(self) -> dict:
        """Convert to dictionary for logging."""
        return {
            "duration_seconds": self.duration_seconds,
            "text_length": self.text_length,
            "word_count": self.word_count,
            "language": self.language,
            "model": self.model,
            "inference_time_ms": self.inference_time_ms,
            "realtime_factor": self.inference_time_ms / 1000.0 / max(self.duration_seconds, 0.001),
        }


class SttBackend(Protocol):
    """Abstract interface for STT backends."""

    def transcribe(self, pcm_bytes: bytes, sample_rate: int = 16000) -> str:
        """Transcribe raw PCM audio to text.

        Parameters
        ----------
        pcm_bytes : bytes
            Raw PCM16 audio data (little-endian).
        sample_rate : int, optional
            Sample rate in Hz. Default 16000.

        Returns
        -------
        str
            Transcribed text.
        """
        ...


class FasterWhisperBackend:
    """Speech-to-text using faster-whisper library.

    Requires: pip install faster-whisper

    Enhanced with configurable options for accuracy, language, and advanced features.
    """

    def __init__(
        self,
        model: str = "base.en",
        device: str = "cpu",
        compute_type: str = "int8",
        language: str = "en",
        beam_size: int = 5,
        best_of: int = 5,
        temperature: float = 0.0,
        initial_prompt: str | None = None,
        word_timestamps: bool = False,
    ) -> None:
        """Initialize the Whisper model.

        Parameters
        ----------
        model : str
            Model name (e.g., "tiny.en", "base.en", "small.en", "medium.en").
        device : str
            Device to use ("cpu" or "cuda").
        compute_type : str
            Computation type ("float16", "int8", "int8_float16", "int8_float32").
        language : str
            Language code for transcription (e.g., "en", "de", "fr").
        beam_size : int
            Beam size for decoding (higher = more accurate, slower).
        best_of : int
            Number of candidates to consider (higher = better, slower).
        temperature : float
            Temperature for sampling (0.0 = deterministic, higher = more creative).
        initial_prompt : str, optional
            Initial prompt to guide transcription.
        word_timestamps : bool
            Whether to include word-level timestamps.
        """
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise ImportError(
                "faster-whisper is not installed. "
                "Install via: pip install faster-whisper"
            ) from exc

        self._model = WhisperModel(model, device=device, compute_type=compute_type)
        self._language = language
        self._beam_size = beam_size
        self._best_of = best_of
        self._temperature = temperature
        self._initial_prompt = initial_prompt
        self._word_timestamps = word_timestamps
        self._model_name = model

    def transcribe(self, pcm_bytes: bytes, sample_rate: int = 16000) -> tuple[str, SttMetrics]:
        """Transcribe PCM audio using faster-whisper.

        Parameters
        ----------
        pcm_bytes : bytes
            Raw PCM16 audio.
        sample_rate : int, optional
            Sample rate. Default 16000.

        Returns
        -------
        tuple[str, SttMetrics]
            Tuple of (transcribed text, metrics).
        """
        # Calculate duration for metrics
        duration_seconds = len(pcm_bytes) / (sample_rate * 2)  # 16-bit = 2 bytes per sample

        # Convert raw PCM to WAV in memory
        wav_bytes = pcm_to_wav(pcm_bytes, sample_rate=sample_rate, channels=1, bits=16)

        # Run transcription with timing
        start_time = time.perf_counter()
        segments, info = self._model.transcribe(
            io.BytesIO(wav_bytes),
            language=self._language,
            beam_size=self._beam_size,
            best_of=self._best_of,
            temperature=self._temperature,
            initial_prompt=self._initial_prompt,
            word_timestamps=self._word_timestamps,
            # Keep leading speech; VAD can trim short initial words (e.g. "I am").
            vad_filter=False,
        )
        inference_time_ms = (time.perf_counter() - start_time) * 1000

        # Concatenate segment texts
        text = " ".join(seg.text.strip() for seg in segments)

        # Create metrics
        metrics = SttMetrics(
            duration_seconds=duration_seconds,
            text_length=len(text),
            word_count=len(text.split()) if text else 0,
            language=info.language if hasattr(info, 'language') else self._language,
            model=self._model_name,
            inference_time_ms=inference_time_ms,
        )

        logger.info(
            "STT transcription: model=%s, duration=%.2fs, words=%d, inference_time=%.0fms, realtime_factor=%.2f",
            self._model_name,
            metrics.duration_seconds,
            metrics.word_count,
            metrics.inference_time_ms,
            metrics.to_dict().get("realtime_factor", 0),
        )

        return text, metrics

    def transcribe_simple(self, pcm_bytes: bytes, sample_rate: int = 16000) -> str:
        """Transcribe PCM audio (simple interface, no metrics).

        Parameters
        ----------
        pcm_bytes : bytes
            Raw PCM16 audio.
        sample_rate : int, optional
            Sample rate. Default 16000.

        Returns
        -------
        str
            Transcribed text.
        """
        text, _ = self.transcribe(pcm_bytes, sample_rate)
        return text


class OpenAiWhisperBackend:
    """Speech-to-text using OpenAI audio transcription API."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini-transcribe") -> None:
        if not api_key:
            raise ValueError("OpenAI API key is required")
        self._api_key = api_key
        self._model_name = model

    def transcribe(self, pcm_bytes: bytes, sample_rate: int = 16000) -> tuple[str, SttMetrics]:
        duration_seconds = len(pcm_bytes) / (sample_rate * 2)
        wav_bytes = pcm_to_wav(pcm_bytes, sample_rate=sample_rate, channels=1, bits=16)

        boundary = "----oi-gateway-boundary"
        parts = [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\n{self._model_name}\r\n",
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"response_format\"\r\n\r\njson\r\n",
            (
                f"--{boundary}\r\n"
                "Content-Disposition: form-data; name=\"file\"; filename=\"audio.wav\"\r\n"
                "Content-Type: audio/wav\r\n\r\n"
            ),
        ]
        body = b"".join(p.encode("utf-8") for p in parts) + wav_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

        req = urllib.request.Request(
            "https://api.openai.com/v1/audio/transcriptions",
            data=body,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )

        start_time = time.perf_counter()
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        inference_time_ms = (time.perf_counter() - start_time) * 1000

        text = str(payload.get("text", "")).strip()
        metrics = SttMetrics(
            duration_seconds=duration_seconds,
            text_length=len(text),
            word_count=len(text.split()) if text else 0,
            language="en",
            model=self._model_name,
            inference_time_ms=inference_time_ms,
        )
        return text, metrics


class StubSttBackend:
    """Stub backend for testing — returns a fixed transcript."""

    def __init__(self, response: str = "test transcript") -> None:
        """Initialize with a fixed response.

        Parameters
        ----------
        response : str
            The text to always return. Default "test transcript".
        """
        self._response = response

    def transcribe(self, pcm_bytes: bytes, sample_rate: int = 16000) -> tuple[str, SttMetrics]:
        """Return the fixed response (ignore input).

        Parameters
        ----------
        pcm_bytes : bytes
            Ignored.
        sample_rate : int, optional
            Ignored.

        Returns
        -------
        tuple[str, SttMetrics]
            Tuple of (fixed response, stub metrics).
        """
        duration_seconds = len(pcm_bytes) / (sample_rate * 2) if pcm_bytes else 0.0
        metrics = SttMetrics(
            duration_seconds=duration_seconds,
            text_length=len(self._response),
            word_count=len(self._response.split()) if self._response else 0,
            language="en",
            model="stub",
            inference_time_ms=0.0,
        )
        return self._response, metrics

    def transcribe_simple(self, pcm_bytes: bytes, sample_rate: int = 16000) -> str:
        """Return the fixed response (simple interface).

        Parameters
        ----------
        pcm_bytes : bytes
            Ignored.
        sample_rate : int, optional
            Ignored.

        Returns
        -------
        str
            The fixed response string.
        """
        return self._response


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def clean_transcript(raw: str) -> str:
    """Clean transcribed text by removing fillers and normalizing whitespace.

    Parameters
    ----------
    raw : str
        Raw transcription output.

    Returns
    -------
    str
        Cleaned text.
    """
    # Strip leading filler sounds (um, uh, hmm, ah, er, etc.)
    filler_pattern = r"^\s*(um|uh|hmm|ah|er|erm|like|you know|i mean)\s+"
    text = re.sub(filler_pattern, "", raw.strip(), flags=re.IGNORECASE)

    # Collapse multiple spaces
    text = re.sub(r"\s+", " ", text)

    # Ensure it ends with period if non-empty
    if text and not text.endswith((".", "!", "?")):
        text += "."

    return text


def pcm_to_wav(
    pcm_bytes: bytes,
    sample_rate: int = 16000,
    channels: int = 1,
    bits: int = 16,
) -> bytes:
    """Wrap raw PCM audio in a minimal RIFF WAV container.

    Parameters
    ----------
    pcm_bytes : bytes
        Raw PCM audio data.
    sample_rate : int, optional
        Sample rate in Hz. Default 16000.
    channels : int, optional
        Number of channels. Default 1 (mono).
    bits : int, optional
        Bits per sample. Default 16.

    Returns
    -------
    bytes
        Complete WAV file (RIFF format).
    """
    byte_rate = sample_rate * channels * bits // 8
    block_align = channels * bits // 8

    # WAV file structure (minimal):
    # - "RIFF" + file_size (4 bytes) + "WAVE"
    # - "fmt " (4 bytes) + chunk_size (4 bytes) + format_data (16 bytes minimum)
    # - "data" (4 bytes) + data_size (4 bytes) + pcm_bytes

    fmt_chunk = struct.pack(
        "<HHIIHH",
        1,                    # Format code: 1 = PCM
        channels,             # Number of channels
        sample_rate,          # Sample rate
        byte_rate,            # Byte rate
        block_align,          # Block align
        bits,                 # Bits per sample
    )

    data_size = len(pcm_bytes)
    file_size = 36 + data_size  # 36 bytes of header + data

    wav = b"RIFF"
    wav += struct.pack("<I", file_size)
    wav += b"WAVE"
    wav += b"fmt "
    wav += struct.pack("<I", len(fmt_chunk))
    wav += fmt_chunk
    wav += b"data"
    wav += struct.pack("<I", data_size)
    wav += pcm_bytes

    return wav
