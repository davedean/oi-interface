from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from oi_client.capabilities import (  # noqa: E402
    EXTENDED_COMMANDS,
    OPTIONAL_COMMANDS,
    REQUIRED_COMMANDS,
    SUPPORTED_COMMANDS,
    RuntimeAudioStatus,
    build_capabilities,
)


def test_supported_commands_cover_required_optional_and_extended() -> None:
    for command_group in (REQUIRED_COMMANDS, OPTIONAL_COMMANDS, EXTENDED_COMMANDS):
        for command in command_group:
            assert command in SUPPORTED_COMMANDS


def test_build_capabilities_reflects_runtime_audio() -> None:
    caps = build_capabilities(RuntimeAudioStatus(has_input=True, has_output=False), 24, 8)
    assert caps["display_width"] == 24
    assert caps["display_height"] == 8
    assert caps["has_audio_input"] is True
    assert caps["has_audio_output"] is False
    assert "hold_to_record" in caps["input"]
    assert caps["commands_supported"] == SUPPORTED_COMMANDS
