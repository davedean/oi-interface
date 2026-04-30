"""Tests for handheld app logic without SDL/device dependencies."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


client_src = Path(__file__).parent.parent / "generic_sbc_handheld"
if str(client_src) not in sys.path:
    sys.path.insert(0, str(client_src))

import oi_client.app as app_mod
from oi_client.app import CardData, HandheldApp, UIMode


class StubInput:
    def init(self):
        return True

    def shutdown(self):
        return None

    def poll(self):
        return []


class StubRenderer:
    width = 480
    height = 320
    _font_body = object()
    _font_hint = object()

    def __init__(self):
        self.calls = []

    def init(self):
        return True

    def shutdown(self):
        return None

    def effective_text_grid(self):
        return (40, 18)

    def _wrap_text(self, line, font, width):
        return [line[:10], line[10:]] if len(line) > 10 else [line]

    def clear(self):
        self.calls.append("clear")

    def draw_title(self, *args, **kwargs):
        self.calls.append(("title", args, kwargs))

    def draw_card(self, *args, **kwargs):
        self.calls.append(("card", args, kwargs))

    def draw_spinner(self, *args, **kwargs):
        self.calls.append(("spinner", args, kwargs))

    def draw_recording_indicator(self):
        self.calls.append("recording")

    def draw_hints(self, *args, **kwargs):
        self.calls.append(("hints", args, kwargs))

    def present(self):
        self.calls.append("present")

    def _rect(self, *args, **kwargs):
        self.calls.append(("rect", args, kwargs))

    def _text(self, font, text, color):
        return (object(), len(text), 10)

    def _draw_tex(self, *args, **kwargs):
        self.calls.append(("tex", args, kwargs))

    def _destroy_tex(self, *args, **kwargs):
        self.calls.append(("destroy", args, kwargs))


class StubAudio:
    def __init__(self):
        self.recording = False
        self.start_recording_ok = True
        self.pending = b""
        self.stream_writes = []
        self.saved = []
        self.played = []
        self.stopped = False

    @property
    def is_recording(self):
        return self.recording

    def recording_init(self):
        return True

    def start_recording(self):
        self.recording = self.start_recording_ok
        return self.start_recording_ok

    def stop_recording(self):
        self.recording = False

    def read_recording(self):
        data = self.pending
        self.pending = b""
        return data

    def start_pcm_stream(self, sample_rate=24000, channels=1):
        self.stream_started = (sample_rate, channels)
        return True

    def write_pcm_stream(self, chunk):
        self.stream_writes.append(chunk)
        return True

    def end_pcm_stream(self):
        self.stream_ended = True

    def save_wav(self, pcm16_data, sample_rate=16000, channels=1):
        self.saved.append((pcm16_data, sample_rate, channels))
        return Path("/tmp/generated.wav")

    def play(self, wav_path):
        self.played.append(str(wav_path))
        return True

    def stop(self):
        self.stopped = True


@pytest.fixture
def app(monkeypatch) -> HandheldApp:
    monkeypatch.setattr(app_mod, "Sdl2Input", StubInput)
    monkeypatch.setattr(app_mod, "Sdl2Renderer", StubRenderer)
    monkeypatch.setattr(app_mod, "HandheldAudio", StubAudio)
    monkeypatch.setattr(HandheldApp, "_get_version", lambda self: "testver")
    return HandheldApp("ws://gateway/datp", "dev1", "handheld")


def test_build_capabilities_reflects_audio_status(app: HandheldApp) -> None:
    caps = app._build_capabilities(SimpleNamespace(has_input=True, has_output=False))

    assert caps["display_width"] == 40
    assert caps["display_height"] == 18
    assert caps["has_audio_input"] is True
    assert caps["has_audio_output"] is False
    assert "hold_to_record" in caps["input"]


@pytest.mark.asyncio
async def test_send_prompt_marks_offline_without_connection(app: HandheldApp) -> None:
    app.datp = None

    await app._send_prompt("hello")

    assert app._ui_mode == UIMode.OFFLINE


@pytest.mark.asyncio
async def test_send_prompt_surfaces_send_failures(app: HandheldApp) -> None:
    app.datp = SimpleNamespace(is_connected=True, send_text_prompt=AsyncMock(side_effect=RuntimeError("boom")))

    await app._send_prompt("hello")

    assert app._ui_mode == UIMode.ERROR
    assert app._card.title == "Send failed"
    assert app._card.body == "boom"


@pytest.mark.asyncio
async def test_start_and_stop_recording_flush_audio_chunks(app: HandheldApp, monkeypatch) -> None:
    app.datp = SimpleNamespace(
        is_connected=True,
        send_audio_chunk=AsyncMock(),
        send_recording_finished=AsyncMock(),
    )
    app.audio.pending = b"chunk1"
    monkeypatch.setattr(app_mod.time, "time", lambda: 100.0)

    assert await app.start_recording() is True
    app.datp.send_audio_chunk.assert_awaited_once()
    assert app._ui_mode == UIMode.RECORDING

    app.audio.pending = b"chunk2"
    monkeypatch.setattr(app_mod.time, "time", lambda: 101.5)
    await app.stop_recording()

    assert app._ui_mode == UIMode.OFFLINE
    assert app.datp.send_recording_finished.await_count == 1


def test_handle_command_caches_audio_chunks_and_stops_playback(app: HandheldApp) -> None:
    app._handle_command({
        "op": "audio.cache.put_begin",
        "args": {"stream_id": "s1", "sample_rate": 24000, "channels": 1},
    })
    app._handle_command({
        "op": "audio.cache.put_chunk",
        "args": {"data_b64": "AQI="},
    })
    app._handle_command({
        "op": "audio.cache.put_end",
        "args": {"response_id": "resp1"},
    })
    app._handle_command({"op": "audio.stop", "args": {}})

    assert app.audio.stream_writes == [b"\x01\x02"]
    assert app.audio.saved == [(b"\x01\x02", 24000, 1)]
    assert app._response_audio["resp1"] == "/tmp/generated.wav"
    assert app.audio.stopped is True


def test_state_helpers_and_scrolling(app: HandheldApp) -> None:
    app._ui_mode = UIMode.CARD
    app._response_audio = {"resp1": "/tmp/file.wav"}
    app._card = CardData(title="Response", body="0123456789ABCDE\n\nshort")

    assert app._state_to_ui("thinking") == UIMode.WAITING
    assert app._hint_for_mode() == "A=Replay  B=Back  Up/Down=Scroll"
    assert app._max_card_scroll(app._card.title, app._card.body) >= 0


@pytest.mark.asyncio
async def test_handle_input_navigation_and_menu(app: HandheldApp) -> None:
    app._ui_mode = UIMode.HOME
    app._prompt_idx = 0
    app._send_prompt = AsyncMock()

    await app._handle_input(SimpleNamespace(type="button", name="down", action="pressed", raw=0))
    await app._handle_input(SimpleNamespace(type="button", name="a", action="released", raw=0))
    await app._handle_input(SimpleNamespace(type="button", name="start", action="pressed", raw=0))

    assert app._prompt_idx == 1
    app._send_prompt.assert_awaited_once_with(app_mod.CANNED_PROMPTS[1])
    assert app._ui_mode == UIMode.MENU
    assert app._menu_mode == "main"


@pytest.mark.asyncio
async def test_menu_character_size_toggle(app: HandheldApp) -> None:
    app._ui_mode = UIMode.HOME
    await app._handle_input(SimpleNamespace(type="button", name="select", action="pressed", raw=0))
    assert app._ui_mode == UIMode.MENU
    assert app._menu_mode == "settings"

    app._menu_idx = app._menu_items().index("Character Size")
    original = app._character_size

    await app._handle_input(SimpleNamespace(type="button", name="a", action="pressed", raw=0))

    assert app._character_size != original
    assert app._card.title == "Character Size"
    assert app._ui_mode == UIMode.CARD


@pytest.mark.asyncio
async def test_menu_mute_toggle(app: HandheldApp) -> None:
    app._ui_mode = UIMode.HOME
    await app._handle_input(SimpleNamespace(type="button", name="select", action="pressed", raw=0))
    app._menu_idx = app._menu_items().index("Mute Duration")
    await app._handle_input(SimpleNamespace(type="button", name="a", action="pressed", raw=0))
    assert app._mute_duration_hours == 1

    app._ui_mode = UIMode.MENU
    app._menu_mode = "settings"
    app._menu_idx = app._menu_items().index("Mute")
    await app._handle_input(SimpleNamespace(type="button", name="a", action="pressed", raw=0))
    assert app._device_control.is_muted() is True
    assert app._card.title == "Mute"

    app._ui_mode = UIMode.MENU
    app._menu_mode = "settings"
    app._menu_idx = app._menu_items().index("Mute")
    await app._handle_input(SimpleNamespace(type="button", name="a", action="pressed", raw=0))
    assert app._device_control.is_muted() is False


@pytest.mark.asyncio
async def test_menu_device_settings_and_show_progress_toggle(app: HandheldApp) -> None:
    app._ui_mode = UIMode.HOME
    await app._handle_input(SimpleNamespace(type="button", name="select", action="pressed", raw=0))

    app._menu_idx = app._menu_items().index("Brightness")
    await app._handle_input(SimpleNamespace(type="button", name="a", action="pressed", raw=0))
    assert app._device_control.brightness == 64

    app._ui_mode = UIMode.MENU
    app._menu_mode = "settings"
    app._menu_idx = app._menu_items().index("Volume")
    await app._handle_input(SimpleNamespace(type="button", name="a", action="pressed", raw=0))
    assert app._device_control.volume == 100

    app._ui_mode = UIMode.MENU
    app._menu_mode = "settings"
    app._menu_idx = app._menu_items().index("LED")
    await app._handle_input(SimpleNamespace(type="button", name="a", action="pressed", raw=0))
    assert app._device_control.led_enabled is False

    app._ui_mode = UIMode.MENU
    app._menu_mode = "settings"
    app._menu_idx = app._menu_items().index("Show Progress")
    await app._handle_input(SimpleNamespace(type="button", name="a", action="pressed", raw=0))

    app._ui_mode = UIMode.WAITING
    app._card.body = "Working"
    app._handle_command({"op": "display.show_progress", "args": {"text": "step 1"}})
    assert "step 1" not in app._card.body


@pytest.mark.asyncio
async def test_settings_diagnostics_and_system_menu(app: HandheldApp) -> None:
    app._online = True
    app._ui_mode = UIMode.HOME
    await app._handle_input(SimpleNamespace(type="button", name="select", action="pressed", raw=0))

    app._menu_idx = app._menu_items().index("Diagnostics")
    await app._handle_input(SimpleNamespace(type="button", name="a", action="pressed", raw=0))
    assert app._card.title == "Diagnostics"
    assert "brightness:" in app._card.body

    app._ui_mode = UIMode.MENU
    app._menu_mode = "settings"
    app._menu_idx = app._menu_items().index("System")
    await app._handle_input(SimpleNamespace(type="button", name="a", action="pressed", raw=0))
    assert app._menu_mode == "system"

    app._menu_idx = app._menu_items().index("Reboot")
    await app._handle_input(SimpleNamespace(type="button", name="a", action="pressed", raw=0))
    assert app._card.title == "Reboot"
    assert "blocked" in app._card.body


@pytest.mark.asyncio
async def test_handle_input_error_retry_and_quit(app: HandheldApp) -> None:
    app._ui_mode = UIMode.ERROR
    app.datp = SimpleNamespace(reconnect=AsyncMock(return_value=True), is_connected=True)

    await app._handle_input(SimpleNamespace(type="button", name="a", action="pressed", raw=0))
    assert app._ui_mode == UIMode.READY

    app._ui_mode = UIMode.OFFLINE
    await app._handle_input(SimpleNamespace(type="button", name="b", action="pressed", raw=0))
    assert app._running is False


@pytest.mark.asyncio
async def test_handle_command_updates_ui_and_progress(app: HandheldApp) -> None:
    app._ui_mode = UIMode.WAITING
    app._handle_command({"op": "display.show_status", "args": {"state": "thinking", "label": "Working"}})
    assert app._ui_mode == UIMode.WAITING
    assert app._card.body == "Working"

    app._handle_command({"op": "display.show_progress", "args": {"text": "step 1"}})
    assert "step 1" in app._card.body

    app._handle_command({"op": "display.show_response_delta", "args": {"text_delta": "Hello", "is_final": False}})
    assert app._ui_mode == UIMode.CARD
    assert app._card.body.endswith("Hello")


def test_draw_frame_and_ascii_blob_cover_modes(app: HandheldApp, monkeypatch) -> None:
    monkeypatch.setattr(app_mod.time, "time", lambda: 100.0)
    app._online = True
    app._ui_mode = UIMode.CONNECTING
    app._draw_frame()
    assert app.renderer.calls

    waiting_blob = app._ascii_blob_lines()
    app._ui_mode = UIMode.CARD
    card_blob = app._ascii_blob_lines()
    app._ui_mode = UIMode.ERROR
    error_blob = app._ascii_blob_lines()

    assert waiting_blob
    assert card_blob
    assert error_blob
    assert isinstance(waiting_blob[0], str)
    assert isinstance(card_blob[0], str)
    assert isinstance(error_blob[0], str)


def test_ascii_character_size_small_uses_mini_frames(monkeypatch) -> None:
    monkeypatch.setattr(app_mod, "Sdl2Input", StubInput)
    monkeypatch.setattr(app_mod, "Sdl2Renderer", StubRenderer)
    monkeypatch.setattr(app_mod, "HandheldAudio", StubAudio)
    monkeypatch.setattr(HandheldApp, "_get_version", lambda self: "testver")
    monkeypatch.setattr(app_mod.time, "time", lambda: 100.0)

    app = HandheldApp("ws://gateway/datp", "dev1", "handheld", character_size="small")
    app._character_state = "playing"
    blob = app._ascii_blob_lines()

    assert len(blob) == 1
    assert blob[0] in {"(o_o)♪", "(^_^)♫"}


@pytest.mark.asyncio
async def test_settings_persist_callback_invoked(monkeypatch) -> None:
    monkeypatch.setattr(app_mod, "Sdl2Input", StubInput)
    monkeypatch.setattr(app_mod, "Sdl2Renderer", StubRenderer)
    monkeypatch.setattr(app_mod, "HandheldAudio", StubAudio)
    monkeypatch.setattr(HandheldApp, "_get_version", lambda self: "testver")
    writes = []

    app = HandheldApp(
        "ws://gateway/datp",
        "dev1",
        "handheld",
        settings_persist=lambda payload: writes.append(payload),
    )
    app._ui_mode = UIMode.HOME
    await app._handle_input(SimpleNamespace(type="button", name="select", action="pressed", raw=0))
    app._menu_idx = app._menu_items().index("Show Progress")
    await app._handle_input(SimpleNamespace(type="button", name="a", action="pressed", raw=0))

    assert writes
    latest = writes[-1]
    assert "character_size" in latest
    assert "show_progress_messages" in latest
    assert "show_celebrations" in latest
    assert "brightness" in latest
    assert "volume" in latest
    assert "led_enabled" in latest
    assert "mute_duration_hours" in latest
