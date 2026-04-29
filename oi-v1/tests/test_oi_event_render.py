import unittest
import sys
import os

# Ensure firmware/lib is on sys.path for the import
FIRMWARE_LIB = os.path.join(os.path.dirname(__file__), "..", "firmware", "lib")
FIRMWARE_LIB = os.path.abspath(FIRMWARE_LIB)
if FIRMWARE_LIB not in sys.path:
    sys.path.insert(0, FIRMWARE_LIB)

from oi_event_render import (
    render_agent_status,
    render_tool_status,
    render_queue_status,
    render_compaction_status,
    render_auto_retry_status,
    render_extension_error,
    render_idle_status_line,
)


class TestEventRender(unittest.TestCase):
    def test_render_agent_status_idle(self):
        self.assertEqual(render_agent_status({}), "")

    def test_render_agent_status_active(self):
        self.assertEqual(render_agent_status({"agent_active": True}), "thinking...")

    def test_render_tool_status_idle(self):
        self.assertEqual(render_tool_status({}), "")

    def test_render_tool_status_running(self):
        state = {"tool_executions": {"e1": {"name": "bash", "status": "running"}}}
        self.assertEqual(render_tool_status(state), "run: bash")

    def test_render_queue_status_idle(self):
        self.assertEqual(render_queue_status({}), "")

    def test_render_queue_status(self):
        state = {"queue_steering": ["s1"], "queue_follow_up": ["f1", "f2"]}
        self.assertEqual(render_queue_status(state), "q: 1 steer 2 follow")

    def test_render_compaction_status_idle(self):
        self.assertEqual(render_compaction_status({}), "")

    def test_render_compaction_status_active(self):
        self.assertEqual(render_compaction_status({"compaction_active": True}), "compact...")

    def test_render_auto_retry_status_idle(self):
        self.assertEqual(render_auto_retry_status({}), "")

    def test_render_auto_retry_status(self):
        state = {"auto_retry_active": True, "auto_retry_attempt": 2, "auto_retry_max_attempts": 3}
        self.assertEqual(render_auto_retry_status(state), "retry 2/3")

    def test_render_extension_error_idle(self):
        self.assertEqual(render_extension_error({}), "")

    def test_render_extension_error(self):
        state = {"last_extension_error": {"error": "timeout"}}
        self.assertEqual(render_extension_error(state), "ERR: timeout")

    def test_render_idle_status_line_priority(self):
        state = {"agent_active": True, "last_extension_error": {"error": "x"}}
        self.assertEqual(render_idle_status_line(state), "ERR: x")

    def test_render_idle_status_line_empty(self):
        self.assertEqual(render_idle_status_line({}), "")


if __name__ == "__main__":
    unittest.main()
