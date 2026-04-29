"""Tests for audio quality improvements: validation, normalization, metrics."""
import struct
import sys
from pathlib import Path

import pytest

# Add the gateway source to path for imports
gateway_src = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(gateway_src))

from audio import (
    AudioQualityMetrics,
    AudioValidationResult,
    StubSttBackend,
    SttMetrics,
    TtsMetrics,
    calculate_quality_metrics,
    detect_silence,
    log_audio_metrics,
    pcm_to_wav,
    trim_silence,
    validate_pcm_format,
    validate_wav_format,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def make_test_pcm(duration_seconds: float, sample_rate: int = 16000, frequency: float = 440.0) -> bytes:
    """Generate test PCM audio data (sine wave)."""
    import math
    num_samples = int(duration_seconds * sample_rate)
    # Generate a simple sine wave at the given frequency with 50% amplitude
    samples = []
    max_amplitude = 32767 // 2  # 50% to avoid clipping
    for i in range(num_samples):
        # Simple sine wave
        value = int(max_amplitude * math.sin(2 * math.pi * frequency * i / sample_rate))
        samples.append(value)
    return struct.pack(f"<{num_samples}h", *samples)


def make_test_wav(duration_seconds: float, sample_rate: int = 16000, frequency: float = 440.0) -> bytes:
    """Generate test WAV audio data."""
    pcm = make_test_pcm(duration_seconds, sample_rate, frequency)
    return pcm_to_wav(pcm, sample_rate=sample_rate, channels=1, bits=16)


def make_silent_pcm(duration_seconds: float, sample_rate: int = 16000) -> bytes:
    """Generate silent PCM audio data."""
    num_samples = int(duration_seconds * sample_rate)
    return b"\x00\x00" * num_samples


# ------------------------------------------------------------------
# Tests: STT Metrics
# ------------------------------------------------------------------


def test_stt_metrics_creation():
    """Verify SttMetrics dataclass creation and to_dict."""
    metrics = SttMetrics(
        duration_seconds=2.5,
        text_length=100,
        word_count=15,
        language="en",
        model="base.en",
        inference_time_ms=150.0,
    )

    result = metrics.to_dict()

    assert result["duration_seconds"] == 2.5
    assert result["text_length"] == 100
    assert result["word_count"] == 15
    assert result["language"] == "en"
    assert result["model"] == "base.en"
    assert result["inference_time_ms"] == 150.0
    assert "realtime_factor" in result


def test_stub_stt_backend_returns_metrics():
    """Verify StubSttBackend returns tuple with metrics."""
    backend = StubSttBackend(response="test response")

    pcm = make_test_pcm(1.0)
    text, metrics = backend.transcribe(pcm, sample_rate=16000)

    assert text == "test response"
    assert isinstance(metrics, SttMetrics)
    assert metrics.model == "stub"
    assert metrics.duration_seconds > 0


def test_stub_stt_backend_transcribe_simple():
    """Verify StubSttBackend.transcribe_simple returns just text."""
    backend = StubSttBackend(response="simple response")

    text = backend.transcribe_simple(b"ignored", sample_rate=16000)

    assert text == "simple response"


# ------------------------------------------------------------------
# Tests: TTS Metrics
# ------------------------------------------------------------------


def test_tts_metrics_creation():
    """Verify TtsMetrics dataclass creation and to_dict."""
    metrics = TtsMetrics(
        text_length=50,
        word_count=8,
        audio_duration_seconds=3.0,
        sample_rate=22050,
        voice="en_US-lessac-medium",
        synthesis_time_ms=200.0,
        audio_size_bytes=66000,
    )

    result = metrics.to_dict()

    assert result["text_length"] == 50
    assert result["word_count"] == 8
    assert result["audio_duration_seconds"] == 3.0
    assert result["sample_rate"] == 22050
    assert result["voice"] == "en_US-lessac-medium"
    assert "rtf" in result  # Real-time factor


# ------------------------------------------------------------------
# Tests: Audio Validation (PCM)
# ------------------------------------------------------------------


def test_validate_pcm_format_valid():
    """Verify PCM validation passes for valid audio."""
    pcm = make_test_pcm(1.0)

    result = validate_pcm_format(pcm, sample_rate=16000)

    assert result.is_valid
    assert len(result.errors) == 0
    assert result.sample_rate == 16000
    assert result.channels == 1
    assert result.bits_per_sample == 16
    assert 0.9 < result.duration_seconds < 1.1


def test_validate_pcm_format_too_short():
    """Verify PCM validation fails for too-short audio."""
    pcm = make_test_pcm(0.05)  # 50ms - below 100ms minimum

    result = validate_pcm_format(pcm, sample_rate=16000, min_duration=0.1)

    assert not result.is_valid
    assert any("too short" in e.lower() for e in result.errors)


def test_validate_pcm_format_too_long():
    """Verify PCM validation fails for too-long audio."""
    pcm = make_test_pcm(400)  # 400 seconds - above 300s maximum

    result = validate_pcm_format(pcm, sample_rate=16000, max_duration=300.0)

    assert not result.is_valid
    assert any("too long" in e.lower() for e in result.errors)


def test_validate_pcm_format_empty():
    """Verify PCM validation fails for empty data."""
    result = validate_pcm_format(b"", sample_rate=16000)

    assert not result.is_valid
    assert "empty" in result.errors[0].lower()


def test_validate_pcm_format_silent():
    """Verify PCM validation warns for silent audio."""
    pcm = make_silent_pcm(1.0)

    result = validate_pcm_format(pcm, sample_rate=16000)

    # Should still be valid but have a warning
    assert result.is_valid
    assert any("silent" in w.lower() for w in result.warnings)


# ------------------------------------------------------------------
# Tests: Audio Validation (WAV)
# ------------------------------------------------------------------


def test_validate_wav_format_valid():
    """Verify WAV validation passes for valid audio."""
    wav = make_test_wav(1.0)

    result = validate_wav_format(wav)

    assert result.is_valid
    assert len(result.errors) == 0


def test_validate_wav_format_invalid_header():
    """Verify WAV validation fails for invalid header."""
    # Create a small file that has "RIFF" at start but invalid
    wav = b"RIFF\x00\x00\x00\x00INVALID"

    result = validate_wav_format(wav)

    assert not result.is_valid


def test_validate_wav_format_too_short():
    """Verify WAV validation fails for too-short audio."""
    wav = make_test_wav(0.05)  # 50ms - below 100ms minimum

    result = validate_wav_format(wav, min_duration=0.1)

    assert not result.is_valid


def test_validate_wav_format_too_long():
    """Verify WAV validation fails for too-long audio."""
    wav = make_test_wav(400)  # 400 seconds

    result = validate_wav_format(wav, max_duration=300.0)

    assert not result.is_valid


# ------------------------------------------------------------------
# Tests: WAV Helpers
# ------------------------------------------------------------------


def test_get_wav_sample_rate():
    """Verify WAV sample rate extraction via validation."""
    wav = make_test_wav(1.0, sample_rate=22050)

    result = validate_wav_format(wav)

    assert result.sample_rate == 22050


def test_get_wav_duration():
    """Verify WAV duration calculation via validation."""
    wav = make_test_wav(2.0, sample_rate=16000)

    result = validate_wav_format(wav)

    assert 1.9 < result.duration_seconds < 2.1


# ------------------------------------------------------------------
# Tests: Audio Quality Metrics
# ------------------------------------------------------------------


def test_calculate_quality_metrics_normal():
    """Verify audio quality metrics calculation for normal audio."""
    pcm = make_test_pcm(1.0, frequency=440.0)

    metrics = calculate_quality_metrics(pcm)

    assert isinstance(metrics, AudioQualityMetrics)
    assert metrics.rms_level_dbfs > -60  # Should have some level
    assert metrics.rms_level_dbfs < 0
    assert metrics.peak_level_dbfs < 0
    assert metrics.dynamic_range_db > 0
    assert 0 <= metrics.silence_ratio <= 1
    assert 0 <= metrics.clipping_ratio <= 1


def test_calculate_quality_metrics_silent():
    """Verify audio quality metrics for silent audio."""
    pcm = make_silent_pcm(1.0)

    metrics = calculate_quality_metrics(pcm)

    assert metrics.silence_ratio > 0.9
    assert metrics.rms_level_dbfs < -40


def test_calculate_quality_metrics_empty():
    """Verify audio quality metrics for empty audio."""
    metrics = calculate_quality_metrics(b"")

    assert metrics.silence_ratio == 1.0


def test_audio_quality_metrics_to_dict():
    """Verify AudioQualityMetrics.to_dict."""
    metrics = AudioQualityMetrics(
        rms_level_dbfs=-20.0,
        peak_level_dbfs=-6.0,
        snr_db=30.0,
        silence_ratio=0.1,
        clipping_ratio=0.0,
        dynamic_range_db=60.0,
    )

    result = metrics.to_dict()

    assert result["rms_level_dbfs"] == -20.0
    assert result["peak_level_dbfs"] == -6.0
    assert result["snr_db"] == 30.0
    assert result["silence_ratio"] == 0.1
    assert result["clipping_ratio"] == 0.0
    assert result["dynamic_range_db"] == 60.0


# ------------------------------------------------------------------
# Tests: Silence Detection
# ------------------------------------------------------------------


def test_detect_silence_normal_audio():
    """Verify silence detection in normal audio."""
    # Create audio with silence at start/end and signal in middle
    silence_at_start = make_silent_pcm(0.5)
    signal = make_test_pcm(1.0, frequency=440)
    silence_at_end = make_silent_pcm(0.5)
    pcm = silence_at_start + signal + silence_at_end

    silent_regions = detect_silence(pcm, sample_rate=16000, threshold_dbfs=-50, min_duration=0.2)

    # Should detect silence at start and end
    assert len(silent_regions) >= 1


def test_detect_silence_all_silent():
    """Verify silence detection returns full range for all-silent audio."""
    pcm = make_silent_pcm(2.0)

    silent_regions = detect_silence(pcm, sample_rate=16000, min_duration=0.1)

    assert len(silent_regions) >= 1
    # The entire audio should be detected as silent
    assert silent_regions[0][1] - silent_regions[0][0] > 1.5


def test_detect_silence_empty():
    """Verify silence detection handles empty audio."""
    silent_regions = detect_silence(b"", sample_rate=16000)

    assert silent_regions == []


# ------------------------------------------------------------------
# Tests: Silence Trimming
# ------------------------------------------------------------------


def test_trim_silence_normal():
    """Verify silence trimming removes leading/trailing silence."""
    silence_at_start = make_silent_pcm(0.5)
    signal = make_test_pcm(1.0, frequency=440)
    silence_at_end = make_silent_pcm(0.5)
    pcm = silence_at_start + signal + silence_at_end

    trimmed = trim_silence(pcm, sample_rate=16000, threshold_dbfs=-40, max_trim_seconds=2.0)

    # The trimmed audio should be shorter
    assert len(trimmed) < len(pcm)


def test_trim_silence_no_trim():
    """Verify silence trimming handles audio without much silence."""
    signal = make_test_pcm(1.0, frequency=440)

    trimmed = trim_silence(signal, sample_rate=16000, threshold_dbfs=-40)

    # Should still have most of the audio
    assert len(trimmed) > len(signal) * 0.8


def test_trim_silence_empty():
    """Verify silence trimming handles empty audio."""
    trimmed = trim_silence(b"", sample_rate=16000)

    assert trimmed == b""


# ------------------------------------------------------------------
# Tests: Audio Logging
# ------------------------------------------------------------------


def test_log_audio_metrics_with_pcm(capsys):
    """Verify log_audio_metrics logs correctly with PCM input."""
    pcm = make_test_pcm(0.5)

    log_audio_metrics("test operation", pcm_bytes=pcm)

    # Just verify it doesn't raise an exception
    captured = capsys.readouterr()
    # Output goes to logger, not stdout/stderr


def test_log_audio_metrics_with_metrics(capsys):
    """Verify log_audio_metrics logs correctly with pre-calculated metrics."""
    metrics = AudioQualityMetrics(
        rms_level_dbfs=-20.0,
        peak_level_dbfs=-6.0,
        snr_db=30.0,
        silence_ratio=0.1,
        clipping_ratio=0.0,
        dynamic_range_db=60.0,
    )

    log_audio_metrics("test operation", metrics=metrics, extra={"custom": "value"})

    # Just verify it doesn't raise an exception


def test_log_audio_metrics_empty(capsys):
    """Verify log_audio_metrics handles empty audio."""
    log_audio_metrics("test operation", pcm_bytes=b"")

    # Should not raise