from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from character_packs import (
    BuiltInPacks,
    CharacterPack,
    CharacterRendererService,
    DeviceRenderer,
    PackGenerator,
    PackValidator,
    SemanticState,
    StateConfig,
)


class EventBusStub:
    def __init__(self):
        self.handlers = []

    def subscribe(self, handler):
        self.handlers.append(handler)


class ServerStub:
    def __init__(self):
        self.event_bus = EventBusStub()
        self.send_to_device = AsyncMock(return_value=True)
        self._server = SimpleNamespace(_loop=None)


@pytest.fixture
def sample_pack():
    return CharacterPack(
        pack_id="sample",
        target="tiny_135x240",
        format="indexed_png",
        states={
            "idle": StateConfig("idle.png", "Idle"),
            "listening": StateConfig("listen.png", "Listen", "pulse"),
            "uploading": StateConfig("upload.png", "Upload"),
            "thinking": StateConfig("think.png", "Think", "spin"),
            "response_cached": StateConfig("ready.png", "Ready"),
            "playing": StateConfig("play.png", "Play", "waveform"),
            "confirm": StateConfig("confirm.png", "Confirm"),
            "muted": StateConfig("mute.png", "Muted"),
            "offline": StateConfig("off.png", "Offline"),
            "error": StateConfig("err.png", "Error"),
            "safe_mode": StateConfig("safe.png", "Safe"),
            "task_running": StateConfig("task.png", "Task"),
            "blocked": StateConfig("blocked.png", "Blocked"),
        },
        overlays={"battery_low": StateConfig("battery.png", "Low", "blink")},
    )


@pytest.fixture
def renderer_service(sample_pack):
    server = ServerStub()
    registry = SimpleNamespace(
        get_character_pack=AsyncMock(return_value=sample_pack),
        set_character_pack=AsyncMock(return_value=True),
        get_device=AsyncMock(return_value=SimpleNamespace(state={"mode": "READY"})),
    )
    return CharacterRendererService(server, registry, MagicMock()), server, registry


def test_character_renderer_service_event_mapping(renderer_service):
    service, _server, _registry = renderer_service
    service._render_state = MagicMock()
    service._invalidate_last = MagicMock()

    service._on_event("state", "dev1", {"mode": "THINKING"})
    service._on_event("event", "dev1", {"event": "button.long_hold_started"})
    service._on_event("event", "dev1", {"event": "audio.recording_finished"})
    service._on_event("event", "dev1", {"event": "button.double_tap"})
    service._on_event("event", "dev1", {"event": "audio.playback_finished"})
    service._on_event("event", "dev1", {"event": "device.error"})
    service._on_event("event", "dev1", {"event": "device.capability_updated"})

    assert service._render_state.call_count >= 5
    service._invalidate_last.assert_called_once_with("dev1")


def test_character_renderer_service_mapping_helpers(renderer_service):
    service, server, _registry = renderer_service
    assert service._map_to_semantic_state(None) == SemanticState.IDLE
    assert service._map_to_semantic_state("playing") == SemanticState.PLAYING
    assert service._map_to_semantic_state("unknown") == SemanticState.IDLE
    assert service._map_command_to_semantic("display.show_status", {"state": "MUTED", "label": "Muted"}) == (SemanticState.MUTED, "Muted")
    assert service._map_command_to_semantic("audio.cache.put_begin", {}) == (SemanticState.UPLOADING, "Buffering")
    assert service._map_command_to_semantic("audio.cache.put_end", {}) == (SemanticState.RESPONSE_CACHED, "Ready")
    assert service._map_command_to_semantic("audio.play", {}) == (SemanticState.PLAYING, "Speaking")
    assert service._map_command_to_semantic("audio.stop", {}) == (SemanticState.IDLE, None)
    assert service._map_command_to_semantic("device.mute_until", {}) == (SemanticState.MUTED, "Muted")
    assert service._map_command_to_semantic("device.reboot", {}) == (SemanticState.IDLE, "Booting")
    assert service._map_command_to_semantic("device.shutdown", {}) == (SemanticState.OFFLINE, "Off")
    assert service._map_command_to_semantic("other", {}) == (None, None)

    loop = MagicMock()
    loop.is_running.return_value = True
    server._server._loop = loop
    def fake_run_coroutine_threadsafe(coro, _loop):
        coro.close()
        return MagicMock()

    with patch("asyncio.run_coroutine_threadsafe", side_effect=fake_run_coroutine_threadsafe) as rcts:
        service.render_for_command("dev1", "audio.play", {})
        rcts.assert_called_once()


@pytest.mark.asyncio
async def test_character_renderer_service_render_state_async_paths(renderer_service, sample_pack):
    service, server, registry = renderer_service
    service.disable_rendering("dev1")
    assert await service._render_state_async("dev1", SemanticState.IDLE) is False
    service.enable_rendering("dev1")

    service._last_rendered["dev1"] = (SemanticState.IDLE, None)
    assert await service._render_state_async("dev1", SemanticState.IDLE) is True
    service._last_rendered.clear()

    registry.get_character_pack = AsyncMock(return_value=None)
    with patch.object(BuiltInPacks, "list", return_value=[]):
        assert await service._render_state_async("dev1", SemanticState.IDLE) is False

    registry.get_character_pack = AsyncMock(return_value=sample_pack)
    assert await service._render_state_async("dev1", SemanticState.IDLE, "Custom") is True
    assert service._last_rendered["dev1"] == (SemanticState.IDLE, "Custom")

    with patch.object(DeviceRenderer, "render", side_effect=RuntimeError("boom")):
        assert await service._render_state_async("dev1", SemanticState.IDLE) is False


@pytest.mark.asyncio
async def test_character_renderer_service_set_pack_and_status(renderer_service):
    service, _server, registry = renderer_service
    service._render_from_display_state = MagicMock()
    service._last_rendered["dev1"] = (SemanticState.PLAYING, "Now")

    assert await service.set_character_pack_async("dev1", "sample") is True
    service._render_from_display_state.assert_called_once_with("dev1", "READY")
    status = service.get_rendering_status("dev1")
    assert status["rendering_enabled"] is True
    assert status["last_rendered"] is None
    assert "idle" in service.get_available_states("dev1")

    registry.set_character_pack = AsyncMock(return_value=False)
    assert await service.set_character_pack_async("dev1", "sample") is False


def test_character_renderer_service_render_state_handles_runtime_error(renderer_service):
    service, _server, _registry = renderer_service

    def fake_create_task(coro):
        coro.close()
        raise RuntimeError

    with patch("asyncio.create_task", side_effect=fake_create_task):
        service._render_state("dev1", SemanticState.IDLE)


def test_character_pack_validator_and_generator_extra_cases(sample_pack):
    too_long = "x" * (PackValidator.MAX_SPRITE_PATH_LENGTH + 1)
    label_long = "y" * (PackValidator.MAX_LABEL_LENGTH + 1)
    bad_pack = CharacterPack(
        pack_id="ok-pack",
        target="tiny_135x240",
        format="indexed_png",
        states={state: StateConfig(too_long if state == "idle" else f"{state}.png", label_long if state == "listening" else state.title()) for state in sample_pack.states},
        overlays={"battery_low": StateConfig("battery.png", "Low", "bad-anim")},
    )
    is_valid, errors = PackValidator.validate(bad_pack)
    assert is_valid is False
    assert any("sprite path too long" in e for e in errors)
    assert any("label too long" in e for e in errors)
    assert any("Overlay 'battery_low': invalid animation" in e for e in errors)

    generated = PackGenerator.generate_from_prompt("friendly gentle minimal fox")
    assert generated.pack_id.startswith("gen-")
    assert generated.states["idle"].label in {"Hello!", "•"}
    fallback = PackGenerator.generate_from_prompt("a b")
    assert fallback.pack_id == "gen-custom"
