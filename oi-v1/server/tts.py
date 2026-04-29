"""
server/tts.py — text-to-speech for device audio output.

Output: 44100 Hz stereo 16-bit WAV (matches device I2S playback path).
Backend: piper (neural, en_US-lessac-medium) with espeak-ng fallback.

Piper model path: OI_PIPER_MODEL env var, or the lessac model from
the rosie-voice-assistant project if present.
"""

from __future__ import annotations

import io
import os
import subprocess
import wave

import numpy as np

_piper_voice = None  # cached PiperVoice

# Maximum allowed TTS output size (~8.5 seconds of 44.1 kHz stereo 16-bit).
MAX_SPEAK_WAV_BYTES = 1_500_000

_DEFAULT_MODEL = os.path.join(
    os.path.dirname(__file__),
    "..", "..", "rosie-voice-assistant", "voices", "en_US-lessac-medium.onnx",
)
PIPER_MODEL = os.environ.get(
    "OI_PIPER_MODEL",
    os.path.realpath(_DEFAULT_MODEL),
)


class TtsUnavailable(Exception):
    """Raised when no TTS backend can produce audio."""


def synthesize(text: str) -> bytes:
    """Return 44100 Hz stereo 16-bit WAV bytes for *text*.

    Raises ValueError if the output exceeds MAX_SPEAK_WAV_BYTES."""
    global _piper_voice
    try:
        if _piper_voice is None:
            import time as _time
            t0 = _time.monotonic()
            from piper import PiperVoice  # type: ignore
            _piper_voice = PiperVoice.load(PIPER_MODEL)
            print(f"[tts] piper model loaded in {_time.monotonic()-t0:.1f}s", flush=True)

        import time as _time
        t0 = _time.monotonic()
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            _piper_voice.synthesize_wav(text, wf)
        raw_wav = buf.getvalue()
        out = _to_device_wav(raw_wav)
        if len(out) > MAX_SPEAK_WAV_BYTES:
            raise ValueError("TTS output too large")
        print(f"[tts] synthesized via piper in {_time.monotonic()-t0:.2f}s: {text!r:.60}", flush=True)
        return out
    except ValueError:
        raise
    except Exception as e:
        if not isinstance(e, (ImportError, ModuleNotFoundError, FileNotFoundError)):
            print(f"[tts] piper error ({e}), falling back to espeak-ng", flush=True)
        return _synthesize_via_espeak(text)


def _synthesize_via_espeak(text: str) -> bytes:
    """Produce device WAV via espeak-ng (fallback)."""
    import time as _time
    t0 = _time.monotonic()
    result = subprocess.run(
        ["espeak-ng", "-v", "en-us", "-s", "150", "--stdout"],
        input=text.encode(),
        capture_output=True,
    )
    if result.returncode != 0:
        raise TtsUnavailable("espeak-ng failed: " + result.stderr.decode())
    out = _to_device_wav(result.stdout)
    print(f"[tts] synthesized via espeak-ng in {_time.monotonic()-t0:.2f}s", flush=True)
    return out


def _to_device_wav(src_wav: bytes) -> bytes:
    """Resample and convert source WAV to 44100 Hz stereo 16-bit WAV."""
    buf = io.BytesIO(src_wav)
    with wave.open(buf) as wf:
        src_rate = wf.getframerate()
        src_channels = wf.getnchannels()
        pcm = wf.readframes(wf.getnframes())

    samples = np.frombuffer(pcm, dtype=np.int16)

    # If stereo, keep only the left channel before duplicating to stereo.
    if src_channels == 2:
        samples = samples[::2]

    # Upsample to 44100 if needed (integer factor only).
    if src_rate != 44100:
        factor = 44100 // src_rate
        samples = np.repeat(samples, factor)

    # Expand mono to stereo for device playback.
    stereo = np.column_stack([samples, samples]).flatten().astype(np.int16)

    out = io.BytesIO()
    with wave.open(out, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        wf.writeframes(stereo.tobytes())
    return out.getvalue()
