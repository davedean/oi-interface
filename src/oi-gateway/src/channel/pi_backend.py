"""Pi agent backend implementations."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, AsyncGenerator

from .backend import AgentBackend, AgentBackendError, AgentRequest, AgentResponse, AgentStreamChunk
from .request_builder import render_text_prompt

logger = logging.getLogger(__name__)


class PiBackendError(AgentBackendError):
    """Backward-compatible alias for Pi backend failures."""


@dataclass
class _StreamState:
    sent_text: str = ""
    response_text: str = ""
    responded: bool = False


class SubprocessPiBackend(AgentBackend):
    """Send requests to pi via subprocess RPC."""

    def __init__(self, pi_command: list[str] | None = None, timeout_seconds: float | None = None) -> None:
        self._pi_command = pi_command or ["pi", "--mode", "rpc", "--no-session"]
        self._timeout_seconds = timeout_seconds if timeout_seconds is not None else self._read_timeout_from_env()

    @property
    def mode(self) -> str:
        return "subprocess"

    @property
    def name(self) -> str:
        return "pi"

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds

    async def send_request(self, request: AgentRequest) -> AgentResponse:
        message = render_text_prompt(request)
        response_text = await self.send_prompt(message)
        return AgentResponse(
            response_text=response_text,
            backend_name=self.name,
            session_key=request.session_key,
            correlation_id=request.correlation_id,
        )

    async def _read_events_from_prompt(self, message: str):
        """Read events from pi subprocess as an async generator yielding AgentStreamChunk."""
        logger.debug(
            "starting pi subprocess prompt",
            extra={
                "backend_mode": self.mode,
                "pi_command": self._pi_command,
                "timeout_seconds": self._timeout_seconds,
                "message_len": len(message),
            },
        )
        proc = await asyncio.create_subprocess_exec(
            *self._pi_command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        await self._write_prompt(proc, message)
        state = _StreamState()

        try:
            while True:
                event = await self._read_event(proc)
                if event is None:
                    if state.sent_text.strip():
                        state.response_text = state.sent_text
                    break

                chunk = self._build_text_chunk(event, state)
                if chunk is not None:
                    yield chunk

                terminal_chunk = self._build_terminal_chunk(event, state)
                if terminal_chunk is not None:
                    yield terminal_chunk
                    break

                if chunk is None:
                    progress_chunk = self._build_progress_chunk(event)
                    if progress_chunk is not None:
                        yield progress_chunk
                    else:
                        self._log_ignored_event(event)
        except asyncio.TimeoutError as exc:
            raise PiBackendError(
                f"pi subprocess timed out waiting for response after {self._timeout_seconds:.1f}s"
            ) from exc
        finally:
            await self._cleanup_process(proc)

        if state.response_text and not state.responded:
            yield AgentStreamChunk(
                text_delta=state.response_text,
                is_final=True,
                metadata={"event_type": "complete"},
            )

    async def send_prompt(self, message: str) -> str:
        """Backward-compatible helper for tests and legacy callers."""
        response_text = ""
        got_any = False
        async for chunk in self._read_events_from_prompt(message):
            if chunk.text_delta:
                if chunk.is_final:
                    response_text = chunk.text_delta
                else:
                    response_text += chunk.text_delta
                got_any = True
            if chunk.is_final and not chunk.text_delta:
                got_any = True
        if not got_any:
            raise PiBackendError("pi closed stdout without usable response text")
        return response_text

    async def send_request_streaming(self, request: AgentRequest) -> AsyncGenerator[AgentStreamChunk, None]:
        """Send a request and yield streaming text chunks."""
        message = render_text_prompt(request)
        async for chunk in self._read_events_from_prompt(message):
            yield chunk

    async def _write_prompt(self, proc: asyncio.subprocess.Process, message: str) -> None:
        prompt_line = json.dumps({"type": "prompt", "message": message}) + "\n"
        assert proc.stdin is not None
        proc.stdin.write(prompt_line.encode())
        await proc.stdin.drain()

    async def _read_event(self, proc: asyncio.subprocess.Process) -> dict[str, Any] | None:
        assert proc.stdout is not None
        raw = await asyncio.wait_for(proc.stdout.readline(), timeout=self._timeout_seconds)
        if not raw:
            return None

        line = raw.decode(errors="replace").strip()
        if not line:
            return {}

        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PiBackendError(f"malformed JSON from pi stdout: {line}") from exc

        if not isinstance(event, dict):
            logger.debug("Ignoring non-object pi event: %r", event)
            return {}
        return event

    def _build_text_chunk(self, event: dict[str, Any], state: _StreamState) -> AgentStreamChunk | None:
        event_type = event.get("type")
        extracted = self._extract_text(event)
        if extracted is None:
            return None

        text, is_incremental = extracted
        delta = self._consume_text(text, is_incremental, state)
        if not delta:
            return None

        return AgentStreamChunk(
            text_delta=delta,
            is_final=event_type in self._terminal_event_types(),
            metadata={"event_type": event_type} if event_type else {},
        )

    def _build_terminal_chunk(self, event: dict[str, Any], state: _StreamState) -> AgentStreamChunk | None:
        event_type = event.get("type")
        if event_type not in self._terminal_event_types():
            return None

        extracted = self._extract_text(event)
        if extracted is not None:
            final_text, _ = extracted
            state.responded = True
            state.response_text = final_text
            final_delta = self._finalize_text(final_text, state)
            return AgentStreamChunk(
                text_delta=final_delta,
                is_final=True,
                metadata={"event_type": event_type},
            )

        if state.sent_text.strip() and not state.responded:
            state.responded = True
            state.response_text = state.sent_text
            return AgentStreamChunk(
                text_delta="",
                is_final=True,
                metadata={"event_type": event_type},
            )
        return None

    def _build_progress_chunk(self, event: dict[str, Any]) -> AgentStreamChunk | None:
        progress_text = self._extract_progress_text(event)
        if not progress_text:
            return None

        event_type = event.get("type")
        metadata = {"progress_text": progress_text}
        if event_type:
            metadata["event_type"] = event_type
        return AgentStreamChunk(text_delta="", is_final=False, metadata=metadata)

    def _log_ignored_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        if event_type == "message_update":
            logger.debug(
                "No streamable text extracted from message_update assistantMessageEvent=%r",
                event.get("assistantMessageEvent"),
            )
            return
        if event_type:
            logger.debug("Ignoring non-terminal pi event type=%r", event_type)

    def _consume_text(self, text: str, is_incremental: bool, state: _StreamState) -> str:
        if is_incremental:
            if text.startswith(state.sent_text):
                delta = text[len(state.sent_text) :]
                state.sent_text = text
            else:
                delta = text
                state.sent_text += delta
            state.response_text = state.sent_text
            return delta

        if text.startswith(state.sent_text):
            delta = text[len(state.sent_text) :]
        else:
            delta = text
        state.sent_text = text
        state.response_text = text
        return delta

    def _finalize_text(self, final_text: str, state: _StreamState) -> str:
        if final_text.startswith(state.sent_text):
            delta = final_text[len(state.sent_text) :]
        else:
            delta = final_text
        state.sent_text = final_text
        return delta

    async def _cleanup_process(self, proc: asyncio.subprocess.Process) -> None:
        with contextlib.suppress(Exception):
            if proc.stdin and not proc.stdin.is_closing():
                proc.stdin.close()
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(proc.wait(), timeout=5.0)

    def _extract_text(self, event: dict[str, Any]) -> tuple[str, bool] | None:
        """Extract text plus whether it's incremental (delta) or snapshot/final."""
        event_type = event.get("type")

        if event_type == "agent_end":
            messages = event.get("messages")
            if isinstance(messages, list):
                for msg in reversed(messages):
                    text = self._extract_message_text(msg)
                    if text:
                        return text, False
            return None

        if event_type == "message_end":
            text = self._extract_message_text(event.get("message"))
            if text:
                return text, False
            return None

        assistant_event = event.get("assistantMessageEvent")
        if isinstance(assistant_event, dict):
            assistant_event_type = assistant_event.get("type")
            if assistant_event_type in {"text_delta", "text_end", "text_start"}:
                for key in ("content", "delta", "text"):
                    value = assistant_event.get(key)
                    if isinstance(value, str) and value.strip():
                        return value, assistant_event_type == "text_delta"

                content_value = assistant_event.get("content")
                if isinstance(content_value, dict):
                    text = self._extract_message_text(content_value)
                    if text:
                        return text, False

                partial = assistant_event.get("partial")
                text = self._extract_message_text(partial)
                if text:
                    return text, False
            return None

        for key in ("text", "response", "content"):
            value = event.get(key)
            if isinstance(value, str) and value.strip():
                return value, False
        return None

    def _extract_progress_text(self, event: dict[str, Any]) -> str | None:
        """Best-effort human-readable progress text from non-terminal events."""
        event_type = event.get("type")
        if event_type in {"agent_start", "turn_start"}:
            return "[thinking] starting"
        if event_type == "turn_end":
            return "[thinking] wrapping up"

        if event_type == "extension_ui_request":
            method = event.get("method")
            message = event.get("message")
            if isinstance(method, str) and method in {"setWidget", "setStatus"}:
                if isinstance(message, str) and "Model Tagger" in message:
                    return f"[extension] {message.strip()}"
                return None
            if isinstance(message, str) and message.strip():
                return f"[extension] {message.strip()}"
            if isinstance(method, str) and method.strip():
                return f"[extension] {method.strip()}"
            return "[extension] update"

        if event_type == "message_update":
            assistant_event = event.get("assistantMessageEvent")
            if isinstance(assistant_event, dict):
                assistant_type = assistant_event.get("type")
                if assistant_type and assistant_type.startswith("toolcall"):
                    name = assistant_event.get("name") or assistant_event.get("toolName")
                    if isinstance(name, str) and name.strip():
                        return f"[tool] {name.strip()}"
                    if assistant_type in {"toolcall_start", "toolcall"}:
                        return "[tool] working"
        return None

    def _extract_message_text(self, message: Any) -> str | None:
        if not isinstance(message, dict):
            return None
        role = message.get("role")
        if role is not None and role != "assistant":
            return None

        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            chunks: list[str] = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                part_type = part.get("type")
                if part_type not in (None, "text"):
                    continue
                text = part.get("text")
                if isinstance(text, str) and text:
                    chunks.append(text)
            if chunks:
                return "".join(chunks)
        return None

    @staticmethod
    def _terminal_event_types() -> set[str]:
        return {"agent_end", "end", "completed", "response_end"}

    @staticmethod
    def _read_timeout_from_env() -> float:
        raw = os.getenv("OI_GATEWAY_PI_TIMEOUT_SECONDS", "60")
        try:
            timeout = float(raw)
        except ValueError:
            logger.warning(
                "invalid OI_GATEWAY_PI_TIMEOUT_SECONDS value; using default",
                extra={"backend_mode": "subprocess", "raw_timeout": raw, "default_timeout": 60.0},
            )
            return 60.0

        if timeout <= 0:
            logger.warning(
                "non-positive OI_GATEWAY_PI_TIMEOUT_SECONDS value; using default",
                extra={"backend_mode": "subprocess", "raw_timeout": raw, "default_timeout": 60.0},
            )
            return 60.0

        return timeout


class StubPiBackend(AgentBackend):
    """Return a fixed response without spawning a subprocess."""

    mode = "stub"

    def __init__(self, response: str = "stub agent response") -> None:
        self._response = response
        self._last_message: str | None = None
        self._last_request: AgentRequest | None = None
        self._call_count = 0

    @property
    def name(self) -> str:
        return "pi"

    async def send_request(self, request: AgentRequest) -> AgentResponse:
        self._last_request = request
        self._last_message = render_text_prompt(request)
        self._call_count += 1
        return AgentResponse(
            response_text=self._response,
            backend_name=self.name,
            session_key=request.session_key,
            correlation_id=request.correlation_id,
        )

    async def send_prompt(self, message: str) -> str:
        """Backward-compatible helper for existing tests."""
        self._last_message = message
        self._call_count += 1
        return self._response

    async def send_request_streaming(self, request: AgentRequest) -> AsyncGenerator[AgentStreamChunk, None]:
        """Return a fixed streaming response without spawning a subprocess."""
        self._last_request = request
        self._last_message = render_text_prompt(request)
        self._call_count += 1
        yield AgentStreamChunk(
            text_delta=self._response,
            is_final=True,
            metadata={"stub": True},
        )

    @property
    def last_message(self) -> str | None:
        return self._last_message

    @property
    def last_request(self) -> AgentRequest | None:
        return self._last_request

    @property
    def call_count(self) -> int:
        return self._call_count
