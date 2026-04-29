"""Tests for the DeviceRenderer service."""
from __future__ import annotations

import pytest

from pathlib import Path
gateway_src = Path(__file__).parent.parent / "src"
import sys
if str(gateway_src) not in sys.path:
    sys.path.insert(0, str(gateway_src))

from character_packs import (
    CharacterPack,
    StateConfig,
    DeviceRenderer,
    RenderInstruction,
    SemanticState,
)


# ------------------------------------------------------------------
# DeviceRenderer tests
# ------------------------------------------------------------------

def test_renderer_creation():
    """DeviceRenderer can be created with a character pack."""
    pack = CharacterPack(
        pack_id="test-pack",
        target="tiny_135x240",
        format="indexed_png",
        states={
            "idle": StateConfig(sprite="idle.png", label="Ready"),
        },
    )
    renderer = DeviceRenderer(pack)
    assert renderer.pack == pack


def test_render_idle_state():
    """Renderer produces correct instruction for idle state."""
    pack = CharacterPack(
        pack_id="test-pack",
        target="tiny_135x240",
        format="indexed_png",
        states={
            "idle": StateConfig(sprite="idle.png", label="Ready", animation=None),
        },
    )
    renderer = DeviceRenderer(pack)
    instruction = renderer.render("idle")

    assert isinstance(instruction, RenderInstruction)
    assert instruction.sprite_path == "idle.png"
    assert instruction.label == "Ready"
    assert instruction.animation is None
    assert instruction.overlay_sprite_path is None
    assert instruction.overlay_label is None


def test_render_state_with_animation():
    """Renderer includes animation when specified."""
    pack = CharacterPack(
        pack_id="test-pack",
        target="tiny_135x240",
        format="indexed_png",
        states={
            "thinking": StateConfig(sprite="think.png", label="Thinking", animation="spin"),
        },
    )
    renderer = DeviceRenderer(pack)
    instruction = renderer.render("thinking")

    assert instruction.sprite_path == "think.png"
    assert instruction.label == "Thinking"
    assert instruction.animation == "spin"


def test_render_with_custom_label():
    """Renderer uses custom label when provided."""
    pack = CharacterPack(
        pack_id="test-pack",
        target="tiny_135x240",
        format="indexed_png",
        states={
            "idle": StateConfig(sprite="idle.png", label="Ready"),
        },
    )
    renderer = DeviceRenderer(pack)
    instruction = renderer.render("idle", custom_label="Hello!")

    assert instruction.label == "Hello!"


def test_render_with_overlay():
    """Renderer includes overlay when specified."""
    pack = CharacterPack(
        pack_id="test-pack",
        target="tiny_135x240",
        format="indexed_png",
        states={
            "idle": StateConfig(sprite="idle.png", label="Ready"),
        },
        overlays={
            "battery_low": StateConfig(sprite="battery_low.png", label="Low"),
        },
    )
    renderer = DeviceRenderer(pack)
    instruction = renderer.render("idle", overlay="battery_low")

    assert instruction.sprite_path == "idle.png"
    assert instruction.overlay_sprite_path == "battery_low.png"
    assert instruction.overlay_label == "Low"


def test_render_invalid_state_raises():
    """Renderer raises ValueError for unknown state."""
    pack = CharacterPack(
        pack_id="test-pack",
        target="tiny_135x240",
        format="indexed_png",
        states={
            "idle": StateConfig(sprite="idle.png", label="Ready"),
        },
    )
    renderer = DeviceRenderer(pack)
    with pytest.raises(ValueError, match="State 'unknown' not found"):
        renderer.render("unknown")


def test_render_invalid_overlay_raises():
    """Renderer raises ValueError for unknown overlay."""
    pack = CharacterPack(
        pack_id="test-pack",
        target="tiny_135x240",
        format="indexed_png",
        states={
            "idle": StateConfig(sprite="idle.png", label="Ready"),
        },
    )
    renderer = DeviceRenderer(pack)
    with pytest.raises(ValueError, match="Overlay 'unknown' not found"):
        renderer.render("idle", overlay="unknown")


def test_to_datp_command():
    """DeviceRenderer.to_datp_command (via render) creates valid DATP args."""
    pack = CharacterPack(
        pack_id="test-pack",
        target="tiny_135x240",
        format="indexed_png",
        states={
            "idle": StateConfig(sprite="idle.png", label="Ready"),
        },
        overlays={
            "battery_low": StateConfig(sprite="battery_low.png", label="Low"),
        },
    )
    renderer = DeviceRenderer(pack)
    instruction = renderer.render("idle", overlay="battery_low")

    # Check instruction data that would be used in DATP command
    assert instruction.sprite_path == "idle.png"
    assert instruction.label == "Ready"
    assert instruction.animation is None
    assert instruction.overlay_sprite_path == "battery_low.png"
    assert instruction.overlay_label == "Low"


def test_get_available_states():
    """Renderer can list available states."""
    pack = CharacterPack(
        pack_id="test-pack",
        target="tiny_135x240",
        format="indexed_png",
        states={
            "idle": StateConfig(sprite="idle.png", label="Ready"),
            "thinking": StateConfig(sprite="think.png", label="Thinking"),
        },
    )
    renderer = DeviceRenderer(pack)
    states = renderer.get_available_states()

    assert "idle" in states
    assert "thinking" in states


def test_get_available_overlays():
    """Renderer can list available overlays."""
    pack = CharacterPack(
        pack_id="test-pack",
        target="tiny_135x240",
        format="indexed_png",
        states={
            "idle": StateConfig(sprite="idle.png", label="Ready"),
        },
        overlays={
            "battery_low": StateConfig(sprite="battery_low.png", label="Low"),
        },
    )
    renderer = DeviceRenderer(pack)
    overlays = renderer.get_available_overlays()

    assert overlays is not None
    assert "battery_low" in overlays


def test_render_label_length_truncation():
    """Renderer truncates long labels with ellipsis."""
    pack = CharacterPack(
        pack_id="test-pack",
        target="tiny_135x240",
        format="indexed_png",
        states={
            "idle": StateConfig(sprite="idle.png", label="A" * 20),  # 20 chars
        },
    )
    renderer = DeviceRenderer(pack)
    instruction = renderer.render("idle")

    # Max for tiny_135x240 is 12 chars
    assert len(instruction.label) <= 12
    assert instruction.label.endswith("…")


def test_multiple_renderers_independent():
    """Multiple renderers with different packs work independently."""
    pack1 = CharacterPack(
        pack_id="pack-1",
        target="tiny_135x240",
        format="indexed_png",
        states={
            "idle": StateConfig(sprite="idle1.png", label="Ready1"),
        },
    )
    pack2 = CharacterPack(
        pack_id="pack-2",
        target="tiny_135x240",
        format="indexed_png",
        states={
            "idle": StateConfig(sprite="idle2.png", label="Ready2"),
        },
    )
    renderer1 = DeviceRenderer(pack1)
    renderer2 = DeviceRenderer(pack2)

    assert renderer1.render("idle").sprite_path == "idle1.png"
    assert renderer2.render("idle").sprite_path == "idle2.png"
