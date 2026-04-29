"""Data models for character packs."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StateConfig:
    """Configuration for a semantic state."""
    sprite: str
    label: str
    animation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "sprite": self.sprite,
            "label": self.label,
            "animation": self.animation,
        }


@dataclass
class CharacterPack:
    """Character pack definition.

    Attributes:
        pack_id: Unique identifier for the pack
        target: Target device type (e.g., "tiny_135x240")
        format: Asset format (indexed_png, rgb565, spritesheet)
        states: Mapping of semantic state to state configuration
        version: Pack version string
        overlays: Optional mapping of overlay state to configuration
    """
    pack_id: str
    target: str
    format: str
    states: dict[str, StateConfig]
    version: str = "1.0"
    overlays: dict[str, StateConfig] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation for API responses."""
        return {
            "pack_id": self.pack_id,
            "target": self.target,
            "format": self.format,
            "version": self.version,
            "states": {
                name: cfg.to_dict()
                for name, cfg in self.states.items()
            },
            "overlays": {
                name: cfg.to_dict()
                for name, cfg in (self.overlays or {}).items()
            } if self.overlays else None,
        }