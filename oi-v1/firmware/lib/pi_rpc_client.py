# pi_rpc_client.py — MicroPython TCP JSONL client for Pi RPC gateway.
#
# Connects to the gateway via plain TCP, sends JSON commands, and parses
# JSONL responses/events from the socket.
#
# Usage in main.py:
#   client = PiRpcClient("gateway.local", 8843)
#   client.connect()
#   client.send({"type": "get_state"})
#   for msg in client.poll():
#       handle_msg(msg)

try:
    import usocket
except ImportError:
    import socket as usocket

try:
    import ujson
except ImportError:
    import json as ujson

import time

from pi_rpc_commands import COMMAND_BUILDERS
from pi_rpc_events import EVENT_PROJECTIONS
from pi_rpc_protocol import (
    build_extension_ui_response,
    jsonl_encode,
    parse_jsonl_buffer,
    project_extension_ui_request,
    project_get_state_response,
)

# CPython test compatibility: provide MicroPython-style tick helpers.
if not hasattr(time, "ticks_ms"):
    _ticks_epoch = time.monotonic()

    def _ticks_ms():
        return int((time.monotonic() - _ticks_epoch) * 1000)

    def _ticks_add(base, delta):
        return base + delta

    def _ticks_diff(a, b):
        return a - b

    time.ticks_ms = _ticks_ms
    time.ticks_add = _ticks_add
    time.ticks_diff = _ticks_diff


class PiRpcClient:
    """
    Non-blocking JSONL client for Pi RPC over TCP.

    - connect() opens the socket (call after WiFi is up).
    - send(obj) serialises and sends one JSON line.
    - poll() reads available bytes, parses complete JSONL lines, and returns
      a list of parsed dicts.  Call this every loop iteration.
    - connected() returns True if the socket appears open.
    """

    def __init__(self, host, port, timeout_ms=4000):
        self.host = host
        self.port = port
        self.timeout_ms = timeout_ms
        self.sock = None
        self._buffer = b""
        self._reconnect_delay_ms = 1000
        self._max_reconnect_delay_ms = 30000
        self._next_reconnect_at = 0

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self):
        """Open a fresh TCP socket to the gateway."""
        self.close()
        try:
            addr = usocket.getaddrinfo(self.host, self.port, 0, usocket.SOCK_STREAM)[0][-1]
            self.sock = usocket.socket()
            self.sock.settimeout(self.timeout_ms / 1000.0)
            self.sock.connect(addr)
            self._buffer = b""
            self._next_reconnect_at = 0
            return True
        except Exception as e:
            print("[pi_rpc] connect error:", e)
            self.sock = None
            self._schedule_reconnect()
            return False

    def close(self):
        """Close the socket cleanly."""
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        self._buffer = b""

    def connected(self):
        """Best-effort check: socket object exists."""
        return self.sock is not None

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    def send(self, obj):
        """Serialise obj to JSON and send as one line + LF."""
        if self.sock is None:
            return False
        try:
            line = jsonl_encode(obj, ujson.dumps)
            self.sock.send(line.encode("utf-8"))
            return True
        except Exception as e:
            print("[pi_rpc] send error:", e)
            self.close()
            self._schedule_reconnect()
            return False

    # ------------------------------------------------------------------
    # Receive / poll
    # ------------------------------------------------------------------

    def poll(self):
        """
        Read any available data and return a list of parsed JSON objects.
        Returns [] if nothing is ready or on error.
        """
        if self.sock is None:
            now = time.ticks_ms()
            if time.ticks_diff(now, self._next_reconnect_at) >= 0:
                self.connect()
            return []

        try:
            self.sock.setblocking(False)
            chunk = self.sock.recv(2048)
        except OSError as e:
            # EAGAIN / EWOULDBLOCK = no data available (expected)
            if e.args[0] not in (11, 35):  # 11=EAGAIN, 35=EWOULDBLOCK
                print("[pi_rpc] recv error:", e)
                self.close()
                self._schedule_reconnect()
            return []
        except Exception as e:
            print("[pi_rpc] recv error:", e)
            self.close()
            self._schedule_reconnect()
            return []
        finally:
            # Always restore blocking mode after recv attempt
            try:
                self.sock.setblocking(True)
            except Exception:
                pass
        if chunk == b"":
            # Empty recv = server closed the connection
            print("[pi_rpc] server closed connection")
            self.close()
            self._schedule_reconnect()
            return []
        if chunk:
            self._buffer += chunk

        return self._parse_buffer()

    def _parse_buffer(self):
        """Extract complete LF-delimited JSON lines from _buffer."""
        msgs, self._buffer = parse_jsonl_buffer(self._buffer, ujson.loads)
        return msgs

    # ------------------------------------------------------------------
    # Reconnect backoff
    # ------------------------------------------------------------------

    def _schedule_reconnect(self):
        now = time.ticks_ms()
        self._next_reconnect_at = time.ticks_add(now, self._reconnect_delay_ms)
        self._reconnect_delay_ms = min(
            self._reconnect_delay_ms * 2,
            self._max_reconnect_delay_ms,
        )

    def reset_backoff(self):
        """Call after a successful operation to reset reconnect delay."""
        self._reconnect_delay_ms = 1000


# ------------------------------------------------------------------
# Convenience: map Pi RPC events to the legacy state shapes used by
# firmware/main.py so the refactor is smaller.
# ------------------------------------------------------------------

class PiRpcStateMapper:
    """
    Accumulates Pi RPC responses/events and produces a state dict compatible
    with the legacy firmware state model.

    Legacy state keys expected by main.py:
      - id, title, body, options   (prompt / question)
      - sessions -> { active_session_id, sessions[] }
      - snapshot -> { msg, running, waiting, tokens_today, entries[], ts }
      - control -> { chirp_seq, chirp, speak_seq }

    The mapper keeps the last known values and updates them incrementally
    as events arrive.
    """

    def __init__(self):
        self._state = {
            "id": None,
            "title": None,
            "body": None,
            "options": [],
            "sessions": {
                "active_session_id": None,
                "sessions": [],
            },
            "snapshot": None,
            "control": {},
        }
        # Track pending extension_ui_request id -> prompt mapping
        self._ext_prompt_id = None
        self._ext_prompt_ui_id = None
        # Track assistant streaming text so we can surface reply previews.
        self._assistant_text_stream = ""
        self._unknown_event_types = set()

    def _store_command_response(self, msg):
        """Store key data from non-get_state command responses into state."""
        command = msg.get("command", "")
        data = msg.get("data") or {}
        success = msg.get("success", False)

        # Surface model/thinking-level changes so the idle screen can show them.
        if command == "cycle_model" and success and data:
            model = data.get("model") or {}
            name = model.get("id") or model.get("name") or "?"
            self._state["last_model_change"] = name
        elif command == "set_model" and success and data:
            model = data.get("model") or {}
            name = model.get("id") or model.get("name") or "?"
            self._state["last_model_change"] = name
        elif command == "cycle_thinking_level" and success and data:
            level = data.get("level") or data.get("thinkingLevel") or "?"
            self._state["last_thinking_change"] = level
        elif command == "set_thinking_level" and success:
            # set_thinking_level response has no data, but the next get_state poll
            # will update thinkingLevel in state from get_state response data.
            pass

        # Store a generic last_response so the idle screen can flash results.
        self._state["last_response"] = {
            "command": command,
            "success": success,
            "ts": time.ticks_ms(),
        }

    def state(self):
        """Return the current synthesised state dict."""
        return self._state

    def handle_messages(self, msgs):
        """Process a list of parsed RPC messages and update internal state."""
        for msg in msgs:
            self._handle_one(msg)

    def _handle_one(self, msg):
        t = msg.get("type")

        if t == "response":
            if msg.get("command") == "get_state" and msg.get("success"):
                self._state = project_get_state_response(self._state, msg)
            else:
                self._store_command_response(msg)
            return

        if t == "extension_ui_request":
            self._state, prompt_id, ui_id = project_extension_ui_request(self._state, msg)
            if prompt_id is not None:
                self._ext_prompt_id = prompt_id
                self._ext_prompt_ui_id = ui_id
            return

        projection = EVENT_PROJECTIONS.get(t)
        if projection is not None:
            self._state["_assistant_text_stream"] = self._assistant_text_stream
            self._state = projection(self._state, msg)
            self._assistant_text_stream = self._state.pop(
                "_assistant_text_stream",
                self._assistant_text_stream,
            )
            return

        if t not in self._unknown_event_types:
            print("[pi_rpc] unknown event type:", t)
            self._unknown_event_types.add(t)

    def prompt_answer_payload(self, prompt_id, value):
        """
        Build the RPC command to answer a prompt.
        Returns the command dict, or None if we don't know the ext id.
        """
        if self._ext_prompt_id != prompt_id:
            return None
        if self._ext_prompt_ui_id is None:
            return None
        return build_extension_ui_response(self._ext_prompt_ui_id, value)

    def clear_prompt(self):
        """Clear the pending prompt state."""
        self._state["id"] = None
        self._state["title"] = None
        self._state["body"] = None
        self._state["options"] = []
        self._ext_prompt_id = None
        self._ext_prompt_ui_id = None
