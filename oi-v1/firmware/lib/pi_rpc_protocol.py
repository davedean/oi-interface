# pi_rpc_protocol.py — pure Pi RPC protocol helpers.
# MicroPython-compatible: keep dependencies minimal.

import sys

try:
    import ujson as _json
except ImportError:
    import json as _json


UI_METHOD_HANDLERS: dict[str, callable] = {}


def build_extension_ui_response(ui_id, value=None, confirmed=None, cancelled=False):
    """
    Build an extension_ui_response message.

    Args:
        ui_id: The request id to echo back.
        value: For select/input/editor — the user's input value.
        confirmed: For confirm — True/False.
        cancelled: For any dialog — True if user dismissed.

    Returns dict ready to be serialized and sent as extension_ui_response.
    """
    resp = {
        "type": "extension_ui_response",
        "id": ui_id,
    }
    if cancelled:
        resp["cancelled"] = True
    elif confirmed is not None:
        resp["confirmed"] = confirmed
    else:
        resp["value"] = value if value is not None else ""
    return resp


def map_extension_ui_request(msg):
    """
    Extract fields from an extension_ui_request message.

    Args:
        msg: The parsed extension_ui_request dict.

    Returns dict with id, method, and common optional fields.
    """
    return {
        "id": msg.get("id"),
        "method": msg.get("method"),
        "title": msg.get("title"),
        "message": msg.get("message"),
        "options": msg.get("options"),
        "placeholder": msg.get("placeholder"),
        "prefill": msg.get("prefill"),
        "timeout": msg.get("timeout"),
    }


# --- Dialog handlers (block until response) ---


def handle_select(request: dict) -> dict | None:
    """Handle select dialog: user picks from options list."""
    ui_id = request.get("id")
    opts = request.get("options") or []
    return build_extension_ui_response(ui_id, value=opts[0] if opts else "")


def handle_confirm(request: dict) -> dict | None:
    """Handle confirm dialog: yes/no."""
    ui_id = request.get("id")
    return build_extension_ui_response(ui_id, confirmed=False)


def handle_input(request: dict) -> dict | None:
    """Handle input dialog: free-form text entry."""
    ui_id = request.get("id")
    return build_extension_ui_response(ui_id, value=request.get("placeholder") or "")


def handle_editor(request: dict) -> dict | None:
    """Handle editor dialog: multi-line text."""
    ui_id = request.get("id")
    return build_extension_ui_response(ui_id, value=request.get("prefill") or "")


# --- Fire-and-forget handlers (no response) ---


def _log_fire_and_forget(method, request):
    """Log a fire-and-forget extension UI request to stderr."""
    extras = {}
    for _key in ("id", "message", "statusText", "statusKey",
                 "widgetLines", "widgetKey", "widgetPlacement",
                 "title", "text", "notifyType"):
        if _key in request:
            extras[_key] = request[_key]
    try:
        print(f"[pi_rpc] {method}: {extras}", file=sys.stderr)
    except Exception:
        pass


def handle_notify(request: dict) -> None:
    """Handle notify: show a notification. No response."""
    _log_fire_and_forget("notify", request)


def handle_setStatus(request: dict) -> None:
    """Handle setStatus: set status indicator. No response."""
    _log_fire_and_forget("setStatus", request)


def handle_setWidget(request: dict) -> None:
    """Handle setWidget: set widget state. No response."""
    _log_fire_and_forget("setWidget", request)


def handle_setTitle(request: dict) -> None:
    """Handle setTitle: set window title. No response."""
    _log_fire_and_forget("setTitle", request)


def handle_set_editor_text(request: dict) -> None:
    """Handle set_editor_text: set editor content. No response."""
    _log_fire_and_forget("set_editor_text", request)


# Register all handlers
UI_METHOD_HANDLERS = {
    "select": handle_select,
    "confirm": handle_confirm,
    "input": handle_input,
    "editor": handle_editor,
    "notify": handle_notify,
    "setStatus": handle_setStatus,
    "setWidget": handle_setWidget,
    "setTitle": handle_setTitle,
    "set_editor_text": handle_set_editor_text,
}


def jsonl_encode(obj, dumps=None):
    """Serialise one object as a JSONL line string."""
    if dumps is None:
        dumps = _json.dumps
    return dumps(obj) + "\n"


def parse_jsonl_buffer(buffer, loads=None, log=print):
    """Return (messages, remaining_buffer) from LF-delimited JSON bytes."""
    if loads is None:
        loads = _json.loads
    msgs = []
    buf = buffer.replace(b"\r\n", b"\n")
    while b"\n" in buf:
        idx = buf.index(b"\n")
        line = buf[:idx]
        buf = buf[idx + 1:]
        if line:
            try:
                msgs.append(loads(line))
            except Exception as e:
                log("[pi_rpc] json parse error:", e, "line:", line[:80])
    return msgs, buf


def project_get_state_response(state, msg):
    """Map a successful get_state response into the legacy session shape."""
    data = msg.get("data") or {}
    sid = data.get("sessionId") or data.get("session_id")
    name = data.get("sessionName") or data.get("session_name") or sid
    state["sessions"] = {
        "active_session_id": sid,
        "sessions": [
            {
                "session_id": sid,
                "name": name,
                "status": "streaming" if data.get("isStreaming") else "idle",
                "pending_count": data.get("pendingMessageCount") or 0,
                "stale": False,
                "last_seen_age_s": None,
            }
        ] if sid else [],
    }
    # Surface model and thinking level from get_state so the idle screen can show them.
    model_info = data.get("model")
    if model_info:
        model_id = model_info.get("id") or model_info.get("name") if isinstance(model_info, dict) else str(model_info)
        if model_id:
            state["last_model_change"] = model_id
    thinking = data.get("thinkingLevel")
    if thinking:
        state["last_thinking_change"] = thinking
    # Surface steering/follow-up mode for display.
    steering = data.get("steeringMode")
    if steering:
        state["steering_mode"] = steering
    follow_up = data.get("followUpMode")
    if follow_up:
        state["follow_up_mode"] = follow_up
    return state


def project_extension_ui_request(state, msg):
    """
    Map supported extension_ui_request dialogs into the legacy prompt shape.
    Returns (state, prompt_id, ui_id); prompt_id/ui_id are None if unsupported.
    """
    method = msg.get("method")
    if method not in ("select", "confirm", "input", "editor"):
        return state, None, None

    ui_id = msg.get("id")
    prompt_id = "ext-" + str(msg.get("id", "0"))
    title = msg.get("title") or ""
    message = msg.get("message") or ""
    if method == "confirm":
        opts = [{"label": "Yes", "value": "yes"}, {"label": "No", "value": "no"}]
    elif method == "select":
        raw = msg.get("options") or []
        opts = [{"label": str(o), "value": str(o)} for o in raw]
    elif method in ("input", "editor"):
        opts = [{"label": "OK", "value": "ok"}]
    else:
        opts = []

    state["id"] = prompt_id
    state["title"] = title
    state["body"] = message
    state["options"] = opts
    return state, prompt_id, ui_id