import tempfile
import unittest
from pathlib import Path
from unittest import mock

from server.oi_sessions import SessionRouter


class SessionRouterCompactionCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.router = SessionRouter(
            Path(self.tmp.name),
            max_completed_prompts=1,
            max_finished_commands=1,
        )
        self.router.upsert_session({"session_id": "s1", "name": "one"})

    def tearDown(self):
        self.tmp.cleanup()

    def test_compacts_completed_prompts_but_keeps_pending(self):
        p1 = self.router.create_prompt({"session_id": "s1", "title": "first"})
        self.router.answer_prompt(p1["prompt_id"], "ok")
        p2 = self.router.create_prompt({"session_id": "s1", "title": "second"})
        self.router.answer_prompt(p2["prompt_id"], "ok")
        p3 = self.router.create_prompt({"session_id": "s1", "title": "pending"})

        answered = self.router.list_prompts(session_id="s1", status="answered")
        pending = self.router.list_prompts(session_id="s1", status="pending")

        self.assertEqual([p["prompt_id"] for p in answered], [p2["prompt_id"]])
        self.assertEqual([p["prompt_id"] for p in pending], [p3["prompt_id"]])
        all_ids = [p["prompt_id"] for p in self.router.list_prompts(session_id="s1")]
        self.assertNotIn(p1["prompt_id"], all_ids)

    def test_compacts_finished_commands_but_keeps_queued(self):
        c1 = self.router.create_command({"session_id": "s1", "verb": "status"})
        self.router.finish_command(c1["command_id"], "acked", {"ok": True})
        c2 = self.router.create_command({"session_id": "s1", "verb": "abort"})
        self.router.finish_command(c2["command_id"], "failed", "boom")
        c3 = self.router.create_command({"session_id": "s1", "verb": "status"})

        queued = self.router.list_commands(session_id="s1", status="queued")
        failed = self.router.list_commands(session_id="s1", status="failed")
        acked = self.router.list_commands(session_id="s1", status="acked")

        self.assertEqual([c["command_id"] for c in queued], [c3["command_id"]])
        self.assertEqual([c["command_id"] for c in failed], [c2["command_id"]])
        self.assertEqual(acked, [])


class SessionRouterRetentionCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.router = SessionRouter(Path(self.tmp.name), session_retention_s=1)

    def tearDown(self):
        self.tmp.cleanup()

    def test_prunes_old_inactive_sessions(self):
        with mock.patch("server.oi_sessions.now_iso", return_value="2000-01-01T00:00:00+00:00"):
            self.router.upsert_session({"session_id": "s-old", "name": "old"})
        self.router.upsert_session({"session_id": "s-new", "name": "new"})
        self.router.set_active("s-new")

        listed_ids = [s["session_id"] for s in self.router.list_sessions()["sessions"]]
        self.assertIn("s-new", listed_ids)
        self.assertNotIn("s-old", listed_ids)

    def test_keeps_old_session_with_pending_prompt(self):
        with mock.patch("server.oi_sessions.now_iso", return_value="2000-01-01T00:00:00+00:00"):
            self.router.upsert_session({"session_id": "s-old", "name": "old"})
        self.router.create_prompt({"session_id": "s-old", "title": "still relevant"})
        self.router.upsert_session({"session_id": "s-new", "name": "new"})
        self.router.set_active("s-new")

        listed_ids = [s["session_id"] for s in self.router.list_sessions()["sessions"]]
        self.assertIn("s-old", listed_ids)
        self.assertIn("s-new", listed_ids)


class SessionRouterStatusCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.router = SessionRouter(Path(self.tmp.name), session_stale_s=1)

    def tearDown(self):
        self.tmp.cleanup()

    def test_stale_session_maps_to_offline_status(self):
        with mock.patch("server.oi_sessions.now_iso", return_value="2000-01-01T00:00:00+00:00"):
            self.router.upsert_session({"session_id": "s1", "name": "one", "status": "running"})
        listed = self.router.list_sessions()["sessions"]
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["status"], "offline")
        self.assertEqual(listed[0]["reported_status"], "running")
        self.assertTrue(listed[0]["stale"])
        self.assertIn("pending_count", listed[0])

    def test_stats_reports_prompt_and_command_status_counts(self):
        self.router.upsert_session({"session_id": "s1", "name": "one"})
        p = self.router.create_prompt({"session_id": "s1", "title": "q"})
        self.router.answer_prompt(p["prompt_id"], "ok")
        self.router.create_prompt({"session_id": "s1", "title": "q2"})

        c1 = self.router.create_command({"session_id": "s1", "verb": "status"})
        self.router.finish_command(c1["command_id"], "acked", {"ok": True})
        self.router.create_command({"session_id": "s1", "verb": "abort"})

        stats = self.router.stats()
        self.assertEqual(stats["session_count"], 1)
        self.assertEqual(stats["prompts"]["by_status"].get("answered"), 1)
        self.assertEqual(stats["prompts"]["by_status"].get("pending"), 1)
        self.assertEqual(stats["commands"]["by_status"].get("acked"), 1)
        self.assertEqual(stats["commands"]["by_status"].get("queued"), 1)
        self.assertIsInstance(stats["oldest_pending_prompt_age_s"], int)
        self.assertIsInstance(stats["oldest_queued_command_age_s"], int)

    def test_cancel_command_is_idempotent_for_finished_commands(self):
        self.router.upsert_session({"session_id": "s1", "name": "one"})
        cmd = self.router.create_command({"session_id": "s1", "verb": "status"})
        self.router.finish_command(cmd["command_id"], "acked", {"ok": True})

        unchanged = self.router.cancel_command(cmd["command_id"], "operator")
        self.assertEqual(unchanged["status"], "acked")


if __name__ == "__main__":
    unittest.main()
