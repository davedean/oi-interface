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
