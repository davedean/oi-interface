"""Tests for handheld audio helpers."""
from __future__ import annotations

import io
import os
import sys
import types
from pathlib import Path
from unittest.mock import Mock


client_src = Path(__file__).parent.parent / "generic_sbc_handheld"
if str(client_src) not in sys.path:
    sys.path.insert(0, str(client_src))

import oi_client.audio as audio_mod
from oi_client.audio import HandheldAudio


class FakeProc:
    def __init__(self, *, running=True, stdin=None):
        self._running = running
        self.stdin = stdin
        self.terminated = False

    def poll(self):
        return None if self._running else 1

    def terminate(self):
        self.terminated = True
        self._running = False


def test_play_returns_false_when_file_missing(tmp_path: Path) -> None:
    audio = HandheldAudio()
    assert audio.play(tmp_path / "missing.wav") is False


def test_start_and_write_pcm_stream(monkeypatch) -> None:
    stream = io.BytesIO()
    proc = FakeProc(stdin=stream)
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: proc)

    audio = HandheldAudio()

    assert audio.start_pcm_stream(sample_rate=22050, channels=2) is True
    assert audio.write_pcm_stream(b"abc") is True
    assert stream.getvalue() == b"abc"

    audio.end_pcm_stream()
    assert audio._stream_proc is None


def test_write_pcm_stream_returns_false_without_active_process() -> None:
    audio = HandheldAudio()
    assert audio.write_pcm_stream(b"abc") is False


def test_stop_terminates_stream_and_clears_playing(monkeypatch) -> None:
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: None)
    audio = HandheldAudio()
    audio._stream_proc = FakeProc(stdin=io.BytesIO())
    audio._playing = True

    audio.stop()

    assert audio._stream_proc is None
    assert audio._playing is False


def test_is_playing_uses_pgrep_result(monkeypatch) -> None:
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: Mock(returncode=0))
    audio = HandheldAudio()

    assert audio.is_playing() is True


def test_save_wav_writes_header_and_pcm(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "sample.wav"

    def fake_mkstemp(*, suffix: str, prefix: str):
        fd = os.open(target, os.O_CREAT | os.O_TRUNC | os.O_RDWR)
        return fd, str(target)

    monkeypatch.setattr("tempfile.mkstemp", fake_mkstemp)
    audio = HandheldAudio()

    path = audio.save_wav(b"\x01\x02\x03\x04", sample_rate=8000, channels=1)

    data = path.read_bytes()
    assert data.startswith(b"RIFF")
    assert data.endswith(b"\x01\x02\x03\x04")


def test_detect_reports_output_and_usb_input(monkeypatch) -> None:
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: Mock(returncode=0))
    fake_sdl2 = types.SimpleNamespace(
        SDL_INIT_AUDIO=99,
        SDL_Init=lambda flags: 0,
        SDL_GetNumAudioDevices=lambda capture: 1,
        SDL_GetAudioDeviceName=lambda idx, capture: b"USB Mic",
        SDL_QuitSubSystem=lambda flags: None,
    )
    monkeypatch.setitem(sys.modules, "sdl2", fake_sdl2)

    audio = HandheldAudio()
    status = audio.detect()

    assert status.has_output is True
    assert status.has_input is True
    assert status.capture_device_name == "USB Mic"



def test_read_recording_dequeues_available_audio(monkeypatch) -> None:
    fake_sdl2 = types.SimpleNamespace(SDL_GetQueuedAudioSize=lambda dev: 4)

    def fake_dequeue(dev, buf, chunk_size):
        for idx, value in enumerate(b"abcd"):
            buf[idx] = value
        return 4

    fake_sdl2.SDL_DequeueAudio = fake_dequeue
    monkeypatch.setitem(sys.modules, "sdl2", fake_sdl2)
    audio = HandheldAudio()
    audio._recording = True
    audio._recording_dev = 1

    assert audio.read_recording() == b"abcd"



def test_stop_recording_closes_device(monkeypatch) -> None:
    calls = []
    fake_sdl2 = types.SimpleNamespace(
        SDL_PauseAudioDevice=lambda dev, pause: calls.append(("pause", dev, pause)),
        SDL_CloseAudioDevice=lambda dev: calls.append(("close", dev)),
    )
    monkeypatch.setitem(sys.modules, "sdl2", fake_sdl2)
    audio = HandheldAudio()
    audio._recording = True
    audio._recording_dev = 3

    audio.stop_recording()

    assert audio.is_recording is False
    assert calls == [("pause", 3, 1), ("close", 3)]



def test_recording_info_reflects_current_state() -> None:
    audio = HandheldAudio()
    audio._recording = True
    audio._recording_sr = 16000
    audio._recording_ch = 1

    assert audio.recording_info() == {
        "is_recording": True,
        "sample_rate": 16000,
        "channels": 1,
    }
