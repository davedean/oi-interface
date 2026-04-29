# pi_rpc_events.py — pure projections for Pi RPC events.
# MicroPython-compatible: keep dependencies minimal.

import time


_STREAM_KEY = "_assistant_text_stream"


def _ticks_ms():
    if hasattr(time, "ticks_ms"):
        return time.ticks_ms()
    return int(time.time() * 1000)


# ------------------------------------------------------------------
# Helper
# ------------------------------------------------------------------


def _warn_unknown(msg_type):
    """Log unknown event types once."""
    print("[pi_rpc_events] unknown event type:", msg_type)


_unknown_warned = set()


def _project_unknown(state, msg):
    t = msg.get("type", "?")
    if t not in _unknown_warned:
        _warn_unknown(t)
        _unknown_warned.add(t)
    return state


# ------------------------------------------------------------------
# Session / agent lifecycle
# ------------------------------------------------------------------


def project_session_activity(state, msg):
    """Preserve existing heuristic: only agent_start means streaming."""
    sess = state.get("sessions")
    if sess and sess.get("sessions"):
        sess["sessions"][0]["status"] = "streaming" if msg.get("type") == "agent_start" else "idle"
    return state


# ------------------------------------------------------------------
# Message lifecycle
# ------------------------------------------------------------------


def project_message_start(state, msg):
    """Emitted when a new assistant message begins."""
    message = msg.get("message") or {}
    msg_type = message.get("type") or message.get("role")
    msg_id = message.get("id")
    state["current_message_id"] = msg_id
    state["current_message_type"] = msg_type
    state["current_message_text"] = ""
    # Initialise tool_executions dict if not present
    if "tool_executions" not in state:
        state["tool_executions"] = {}
    return state


def project_message_update(state, msg):
    """
    Handle assistant streaming deltas (text, thinking, toolcall).
    Supports sub-field types: text_start, text_delta, text_end,
    thinking_start, thinking_delta, thinking_end,
    toolcall_start, toolcall_delta, toolcall_end.
    """
    event = msg.get("assistantMessageEvent") or {}
    etype = event.get("type")

    if etype == "text_start":
        state[_STREAM_KEY] = ""
        return state

    if etype == "text_delta":
        delta = event.get("delta") or ""
        if delta:
            state[_STREAM_KEY] = state.get(_STREAM_KEY, "") + str(delta)
        return state

    if etype == "text_end":
        text = event.get("content") or state.get(_STREAM_KEY, "")
        if text:
            _set_snapshot_msg(state, text)
            state["last_assistant_text"] = text
        state[_STREAM_KEY] = ""
        return state

    if etype == "thinking_start":
        # Begin accumulating thinking content
        state["_thinking_stream"] = ""
        return state

    if etype == "thinking_delta":
        delta = event.get("delta") or ""
        if delta:
            state["_thinking_stream"] = state.get("_thinking_stream", "") + str(delta)
        return state

    if etype == "thinking_end":
        # Thinking block ended; accumulate in current_message_text for now
        thinking = state.pop("_thinking_stream", "")
        current_text = state.get("current_message_text", "")
        state["current_message_text"] = current_text
        return state

    if etype == "toolcall_start":
        # A new tool call block is starting
        toolcall = event.get("partial") or {}
        tc_id = toolcall.get("id")
        tc_name = toolcall.get("name")
        state["current_tool_execution_id"] = tc_id
        if "tool_executions" not in state:
            state["tool_executions"] = {}
        if tc_id:
            state["tool_executions"][tc_id] = {
                "name": tc_name,
                "input": toolcall.get("arguments") or {},
                "status": "streaming",
                "output": "",
                "error": None,
            }
        return state

    if etype == "toolcall_delta":
        # Arguments chunk for an in-progress tool call
        delta = event.get("delta") or ""
        if delta:
            tc_id = state.get("current_tool_execution_id")
            if tc_id and tc_id in state.get("tool_executions", {}):
                state["tool_executions"][tc_id]["input"] = (
                    state["tool_executions"][tc_id].get("input", "") + str(delta)
                )
        return state

    if etype == "toolcall_end":
        # Tool call fully constructed; full object in 'toolCall'
        toolcall = event.get("toolCall") or event.get("partial") or {}
        tc_id = toolcall.get("id")
        tc_name = toolcall.get("name")
        if tc_id and "tool_executions" in state:
            if tc_id in state["tool_executions"]:
                state["tool_executions"][tc_id]["name"] = tc_name
                state["tool_executions"][tc_id]["status"] = "completed"
        state["current_tool_execution_id"] = None
        return state

    # Unknown sub-event type — tolerate and skip
    return state


def project_message_end(state, msg):
    """Emitted when a message completes."""
    message = msg.get("message") or {}
    if message.get("role") == "assistant":
        final_text = _extract_assistant_text(message)
        # Fallback: if content was a plain string or empty, use streamed text
        if not final_text:
            final_text = state.get(_STREAM_KEY, "").strip() or state.get("current_text", "").strip()
        if final_text:
            _set_snapshot_msg(state, final_text)
            state["last_assistant_text"] = final_text
        state[_STREAM_KEY] = ""
    state["current_message_id"] = None
    state["current_message_type"] = None
    state["current_message_text"] = ""
    return state


# ------------------------------------------------------------------
# Tool execution lifecycle
# ------------------------------------------------------------------


def project_tool_execution_start(state, msg):
    """
    Emitted when a tool call begins execution.
    Fields: toolCallId, toolName, args
    """
    tc_id = msg.get("toolCallId")
    tc_name = msg.get("toolName")
    tc_args = msg.get("args") or {}
    if "tool_executions" not in state:
        state["tool_executions"] = {}
    if tc_id:
        state["tool_executions"][tc_id] = {
            "name": tc_name,
            "input": tc_args,
            "status": "running",
            "output": "",
            "error": None,
        }
    state["current_tool_execution_id"] = tc_id
    return state


def project_tool_execution_update(state, msg):
    """
    Streaming output for a tool call.
    Fields: toolCallId, partialResult (accumulated output so far).
    """
    tc_id = msg.get("toolCallId")
    partial = msg.get("partialResult") or {}
    # Extract text content from partialResult
    content = partial.get("content") or []
    output_parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if text:
                output_parts.append(str(text))
    output_text = "".join(output_parts)
    if tc_id and "tool_executions" in state and tc_id in state["tool_executions"]:
        # partialResult is the accumulated output so far, not a delta
        state["tool_executions"][tc_id]["output"] = output_text
        state["tool_executions"][tc_id]["status"] = "streaming"
    return state


def project_tool_execution_end(state, msg):
    """
    Emitted when a tool call completes.
    Fields: toolCallId, toolName, result (content array), isError.
    """
    tc_id = msg.get("toolCallId")
    tc_name = msg.get("toolName")
    result = msg.get("result") or {}
    is_error = msg.get("isError", False)
    # Extract text from result content
    content = result.get("content") or []
    output_parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if text:
                output_parts.append(str(text))
    output_text = "".join(output_parts)
    if "tool_executions" not in state:
        state["tool_executions"] = {}
    if tc_id:
        state["tool_executions"][tc_id] = {
            "name": tc_name,
            "input": state["tool_executions"].get(tc_id, {}).get("input", {}),
            "status": "error" if is_error else "completed",
            "output": output_text,
            "error": None if not is_error else output_text,
        }
    if state.get("current_tool_execution_id") == tc_id:
        state["current_tool_execution_id"] = None
    return state


# ------------------------------------------------------------------
# Queue
# ------------------------------------------------------------------


def project_queue_update(state, msg):
    """
    Emitted when the pending steering/follow-up queue changes.
    Fields: steering (list), followUp (list).
    """
    steering = msg.get("steering") or []
    follow_up = msg.get("followUp") or []
    state["queue_steering"] = list(steering)
    state["queue_follow_up"] = list(follow_up)
    return state


# ------------------------------------------------------------------
# Compaction
# ------------------------------------------------------------------


def project_compaction_start(state, msg):
    """
    Emitted when auto-compaction begins.
    Fields: reason ("manual", "threshold", "overflow").
    """
    reason = msg.get("reason")
    state["compaction_active"] = True
    state["compaction_reason"] = reason
    return state


def project_compaction_end(state, msg):
    """
    Emitted when compaction completes.
    Fields: aborted, result, errorMessage.
    """
    state["compaction_active"] = False
    # Preserve reason from start event if available
    # result may contain summary, firstKeptEntryId, tokensBefore, details
    result = msg.get("result")
    if result is not None:
        state["last_compaction_result"] = result
    if msg.get("aborted"):
        state["last_compaction_result"] = None
    error_msg = msg.get("errorMessage")
    if error_msg:
        state["last_compaction_error"] = error_msg
    will_retry = msg.get("willRetry")
    if will_retry is not None:
        state["compaction_will_retry"] = will_retry
    return state


# ------------------------------------------------------------------
# Auto-retry
# ------------------------------------------------------------------


def project_auto_retry_start(state, msg):
    """
    Emitted when auto-retry begins after a transient error.
    Fields: attempt, maxAttempts, delayMs, errorMessage.
    """
    attempt = msg.get("attempt", 1)
    max_attempts = msg.get("maxAttempts", 3)
    delay_ms = msg.get("delayMs", 0)
    error_msg = msg.get("errorMessage")
    state["auto_retry_active"] = True
    state["auto_retry_attempt"] = attempt
    state["auto_retry_max_attempts"] = max_attempts
    state["auto_retry_delay_ms"] = delay_ms
    state["auto_retry_error"] = error_msg
    return state


def project_auto_retry_end(state, msg):
    """
    Emitted when auto-retry ends (success or final failure).
    Fields: success, attempt, finalError.
    """
    success = msg.get("success", False)
    attempt = msg.get("attempt")
    final_error = msg.get("finalError")
    state["auto_retry_active"] = False
    state["auto_retry_attempt"] = attempt
    state["auto_retry_result"] = "success" if success else "failed"
    if final_error:
        state["auto_retry_error"] = final_error
    return state


# ------------------------------------------------------------------
# Extension error
# ------------------------------------------------------------------


def project_extension_error(state, msg):
    """
    Emitted when an extension throws an error.
    Fields: extensionPath, event, error.
    """
    state["last_extension_error"] = {
        "extension_path": msg.get("extensionPath"),
        "event": msg.get("event"),
        "error": msg.get("error"),
    }
    return state


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _extract_assistant_text(message):
    """Extract concatenated assistant text blocks from a message payload."""
    blocks = message.get("content") or []
    texts = []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if text:
                texts.append(str(text))
    return " ".join(texts).strip()


def _set_snapshot_msg(state, msg):
    """Store latest assistant text in snapshot for idle-screen preview."""
    text = str(msg).strip()
    if not text:
        return state
    snap = state.get("snapshot") or {}
    snap["msg"] = text
    if "running" not in snap:
        snap["running"] = None
    if "waiting" not in snap:
        snap["waiting"] = None
    if "tokens_today" not in snap:
        snap["tokens_today"] = None
    if "entries" not in snap:
        snap["entries"] = []
    snap["ts"] = _ticks_ms()
    state["snapshot"] = snap
    return state


# ------------------------------------------------------------------
# Registry — all 16 Pi RPC event types
# ------------------------------------------------------------------

EVENT_PROJECTIONS: dict[str, callable] = {
    # Session / agent lifecycle
    "agent_start": project_session_activity,
    "agent_end": project_session_activity,
    "turn_start": project_session_activity,
    "turn_end": project_session_activity,
    # Message lifecycle
    "message_start": project_message_start,
    "message_update": project_message_update,
    "message_end": project_message_end,
    # Tool execution
    "tool_execution_start": project_tool_execution_start,
    "tool_execution_update": project_tool_execution_update,
    "tool_execution_end": project_tool_execution_end,
    # Queue
    "queue_update": project_queue_update,
    # Compaction
    "compaction_start": project_compaction_start,
    "compaction_end": project_compaction_end,
    # Auto-retry
    "auto_retry_start": project_auto_retry_start,
    "auto_retry_end": project_auto_retry_end,
    # Extension
    "extension_error": project_extension_error,
}
