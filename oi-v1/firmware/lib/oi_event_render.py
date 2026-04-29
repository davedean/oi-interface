# oi_event_render.py — pure functions that turn state dict slices
# into screen-friendly strings for the M5StickS3 idle status bar.
# MicroPython-compatible: no I/O, no side effects, no imports.


def render_agent_status(state):
    """'thinking...' when agent_active else ''."""
    if state.get("agent_active"):
        return "thinking..."
    return ""


def render_tool_status(state):
    """'run: <tool>' when a tool is executing else ''."""
    executions = state.get("tool_executions") or {}
    for tc in executions.values():
        if isinstance(tc, dict) and tc.get("status") == "running":
            return "run: " + str(tc.get("name") or "?")
    return ""


def render_queue_status(state):
    """'q: <n> steer <m> follow' when queue non-empty else ''."""
    steering = state.get("queue_steering") or []
    follow_up = state.get("queue_follow_up") or []
    if not steering and not follow_up:
        return ""
    return "q: %d steer %d follow" % (len(steering), len(follow_up))


def render_compaction_status(state):
    """'compact...' when compacting else ''."""
    if state.get("compaction_active"):
        return "compact..."
    return ""


def render_auto_retry_status(state):
    """'retry N/M' when auto-retrying else ''."""
    if not state.get("auto_retry_active"):
        return ""
    attempt = state.get("auto_retry_attempt", "?")
    max_attempts = state.get("auto_retry_max_attempts", "?")
    return "retry %s/%s" % (attempt, max_attempts)


def render_extension_error(state):
    """'ERR: <msg>' when last_extension_error set else ''."""
    err = state.get("last_extension_error")
    if err and isinstance(err, dict):
        msg = err.get("error") or err.get("extension_path") or "?"
        return "ERR: " + str(msg)
    return ""


def render_idle_status_line(state):
    """Combined single-line status for the idle screen status bar.

    Priority: extension_error > agent > tool > queue > compaction > auto_retry > ''
    """
    text = render_extension_error(state)
    if text:
        return text
    text = render_agent_status(state)
    if text:
        return text
    text = render_tool_status(state)
    if text:
        return text
    text = render_queue_status(state)
    if text:
        return text
    text = render_compaction_status(state)
    if text:
        return text
    text = render_auto_retry_status(state)
    if text:
        return text
    return ""
