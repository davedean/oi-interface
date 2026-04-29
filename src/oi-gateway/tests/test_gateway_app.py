from pathlib import Path
import sys


gateway_src = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(gateway_src))

from channel import StubPiBackend
from gateway_app import GatewayRuntime


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
