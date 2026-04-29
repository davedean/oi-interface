import importlib
import sys
import types
import unittest
from pathlib import Path


FIRMWARE_LIB = Path(__file__).resolve().parents[1] / "firmware" / "lib"
if str(FIRMWARE_LIB) not in sys.path:
    sys.path.insert(0, str(FIRMWARE_LIB))


class FakePin:
    OUT = 1

    def __init__(self, pin_no, *args, **kwargs):
        self.pin_no = pin_no


class FakeI2S:
    TX = 1
    MONO = 1
    STEREO = 2

    def __init__(self, channel, **kwargs):
        self.channel = channel
        self.kwargs = kwargs
        self.writes = []

    def write(self, data):
        self.writes.append(bytes(data))
        return len(data)


class FakeI2CBus:
    def __init__(self):
        self.mem = {}
        self.writes = []

    def readfrom_mem(self, addr, reg, n):
        return bytes(self.mem.get((addr, reg + i), 0) for i in range(n))

    def writeto_mem(self, addr, reg, data):
        for i, b in enumerate(data):
            self.mem[(addr, reg + i)] = b
        self.writes.append((addr, reg, bytes(data)))


class FakePMIC:
    def __init__(self):
        self.amp_calls = []

    def enable_speaker_amp(self, on=True):
        self.amp_calls.append(bool(on))


class FirmwareAudioCase(unittest.TestCase):
    def setUp(self):
        fake_machine = types.SimpleNamespace(I2S=FakeI2S, Pin=FakePin)
        self.old_machine = sys.modules.get("machine")
        sys.modules["machine"] = fake_machine
        if "oi_audio" in sys.modules:
            del sys.modules["oi_audio"]

    def tearDown(self):
        if self.old_machine is None:
            sys.modules.pop("machine", None)
        else:
            sys.modules["machine"] = self.old_machine
        sys.modules.pop("oi_audio", None)

    def test_chirp_initialises_codec_stereo_i2s_and_amp(self):
        oi_audio = importlib.import_module("oi_audio")
        if not hasattr(oi_audio.time, "sleep_ms"):
            oi_audio.time.sleep_ms = lambda _ms: None

        i2c = FakeI2CBus()
        pmic = FakePMIC()
        audio = oi_audio.OiAudio(i2c, pmic=pmic)

        result = audio.chirp("good")

        self.assertEqual(result, "ok")
        # Reg 0x01 = 0xB5 (M5Unified-verified BCLK-locked clock manager).
        self.assertIn((oi_audio.ES8311_ADDR, 0x01, bytes([0xB5])), i2c.writes)
        self.assertEqual([call for call in pmic.amp_calls], [True, False])
        self.assertIsNotNone(audio._i2s)
        self.assertEqual(audio._i2s.kwargs["format"], FakeI2S.STEREO)
        self.assertEqual(audio._i2s.kwargs["rate"], 44100)
        self.assertEqual(audio._i2s.kwargs["ibuf"], 8192)
        self.assertEqual(audio._i2s.kwargs["sck"].pin_no, 17)
        self.assertEqual(audio._i2s.kwargs["ws"].pin_no, 15)
        self.assertEqual(audio._i2s.kwargs["sd"].pin_no, 14)
        self.assertNotIn("mck", audio._i2s.kwargs)
        self.assertEqual(len(audio._i2s.writes), 2)

    def test_tone_buffer_is_stereo_16bit(self):
        oi_audio = importlib.import_module("oi_audio")
        audio = oi_audio.OiAudio(FakeI2CBus(), pmic=FakePMIC())

        buf = audio._tone_buf(1000, ms=10, rate=44100)

        self.assertEqual(len(buf), 441 * 4)
        self.assertEqual(buf[:4], b"\x00\x00\x00\x00")

    def test_volume_scales_and_zero_mutes(self):
        oi_audio = importlib.import_module("oi_audio")
        audio = oi_audio.OiAudio(FakeI2CBus(), pmic=FakePMIC())

        audio.set_volume(40)
        self.assertEqual(audio.volume(), 40)
        self.assertFalse(audio.is_muted())
        audio.set_volume(0)
        self.assertEqual(audio.volume(), 0)
        self.assertTrue(audio.is_muted())

    def test_chirp_returns_err_string_when_codec_init_throws(self):
        oi_audio = importlib.import_module("oi_audio")
        if not hasattr(oi_audio.time, "sleep_ms"):
            oi_audio.time.sleep_ms = lambda _ms: None

        class BoomI2C(FakeI2CBus):
            def writeto_mem(self, addr, reg, data):
                raise OSError(19, "ENODEV")

        audio = oi_audio.OiAudio(BoomI2C(), pmic=FakePMIC())
        result = audio.chirp("good")
        self.assertTrue(result.startswith("ERR:"), result)


def _make_wav(frames=8, rate=44100, channels=2, sampwidth=2):
    """Build a minimal valid RIFF WAV with silence."""
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(rate)
        wf.writeframes(b"\x00" * (frames * channels * sampwidth))
    return buf.getvalue()


class PlayWavCase(unittest.TestCase):
    def setUp(self):
        fake_machine = types.SimpleNamespace(I2S=FakeI2S, Pin=FakePin)
        self.old_machine = sys.modules.get("machine")
        sys.modules["machine"] = fake_machine
        if "oi_audio" in sys.modules:
            del sys.modules["oi_audio"]

    def tearDown(self):
        if self.old_machine is None:
            sys.modules.pop("machine", None)
        else:
            sys.modules["machine"] = self.old_machine
        sys.modules.pop("oi_audio", None)

    def test_play_wav_writes_pcm_to_i2s(self):
        oi_audio = importlib.import_module("oi_audio")
        if not hasattr(oi_audio.time, "sleep_ms"):
            oi_audio.time.sleep_ms = lambda _ms: None

        i2c = FakeI2CBus()
        pmic = FakePMIC()
        audio = oi_audio.OiAudio(i2c, pmic=pmic)

        wav = _make_wav(frames=16)
        result = audio.play_wav(wav)

        self.assertEqual(result, "ok")
        self.assertTrue(len(audio._i2s.writes) > 0)
        total_written = sum(len(w) for w in audio._i2s.writes)
        # 16 frames × 2 channels × 2 bytes = 64 bytes PCM
        self.assertEqual(total_written, 64)

    def test_play_wav_enables_then_disables_amp(self):
        oi_audio = importlib.import_module("oi_audio")
        if not hasattr(oi_audio.time, "sleep_ms"):
            oi_audio.time.sleep_ms = lambda _ms: None

        pmic = FakePMIC()
        audio = oi_audio.OiAudio(FakeI2CBus(), pmic=pmic)
        audio.play_wav(_make_wav())

        self.assertEqual(pmic.amp_calls, [True, False])

    def test_play_wav_returns_muted_when_muted(self):
        oi_audio = importlib.import_module("oi_audio")
        audio = oi_audio.OiAudio(FakeI2CBus(), pmic=FakePMIC())
        audio.set_muted(True)

        result = audio.play_wav(_make_wav())

        self.assertEqual(result, "muted")
        self.assertIsNone(audio._i2s)

    def test_play_wav_rejects_non_wav(self):
        oi_audio = importlib.import_module("oi_audio")
        audio = oi_audio.OiAudio(FakeI2CBus(), pmic=FakePMIC())

        result = audio.play_wav(b"not a wav file at all")
        self.assertTrue(result.startswith("ERR:"), result)


class DacVolumeCase(unittest.TestCase):
    def setUp(self):
        fake_machine = types.SimpleNamespace(I2S=FakeI2S, Pin=FakePin)
        self.old_machine = sys.modules.get("machine")
        sys.modules["machine"] = fake_machine
        if "oi_audio" in sys.modules:
            del sys.modules["oi_audio"]

    def tearDown(self):
        if self.old_machine is None:
            sys.modules.pop("machine", None)
        else:
            sys.modules["machine"] = self.old_machine
        sys.modules.pop("oi_audio", None)

    def _dac_writes(self, i2c, oi_audio):
        return [w for w in i2c.writes if w[0] == oi_audio.ES8311_ADDR and w[1] == 0x32]

    def test_set_volume_writes_dac_register(self):
        oi_audio = importlib.import_module("oi_audio")
        i2c = FakeI2CBus()
        audio = oi_audio.OiAudio(i2c, pmic=FakePMIC())
        audio._initialised = True  # simulate already-inited codec

        audio.set_volume(50)

        writes = self._dac_writes(i2c, oi_audio)
        self.assertEqual(len(writes), 1)
        expected = int(0xBF * 50 // 100)
        self.assertEqual(writes[0][2], bytes([expected]))

    def test_set_volume_zero_writes_zero_to_dac(self):
        oi_audio = importlib.import_module("oi_audio")
        i2c = FakeI2CBus()
        audio = oi_audio.OiAudio(i2c, pmic=FakePMIC())
        audio._initialised = True

        audio.set_volume(0)

        writes = self._dac_writes(i2c, oi_audio)
        self.assertEqual(writes[-1][2], bytes([0]))

    def test_init_codec_applies_current_volume(self):
        oi_audio = importlib.import_module("oi_audio")
        if not hasattr(oi_audio.time, "sleep_ms"):
            oi_audio.time.sleep_ms = lambda _ms: None
        i2c = FakeI2CBus()
        audio = oi_audio.OiAudio(i2c, pmic=FakePMIC())
        audio.set_volume(50)   # set before first chirp (before codec init)

        audio.chirp()          # triggers _init_codec

        writes = self._dac_writes(i2c, oi_audio)
        last = writes[-1][2][0]
        expected = int(0xBF * 50 // 100)
        self.assertEqual(last, expected)

    def test_tone_buf_uses_full_amplitude_independent_of_volume(self):
        import struct, math
        oi_audio = importlib.import_module("oi_audio")
        audio = oi_audio.OiAudio(FakeI2CBus(), pmic=FakePMIC())
        audio.set_volume(10)   # low volume — should NOT reduce tone amplitude

        buf = audio._tone_buf(440, ms=100)

        # Sample near the sine peak (quarter-period index)
        quarter = 44100 // (4 * 440)
        v = struct.unpack_from("<h", buf, quarter * 4)[0]
        # Full amplitude is 8000; expect > 5000 (not scaled down to 800)
        self.assertGreater(abs(v), 5000)


class PMICAudioCase(unittest.TestCase):
    def test_enable_speaker_amp_configures_pmic_gpio3(self):
        m5pm1 = importlib.import_module("m5pm1")
        i2c = FakeI2CBus()
        pmic = m5pm1.M5PM1(i2c)

        # Start with set bits so the helper must actively clear FUNC/DRV bits.
        i2c.mem[(m5pm1.ADDR, m5pm1.R_GPIO_FUNC0)] = 0xFF
        i2c.mem[(m5pm1.ADDR, m5pm1.R_GPIO_DRV)] = 0xFF
        i2c.mem[(m5pm1.ADDR, m5pm1.R_GPIO_MODE)] = 0x00
        i2c.mem[(m5pm1.ADDR, m5pm1.R_GPIO_OUT)] = 0x00

        pmic.enable_speaker_amp(True)

        self.assertEqual(i2c.mem[(m5pm1.ADDR, m5pm1.R_GPIO_FUNC0)] & 0b11000000, 0)
        self.assertEqual(i2c.mem[(m5pm1.ADDR, m5pm1.R_GPIO_DRV)] & (1 << 3), 0)
        self.assertTrue(i2c.mem[(m5pm1.ADDR, m5pm1.R_GPIO_MODE)] & (1 << 3))
        self.assertTrue(i2c.mem[(m5pm1.ADDR, m5pm1.R_GPIO_OUT)] & (1 << 3))

        pmic.enable_speaker_amp(False)
        self.assertEqual(i2c.mem[(m5pm1.ADDR, m5pm1.R_GPIO_OUT)] & (1 << 3), 0)


if __name__ == "__main__":
    unittest.main()
