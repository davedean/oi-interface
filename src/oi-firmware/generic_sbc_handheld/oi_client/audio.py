#!/usr/bin/env python3
"""Audio adapter for Linux SBC handhelds.

Playback via aplay (ALSA) or SDL2 audio.
Optional capture via SDL2 audio capture API.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


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
            subprocess.Popen(
                ["aplay", str(wav_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._playing = True
            return True
        except FileNotFoundError:
            return False

    def stop(self) -> None:
        """Kill any running aplay process."""
        try:
            subprocess.run(["pkill", "-f", "aplay"], capture_output=True)
        except Exception:
            pass
        self._playing = False

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
