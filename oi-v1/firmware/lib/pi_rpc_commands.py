# pi_rpc_commands.py — pure Pi RPC command builders.
# MicroPython-compatible: keep dependencies minimal.


def _with_optional_id(payload, request_id):
    if request_id is not None:
        payload["id"] = request_id
    return payload


def build_get_state(key, **kwargs):
    return _with_optional_id({"type": key}, kwargs.get("id"))


def build_get_messages(key, **kwargs):
    return _with_optional_id({"type": key}, kwargs.get("id"))


def build_get_available_models(key, **kwargs):
    return _with_optional_id({"type": key}, kwargs.get("id"))


def build_get_session_stats(key, **kwargs):
    return _with_optional_id({"type": key}, kwargs.get("id"))


def build_get_fork_messages(key, **kwargs):
    return _with_optional_id({"type": key}, kwargs.get("id"))


def build_get_last_assistant_text(key, **kwargs):
    return _with_optional_id({"type": key}, kwargs.get("id"))


def build_get_commands(key, **kwargs):
    return _with_optional_id({"type": key}, kwargs.get("id"))


def _build_message_command(key, **kwargs):
    payload = {"type": key}
    msg = kwargs.get("message")
    if msg:
        payload["message"] = msg
    # images field: list of {"type":"image","data":base64,"mimeType":mime}
    images = kwargs.get("images")
    if images:
        payload["images"] = images
    # streamingBehavior: "steer" | "followUp" — only for prompt
    sb = kwargs.get("streamingBehavior")
    if sb and key == "prompt":
        payload["streamingBehavior"] = sb
    return _with_optional_id(payload, kwargs.get("id"))


def build_prompt(key, **kwargs):
    return _build_message_command(key, **kwargs)


def build_steer(key, **kwargs):
    return _build_message_command(key, **kwargs)


def build_follow_up(key, **kwargs):
    return _build_message_command(key, **kwargs)


def build_abort(key, **kwargs):
    return _with_optional_id({"type": key}, kwargs.get("id"))


# =============================================================================
# Step 3c — Lifecycle/interactive (continued)
# =============================================================================

def build_new_session(key, **kwargs):
    """
    Start a fresh session.
    Wire: {"type":"new_session"} or {"type":"new_session","parentSession":"/path"}
    """
    payload = {"type": key}
    parent = kwargs.get("parentSession")
    if parent:
        payload["parentSession"] = parent
    return _with_optional_id(payload, kwargs.get("id"))


def build_switch_session(key, **kwargs):
    """
    Load a different session.
    Wire: {"type":"switch_session","sessionPath":"/path/to/session.jsonl"}
    """
    payload = {"type": key}
    path = kwargs.get("sessionPath")
    if path:
        payload["sessionPath"] = path
    return _with_optional_id(payload, kwargs.get("id"))


def build_abort_retry(key, **kwargs):
    """
    Abort an in-progress retry.
    Wire: {"type":"abort_retry"}
    """
    return _with_optional_id({"type": key}, kwargs.get("id"))


def build_abort_bash(key, **kwargs):
    """
    Abort a running bash command.
    Wire: {"type":"abort_bash"}
    """
    return _with_optional_id({"type": key}, kwargs.get("id"))


# =============================================================================
# Step 3b — Mode/setting commands (9)
# =============================================================================

def build_set_model(key, **kwargs):
    """
    Switch to a specific model.
    Wire format: {"type": "set_model", "provider": "...", "modelId": "..."}
    """
    payload = {"type": key}
    if "provider" in kwargs and kwargs["provider"] is not None:
        payload["provider"] = kwargs["provider"]
    if "modelId" in kwargs and kwargs["modelId"] is not None:
        payload["modelId"] = kwargs["modelId"]
    return _with_optional_id(payload, kwargs.get("id"))


def build_cycle_model(key, **kwargs):
    """
    Cycle to the next available model.
    Wire format: {"type": "cycle_model"}
    """
    return _with_optional_id({"type": key}, kwargs.get("id"))


def build_set_thinking_level(key, **kwargs):
    """
    Set the reasoning/thinking level for models that support it.
    Wire format: {"type": "set_thinking_level", "level": "off|minimal|low|medium|high|xhigh"}
    """
    payload = {"type": key}
    if "level" in kwargs and kwargs["level"] is not None:
        payload["level"] = kwargs["level"]
    return _with_optional_id(payload, kwargs.get("id"))


def build_cycle_thinking_level(key, **kwargs):
    """
    Cycle through available thinking levels.
    Wire format: {"type": "cycle_thinking_level"}
    """
    return _with_optional_id({"type": key}, kwargs.get("id"))


def build_set_steering_mode(key, **kwargs):
    """
    Control how steering messages are delivered.
    Wire format: {"type": "set_steering_mode", "mode": "all|one-at-a-time"}
    """
    payload = {"type": key}
    if "mode" in kwargs and kwargs["mode"] is not None:
        payload["mode"] = kwargs["mode"]
    return _with_optional_id(payload, kwargs.get("id"))


def build_set_follow_up_mode(key, **kwargs):
    """
    Control how follow-up messages are delivered.
    Wire format: {"type": "set_follow_up_mode", "mode": "all|one-at-a-time"}
    """
    payload = {"type": key}
    if "mode" in kwargs and kwargs["mode"] is not None:
        payload["mode"] = kwargs["mode"]
    return _with_optional_id(payload, kwargs.get("id"))


def build_set_auto_compaction(key, **kwargs):
    """
    Enable or disable automatic compaction when context is nearly full.
    Wire format: {"type": "set_auto_compaction", "enabled": true|false}
    """
    payload = {"type": key}
    if "enabled" in kwargs and kwargs["enabled"] is not None:
        payload["enabled"] = kwargs["enabled"]
    return _with_optional_id(payload, kwargs.get("id"))


def build_set_auto_retry(key, **kwargs):
    """
    Enable or disable automatic retry on transient errors.
    Wire format: {"type": "set_auto_retry", "enabled": true|false}
    """
    payload = {"type": key}
    if "enabled" in kwargs and kwargs["enabled"] is not None:
        payload["enabled"] = kwargs["enabled"]
    return _with_optional_id(payload, kwargs.get("id"))


def build_set_session_name(key, **kwargs):
    """
    Set a display name for the current session.
    Wire format: {"type": "set_session_name", "name": "..."}
    """
    payload = {"type": key}
    if "name" in kwargs and kwargs["name"] is not None:
        payload["name"] = kwargs["name"]
    return _with_optional_id(payload, kwargs.get("id"))


# =============================================================================
# Step 3d — Heavy/destructive commands (5)
# =============================================================================

def build_bash(key, **kwargs):
    """
    Execute a shell command.
    Wire: {"type":"bash","command":"ls -la"} with optional
    workingDirectory, environment.
    """
    payload = {"type": key, "command": kwargs.get("command", "")}
    wd = kwargs.get("workingDirectory")
    if wd:
        payload["workingDirectory"] = wd
    env = kwargs.get("environment")
    if env:
        payload["environment"] = env
    return _with_optional_id(payload, kwargs.get("id"))


def build_compact(key, **kwargs):
    """
    Manually compact conversation context.
    Wire: {"type":"compact"} or {"type":"compact","customInstructions":"..."}
    """
    payload = {"type": key}
    ci = kwargs.get("customInstructions")
    if ci:
        payload["customInstructions"] = ci
    return _with_optional_id(payload, kwargs.get("id"))


def build_fork(key, **kwargs):
    """
    Create a fork from a previous user message.
    Wire: {"type":"fork"} or {"type":"fork","entryId":"abc123"}
    """
    payload = {"type": key}
    entry = kwargs.get("entryId")
    if entry:
        payload["entryId"] = entry
    return _with_optional_id(payload, kwargs.get("id"))


def build_clone(key, **kwargs):
    """
    Duplicate the current session branch.
    Wire: {"type":"clone"}
    """
    return _with_optional_id({"type": key}, kwargs.get("id"))


def build_export_html(key, **kwargs):
    """
    Export session to HTML.
    Wire: {"type":"export_html"} or {"type":"export_html","outputPath":"/tmp/s.html"}
    """
    payload = {"type": key}
    path = kwargs.get("outputPath")
    if path:
        payload["outputPath"] = path
    return _with_optional_id(payload, kwargs.get("id"))


# =============================================================================
# Command registry
# =============================================================================

def build_command(command, **kwargs):
    """Build a command payload. Unknown commands raise KeyError."""
    return COMMAND_BUILDERS[command](command, **kwargs)


COMMAND_BUILDERS: dict[str, callable] = {
    # Step 3a — Read-only (7)
    "get_state": build_get_state,
    "get_messages": build_get_messages,
    "get_available_models": build_get_available_models,
    "get_session_stats": build_get_session_stats,
    "get_fork_messages": build_get_fork_messages,
    "get_last_assistant_text": build_get_last_assistant_text,
    "get_commands": build_get_commands,
    # Step 3b — Mode/setting (9)
    "set_model": build_set_model,
    "cycle_model": build_cycle_model,
    "set_thinking_level": build_set_thinking_level,
    "cycle_thinking_level": build_cycle_thinking_level,
    "set_steering_mode": build_set_steering_mode,
    "set_follow_up_mode": build_set_follow_up_mode,
    "set_auto_compaction": build_set_auto_compaction,
    "set_auto_retry": build_set_auto_retry,
    "set_session_name": build_set_session_name,
    # Step 3c — Lifecycle/interactive (8)
    "prompt": build_prompt,
    "steer": build_steer,
    "follow_up": build_follow_up,
    "abort": build_abort,
    "new_session": build_new_session,
    "switch_session": build_switch_session,
    "abort_retry": build_abort_retry,
    "abort_bash": build_abort_bash,
    # Step 3d — Heavy/destructive (5)
    "bash": build_bash,
    "compact": build_compact,
    "fork": build_fork,
    "clone": build_clone,
    "export_html": build_export_html,
}
