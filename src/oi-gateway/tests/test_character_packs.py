"""Tests for the character packs module (Phase 2)."""
from __future__ import annotations

import json
import asyncio

import pytest

# Ensure src is on the path
from pathlib import Path
gateway_src = Path(__file__).parent.parent / "src"
import sys
if str(gateway_src) not in sys.path:
    sys.path.insert(0, str(gateway_src))

from character_packs import (
    CharacterPack,
    StateConfig,
    SemanticState,
    Overlay,
    CharacterPackStore,
    CharacterPackService,
    BuiltInPacks,
    REQUIRED_STATES,
)


EXPECTED_REQUIRED_STATES = [
    "idle",
    "listening",
    "uploading",
    "thinking",
    "response_cached",
    "playing",
    "confirm",
    "muted",
    "offline",
    "error",
    "safe_mode",
    "task_running",
    "blocked",
]

COMPLETE_PACK_STATES = {
    "idle": StateConfig(sprite="idle.png", label="Ready"),
    "listening": StateConfig(sprite="listen.png", label="Listening"),
    "uploading": StateConfig(sprite="upload.png", label="Uploading"),
    "thinking": StateConfig(sprite="think.png", label="Thinking"),
    "response_cached": StateConfig(sprite="ready.png", label="Ready"),
    "playing": StateConfig(sprite="speak.png", label="Speaking"),
    "confirm": StateConfig(sprite="confirm.png", label="Confirm"),
    "muted": StateConfig(sprite="muted.png", label="Muted"),
    "offline": StateConfig(sprite="offline.png", label="Offline"),
    "error": StateConfig(sprite="error.png", label="Error"),
    "safe_mode": StateConfig(sprite="safe.png", label="Safe Mode"),
    "task_running": StateConfig(sprite="task.png", label="Working"),
    "blocked": StateConfig(sprite="blocked.png", label="Blocked"),
}


# ------------------------------------------------------------------
# StateConfig tests
# ------------------------------------------------------------------

def test_state_config_creation():
    """StateConfig stores sprite, label, and optional animation."""
    cfg = StateConfig(sprite="idle.png", label="Ready")
    assert cfg.sprite == "idle.png"
    assert cfg.label == "Ready"
    assert cfg.animation is None

    cfg_anim = StateConfig(sprite="think.png", label="Thinking", animation="spin")
    assert cfg_anim.animation == "spin"


def test_state_config_to_dict():
    """StateConfig serializes to dict correctly."""
    cfg = StateConfig(sprite="idle.png", label="Ready", animation=None)
    assert cfg.to_dict() == {"sprite": "idle.png", "label": "Ready", "animation": None}

    cfg_anim = StateConfig(sprite="listen.png", label="Listening", animation="pulse")
    assert cfg_anim.to_dict() == {"sprite": "listen.png", "label": "Listening", "animation": "pulse"}


# ------------------------------------------------------------------
# CharacterPack tests
# ------------------------------------------------------------------

def test_character_pack_creation():
    """CharacterPack stores pack metadata and states."""
    states = {
        "idle": StateConfig(sprite="idle.png", label="Ready"),
        "thinking": StateConfig(sprite="think.png", label="Thinking", animation="spin"),
    }
    pack = CharacterPack(
        pack_id="test-pack",
        target="tiny_135x240",
        format="indexed_png",
        states=states,
        version="1.0",
    )
    assert pack.pack_id == "test-pack"
    assert pack.target == "tiny_135x240"
    assert pack.format == "indexed_png"
    assert pack.version == "1.0"
    assert "idle" in pack.states
    assert "thinking" in pack.states


def test_character_pack_to_dict():
    """CharacterPack serializes to dict for API responses."""
    pack = CharacterPack(
        pack_id="synth-goblin",
        target="tiny_135x240",
        format="indexed_png",
        states={
            "idle": StateConfig(sprite="idle.png", label="Ready"),
        },
        version="1.0",
    )
    d = pack.to_dict()
    assert d["pack_id"] == "synth-goblin"
    assert d["target"] == "tiny_135x240"
    assert d["format"] == "indexed_png"
    assert d["states"]["idle"]["sprite"] == "idle.png"
    assert d["states"]["idle"]["label"] == "Ready"


def test_character_pack_from_dict():
    """CharacterPack deserializes from dict."""
    data = {
        "pack_id": "synth-goblin",
        "target": "tiny_135x240",
        "format": "indexed_png",
        "version": "1.0",
        "states": {
            "idle": {"sprite": "idle.png", "label": "Ready"},
            "thinking": {"sprite": "think.png", "label": "Thinking", "animation": "spin"},
        },
        "overlays": {
            "battery_low": {"sprite": "battery_low.png", "label": "Low Battery"},
        },
    }
    pack = CharacterPack.from_dict(data)
    assert pack.pack_id == "synth-goblin"
    assert pack.states["idle"].sprite == "idle.png"
    assert pack.states["thinking"].animation == "spin"
    assert pack.overlays["battery_low"].label == "Low Battery"


def test_character_pack_overlays_optional():
    """CharacterPack without overlays serializes correctly."""
    pack = CharacterPack(
        pack_id="no-overlays",
        target="tiny_135x240",
        format="indexed_png",
        states={"idle": StateConfig(sprite="idle.png", label="Ready")},
    )
    d = pack.to_dict()
    assert d["overlays"] is None


# ------------------------------------------------------------------
# SemanticState and REQUIRED_STATES tests
# ------------------------------------------------------------------

def test_semantic_states_defined():
    """All required semantic states are defined in the enum."""
    for state in EXPECTED_REQUIRED_STATES:
        assert hasattr(SemanticState, state.upper())
        assert SemanticState[state.upper()].value == state


def test_overlay_states_defined():
    """Optional overlay states are defined."""
    overlays = [
        "battery_low",
        "wifi_weak",
        "tool_running",
        "code_task",
        "home_task",
        "calendar_task",
        "wiki_update",
        "private_content",
        "remote_connection",
        "cloud_model",
    ]
    for overlay in overlays:
        assert hasattr(Overlay, overlay.upper())


def test_required_states_list():
    """REQUIRED_STATES contains all required state names."""
    assert REQUIRED_STATES == EXPECTED_REQUIRED_STATES


# ------------------------------------------------------------------
# CharacterPackStore tests
# ------------------------------------------------------------------

def test_store_upsert_pack(tmp_path):
    """Store can insert and retrieve a character pack."""
    db_path = str(tmp_path / "packs.db")
    store = CharacterPackStore(db_path)

    pack = CharacterPack(
        pack_id="test-store",
        target="tiny_135x240",
        format="indexed_png",
        states={
            "idle": StateConfig(sprite="idle.png", label="Ready"),
        },
    )
    store.upsert_pack(pack)

    retrieved = store.get_pack("test-store")
    assert retrieved is not None
    assert retrieved.pack_id == "test-store"
    assert retrieved.target == "tiny_135x240"


def test_store_get_nonexistent_pack(tmp_path):
    """Store returns None for nonexistent pack."""
    db_path = str(tmp_path / "packs.db")
    store = CharacterPackStore(db_path)

    result = store.get_pack("nonexistent")
    assert result is None


def test_store_list_packs(tmp_path):
    """Store can list all registered packs."""
    db_path = str(tmp_path / "packs.db")
    store = CharacterPackStore(db_path)

    pack1 = CharacterPack(
        pack_id="pack-1",
        target="tiny_135x240",
        format="indexed_png",
        states={"idle": StateConfig(sprite="idle.png", label="Ready")},
    )
    pack2 = CharacterPack(
        pack_id="pack-2",
        target="tiny_135x240",
        format="spritesheet",
        states={"idle": StateConfig(sprite="idle_sheet.png", label="Ready")},
    )
    store.upsert_pack(pack1)
    store.upsert_pack(pack2)

    packs = store.list_packs()
    assert len(packs) == 2
    pack_ids = [p.pack_id for p in packs]
    assert "pack-1" in pack_ids
    assert "pack-2" in pack_ids


def test_store_update_pack(tmp_path):
    """Store can update an existing pack."""
    db_path = str(tmp_path / "packs.db")
    store = CharacterPackStore(db_path)

    pack = CharacterPack(
        pack_id="update-test",
        target="tiny_135x240",
        format="indexed_png",
        states={"idle": StateConfig(sprite="idle.png", label="Ready")},
    )
    store.upsert_pack(pack)

    updated_pack = CharacterPack(
        pack_id="update-test",
        target="tiny_135x240",
        format="indexed_png",
        states={
            "idle": StateConfig(sprite="idle_v2.png", label="Ready v2"),
            "thinking": StateConfig(sprite="think.png", label="Thinking"),
        },
        version="2.0",
    )
    store.upsert_pack(updated_pack)

    retrieved = store.get_pack("update-test")
    assert retrieved.version == "2.0"
    assert retrieved.states["idle"].sprite == "idle_v2.png"
    assert "thinking" in retrieved.states


def test_store_delete_pack(tmp_path):
    """Store can delete a pack."""
    db_path = str(tmp_path / "packs.db")
    store = CharacterPackStore(db_path)

    pack = CharacterPack(
        pack_id="delete-me",
        target="tiny_135x240",
        format="indexed_png",
        states={"idle": StateConfig(sprite="idle.png", label="Ready")},
    )
    store.upsert_pack(pack)
    assert store.get_pack("delete-me") is not None

    store.delete_pack("delete-me")
    assert store.get_pack("delete-me") is None


def test_store_get_packs_by_target(tmp_path):
    """Store can filter packs by target device type."""
    db_path = str(tmp_path / "packs.db")
    store = CharacterPackStore(db_path)

    pack1 = CharacterPack(
        pack_id="tiny-pack",
        target="tiny_135x240",
        format="indexed_png",
        states={"idle": StateConfig(sprite="idle.png", label="Ready")},
    )
    pack2 = CharacterPack(
        pack_id="watch-pack",
        target="watch_240x280",
        format="indexed_png",
        states={"idle": StateConfig(sprite="idle.png", label="Ready")},
    )
    store.upsert_pack(pack1)
    store.upsert_pack(pack2)

    tiny_packs = store.get_packs_by_target("tiny_135x240")
    assert len(tiny_packs) == 1
    assert tiny_packs[0].pack_id == "tiny-pack"


# ------------------------------------------------------------------
# CharacterPackService tests
# ------------------------------------------------------------------

def test_service_register_pack(tmp_path):
    """Service can register a new character pack."""
    db_path = str(tmp_path / "packs.db")
    store = CharacterPackStore(db_path)
    service = CharacterPackService(store)

    pack = CharacterPack(
        pack_id="service-test",
        target="tiny_135x240",
        format="indexed_png",
        states={
            "idle": StateConfig(sprite="idle.png", label="Ready"),
            "thinking": StateConfig(sprite="think.png", label="Thinking"),
        },
    )
    result = service.register_pack(pack)
    assert result is True

    retrieved = service.get_pack("service-test")
    assert retrieved is not None
    assert retrieved.pack_id == "service-test"


def test_service_register_duplicate_pack(tmp_path):
    """Service rejects duplicate pack registration."""
    db_path = str(tmp_path / "packs.db")
    store = CharacterPackStore(db_path)
    service = CharacterPackService(store)

    pack = CharacterPack(
        pack_id="duplicate-test",
        target="tiny_135x240",
        format="indexed_png",
        states={"idle": StateConfig(sprite="idle.png", label="Ready")},
    )
    result1 = service.register_pack(pack)
    assert result1 is True

    result2 = service.register_pack(pack)
    assert result2 is False  # Should reject duplicate


def test_service_list_packs(tmp_path):
    """Service lists all registered packs."""
    db_path = str(tmp_path / "packs.db")
    store = CharacterPackStore(db_path)
    service = CharacterPackService(store)

    for i in range(3):
        pack = CharacterPack(
            pack_id=f"list-test-{i}",
            target="tiny_135x240",
            format="indexed_png",
            states={"idle": StateConfig(sprite="idle.png", label="Ready")},
        )
        service.register_pack(pack)

    packs = service.list_packs()
    assert len(packs) == 3


def test_service_get_packs_by_target(tmp_path):
    """Service filters packs by target."""
    db_path = str(tmp_path / "packs.db")
    store = CharacterPackStore(db_path)
    service = CharacterPackService(store)

    pack1 = CharacterPack(
        pack_id="tiny-pack",
        target="tiny_135x240",
        format="indexed_png",
        states={"idle": StateConfig(sprite="idle.png", label="Ready")},
    )
    pack2 = CharacterPack(
        pack_id="watch-pack",
        target="watch_240x280",
        format="indexed_png",
        states={"idle": StateConfig(sprite="idle.png", label="Ready")},
    )
    service.register_pack(pack1)
    service.register_pack(pack2)

    tiny_packs = service.get_packs_by_target("tiny_135x240")
    assert len(tiny_packs) == 1
    assert tiny_packs[0].pack_id == "tiny-pack"


def test_service_validate_pack_missing_state(tmp_path):
    """Service validates that pack has all required states."""
    db_path = str(tmp_path / "packs.db")
    store = CharacterPackStore(db_path)
    service = CharacterPackService(store)

    # Pack missing required states
    pack = CharacterPack(
        pack_id="incomplete-pack",
        target="tiny_135x240",
        format="indexed_png",
        states={
            "idle": StateConfig(sprite="idle.png", label="Ready"),
            # Missing: listening, thinking, etc.
        },
    )
    is_valid, errors = service.validate_pack(pack)
    assert is_valid is False
    assert len(errors) > 0
    assert any("listening" in err.lower() for err in errors)


def test_service_validate_pack_complete(tmp_path):
    """Service validates complete pack."""
    db_path = str(tmp_path / "packs.db")
    store = CharacterPackStore(db_path)
    service = CharacterPackService(store)

    pack = CharacterPack(
        pack_id="complete-pack",
        target="tiny_135x240",
        format="indexed_png",
        states=COMPLETE_PACK_STATES,
    )
    is_valid, errors = service.validate_pack(pack)
    assert is_valid is True
    assert len(errors) == 0


# ------------------------------------------------------------------
# Built-in packs tests
# ------------------------------------------------------------------

def test_built_in_packs_exist():
    """Built-in packs are registered on module load."""
    from character_packs import BuiltInPacks

    # Should have at least one built-in pack
    assert len(BuiltInPacks.list()) >= 1


def test_built_in_packs_have_all_states():
    """Built-in packs have all required states."""
    from character_packs import BuiltInPacks

    for pack in BuiltInPacks.list():
        for required_state in REQUIRED_STATES:
            assert required_state in pack.states, f"Pack {pack.pack_id} missing state: {required_state}"


def test_built_in_packs_targets():
    """Built-in packs target specific device types."""
    from character_packs import BuiltInPacks

    for pack in BuiltInPacks.list():
        assert pack.target in ["tiny_135x240", "watch_240x280", "phone_390x450"]
