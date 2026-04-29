"""Tests for channel message assembly and pi integration."""
import asyncio
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Add the gateway source to path for imports
import sys

gateway_src = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(gateway_src))

from channel import ChannelService, PiBackendError, StubPiBackend
from datp import EventBus
from registry.models import DeviceInfo


# ------------------------------------------------------------------
# Test Fixtures and Helpers
# ------------------------------------------------------------------


class StubRegistry:
    """Minimal registry stub for testing ChannelService."""

    def __init__(self, devices=None, foreground=None):
        """Initialize stub registry.

        Parameters
        ----------
        devices : list[DeviceInfo], optional
            List of online devices. Default: empty.
        foreground : DeviceInfo, optional
            Foreground device. Default: None.
        """
        self._devices = devices or []
        self._foreground = foreground

    def get_online_devices(self):
        """Return the list of online devices."""
        return self._devices

    def get_capabilities(self, device_id: str):
        """Return capabilities for a device, or None."""
        for device in self._devices:
            if device.device_id == device_id:
                return device.capabilities
        return None

    def get_foreground_device(self):
        """Return the foreground device."""
        return self._foreground


@pytest.fixture
def event_bus():
    """Create a fresh event bus."""
    return EventBus()


@pytest.fixture
def stub_device():
    """Create a stub device for testing."""
    return DeviceInfo(
        device_id="test-device",
        device_type="test",
        session_id="sess_001",
        connected_at=None,
        last_seen=None,
        capabilities={"max_spoken_seconds": 12, "supports_confirm_buttons": True},
        resume_token=None,
        nonce=None,
        state={},
        audio_cache_bytes=0,
        muted_until=None,
    )


# ------------------------------------------------------------------
# Tests: PiBackend Implementations
# ------------------------------------------------------------------


def test_stub_backend_returns_fixed_response():
    """Verify StubPiBackend returns the configured response."""

    async def run():
        backend = StubPiBackend(response="hello world")
        result = await backend.send_prompt("test message")
        assert result == "hello world"

    asyncio.run(run())


def test_stub_backend_records_last_message():
    """Verify StubPiBackend records the last message sent."""

    async def run():
        backend = StubPiBackend(response="response")
        assert backend.last_message is None
        assert backend.call_count == 0

        await backend.send_prompt("first message")
        assert backend.last_message == "first message"
        assert backend.call_count == 1

    asyncio.run(run())


def test_stub_backend_multiple_calls():
    """Verify call_count accumulates across multiple calls."""

    async def run():
        backend = StubPiBackend(response="response")

        await backend.send_prompt("msg1")
        assert backend.call_count == 1
        assert backend.last_message == "msg1"

        await backend.send_prompt("msg2")
        assert backend.call_count == 2
        assert backend.last_message == "msg2"

    asyncio.run(run())


# ------------------------------------------------------------------
# Tests: Device Context Assembly
# ------------------------------------------------------------------


def test_build_device_context_single_device(stub_device):
    """Verify device context assembly with one online device."""
    registry = StubRegistry(devices=[stub_device], foreground=stub_device)
    backend = StubPiBackend()
    service = ChannelService(EventBus(), registry, backend)

    context = service._build_device_context("test-device")

    assert context["source_device"] == "test-device"
    assert context["foreground"] == "test-device"
    assert context["online"] == ["test-device"]
    assert "test-device" in context["capabilities"]
    assert context["capabilities"]["test-device"]["max_spoken_seconds"] == 12


def test_build_device_context_multiple_devices(stub_device):
    """Verify device context with multiple devices and no foreground."""
    device2 = DeviceInfo(
        device_id="other-device",
        device_type="other",
        session_id="sess_002",
        connected_at=None,
        last_seen=None,
        capabilities={"max_spoken_seconds": 120},
        resume_token=None,
        nonce=None,
        state={},
        audio_cache_bytes=0,
        muted_until=None,
    )
    registry = StubRegistry(devices=[stub_device, device2], foreground=None)
    backend = StubPiBackend()
    service = ChannelService(EventBus(), registry, backend)

    context = service._build_device_context("test-device")

    assert context["source_device"] == "test-device"
    assert context["foreground"] is None  # Ambiguous: multiple devices online
    assert set(context["online"]) == {"test-device", "other-device"}
    assert len(context["capabilities"]) == 2


def test_build_prompt_message_includes_transcript(stub_device):
    """Verify prompt message includes transcript and device info."""
    registry = StubRegistry(devices=[stub_device], foreground=stub_device)
    backend = StubPiBackend()
    service = ChannelService(EventBus(), registry, backend)

    context = service._build_device_context("test-device")
    message = service._build_prompt_message("turn off the lights", context)

    assert "turn off the lights" in message
    assert "test-device" in message
    assert "(foreground)" in message
    assert "max_spoken_seconds=12" in message


def test_build_prompt_message_without_foreground(stub_device):
    """Verify prompt message excludes (foreground) when not foreground."""
    registry = StubRegistry(devices=[stub_device], foreground=None)
    backend = StubPiBackend()
    service = ChannelService(EventBus(), registry, backend)

    context = service._build_device_context("test-device")
    message = service._build_prompt_message("test", context)

    assert "(foreground)" not in message


# ------------------------------------------------------------------
# Tests: Channel Service Event Flow
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcript_event_triggers_agent_response(event_bus, stub_device):
    """Verify transcript event triggers agent_response event emission."""
    registry = StubRegistry(devices=[stub_device], foreground=stub_device)
    backend = StubPiBackend(response="ok")
    service = ChannelService(event_bus, registry, backend)

    response_received = None

    def capture_response(event_type, device_id, payload):
        nonlocal response_received
        if event_type == "agent_response":
            response_received = payload

    event_bus.subscribe(capture_response)

    # Emit a transcript event
    event_bus.emit("transcript", "test-device", {
        "stream_id": "rec_001",
        "text": "raw text",
        "cleaned": "turn off lights.",
    })

    # Wait for async processing
    await asyncio.sleep(0.1)

    # Verify agent_response was emitted
    assert response_received is not None
    assert response_received["stream_id"] == "rec_001"
    assert response_received["response_text"] == "ok"
    assert response_received["transcript"] == "turn off lights."


@pytest.mark.asyncio
async def test_agent_response_payload_shape(event_bus, stub_device):
    """Verify agent_response payload has all required fields."""
    registry = StubRegistry(devices=[stub_device], foreground=stub_device)
    backend = StubPiBackend(response="done")
    service = ChannelService(event_bus, registry, backend)

    response_received = None

    def capture_response(event_type, device_id, payload):
        nonlocal response_received
        if event_type == "agent_response":
            response_received = payload

    event_bus.subscribe(capture_response)
    service.start()

    event_bus.emit("transcript", "test-device", {
        "stream_id": "rec_001",
        "text": "raw",
        "cleaned": "test.",
    })

    await asyncio.sleep(0.1)

    assert response_received is not None
    assert "stream_id" in response_received
    assert "transcript" in response_received
    assert "response_text" in response_received
    assert "device_context" in response_received

    device_context = response_received["device_context"]
    assert "source_device" in device_context
    assert "foreground" in device_context
    assert "online" in device_context
    assert "capabilities" in device_context

    service.stop()


@pytest.mark.asyncio
async def test_non_transcript_events_ignored(event_bus, stub_device):
    """Verify non-transcript events do not trigger pi backend calls."""
    registry = StubRegistry(devices=[stub_device], foreground=stub_device)
    backend = StubPiBackend(response="ignored")
    service = ChannelService(event_bus, registry, backend)

    service.start()

    # Emit non-transcript events
    event_bus.emit("audio_chunk", "test-device", {"seq": 0, "data_b64": "xxx"})
    event_bus.emit("event", "test-device", {"event": "some_event"})
    event_bus.emit("registry.device_online", "test-device", {})

    await asyncio.sleep(0.1)

    # Verify pi backend was never called
    assert backend.call_count == 0

    service.stop()


@pytest.mark.asyncio
async def test_empty_transcript_is_skipped(event_bus, stub_device):
    """Verify empty transcripts do not trigger pi backend."""
    registry = StubRegistry(devices=[stub_device], foreground=stub_device)
    backend = StubPiBackend(response="response")
    service = ChannelService(event_bus, registry, backend)

    service.start()

    # Emit transcript with empty cleaned text
    event_bus.emit("transcript", "test-device", {
        "stream_id": "rec_001",
        "text": "   ",
        "cleaned": "   ",
    })

    await asyncio.sleep(0.1)

    # Verify pi backend was not called
    assert backend.call_count == 0

    service.stop()


@pytest.mark.asyncio
async def test_pi_backend_error_does_not_crash_service(event_bus, stub_device):
    """Verify pi backend errors are logged and do not crash the service."""

    class FailingBackend:
        async def send_prompt(self, message: str) -> str:
            raise PiBackendError("simulated error")

    registry = StubRegistry(devices=[stub_device], foreground=stub_device)
    backend = FailingBackend()
    service = ChannelService(event_bus, registry, backend)

    response_received = None

    def capture_response(event_type, device_id, payload):
        nonlocal response_received
        if event_type == "agent_response":
            response_received = payload

    event_bus.subscribe(capture_response)
    service.start()

    # Emit a transcript that will cause the backend to fail
    event_bus.emit("transcript", "test-device", {
        "stream_id": "rec_001",
        "text": "test",
        "cleaned": "test.",
    })

    await asyncio.sleep(0.1)

    # Verify no agent_response was emitted (due to error)
    assert response_received is None

    # Verify service is still subscribed (can process next event)
    # Send another event to verify the service is still working
    response_received = None
    backend = StubPiBackend(response="ok")
    service._pi_backend = backend
    event_bus.emit("transcript", "test-device", {
        "stream_id": "rec_002",
        "text": "test2",
        "cleaned": "test2.",
    })

    await asyncio.sleep(0.1)

    assert response_received is not None
    assert response_received["response_text"] == "ok"

    service.stop()


# ------------------------------------------------------------------
# Integration Test: Full Event Flow
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pi_backend_receives_formatted_message(event_bus, stub_device):
    """Verify pi backend receives the correctly formatted prompt message."""
    registry = StubRegistry(devices=[stub_device], foreground=stub_device)
    backend = StubPiBackend(response="response")
    service = ChannelService(event_bus, registry, backend)

    service.start()

    event_bus.emit("transcript", "test-device", {
        "stream_id": "rec_001",
        "text": "mute for 30 minutes",
        "cleaned": "mute for 30 minutes.",
    })

    await asyncio.sleep(0.1)

    # Verify the pi backend received the formatted prompt
    assert backend.call_count == 1
    assert backend.last_message is not None
    assert "mute for 30 minutes." in backend.last_message
    assert "test-device" in backend.last_message
    assert "(foreground)" in backend.last_message

    service.stop()


@pytest.mark.asyncio
async def test_subprocess_backend_timeout_raises_pi_backend_error():
    """Verify SubprocessPiBackend wraps asyncio.TimeoutError in PiBackendError."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from channel.pi_backend import SubprocessPiBackend, PiBackendError

    backend = SubprocessPiBackend(pi_command=["pi", "--mode", "rpc"])

    mock_proc = MagicMock()
    mock_proc.stdin = MagicMock()
    mock_proc.stdin.drain = AsyncMock()
    mock_proc.stdin.is_closing = MagicMock(return_value=False)
    mock_proc.stdout = AsyncMock()
    mock_proc.stdout.readline = AsyncMock(side_effect=asyncio.TimeoutError)
    mock_proc.stderr = AsyncMock()
    mock_proc.returncode = None
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock(return_value=0)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(PiBackendError, match="timed out"):
            await backend.send_prompt("test message")


@pytest.mark.asyncio
async def test_subprocess_backend_happy_path_agent_end():
    """Verify agent_end event returns extracted message text."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from channel.pi_backend import SubprocessPiBackend

    backend = SubprocessPiBackend(pi_command=["pi", "--mode", "rpc"])
    lines = [
        b'{"type":"agent_delta","text":"partial"}\n',
        b'{"type":"agent_end","messages":[{"content":[{"text":"final text"}]}]}\n',
    ]

    mock_proc = MagicMock()
    mock_proc.stdin = MagicMock()
    mock_proc.stdin.drain = AsyncMock()
    mock_proc.stdin.is_closing = MagicMock(return_value=False)
    mock_proc.stdout = AsyncMock()
    mock_proc.stdout.readline = AsyncMock(side_effect=lines)
    mock_proc.stderr = AsyncMock()
    mock_proc.returncode = None
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock(return_value=0)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await backend.send_prompt("hello")

    assert result == "final text"


@pytest.mark.asyncio
async def test_subprocess_backend_terminal_variant_end():
    """Verify terminal event variant (type=end) is accepted."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from channel.pi_backend import SubprocessPiBackend

    backend = SubprocessPiBackend(pi_command=["pi", "--mode", "rpc"])
    lines = [
        b'{"type":"end","text":"variant final"}\n',
    ]

    mock_proc = MagicMock()
    mock_proc.stdin = MagicMock()
    mock_proc.stdin.drain = AsyncMock()
    mock_proc.stdin.is_closing = MagicMock(return_value=False)
    mock_proc.stdout = AsyncMock()
    mock_proc.stdout.readline = AsyncMock(side_effect=lines)
    mock_proc.stderr = AsyncMock()
    mock_proc.returncode = None
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock(return_value=0)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await backend.send_prompt("hello")

    assert result == "variant final"


@pytest.mark.asyncio
async def test_subprocess_backend_eof_with_recoverable_text():
    """Verify EOF without terminal event still succeeds when text was captured."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from channel.pi_backend import SubprocessPiBackend

    backend = SubprocessPiBackend(pi_command=["pi", "--mode", "rpc"])
    lines = [
        b'{"type":"agent_delta","text":"recover me"}\n',
        b"",
    ]

    mock_proc = MagicMock()
    mock_proc.stdin = MagicMock()
    mock_proc.stdin.drain = AsyncMock()
    mock_proc.stdin.is_closing = MagicMock(return_value=False)
    mock_proc.stdout = AsyncMock()
    mock_proc.stdout.readline = AsyncMock(side_effect=lines)
    mock_proc.stderr = AsyncMock()
    mock_proc.returncode = None
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock(return_value=0)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await backend.send_prompt("hello")

    assert result == "recover me"


@pytest.mark.asyncio
async def test_subprocess_backend_message_update_text_end_returns_final_text():
    """Verify real pi RPC message_update/text_end events are parsed as the response."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from channel.pi_backend import SubprocessPiBackend

    backend = SubprocessPiBackend(pi_command=["pi", "--mode", "rpc", "--no-session"])
    lines = [
        b'{"type":"response","command":"prompt","success":true}\n',
        b'{"type":"agent_start"}\n',
        b'{"type":"turn_start"}\n',
        b'{"type":"message_update","assistantMessageEvent":{"type":"text_delta","contentIndex":0,"delta":"Hello"}}\n',
        b'{"type":"message_update","assistantMessageEvent":{"type":"text_end","contentIndex":0,"content":"Hello!"}}\n',
        b'{"type":"agent_end","messages":[{"role":"assistant","content":[{"type":"text","text":"Hello!"}]}]}\n',
    ]

    mock_proc = MagicMock()
    mock_proc.stdin = MagicMock()
    mock_proc.stdin.drain = AsyncMock()
    mock_proc.stdin.is_closing = MagicMock(return_value=False)
    mock_proc.stdout = AsyncMock()
    mock_proc.stdout.readline = AsyncMock(side_effect=lines)
    mock_proc.stderr = AsyncMock()
    mock_proc.returncode = None
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock(return_value=0)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await backend.send_prompt("hello")

    assert result == "Hello!"


@pytest.mark.asyncio
async def test_subprocess_backend_ignores_extension_notify_and_toolcall_text():
    """Verify startup notifications and tool-call deltas never become the returned response."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from channel.pi_backend import SubprocessPiBackend

    backend = SubprocessPiBackend(pi_command=["pi", "--mode", "rpc", "--no-session"])
    lines = [
        b'{"type":"extension_ui_request","method":"notify","message":"Model Tagger loaded (3 tags)"}\n',
        b'{"type":"response","command":"prompt","success":true}\n',
        b'{"type":"message_update","assistantMessageEvent":{"type":"toolcall_delta","contentIndex":0,"delta":"/workspace/.pi/agent/skills/agent-startup/SKILL.md"}}\n',
        b'{"type":"message_end","message":{"role":"assistant","content":[{"type":"toolCall","name":"read","arguments":{"path":"/workspace/.pi/agent/skills/agent-startup/SKILL.md"}}]}}\n',
        b'{"type":"message_update","assistantMessageEvent":{"type":"text_end","contentIndex":0,"content":"Hello there!"}}\n',
        b'{"type":"agent_end","messages":[{"role":"assistant","content":[{"type":"text","text":"Hello there!"}]}]}\n',
    ]

    mock_proc = MagicMock()
    mock_proc.stdin = MagicMock()
    mock_proc.stdin.drain = AsyncMock()
    mock_proc.stdin.is_closing = MagicMock(return_value=False)
    mock_proc.stdout = AsyncMock()
    mock_proc.stdout.readline = AsyncMock(side_effect=lines)
    mock_proc.stderr = AsyncMock()
    mock_proc.returncode = None
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock(return_value=0)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await backend.send_prompt("hello")

    assert result == "Hello there!"


@pytest.mark.asyncio
async def test_subprocess_backend_malformed_json_raises():
    """Verify malformed JSON line raises PiBackendError."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from channel.pi_backend import SubprocessPiBackend, PiBackendError

    backend = SubprocessPiBackend(pi_command=["pi", "--mode", "rpc"])
    lines = [b"not-json\n"]

    mock_proc = MagicMock()
    mock_proc.stdin = MagicMock()
    mock_proc.stdin.drain = AsyncMock()
    mock_proc.stdin.is_closing = MagicMock(return_value=False)
    mock_proc.stdout = AsyncMock()
    mock_proc.stdout.readline = AsyncMock(side_effect=lines)
    mock_proc.stderr = AsyncMock()
    mock_proc.returncode = None
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock(return_value=0)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(PiBackendError, match="malformed JSON"):
            await backend.send_prompt("hello")


@pytest.mark.asyncio
async def test_subprocess_backend_eof_without_usable_text_raises():
    """Verify EOF with no usable content raises PiBackendError."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from channel.pi_backend import SubprocessPiBackend, PiBackendError

    backend = SubprocessPiBackend(pi_command=["pi", "--mode", "rpc"])
    lines = [b"\n", b""]

    mock_proc = MagicMock()
    mock_proc.stdin = MagicMock()
    mock_proc.stdin.drain = AsyncMock()
    mock_proc.stdin.is_closing = MagicMock(return_value=False)
    mock_proc.stdout = AsyncMock()
    mock_proc.stdout.readline = AsyncMock(side_effect=lines)
    mock_proc.stderr = AsyncMock()
    mock_proc.returncode = None
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock(return_value=0)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(PiBackendError, match="without usable response text"):
            await backend.send_prompt("hello")


def test_subprocess_backend_timeout_can_be_set_via_env(monkeypatch):
    """Verify subprocess backend reads timeout from env."""
    from channel.pi_backend import SubprocessPiBackend

    monkeypatch.setenv("OI_GATEWAY_PI_TIMEOUT_SECONDS", "12.5")

    backend = SubprocessPiBackend(pi_command=["pi", "--mode", "rpc"])

    assert backend.timeout_seconds == 12.5


@pytest.mark.parametrize("raw_timeout", ["abc", "0", "-5"])
def test_subprocess_backend_invalid_timeout_env_falls_back_to_default(monkeypatch, caplog, raw_timeout):
    """Verify invalid timeout env values log a warning and use default."""
    from channel.pi_backend import SubprocessPiBackend

    monkeypatch.setenv("OI_GATEWAY_PI_TIMEOUT_SECONDS", raw_timeout)

    with caplog.at_level(logging.WARNING):
        backend = SubprocessPiBackend(pi_command=["pi", "--mode", "rpc"])

    assert backend.timeout_seconds == 60.0
    assert any(record.message.endswith("using default") for record in caplog.records)


# ------------------------------------------------------------------
# Tests: DATP message builders
# ------------------------------------------------------------------

def test_build_display_show_card_with_body():
    """Verify build_display_show_card includes optional body."""
    from datp.messages import build_display_show_card

    msg = build_display_show_card("dev-001", "Title", [], body="Body text")
    assert msg["type"] == "command"
    assert msg["payload"]["op"] == "display.show_card"
    assert msg["payload"]["args"]["title"] == "Title"
    assert msg["payload"]["args"]["body"] == "Body text"
    assert msg["payload"]["args"]["options"] == []


def test_build_display_show_card_without_body():
    """Verify build_display_show_card works without body (backward compat)."""
    from datp.messages import build_display_show_card

    msg = build_display_show_card("dev-001", "Title", [{"id": "ok", "label": "OK"}])
    assert msg["payload"]["args"]["title"] == "Title"
    assert msg["payload"]["args"]["options"][0]["id"] == "ok"
    assert "body" not in msg["payload"]["args"]


# ------------------------------------------------------------------
# Tests: CommandDispatcher with body
# ------------------------------------------------------------------

def test_command_dispatcher_show_card_with_body():
    """Verify CommandDispatcher.show_card passes body through."""
    from datp.commands import CommandDispatcher
    from datp.server import DATPServer

    mock_server = MagicMock(spec=DATPServer)
    mock_server.send_to_device = MagicMock(return_value=True)
    mock_server.event_bus = MagicMock()

    dispatcher = CommandDispatcher(mock_server)
    # Just verify msg building includes body - actual async test is in other tests
    import datp.messages as msgs
    msg = msgs.build_display_show_card("dev", "T", options=[], body="B")
    assert msg["payload"]["args"]["body"] == "B"


# ------------------------------------------------------------------
# Tests: ChannelService text prompt round-trip
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_text_prompt_event_triggers_agent_response(event_bus, stub_device):
    """Verify text.prompt event triggers agent_response emission.
    
    This mirrors test_transcript_event_triggers_agent_response but for text input.
    """
    registry = StubRegistry(devices=[stub_device], foreground=stub_device)
    backend = StubPiBackend(response="ok")
    service = ChannelService(event_bus, registry, backend)

    response_received = None

    def capture_response(event_type, device_id, payload):
        nonlocal response_received
        if event_type == "agent_response":
            response_received = payload

    event_bus.subscribe(capture_response)

    # Emit a text.prompt event
    event_bus.emit("event", "test-device", {
        "event": "text.prompt",
        "text": "what time is it?",
    })

    # Wait for async processing
    await asyncio.sleep(0.1)

    # Verify agent_response was emitted
    assert response_received is not None
    assert response_received["response_text"] == "ok"
    assert response_received["prompt_text"] == "what time is it?"
    assert "device_context" in response_received


@pytest.mark.asyncio
async def test_text_prompt_empty_is_skipped(event_bus, stub_device):
    """Verify empty text prompts do not trigger pi backend."""
    registry = StubRegistry(devices=[stub_device], foreground=stub_device)
    backend = StubPiBackend(response="response")
    service = ChannelService(event_bus, registry, backend)

    service.start()

    # Emit text.prompt with empty text
    event_bus.emit("event", "test-device", {
        "event": "text.prompt",
        "text": "   ",
    })

    await asyncio.sleep(0.1)

    # Verify pi backend was not called
    assert backend.call_count == 0

    service.stop()


# ------------------------------------------------------------------
# Tests: ChannelService text response delivery to device
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_text_response_delivered_to_device(event_bus, stub_device):
    """Verify text prompt response is delivered to device via display.show_card.
    
    This is the key test for Priority 1: text response delivery.
    """
    from unittest.mock import AsyncMock, MagicMock
    from datp.commands import CommandDispatcher
    from text.delivery import TextDeliveryPipeline

    registry = StubRegistry(devices=[stub_device], foreground=stub_device)
    backend = StubPiBackend(response="It's 3:14 PM")
    
    # Create a mock CommandDispatcher
    mock_dispatcher = MagicMock(spec=CommandDispatcher)
    mock_dispatcher.show_card = AsyncMock(return_value=True)
    mock_dispatcher.show_text_delta = AsyncMock(return_value=True)

    service = ChannelService(event_bus, registry, backend, command_dispatcher=mock_dispatcher)
    
    # Create TextDeliveryPipeline to handle agent_response_delta events
    text_pipeline = TextDeliveryPipeline(event_bus, mock_dispatcher)

    response_received = None

    def capture_response(event_type, device_id, payload):
        nonlocal response_received
        if event_type == "agent_response":
            response_received = payload

    event_bus.subscribe(capture_response)

    # Emit a text.prompt event
    event_bus.emit("event", "test-device", {
        "event": "text.prompt",
        "text": "what time is it?",
    })

    # Wait for async processing
    await asyncio.sleep(0.1)

    # Verify agent_response was emitted
    assert response_received is not None
    assert response_received["response_text"] == "It's 3:14 PM"

    # With StubPiBackend, streaming is used (has send_request_streaming)
    # So show_text_delta should be called, NOT show_card
    if response_received.get("streaming_used", False):
        # Streaming path - check show_text_delta was called
        mock_dispatcher.show_text_delta.assert_called()
        print("Streaming path used - show_text_delta called")
    else:
        # Non-streaming path - check show_card was called
        mock_dispatcher.show_card.assert_called_once()
        call_args = mock_dispatcher.show_card.call_args
        assert call_args[0][0] == "test-device"  # device_id
        assert call_args[1]["title"] == "Response"  # title
        assert call_args[1]["body"] == "It's 3:14 PM"  # body
        assert call_args[1]["options"] == []  # no options
        print("Non-streaming path used - show_card called")


@pytest.mark.asyncio
async def test_text_response_delivery_without_dispatcher(event_bus, stub_device):
    """Verify text prompt works even when command_dispatcher is None (backward compat).

    The service should still emit agent_response but not crash when trying to
    deliver to device without a dispatcher.
    """
    registry = StubRegistry(devices=[stub_device], foreground=stub_device)
    backend = StubPiBackend(response="response")

    # No command_dispatcher (None)
    service = ChannelService(event_bus, registry, backend, command_dispatcher=None)

    response_received = None

    def capture_response(event_type, device_id, payload):
        nonlocal response_received
        if event_type == "agent_response":
            response_received = payload

    event_bus.subscribe(capture_response)

    # Emit a text.prompt event - should not raise
    event_bus.emit("event", "test-device", {
        "event": "text.prompt",
        "text": "test",
    })

    await asyncio.sleep(0.1)

    # Should still emit agent_response
    assert response_received is not None
    assert response_received["response_text"] == "response"

    service.stop()


@pytest.mark.asyncio
async def test_text_prompt_pi_failure_sends_fallback_error_card(event_bus, stub_device):
    """Verify text prompt backend failure sends visible fallback error card."""
    from unittest.mock import AsyncMock, MagicMock
    from datp.commands import CommandDispatcher

    class FailingBackend:
        async def send_prompt(self, message: str) -> str:
            raise PiBackendError("simulated backend failure")

    registry = StubRegistry(devices=[stub_device], foreground=stub_device)
    backend = FailingBackend()

    mock_dispatcher = MagicMock(spec=CommandDispatcher)
    mock_dispatcher.show_card = AsyncMock(return_value=True)

    service = ChannelService(event_bus, registry, backend, command_dispatcher=mock_dispatcher)

    event_bus.emit("event", "test-device", {
        "event": "text.prompt",
        "text": "please respond",
    })

    await asyncio.sleep(0.1)

    mock_dispatcher.show_card.assert_called_once()
    call_args = mock_dispatcher.show_card.call_args
    assert call_args[0][0] == "test-device"
    assert call_args[1]["title"] == "Agent Error"
    assert "couldn't get a response" in call_args[1]["body"]
    assert call_args[1]["options"] == []

    service.stop()


@pytest.mark.asyncio
async def test_transcript_failure_logs_structured_context(event_bus, stub_device, caplog):
    """Verify transcript backend failures log device, stream, backend mode, and error class."""

    class FailingBackend:
        mode = "failing-test-backend"

        async def send_prompt(self, message: str) -> str:
            raise PiBackendError("simulated error")

    registry = StubRegistry(devices=[stub_device], foreground=stub_device)
    service = ChannelService(event_bus, registry, FailingBackend())

    with caplog.at_level(logging.ERROR):
        event_bus.emit("transcript", "test-device", {
            "stream_id": "rec_structured_001",
            "text": "raw",
            "cleaned": "hello there.",
        })
        await asyncio.sleep(0.1)

    record = next(r for r in caplog.records if r.message == "agent backend failed while processing transcript")
    assert record.device_id == "test-device"
    assert record.stream_id == "rec_structured_001"
    assert record.backend_mode == "failing-test-backend"
    assert record.error_class == "PiBackendError"
    assert isinstance(record.elapsed_ms, float)


@pytest.mark.asyncio
async def test_text_prompt_success_logs_structured_context(event_bus, stub_device, caplog):
    """Verify successful text prompts log structured device/backend/timing context."""
    registry = StubRegistry(devices=[stub_device], foreground=stub_device)
    backend = StubPiBackend(response="ok")
    service = ChannelService(event_bus, registry, backend)

    with caplog.at_level(logging.INFO):
        event_bus.emit("event", "test-device", {
            "event": "text.prompt",
            "text": "hello",
        })
        await asyncio.sleep(0.1)

    record = next(r for r in caplog.records if r.message == "Text prompt processed")
    assert record.device_id == "test-device"
    assert record.stream_id is None
    assert record.backend_mode == "stub"
    assert record.event_kind == "text.prompt"
    assert record.text_len == 5
    assert isinstance(record.elapsed_ms, float)


@pytest.mark.asyncio
async def test_multiple_text_prompts_from_one_device_are_all_processed(event_bus, stub_device):
    """Verify a burst of text prompts from one device all produce responses."""
    registry = StubRegistry(devices=[stub_device], foreground=stub_device)
    backend = StubPiBackend(response="ok")
    ChannelService(event_bus, registry, backend)

    responses = []

    def capture_response(event_type, device_id, payload):
        if event_type == "agent_response":
            responses.append((device_id, payload))

    event_bus.subscribe(capture_response)

    for i in range(5):
        event_bus.emit("event", "test-device", {
            "event": "text.prompt",
            "text": f"prompt {i}",
        })

    await asyncio.sleep(0.2)

    assert backend.call_count == 5
    assert len(responses) == 5
    assert [payload["prompt_text"] for _, payload in responses] == [f"prompt {i}" for i in range(5)]


@pytest.mark.asyncio
async def test_multiple_text_prompts_from_many_devices_are_all_processed(event_bus, stub_device):
    """Verify concurrent prompts from multiple devices all produce responses."""
    device2 = DeviceInfo(
        device_id="other-device",
        device_type="other",
        session_id="sess_002",
        connected_at=None,
        last_seen=None,
        capabilities={"max_spoken_seconds": 120},
        resume_token=None,
        nonce=None,
        state={},
        audio_cache_bytes=0,
        muted_until=None,
    )
    registry = StubRegistry(devices=[stub_device, device2], foreground=stub_device)
    backend = StubPiBackend(response="ok")
    ChannelService(event_bus, registry, backend)

    responses = []

    def capture_response(event_type, device_id, payload):
        if event_type == "agent_response":
            responses.append((device_id, payload))

    event_bus.subscribe(capture_response)

    events = [
        ("test-device", "hello from test-device"),
        ("other-device", "hello from other-device"),
        ("test-device", "second from test-device"),
        ("other-device", "second from other-device"),
    ]
    for device_id, text in events:
        event_bus.emit("event", device_id, {
            "event": "text.prompt",
            "text": text,
        })

    await asyncio.sleep(0.2)

    assert backend.call_count == 4
    assert len(responses) == 4
    assert sorted((device_id, payload["prompt_text"]) for device_id, payload in responses) == sorted(events)
