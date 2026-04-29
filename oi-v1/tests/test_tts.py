"""Tests for server/tts.py — TTS synthesis and device WAV conversion."""

import io
import sys
import unittest
import wave
from pathlib import Path
from unittest import mock

SERVER = Path(__file__).resolve().parents[1] / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))


class TtsSynthesizeCase(unittest.TestCase):
    def setUp(self):
        # Force fresh import so module state is clean per test.
        for key in list(sys.modules.keys()):
            if "tts" in key and "faster" not in key:
                del sys.modules[key]
        import tts as _tts
        self.tts = _tts
        self.tts._piper_voice = None  # reset cached model

    def _parse_wav(self, wav_bytes):
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf) as wf:
            return {
                "channels": wf.getnchannels(),
                "rate": wf.getframerate(),
                "width": wf.getsampwidth(),
                "frames": wf.getnframes(),
            }

    def test_synthesize_returns_44100_stereo_16bit_wav(self):
        wav = self.tts.synthesize("hello")
        info = self._parse_wav(wav)
        self.assertEqual(info["channels"], 2)
        self.assertEqual(info["rate"], 44100)
        self.assertEqual(info["width"], 2)
        self.assertGreater(info["frames"], 0)

    def test_synthesize_duration_is_nonzero(self):
        wav = self.tts.synthesize("the recording is complete")
        info = self._parse_wav(wav)
        duration = info["frames"] / info["rate"]
        self.assertGreater(duration, 0.5)

    def test_espeak_fallback_when_piper_unavailable(self):
        # Patch out piper so fallback to espeak is exercised.
        with mock.patch.dict(sys.modules, {"piper": None}):
            self.tts._piper_voice = None
            wav = self.tts._synthesize_via_espeak("hello world")
        info = self._parse_wav(wav)
        self.assertEqual(info["channels"], 2)
        self.assertEqual(info["rate"], 44100)

    def test_to_device_wav_converts_22050_mono_to_44100_stereo(self):
        # Build a minimal 22050Hz mono 16-bit WAV in-memory.
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(22050)
            # 1000 frames of silence
            wf.writeframes(b"\x00\x00" * 1000)
        raw_wav = buf.getvalue()

        out = self.tts._to_device_wav(raw_wav)
        info = self._parse_wav(out)
        self.assertEqual(info["channels"], 2)
        self.assertEqual(info["rate"], 44100)
        # 1000 input frames × 2 (upsample) = 2000 stereo frames
        self.assertEqual(info["frames"], 2000)


if __name__ == "__main__":
    unittest.main()
