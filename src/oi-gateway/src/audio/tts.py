"""Text-to-speech backend abstraction and implementations."""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import struct
import subprocess
import tempfile
import time
import urllib.request
import uuid
import wave
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass
class TtsMetrics:
    """Metrics from a TTS synthesis operation."""
    text_length: int
    word_count: int
    audio_duration_seconds: float
    sample_rate: int
    voice: str
    synthesis_time_ms: float
    audio_size_bytes: int

    def to_dict(self) -> dict:
        """Convert to dictionary for logging."""
        return {
            "text_length": self.text_length,
            "word_count": self.word_count,
            "audio_duration_seconds": self.audio_duration_seconds,
            "sample_rate": self.sample_rate,
            "voice": self.voice,
            "synthesis_time_ms": self.synthesis_time_ms,
            "audio_size_bytes": self.audio_size_bytes,
            "rtf": self.synthesis_time_ms / 1000.0 / max(self.audio_duration_seconds, 0.001),
        }


class TtsBackend(Protocol):
    """Abstract interface for TTS backends."""

    def synthesize(self, text: str) -> bytes:
        """Synthesize text to WAV audio.

        Parameters
        ----------
        text : str
            Text to synthesize.

        Returns
        -------
        bytes
            WAV audio data.
        """
        ...


class PiperTtsBackend:
    """Text-to-speech using Piper TTS engine.

    Requires: pip install piper-tts

    Enhanced with configurable synthesis options and audio post-processing.
    """

    def __init__(
        self,
        model_path: str | None = None,
        voice: str = "en_US-lessac-medium",
        noise_scale: float = 0.667,
        length_scale: float = 1.0,
        temperature: float = 1.0,
        sentence_silence: float = 0.2,
    ) -> None:
        """Initialize the Piper TTS engine.

        Parameters
        ----------
        model_path : str, optional
            Path to Piper model files. If not provided, uses the voice name
            to look for a default model.
        voice : str
            Voice name to use. Default "en_US-lessac-medium".
        noise_scale : float
            Noise scale (phoneme pitch variation). Lower = more stable.
            Default 0.667.
        length_scale : float
            Length scale (speech speed). Higher = slower.
            Default 1.0.
        temperature : float
            Temperature for sampling. Higher = more variation.
            Default 1.0.
        sentence_silence : float
            Silence between sentences in seconds. Default 0.2.
        """
        self._voice = voice
        self._noise_scale = noise_scale
        self._length_scale = length_scale
        self._temperature = temperature
        self._sentence_silence = sentence_silence

        self._mode = "unknown"
        self._synth = None
        self._piper_voice = None

        try:
            import piper_tts as piper_module
            if model_path:
                self._synth = piper_module.PiperSynthesizer(model_path=model_path)
            else:
                self._synth = piper_module.PiperSynthesizer.load_local(voice=voice)
            self._mode = "piper_tts"
            return
        except Exception:
            pass

        try:
            import piper
            resolved_model_path = model_path
            if not resolved_model_path:
                raise RuntimeError(
                    "piper module is available but no model path provided. "
                    "Set OI_PIPER_MODEL_PATH to a .onnx voice model file."
                )
            self._piper_voice = piper.PiperVoice.load(resolved_model_path)
            self._mode = "piper_voice"
            return
        except Exception as exc:
            raise ImportError(
                "No compatible Piper TTS runtime available. Install piper-tts with a compatible API "
                "or configure OI_PIPER_MODEL_PATH for piper.PiperVoice."
            ) from exc

    def synthesize(self, text: str) -> bytes:
        """Synthesize text to WAV using Piper.

        Parameters
        ----------
        text : str
            Text to synthesize.

        Returns
        -------
        bytes
            WAV audio data.
        """
        if self._mode == "piper_tts":
            return self._synth.synthesize_wav(text)

        if self._mode == "piper_voice":
            import numpy as np

            pcm = bytearray()
            sample_rate = 22050
            for chunk in self._piper_voice.synthesize(text):
                sample_rate = chunk.sample_rate
                floats = np.clip(chunk.audio_float_array, -1.0, 1.0)
                int16 = (floats * 32767.0).astype(np.int16)
                pcm.extend(int16.tobytes())

            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(bytes(pcm))
            return buf.getvalue()

        raise RuntimeError("Piper backend not initialized")

    def synthesize_with_metrics(self, text: str) -> tuple[bytes, TtsMetrics]:
        """Synthesize text with metrics tracking.

        Parameters
        ----------
        text : str
            Text to synthesize.

        Returns
        -------
        tuple[bytes, TtsMetrics]
            Tuple of (WAV audio data, synthesis metrics).
        """
        start_time = time.perf_counter()
        wav_bytes = self.synthesize(text)
        synthesis_time_ms = (time.perf_counter() - start_time) * 1000

        # Extract audio properties from WAV
        sample_rate = _get_wav_sample_rate(wav_bytes)
        audio_duration_seconds = _get_wav_duration(wav_bytes, sample_rate)

        metrics = TtsMetrics(
            text_length=len(text),
            word_count=len(text.split()) if text else 0,
            audio_duration_seconds=audio_duration_seconds,
            sample_rate=sample_rate,
            voice=self._voice,
            synthesis_time_ms=synthesis_time_ms,
            audio_size_bytes=len(wav_bytes),
        )

        logger.info(
            "TTS synthesis: voice=%s, duration=%.2fs, words=%d, synthesis_time=%.0fms, audio_size=%d bytes",
            self._voice,
            metrics.audio_duration_seconds,
            metrics.word_count,
            metrics.synthesis_time_ms,
            metrics.audio_size_bytes,
        )

        return wav_bytes, metrics


def _make_minimal_wav() -> bytes:
    """Create a minimal valid WAV file with a short silent PCM chunk."""
    import struct
    sample_rate = 16000
    num_channels = 1
    bits_per_sample = 16
    num_samples = 1600  # 100ms of audio
    data_size = num_samples * num_channels * (bits_per_sample // 8)
    wav = b"RIFF"
    wav += struct.pack("<I", 4 + 24 + data_size)  # file size - 8
    wav += b"WAVE"
    wav += b"fmt "
    wav += struct.pack("<I", 16)  # fmt chunk size
    wav += struct.pack("<H", 1)   # PCM format
    wav += struct.pack("<H", num_channels)
    wav += struct.pack("<I", sample_rate)
    wav += struct.pack("<I", sample_rate * num_channels * bits_per_sample // 8)  # byte rate
    wav += struct.pack("<H", num_channels * bits_per_sample // 8)  # block align
    wav += struct.pack("<H", bits_per_sample)
    wav += b"data"
    wav += struct.pack("<I", data_size)
    wav += b"\x00" * data_size  # silent samples
    return wav


class EspeakNgTtsBackend:
    """Text-to-speech using espeak-ng CLI."""

    def __init__(self, voice: str = "en") -> None:
        self._voice = voice

    def synthesize(self, text: str) -> bytes:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            out = tmp.name
        try:
            subprocess.run(
                ["espeak-ng", "-v", self._voice, "-w", out, text],
                check=True,
                capture_output=True,
                text=True,
            )
            with open(out, "rb") as f:
                return f.read()
        finally:
            if os.path.exists(out):
                os.unlink(out)


class OpenAiTtsBackend:
    """Text-to-speech using OpenAI audio speech API."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini-tts", voice: str = "alloy") -> None:
        if not api_key:
            raise ValueError("OpenAI API key is required")
        self._api_key = api_key
        self._model = model
        self._voice = voice

    def synthesize(self, text: str) -> bytes:
        payload = {
            "model": self._model,
            "voice": self._voice,
            "input": text,
            "format": "wav",
        }
        req = urllib.request.Request(
            "https://api.openai.com/v1/audio/speech",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()


class StubTtsBackend:
    """Stub backend for testing — returns a valid WAV response."""

    _wav: bytes = _make_minimal_wav()  # class-level shared WAV

    def __init__(self, response_wav: bytes | None = None) -> None:
        """Initialize with an optional custom WAV response."""
        self._response_wav = response_wav or self._wav

    def synthesize(self, text: str) -> bytes:
        """Return the fixed WAV response (ignore input)."""
        return self._response_wav


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def generate_response_id() -> str:
    """Generate a unique response ID.

    Returns
    -------
    str
        Unique response identifier (e.g. "resp_a1b2c3d4e5f6").
    """
    return f"resp_{uuid.uuid4().hex[:12]}"


def text_to_wav(text: str) -> bytes:
    """Convert text to WAV using Piper TTS.

    This is a convenience function that creates a PiperTtsBackend
    and synthesizes the text in one call.

    Parameters
    ----------
    text : str
        Text to synthesize.

    Returns
    -------
    bytes
        WAV audio data.

    Raises
    ------
    ImportError
        If piper-tts is not installed.
    """
    backend = PiperTtsBackend()
    return backend.synthesize(text)


def _wav_to_pcm_chunks(wav_data: bytes, chunk_size: int = 1024) -> list[bytes]:
    """Extract PCM data from WAV and split into chunks.

    Parameters
    ----------
    wav_data : bytes
        Complete WAV file data.
    chunk_size : int, optional
        Size of each chunk in bytes. Default 1024.

    Returns
    -------
    list[bytes]
        List of PCM chunks (not base64-encoded).
    """
    # Find the 'data' chunk and extract PCM
    pcm_data = _extract_pcm_from_wav(wav_data)
    if not pcm_data:
        return []

    # Split into chunks
    chunks = []
    for i in range(0, len(pcm_data), chunk_size):
        chunks.append(pcm_data[i:i + chunk_size])

    return chunks


def _extract_pcm_from_wav(wav_data: bytes) -> bytes:
    """Extract raw PCM data from a WAV file.

    Parameters
    ----------
    wav_data : bytes
        Complete WAV file data.

    Returns
    -------
    bytes
        Raw PCM audio data, or empty bytes if extraction fails.
    """
    try:
        # Find 'data' chunk marker
        data_index = wav_data.find(b"data")
        if data_index == -1:
            logger.warning("No 'data' chunk found in WAV")
            return b""

        # data chunk starts with 'data' (4 bytes) + size (4 bytes)
        # PCM data follows immediately after the size field
        pcm_start = data_index + 8
        if pcm_start > len(wav_data):
            return b""

        return wav_data[pcm_start:]
    except Exception as exc:
        logger.warning("Failed to extract PCM from WAV: %s", exc)
        return b""


def encode_pcm_to_base64(pcm_bytes: bytes) -> str:
    """Encode PCM bytes to base64 string.

    Parameters
    ----------
    pcm_bytes : bytes
        Raw PCM audio bytes.

    Returns
    -------
    str
        Base64-encoded string.
    """
    return base64.b64encode(pcm_bytes).decode("ascii")


# ------------------------------------------------------------------
# WAV Helpers
# ------------------------------------------------------------------


def _get_wav_sample_rate(wav_data: bytes) -> int:
    """Extract sample rate from WAV data.

    Parameters
    ----------
    wav_data : bytes
        Complete WAV file data.

    Returns
    -------
    int
        Sample rate in Hz, or default 22050 if extraction fails.
    """
    try:
        # Look for 'fmt ' chunk (typically at offset 12)
        fmt_index = wav_data.find(b"fmt ")
        if fmt_index == -1 or len(wav_data) < fmt_index + 24:
            return 22050

        # After 'fmt ' (4 bytes) comes chunk size (4 bytes)
        # Then format data starts: format (2), channels (2), sample_rate (4)
        sample_rate_offset = fmt_index + 12  # 4 (fmt ) + 4 (size) + 4 (format data starts)
        return struct.unpack("<I", wav_data[sample_rate_offset:sample_rate_offset + 4])[0]
    except Exception:
        return 22050


def _get_wav_duration(wav_data: bytes, sample_rate: int) -> float:
    """Calculate duration of WAV audio in seconds.

    Parameters
    ----------
    wav_data : bytes
        Complete WAV file data.
    sample_rate : int
        Sample rate in Hz.

    Returns
    -------
    float
        Duration in seconds.
    """
    pcm_data = _extract_pcm_from_wav(wav_data)
    if not pcm_data or sample_rate == 0:
        return 0.0
    # Assuming 16-bit mono (2 bytes per sample)
    num_samples = len(pcm_data) // 2
    return num_samples / sample_rate


# ------------------------------------------------------------------
# Audio Validation
# ------------------------------------------------------------------


@dataclass
class AudioValidationResult:
    """Result of audio validation."""
    is_valid: bool
    errors: list[str]
    warnings: list[str]
    sample_rate: int
    channels: int
    bits_per_sample: int
    duration_seconds: float
    byte_size: int


def validate_pcm_format(
    pcm_bytes: bytes,
    sample_rate: int = 16000,
    expected_channels: int = 1,
    expected_bits: int = 16,
    min_duration: float = 0.1,
    max_duration: float = 300.0,
) -> AudioValidationResult:
    """Validate raw PCM audio format.

    Parameters
    ----------
    pcm_bytes : bytes
        Raw PCM audio data.
    sample_rate : int, optional
        Expected sample rate. Default 16000.
    expected_channels : int, optional
        Expected number of channels. Default 1.
    expected_bits : int, optional
        Expected bits per sample. Default 16.
    min_duration : float, optional
        Minimum acceptable duration in seconds. Default 0.1.
    max_duration : float, optional
        Maximum acceptable duration in seconds. Default 300 (5 minutes).

    Returns
    -------
    AudioValidationResult
        Validation result with errors and warnings.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Check empty
    if not pcm_bytes:
        return AudioValidationResult(
            is_valid=False,
            errors=["Empty PCM data"],
            warnings=[],
            sample_rate=sample_rate,
            channels=expected_channels,
            bits_per_sample=expected_bits,
            duration_seconds=0.0,
            byte_size=0,
        )

    # Calculate duration
    bytes_per_sample = expected_channels * (expected_bits // 8)
    num_samples = len(pcm_bytes) // bytes_per_sample
    duration = num_samples / sample_rate if sample_rate > 0 else 0.0

    # Check duration bounds
    if duration < min_duration:
        errors.append(f"Audio too short: {duration:.2f}s (min: {min_duration}s)")
    elif duration > max_duration:
        errors.append(f"Audio too long: {duration:.2f}s (max: {max_duration}s)")

    # Check alignment
    if len(pcm_bytes) % bytes_per_sample != 0:
        warnings.append(f"PCM data not aligned to expected format (remainder: {len(pcm_bytes) % bytes_per_sample})")

    # Check for likely silence (all zeros or all max values)
    if len(pcm_bytes) > 0:
        # Sample some bytes to check for silence
        sample_size = min(1024, len(pcm_bytes))
        if pcm_bytes[:sample_size] == b"\x00" * sample_size:
            warnings.append("Audio appears to be silent (all zeros)")

    return AudioValidationResult(
        is_valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        sample_rate=sample_rate,
        channels=expected_channels,
        bits_per_sample=expected_bits,
        duration_seconds=duration,
        byte_size=len(pcm_bytes),
    )


def validate_wav_format(
    wav_bytes: bytes,
    min_duration: float = 0.1,
    max_duration: float = 300.0,
) -> AudioValidationResult:
    """Validate WAV audio format.

    Parameters
    ----------
    wav_bytes : bytes
        WAV file data.
    min_duration : float, optional
        Minimum acceptable duration in seconds. Default 0.1.
    max_duration : float, optional
        Maximum acceptable duration in seconds. Default 300.

    Returns
    -------
    AudioValidationResult
        Validation result with errors and warnings.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Check header
    if len(wav_bytes) < 44:
        return AudioValidationResult(
            is_valid=False,
            errors=["WAV file too small (less than header size)"],
            warnings=[],
            sample_rate=0,
            channels=0,
            bits_per_sample=0,
            duration_seconds=0.0,
            byte_size=len(wav_bytes),
        )

    # Check RIFF header
    if not wav_bytes.startswith(b"RIFF"):
        errors.append("Invalid RIFF header")
    if not wav_bytes[8:12] == b"WAVE":
        errors.append("Invalid WAVE format")

    # Find fmt chunk
    fmt_index = wav_bytes.find(b"fmt ")
    if fmt_index == -1:
        errors.append("Missing fmt chunk")
    else:
        # Parse fmt chunk
        try:
            # After 'fmt ' (4 bytes) + chunk size (4 bytes)
            fmt_data_start = fmt_index + 8
            if len(wav_bytes) >= fmt_data_start + 16:
                channels = struct.unpack("<H", wav_bytes[fmt_data_start + 2:fmt_data_start + 4])[0]
                sample_rate = struct.unpack("<I", wav_bytes[fmt_data_start + 4:fmt_data_start + 8])[0]
                bits = struct.unpack("<H", wav_bytes[fmt_data_start + 14:fmt_data_start + 16])[0]
            else:
                channels, sample_rate, bits = 1, 22050, 16
        except Exception:
            channels, sample_rate, bits = 1, 22050, 16
            warnings.append("Could not parse fmt chunk fully")

    # Find data chunk
    data_index = wav_bytes.find(b"data")
    if data_index == -1:
        errors.append("Missing data chunk")
        return AudioValidationResult(
            is_valid=False,
            errors=errors,
            warnings=warnings,
            sample_rate=sample_rate if 'sample_rate' in dir() else 0,
            channels=channels if 'channels' in dir() else 0,
            bits_per_sample=bits if 'bits' in dir() else 0,
            duration_seconds=0.0,
            byte_size=len(wav_bytes),
        )

    # Calculate duration
    data_size = len(wav_bytes) - data_index - 8
    if data_size > 0 and sample_rate > 0:
        bytes_per_sample = channels * (bits // 8)
        num_samples = data_size // bytes_per_sample
        duration = num_samples / sample_rate
    else:
        duration = 0.0

    # Check duration bounds
    if duration < min_duration:
        errors.append(f"Audio too short: {duration:.2f}s (min: {min_duration}s)")
    elif duration > max_duration:
        errors.append(f"Audio too long: {duration:.2f}s (max: {max_duration}s)")

    return AudioValidationResult(
        is_valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        sample_rate=sample_rate,
        channels=channels,
        bits_per_sample=bits,
        duration_seconds=duration,
        byte_size=len(wav_bytes),
    )


# ------------------------------------------------------------------
# Audio Normalization and Quality Metrics
# ------------------------------------------------------------------


@dataclass
class AudioQualityMetrics:
    """Audio quality metrics."""
    rms_level_dbfs: float
    peak_level_dbfs: float
    snr_db: float | None
    silence_ratio: float
    clipping_ratio: float
    dynamic_range_db: float

    def to_dict(self) -> dict:
        """Convert to dictionary for logging."""
        return {
            "rms_level_dbfs": self.rms_level_dbfs,
            "peak_level_dbfs": self.peak_level_dbfs,
            "snr_db": self.snr_db,
            "silence_ratio": self.silence_ratio,
            "clipping_ratio": self.clipping_ratio,
            "dynamic_range_db": self.dynamic_range_db,
        }


def measure_audio_level(pcm_bytes: bytes, bits_per_sample: int = 16) -> float:
    """Calculate RMS audio level in dBFS.

    Parameters
    ----------
    pcm_bytes : bytes
        Raw PCM audio data.
    bits_per_sample : int, optional
        Bits per sample. Default 16.

    Returns
    -------
    float
        RMS level in dBFS (-inf to 0).
    """
    import math

    if not pcm_bytes:
        return float("-inf")

    # Convert bytes to samples
    if bits_per_sample == 16:
        # Parse as signed 16-bit integers
        num_samples = len(pcm_bytes) // 2
        try:
            samples = struct.unpack(f"<{num_samples}h", pcm_bytes)
        except struct.error:
            return float("-inf")
    elif bits_per_sample == 8:
        num_samples = len(pcm_bytes)
        try:
            samples = struct.unpack(f"<{num_samples}B", pcm_bytes)
            # Convert from unsigned to signed
            samples = [s - 128 for s in samples]
        except struct.error:
            return float("-inf")
    else:
        return float("-inf")

    if not samples:
        return float("-inf")

    # Calculate RMS
    sum_squares = sum(s * s for s in samples)
    rms = (sum_squares / len(samples)) ** 0.5

    if rms == 0:
        return float("-inf")

    # Convert to dBFS using log scale (assuming max amplitude is the max representable value)
    max_amplitude = (1 << (bits_per_sample - 1)) - 1
    rms_dbfs = 20 * math.log10(rms / max_amplitude)

    return rms_dbfs


def measure_peak_level(pcm_bytes: bytes, bits_per_sample: int = 16) -> float:
    """Calculate peak audio level in dBFS.

    Parameters
    ----------
    pcm_bytes : bytes
        Raw PCM audio data.
    bits_per_sample : int, optional
        Bits per sample. Default 16.

    Returns
    -------
    float
        Peak level in dBFS (-inf to 0).
    """
    import math

    if not pcm_bytes:
        return float("-inf")

    # Convert bytes to samples
    if bits_per_sample == 16:
        num_samples = len(pcm_bytes) // 2
        try:
            samples = struct.unpack(f"<{num_samples}h", pcm_bytes)
        except struct.error:
            return float("-inf")
    elif bits_per_sample == 8:
        num_samples = len(pcm_bytes)
        try:
            samples = struct.unpack(f"<{num_samples}B", pcm_bytes)
            samples = [s - 128 for s in samples]
        except struct.error:
            return float("-inf")
    else:
        return float("-inf")

    if not samples:
        return float("-inf")

    # Find peak
    max_amplitude = max(abs(s) for s in samples)

    if max_amplitude == 0:
        return float("-inf")

    max_representable = (1 << (bits_per_sample - 1)) - 1
    peak_dbfs = 20 * math.log10(max_amplitude / max_representable)

    return peak_dbfs


def calculate_snr(pcm_bytes: bytes, bits_per_sample: int = 16) -> float | None:
    """Calculate Signal-to-Noise Ratio in dB.

    Estimates noise floor from the quietest portion of the audio.

    Parameters
    ----------
    pcm_bytes : bytes
        Raw PCM audio data.
    bits_per_sample : int, optional
        Bits per sample. Default 16.

    Returns
    -------
    float | None
        SNR in dB, or None if calculation fails.
    """
    import math

    if not pcm_bytes:
        return None

    if bits_per_sample == 16:
        num_samples = len(pcm_bytes) // 2
        try:
            samples = struct.unpack(f"<{num_samples}h", pcm_bytes)
        except struct.error:
            return None
    else:
        return None

    if len(samples) < 100:
        return None

    # Divide into windows and find the quietest section
    window_size = len(samples) // 10
    if window_size < 100:
        window_size = 100

    window_rms = []
    for i in range(0, len(samples) - window_size, window_size // 2):
        window = samples[i:i + window_size]
        rms = (sum(s * s for s in window) / len(window)) ** 0.5
        window_rms.append(rms)

    if not window_rms:
        return None

    # Use 10th percentile as noise floor estimate
    sorted_rms = sorted(window_rms)
    noise_floor_idx = max(0, len(sorted_rms) // 10)
    noise_floor_rms = sorted_rms[noise_floor_idx]

    # Use peak as signal estimate
    signal_peak = max(abs(s) for s in samples)

    if noise_floor_rms == 0 or signal_peak == 0:
        return None

    max_representable = (1 << (bits_per_sample - 1)) - 1
    signal_db = 20 * math.log10(signal_peak / max_representable)
    noise_db = 20 * math.log10(noise_floor_rms / max_representable)

    return signal_db - noise_db


def detect_silence(
    pcm_bytes: bytes,
    sample_rate: int = 16000,
    threshold_dbfs: float = -50.0,
    min_duration: float = 0.3,
) -> list[tuple[float, float]]:
    """Detect silent portions in audio.

    Parameters
    ----------
    pcm_bytes : bytes
        Raw PCM audio data.
    sample_rate : int, optional
        Sample rate. Default 16000.
    threshold_dbfs : float, optional
        Silence threshold in dBFS. Default -50.0.
    min_duration : float, optional
        Minimum silence duration to report. Default 0.3s.

    Returns
    -------
    list[tuple[float, float]]
        List of (start_time, end_time) tuples for silent portions.
    """
    if not pcm_bytes or sample_rate == 0:
        return []

    # Convert threshold from dB to linear
    threshold_linear = 10 ** (threshold_dbfs / 20)

    # Convert bytes to samples
    num_samples = len(pcm_bytes) // 2
    try:
        samples = struct.unpack(f"<{num_samples}h", pcm_bytes)
    except struct.error:
        return []

    max_amplitude = (1 << 15) - 1  # 16-bit max
    threshold_samples = int(threshold_linear * max_amplitude)

    # Window-based analysis
    window_size = int(sample_rate * 0.05)  # 50ms windows
    is_silent = []

    for i in range(0, len(samples), window_size):
        window = samples[i:min(i + window_size, len(samples))]
        rms = (sum(s * s for s in window) / len(window)) ** 0.5
        is_silent.append(rms < threshold_samples)

    # Find contiguous silent regions
    silent_regions = []
    start_idx = None

    for i, silent in enumerate(is_silent):
        if silent and start_idx is None:
            start_idx = i
        elif not silent and start_idx is not None:
            start_time = (start_idx * window_size) / sample_rate
            end_time = (i * window_size) / sample_rate
            if end_time - start_time >= min_duration:
                silent_regions.append((start_time, end_time))
            start_idx = None

    # Handle trailing silence
    if start_idx is not None:
        start_time = (start_idx * window_size) / sample_rate
        end_time = len(samples) / sample_rate
        if end_time - start_time >= min_duration:
            silent_regions.append((start_time, end_time))

    return silent_regions


def trim_silence(
    pcm_bytes: bytes,
    sample_rate: int = 16000,
    threshold_dbfs: float = -40.0,
    max_trim_seconds: float = 2.0,
) -> bytes:
    """Trim leading and trailing silence from PCM audio.

    Parameters
    ----------
    pcm_bytes : bytes
        Raw PCM audio data.
    sample_rate : int, optional
        Sample rate. Default 16000.
    threshold_dbfs : float, optional
        Silence threshold in dBFS. Default -40.0.
    max_trim_seconds : float, optional
        Maximum silence to trim from start/end. Default 2.0.

    Returns
    -------
    bytes
        Trimmed PCM audio.
    """
    if not pcm_bytes or sample_rate == 0:
        return pcm_bytes

    # Convert threshold from dB to linear
    threshold_linear = 10 ** (threshold_dbfs / 20)

    # Convert bytes to samples
    num_samples = len(pcm_bytes) // 2
    try:
        samples = list(struct.unpack(f"<{num_samples}h", pcm_bytes))
    except struct.error:
        return pcm_bytes

    max_amplitude = (1 << 15) - 1
    threshold_samples = int(threshold_linear * max_amplitude)
    max_trim_samples = int(max_trim_seconds * sample_rate)

    # Find leading non-silence
    start_idx = 0
    window_size = min(512, sample_rate // 100)  # 10ms windows

    for i in range(0, min(max_trim_samples, len(samples)), window_size):
        window = samples[i:min(i + window_size, len(samples))]
        rms = (sum(s * s for s in window) / len(window)) ** 0.5
        if rms >= threshold_samples:
            start_idx = i
            break

    # Find trailing non-silence
    end_idx = len(samples)
    for i in range(len(samples) - 1, max(len(samples) - max_trim_samples, start_idx), -window_size):
        window = samples[max(0, i - window_size):i]
        rms = (sum(s * s for s in window) / len(window)) ** 0.5
        if rms >= threshold_samples:
            end_idx = i
            break

    # Return trimmed samples
    trimmed = samples[start_idx:end_idx]
    return struct.pack(f"<{len(trimmed)}h", *trimmed)


def calculate_quality_metrics(pcm_bytes: bytes, bits_per_sample: int = 16) -> AudioQualityMetrics:
    """Calculate comprehensive audio quality metrics.

    Parameters
    ----------
    pcm_bytes : bytes
        Raw PCM audio data.
    bits_per_sample : int, optional
        Bits per sample. Default 16.

    Returns
    -------
    AudioQualityMetrics
        Quality metrics.
    """
    import math

    if not pcm_bytes:
        return AudioQualityMetrics(
            rms_level_dbfs=float("-inf"),
            peak_level_dbfs=float("-inf"),
            snr_db=None,
            silence_ratio=1.0,
            clipping_ratio=0.0,
            dynamic_range_db=0.0,
        )

    # Convert bytes to samples
    if bits_per_sample == 16:
        num_samples = len(pcm_bytes) // 2
        try:
            samples = struct.unpack(f"<{num_samples}h", pcm_bytes)
        except struct.error:
            samples = []
    else:
        samples = []

    if not samples:
        return AudioQualityMetrics(
            rms_level_dbfs=float("-inf"),
            peak_level_dbfs=float("-inf"),
            snr_db=None,
            silence_ratio=1.0,
            clipping_ratio=0.0,
            dynamic_range_db=0.0,
        )

    # Calculate RMS
    rms = (sum(s * s for s in samples) / len(samples)) ** 0.5
    max_amplitude = (1 << (bits_per_sample - 1)) - 1
    rms_dbfs = 20 * math.log10(rms / max_amplitude) if rms > 0 else float("-inf")

    # Calculate peak
    peak = max(abs(s) for s in samples)
    peak_dbfs = 20 * math.log10(peak / max_amplitude) if peak > 0 else float("-inf")

    # Calculate SNR
    snr_db = calculate_snr(pcm_bytes, bits_per_sample)

    # Calculate silence ratio
    threshold_samples = int(0.01 * max_amplitude)  # -40 dB threshold
    silent_samples = sum(1 for s in samples if abs(s) < threshold_samples)
    silence_ratio = silent_samples / len(samples)

    # Calculate clipping ratio (samples at or near max)
    clipping_threshold = int(0.99 * max_amplitude)
    clipping_samples = sum(1 for s in samples if abs(s) >= clipping_threshold)
    clipping_ratio = clipping_samples / len(samples)

    # Calculate dynamic range
    non_silent_samples = [s for s in samples if abs(s) > threshold_samples]
    if non_silent_samples:
        max_val = max(abs(s) for s in non_silent_samples)
        min_val = min(abs(s) for s in non_silent_samples)
        dynamic_range_db = 20 * math.log10(max_val / min_val) if min_val > 0 else 0.0
    else:
        dynamic_range_db = 0.0

    return AudioQualityMetrics(
        rms_level_dbfs=rms_dbfs,
        peak_level_dbfs=peak_dbfs,
        snr_db=snr_db,
        silence_ratio=silence_ratio,
        clipping_ratio=clipping_ratio,
        dynamic_range_db=dynamic_range_db,
    )


def log_audio_metrics(
    operation: str,
    pcm_bytes: bytes | None = None,
    wav_bytes: bytes | None = None,
    metrics: AudioQualityMetrics | None = None,
    extra: dict | None = None,
) -> None:
    """Log audio metrics.

    Parameters
    ----------
    operation : str
        Operation name (e.g., "STT input", "TTS output").
    pcm_bytes : bytes, optional
        Raw PCM audio data.
    wav_bytes : bytes, optional
        WAV audio data.
    metrics : AudioQualityMetrics, optional
        Pre-calculated metrics.
    extra : dict, optional
        Additional fields to log.
    """
    if metrics is None and pcm_bytes:
        metrics = calculate_quality_metrics(pcm_bytes)

    if metrics:
        logger.info(
            "Audio quality [%s]: rms=%.1f dBFS, peak=%.1f dBFS, SNR=%s dB, silence=%.1f%%, clipping=%.2f%%, dynamic_range=%.1f dB",
            operation,
            metrics.rms_level_dbfs,
            metrics.peak_level_dbfs,
            f"{metrics.snr_db:.1f}" if metrics.snr_db is not None else "N/A",
            metrics.silence_ratio * 100,
            metrics.clipping_ratio * 100,
            metrics.dynamic_range_db,
        )

    if extra:
        logger.info("Audio extra [%s]: %s", operation, extra)
