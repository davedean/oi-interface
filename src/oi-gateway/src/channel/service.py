"""Channel service: assemble channel messages and send to an agent backend."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from .backend import AgentBackend, AgentBackendError, AgentRequest, AgentResponse, AgentStreamChunk
from .request_builder import (
    build_agent_request_from_text_prompt,
    build_agent_request_from_transcript,
    render_text_prompt,
)

if TYPE_CHECKING:
    from datp import EventBus
    from registry import RegistryService
from datp.commands import CommandDispatcher

logger = logging.getLogger(__name__)


class ChannelService:
    """Bridge transcripts/text prompts to a configured agent backend."""

    def __init__(
        self,
        event_bus: EventBus,
        registry: RegistryService,
        pi_backend: AgentBackend,
        command_dispatcher: CommandDispatcher | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._registry = registry
        self._pi_backend = pi_backend
        self._command_dispatcher = command_dispatcher
        event_bus.subscribe(self._on_event)
        logger.info("ChannelService started", extra={"backend_mode": self._backend_mode})

    def start(self) -> None:
        """No-op for backward compatibility."""

    def stop(self) -> None:
        """No-op for backward compatibility."""

    def _on_event(self, event_type: str, device_id: str, payload: dict[str, Any]) -> None:
        if event_type == "event" and payload.get("event") == "text.prompt":
            self._schedule_handler(
                self._handle_text_prompt,
                device_id,
                payload,
                "Event loop not running; cannot schedule text prompt handling",
            )
            return

        if event_type != "transcript":
            return

        self._schedule_handler(
            self._handle_transcript,
            device_id,
            payload,
            "Event loop not running; cannot schedule channel handling",
        )

    async def _handle_transcript(self, device_id: str, payload: dict[str, Any]) -> None:
        stream_id = payload.get("stream_id")
        cleaned = payload.get("cleaned", "").strip()
        log_context = {
            "device_id": device_id,
            "stream_id": stream_id,
            "backend_mode": self._backend_mode,
            "event_kind": "transcript",
        }
        if not cleaned:
            logger.warning("Skipping empty transcript", extra=log_context)
            return

        device_context = self._build_device_context(device_id)
        request = build_agent_request_from_transcript(
            device_id=device_id,
            stream_id=stream_id,
            transcript=cleaned,
            device_context=device_context,
        )

        started = time.perf_counter()
        try:
            response = await self._send_backend_request(request)
        except AgentBackendError as exc:
            logger.exception(
                "agent backend failed while processing transcript",
                extra={
                    **log_context,
                    "error_class": type(exc).__name__,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            return

        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        self._event_bus.emit(
            "agent_response",
            device_id,
            {
                "stream_id": request.stream_id,
                "transcript": request.transcript,
                "response_text": response.response_text,
                "device_context": request.device_context,
                "reply_constraints": request.reply_constraints,
                "backend_name": response.backend_name,
                "session_key": response.session_key,
                "correlation_id": response.correlation_id,
                "streaming_used": response.streaming_used,
            },
        )
        logger.info("Channel message processed", extra={**log_context, "elapsed_ms": elapsed_ms})

    async def _handle_text_prompt(self, device_id: str, payload: dict[str, Any]) -> None:
        text = payload.get("text", "").strip()
        log_context = {
            "device_id": device_id,
            "stream_id": None,
            "backend_mode": self._backend_mode,
            "event_kind": "text.prompt",
            "text_len": len(text),
        }
        if not text:
            logger.warning("Skipping empty text prompt", extra=log_context)
            return

        device_context = self._build_device_context(device_id)
        request = build_agent_request_from_text_prompt(
            device_id=device_id,
            text=text,
            device_context=device_context,
        )

        started = time.perf_counter()
        try:
            response = await self._send_backend_request(request)
        except AgentBackendError as exc:
            logger.exception(
                "agent backend failed for text prompt",
                extra={
                    **log_context,
                    "error": str(exc),
                    "error_class": type(exc).__name__,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            if self._command_dispatcher is not None:
                await self._command_dispatcher.show_card(
                    device_id,
                    title="Agent Error",
                    body="Sorry, I couldn't get a response from the agent. Please try again.",
                    options=[],
                )
            return

        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        self._event_bus.emit(
            "agent_response",
            device_id,
            {
                "prompt_text": request.prompt_text,
                "response_text": response.response_text,
                "device_context": request.device_context,
                "reply_constraints": request.reply_constraints,
                "backend_name": response.backend_name,
                "session_key": response.session_key,
                "correlation_id": response.correlation_id,
                "streaming_used": response.streaming_used,
            },
        )

        if self._command_dispatcher is not None and not response.streaming_used:
            logger.info("Non-streaming path: showing card for device %s", device_id)
            await self._command_dispatcher.show_card(
                device_id,
                title="Response",
                body=response.response_text,
                options=[],
            )

        logger.info("Text prompt processed: device=%s streaming=%s response_len=%d", device_id, response.streaming_used, len(response.response_text))

    async def _handle_streaming_request(self, request: AgentRequest, streaming_method) -> AgentResponse:
        """Handle a streaming request, emitting delta events and returning final response."""
        last_text = ""
        chunk_count = 0
        logger.info("Starting streaming request for device %s", request.source_device_id)
        last_progress_text = None
        async for chunk in streaming_method(request):
            chunk_count += 1
            if not isinstance(chunk, AgentStreamChunk):
                continue

            progress_text = chunk.metadata.get("progress_text") if chunk.metadata else None
            if progress_text and progress_text != last_progress_text:
                last_progress_text = progress_text
                self._emit_stream_progress(request, progress_text)

            if chunk.text_delta or chunk.is_final:
                last_text = self._accumulate_stream_text(last_text, chunk)
                logger.debug(
                    "Emitting delta: device=%s seq=%d final=%s text=%r",
                    request.source_device_id,
                    chunk_count,
                    chunk.is_final,
                    chunk.text_delta[:50] if chunk.text_delta else "",
                )
                self._emit_stream_delta(request, chunk)

        logger.info(
            "Streaming request completed: device=%s chunks=%d final_len=%d",
            request.source_device_id,
            chunk_count,
            len(last_text),
        )

        session_key_mapper = getattr(self._pi_backend, "map_session_key", None)
        session_key = request.session_key
        if callable(session_key_mapper):
            session_key = session_key_mapper(request)

        return AgentResponse(
            response_text=last_text,
            backend_name=self._backend_name,
            session_key=session_key,
            correlation_id=request.correlation_id,
            streaming_used=True,
        )

    def _accumulate_stream_text(self, current_text: str, chunk: AgentStreamChunk) -> str:
        if not chunk.text_delta:
            return current_text
        if chunk.is_final:
            return chunk.text_delta
        return current_text + chunk.text_delta

    def _schedule_handler(self, handler, device_id: str, payload: dict[str, Any], warning_message: str) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning(warning_message)
            return

        loop.create_task(handler(device_id, payload))

    def _stream_payload_base(self, request: AgentRequest) -> dict[str, Any]:
        return {
            "stream_id": request.stream_id,
            "device_context": request.device_context,
            "reply_constraints": request.reply_constraints,
            "backend_name": self._backend_name,
            "session_key": request.session_key,
            "correlation_id": request.correlation_id,
        }

    def _emit_stream_progress(self, request: AgentRequest, progress_text: str) -> None:
        self._event_bus.emit(
            "agent_progress",
            request.source_device_id,
            {
                **self._stream_payload_base(request),
                "text": progress_text,
                "kind": "status",
            },
        )

    def _emit_stream_delta(self, request: AgentRequest, chunk: AgentStreamChunk) -> None:
        self._event_bus.emit(
            "agent_response_stream",
            request.source_device_id,
            {
                **self._stream_payload_base(request),
                "text_delta": chunk.text_delta,
                "is_final": chunk.is_final,
            },
        )

    async def _send_backend_request(self, request: AgentRequest) -> AgentResponse:
        """Send request to backend, using streaming if available."""
        streaming_method = getattr(self._pi_backend, "send_request_streaming", None)
        if callable(streaming_method):
            logger.info("Using STREAMING path for device %s", request.source_device_id)
            return await self._handle_streaming_request(request, streaming_method)

        logger.info("Using NON-STREAMING path for device %s", request.source_device_id)
        send_request = getattr(self._pi_backend, "send_request", None)
        if callable(send_request):
            return await send_request(request)

        send_prompt = getattr(self._pi_backend, "send_prompt", None)
        if callable(send_prompt):
            try:
                response_text = await send_prompt(render_text_prompt(request))
            except AgentBackendError:
                raise
            except Exception as exc:  # pragma: no cover - defensive wrapper
                raise AgentBackendError(str(exc)) from exc

            backend_name = getattr(self._pi_backend, "name", "legacy")
            if callable(backend_name):
                backend_name = backend_name()

            return AgentResponse(
                response_text=response_text,
                backend_name=str(backend_name),
                session_key=request.session_key,
                correlation_id=request.correlation_id,
            )

        raise AgentBackendError("backend does not implement send_request or send_prompt")

    def _build_device_context(self, source_device_id: str) -> dict[str, Any]:
        online_devices = self._registry.get_online_devices()
        foreground_device = self._registry.get_foreground_device()

        capabilities: dict[str, dict[str, Any]] = {}
        for device in online_devices:
            caps = self._registry.get_capabilities(device.device_id)
            capabilities[device.device_id] = caps or {}

        return {
            "source_device": source_device_id,
            "foreground": foreground_device.device_id if foreground_device else None,
            "online": [d.device_id for d in online_devices],
            "capabilities": capabilities,
        }

    @property
    def _backend_name(self) -> str:
        backend_name = getattr(self._pi_backend, "name", "unknown")
        if callable(backend_name):
            backend_name = backend_name()
        return str(backend_name)

    @property
    def _backend_mode(self) -> str:
        return getattr(self._pi_backend, "mode", getattr(self._pi_backend, "name", type(self._pi_backend).__name__))
