"""Codex agent backend via subprocess CLI invocation."""
from __future__ import annotations

import json
from typing import Any

from .cli_backend import CliBackend


class CodexBackend(CliBackend):
    """Send requests to Codex via `codex exec ...` subprocess."""

    backend_name = "codex"
    backend_label = "Codex"

    def __init__(self, command: list[str] | None = None, timeout_seconds: float = 120.0) -> None:
        super().__init__(command or ["codex", "exec", "--json", "--skip-git-repo-check"], timeout_seconds)

    def _agent_args(self, agent_id: str) -> list[str]:
        return ["--agent", agent_id]

    def _extract_text_from_output(self, output: str) -> str:
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
            text = self._extract_text_from_event(event)
            if text:
                text_parts.append(text)

        if text_parts:
            return "".join(text_parts).strip()
        if saw_json:
            return ""
        return output.strip()

    def _extract_text_from_event(self, event: dict[str, Any]) -> str | None:
        event_type = event.get("type")
        if event_type in {"response.output_text.delta", "delta"}:
            delta = event.get("delta")
            if isinstance(delta, str) and delta.strip():
                return delta
        if event_type in {"response.output_text.done", "text", "agent_text"}:
            text = event.get("text")
            if isinstance(text, str) and text.strip():
                return text

        part = event.get("part")
        if isinstance(part, dict):
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                return text

        message = event.get("message")
        if isinstance(message, dict):
            role = message.get("role")
            if role in {None, "assistant"}:
                content = message.get("content")
                extracted = self._extract_text_content(content)
                if extracted:
                    return extracted

        for key in ("text", "response", "content"):
            value = event.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return None

    def _extract_text_content(self, content: Any) -> str | None:
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str) and item.strip():
                    parts.append(item)
                    continue
                if not isinstance(item, dict):
                    continue
                text = item.get("text") or item.get("content")
                if isinstance(text, str) and text.strip():
                    parts.append(text)
            if parts:
                return "".join(parts)
        return None
