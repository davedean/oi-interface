from __future__ import annotations

import math
import struct
from unittest.mock import Mock, patch

import pytest

from audio.tts import (
    EspeakNgTtsBackend,
    OpenAiTtsBackend,
    PiperTtsBackend,
    TtsMetrics,
    _extract_pcm_from_wav,
    _get_wav_duration,
    _get_wav_sample_rate,
    calculate_quality_metrics,
    calculate_snr,
    detect_silence,
    encode_pcm_to_base64,
    log_audio_metrics,
    measure_audio_level,
    measure_peak_level,
    trim_silence,
    validate_pcm_format,
    validate_wav_format,
)


class DummyChunk:
    def __init__(self, audio_float_array, sample_rate=22050):
        self.audio_float_array = audio_float_array
        self.sample_rate = sample_rate


def make_wav(pcm: bytes, sample_rate: int = 16000, channels: int = 1, bits: int = 16) -> bytes:
    byte_rate = sample_rate * channels * bits // 8
    block_align = channels * bits // 8
    fmt_chunk = struct.pack("<HHIIHH", 1, channels, sample_rate, byte_rate, block_align, bits)
    file_size = 36 + len(pcm)
    return b"RIFF" + struct.pack("<I", file_size) + b"WAVEfmt " + struct.pack("<I", len(fmt_chunk)) + fmt_chunk + b"data" + struct.pack("<I", len(pcm)) + pcm


def pcm16(samples: list[int]) -> bytes:
    return struct.pack(f"<{len(samples)}h", *samples)


def test_extract_pcm_and_wav_helpers_cover_edge_cases():
    wav = make_wav(b"\x01\x02\x03\x04", sample_rate=12345)
    assert _extract_pcm_from_wav(wav) == b"\x01\x02\x03\x04"
    assert _extract_pcm_from_wav(b"RIFFWAVE") == b""
    assert _extract_pcm_from_wav(b"data") == b""
    assert _get_wav_sample_rate(wav) == 12345
    assert _get_wav_sample_rate(b"no fmt") == 22050
    assert _get_wav_duration(wav, 12345) > 0
    assert _get_wav_duration(b"", 12345) == 0.0
    assert _get_wav_duration(wav, 0) == 0.0
    assert encode_pcm_to_base64(b"ab") == "YWI="


def test_validate_pcm_format_covers_empty_short_long_alignment_and_silence():
    empty = validate_pcm_format(b"")
    assert empty.is_valid is False
    assert empty.errors == ["Empty PCM data"]

    short = validate_pcm_format(b"\x00\x00", sample_rate=16000, min_duration=0.1)
    assert any("too short" in err for err in short.errors)
    assert any("silent" in warning for warning in short.warnings)

    long_pcm = b"\x01\x00" * (16000 * 301)
    long = validate_pcm_format(long_pcm, sample_rate=16000, max_duration=300.0)
    assert any("too long" in err for err in long.errors)

    unaligned = validate_pcm_format(b"\x01\x00\x02", sample_rate=16000, min_duration=0.0)
    assert any("not aligned" in warning for warning in unaligned.warnings)


def test_validate_wav_format_covers_invalid_and_valid_paths():
    too_small = validate_wav_format(b"tiny")
    assert too_small.is_valid is False
    assert "too small" in too_small.errors[0]

    invalid = validate_wav_format(b"NOPE" + b"\x00" * 60, min_duration=0.0)
    assert "Invalid RIFF header" in invalid.errors
    assert "Invalid WAVE format" in invalid.errors
    assert "Missing fmt chunk" in invalid.errors
    assert "Missing data chunk" in invalid.errors

    missing_data = validate_wav_format(make_wav(b"").replace(b"data", b"xxxx", 1), min_duration=0.0)
    assert "Missing data chunk" in missing_data.errors

    valid = validate_wav_format(make_wav(pcm16([1000] * 1600)), min_duration=0.0)
    assert valid.is_valid is True
    assert valid.sample_rate == 16000
    assert valid.channels == 1
    assert valid.bits_per_sample == 16


def test_measure_audio_levels_and_quality_metrics_cover_multiple_paths():
    assert measure_audio_level(b"") == float("-inf")
    assert measure_audio_level(b"\x01", bits_per_sample=16) == float("-inf")
    assert measure_audio_level(bytes([128, 255]), bits_per_sample=8) <= 0
    assert measure_audio_level(b"\x00", bits_per_sample=12) == float("-inf")

    assert measure_peak_level(b"") == float("-inf")
    assert measure_peak_level(b"\x01", bits_per_sample=16) == float("-inf")
    assert math.isclose(measure_peak_level(pcm16([32767]), bits_per_sample=16), 0.0, abs_tol=0.1)
    assert measure_peak_level(bytes([128, 255]), bits_per_sample=8) <= 0
    assert measure_peak_level(b"\x00", bits_per_sample=12) == float("-inf")

    quiet_then_loud = pcm16([0] * 200 + [1000] * 200 + [2000] * 200 + [3000] * 200 + [4000] * 200)
    assert calculate_snr(quiet_then_loud) is None
    richer = pcm16(([200] * 100) + ([2000] * 200) + ([800] * 200) + ([4000] * 200) + ([500] * 200) + ([3500] * 200))
    assert calculate_snr(richer) is not None
    assert calculate_snr(b"\x01", bits_per_sample=16) is None
    assert calculate_snr(b"\x00\x00", bits_per_sample=8) is None

    empty_metrics = calculate_quality_metrics(b"")
    assert empty_metrics.silence_ratio == 1.0
    metrics = calculate_quality_metrics(pcm16([0, 100, 32000, -32000, 500]))
    assert metrics.peak_level_dbfs <= 0
    assert 0.0 <= metrics.silence_ratio <= 1.0
    assert 0.0 <= metrics.clipping_ratio <= 1.0
    assert isinstance(metrics.to_dict(), dict)


def test_detect_and_trim_silence():
    leading = [0] * 1600
    body = [5000] * 1600
    trailing = [0] * 1600
    audio = pcm16(leading + body + trailing)
    silences = detect_silence(audio, sample_rate=16000, min_duration=0.05)
    assert silences[0][0] == 0.0
    assert silences[-1][1] >= 0.25
    assert detect_silence(b"\x01", sample_rate=16000) == []
    assert detect_silence(b"", sample_rate=0) == []

    trimmed = trim_silence(audio, sample_rate=16000, max_trim_seconds=2.0)
    assert len(trimmed) < len(audio)
    assert trim_silence(b"\x01", sample_rate=16000) == b"\x01"
    assert trim_silence(b"", sample_rate=0) == b""


def test_tts_metrics_to_dict_and_log_audio_metrics(caplog):
    metrics = TtsMetrics(1, 2, 3.0, 16000, "voice", 5.0, 6)
    data = metrics.to_dict()
    assert data["rtf"] > 0

    caplog.set_level("INFO")
    log_audio_metrics("op", pcm_bytes=pcm16([0, 1000, -1000]), extra={"k": "v"})
    assert "Audio quality [op]" in caplog.text
    assert "Audio extra [op]" in caplog.text


def test_espeak_backend_reads_file_and_cleans_up(tmp_path):
    out = tmp_path / "speech.wav"

    def fake_named_tempfile(*args, **kwargs):
        class Temp:
            name = str(out)
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc, tb):
                return None
        return Temp()

    def fake_run(*args, **kwargs):
        out.write_bytes(b"wav-data")

    with patch("audio.tts.tempfile.NamedTemporaryFile", side_effect=fake_named_tempfile), patch("audio.tts.subprocess.run", side_effect=fake_run):
        backend = EspeakNgTtsBackend("en")
        assert backend.synthesize("hello") == b"wav-data"
    assert not out.exists()


def test_openai_tts_backend_request_and_streaming_paths():
    backend = OpenAiTtsBackend(api_key="secret", model="m", voice="v")

    class StreamResp:
        def __init__(self, chunks):
            self.chunks = list(chunks)
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return None
        def read(self, n=-1):
            if n == -1:
                data = b"".join(self.chunks)
                self.chunks.clear()
                return data
            return self.chunks.pop(0) if self.chunks else b""

    with patch("audio.tts.urllib.request.urlopen", return_value=StreamResp([b"abc", b"def", b""])) as mock_urlopen:
        request = backend._request("hello", "pcm")
        assert request.read(3) == b"abc"
        sent_request = mock_urlopen.call_args.args[0]
        assert sent_request.headers["Authorization"] == "Bearer secret"

    with patch.object(backend, "_request", return_value=StreamResp([b"ab", b"cd", b""])):
        assert list(backend.synthesize_pcm_stream("hello", chunk_size=2)) == [b"ab", b"cd"]

    wav = make_wav(pcm16([1, 2, 3]))
    with patch.object(backend, "_request", return_value=StreamResp([wav[:8], wav[8:]])):
        assert backend.synthesize("hello").startswith(b"RIFF")

    with patch.object(backend, "_request", return_value=StreamResp([b"not-wav"])):
        with pytest.raises(RuntimeError, match="did not return WAV"):
            backend.synthesize("hello")


def test_openai_tts_backend_requires_api_key():
    with pytest.raises(ValueError, match="API key"):
        OpenAiTtsBackend(api_key="")


def test_piper_backend_modes(monkeypatch):
    synth = Mock()
    synth.synthesize_wav.return_value = b"wav"

    class PiperModule:
        class PiperSynthesizer:
            @staticmethod
            def load_local(voice):
                return synth

    with patch.dict("sys.modules", {"piper_tts": PiperModule()}):
        backend = PiperTtsBackend(voice="v")
        assert backend.synthesize("hi") == b"wav"

    class FakeNp:
        int16 = "int16"
        @staticmethod
        def clip(values, low, high):
            class Arr(list):
                def __mul__(self, other):
                    return Arr([x * other for x in self])
                def astype(self, _dtype):
                    class IntArr(list):
                        def tobytes(self_inner):
                            return b"".join(struct.pack("<h", int(v)) for v in self_inner)
                    return IntArr(self)
            return Arr(values)

    class Voice:
        @staticmethod
        def load(path):
            class Loaded:
                def synthesize(self, text):
                    return [DummyChunk([0.5, -0.5], 22050)]
            return Loaded()

    with patch.dict("sys.modules", {"piper_tts": None, "piper": type("P", (), {"PiperVoice": Voice}), "numpy": FakeNp()}):
        backend = PiperTtsBackend(model_path="voice.onnx")
        assert backend.synthesize("hi").startswith(b"RIFF")

    with patch.dict("sys.modules", {"piper_tts": None, "piper": None}):
        with pytest.raises(ImportError, match="No compatible Piper"):
            PiperTtsBackend()
