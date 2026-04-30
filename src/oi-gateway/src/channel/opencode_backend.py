"""OpenCode agent backend via subprocess CLI invocation."""
from __future__ import annotations

import asyncio
import json
import shlex

from .backend import AgentBackend, AgentBackendError, AgentRequest, AgentResponse
from .request_builder import render_text_prompt


class OpenCodeBackend(AgentBackend):
    """Send requests to OpenCode via `opencode run ...` subprocess."""

    def __init__(self, command: list[str] | None = None, timeout_seconds: float = 120.0) -> None:
        self._command = command or ["opencode", "run", "--format", "json"]
        self._timeout_seconds = timeout_seconds

    @property
    def name(self) -> str:
        return "opencode"

    @property
    def command(self) -> list[str]:
        return self._command

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds

    @classmethod
    def from_command_text(cls, command: str | None, timeout_seconds: float = 120.0) -> "OpenCodeBackend":
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
            raise AgentBackendError(
                f"OpenCode subprocess timed out after {self._timeout_seconds:.1f}s"
            ) from exc

        stdout_text = stdout.decode(errors="replace").strip()
        stderr_text = stderr.decode(errors="replace").strip()
        if proc.returncode != 0:
            detail = stderr_text or stdout_text or f"exit code {proc.returncode}"
            raise AgentBackendError(f"OpenCode subprocess failed: {detail}")
        parsed_text = self._extract_text_from_output(stdout_text)
        if not parsed_text:
            raise AgentBackendError("OpenCode subprocess returned no assistant text")

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
        """Extract assistant text from `opencode run` output.

        Supports both:
        - `--format json` NDJSON event stream (preferred)
        - plain text output fallback
        """
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
