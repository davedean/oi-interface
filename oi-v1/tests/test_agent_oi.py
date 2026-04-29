import importlib
import io
import json
import os
import urllib.error
import unittest
from datetime import datetime
from unittest import mock

import agent.oi as oi


class AgentOiCase(unittest.TestCase):
    def test_normalise_options_defaults_to_ok(self):
        self.assertEqual(oi._normalise_options(None), [{"label": "ok", "value": "ok"}])
        self.assertEqual(oi._normalise_options([]), [{"label": "ok", "value": "ok"}])

    def test_normalise_options_accepts_supported_shapes(self):
        self.assertEqual(
            oi._normalise_options(["yes", ("No thanks", "no"), {"label": "Later", "value": "later"}]),
            [
                {"label": "yes", "value": "yes"},
                {"label": "No thanks", "value": "no"},
                {"label": "Later", "value": "later"},
            ],
        )

    def test_normalise_options_rejects_unknown_shapes(self):
        with self.assertRaises(ValueError):
            oi._normalise_options([object()])

    def test_server_url_can_be_set_from_environment(self):
        with mock.patch.dict(os.environ, {"OI_SERVER_URL": "http://example.test:8842"}):
            reloaded = importlib.reload(oi)
            self.assertEqual(reloaded.SERVER_URL, "http://example.test:8842")
        importlib.reload(oi)

    def test_wait_for_ping_prefers_seq_over_timestamp(self):
        calls = [
            [{"seq": 2, "ts": "same"}],
            [{"seq": 2, "ts": "same"}],
            [{"seq": 2, "ts": "same"}, {"seq": 3, "ts": "same"}],
        ]
        with mock.patch.object(oi, "recent_pings", side_effect=calls), \
                mock.patch.object(oi.time, "sleep", return_value=None):
            self.assertEqual(oi.wait_for_ping(timeout=2), {"seq": 3, "ts": "same"})

    def test_wait_for_ping_handles_baseline_without_seq(self):
        calls = [
            [{"ts": "2026-04-25T00:00:00+10:00"}],
            [{"ts": "2026-04-25T00:00:00+10:00"}, {"seq": 1, "ts": "2026-04-25T00:00:00+10:00"}],
        ]
        with mock.patch.object(oi, "recent_pings", side_effect=calls), \
                mock.patch.object(oi.time, "sleep", return_value=None):
            self.assertEqual(oi.wait_for_ping(timeout=2), {"seq": 1, "ts": "2026-04-25T00:00:00+10:00"})

    def test_session_helpers_call_session_routes(self):
        calls = []
        def fake_post(path, payload):
            calls.append((path, payload))
            if path == "/oi/sessions/upsert":
                return {"session": {"session_id": payload["session_id"]}}
            if path == "/oi/sessions/active":
                return {"session": {"session_id": payload["session_id"]}}
            if path == "/oi/commands":
                return {"command": {"command_id": "c-1", **payload}}
            if path.endswith("/ack") or path.endswith("/fail") or path.endswith("/cancel"):
                return {"command": {"command_id": path.split("/")[3]}}
            raise AssertionError(path)
        with mock.patch.object(oi, "_post", side_effect=fake_post):
            self.assertEqual(oi.register_session("s1")["session_id"], "s1")
            self.assertEqual(oi.activate_session("s1")["session_id"], "s1")
            self.assertEqual(oi.send_command("s1", "status")["verb"], "status")
            self.assertEqual(oi.ack_command("c-1")["command_id"], "c-1")
            self.assertEqual(oi.fail_command("c-1", "boom")["command_id"], "c-1")
            self.assertEqual(oi.cancel_command("c-1")["command_id"], "c-1")
        self.assertEqual(calls[0][0], "/oi/sessions/upsert")

    def test_send_command_passes_optional_request_id(self):
        sent = {}
        def fake_post(path, payload):
            sent["path"] = path
            sent["payload"] = payload
            return {"command": {"command_id": "c-1"}}
        with mock.patch.object(oi, "_post", side_effect=fake_post):
            oi.send_command("s1", "status", request_id="fw:s1:status")
        self.assertEqual(sent["path"], "/oi/commands")
        self.assertEqual(sent["payload"]["request_id"], "fw:s1:status")

    def test_send_command_can_set_expiry_from_offset(self):
        sent = {}
        def fake_post(path, payload):
            sent["payload"] = payload
            return {"command": {"command_id": "c-1"}}
        with mock.patch.object(oi, "_post", side_effect=fake_post):
            oi.send_command("s1", "status", expires_in=30)
        self.assertIn("expires_at", sent["payload"])
        datetime.fromisoformat(sent["payload"]["expires_at"])

    def test_send_command_rejects_both_expires_in_and_expires_at(self):
        with self.assertRaises(ValueError):
            oi.send_command("s1", "status", expires_in=30, expires_at="2026-01-01T00:00:00+00:00")

    def test_count_pending_prompts_counts_pending_only(self):
        with mock.patch.object(oi, "list_session_prompts", return_value=[{"prompt_id": "p-1"}, {"prompt_id": "p-2"}]):
            self.assertEqual(oi.count_pending_prompts(session_id="s1"), 2)

    def test_cancel_pending_prompts_uses_bulk_endpoint(self):
        with mock.patch.object(oi, "_post", return_value={"cancelled": 2}) as post:
            count = oi.cancel_pending_prompts(session_id="s1")
        self.assertEqual(count, 2)
        self.assertEqual(post.call_args.args[0], "/oi/prompts/cancel")

    def test_cancel_pending_prompts_falls_back_when_bulk_endpoint_missing(self):
        prompts = [{"prompt_id": "p-1"}, {"prompt_id": "p-2"}, {"prompt_id": None}]
        cancelled = []
        err = urllib.error.HTTPError(url="http://x/oi/prompts/cancel", code=404, msg="nf", hdrs={}, fp=io.BytesIO(b"{}"))
        with mock.patch.object(oi, "_post", side_effect=err), \
                mock.patch.object(oi, "list_session_prompts", return_value=prompts), \
                mock.patch.object(oi, "cancel_prompt", side_effect=lambda pid: cancelled.append(pid) or {}):
            count = oi.cancel_pending_prompts(session_id="s1")
        self.assertEqual(count, 2)
        self.assertEqual(cancelled, ["p-1", "p-2"])

    def test_count_queued_commands_counts_queued_only(self):
        with mock.patch.object(oi, "list_commands", return_value=[{"command_id": "c-1"}]):
            self.assertEqual(oi.count_queued_commands(session_id="s1"), 1)

    def test_cancel_queued_commands_uses_bulk_endpoint(self):
        with mock.patch.object(oi, "_post", return_value={"cancelled": 2}) as post:
            count = oi.cancel_queued_commands(session_id="s1", reason="cleanup")
        self.assertEqual(count, 2)
        self.assertEqual(post.call_args.args[0], "/oi/commands/cancel")

    def test_cancel_queued_commands_falls_back_when_bulk_endpoint_missing(self):
        queued = [{"command_id": "c-1"}, {"command_id": "c-2"}, {"command_id": None}]
        cancelled = []
        err = urllib.error.HTTPError(url="http://x/oi/commands/cancel", code=404, msg="nf", hdrs={}, fp=io.BytesIO(b"{}"))
        with mock.patch.object(oi, "_post", side_effect=err), \
                mock.patch.object(oi, "list_commands", return_value=queued), \
                mock.patch.object(oi, "cancel_command", side_effect=lambda cid, reason="": cancelled.append((cid, reason)) or {}):
            count = oi.cancel_queued_commands(session_id="s1", reason="cleanup")
        self.assertEqual(count, 2)
        self.assertEqual(cancelled, [("c-1", "cleanup"), ("c-2", "cleanup")])

    def test_cleanup_session_uses_bulk_endpoint(self):
        with mock.patch.object(oi, "_post", return_value={"cancelled_prompts": 4, "cancelled_commands": 2}) as post:
            result = oi.cleanup_session(session_id="s1", reason="cleanup")
        self.assertEqual(result, {"cancelled_prompts": 4, "cancelled_commands": 2})
        self.assertEqual(post.call_args.args[0], "/oi/sessions/cleanup")

    def test_cleanup_session_falls_back_when_endpoint_missing(self):
        err = urllib.error.HTTPError(url="http://x/oi/sessions/cleanup", code=404, msg="nf", hdrs={}, fp=io.BytesIO(b"{}"))
        with mock.patch.object(oi, "_post", side_effect=err), \
                mock.patch.object(oi, "cancel_pending_prompts", return_value=1), \
                mock.patch.object(oi, "cancel_queued_commands", return_value=2):
            result = oi.cleanup_session(session_id="s1", reason="cleanup")
        self.assertEqual(result, {"cancelled_prompts": 1, "cancelled_commands": 2})

    def test_ask_session_posts_prompt_and_waits_for_prompt_answer(self):
        responses = [
            {"answers": []},
            {"answers": [{"prompt_id": "p-1", "value": "approve"}]},
        ]
        with mock.patch.object(oi, "_post", return_value={"prompt": {"prompt_id": "p-1"}}) as post, \
                mock.patch.object(oi, "_get", side_effect=responses), \
                mock.patch.object(oi.time, "sleep", return_value=None):
            self.assertEqual(oi.approve_session("s1", "Bash", "ls", tool_use_id="t1", timeout=2), "approve")
        post.assert_called_once()
        self.assertEqual(post.call_args.args[0], "/oi/prompts")
        self.assertEqual(post.call_args.args[1]["session_id"], "s1")
        self.assertEqual(post.call_args.args[1]["tool_use_id"], "t1")

    def test_approve_session_cancels_prompt_on_timeout(self):
        posted = {"prompt": {"prompt_id": "p-1"}}
        with mock.patch.object(oi, "_post", side_effect=[posted, {"prompt": {"prompt_id": "p-1", "status": "cancelled"}}]) as post, \
                mock.patch.object(oi, "_get", return_value={"answers": []}), \
                mock.patch.object(oi.time, "monotonic", side_effect=[0, 2]), \
                mock.patch.object(oi.time, "sleep", return_value=None):
            self.assertIsNone(oi.approve_session("s1", "Bash", timeout=1))
        self.assertEqual(post.call_args_list[-1].args[0], "/oi/prompts/p-1/cancel")

    def test_poll_commands_uses_session_query(self):
        with mock.patch.object(oi, "_get", return_value={"commands": [{"seq": 2}]}) as get:
            self.assertEqual(oi.poll_commands("s 1", after_seq=1), [{"seq": 2}])
        self.assertIn("session_id=s+1", get.call_args.args[0])
        self.assertIn("after_seq=1", get.call_args.args[0])

    def test_list_session_prompts_builds_filtered_query(self):
        with mock.patch.object(oi, "_get", return_value={"prompts": [{"prompt_id": "p-1"}]}) as get:
            prompts = oi.list_session_prompts(session_id="s 1", status="pending", limit=5)
        self.assertEqual(prompts, [{"prompt_id": "p-1"}])
        self.assertIn("session_id=s+1", get.call_args.args[0])
        self.assertIn("status=pending", get.call_args.args[0])
        self.assertIn("limit=5", get.call_args.args[0])

    def test_list_commands_builds_query(self):
        with mock.patch.object(oi, "_get", return_value={"commands": [{"command_id": "c-1"}]}) as get:
            commands = oi.list_commands(session_id="s1", status="failed", after_seq=3, limit=2)
        self.assertEqual(commands, [{"command_id": "c-1"}])
        self.assertIn("session_id=s1", get.call_args.args[0])
        self.assertIn("status=failed", get.call_args.args[0])
        self.assertIn("after_seq=3", get.call_args.args[0])
        self.assertIn("limit=2", get.call_args.args[0])

    def test_session_stats_helper_calls_stats_route(self):
        with mock.patch.object(oi, "_get", return_value={"session_count": 2}) as get:
            stats = oi.session_stats()
        self.assertEqual(stats["session_count"], 2)
        get.assert_called_once_with("/oi/sessions/stats")

    def test_status_collects_health_state_and_recent_pings(self):
        responses = {
            "/oi/health": {"ok": True, "service": "oi"},
            "/oi/sessions": {"active_session_id": "s1", "sessions": [{"session_id": "s1"}]},
            "/oi/sessions/stats": {"session_count": 1, "prompts": {"total": 1}, "commands": {"total": 0}},
            "/oi/state": {
                "id": "q1",
                "title": "Pick",
                "body": "body",
                "options": [{"label": "yes", "value": "yes"}],
                "snapshot": {"msg": "ready"},
                "control": {"brightness": 42},
                "device": {"volume": 0, "mute": True, "response_pace_hint": "possibly_delayed"},
            },
            "/oi/pings": {"pings": [{"seq": 1}, {"seq": 2}]},
        }
        with mock.patch.object(oi, "_get", side_effect=lambda path: responses[path]):
            status = oi.status(n=1)
        self.assertEqual(status["health"], {"ok": True, "service": "oi"})
        self.assertEqual(status["question"]["id"], "q1")
        self.assertEqual(status["snapshot"], {"msg": "ready"})
        self.assertEqual(status["control"], {"brightness": 42})
        self.assertEqual(status["device"], {"volume": 0, "mute": True, "response_pace_hint": "possibly_delayed"})
        self.assertEqual(status["sessions"]["active_session_id"], "s1")
        self.assertEqual(status["session_stats"]["session_count"], 1)
        self.assertEqual(status["pings"], [{"seq": 2}])

    def test_healthcheck_reports_threshold_violations(self):
        fake_status = {
            "session_stats": {
                "oldest_pending_prompt_age_s": 600,
                "oldest_queued_command_age_s": 120,
                "stale_session_count": 2,
            }
        }
        with mock.patch.object(oi, "status", return_value=fake_status):
            result = oi.healthcheck(max_oldest_prompt_s=300, max_oldest_command_s=300, max_stale_sessions=1)
        self.assertFalse(result["ok"])
        self.assertTrue(any("oldest pending prompt" in r for r in result["reasons"]))
        self.assertTrue(any("stale sessions" in r for r in result["reasons"]))

    def test_healthcheck_passes_when_within_limits(self):
        fake_status = {
            "session_stats": {
                "oldest_pending_prompt_age_s": 10,
                "oldest_queued_command_age_s": 20,
                "stale_session_count": 0,
            }
        }
        with mock.patch.object(oi, "status", return_value=fake_status):
            result = oi.healthcheck(max_oldest_prompt_s=300, max_oldest_command_s=300, max_stale_sessions=1)
        self.assertTrue(result["ok"])
        self.assertEqual(result["reasons"], [])

    def test_format_overview_includes_core_sections(self):
        text = oi.format_overview({
            "health": {"ok": True},
            "question": {"id": "q1", "title": "Deploy?"},
            "device": {"volume": 0, "mute": True, "response_pace_hint": "possibly_delayed"},
            "sessions": {
                "active_session_id": "s1",
                "sessions": [{"session_id": "s1", "name": "repo", "status": "running"}],
            },
            "session_stats": {
                "session_count": 1,
                "stale_session_count": 0,
                "oldest_pending_prompt_age_s": 1,
                "oldest_queued_command_age_s": 2,
                "prompts": {"total": 2},
                "commands": {"total": 1},
            },
            "pings": [{"seq": 7, "ts": "2026-04-26T12:00:00+10:00"}],
        })
        self.assertIn("service: ok", text)
        self.assertIn("question: q1 Deploy?", text)
        self.assertIn("pace=possibly_delayed", text)
        self.assertIn("active: repo", text)
        self.assertIn("queues: prompts=2 commands=1", text)

    def test_format_overview_warns_on_old_queues(self):
        text = oi.format_overview({
            "health": {"ok": True},
            "question": None,
            "session_stats": {
                "session_count": 1,
                "stale_session_count": 0,
                "oldest_pending_prompt_age_s": 0,
                "oldest_queued_command_age_s": 601,
                "prompts": {"total": 0},
                "commands": {"total": 1},
            },
        })
        self.assertIn("warning: queue age high", text)

    def test_cli_session_stats_prints_json(self):
        with mock.patch.object(oi, "session_stats", return_value={"session_count": 1}), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            rc = oi._main(["session-stats"])
        self.assertEqual(rc, 0)
        self.assertIn("session_count", stdout.getvalue())

    def test_cli_healthcheck_exit_codes(self):
        with mock.patch.object(oi, "healthcheck", return_value={"ok": True, "reasons": [], "stats": {}}), \
                mock.patch("sys.stdout", new_callable=io.StringIO):
            ok_rc = oi._main(["healthcheck"])
        self.assertEqual(ok_rc, 0)

        with mock.patch.object(oi, "healthcheck", return_value={"ok": False, "reasons": ["x"], "stats": {}}), \
                mock.patch("sys.stdout", new_callable=io.StringIO):
            bad_rc = oi._main(["healthcheck"])
        self.assertEqual(bad_rc, 1)

    def test_cli_overview_prints_human_readable_summary(self):
        fake = {
            "health": {"ok": True},
            "question": None,
            "device": {"volume": 50, "mute": False, "response_pace_hint": "normal"},
            "sessions": {"active_session_id": None, "sessions": []},
            "session_stats": {
                "session_count": 0,
                "stale_session_count": 0,
                "oldest_pending_prompt_age_s": None,
                "oldest_queued_command_age_s": None,
                "prompts": {"total": 0},
                "commands": {"total": 0},
            },
            "pings": [],
        }
        with mock.patch.object(oi, "status", return_value=fake), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            rc = oi._main(["overview"])
        self.assertEqual(rc, 0)
        self.assertIn("service: ok", stdout.getvalue())
        self.assertIn("question: none", stdout.getvalue())

    def test_cli_prompts_and_commands_emit_json(self):
        with mock.patch.object(oi, "list_session_prompts", return_value=[{"prompt_id": "p-1"}]) as lp, \
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            rc_prompts = oi._main(["prompts", "--status", "pending", "--limit", "3"])
        self.assertEqual(rc_prompts, 0)
        self.assertIn("prompt_id", stdout.getvalue())
        self.assertEqual(lp.call_args.kwargs["limit"], 3)

        with mock.patch.object(oi, "list_commands", return_value=[{"command_id": "c-1"}]) as lc, \
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout2:
            rc_commands = oi._main(["commands", "--status", "queued", "--limit", "2"])
        self.assertEqual(rc_commands, 0)
        self.assertIn("command_id", stdout2.getvalue())
        self.assertEqual(lc.call_args.kwargs["limit"], 2)

    def test_cli_cancel_prompts_prints_count(self):
        with mock.patch.object(oi, "cancel_pending_prompts", return_value=3), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            rc = oi._main(["cancel-prompts", "--session-id", "s1"])
        self.assertEqual(rc, 0)
        self.assertIn("cancelled 3 prompt(s)", stdout.getvalue())

    def test_cli_cancel_prompts_dry_run(self):
        with mock.patch.object(oi, "count_pending_prompts", return_value=5), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            rc = oi._main(["cancel-prompts", "--session-id", "s1", "--dry-run"])
        self.assertEqual(rc, 0)
        self.assertIn("would cancel 5 prompt(s)", stdout.getvalue())

    def test_cli_cancel_commands_prints_count(self):
        with mock.patch.object(oi, "cancel_queued_commands", return_value=2), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            rc = oi._main(["cancel-commands", "--session-id", "s1"])
        self.assertEqual(rc, 0)
        self.assertIn("cancelled 2 command(s)", stdout.getvalue())

    def test_cli_cancel_commands_dry_run(self):
        with mock.patch.object(oi, "count_queued_commands", return_value=4), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            rc = oi._main(["cancel-commands", "--session-id", "s1", "--dry-run"])
        self.assertEqual(rc, 0)
        self.assertIn("would cancel 4 command(s)", stdout.getvalue())

    def test_cli_cleanup_session_prints_json(self):
        with mock.patch.object(oi, "cleanup_session", return_value={"cancelled_prompts": 1, "cancelled_commands": 2}), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            rc = oi._main(["cleanup-session", "--session-id", "s1"])
        self.assertEqual(rc, 0)
        self.assertIn("cancelled_prompts", stdout.getvalue())

    def test_cli_cleanup_session_dry_run_prints_counts(self):
        with mock.patch.object(oi, "count_pending_prompts", return_value=3), \
                mock.patch.object(oi, "count_queued_commands", return_value=2), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            rc = oi._main(["cleanup-session", "--session-id", "s1", "--dry-run"])
        self.assertEqual(rc, 0)
        text = stdout.getvalue()
        self.assertIn("would_cancel_prompts", text)
        self.assertIn("would_cancel_commands", text)

    def test_cli_command_accepts_expires_in(self):
        with mock.patch.object(oi, "send_command", return_value={"command_id": "c-1"}) as send, \
                mock.patch("sys.stdout", new_callable=io.StringIO):
            rc = oi._main(["command", "s1", "status", "--expires-in", "5"])
        self.assertEqual(rc, 0)
        self.assertEqual(send.call_args.kwargs["expires_in"], 5.0)

    def test_cli_status_prints_friendly_server_down_error(self):
        with mock.patch.object(oi, "_get", side_effect=urllib.error.URLError("refused")), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            rc = oi._main(["status"])
        self.assertEqual(rc, 1)
        self.assertIn("cannot reach oi server", stderr.getvalue())

    def test_cli_http_error_reports_server_validation_message(self):
        err = urllib.error.HTTPError(
            url="http://example.test/oi/state",
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=io.BytesIO(b'{"error":"state.options must be a list"}'),
        )
        with mock.patch.object(oi, "_post", side_effect=err), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            rc = oi._main(["clear"])
        self.assertEqual(rc, 1)
        self.assertIn("server returned HTTP 400", stderr.getvalue())
        self.assertIn("state.options must be a list", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
