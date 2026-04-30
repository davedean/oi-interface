from __future__ import annotations

from character_packs.models import CharacterPack, StateConfig


def test_state_config_to_dict_exact_shape():
    assert StateConfig("idle.png", "Idle").to_dict() == {
        "sprite": "idle.png",
        "label": "Idle",
        "animation": None,
    }
    assert StateConfig("think.png", "Thinking", "pulse").to_dict() == {
        "sprite": "think.png",
        "label": "Thinking",
        "animation": "pulse",
    }


def test_character_pack_to_dict_without_overlays():
    pack = CharacterPack(
        pack_id="robot-v1",
        target="tiny_135x240",
        format="indexed_png",
        states={
            "idle": StateConfig("idle.png", "Idle"),
            "thinking": StateConfig("thinking.png", "Thinking", "pulse"),
        },
    )

    assert pack.version == "1.0"
    assert pack.overlays is None
    assert pack.to_dict() == {
        "pack_id": "robot-v1",
        "target": "tiny_135x240",
        "format": "indexed_png",
        "version": "1.0",
        "states": {
            "idle": {"sprite": "idle.png", "label": "Idle", "animation": None},
            "thinking": {"sprite": "thinking.png", "label": "Thinking", "animation": "pulse"},
        },
        "overlays": None,
    }


def test_character_pack_to_dict_with_overlays_and_manual_round_trip():
    pack = CharacterPack(
        pack_id="robot-v2",
        target="watch_240x280",
        format="rgb565",
        version="2.1.0",
        states={"idle": StateConfig("idle.png", "Idle")},
        overlays={"muted": StateConfig("muted.png", "Muted", "blink")},
    )

    payload = pack.to_dict()
    assert payload["overlays"] == {
        "muted": {"sprite": "muted.png", "label": "Muted", "animation": "blink"}
    }

    rebuilt = CharacterPack(
        pack_id=payload["pack_id"],
        target=payload["target"],
        format=payload["format"],
        version=payload["version"],
        states={name: StateConfig(**cfg) for name, cfg in payload["states"].items()},
        overlays={name: StateConfig(**cfg) for name, cfg in payload["overlays"].items()},
    )

    assert rebuilt == pack
