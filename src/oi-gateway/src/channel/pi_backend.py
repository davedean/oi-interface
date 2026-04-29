"""Pi agent backend implementations."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from typing import Any, AsyncGenerator

from .backend import AgentBackend, AgentBackendError, AgentRequest, AgentResponse, AgentStreamChunk
from .request_builder import render_text_prompt

logger = logging.getLogger(__name__)

class PiBackendError(AgentBackendError):
    """Backward-compatible alias for Pi backend failures."""


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

        prompt_line = json.dumps({"type": "prompt", "message": message}) + "\n"
        proc.stdin.write(prompt_line.encode())
        await proc.stdin.drain()

        terminal_event_types = {"agent_end", "end", "completed", "response_end"}
        last_text: str | None = None
        responded = False
        response_text = ""
        sent_text = ""  # Track what we've already sent

        try:
            while True:
                raw = await asyncio.wait_for(proc.stdout.readline(), timeout=self._timeout_seconds)
                if not raw:
                    if sent_text and sent_text.strip():
                        response_text = sent_text
                    break

                line = raw.decode(errors="replace").strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise PiBackendError(f"malformed JSON from pi stdout: {line}") from exc

                if not isinstance(event, dict):
                    logger.debug("Ignoring non-object pi event: %r", event)
                    continue

                event_type = event.get("type")
                extracted = self._extract_text(event)
                emitted = False
                if extracted and extracted.strip():
                    # Only yield the DELTA (new text), not the full text
                    if extracted.startswith(sent_text):
                        delta = extracted[len(sent_text):]
                    else:
                        # Text doesn't match up, send full new text
                        delta = extracted

                    if delta:
                        sent_text = extracted
                        response_text = extracted
                        is_final = event_type in terminal_event_types
                        emitted = True
                        yield AgentStreamChunk(
                            text_delta=delta,
                            is_final=is_final,
                            metadata={"event_type": event_type} if event_type else {},
                        )

                if event_type in terminal_event_types:
                    event_text = self._extract_text(event)
                    if event_text and event_text.strip() and not responded:
                        responded = True
                        response_text = event_text
                        if event_text.startswith(sent_text):
                            final_delta = event_text[len(sent_text):]
                        else:
                            final_delta = event_text
                        sent_text = event_text
                        yield AgentStreamChunk(
                            text_delta=final_delta,
                            is_final=True,
                            metadata={"event_type": event_type},
                        )
                        break
                    if sent_text.strip() and not responded:
                        responded = True
                        response_text = sent_text
                        yield AgentStreamChunk(
                            text_delta="",
                            is_final=True,
                            metadata={"event_type": event_type},
                        )
                        break
                    continue

                if not emitted:
                    if event_type == "message_update":
                        logger.debug(
                            "No streamable text extracted from message_update assistantMessageEvent=%r",
                            event.get("assistantMessageEvent"),
                        )
                    else:
                        logger.debug("Ignoring non-terminal pi event type=%r", event_type)
        except asyncio.TimeoutError as exc:
            raise PiBackendError(
                f"pi subprocess timed out waiting for response after {self._timeout_seconds:.1f}s"
            ) from exc
        finally:
            with contextlib.suppress(Exception):
                if proc.stdin and not proc.stdin.is_closing():
                    proc.stdin.close()
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(proc.wait(), timeout=5.0)

        # If we never yielded anything but have text, yield it as final
        if response_text and not responded:
            yield AgentStreamChunk(
                text_delta=response_text,
                is_final=True,
                metadata={"event_type": "complete"},
            )

    async def send_prompt(self, message: str) -> str:
        """Backward-compatible helper for tests and legacy callers."""
        response_text = ""
        got_any = False
        async for chunk in self._read_events_from_prompt(message):
            if chunk.text_delta:
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

    def _extract_text(self, event: dict[str, Any]) -> str | None:
        event_type = event.get("type")

        if event_type == "agent_end":
            messages = event.get("messages")
            if isinstance(messages, list):
                for msg in reversed(messages):
                    text = self._extract_message_text(msg)
                    if text:
                        return text
            return None

        if event_type == "message_end":
            text = self._extract_message_text(event.get("message"))
            if text:
                return text
            return None

        assistant_event = event.get("assistantMessageEvent")
        if isinstance(assistant_event, dict):
            assistant_event_type = assistant_event.get("type")
            if assistant_event_type in {"text_delta", "text_end", "text_start"}:
                for key in ("content", "delta", "text"):
                    val = assistant_event.get(key)
                    if isinstance(val, str) and val.strip():
                        return val

                content_value = assistant_event.get("content")
                if isinstance(content_value, dict):
                    text = self._extract_message_text(content_value)
                    if text:
                        return text

                partial = assistant_event.get("partial")
                text = self._extract_message_text(partial)
                if text:
                    return text
            return None

        for key in ("text", "response", "content"):
            val = event.get(key)
            if isinstance(val, str) and val.strip():
                return val
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

    @property
    def last_message(self) -> str | None:
        return self._last_message

    @property
    def last_request(self) -> AgentRequest | None:
        return self._last_request

    @property
    def call_count(self) -> int:
        return self._call_count
    async def send_request_streaming(self, request: AgentRequest) -> AsyncGenerator[AgentStreamChunk, None]:
        """Return a fixed streaming response without spawning a subprocess."""
        from .request_builder import render_text_prompt
        self._last_message = render_text_prompt(request)
        self._call_count += 1
        yield AgentStreamChunk(
            text_delta=self._response,
            is_final=True,
            metadata={"stub": True},
        )

