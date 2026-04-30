#!/usr/bin/env python3
"""Audio adapter for Linux SBC handhelds.

Playback via aplay (ALSA) or SDL2 audio.
Optional capture via SDL2 audio capture API.
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class AudioStatus:
    has_input: bool = False
    has_output: bool = True
    capture_device_name: str | None = None


class HandheldAudio:
    """Audio adapter for playback and optional capture."""

    def __init__(self) -> None:
        self._playing = False
        self._status = AudioStatus()
        self._stream_proc: subprocess.Popen | None = None

    def detect(self) -> AudioStatus:
        """Detect available audio hardware."""
        # Check for aplay (playback)
        self._status.has_output = subprocess.run(
            ["which", "aplay"], capture_output=True
        ).returncode == 0

        # Check for USB mic via SDL2 capture devices
        # Do a quick SDL2 init just to probe devices
        try:
            os.environ.setdefault("PYSDL2_DLL_PATH", "/usr/lib")
            import sdl2
            sdl2.SDL_Init(sdl2.SDL_INIT_AUDIO)
            num = sdl2.SDL_GetNumAudioDevices(1)
            for i in range(num):
                name = sdl2.SDL_GetAudioDeviceName(i, 1)
                n = name.decode() if name else ""
                if "USB" in n or "Mic" in n or "capture" in n.lower():
                    self._status.has_input = True
                    self._status.capture_device_name = n
                    break
            sdl2.SDL_QuitSubSystem(sdl2.SDL_INIT_AUDIO)
        except Exception:
            pass

        return self._status

    def play(self, wav_path: str | Path) -> bool:
        """Play a WAV file via aplay. Returns immediately (non-blocking).

        Note: this is fire-and-forget. Use is_playing() to check status.
        """
        wav_path = Path(wav_path)
        if not wav_path.exists():
            return False

        try:
            proc = subprocess.Popen(
                ["aplay", "-q", str(wav_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._playing = proc.poll() is None
            logger.info("aplay started path=%s ok=%s", wav_path, self._playing)
            return self._playing
        except FileNotFoundError:
            logger.warning("aplay not found")
            return False
        except Exception as exc:
            logger.exception("aplay launch failed for %s: %s", wav_path, exc)
            return False

    def stop(self) -> None:
        """Kill any running aplay process."""
        try:
            if self._stream_proc and self._stream_proc.poll() is None:
                self._stream_proc.terminate()
            self._stream_proc = None
            subprocess.run(["pkill", "-f", "aplay"], capture_output=True)
        except Exception:
            pass
        self._playing = False

    def start_pcm_stream(self, sample_rate: int = 24000, channels: int = 1) -> bool:
        """Start streaming raw PCM16LE to aplay stdin."""
        try:
            if self._stream_proc and self._stream_proc.poll() is None:
                self._stream_proc.terminate()
            self._stream_proc = subprocess.Popen(
                ["aplay", "-q", "-t", "raw", "-f", "S16_LE", "-r", str(sample_rate), "-c", str(channels), "-"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._playing = self._stream_proc.poll() is None
            return self._playing
        except Exception as exc:
            logger.warning("start_pcm_stream failed: %s", exc)
            self._stream_proc = None
            return False

    def write_pcm_stream(self, pcm_chunk: bytes) -> bool:
        """Write a PCM chunk to active stream."""
        try:
            if not self._stream_proc or self._stream_proc.poll() is not None or not self._stream_proc.stdin:
                return False
            self._stream_proc.stdin.write(pcm_chunk)
            self._stream_proc.stdin.flush()
            return True
        except Exception:
            return False

    def end_pcm_stream(self) -> None:
        """Finalize active PCM stream playback."""
        try:
            if self._stream_proc and self._stream_proc.stdin:
                self._stream_proc.stdin.close()
        except Exception:
            pass
        self._stream_proc = None

    def is_playing(self) -> bool:
        """Best-effort check if playback is still active."""
        try:
            result = subprocess.run(
                ["pgrep", "-x", "aplay"],
                capture_output=True,
            )
            self._playing = result.returncode == 0
        except Exception:
            self._playing = False
        return self._playing

    def save_wav(self, pcm16_data: bytes, sample_rate: int = 16000, channels: int = 1) -> Path:
        """Write PCM16 data to a temp WAV file with header."""
        # Simple WAV header for PCM16LE
        import struct
        data_size = len(pcm16_data)
        header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            data_size + 36,
            b"WAVE",
            b"fmt ",
            16,  # subchunk size
            1,   # PCM
            channels,
            sample_rate,
            sample_rate * channels * 2,
            channels * 2,
            16,  # bits per sample
            b"data",
            data_size,
        )
        fd, path = tempfile.mkstemp(suffix=".wav", prefix="oi_audio_")
        with os.fdopen(fd, "wb") as fh:
            fh.write(header)
            fh.write(pcm16_data)
        return Path(path)

    # ------------------------------------------------------------------
    # Recording (SDL2 capture)
    # ------------------------------------------------------------------

    def recording_init(self) -> bool:
        """Initialize SDL2 audio capture subsystem.

        Returns True if at least one capture device is available.
        """
        try:
            os.environ.setdefault("PYSDL2_DLL_PATH", "/usr/lib")
            import sdl2
            if sdl2.SDL_Init(sdl2.SDL_INIT_AUDIO) != 0:
                return False
            num = sdl2.SDL_GetNumAudioDevices(1)
            if num > 0:
                return True
            sdl2.SDL_QuitSubSystem(sdl2.SDL_INIT_AUDIO)
        except Exception:
            pass
        return False

    def start_recording(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        format_pcm16: bool = True,
    ) -> bool:
        """Start capturing audio from the default input device.

        The captured PCM16 data can be retrieved with read_recording().
        Returns True on success.
        """
        try:
            import sdl2
            from sdl2 import (
                SDL_OpenAudioDevice, SDL_AudioSpec,
                SDL_AUDIO_ALLOW_FORMAT_CHANGE, SDL_PauseAudioDevice,
            )
        except Exception:
            return False

        if getattr(self, "_recording", False):
            return False

        # SDL_AudioSpec constructor differs across PySDL2 versions:
        # some use "format", others use "aformat".
        audio_fmt = sdl2.AUDIO_S16LSB if format_pcm16 else sdl2.AUDIO_S8
        try:
            desired = SDL_AudioSpec(
                freq=sample_rate,
                format=audio_fmt,
                channels=channels,
                samples=1024,
            )
            obtained = SDL_AudioSpec(freq=0, format=0, channels=0, samples=0)
        except TypeError:
            desired = SDL_AudioSpec(
                freq=sample_rate,
                aformat=audio_fmt,
                channels=channels,
                samples=1024,
            )
            obtained = SDL_AudioSpec(freq=0, aformat=0, channels=0, samples=0)

        # Try explicit capture-device selection first; some targets choose a
        # playback-only default and fail capture open.
        dev_name = None
        try:
            num_caps = sdl2.SDL_GetNumAudioDevices(1)
            chosen = None
            for i in range(num_caps):
                nm = sdl2.SDL_GetAudioDeviceName(i, 1)
                n = nm.decode() if nm else ""
                low = n.lower()
                if "usb" in low or "mic" in low or "capture" in low:
                    chosen = n
                    break
            if not chosen and num_caps > 0:
                nm = sdl2.SDL_GetAudioDeviceName(0, 1)
                chosen = nm.decode() if nm else None
            dev_name = chosen.encode() if chosen else None
            if chosen:
                logger.info("Opening capture device: %s", chosen)
        except Exception:
            dev_name = None

        self._recording_dev = SDL_OpenAudioDevice(
            dev_name,
            1,     # iscapture
            desired,
            obtained,
            SDL_AUDIO_ALLOW_FORMAT_CHANGE,
        )

        if self._recording_dev == 0:
            return False

        self._recording = True
        self._recording_chunks = []
        self._recording_sr = obtained.freq
        self._recording_ch = obtained.channels
        SDL_PauseAudioDevice(self._recording_dev, 0)  # unpause / start
        logger.info("Audio recording started: sr=%s ch=%s", self._recording_sr, self._recording_ch)
        return True

    def stop_recording(self) -> None:
        """Stop capturing audio."""
        if getattr(self, "_recording", False) and getattr(self, "_recording_dev", 0):
            try:
                import sdl2
                sdl2.SDL_PauseAudioDevice(self._recording_dev, 1)
                sdl2.SDL_CloseAudioDevice(self._recording_dev)
            except Exception:
                pass
        self._recording = False

    def read_recording(self) -> bytes:
        """Read all available captured PCM16 data as a single bytes object.

        Returns empty bytes if not recording or nothing available.
        """
        if not getattr(self, "_recording", False):
            return b""
        try:
            import sdl2
            from sdl2 import SDL_DequeueAudio
            # Query queued size
            queued = sdl2.SDL_GetQueuedAudioSize(self._recording_dev)
            if queued == 0:
                return b""
            # Dequeue in reasonable chunk sizes (max 4096 per call)
            result = bytearray()
            while queued > 0:
                chunk_size = min(queued, 4096)
                buf = bytearray(chunk_size)
                c_buf = (ctypes.c_ubyte * chunk_size).from_buffer(buf)
                received = SDL_DequeueAudio(self._recording_dev, c_buf, chunk_size)
                if received > 0:
                    result.extend(buf[:received])
                queued -= received
                if queued <= 0:
                    break
            return bytes(result)
        except Exception as e:
            logger.debug("read_recording failed: %s", e)
            return b""

    @property
    def is_recording(self) -> bool:
        """Whether we are currently capturing audio."""
        return getattr(self, "_recording", False)

    def recording_info(self) -> dict:
        """Get info about current recording session."""
        return {
            "is_recording": self.is_recording,
            "sample_rate": getattr(self, "_recording_sr", 0),
            "channels": getattr(self, "_recording_ch", 0),
        }
