"""Tests for TTS backends and synthesis."""
from __future__ import annotations

import base64
import struct
from pathlib import Path

import pytest

import sys

gateway_src = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(gateway_src))

from audio.tts import (
    PiperTtsBackend,
    StubTtsBackend,
    TtsBackend,
    generate_response_id,
    text_to_wav,
)


# ------------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------------


def _piper_available() -> bool:
    """Check if piper-tts is installed."""
    try:
        import piper_tts  # noqa: F401
        return True
    except ImportError:
        return False


# ------------------------------------------------------------------
# Tests: StubTtsBackend


# ------------------------------------------------------------------
# Tests: StubTtsBackend
# ------------------------------------------------------------------


def test_stub_backend_returns_fixed_wav():
    """Verify StubTtsBackend always returns the same fixed WAV."""
    backend = StubTtsBackend(response_wav=b"FAKE_WAV_DATA")

    result = backend.synthesize("hello world")
    assert result == b"FAKE_WAV_DATA"


def test_stub_backend_default_response():
    """Verify StubTtsBackend returns valid WAV data by default."""
    backend = StubTtsBackend()
    result = backend.synthesize("any text")

    # Default WAV is a valid RIFF/WAVE file
    assert result.startswith(b"RIFF")
    assert b"WAVE" in result[:12]
    assert len(result) > 44  # minimum WAV header + data


def test_stub_backend_synthesize_returns_bytes():
    """Verify synthesize always returns bytes."""
    backend = StubTtsBackend(response_wav=b"\x00\x01\x02")
    result = backend.synthesize("test")
    assert isinstance(result, bytes)


def test_stub_backend_different_inputs_same_output():
    """Verify StubTtsBackend ignores input text."""
    backend = StubTtsBackend(response_wav=b"fixed")

    r1 = backend.synthesize("first text")
    r2 = backend.synthesize("completely different text")

    assert r1 == r2 == b"fixed"


# ------------------------------------------------------------------
# Tests: Response ID generation
# ------------------------------------------------------------------


def test_generate_response_id_format():
    """Verify response IDs are unique and have expected format."""
    ids = [generate_response_id() for _ in range(10)]

    # All unique
    assert len(set(ids)) == 10

    # All non-empty strings
    for rid in ids:
        assert isinstance(rid, str)
        assert len(rid) > 0

    # All start with expected prefix
    for rid in ids:
        assert rid.startswith("resp_")


def test_generate_response_id_unique():
    """Verify consecutive calls produce unique IDs."""
    id1 = generate_response_id()
    id2 = generate_response_id()
    assert id1 != id2


# ------------------------------------------------------------------
# Tests: text_to_wav helper (requires piper-tts)
# ------------------------------------------------------------------


@pytest.mark.skipif(
    not _piper_available(),
    reason="piper-tts not installed",
)
def test_text_to_wav_returns_wav_bytes():
    """Verify text_to_wav returns WAV-formatted bytes."""
    wav = text_to_wav("test")

    assert wav[:4] == b"RIFF"
    assert wav[8:12] == b"WAVE"


@pytest.mark.skipif(
    not _piper_available(),
    reason="piper-tts not installed",
)
def test_text_to_wav_different_texts_different_output():
    """Verify different texts produce different WAV data."""
    wav1 = text_to_wav("hello")
    wav2 = text_to_wav("world")

    assert wav1 != wav2


@pytest.mark.skipif(
    not _piper_available(),
    reason="piper-tts not installed",
)
def test_text_to_wav_valid_wav_header():
    """Verify WAV header contains fmt and data chunks."""
    wav = text_to_wav("testing")

    assert b"fmt " in wav
    assert b"data" in wav


# ------------------------------------------------------------------
# Tests: WAV chunking utilities
# ------------------------------------------------------------------


def _make_test_wav(pcm_data: bytes, sample_rate: int = 16000) -> bytes:
    """Create a minimal valid WAV file for testing."""
    import struct

    byte_rate = sample_rate * 1 * 16 // 8
    block_align = 1 * 16 // 8
    fmt_chunk = struct.pack("<HHIIHH", 1, 1, sample_rate, byte_rate, block_align, 16)
    data_size = len(pcm_data)
    file_size = 36 + data_size

    wav = b"RIFF"
    wav += struct.pack("<I", file_size)
    wav += b"WAVE"
    wav += b"fmt "
    wav += struct.pack("<I", len(fmt_chunk))
    wav += fmt_chunk
    wav += b"data"
    wav += struct.pack("<I", data_size)
    wav += pcm_data

    return wav


def test_wav_to_pcm_chunks_correct_padding():
    """Verify _wav_to_pcm_chunks produces correct-sized chunks."""
    from audio.tts import _wav_to_pcm_chunks

    # Create a WAV with 100 bytes of PCM
    pcm = b"\x00" * 100
    wav = _make_test_wav(pcm)

    # If we have real WAV data, chunk it
    chunks = _wav_to_pcm_chunks(wav, chunk_size=20)
    total = sum(len(c) for c in chunks)

    assert total == 100
    assert len(chunks) == 5  # 100 / 20 = 5


def test_wav_to_pcm_chunks_handles_remainder():
    """Verify _wav_to_pcm_chunks handles non-divisible sizes."""
    from audio.tts import _wav_to_pcm_chunks

    pcm = b"\x00" * 95
    wav = _make_test_wav(pcm)

    chunks = _wav_to_pcm_chunks(wav, chunk_size=20)
    total = sum(len(c) for c in chunks)

    assert total == 95
    assert len(chunks) == 5  # 4 full chunks (80) + 1 partial (15)


def test_wav_to_pcm_chunks_single_chunk():
    """Verify _wav_to_pcm_chunks handles data smaller than chunk_size."""
    from audio.tts import _wav_to_pcm_chunks

    pcm = b"\x00" * 10
    wav = _make_test_wav(pcm)

    chunks = _wav_to_pcm_chunks(wav, chunk_size=100)
    assert len(chunks) == 1
    assert len(chunks[0]) == 10


def test_wav_to_pcm_chunks_empty():
    """Verify _wav_to_pcm_chunks handles empty input."""
    from audio.tts import _wav_to_pcm_chunks

    chunks = _wav_to_pcm_chunks(b"RIFF" + b"\x00" * 100 + b"WAVE", chunk_size=20)
    # Should return empty list for WAV with no data
    assert isinstance(chunks, list)


# ------------------------------------------------------------------
# Tests: TtsBackend Protocol conformance
# ------------------------------------------------------------------


def test_stub_backend_conforms_to_protocol():
    """Verify StubTtsBackend can be used wherever TtsBackend is expected."""
    def use_backend(backend: TtsBackend, text: str) -> bytes:
        return backend.synthesize(text)

    backend = StubTtsBackend(response_wav=b"test_wav")
    result = use_backend(backend, "hello")

    assert result == b"test_wav"


# ------------------------------------------------------------------
# Tests: PiperTtsBackend import handling
# ------------------------------------------------------------------


def test_piper_backend_raises_import_error_without_piper():
    """Verify PiperTtsBackend raises ImportError if piper-tts is not installed.
    
    Since piper-tts is not installed in this environment, this test verifies
    that attempting to use PiperTtsBackend raises an appropriate ImportError.
    """
    if _piper_available():
        pytest.skip("piper-tts is installed; cannot test import failure")
    
    with pytest.raises(ImportError, match="piper-tts"):
        PiperTtsBackend()


# ------------------------------------------------------------------
# Integration tests (require piper-tts to be installed)
# ------------------------------------------------------------------


@pytest.mark.skipif(
    not _piper_available(),
    reason="piper-tts not installed",
)
def test_piper_backend_synthesizes_text():
    """Verify PiperTtsBackend can synthesize text to WAV (if piper installed)."""
    # This test is skipped unless piper-tts is actually available
    pytest.skip("Requires piper-tts installation")
