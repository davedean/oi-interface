"""Helpers for constructing backend-neutral agent requests."""
from __future__ import annotations

from .backend import AgentRequest


def build_session_key(device_id: str) -> str:
    """Build the default Oi session key for a device."""
    return f"oi:device:{device_id}"


def build_reply_constraints(device_context: dict[str, object]) -> dict[str, object]:
    """Extract reply-relevant constraints from the source device capabilities."""
    source = device_context.get("source_device")
    capabilities = device_context.get("capabilities", {})
    if not isinstance(capabilities, dict) or not isinstance(source, str):
        return {}
    source_caps = capabilities.get(source, {})
    if not isinstance(source_caps, dict):
        return {}
    return dict(source_caps)


def build_agent_request_from_transcript(
    *,
    device_id: str,
    stream_id: str | None,
    transcript: str,
    device_context: dict[str, object],
    session_key: str | None = None,
    backend_id: str | None = None,
    agent_id: str | None = None,
) -> AgentRequest:
    """Create an AgentRequest from a transcript event."""
    correlation_id = stream_id or f"transcript:{device_id}:{transcript}"
    return AgentRequest(
        user_text=transcript,
        source_device_id=device_id,
        input_kind="transcript",
        stream_id=stream_id,
        transcript=transcript,
        session_key=session_key or build_session_key(device_id),
        backend_id=backend_id,
        agent_id=agent_id,
        correlation_id=correlation_id,
        idempotency_key=correlation_id,
        device_context=device_context,
        reply_constraints=build_reply_constraints(device_context),
    )


def build_agent_request_from_text_prompt(
    *,
    device_id: str,
    text: str,
    device_context: dict[str, object],
    session_key: str | None = None,
    backend_id: str | None = None,
    agent_id: str | None = None,
) -> AgentRequest:
    """Create an AgentRequest from a text.prompt event."""
    correlation_id = f"text:{device_id}:{text}"
    return AgentRequest(
        user_text=text,
        source_device_id=device_id,
        input_kind="text_prompt",
        prompt_text=text,
        session_key=session_key or build_session_key(device_id),
        backend_id=backend_id,
        agent_id=agent_id,
        correlation_id=correlation_id,
        idempotency_key=correlation_id,
        device_context=device_context,
        reply_constraints=build_reply_constraints(device_context),
    )


def render_text_prompt(request: AgentRequest) -> str:
    """Render a natural-language prompt for text-only backends."""
    device_context = request.device_context
    source = device_context.get("source_device", request.source_device_id)
    capabilities = device_context.get("capabilities", {})
    caps = capabilities.get(source, {}) if isinstance(capabilities, dict) else {}
    if not isinstance(caps, dict):
        caps = {}
    cap_pairs = [f"{k}={v}" for k, v in caps.items()]
    cap_str = ", ".join(cap_pairs) if cap_pairs else "no capabilities"

    foreground = device_context.get("foreground")
    fg_note = " (foreground)" if source == foreground else ""

    if request.input_kind == "text_prompt":
        return f"User text: '{request.user_text}'. Device: {source}{fg_note}, {cap_str}."

    return f"The user said: '{request.user_text}'. Device: {source}{fg_note}, {cap_str}."
