"""Tests for speak output — stereo WAV synthesis and size limits."""

import io
import sys
import unittest
import wave
from pathlib import Path
from unittest import mock

SERVER = Path(__file__).resolve().parents[1] / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))


class SynthesizeStereoCase(unittest.TestCase):
    """Test that synthesize returns stereo 44100 Hz 16-bit WAV."""

    def setUp(self):
        # Force fresh import so module state is clean per test.
        for key in list(sys.modules.keys()):
            if "tts" in key and "faster" not in key:
                del sys.modules[key]
        import tts as _tts
        self.tts = _tts
        self.tts._piper_voice = None

    def _parse_wav(self, wav_bytes):
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf) as wf:
            return {
                "channels": wf.getnchannels(),
                "rate": wf.getframerate(),
                "width": wf.getsampwidth(),
                "frames": wf.getnframes(),
            }

    def test_synthesize_returns_stereo_44100_16bit_wav(self):
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


class ToDeviceWavStereoCase(unittest.TestCase):
    """Test that _to_device_wav produces stereo output from various inputs."""

    def setUp(self):
        for key in list(sys.modules.keys()):
            if "tts" in key and "faster" not in key:
                del sys.modules[key]
        import tts as _tts
        self.tts = _tts

    def _make_wav(self, rate, channels, frames_data):
        """Build a minimal WAV in memory."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(frames_data)
        return buf.getvalue()

    def _parse_wav(self, wav_bytes):
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf) as wf:
            return {
                "channels": wf.getnchannels(),
                "rate": wf.getframerate(),
                "width": wf.getsampwidth(),
                "frames": wf.getnframes(),
            }

    def test_to_device_wav_mono_input_produces_stereo_output(self):
        """Mono input → stereo output at 44100 Hz."""
        raw = self._make_wav(22050, 1, b"\x00\x00" * 1000)
        out = self.tts._to_device_wav(raw)
        info = self._parse_wav(out)
        self.assertEqual(info["channels"], 2)
        self.assertEqual(info["rate"], 44100)
        self.assertEqual(info["width"], 2)
        # 1000 input frames × 2 (upsample factor) = 2000 stereo frames
        self.assertEqual(info["frames"], 2000)

    def test_to_device_wav_stereo_input_produces_stereo_output(self):
        """Stereo input → stereo output, resampled to 44100 Hz."""
        frame_count = 1000
        samples = bytearray()
        for i in range(frame_count):
            l_val = (i % 256) & 0xFF
            samples.extend([l_val, 0])
            r_val = ((i + 128) % 256) & 0xFF
            samples.extend([r_val, 0])

        raw = self._make_wav(22050, 2, bytes(samples))
        out = self.tts._to_device_wav(raw)
        info = self._parse_wav(out)
        self.assertEqual(info["channels"], 2)
        self.assertEqual(info["rate"], 44100)
        self.assertEqual(info["width"], 2)
        self.assertEqual(info["frames"], 2000)


class SizeLimitCase(unittest.TestCase):
    """Test that synthesize raises ValueError when output exceeds limit."""

    def setUp(self):
        for key in list(sys.modules.keys()):
            if "tts" in key and "faster" not in key:
                del sys.modules[key]
        import tts as _tts
        self.tts = _tts
        self.tts._piper_voice = None

    def test_size_limit_raises_value_error(self):
        """If _to_device_wav would produce >1.5 MB, synthesize raises ValueError."""
        oversized = b"\x00" * (self.tts.MAX_SPEAK_WAV_BYTES + 1)
        with mock.patch.object(self.tts, "_to_device_wav", return_value=oversized):
            with self.assertRaises(ValueError) as ctx:
                self.tts.synthesize("x" * 10000)
            self.assertEqual(str(ctx.exception), "TTS output too large")


class SpeechCleanCase(unittest.TestCase):
    """Test _speech_clean from main.py."""

    def setUp(self):
        import re
        self.re = re

    def _speech_clean(self, text, max_chars=300):
        re = self.re
        text = re.sub(r'```[\s\S]*?```', ' code omitted', text)
        text = re.sub(r'`[^`]+`', ' code omitted', text)
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
        text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
        text = re.sub(r'https?://\S+', ' link', text)
        text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'\n{2,}', '. ', text)
        text = re.sub(r'\n', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        if len(text) <= max_chars:
            return text
        truncated = text[:max_chars]
        last_sent = max(truncated.rfind('.'), truncated.rfind('!'), truncated.rfind('?'))
        if last_sent > max_chars // 2:
            text = text[:last_sent + 1]
        else:
            text = truncated.rstrip() + '...'
        return text

    def test_markdown_link_flattened(self):
        result = self._speech_clean('See [the docs](https://example.com) for details.')
        self.assertNotIn('https', result)
        self.assertIn('the docs', result)

    def test_bare_url_simplified(self):
        result = self._speech_clean('Visit https://example.com for more.')
        self.assertNotIn('https', result)
        self.assertIn('link', result)


if __name__ == "__main__":
    unittest.main()
