import sys
import unittest
from pathlib import Path


FIRMWARE_LIB = Path(__file__).resolve().parents[1] / "firmware" / "lib"
if str(FIRMWARE_LIB) not in sys.path:
    sys.path.insert(0, str(FIRMWARE_LIB))

import oi_session_ui as ui


class FirmwareSessionUiCase(unittest.TestCase):
    def test_sessions_summary_handles_missing_and_active_selection(self):
        self.assertEqual(ui.sessions_summary(None), (None, []))
        state = {
            "sessions": {
                "active_session_id": "s2",
                "sessions": [{"session_id": "s1"}, {"session_id": "s2"}],
            }
        }
        active, sessions = ui.sessions_summary(state)
        self.assertEqual(active, "s2")
        self.assertEqual(ui.selected_index_for_active(sessions, active), 1)
        self.assertEqual(ui.selected_index_for_active(sessions, "missing"), 0)

    def test_wrap_and_labels(self):
        self.assertEqual(ui.wrap_index(-1, 3), 2)
        self.assertEqual(ui.wrap_index(3, 3), 0)
        self.assertEqual(ui.visible_window_start(1, 2, 5), 0)
        self.assertEqual(ui.visible_window_start(4, 10, 3), 4)
        self.assertEqual(ui.visible_window_start(9, 10, 3), 7)
        self.assertEqual(ui.session_label({"name": "repo", "session_id": "s1"}), "repo")
        self.assertEqual(ui.session_label({"session_id": "s1"}), "s1")
        self.assertEqual(ui.session_status({"status": "running", "pending_count": 2}), "running p:2")
        self.assertEqual(ui.session_status({"status": "running", "stale": True}), "offline")
        self.assertEqual(ui.session_status({"status": "running", "stale": True, "last_seen_age_s": 125}), "offline 2m")
        self.assertEqual(ui._age_label(12), "12s")
        self.assertEqual(ui._age_label(120), "2m")
        self.assertEqual(ui._age_label(7200), "2h")

    def test_command_payloads_are_bridge_compatible(self):
        # Verify the extended menu includes all tier-D commands
        verbs = [ui.command_payload("s1", i)["verb"] for i in range(ui.command_count())]
        self.assertIn("abort", verbs)
        self.assertIn("abort_retry", verbs)
        self.assertIn("cycle_model", verbs)
        self.assertIn("cycle_thinking_level", verbs)
        self.assertIn("prompt", verbs)
        self.assertIn("compact", verbs)
        self.assertLessEqual(ui.command_count(), 12)

        # spot-check a few entries dispatch correctly
        prompt = ui.command_payload("s1", 4)  # first "prompt OK"
        self.assertEqual(prompt["verb"], "prompt")
        self.assertEqual(prompt["args"]["message"], "Reply with exactly: OK")

        compact = ui.command_payload("s1", 7)  # "compact"
        self.assertEqual(compact["verb"], "compact")

        retry = ui.command_payload("s1", 1)  # "retry" → abort_retry
        self.assertEqual(retry["verb"], "abort_retry")

        rpc_prompt = ui.rpc_command_payload("s1", 4)
        self.assertEqual(rpc_prompt, {"type": "prompt", "message": "Reply with exactly: OK"})

        rpc_compact = ui.rpc_command_payload("s1", 7)
        self.assertEqual(rpc_compact, {"type": "compact"})

        self.assertEqual(ui.command_payload("s1", ui.command_count())["verb"], "abort")

    def test_no_local_only_commands(self):
        for i in range(ui.command_count()):
            self.assertFalse(ui.command_is_local(i))

    def test_json_headers_adds_optional_token(self):
        self.assertEqual(ui.json_headers(), {"Content-Type": "application/json"})
        self.assertEqual(
            ui.json_headers("secret"),
            {"Content-Type": "application/json", "Authorization": "Bearer secret"},
        )


if __name__ == "__main__":
    unittest.main()
