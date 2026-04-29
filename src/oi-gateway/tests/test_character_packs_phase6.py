"""Tests for Phase 6: Character packs enhancements and device rendering.

This module tests:
- Additional built-in character packs
- Device renderer functionality
- Enhanced pack validation
- Experimental pack generation
"""
from __future__ import annotations

import pytest
from pathlib import Path

# Ensure src is on the path
gateway_src = Path(__file__).parent.parent / "src"
import sys
if str(gateway_src) not in sys.path:
    sys.path.insert(0, str(gateway_src))

from character_packs import (
    CharacterPack,
    StateConfig,
    BuiltInPacks,
    DeviceRenderer,
    RenderInstruction,
    PackValidator,
    PackGenerator,
    REQUIRED_STATES,
)


# ------------------------------------------------------------------
# Built-in Packs Tests (Phase 6)
# ------------------------------------------------------------------

class TestBuiltInPacksPhase6:
    """Test the additional built-in packs added in Phase 6."""

    def test_built_in_packs_count(self):
        """Built-in packs should have at least 8 packs now."""
        packs = BuiltInPacks.list()
        assert len(packs) >= 8, f"Expected at least 8 packs, got {len(packs)}"

    def test_new_packs_have_all_required_states(self):
        """All new built-in packs should have all required states."""
        packs = BuiltInPacks.list()
        
        # Check the new packs (after the original 4)
        new_pack_ids = ["wise-owl", "cute-cat", "geometric-glyph", "nature-leaf", "neon-fox", "crystal-gem"]
        
        for pack in packs:
            if pack.pack_id in new_pack_ids:
                for required_state in REQUIRED_STATES:
                    assert required_state in pack.states, (
                        f"Pack {pack.pack_id} missing required state: {required_state}"
                    )

    def test_wise_owl_pack_exists(self):
        """Wise owl pack should exist."""
        packs = BuiltInPacks.list()
        pack_ids = [p.pack_id for p in packs]
        assert "wise-owl" in pack_ids, "wise-owl pack should exist"
        
        owl_pack = next(p for p in packs if p.pack_id == "wise-owl")
        assert owl_pack.target == "tiny_135x240"
        assert owl_pack.states["idle"].label == " Awake"
        assert owl_pack.overlays is not None

    def test_cute_cat_pack_exists(self):
        """Cute cat pack should exist."""
        packs = BuiltInPacks.list()
        pack_ids = [p.pack_id for p in packs]
        assert "cute-cat" in pack_ids
        
        cat_pack = next(p for p in packs if p.pack_id == "cute-cat")
        assert cat_pack.states["listening"].label == "Alert!"
        assert cat_pack.states["playing"].animation == "waveform"

    def test_geometric_glyph_pack_exists(self):
        """Geometric glyph pack should exist."""
        packs = BuiltInPacks.list()
        pack_ids = [p.pack_id for p in packs]
        assert "geometric-glyph" in pack_ids
        
        glyph_pack = next(p for p in packs if p.pack_id == "geometric-glyph")
        assert glyph_pack.states["idle"].label == "◇"
        assert glyph_pack.states["muted"].label == "⊘"

    def test_nature_leaf_pack_exists(self):
        """Nature leaf pack should exist."""
        packs = BuiltInPacks.list()
        pack_ids = [p.pack_id for p in packs]
        assert "nature-leaf" in pack_ids
        
        leaf_pack = next(p for p in packs if p.pack_id == "nature-leaf")
        assert leaf_pack.states["idle"].label == "Resting"
        assert leaf_pack.overlays is not None
        assert "battery_low" in leaf_pack.overlays

    def test_neon_fox_pack_exists(self):
        """Neon fox pack should exist with overlays."""
        packs = BuiltInPacks.list()
        pack_ids = [p.pack_id for p in packs]
        assert "neon-fox" in pack_ids
        
        fox_pack = next(p for p in packs if p.pack_id == "neon-fox")
        assert fox_pack.states["thinking"].label == "Hacking"
        assert fox_pack.overlays is not None
        assert "tool_running" in fox_pack.overlays
        assert "code_task" in fox_pack.overlays

    def test_crystal_gem_pack_exists(self):
        """Crystal gem pack should exist."""
        packs = BuiltInPacks.list()
        pack_ids = [p.pack_id for p in packs]
        assert "crystal-gem" in pack_ids
        
        gem_pack = next(p for p in packs if p.pack_id == "crystal-gem")
        assert gem_pack.states["idle"].label == "Radiant"
        assert gem_pack.overlays is not None
        assert "cloud_model" in gem_pack.overlays


# ------------------------------------------------------------------
# Device Renderer Tests
# ------------------------------------------------------------------

class TestDeviceRenderer:
    """Test the DeviceRenderer class."""

    @pytest.fixture
    def sample_pack(self) -> CharacterPack:
        """Create a sample pack for testing."""
        states = {
            "idle": StateConfig(sprite="test-idle.png", label="Ready", animation=None),
            "thinking": StateConfig(sprite="test-think.png", label="Thinking", animation="spin"),
            "playing": StateConfig(sprite="test-speak.png", label="Speaking", animation="waveform"),
            "muted": StateConfig(sprite="test-mute.png", label="Muted", animation=None),
        }
        overlays = {
            "battery_low": StateConfig(sprite="battery-low.png", label="Low", animation="blink"),
        }
        return CharacterPack(
            pack_id="test-pack",
            target="tiny_135x240",
            format="indexed_png",
            states=states,
            version="1.0",
            overlays=overlays,
        )

    def test_renderer_initialization(self, sample_pack):
        """Renderer initializes with a pack."""
        renderer = DeviceRenderer(sample_pack)
        assert renderer.pack == sample_pack

    def test_render_basic_state(self, sample_pack):
        """Renderer can render a basic state."""
        renderer = DeviceRenderer(sample_pack)
        instruction = renderer.render("idle")
        
        assert isinstance(instruction, RenderInstruction)
        assert instruction.sprite_path == "test-idle.png"
        assert instruction.label == "Ready"
        assert instruction.animation is None

    def test_render_state_with_animation(self, sample_pack):
        """Renderer can render state with animation."""
        renderer = DeviceRenderer(sample_pack)
        instruction = renderer.render("thinking")
        
        assert instruction.sprite_path == "test-think.png"
        assert instruction.label == "Thinking"
        assert instruction.animation == "spin"

    def test_render_state_with_overlay(self, sample_pack):
        """Renderer can render state with overlay."""
        renderer = DeviceRenderer(sample_pack)
        instruction = renderer.render("idle", overlay="battery_low")
        
        assert instruction.overlay_sprite_path == "battery-low.png"
        assert instruction.overlay_label == "Low"

    def test_render_custom_label(self, sample_pack):
        """Renderer accepts custom label override."""
        renderer = DeviceRenderer(sample_pack)
        instruction = renderer.render("idle", custom_label="Custom Label")
        
        assert instruction.label == "Custom Label"

    def test_render_label_truncation(self, sample_pack):
        """Renderer truncates long labels."""
        renderer = DeviceRenderer(sample_pack)
        
        # Create a very long label
        long_label = "A" * 50
        instruction = renderer.render("idle", custom_label=long_label)
        
        # Should be truncated to max length (12 for tiny_135x240) minus 1 for ellipsis
        assert len(instruction.label) <= 12

    def test_render_invalid_state_raises(self, sample_pack):
        """Renderer raises ValueError for invalid state."""
        renderer = DeviceRenderer(sample_pack)
        
        with pytest.raises(ValueError, match="not found"):
            renderer.render("nonexistent_state")

    def test_render_invalid_overlay_raises(self, sample_pack):
        """Renderer raises ValueError for invalid overlay."""
        renderer = DeviceRenderer(sample_pack)
        
        with pytest.raises(ValueError, match="not found"):
            renderer.render("idle", overlay="invalid_overlay")

    def test_to_datp_command(self, sample_pack):
        """Renderer can produce DATP command."""
        renderer = DeviceRenderer(sample_pack)
        command = renderer.to_datp_command("thinking", overlay="battery_low")
        
        assert command["op"] == "character.set_state"
        assert command["args"]["sprite"] == "test-think.png"
        assert command["args"]["label"] == "Thinking"
        assert command["args"]["animation"] == "spin"
        assert command["args"]["overlay"] == "battery-low.png"
        assert command["args"]["pack_id"] == "test-pack"

    def test_get_available_states(self, sample_pack):
        """Renderer returns list of available states."""
        renderer = DeviceRenderer(sample_pack)
        states = renderer.get_available_states()
        
        assert "idle" in states
        assert "thinking" in states
        assert "playing" in states

    def test_get_available_overlays(self, sample_pack):
        """Renderer returns list of available overlays."""
        renderer = DeviceRenderer(sample_pack)
        overlays = renderer.get_available_overlays()
        
        assert overlays is not None
        assert "battery_low" in overlays

    def test_get_available_overlays_none(self):
        """Renderer returns None when no overlays."""
        pack = CharacterPack(
            pack_id="no-overlays",
            target="tiny_135x240",
            format="indexed_png",
            states={"idle": StateConfig(sprite="idle.png", label="Ready")},
        )
        renderer = DeviceRenderer(pack)
        
        assert renderer.get_available_overlays() is None


# ------------------------------------------------------------------
# Pack Validator Tests
# ------------------------------------------------------------------

class TestPackValidator:
    """Test the enhanced PackValidator class."""

    def test_validate_valid_pack(self):
        """Validator accepts valid pack."""
        states = {
            state: StateConfig(sprite=f"{state}.png", label=state.title(), animation=None)
            for state in REQUIRED_STATES
        }
        pack = CharacterPack(
            pack_id="valid-pack",
            target="tiny_135x240",
            format="indexed_png",
            states=states,
            version="1.0",
        )
        
        is_valid, errors = PackValidator.validate(pack)
        assert is_valid is True
        assert len(errors) == 0

    def test_validate_missing_required_state(self):
        """Validator detects missing required states."""
        states = {
            "idle": StateConfig(sprite="idle.png", label="Ready"),
            # Missing other states
        }
        pack = CharacterPack(
            pack_id="incomplete-pack",
            target="tiny_135x240",
            format="indexed_png",
            states=states,
        )
        
        is_valid, errors = PackValidator.validate(pack)
        assert is_valid is False
        assert any("Missing required state" in err for err in errors)

    def test_validate_invalid_target(self):
        """Validator detects invalid target."""
        states = {
            state: StateConfig(sprite=f"{state}.png", label=state.title())
            for state in REQUIRED_STATES
        }
        pack = CharacterPack(
            pack_id="bad-target",
            target="invalid_target",
            format="indexed_png",
            states=states,
        )
        
        is_valid, errors = PackValidator.validate(pack)
        assert is_valid is False
        assert any("Invalid target" in err for err in errors)

    def test_validate_invalid_format(self):
        """Validator detects invalid format."""
        states = {
            state: StateConfig(sprite=f"{state}.png", label=state.title())
            for state in REQUIRED_STATES
        }
        pack = CharacterPack(
            pack_id="bad-format",
            target="tiny_135x240",
            format="invalid_format",
            states=states,
        )
        
        is_valid, errors = PackValidator.validate(pack)
        assert is_valid is False
        assert any("Invalid format" in err for err in errors)

    def test_validate_missing_sprite_path(self):
        """Validator detects missing sprite path."""
        states = {
            "idle": StateConfig(sprite="", label="Ready"),
            "listening": StateConfig(sprite="listen.png", label="Listening"),
            "thinking": StateConfig(sprite="think.png", label="Thinking"),
            "response_cached": StateConfig(sprite="ready.png", label="Ready"),
            "playing": StateConfig(sprite="speak.png", label="Speaking"),
            "confirm": StateConfig(sprite="confirm.png", label="Confirm"),
            "muted": StateConfig(sprite="muted.png", label="Muted"),
            "offline": StateConfig(sprite="offline.png", label="Offline"),
            "error": StateConfig(sprite="error.png", label="Error"),
            "safe_mode": StateConfig(sprite="safe.png", label="Safe Mode"),
            "task_running": StateConfig(sprite="task.png", label="Working"),
            "blocked": StateConfig(sprite="blocked.png", label="Waiting"),
            "uploading": StateConfig(sprite="upload.png", label="Uploading"),
        }
        pack = CharacterPack(
            pack_id="no-sprite",
            target="tiny_135x240",
            format="indexed_png",
            states=states,
        )
        
        is_valid, errors = PackValidator.validate(pack)
        assert is_valid is False
        assert any("sprite path is required" in err for err in errors)

    def test_validate_missing_label(self):
        """Validator detects missing label."""
        states = {
            state: StateConfig(sprite=f"{state}.png", label="")
            for state in REQUIRED_STATES
        }
        pack = CharacterPack(
            pack_id="no-label",
            target="tiny_135x240",
            format="indexed_png",
            states=states,
        )
        
        is_valid, errors = PackValidator.validate(pack)
        assert is_valid is False
        assert any("label is required" in err for err in errors)

    def test_validate_invalid_animation(self):
        """Validator detects invalid animation."""
        states = {
            state: StateConfig(sprite=f"{state}.png", label=state.title(), animation="invalid")
            for state in REQUIRED_STATES
        }
        pack = CharacterPack(
            pack_id="bad-anim",
            target="tiny_135x240",
            format="indexed_png",
            states=states,
        )
        
        is_valid, errors = PackValidator.validate(pack)
        assert is_valid is False
        assert any("invalid animation" in err for err in errors)

    def test_validate_invalid_pack_id(self):
        """Validator detects invalid pack_id."""
        states = {
            state: StateConfig(sprite=f"{state}.png", label=state.title())
            for state in REQUIRED_STATES
        }
        pack = CharacterPack(
            pack_id="invalid id!",
            target="tiny_135x240",
            format="indexed_png",
            states=states,
        )
        
        is_valid, errors = PackValidator.validate(pack)
        assert is_valid is False
        assert any("pack_id" in err.lower() for err in errors)

    def test_validate_invalid_version(self):
        """Validator detects invalid version format."""
        states = {
            state: StateConfig(sprite=f"{state}.png", label=state.title())
            for state in REQUIRED_STATES
        }
        pack = CharacterPack(
            pack_id="test-pack",
            target="tiny_135x240",
            format="indexed_png",
            states=states,
            version="not-a-version",
        )
        
        is_valid, errors = PackValidator.validate(pack)
        assert is_valid is False
        assert any("version" in err.lower() for err in errors)

    def test_validate_overlay_missing_fields(self):
        """Validator detects missing overlay fields."""
        states = {
            state: StateConfig(sprite=f"{state}.png", label=state.title())
            for state in REQUIRED_STATES
        }
        overlays = {
            "battery_low": StateConfig(sprite="", label=""),  # Missing fields
        }
        pack = CharacterPack(
            pack_id="bad-overlay",
            target="tiny_135x240",
            format="indexed_png",
            states=states,
            overlays=overlays,
        )
        
        is_valid, errors = PackValidator.validate(pack)
        assert is_valid is False


# ------------------------------------------------------------------
# Pack Generator Tests
# ------------------------------------------------------------------

class TestPackGenerator:
    """Test the experimental PackGenerator class."""

    def test_generate_robot_style(self):
        """Generator can create robot style pack."""
        pack = PackGenerator.generate(
            pack_id="gen-robot",
            style="robot",
            label_template="technical",
        )
        
        assert pack.pack_id == "gen-robot"
        assert pack.target == "tiny_135x240"
        assert pack.format == "indexed_png"
        assert "idle" in pack.states
        assert pack.states["idle"].label == "Online"
        assert pack.states["thinking"].animation == "spin"

    def test_generate_animal_style(self):
        """Generator can create animal style pack."""
        pack = PackGenerator.generate(
            pack_id="gen-animal",
            style="animal",
            label_template="friendly",
        )
        
        assert pack.pack_id == "gen-animal"
        assert "idle" in pack.states
        # Animal style uses {name} placeholder
        assert "idle.png" in pack.states["idle"].sprite

    def test_generate_minimal_style(self):
        """Generator can create minimal style pack."""
        pack = PackGenerator.generate(
            pack_id="gen-minimal",
            style="minimal",
            label_template="minimal",
        )
        
        assert pack.pack_id == "gen-minimal"
        assert pack.states["idle"].label == "•"
        assert pack.states["thinking"].label == "..."

    def test_generate_friendly_labels(self):
        """Generator can use friendly labels."""
        pack = PackGenerator.generate(
            pack_id="gen-friendly",
            style="robot",
            label_template="friendly",
        )
        
        assert pack.states["idle"].label == "Hello!"
        assert pack.states["listening"].label == "I hear you"

    def test_generate_calm_animations(self):
        """Generator can use calm animations."""
        pack = PackGenerator.generate(
            pack_id="gen-calm",
            style="robot",
            animation_template="calm",
        )
        
        assert pack.states["listening"].animation == "fade"
        assert pack.states["thinking"].animation == "pulse"

    def test_generate_custom_labels(self):
        """Generator accepts custom labels."""
        pack = PackGenerator.generate(
            pack_id="gen-custom",
            style="robot",
            custom_labels={
                "idle": "My Custom Label",
                "thinking": "Custom Thought",
            },
        )
        
        assert pack.states["idle"].label == "My Custom Label"
        assert pack.states["thinking"].label == "Custom Thought"

    def test_generate_different_target(self):
        """Generator can create pack for different target."""
        pack = PackGenerator.generate(
            pack_id="gen-watch",
            target="watch_240x280",
        )
        
        assert pack.target == "watch_240x280"

    def test_generate_invalid_style_raises(self):
        """Generator raises on invalid style."""
        with pytest.raises(ValueError, match="Unknown style"):
            PackGenerator.generate(pack_id="test", style="invalid_style")

    def test_generate_invalid_label_template_raises(self):
        """Generator raises on invalid label template."""
        with pytest.raises(ValueError, match="Unknown label template"):
            PackGenerator.generate(pack_id="test", label_template="invalid")

    def test_generate_invalid_animation_template_raises(self):
        """Generator raises on invalid animation template."""
        with pytest.raises(ValueError, match="Unknown animation template"):
            PackGenerator.generate(pack_id="test", animation_template="invalid")

    def test_generate_from_prompt_robot(self):
        """Generator can parse robot prompt."""
        pack = PackGenerator.generate_from_prompt("technical robot assistant")
        
        assert pack.pack_id.startswith("gen-")
        assert pack.states["idle"].label == "Online"
        assert pack.states["thinking"].animation == "spin"

    def test_generate_from_prompt_friendly(self):
        """Generator can parse friendly prompt."""
        pack = PackGenerator.generate_from_prompt("friendly cute cat")
        
        assert pack.states["idle"].label == "Hello!"
        # Pack ID includes up to 3 words > 2 chars
        assert "friendly" in pack.pack_id
        assert "cute" in pack.pack_id

    def test_generate_from_prompt_minimal(self):
        """Generator can parse minimal prompt."""
        pack = PackGenerator.generate_from_prompt("simple minimal symbol")
        
        assert pack.states["idle"].label == "•"
        assert pack.states["thinking"].label == "..."

    def test_generate_from_prompt_calm(self):
        """Generator can parse calm prompt."""
        pack = PackGenerator.generate_from_prompt("calm gentle fox")
        
        assert pack.states["listening"].animation == "fade"
        assert pack.states["thinking"].animation == "pulse"

    def test_generate_from_prompt_custom_id(self):
        """Generator creates sensible pack_id from prompt."""
        pack = PackGenerator.generate_from_prompt("friendly robot dog")
        
        assert "robot" in pack.pack_id
        assert "dog" in pack.pack_id

    def test_generate_from_prompt_short_words(self):
        """Generator handles prompt with short words."""
        pack = PackGenerator.generate_from_prompt("a b c")
        
        # Should still work, just uses default
        assert pack.pack_id == "gen-custom"


# ------------------------------------------------------------------
# Integration Tests
# ------------------------------------------------------------------

class TestCharacterPacksIntegration:
    """Integration tests combining multiple components."""

    def test_renderer_with_built_in_pack(self):
        """DeviceRenderer works with built-in packs."""
        packs = BuiltInPacks.list()
        synth_goblin = next(p for p in packs if p.pack_id == "synth-goblin")
        
        renderer = DeviceRenderer(synth_goblin)
        instruction = renderer.render("thinking")
        
        assert instruction.sprite_path == "goblin-think.png"
        assert instruction.label == "Thinking"
        assert instruction.animation == "spin"

    def test_validator_with_built_in_packs(self):
        """PackValidator works with built-in packs."""
        packs = BuiltInPacks.list()
        
        for pack in packs:
            is_valid, errors = PackValidator.validate(pack)
            assert is_valid is True, f"Pack {pack.pack_id} failed validation: {errors}"

    def test_generator_produces_valid_pack(self):
        """Generator produces a pack that passes validation."""
        pack = PackGenerator.generate(
            pack_id="test-gen-valid",
            style="robot",
            label_template="technical",
        )
        
        is_valid, errors = PackValidator.validate(pack)
        assert is_valid is True, f"Generated pack failed validation: {errors}"

    def test_all_built_in_packs_pass_validation(self):
        """All built-in packs pass enhanced validation."""
        packs = BuiltInPacks.list()
        
        for pack in packs:
            is_valid, errors = PackValidator.validate(pack)
            assert is_valid is True, f"Pack {pack.pack_id} failed: {errors}"