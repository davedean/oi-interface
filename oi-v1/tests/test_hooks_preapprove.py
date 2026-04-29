import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock


HOOKS_DIR = Path(__file__).resolve().parents[1] / "hooks"
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

import preapprove


class FakeOi:
    def __init__(self, pick="approve", fail=False):
        self.pick = pick
        self.fail = fail
        self.calls = []

    def register_session(self, **kwargs):
        self.calls.append(("register_session", kwargs))
        if self.fail:
            raise RuntimeError("server down")
        return {"session_id": kwargs["session_id"]}

    def approve_session(self, *args, **kwargs):
        self.calls.append(("approve_session", args, kwargs))
        if self.fail:
            raise RuntimeError("server down")
        return self.pick

    def approve(self, *args, **kwargs):
        self.calls.append(("approve", args, kwargs))
        if self.fail:
            raise RuntimeError("server down")
        return self.pick


class PreapproveHookCase(unittest.TestCase):
    def run_hook(self, payload, fake_oi):
        stdin = io.StringIO(json.dumps(payload))
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.dict(sys.modules, {"oi": fake_oi}), \
                mock.patch("sys.stdin", stdin), \
                mock.patch("sys.stdout", stdout), \
                mock.patch("sys.stderr", stderr):
            with self.assertRaises(SystemExit) as cm:
                preapprove.main()
        return cm.exception.code, stdout.getvalue(), stderr.getvalue(), fake_oi.calls

    def decision(self, stdout):
        return json.loads(stdout)["hookSpecificOutput"]["permissionDecision"]

    def test_session_approval_uses_session_id_and_tool_use_id(self):
        fake = FakeOi("approve")
        code, stdout, stderr, calls = self.run_hook({
            "session_id": "s1",
            "tool_use_id": "t1",
            "tool_name": "Bash",
            "tool_input": {"command": "pytest"},
            "cwd": "/repo",
        }, fake)
        self.assertEqual(code, 0)
        self.assertEqual(self.decision(stdout), "allow")
        self.assertEqual(calls[0][0], "register_session")
        self.assertEqual(calls[0][1]["session_id"], "s1")
        self.assertEqual(calls[0][1]["cwd"], "/repo")
        self.assertEqual(calls[1][0], "approve_session")
        self.assertEqual(calls[1][1][0], "s1")
        self.assertEqual(calls[1][2]["tool_use_id"], "t1")

    def test_deny_and_notes_decisions(self):
        code, stdout, _, _ = self.run_hook({"session_id": "s1", "tool_name": "Edit", "tool_input": {}}, FakeOi("deny"))
        self.assertEqual(self.decision(stdout), "deny")
        code, stdout, _, _ = self.run_hook({"session_id": "s1", "tool_name": "Edit", "tool_input": {}}, FakeOi("notes"))
        self.assertEqual(self.decision(stdout), "ask")

    def test_missing_session_falls_back_to_legacy_approve(self):
        fake = FakeOi("approve")
        code, stdout, _, calls = self.run_hook({"tool_name": "Bash", "tool_input": {"command": "ls"}}, fake)
        self.assertEqual(self.decision(stdout), "allow")
        self.assertEqual(calls[0][0], "approve")

    def test_server_failure_fail_opens_with_no_stdout(self):
        code, stdout, stderr, calls = self.run_hook({
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
        }, FakeOi(fail=True))
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertIn("fail-open", stderr)


if __name__ == "__main__":
    unittest.main()
