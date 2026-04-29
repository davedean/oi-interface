#!/usr/bin/env python3
"""
oi server — held state for the M5StickS3 desk pager.

Endpoints:
  GET  /oi/state                -> current state JSON (or {"id": null} if idle)
                                   also includes "snapshot" key with dashboard data
  POST /oi/state                -> set new state (admin / agent push)
                                   body: full state JSON; resets answers for new id
  POST /oi/answer               -> record a button press
                                   body: {"id": "...", "value": "..."}
  GET  /oi/answers              -> recent answers (debug)
  POST /oi/ping                 -> user ↦ agent ping (idle BtnA on device)
                                   body: optional {"note": "..."}
  GET  /oi/pings                -> recent pings (for the agent to see at session start)
  POST /oi/snapshot             -> set/clear ambient dashboard snapshot
                                   body: snapshot fields, or {"clear": true} to remove
  GET  /oi/snapshot             -> current snapshot or null (stale after 10 min)
  POST /oi/up                   -> device boot ping; logs "[oi] device boot: version=..."
                                   body: {"version": "abc1234"}
  POST /oi/event                -> device diagnostic event; logs "[oi] device event: <kind> <data>"
                                   body: {"kind": "chirp", "data": "ok"}
  GET  /oi/health               -> {"ok": true}

State JSON shape (what the device renders):
  {
    "id":      "q-2026-04-24-001",          # unique question id; null if idle
    "title":   "Which Adam?",                # short, fits on small screen
    "body":    "you flagged ...",            # optional longer context
    "options": [                              # 0..N options
      {"label": "Wilson", "value": "wilson"},
      {"label": "G",      "value": "g"},
      {"label": "later",  "value": "snooze"}
    ],
    "ts":      "2026-04-24T17:00:00+10:00"   # when it was posted
  }

Snapshot JSON shape (ambient dashboard, merged into GET /oi/state response):
  {
    "running":      1,
    "waiting":      0,
    "msg":          "briefing ready",
    "entries":      ["10:42 git push", "10:41 yarn test"],
    "tokens_today": 31200,
    "ts":           "2026-04-24T23:15:00+10:00"   # set server-side on POST
  }

State is persisted to a JSON file so the server can restart without losing
the pending question. Answers are appended to a JSONL log forever.
Snapshot is persisted to snapshot.json; stale after 10 minutes (TTL).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    from server.oi_sessions import SessionRouter, query_params
except ModuleNotFoundError:  # direct script execution from server/ path
    from oi_sessions import SessionRouter, query_params

# ---------------------------------------------------------------------------
# State store
# ---------------------------------------------------------------------------

DEFAULT_STATE_DIR = Path(os.environ.get("OI_STATE_DIR", "/var/lib/oi"))

SNAPSHOT_TTL_S = 600  # 10 minutes


class BadRequest(Exception):
    """Client sent syntactically valid HTTP with invalid JSON/body shape."""


def _json_default_state() -> dict:
    return {"id": None}


def _json_default_control() -> dict:
    return {"brightness": None, "mute": None, "chirp": None, "chirp_seq": 0}


def _atomic_write_json(path: Path, payload: dict) -> None:
    """Write JSON via same-directory temp file + os.replace()."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def _next_seq_from_jsonl(path: Path) -> int:
    """Return one greater than the largest valid seq in a JSONL file."""
    if not path.exists():
        return 1
    max_seq = 0
    try:
        lines = path.read_text().splitlines()
    except Exception:
        return 1
    for line in lines:
        try:
            seq = json.loads(line).get("seq")
        except Exception:
            continue
        if isinstance(seq, int) and seq > max_seq:
            max_seq = seq
    return max_seq + 1


def _validate_state_payload(payload: dict) -> dict:
    allowed = {"id", "title", "body", "options", "ts"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise BadRequest("unknown state field(s): " + ", ".join(unknown))
    if "id" in payload and payload["id"] is not None and not isinstance(payload["id"], str):
        raise BadRequest("state.id must be a string or null")
    for key in ("title", "body", "ts"):
        if key in payload and payload[key] is not None and not isinstance(payload[key], str):
            raise BadRequest(f"state.{key} must be a string or null")
    if "options" in payload:
        options = payload["options"]
        if not isinstance(options, list):
            raise BadRequest("state.options must be a list")
        for i, opt in enumerate(options):
            if not isinstance(opt, dict):
                raise BadRequest(f"state.options[{i}] must be an object")
            if set(opt) != {"label", "value"}:
                raise BadRequest(f"state.options[{i}] must contain label and value")
            if not isinstance(opt["label"], str) or not isinstance(opt["value"], str):
                raise BadRequest(f"state.options[{i}].label/value must be strings")
    return payload


def _validate_snapshot_payload(payload: dict) -> dict:
    if "clear" in payload and not isinstance(payload["clear"], bool):
        raise BadRequest("snapshot.clear must be boolean")
    if payload.get("clear"):
        unknown = sorted(set(payload) - {"clear"})
        if unknown:
            raise BadRequest("snapshot clear payload must only contain clear")
        return payload
    if "msg" in payload and payload["msg"] is not None and not isinstance(payload["msg"], str):
        raise BadRequest("snapshot.msg must be a string or null")
    for key in ("running", "waiting", "tokens_today"):
        if key in payload and payload[key] is not None and not isinstance(payload[key], int):
            raise BadRequest(f"snapshot.{key} must be an integer or null")
    if "entries" in payload:
        entries = payload["entries"]
        if entries is not None and (not isinstance(entries, list) or not all(isinstance(e, str) for e in entries)):
            raise BadRequest("snapshot.entries must be a list of strings or null")
    return payload


def _validate_control_payload(payload: dict) -> dict:
    allowed = {"brightness", "mute", "chirp"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise BadRequest("unknown control field(s): " + ", ".join(unknown))
    if "brightness" in payload:
        brightness = payload["brightness"]
        if brightness is not None and (not isinstance(brightness, int) or brightness < 0 or brightness > 100):
            raise BadRequest("control.brightness must be an integer 0..100 or null")
    if "mute" in payload and payload["mute"] is not None and not isinstance(payload["mute"], bool):
        raise BadRequest("control.mute must be boolean or null")
    if "chirp" in payload and payload["chirp"] is not None and payload["chirp"] not in ("good", "bad"):
        raise BadRequest("control.chirp must be 'good', 'bad', or null")
    return payload


def _validate_ping_payload(payload: dict) -> dict:
    if "note" in payload and payload["note"] is not None and not isinstance(payload["note"], str):
        raise BadRequest("ping.note must be a string or null")
    return payload


def _validate_answer_payload(payload: dict) -> dict:
    allowed = {"id", "value"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise BadRequest("unknown answer field(s): " + ", ".join(unknown))
    if not isinstance(payload.get("id"), str) or "value" not in payload:
        raise BadRequest("id and value required")
    if not isinstance(payload["value"], str):
        raise BadRequest("answer.value must be a string")
    return payload


def _validate_bulk_cancel_prompts_payload(payload: dict) -> dict:
    allowed = {"session_id"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise BadRequest("unknown prompt-cancel field(s): " + ", ".join(unknown))
    session_id = payload.get("session_id")
    if session_id is not None and not isinstance(session_id, str):
        raise BadRequest("prompt-cancel.session_id must be a string or null")
    return payload


def _validate_bulk_cancel_commands_payload(payload: dict) -> dict:
    allowed = {"session_id", "reason"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise BadRequest("unknown command-cancel field(s): " + ", ".join(unknown))
    session_id = payload.get("session_id")
    if session_id is not None and not isinstance(session_id, str):
        raise BadRequest("command-cancel.session_id must be a string or null")
    reason = payload.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise BadRequest("command-cancel.reason must be a string or null")
    return payload


def _validate_cleanup_session_payload(payload: dict) -> dict:
    allowed = {"session_id", "reason"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise BadRequest("unknown cleanup field(s): " + ", ".join(unknown))
    session_id = payload.get("session_id")
    if session_id is not None and not isinstance(session_id, str):
        raise BadRequest("cleanup.session_id must be a string or null")
    reason = payload.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise BadRequest("cleanup.reason must be a string or null")
    return payload


def _validate_up_payload(payload: dict) -> dict:
    allowed = {"version", "volume", "mute"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise BadRequest("unknown up field(s): " + ", ".join(unknown))
    if "version" in payload and payload["version"] is not None and not isinstance(payload["version"], str):
        raise BadRequest("up.version must be a string or null")
    if "volume" in payload:
        volume = payload["volume"]
        if volume is not None and (isinstance(volume, bool) or not isinstance(volume, int) or volume < 0 or volume > 100):
            raise BadRequest("up.volume must be an integer 0..100 or null")
    if "mute" in payload and payload["mute"] is not None and not isinstance(payload["mute"], bool):
        raise BadRequest("up.mute must be boolean or null")
    return payload


class StateStore:
    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = state_dir / "state.json"
        self.snapshot_path = state_dir / "snapshot.json"
        self.control_path = state_dir / "control.json"
        self.answers_path = state_dir / "answers.jsonl"
        self.pings_path = state_dir / "pings.jsonl"
        self._lock = threading.Lock()
        self.router = SessionRouter(state_dir)
        self._answer_seq = _next_seq_from_jsonl(self.answers_path)
        self._ping_seq = _next_seq_from_jsonl(self.pings_path)
        self._speak_wav: bytes | None = None
        self._speak_seq: int = 0
        self._device_volume: int | None = None
        self._device_mute: bool | None = None

    def get(self) -> dict:
        projected = self.router.projected_prompt_state()
        if projected is not None:
            return projected
        with self._lock:
            if not self.state_path.exists():
                return _json_default_state()
            try:
                return json.loads(self.state_path.read_text())
            except Exception:
                return _json_default_state()

    def set(self, state: dict) -> dict:
        # Normalise / fill defaults
        state = dict(state or {})
        if "id" not in state:
            state["id"] = None
        state.setdefault("title", None)
        state.setdefault("body", None)
        state.setdefault("options", [])
        state.setdefault("ts", datetime.now(timezone.utc).astimezone().isoformat())
        with self._lock:
            _atomic_write_json(self.state_path, state)
        return state

    def clear(self) -> None:
        self.set({"id": None})

    def append_answer(self, answer: dict) -> dict:
        prompt = self.router.get_prompt(answer.get("id"))
        metadata = {}
        if prompt:
            metadata = {
                "prompt_id": prompt.get("prompt_id"),
                "session_id": prompt.get("session_id"),
                "tool_use_id": prompt.get("tool_use_id"),
                "kind": prompt.get("kind"),
            }
        with self._lock:
            record = {
                **answer,
                **metadata,
                "seq": self._answer_seq,
                "ts": datetime.now(timezone.utc).astimezone().isoformat(),
            }
            self._answer_seq += 1
            with self.answers_path.open("a") as f:
                f.write(json.dumps(record) + "\n")
            # If the answer matches the current pending legacy question, clear it.
            cur = self.get_unlocked()
            if cur.get("id") and cur.get("id") == record.get("id"):
                _atomic_write_json(self.state_path, _json_default_state())
        if prompt:
            self.router.answer_prompt(prompt["prompt_id"], answer.get("value"))
        return record

    def get_unlocked(self) -> dict:
        if not self.state_path.exists():
            return _json_default_state()
        try:
            return json.loads(self.state_path.read_text())
        except Exception:
            return _json_default_state()

    def recent_answers(self, n: int = 20) -> list:
        if not self.answers_path.exists():
            return []
        with self._lock:
            lines = self.answers_path.read_text().splitlines()
        out = []
        for line in lines[-n:]:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
        return out

    def append_ping(self, note: str | None = None) -> dict:
        with self._lock:
            record = {
                "seq": self._ping_seq,
                "ts": datetime.now(timezone.utc).astimezone().isoformat(),
            }
            self._ping_seq += 1
            if note:
                record["note"] = note
            with self.pings_path.open("a") as f:
                f.write(json.dumps(record) + "\n")
        return record

    def recent_pings(self, n: int = 20) -> list:
        if not self.pings_path.exists():
            return []
        with self._lock:
            lines = self.pings_path.read_text().splitlines()
        out = []
        for line in lines[-n:]:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
        return out

    def set_snapshot(self, payload: dict) -> dict:
        """Store a snapshot, adding a server-side ts. Returns the stored snapshot."""
        snap = {k: v for k, v in payload.items() if k != "clear"}
        snap["ts"] = datetime.now(timezone.utc).astimezone().isoformat()
        with self._lock:
            _atomic_write_json(self.snapshot_path, snap)
        return snap

    def get_snapshot(self) -> dict | None:
        """Return the snapshot, or None if missing or older than SNAPSHOT_TTL_S."""
        with self._lock:
            if not self.snapshot_path.exists():
                return None
            try:
                snap = json.loads(self.snapshot_path.read_text())
            except Exception:
                return None
        ts_str = snap.get("ts")
        if not ts_str:
            return None
        try:
            ts = datetime.fromisoformat(ts_str)
            age = datetime.now(timezone.utc) - ts.astimezone(timezone.utc)
            if age > timedelta(seconds=SNAPSHOT_TTL_S):
                return None
        except Exception:
            return None
        return snap

    def clear_snapshot(self) -> None:
        """Delete the snapshot file."""
        with self._lock:
            if self.snapshot_path.exists():
                self.snapshot_path.unlink()

    def get_control(self) -> dict:
        """Return current control state, or defaults if absent."""
        with self._lock:
            if not self.control_path.exists():
                return _json_default_control()
            try:
                return json.loads(self.control_path.read_text())
            except Exception:
                return _json_default_control()

    def update_control(self, payload: dict) -> dict:
        """
        Merge payload into control state. Handles chirp as one-shot:
        if 'chirp' is present in payload, increment chirp_seq so the device
        can detect and play it once then ignore future polls with the same seq.
        After device delivery (seq bump), 'chirp' field is preserved in state
        but the device tracks last_chirp_seq to avoid replaying.
        """
        with self._lock:
            if self.control_path.exists():
                try:
                    ctrl = json.loads(self.control_path.read_text())
                except Exception:
                    ctrl = {}
            else:
                ctrl = {}
            ctrl.setdefault("brightness", None)
            ctrl.setdefault("mute", None)
            ctrl.setdefault("chirp", None)
            ctrl.setdefault("chirp_seq", 0)

            if "brightness" in payload:
                ctrl["brightness"] = payload["brightness"]
            if "mute" in payload:
                ctrl["mute"] = payload["mute"]
            if "chirp" in payload and payload["chirp"] is not None:
                ctrl["chirp"] = payload["chirp"]
                ctrl["chirp_seq"] = ctrl.get("chirp_seq", 0) + 1

            _atomic_write_json(self.control_path, ctrl)
            return ctrl

    def set_device_settings(self, volume: int | None, mute: bool | None) -> None:
        with self._lock:
            if volume is not None:
                self._device_volume = int(volume)
            if mute is not None:
                self._device_mute = bool(mute)

    def get_device_settings(self) -> dict:
        with self._lock:
            volume = self._device_volume
            mute = self._device_mute
        if mute is None and volume is None:
            hint = "unknown"
        elif mute is True or volume == 0:
            hint = "possibly_delayed"
        else:
            hint = "normal"
        return {
            "volume": volume,
            "mute": mute,
            "response_pace_hint": hint,
        }

    def set_speak(self, wav_bytes: bytes) -> int:
        """Store a TTS WAV for the device to fetch; return new speak_seq."""
        with self._lock:
            self._speak_wav = wav_bytes
            self._speak_seq += 1
            seq = self._speak_seq
        ctrl = self.get_control()
        ctrl["speak_seq"] = seq
        _atomic_write_json(self.control_path, ctrl)
        return seq

    def get_speak(self) -> bytes | None:
        """Return the latest TTS WAV, or None if none has been queued."""
        with self._lock:
            return self._speak_wav


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "oi/0.1"
    store: StateStore  # set by run()

    def _json(self, code: int, payload) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_raw_body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return b""
        return self.rfile.read(n)

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        raw = self.rfile.read(n)
        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception:
            raise BadRequest("malformed JSON")
        if not isinstance(body, dict):
            raise BadRequest("JSON body must be an object")
        return body

    def _auth_ok(self, path: str) -> bool:
        token = os.environ.get("OI_API_TOKEN")
        if not token:
            return True
        protected = path.startswith(("/oi/sessions", "/oi/prompts", "/oi/commands"))
        if not protected:
            return True
        return self.headers.get("Authorization") == "Bearer " + token

    # --- routes ---

    def do_GET(self):
        if not self._auth_ok(self.path.split("?", 1)[0]):
            self._json(401, {"error": "unauthorized"})
            return
        path = self.path.split("?", 1)[0]
        params = query_params(self.path)
        if path == "/oi/state":
            state = self.store.get()
            snap = self.store.get_snapshot()
            state["snapshot"] = snap
            state["control"] = self.store.get_control()
            state["sessions"] = self.store.router.summary()
            state["device"] = self.store.get_device_settings()
            self._json(200, state)
        elif path == "/oi/snapshot":
            snap = self.store.get_snapshot()
            self._json(200, {"snapshot": snap})
        elif path == "/oi/answers":
            self._json(200, {"answers": self.store.recent_answers()})
        elif path == "/oi/pings":
            self._json(200, {"pings": self.store.recent_pings()})
        elif path == "/oi/sessions":
            self._json(200, self.store.router.list_sessions())
        elif path == "/oi/sessions/active":
            self._json(200, {"session": self.store.router.active_session()})
        elif path == "/oi/sessions/stats":
            self._json(200, self.store.router.stats())
        elif path == "/oi/prompts":
            limit = None
            if params.get("limit") is not None:
                try:
                    limit = int(params.get("limit") or 0)
                except ValueError:
                    self._json(400, {"error": "limit must be an integer"})
                    return
                if limit < 0:
                    self._json(400, {"error": "limit must be >= 0"})
                    return
            self._json(200, {"prompts": self.store.router.list_prompts(
                session_id=params.get("session_id"), status=params.get("status"), limit=limit)})
        elif path == "/oi/commands":
            try:
                after_seq = int(params.get("after_seq") or 0)
            except ValueError:
                self._json(400, {"error": "after_seq must be an integer"})
                return
            limit = None
            if params.get("limit") is not None:
                try:
                    limit = int(params.get("limit") or 0)
                except ValueError:
                    self._json(400, {"error": "limit must be an integer"})
                    return
                if limit < 0:
                    self._json(400, {"error": "limit must be >= 0"})
                    return
            self._json(200, {"commands": self.store.router.list_commands(
                session_id=params.get("session_id"),
                after_seq=after_seq,
                status=params.get("status") or "queued",
                limit=limit)})
        elif path == "/oi/speak":
            wav = self.store.get_speak()
            if wav is None:
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(wav)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(wav)
        elif path in ("/oi/health", "/health", "/"):
            self._json(200, {"ok": True, "service": "oi"})
        else:
            self._json(404, {"error": "not found", "path": path})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        params = query_params(self.path)
        if not self._auth_ok(path):
            self._json(401, {"error": "unauthorized"})
            return
        # /oi/audio receives binary WAV — must be handled before _read_json().
        if path == "/oi/audio":
            try:
                session_id = params.get("session_id")
                wav_bytes = self._read_raw_body()
                if not wav_bytes:
                    raise BadRequest("empty audio body")
                try:
                    try:
                        from server.stt import transcribe, SttUnavailable, clean_transcript
                    except ModuleNotFoundError:
                        from stt import transcribe, SttUnavailable, clean_transcript
                    transcript = transcribe(wav_bytes)
                except SttUnavailable as e:
                    self._json(503, {"error": str(e)})
                    return
                submit = params.get("submit", "1")
                cleaned = clean_transcript(transcript) if transcript else ""
                if session_id and transcript and submit != "0":
                    message = cleaned or transcript
                    self.store.router.create_command({
                        "session_id": session_id,
                        "verb": "prompt",
                        "args": {"message": message, "source": "voice"},
                    })
                result = {"transcript": transcript}
                if submit == "0":
                    result["cleaned"] = cleaned
                self._json(200, result)
            except (BadRequest, ValueError) as e:
                self._json(400, {"error": str(e)})
            return
        try:
            body = self._read_json()
            if path == "/oi/state":
                new_state = self.store.set(_validate_state_payload(body))
                self._json(200, new_state)
            elif path == "/oi/answer":
                rec = self.store.append_answer(_validate_answer_payload(body))
                self._json(200, {"recorded": rec})
            elif path == "/oi/ping":
                body = _validate_ping_payload(body)
                rec = self.store.append_ping(note=body.get("note"))
                self._json(200, {"recorded": rec})
            elif path == "/oi/snapshot":
                body = _validate_snapshot_payload(body)
                if body.get("clear"):
                    self.store.clear_snapshot()
                    self._json(200, {"snapshot": None})
                else:
                    snap = self.store.set_snapshot(body)
                    self._json(200, {"snapshot": snap})
            elif path == "/oi/control":
                ctrl = self.store.update_control(_validate_control_payload(body))
                self._json(200, {"control": ctrl})
            elif path == "/oi/sessions/upsert":
                session = self.store.router.upsert_session(body)
                self._json(200, {"session": session})
            elif path == "/oi/sessions/active":
                session = self.store.router.set_active(body.get("session_id"))
                self._json(200, {"session": session})
            elif path == "/oi/sessions/cleanup":
                body = _validate_cleanup_session_payload(body)
                result = self.store.router.cleanup_session(
                    session_id=body.get("session_id"),
                    reason=body.get("reason"),
                )
                self._json(200, result)
            elif path == "/oi/prompts":
                prompt = self.store.router.create_prompt(body)
                self._json(200, {"prompt": prompt})
            elif path == "/oi/prompts/cancel":
                body = _validate_bulk_cancel_prompts_payload(body)
                cancelled = self.store.router.cancel_pending_prompts(session_id=body.get("session_id"))
                self._json(200, {"cancelled": cancelled})
            elif path.startswith("/oi/prompts/") and path.endswith("/answer"):
                prompt_id = path.split("/")[3]
                value = body.get("value")
                if not isinstance(value, str):
                    raise BadRequest("value required")
                if self.store.router.get_prompt(prompt_id) is None:
                    self._json(404, {"error": "prompt not found"})
                else:
                    rec = self.store.append_answer({"id": prompt_id, "value": value})
                    self._json(200, {"recorded": rec})
            elif path.startswith("/oi/prompts/") and path.endswith("/cancel"):
                prompt_id = path.split("/")[3]
                prompt = self.store.router.cancel_prompt(prompt_id)
                if prompt is None:
                    self._json(404, {"error": "prompt not found"})
                else:
                    self._json(200, {"prompt": prompt})
            elif path == "/oi/commands":
                command = self.store.router.create_command(body)
                self._json(200, {"command": command})
            elif path == "/oi/commands/cancel":
                body = _validate_bulk_cancel_commands_payload(body)
                cancelled = self.store.router.cancel_queued_commands(
                    session_id=body.get("session_id"),
                    reason=body.get("reason"),
                )
                self._json(200, {"cancelled": cancelled})
            elif path.startswith("/oi/commands/") and path.endswith("/ack"):
                command_id = path.split("/")[3]
                command = self.store.router.finish_command(command_id, "acked", body.get("result"))
                if command is None:
                    self._json(404, {"error": "command not found"})
                else:
                    self._json(200, {"command": command})
            elif path.startswith("/oi/commands/") and path.endswith("/fail"):
                command_id = path.split("/")[3]
                command = self.store.router.finish_command(command_id, "failed", body.get("error") or body.get("result"))
                if command is None:
                    self._json(404, {"error": "command not found"})
                else:
                    self._json(200, {"command": command})
            elif path.startswith("/oi/commands/") and path.endswith("/cancel"):
                command_id = path.split("/")[3]
                command = self.store.router.cancel_command(command_id, body.get("reason") or body.get("result"))
                if command is None:
                    self._json(404, {"error": "command not found"})
                else:
                    self._json(200, {"command": command})
            elif path == "/oi/up":
                body = _validate_up_payload(body)
                ver = body.get("version", "?")
                sys.stderr.write("[oi] device boot: version=%s\n" % ver)
                vol = body.get("volume")
                mute = body.get("mute")
                if vol is not None or mute is not None:
                    self.store.set_device_settings(
                        vol if vol is not None else None,
                        mute if mute is not None else None,
                    )
                    sys.stderr.write("[oi] device settings: volume=%s mute=%s\n" % (vol, mute))
                self._json(200, {"ok": True})
            elif path == "/oi/event":
                kind = body.get("kind", "?")
                data = body.get("data", "")
                sys.stderr.write("[oi] device event: %s %s\n" % (kind, data))
                self._json(200, {"ok": True})
            elif path == "/oi/speak":
                text = body.get("text")
                if not text or not isinstance(text, str):
                    raise BadRequest("'text' string required")
                try:
                    try:
                        from server.tts import synthesize, MAX_SPEAK_WAV_BYTES
                    except ModuleNotFoundError:
                        from tts import synthesize  # type: ignore
                        from tts import MAX_SPEAK_WAV_BYTES  # type: ignore
                    wav = synthesize(text)
                except ValueError as e:
                    self._json(413, {"error": "TTS output too large; shorten the text"})
                    return
                except Exception as e:
                    self._json(503, {"error": "tts unavailable: " + str(e)})
                    return
                # Belt-and-suspenders size check (synthesize also enforces this)
                if len(wav) > MAX_SPEAK_WAV_BYTES:
                    self._json(413, {"error": "TTS output too large; shorten the text"})
                    return
                seq = self.store.set_speak(wav)
                self._json(200, {"ok": True, "speak_seq": seq})
            else:
                self._json(404, {"error": "not found", "path": path})
        except (BadRequest, ValueError) as e:
            self._json(400, {"error": str(e)})

    def log_message(self, fmt, *args):
        # Keep the logs short — one line per request.
        sys.stderr.write("[oi] %s - %s\n" % (self.address_string(), fmt % args))


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def run(host: str, port: int, state_dir: Path) -> None:
    Handler.store = StateStore(state_dir)
    httpd = ThreadingHTTPServer((host, port), Handler)
    sys.stderr.write(f"[oi] listening on {host}:{port}, state in {state_dir}\n")
    httpd.serve_forever()


def main() -> None:
    p = argparse.ArgumentParser(description="oi server")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=int(os.environ.get("OI_PORT", "8842")))
    p.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    args = p.parse_args()
    run(args.host, args.port, args.state_dir)


if __name__ == "__main__":
    main()
