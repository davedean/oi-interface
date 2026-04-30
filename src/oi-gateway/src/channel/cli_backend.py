"""Shared subprocess helpers for CLI-backed agent backends."""
from __future__ import annotations

import asyncio
import shlex
from abc import ABC, abstractmethod
from typing import Self

from .backend import AgentBackend, AgentBackendError, AgentRequest, AgentResponse
from .request_builder import render_text_prompt


class CliBackend(AgentBackend, ABC):
    """Base class for subprocess-backed agent backends."""

    backend_name: str
    backend_label: str

    def __init__(self, command: list[str], timeout_seconds: float) -> None:
        self._command = command
        self._timeout_seconds = timeout_seconds

    @property
    def name(self) -> str:
        return self.backend_name

    @property
    def command(self) -> list[str]:
        return self._command

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds

    @classmethod
    def from_command_text(cls, command: str | None, timeout_seconds: float = 120.0) -> Self:
        return cls(command=shlex.split(command) if command else None, timeout_seconds=timeout_seconds)

    async def send_request(self, request: AgentRequest) -> AgentResponse:
        proc = await asyncio.create_subprocess_exec(
            *self._command_args(request),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self._timeout_seconds)
        except asyncio.TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise AgentBackendError(
                f"{self.backend_label} subprocess timed out after {self._timeout_seconds:.1f}s"
            ) from exc

        stdout_text = stdout.decode(errors="replace").strip()
        stderr_text = stderr.decode(errors="replace").strip()
        if proc.returncode != 0:
            detail = stderr_text or stdout_text or f"exit code {proc.returncode}"
            raise AgentBackendError(f"{self.backend_label} subprocess failed: {detail}")

        response_text = self._extract_text_from_output(stdout_text)
        if not response_text:
            raise AgentBackendError(f"{self.backend_label} subprocess returned no assistant text")

        return AgentResponse(
            response_text=response_text,
            backend_name=self.name,
            session_key=request.session_key,
            correlation_id=request.correlation_id,
            raw_response={
                "command": self._command,
                "returncode": proc.returncode,
                "stderr": stderr_text,
            },
        )

    def _command_args(self, request: AgentRequest) -> list[str]:
        return [*self._command, render_text_prompt(request)]

    @abstractmethod
    def _extract_text_from_output(self, output: str) -> str:
        """Extract assistant text from backend stdout."""
