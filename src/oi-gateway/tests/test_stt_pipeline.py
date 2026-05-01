"""Tests for audio STT pipeline and backends."""
import asyncio
import base64
from pathlib import Path

import pytest

# Add the gateway and sim source to path for imports
import sys

gateway_src = Path(__file__).parent.parent / "src"
sim_src = Path(__file__).parent.parent.parent / "oi-clients" / "oi-sim" / "src"
sys.path.insert(0, str(gateway_src))
sys.path.insert(0, str(sim_src))

from audio import (
    FasterWhisperBackend,
    StubSttBackend,
    StreamAccumulator,
    clean_transcript,
    pcm_to_wav,
)
from datp import EventBus
from sim.sim import OiSim
from datp.server import DATPServer


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
async def datp_server():
    """Start an ephemeral DATP server."""
    srv = DATPServer(host="localhost", port=0)
    task = asyncio.create_task(srv.start())
    await asyncio.sleep(0.15)
    yield srv
    await srv.stop()
    await asyncio.sleep(0.1)


@pytest.fixture
async def sim(datp_server):
    """Connect a virtual device to the DATP server."""
    device = OiSim(
        gateway=f"ws://localhost:{datp_server.port}/datp",
        device_id="oi-sim-stt-test",
    )
    await device.connect()
    yield device
    await device.disconnect()


@pytest.fixture
def event_bus():
    """Create a fresh event bus."""
    return EventBus()


# ------------------------------------------------------------------
# Tests: STT Backend Implementations
# ------------------------------------------------------------------


def test_stub_backend_returns_fixed_text():
    """Verify StubSttBackend always returns the configured response."""
    backend = StubSttBackend(response="hello world")

    result1, metrics1 = backend.transcribe(b"fake pcm 1", sample_rate=16000)
    result2, metrics2 = backend.transcribe(b"fake pcm 2", sample_rate=8000)

    assert result1 == "hello world"
    assert result2 == "hello world"
    assert metrics1 is not None
    assert metrics2 is not None


def test_stub_backend_default_response():
    """Verify StubSttBackend uses default response when not configured."""
    backend = StubSttBackend()

    result, metrics = backend.transcribe(b"any data", sample_rate=16000)
    assert result == "test transcript"
    assert metrics is not None


# ------------------------------------------------------------------
# Tests: Transcript Cleaning
# ------------------------------------------------------------------


def test_clean_transcript_strips_leading_fillers():
    """Verify clean_transcript removes leading filler words."""
    assert clean_transcript("um hello world") == "hello world."
    assert clean_transcript("uh like testing") == "like testing."
    assert clean_transcript("  hmm  start") == "start."


def test_clean_transcript_collapses_whitespace():
    """Verify clean_transcript collapses multiple spaces."""
    assert clean_transcript("hello   world") == "hello world."
    assert clean_transcript("  test  ") == "test."


def test_clean_transcript_adds_period():
    """Verify clean_transcript adds a period if missing."""
    assert clean_transcript("no period") == "no period."
    assert clean_transcript("already has.") == "already has."
    assert clean_transcript("question?") == "question?"
    assert clean_transcript("exclaim!") == "exclaim!"


def test_clean_transcript_empty_string():
    """Verify clean_transcript handles empty input."""
    assert clean_transcript("") == ""
    assert clean_transcript("   ") == ""


# ------------------------------------------------------------------
# Tests: WAV Construction
# ------------------------------------------------------------------


def test_pcm_to_wav_valid_header():
    """Verify pcm_to_wav produces a valid RIFF WAV header."""
    pcm = b"\x00" * 3200  # 0.1 seconds at 16kHz, 16-bit, mono
    wav = pcm_to_wav(pcm, sample_rate=16000, channels=1, bits=16)

    # Check RIFF signature
    assert wav[:4] == b"RIFF"
    # Check WAVE signature
    assert wav[8:12] == b"WAVE"
    # Check fmt  subchunk
    assert b"fmt " in wav
    # Check data subchunk
    assert b"data" in wav
    # Check that PCM data is present at the end
    assert pcm in wav


def test_pcm_to_wav_correct_sizes():
    """Verify WAV header has correct size fields."""
    pcm = b"\x00" * 1024
    wav = pcm_to_wav(pcm, sample_rate=16000, channels=1, bits=16)

    import struct

    # RIFF chunk size (file size - 8)
    riff_size = struct.unpack("<I", wav[4:8])[0]
    # Should be 36 (header after RIFF) + len(pcm)
    assert riff_size == 36 + len(pcm)


# ------------------------------------------------------------------
# Tests: Audio Stream Accumulation
# ------------------------------------------------------------------


def test_audio_stream_single_chunk():
    """Verify AudioStream handles a single chunk."""
    from audio.pipeline import AudioStream

    stream = AudioStream(device_id="dev1", stream_id="rec_123")
    stream.chunks[0] = b"\x00\x01\x02\x03"

    assert stream.is_complete()
    assert stream.reassemble_pcm() == b"\x00\x01\x02\x03"


def test_audio_stream_multiple_chunks_in_order():
    """Verify AudioStream reassembles multiple chunks in sequence."""
    from audio.pipeline import AudioStream

    stream = AudioStream(device_id="dev1", stream_id="rec_123")
    stream.chunks[0] = b"aaa"
    stream.chunks[1] = b"bbb"
    stream.chunks[2] = b"ccc"

    assert stream.is_complete()
    assert stream.reassemble_pcm() == b"aaabbbccc"


def test_audio_stream_incomplete_with_gaps():
    """Verify AudioStream.is_complete() returns False for gaps."""
    from audio.pipeline import AudioStream

    stream = AudioStream(device_id="dev1", stream_id="rec_123")
    stream.chunks[0] = b"aaa"
    stream.chunks[2] = b"ccc"  # Missing seq=1

    assert not stream.is_complete()


def test_stream_accumulator_buffers_chunks(event_bus):
    """Verify StreamAccumulator buffers audio_chunk events."""
    backend = StubSttBackend()
    accum = StreamAccumulator(event_bus, backend)

    # Send 3 audio chunks
    event_bus.emit("audio_chunk", "dev1", {
        "stream_id": "rec_001",
        "seq": 0,
        "format": "pcm16",
        "sample_rate": 16000,
        "channels": 1,
        "data_b64": base64.b64encode(b"chunk0").decode(),
    })
    event_bus.emit("audio_chunk", "dev1", {
        "stream_id": "rec_001",
        "seq": 1,
        "format": "pcm16",
        "sample_rate": 16000,
        "channels": 1,
        "data_b64": base64.b64encode(b"chunk1").decode(),
    })
    event_bus.emit("audio_chunk", "dev1", {
        "stream_id": "rec_001",
        "seq": 2,
        "format": "pcm16",
        "sample_rate": 16000,
        "channels": 1,
        "data_b64": base64.b64encode(b"chunk2").decode(),
    })

    # Verify stream is buffered
    assert "rec_001" in accum._streams
    stream = accum._streams["rec_001"]
    assert len(stream.chunks) == 3
    assert stream.reassemble_pcm() == b"chunk0chunk1chunk2"


@pytest.mark.asyncio
async def test_stream_accumulator_transcribes_on_recording_finished(event_bus):
    """Verify StreamAccumulator triggers transcription on recording_finished event."""
    backend = StubSttBackend(response="transcribed text")
    accum = StreamAccumulator(event_bus, backend)

    transcript_received = None

    def capture_transcript(event_type, device_id, payload):
        nonlocal transcript_received
        if event_type == "transcript":
            transcript_received = payload

    event_bus.subscribe(capture_transcript)

    # Send an audio chunk
    event_bus.emit("audio_chunk", "dev1", {
        "stream_id": "rec_001",
        "seq": 0,
        "data_b64": base64.b64encode(b"\x00" * 1024).decode(),
    })

    # Send recording_finished
    event_bus.emit("event", "dev1", {
        "event": "audio.recording_finished",
        "stream_id": "rec_001",
        "duration_ms": 100,
    })

    # Wait for async transcription
    await asyncio.sleep(0.2)

    # Verify transcript event was emitted
    assert transcript_received is not None
    assert transcript_received["stream_id"] == "rec_001"
    assert transcript_received["text"] == "transcribed text"
    # Cleaned version should have period added
    assert transcript_received["cleaned"] == "transcribed text."

    # Stream should be removed after transcription
    assert "rec_001" not in accum._streams


@pytest.mark.asyncio
async def test_stream_accumulator_multiple_streams(event_bus):
    """Verify StreamAccumulator handles multiple simultaneous streams correctly."""
    backend = StubSttBackend(response="result")
    accum = StreamAccumulator(event_bus, backend)

    transcripts = {}

    def capture_transcript(event_type, device_id, payload):
        if event_type == "transcript":
            transcripts[payload["stream_id"]] = payload

    event_bus.subscribe(capture_transcript)

    # Start two streams with chunks
    for stream_id in ["rec_001", "rec_002"]:
        for seq in range(2):
            event_bus.emit("audio_chunk", "dev1", {
                "stream_id": stream_id,
                "seq": seq,
                "data_b64": base64.b64encode(f"data_{stream_id}_{seq}".encode()).decode(),
            })

    # Complete both streams
    for stream_id in ["rec_001", "rec_002"]:
        event_bus.emit("event", "dev1", {
            "event": "audio.recording_finished",
            "stream_id": stream_id,
            "duration_ms": 100,
        })

    await asyncio.sleep(0.2)

    # Verify both transcriptions completed
    assert "rec_001" in transcripts
    assert "rec_002" in transcripts
    assert transcripts["rec_001"]["text"] == "result"
    assert transcripts["rec_002"]["text"] == "result"


# ------------------------------------------------------------------
# Integration Tests: Full Pipeline
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_integration_sim_upload_triggers_transcript(datp_server, sim):
    """Full integration: oi-sim uploads audio, pipeline transcribes."""
    backend = StubSttBackend(response="hello from device")
    accum = StreamAccumulator(datp_server.event_bus, backend)

    transcript_received = None

    def capture_transcript(event_type, device_id, payload):
        nonlocal transcript_received
        if event_type == "transcript":
            transcript_received = payload

    datp_server.event_bus.subscribe(capture_transcript)

    # Device uploads audio (this sends audio chunks + recording_finished)
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        # Write stub audio (just raw bytes, not a real WAV)
        tmp.write(b"\x00" * 2048)
        tmp_path = tmp.name

    try:
        stream_id = await sim.upload_audio_file(tmp_path)
        assert stream_id.startswith("rec_")

        # Wait for pipeline to process
        await asyncio.sleep(0.2)

        # Verify transcript event received
        assert transcript_received is not None
        assert transcript_received["stream_id"] == stream_id
        assert transcript_received["text"] == "hello from device"
        assert "hello from device." == transcript_received["cleaned"]

    finally:
        import os
        os.unlink(tmp_path)


@pytest.mark.asyncio
async def test_integration_multiple_uploads(datp_server, sim):
    """Verify multiple consecutive uploads are handled independently."""
    backend = StubSttBackend(response="upload result")
    accum = StreamAccumulator(datp_server.event_bus, backend)

    transcripts = {}

    def capture_transcript(event_type, device_id, payload):
        if event_type == "transcript":
            stream_id = payload["stream_id"]
            transcripts[stream_id] = payload

    datp_server.event_bus.subscribe(capture_transcript)

    import tempfile

    # Upload twice
    for i in range(2):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(b"\x00" * 1024)
            tmp_path = tmp.name

        try:
            stream_id = await sim.upload_audio_file(tmp_path)
            await asyncio.sleep(0.1)
        finally:
            import os
            os.unlink(tmp_path)

    await asyncio.sleep(0.1)

    # Verify both uploads were transcribed
    assert len(transcripts) == 2
    for transcript in transcripts.values():
        assert transcript["text"] == "upload result"
