"""Codex agent backend via subprocess CLI invocation."""
from __future__ import annotations

import asyncio
import json
import shlex
from typing import Any

from .backend import AgentBackend, AgentBackendError, AgentRequest, AgentResponse
from .request_builder import render_text_prompt


class CodexBackend(AgentBackend):
    """Send requests to Codex via `codex exec ...` subprocess."""

    def __init__(self, command: list[str] | None = None, timeout_seconds: float = 120.0) -> None:
        self._command = command or ["codex", "exec", "--json", "--skip-git-repo-check"]
        self._timeout_seconds = timeout_seconds

    @property
    def name(self) -> str:
        return "codex"

    @property
    def command(self) -> list[str]:
        return self._command

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds

    @classmethod
    def from_command_text(cls, command: str | None, timeout_seconds: float = 120.0) -> "CodexBackend":
        cmd = shlex.split(command) if command else None
        return cls(command=cmd, timeout_seconds=timeout_seconds)

    async def send_request(self, request: AgentRequest) -> AgentResponse:
        prompt = render_text_prompt(request)
        args = [*self._command, prompt]

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self._timeout_seconds)
        except asyncio.TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise AgentBackendError(f"Codex subprocess timed out after {self._timeout_seconds:.1f}s") from exc

        stdout_text = stdout.decode(errors="replace").strip()
        stderr_text = stderr.decode(errors="replace").strip()
        if proc.returncode != 0:
            detail = stderr_text or stdout_text or f"exit code {proc.returncode}"
            raise AgentBackendError(f"Codex subprocess failed: {detail}")

        parsed_text = self._extract_text_from_output(stdout_text)
        if not parsed_text:
            raise AgentBackendError("Codex subprocess returned no assistant text")

        return AgentResponse(
            response_text=parsed_text,
            backend_name=self.name,
            session_key=request.session_key,
            correlation_id=request.correlation_id,
            raw_response={
                "command": self._command,
                "returncode": proc.returncode,
                "stderr": stderr_text,
            },
        )

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
            val = event.get(key)
            if isinstance(val, str) and val.strip():
                return val
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
