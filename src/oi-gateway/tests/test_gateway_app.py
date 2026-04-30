from pathlib import Path
import sys


gateway_src = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(gateway_src))

from channel import StubPiBackend
from gateway_app import GatewayRuntime, _build_stt_backend, _build_tts_backend


class DummyBackend:
    mode = "dummy"
    name = "dummy"

    async def send_request(self, request):  # pragma: no cover - not invoked here
        raise NotImplementedError


def test_gateway_runtime_uses_provided_backend():
    backend = DummyBackend()
    runtime = GatewayRuntime(agent_backend=backend)

    assert runtime.agent_backend is backend


def test_gateway_runtime_defaults_to_stub_tts_when_none_provided():
    runtime = GatewayRuntime(agent_backend=StubPiBackend())

    assert runtime.tts is not None


def test_build_stt_backend_openai_without_key_falls_back_to_stub(monkeypatch):
    monkeypatch.setenv("OI_STT_BACKEND", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    backend = _build_stt_backend()
    assert backend.__class__.__name__ == "StubSttBackend"


def test_build_tts_backend_espeak_backend_selects_class(monkeypatch):
    monkeypatch.setenv("OI_TTS_BACKEND", "espeak-ng")
    monkeypatch.setattr("audio.tts.subprocess.run", lambda *args, **kwargs: None)
    backend = _build_tts_backend()
    assert backend.__class__.__name__ == "EspeakNgTtsBackend"


def test_build_tts_backend_openai_without_key_falls_back_to_stub(monkeypatch):
    monkeypatch.setenv("OI_TTS_BACKEND", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    backend = _build_tts_backend()
    assert backend.__class__.__name__ == "StubTtsBackend"


def test_build_tts_backend_stub_and_openai_success(monkeypatch):
    monkeypatch.setenv("OI_TTS_BACKEND", "stub")
    assert _build_tts_backend().__class__.__name__ == "StubTtsBackend"

    class DummyOpenAi:
        pass

    monkeypatch.setenv("OI_TTS_BACKEND", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("OI_OPENAI_TTS_MODEL", "m")
    monkeypatch.setenv("OI_OPENAI_TTS_VOICE", "v")
    monkeypatch.setattr("gateway_app.OpenAiTtsBackend", lambda api_key, model, voice: DummyOpenAi())
    assert _build_tts_backend().__class__.__name__ == "DummyOpenAi"


def test_build_tts_backend_piper_success_and_failure(monkeypatch):
    class DummyPiper:
        pass

    monkeypatch.setenv("OI_TTS_BACKEND", "piper")
    monkeypatch.setattr("gateway_app.PiperTtsBackend", lambda voice, model_path: DummyPiper())
    assert _build_tts_backend().__class__.__name__ == "DummyPiper"

    monkeypatch.setattr("gateway_app.PiperTtsBackend", lambda voice, model_path: (_ for _ in ()).throw(RuntimeError("no piper")))
    assert _build_tts_backend().__class__.__name__ == "StubTtsBackend"


def test_build_stt_backend_stub_openai_and_whisper_paths(monkeypatch):
    monkeypatch.setenv("OI_STT_BACKEND", "stub")
    assert _build_stt_backend().__class__.__name__ == "StubSttBackend"

    class DummyOpenAi:
        pass

    monkeypatch.setenv("OI_STT_BACKEND", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setattr("gateway_app.OpenAiWhisperBackend", lambda api_key, model: DummyOpenAi())
    assert _build_stt_backend().__class__.__name__ == "DummyOpenAi"

    class DummyWhisper:
        pass

    monkeypatch.setenv("OI_STT_BACKEND", "whisper")
    monkeypatch.setattr("gateway_app.FasterWhisperBackend", lambda model, device, compute_type: DummyWhisper())
    assert _build_stt_backend().__class__.__name__ == "DummyWhisper"
