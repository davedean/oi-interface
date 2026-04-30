"""OpenCode agent backend via subprocess CLI invocation."""
from __future__ import annotations

import json

from .cli_backend import CliBackend


class OpenCodeBackend(CliBackend):
    """Send requests to OpenCode via `opencode run ...` subprocess."""

    backend_name = "opencode"
    backend_label = "OpenCode"

    def __init__(self, command: list[str] | None = None, timeout_seconds: float = 120.0) -> None:
        super().__init__(command or ["opencode", "run", "--format", "json"], timeout_seconds)

    def _extract_text_from_output(self, output: str) -> str:
        """Extract assistant text from `opencode run` output."""
        if not output:
            return ""

        text_parts: list[str] = []
        saw_json = False
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            saw_json = True
            if event.get("type") != "text":
                continue
            part = event.get("part")
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                text_parts.append(text.strip())

        if text_parts:
            return "\n".join(text_parts).strip()
        if saw_json:
            return ""
        return output.strip()
