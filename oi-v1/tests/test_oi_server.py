import io
import json
import os
import tempfile
import unittest
import wave
from unittest import mock
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from server.oi_server import Handler, StateStore


class OiServerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # Handler.store is a class attribute; tests run serially under unittest.
        Handler.store = StateStore(Path(self.tmp.name))
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self.httpd.server_port}"
        self.thread = Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        self.tmp.cleanup()

    def get_json(self, path):
        with urllib.request.urlopen(self.base_url + path, timeout=2) as response:
            self.assertEqual(response.status, 200)
            return json.loads(response.read().decode("utf-8"))

    def post_json(self, path, payload, expected_status=200):
        return self.post_raw(path, json.dumps(payload).encode("utf-8"), expected_status)

    def post_raw(self, path, data, expected_status=200):
        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        if expected_status >= 400:
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(req, timeout=2)
            self.assertEqual(cm.exception.code, expected_status)
            return json.loads(cm.exception.read().decode("utf-8"))
        with urllib.request.urlopen(req, timeout=2) as response:
            self.assertEqual(response.status, expected_status)
            return json.loads(response.read().decode("utf-8"))

    def test_health_and_default_state(self):
        self.assertEqual(self.get_json("/oi/health"), {"ok": True, "service": "oi"})
        self.assertEqual(
            self.get_json("/oi/state"),
            {
                "id": None,
                "snapshot": None,
                "control": {"brightness": None, "mute": None, "chirp": None, "chirp_seq": 0},
                "sessions": {"active_session_id": None, "sessions": []},
                "device": {"volume": None, "mute": None, "response_pace_hint": "unknown"},
            },
        )

    def test_question_answer_flow_clears_matching_state(self):
        state = self.post_json(
            "/oi/state",
            {"id": "q1", "title": "Pick", "options": [{"label": "yes", "value": "yes"}]},
        )
        self.assertEqual(state["id"], "q1")
        self.assertEqual(state["body"], None)
        self.assertIn("ts", state)

        answer = self.post_json("/oi/answer", {"id": "q1", "value": "yes"})["recorded"]
        self.assertEqual(answer["id"], "q1")
        self.assertEqual(answer["value"], "yes")
        self.assertEqual(answer["seq"], 1)
        self.assertEqual(self.get_json("/oi/state")["id"], None)
        self.assertEqual(self.get_json("/oi/answers")["answers"][-1]["value"], "yes")

    def test_answer_requires_id_and_value(self):
        error = self.post_json("/oi/answer", {"id": "q1"}, expected_status=400)
        self.assertEqual(error, {"error": "id and value required"})
        error = self.post_json("/oi/answer", {"id": "q1", "value": "yes", "seq": 999}, expected_status=400)
        self.assertIn("unknown answer field", error["error"])

    def test_post_routes_reject_malformed_and_non_object_json(self):
        for path in ("/oi/state", "/oi/snapshot", "/oi/control", "/oi/ping", "/oi/answer", "/oi/up"):
            with self.subTest(path=path, kind="malformed"):
                error = self.post_raw(path, b"{bad", expected_status=400)
                self.assertEqual(error, {"error": "malformed JSON"})
            with self.subTest(path=path, kind="array"):
                error = self.post_raw(path, b"[]", expected_status=400)
                self.assertEqual(error, {"error": "JSON body must be an object"})

    def test_state_snapshot_and_control_validation(self):
        self.assertIn("state.options", self.post_json(
            "/oi/state", {"id": "q", "options": "yes"}, expected_status=400
        )["error"])
        self.assertIn("snapshot.entries", self.post_json(
            "/oi/snapshot", {"entries": ["ok", 3]}, expected_status=400
        )["error"])
        self.assertIn("control.brightness", self.post_json(
            "/oi/control", {"brightness": 101}, expected_status=400
        )["error"])
        self.post_json("/oi/sessions/upsert", {"session_id": "s1"})
        self.assertIn("options[0]", self.post_json(
            "/oi/prompts", {"session_id": "s1", "options": ["yes"]}, expected_status=400
        )["error"])
        self.assertIn("unsupported command", self.post_json(
            "/oi/commands", {"session_id": "s1", "verb": "shell"}, expected_status=400
        )["error"])
        self.assertIn("expires_at", self.post_json(
            "/oi/commands", {"session_id": "s1", "verb": "status", "expires_at": 123}, expected_status=400
        )["error"])
        self.assertIn("request_id", self.post_json(
            "/oi/commands", {"session_id": "s1", "verb": "status", "request_id": 7}, expected_status=400
        )["error"])
        self.assertIn("prompt-cancel.session_id", self.post_json(
            "/oi/prompts/cancel", {"session_id": 7}, expected_status=400
        )["error"])
        self.assertIn("command-cancel.reason", self.post_json(
            "/oi/commands/cancel", {"reason": 7}, expected_status=400
        )["error"])
        self.assertIn("cleanup.session_id", self.post_json(
            "/oi/sessions/cleanup", {"session_id": 7}, expected_status=400
        )["error"])
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(self.base_url + "/oi/commands?after_seq=abc", timeout=2)
        self.assertEqual(cm.exception.code, 400)
        self.assertEqual(json.loads(cm.exception.read().decode("utf-8")), {"error": "after_seq must be an integer"})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(self.base_url + "/oi/prompts?limit=abc", timeout=2)
        self.assertEqual(cm.exception.code, 400)
        self.assertEqual(json.loads(cm.exception.read().decode("utf-8")), {"error": "limit must be an integer"})

    def test_snapshot_ttl_and_clear(self):
        stored = self.post_json("/oi/snapshot", {"msg": "ready", "running": 1})["snapshot"]
        self.assertEqual(stored["msg"], "ready")
        self.assertEqual(self.get_json("/oi/state")["snapshot"]["msg"], "ready")
        self.assertEqual(self.post_json("/oi/snapshot", {"clear": True}), {"snapshot": None})
        self.assertIsNone(self.get_json("/oi/snapshot")["snapshot"])

    def test_control_chirp_sequence_increments(self):
        first = self.post_json("/oi/control", {"chirp": "good"})["control"]
        second = self.post_json("/oi/control", {"chirp": "bad", "mute": True, "brightness": 42})["control"]
        self.assertEqual(first["chirp_seq"], 1)
        self.assertEqual(second["chirp_seq"], 2)
        self.assertEqual(second["chirp"], "bad")
        self.assertEqual(second["brightness"], 42)
        self.assertTrue(second["mute"])
        cleared = self.post_json("/oi/control", {"mute": None})["control"]
        self.assertIsNone(cleared["mute"])

    def test_ping_and_answer_sequences_survive_store_restart(self):
        first_ping = self.post_json("/oi/ping", {})["recorded"]
        second_ping = self.post_json("/oi/ping", {"note": "yo"})["recorded"]
        self.assertEqual(first_ping["seq"], 1)
        self.assertEqual(second_ping["seq"], 2)

        self.post_json("/oi/state", {"id": "q1", "options": [{"label": "ok", "value": "ok"}]})
        first_answer = self.post_json("/oi/answer", {"id": "q1", "value": "ok"})["recorded"]
        self.assertEqual(first_answer["seq"], 1)

        Handler.store = StateStore(Path(self.tmp.name))
        third_ping = self.post_json("/oi/ping", {})["recorded"]
        second_answer = self.post_json("/oi/answer", {"id": "q2", "value": "later"})["recorded"]
        self.assertEqual(third_ping["seq"], 3)
        self.assertEqual(second_answer["seq"], 2)

    def test_atomic_json_write_preserves_previous_file_on_replace_failure(self):
        store = Handler.store
        store.set({"id": "old", "options": []})
        original = json.loads(store.state_path.read_text())
        with mock.patch("server.oi_server.os.replace", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                store.set({"id": "new", "options": []})
        self.assertEqual(json.loads(store.state_path.read_text()), original)

    def test_session_prompt_projects_through_legacy_state_and_answer_log(self):
        s1 = self.post_json("/oi/sessions/upsert", {"session_id": "s1", "name": "one"})["session"]
        self.post_json("/oi/sessions/upsert", {"session_id": "s2", "name": "two"})
        self.assertEqual(s1["session_id"], "s1")
        self.assertEqual(self.get_json("/oi/sessions")["active_session_id"], "s1")

        p1 = self.post_json("/oi/prompts", {
            "session_id": "s1",
            "tool_use_id": "t1",
            "kind": "approval",
            "title": "approve",
            "body": "run tests",
            "options": [{"label": "yes", "value": "yes"}],
        })["prompt"]
        p1_again = self.post_json("/oi/prompts", {
            "session_id": "s1",
            "tool_use_id": "t1",
            "title": "duplicate",
        })["prompt"]
        self.assertEqual(p1_again["prompt_id"], p1["prompt_id"])

        state = self.get_json("/oi/state")
        self.assertEqual(state["id"], p1["prompt_id"])
        self.assertEqual(state["session_id"], "s1")
        self.assertEqual(state["session_name"], "one")

        answer = self.post_json("/oi/answer", {"id": p1["prompt_id"], "value": "yes"})["recorded"]
        self.assertEqual(answer["prompt_id"], p1["prompt_id"])
        self.assertEqual(answer["session_id"], "s1")
        self.assertEqual(answer["tool_use_id"], "t1")
        prompts = self.get_json("/oi/prompts?session_id=s1&status=answered")["prompts"]
        self.assertEqual(prompts[-1]["response"], "yes")
        all_prompts = self.get_json("/oi/prompts?session_id=s1&status=all")["prompts"]
        self.assertGreaterEqual(len(all_prompts), 1)
        self.assertIsNone(self.get_json("/oi/state")["id"])

    def test_state_includes_compact_session_summary(self):
        self.post_json("/oi/sessions/upsert", {"session_id": "s1", "name": "one", "status": "running", "summary": "tests"})
        self.post_json("/oi/sessions/upsert", {"session_id": "s2", "name": "two", "status": "idle"})
        self.post_json("/oi/prompts", {"session_id": "s1", "title": "one"})
        self.post_json("/oi/prompts", {"session_id": "s1", "title": "two"})
        state = self.get_json("/oi/state")
        ordered_sessions = state["sessions"]["sessions"]
        sessions = {s["session_id"]: s for s in ordered_sessions}
        self.assertEqual(state["sessions"]["active_session_id"], "s1")
        self.assertEqual(ordered_sessions[0]["session_id"], "s1")
        self.assertEqual(sessions["s1"]["name"], "one")
        self.assertEqual(sessions["s1"]["status"], "running")
        self.assertEqual(sessions["s1"]["reported_status"], "running")
        self.assertEqual(sessions["s1"]["summary"], "tests")
        self.assertEqual(sessions["s1"]["pending_count"], 2)
        self.assertEqual(sessions["s2"]["pending_count"], 0)
        self.assertIn("stale", sessions["s1"])
        self.assertIn("last_seen_age_s", sessions["s1"])
        self.assertIsInstance(sessions["s1"]["stale"], bool)

    def test_session_summary_orders_pending_ahead_of_idle_when_not_active(self):
        self.post_json("/oi/sessions/upsert", {"session_id": "s1", "name": "one", "status": "idle"})
        self.post_json("/oi/sessions/upsert", {"session_id": "s2", "name": "two", "status": "idle"})
        self.post_json("/oi/sessions/active", {"session_id": "s1"})
        self.post_json("/oi/prompts", {"session_id": "s2", "title": "pending"})
        state = self.get_json("/oi/state")
        order = [s["session_id"] for s in state["sessions"]["sessions"]]
        self.assertEqual(order[0], "s1")  # active first
        self.assertEqual(order[1], "s2")  # then non-active with pending work

    def test_session_summary_marks_stale_sessions(self):
        with mock.patch("server.oi_sessions.now_iso", return_value="2000-01-01T00:00:00+00:00"):
            self.post_json("/oi/sessions/upsert", {"session_id": "s-old", "name": "old", "status": "running"})
        state = self.get_json("/oi/state")
        sessions = {s["session_id"]: s for s in state["sessions"]["sessions"]}
        self.assertTrue(sessions["s-old"]["stale"])
        self.assertEqual(sessions["s-old"]["status"], "offline")
        self.assertEqual(sessions["s-old"]["reported_status"], "running")
        self.assertGreater(sessions["s-old"]["last_seen_age_s"], 100)

    def test_sessions_stats_endpoint_reports_counts(self):
        self.post_json("/oi/sessions/upsert", {"session_id": "s1", "name": "one"})
        self.post_json("/oi/prompts", {"session_id": "s1", "title": "q1"})
        self.post_json("/oi/commands", {"session_id": "s1", "verb": "status"})
        stats = self.get_json("/oi/sessions/stats")
        self.assertEqual(stats["session_count"], 1)
        self.assertEqual(stats["active_session_id"], "s1")
        self.assertEqual(stats["prompts"]["total"], 1)
        self.assertEqual(stats["prompts"]["by_status"].get("pending"), 1)
        self.assertEqual(stats["commands"]["total"], 1)
        self.assertEqual(stats["commands"]["by_status"].get("queued"), 1)
        self.assertIn("oldest_pending_prompt_age_s", stats)
        self.assertIn("oldest_queued_command_age_s", stats)

    def test_active_session_controls_legacy_state_projection(self):
        self.post_json("/oi/sessions/upsert", {"session_id": "s1", "name": "one"})
        self.post_json("/oi/sessions/upsert", {"session_id": "s2", "name": "two"})
        p1 = self.post_json("/oi/prompts", {"session_id": "s1", "title": "one"})["prompt"]
        p2 = self.post_json("/oi/prompts", {"session_id": "s2", "title": "two"})["prompt"]
        self.assertEqual(self.get_json("/oi/state")["id"], p1["prompt_id"])
        self.post_json("/oi/sessions/active", {"session_id": "s2"})
        self.assertEqual(self.get_json("/oi/state")["id"], p2["prompt_id"])

    def test_direct_prompt_answer_records_answer(self):
        self.post_json("/oi/sessions/upsert", {"session_id": "s1"})
        prompt = self.post_json("/oi/prompts", {"session_id": "s1", "title": "Pick"})["prompt"]
        recorded = self.post_json(f"/oi/prompts/{prompt['prompt_id']}/answer", {"value": "ok"})["recorded"]
        self.assertEqual(recorded["prompt_id"], prompt["prompt_id"])
        self.assertEqual(self.get_json("/oi/answers")["answers"][-1]["value"], "ok")

    def test_bulk_prompt_cancel_endpoint(self):
        self.post_json("/oi/sessions/upsert", {"session_id": "s1"})
        self.post_json("/oi/prompts", {"session_id": "s1", "title": "one"})
        self.post_json("/oi/prompts", {"session_id": "s1", "title": "two"})
        result = self.post_json("/oi/prompts/cancel", {"session_id": "s1"})
        self.assertEqual(result["cancelled"], 2)
        pending = self.get_json("/oi/prompts?session_id=s1&status=pending")["prompts"]
        self.assertEqual(pending, [])

    def test_prompts_limit_query_param(self):
        self.post_json("/oi/sessions/upsert", {"session_id": "s1"})
        self.post_json("/oi/prompts", {"session_id": "s1", "title": "one"})
        self.post_json("/oi/prompts", {"session_id": "s1", "title": "two"})
        limited = self.get_json("/oi/prompts?session_id=s1&status=all&limit=1")["prompts"]
        self.assertEqual(len(limited), 1)
        self.assertEqual(limited[0]["title"], "two")

    def test_sessions_cleanup_endpoint_cancels_prompts_and_commands(self):
        self.post_json("/oi/sessions/upsert", {"session_id": "s1"})
        self.post_json("/oi/prompts", {"session_id": "s1", "title": "one"})
        self.post_json("/oi/commands", {"session_id": "s1", "verb": "status"})
        result = self.post_json("/oi/sessions/cleanup", {"session_id": "s1", "reason": "cleanup"})
        self.assertEqual(result["cancelled_prompts"], 1)
        self.assertEqual(result["cancelled_commands"], 1)

    def test_session_list_includes_pending_count_and_active_first_order(self):
        self.post_json("/oi/sessions/upsert", {"session_id": "s1", "name": "one"})
        self.post_json("/oi/sessions/upsert", {"session_id": "s2", "name": "two"})
        self.post_json("/oi/prompts", {"session_id": "s2", "title": "todo"})
        listed = self.get_json("/oi/sessions")
        self.assertEqual(listed["sessions"][0]["session_id"], "s1")
        rows = {s["session_id"]: s for s in listed["sessions"]}
        self.assertEqual(rows["s1"]["pending_count"], 0)
        self.assertEqual(rows["s2"]["pending_count"], 1)

    def test_session_routes_can_require_bearer_token(self):
        with mock.patch.dict(os.environ, {"OI_API_TOKEN": "secret"}):
            self.assertEqual(self.get_json("/oi/health"), {"ok": True, "service": "oi"})
            self.assertEqual(self.post_json("/oi/sessions/upsert", {"session_id": "s1"}, expected_status=401), {"error": "unauthorized"})

    def test_command_queue_ack_and_fail(self):
        self.post_json("/oi/sessions/upsert", {"session_id": "s1"})
        c1 = self.post_json("/oi/commands", {"session_id": "s1", "verb": "status"})["command"]
        c2 = self.post_json("/oi/commands", {"session_id": "s1", "verb": "abort"})["command"]
        self.assertEqual(c1["seq"], 1)
        queued = self.get_json("/oi/commands?session_id=s1&after_seq=1")["commands"]
        self.assertEqual([c["command_id"] for c in queued], [c2["command_id"]])
        acked = self.post_json(f"/oi/commands/{c2['command_id']}/ack", {"result": {"ok": True}})["command"]
        self.assertEqual(acked["status"], "acked")
        failed = self.post_json(f"/oi/commands/{c1['command_id']}/fail", {"error": "boom"})["command"]
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(self.get_json("/oi/commands?session_id=s1")["commands"], [])
        all_cmds = self.get_json("/oi/commands?session_id=s1&status=all")["commands"]
        self.assertEqual({c["status"] for c in all_cmds}, {"acked", "failed"})

    def test_command_queue_accepts_speak_verb(self):
        self.post_json("/oi/sessions/upsert", {"session_id": "s1"})
        cmd = self.post_json("/oi/commands", {
            "session_id": "s1",
            "verb": "speak",
            "args": {"message": "hello"},
        })["command"]
        self.assertEqual(cmd["verb"], "speak")
        queued = self.get_json("/oi/commands?session_id=s1")["commands"]
        self.assertEqual([c["command_id"] for c in queued], [cmd["command_id"]])

    def test_command_can_be_cancelled(self):
        self.post_json("/oi/sessions/upsert", {"session_id": "s1"})
        cmd = self.post_json("/oi/commands", {"session_id": "s1", "verb": "status"})["command"]
        cancelled = self.post_json(f"/oi/commands/{cmd['command_id']}/cancel", {"reason": "operator"})["command"]
        self.assertEqual(cancelled["status"], "cancelled")
        all_cmds = self.get_json("/oi/commands?session_id=s1&status=all")["commands"]
        self.assertEqual(all_cmds[0]["status"], "cancelled")

    def test_cancel_does_not_override_finished_command(self):
        self.post_json("/oi/sessions/upsert", {"session_id": "s1"})
        cmd = self.post_json("/oi/commands", {"session_id": "s1", "verb": "status"})["command"]
        self.post_json(f"/oi/commands/{cmd['command_id']}/ack", {"result": {"ok": True}})
        cancelled = self.post_json(f"/oi/commands/{cmd['command_id']}/cancel", {"reason": "operator"})["command"]
        self.assertEqual(cancelled["status"], "acked")

    def test_command_queue_dedupes_by_request_id_while_queued(self):
        self.post_json("/oi/sessions/upsert", {"session_id": "s1"})
        c1 = self.post_json("/oi/commands", {
            "session_id": "s1",
            "verb": "status",
            "request_id": "fw:s1:status",
        })["command"]
        c2 = self.post_json("/oi/commands", {
            "session_id": "s1",
            "verb": "status",
            "request_id": "fw:s1:status",
        })["command"]
        self.assertEqual(c1["command_id"], c2["command_id"])
        self.assertEqual(c1["seq"], c2["seq"])
        queued = self.get_json("/oi/commands?session_id=s1")["commands"]
        self.assertEqual(len(queued), 1)

    def test_bulk_command_cancel_endpoint(self):
        self.post_json("/oi/sessions/upsert", {"session_id": "s1"})
        self.post_json("/oi/commands", {"session_id": "s1", "verb": "status"})
        self.post_json("/oi/commands", {"session_id": "s1", "verb": "abort"})
        result = self.post_json("/oi/commands/cancel", {"session_id": "s1", "reason": "cleanup"})
        self.assertEqual(result["cancelled"], 2)
        queued = self.get_json("/oi/commands?session_id=s1")["commands"]
        self.assertEqual(queued, [])
        cancelled = self.get_json("/oi/commands?session_id=s1&status=cancelled")["commands"]
        self.assertEqual(len(cancelled), 2)

    def test_commands_limit_query_param(self):
        self.post_json("/oi/sessions/upsert", {"session_id": "s1"})
        c1 = self.post_json("/oi/commands", {"session_id": "s1", "verb": "status"})["command"]
        c2 = self.post_json("/oi/commands", {"session_id": "s1", "verb": "abort"})["command"]
        all_cmds = self.get_json("/oi/commands?session_id=s1&status=all&limit=1")["commands"]
        self.assertEqual(len(all_cmds), 1)
        self.assertEqual(all_cmds[0]["command_id"], c2["command_id"])

    def test_expired_prompt_is_not_projected_to_state(self):
        self.post_json("/oi/sessions/upsert", {"session_id": "s1"})
        prompt = self.post_json("/oi/prompts", {
            "session_id": "s1",
            "title": "stale",
            "expires_at": "2000-01-01T00:00:00+00:00",
        })["prompt"]
        state = self.get_json("/oi/state")
        self.assertIsNone(state["id"])
        expired = self.get_json("/oi/prompts?status=expired")["prompts"]
        self.assertTrue(any(p["prompt_id"] == prompt["prompt_id"] for p in expired))

    def test_expired_command_is_not_returned_as_queued(self):
        self.post_json("/oi/sessions/upsert", {"session_id": "s1"})
        command = self.post_json("/oi/commands", {
            "session_id": "s1",
            "verb": "status",
            "expires_at": "2000-01-01T00:00:00+00:00",
        })["command"]
        queued = self.get_json("/oi/commands?session_id=s1")["commands"]
        self.assertEqual(queued, [])
        expired = self.get_json("/oi/commands?session_id=s1&status=expired")["commands"]
        self.assertEqual([c["command_id"] for c in expired], [command["command_id"]])
        self.assertEqual(expired[0]["result"], "expired")

    def test_up_endpoint_acks_and_accepts_missing_version(self):
        # /oi/up just needs to ack so the device can fire-and-forget at boot.
        self.assertEqual(self.post_json("/oi/up", {"version": "abc1234"}), {"ok": True})
        # Missing version still acks (server falls back to "?" in its log line).
        self.assertEqual(self.post_json("/oi/up", {}), {"ok": True})

    def test_up_endpoint_validates_payload_shape(self):
        self.assertIn("up.volume", self.post_json("/oi/up", {"volume": 101}, expected_status=400)["error"])
        self.assertIn("up.mute", self.post_json("/oi/up", {"mute": "yes"}, expected_status=400)["error"])
        self.assertIn("unknown up field", self.post_json("/oi/up", {"x": 1}, expected_status=400)["error"])

    def test_event_endpoint_acks(self):
        self.assertEqual(self.post_json("/oi/event", {"kind": "chirp", "data": "wake:ok"}), {"ok": True})
        # Defaults are tolerated so devices can post sparsely.
        self.assertEqual(self.post_json("/oi/event", {}), {"ok": True})

    def _post_wav(self, path, data, expected_status=200):
        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers={"Content-Type": "audio/wav"},
            method="POST",
        )
        if expected_status >= 400:
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(req, timeout=2)
            self.assertEqual(cm.exception.code, expected_status)
            return json.loads(cm.exception.read().decode("utf-8"))
        with urllib.request.urlopen(req, timeout=2) as resp:
            self.assertEqual(resp.status, expected_status)
            return json.loads(resp.read().decode("utf-8"))

    def test_audio_endpoint_transcribes_and_returns_transcript(self):
        fake_wav = b"RIFF\x00\x00\x00\x00WAVEfmt " + b"\x00" * 100
        with mock.patch("server.stt.transcribe", return_value="hello world"):
            result = self._post_wav("/oi/audio", fake_wav)
        self.assertEqual(result, {"transcript": "hello world"})

    def test_audio_endpoint_queues_prompt_when_session_given(self):
        self.post_json("/oi/sessions/upsert", {"session_id": "s1"})
        fake_wav = b"RIFF\x00\x00\x00\x00WAVEfmt " + b"\x00" * 100
        with mock.patch("server.stt.transcribe", return_value="run the tests"):
            result = self._post_wav("/oi/audio?session_id=s1", fake_wav)
        self.assertEqual(result["transcript"], "run the tests")
        commands = self.get_json("/oi/commands?session_id=s1")["commands"]
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0]["verb"], "prompt")
        # Message uses cleaned transcript (adds trailing period)
        self.assertEqual(commands[0]["args"]["message"], "run the tests.")

    def test_audio_endpoint_tags_prompt_command_with_voice_source(self):
        self.post_json("/oi/sessions/upsert", {"session_id": "s1"})
        fake_wav = b"RIFF\x00\x00\x00\x00WAVEfmt " + b"\x00" * 100
        with mock.patch("server.stt.transcribe", return_value="hello"):
            self._post_wav("/oi/audio?session_id=s1", fake_wav)
        commands = self.get_json("/oi/commands?session_id=s1")["commands"]
        self.assertEqual(commands[0]["args"].get("source"), "voice")

    def test_audio_endpoint_rejects_empty_body(self):
        result = self._post_wav("/oi/audio", b"", expected_status=400)
        self.assertIn("error", result)

    def test_audio_endpoint_returns_503_when_stt_unavailable(self):
        from server.stt import SttUnavailable
        fake_wav = b"RIFF\x00\x00\x00\x00WAVEfmt " + b"\x00" * 100
        with mock.patch("server.stt.transcribe", side_effect=SttUnavailable("not installed")):
            req = urllib.request.Request(
                self.base_url + "/oi/audio",
                data=fake_wav,
                headers={"Content-Type": "audio/wav"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(req, timeout=2)
            self.assertEqual(cm.exception.code, 503)

    def test_audio_endpoint_skips_prompt_queue_when_no_session(self):
        fake_wav = b"RIFF\x00\x00\x00\x00WAVEfmt " + b"\x00" * 100
        with mock.patch("server.stt.transcribe", return_value="hello"):
            result = self._post_wav("/oi/audio", fake_wav)
        self.assertEqual(result["transcript"], "hello")
        commands = self.get_json("/oi/commands")["commands"]
        self.assertEqual(commands, [])

    def test_audio_endpoint_submit_zero_transcribe_only(self):
        self.post_json("/oi/sessions/upsert", {"session_id": "s1"})
        fake_wav = b"RIFF\x00\x00\x00\x00WAVEfmt " + b"\x00" * 100
        with mock.patch("server.stt.transcribe", return_value="um hello world"):
            result = self._post_wav("/oi/audio?session_id=s1&submit=0", fake_wav)
        # Returns both raw and cleaned transcript
        self.assertEqual(result["transcript"], "um hello world")
        self.assertEqual(result["cleaned"], "hello world.")
        # Does NOT create a prompt command
        commands = self.get_json("/oi/commands?session_id=s1")["commands"]
        self.assertEqual(commands, [])


class DeviceSettingsCase(OiServerCase):
    def test_state_includes_device_field_with_none_defaults(self):
        state = self.get_json("/oi/state")
        self.assertIn("device", state)
        self.assertIsNone(state["device"]["volume"])
        self.assertIsNone(state["device"]["mute"])
        self.assertEqual(state["device"]["response_pace_hint"], "unknown")

    def test_up_with_volume_and_mute_stored_in_state(self):
        self.post_json("/oi/up", {"version": "abc", "volume": 60, "mute": False})
        state = self.get_json("/oi/state")
        self.assertEqual(state["device"]["volume"], 60)
        self.assertFalse(state["device"]["mute"])
        self.assertEqual(state["device"]["response_pace_hint"], "normal")

    def test_up_with_mute_true(self):
        self.post_json("/oi/up", {"version": "abc", "volume": 0, "mute": True})
        state = self.get_json("/oi/state")
        self.assertTrue(state["device"]["mute"])
        self.assertEqual(state["device"]["response_pace_hint"], "possibly_delayed")

    def test_up_without_settings_leaves_device_none(self):
        self.post_json("/oi/up", {"version": "abc"})
        state = self.get_json("/oi/state")
        self.assertIsNone(state["device"]["mute"])
        self.assertEqual(state["device"]["response_pace_hint"], "unknown")


class SpeakEndpointCase(OiServerCase):
    def _fake_wav(self):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(44100)
            wf.writeframes(b"\x00\x00\x00\x00\x00\x00\x00\x00")
        return buf.getvalue()

    def _post_speak(self, text, expected_status=200):
        with mock.patch("server.tts.synthesize", return_value=self._fake_wav()):
            return self.post_json("/oi/speak", {"text": text}, expected_status)

    def _get_speak_raw(self):
        req = urllib.request.Request(self.base_url + "/oi/speak", method="GET")
        try:
            with urllib.request.urlopen(req, timeout=2) as resp:
                return resp.status, resp.read(), resp.headers.get("Content-Type")
        except urllib.error.HTTPError as e:
            return e.code, b"", ""

    def test_post_speak_returns_ok_and_speak_seq(self):
        result = self._post_speak("hello world")
        self.assertTrue(result["ok"])
        self.assertEqual(result["speak_seq"], 1)

    def test_get_speak_returns_wav_after_post(self):
        fake_wav = self._fake_wav()
        self._post_speak("hello")
        status, body, ct = self._get_speak_raw()
        self.assertEqual(status, 200)
        self.assertEqual(ct, "audio/wav")
        self.assertEqual(body, fake_wav)

    def test_get_speak_returns_204_before_any_post(self):
        status, body, _ = self._get_speak_raw()
        self.assertEqual(status, 204)
        self.assertEqual(body, b"")

    def test_speak_seq_increments_on_each_post(self):
        r1 = self._post_speak("one")
        r2 = self._post_speak("two")
        self.assertEqual(r1["speak_seq"], 1)
        self.assertEqual(r2["speak_seq"], 2)

    def test_speak_seq_appears_in_control(self):
        self._post_speak("hello")
        state = self.get_json("/oi/state")
        self.assertEqual(state["control"].get("speak_seq"), 1)

    def test_post_speak_rejects_missing_text(self):
        with mock.patch("server.tts.synthesize", return_value=self._fake_wav()):
            result = self.post_json("/oi/speak", {}, expected_status=400)
        self.assertIn("error", result)

    def test_post_speak_rejects_oversized_wav(self):
        from server.tts import MAX_SPEAK_WAV_BYTES
        big_wav = b"\x00" * (MAX_SPEAK_WAV_BYTES + 1)
        with mock.patch("server.tts.synthesize", return_value=big_wav):
            result = self.post_json("/oi/speak", {"text": "x" * 10000}, expected_status=413)
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
