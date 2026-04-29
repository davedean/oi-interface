import sys
import unittest
from pathlib import Path
from unittest import mock


AGENT_DIR = Path(__file__).resolve().parents[1] / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import pi_bridge


class FakeRpc:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def call(self, payload):
        self.calls.append(payload)
        if self.fail:
            raise RuntimeError("rpc boom")
        return {"type": "response", "success": True, "command": payload["type"]}


class PiBridgeCase(unittest.TestCase):
    def test_rpc_payload_mapping(self):
        self.assertEqual(pi_bridge.rpc_payload_for_command({"verb": "status"}), {"type": "get_state"})
        self.assertEqual(pi_bridge.rpc_payload_for_command({"verb": "abort"}), {"type": "abort"})
        self.assertEqual(
            pi_bridge.rpc_payload_for_command({"verb": "follow_up", "args": {"message": "later"}}),
            {"type": "follow_up", "message": "later"},
        )
        with self.assertRaises(ValueError):
            pi_bridge.rpc_payload_for_command({"verb": "shell", "args": {"command": "rm -rf /"}})
        with self.assertRaises(ValueError):
            pi_bridge.rpc_payload_for_command({"verb": "steer", "args": {}})

    def test_execute_command_calls_rpc(self):
        rpc = FakeRpc()
        result = pi_bridge.execute_command(rpc, {"verb": "steer", "args": {"message": "stop"}})
        self.assertEqual(rpc.calls, [{"type": "steer", "message": "stop"}])
        self.assertTrue(result["success"])

    def test_speak_verb_handled_locally_not_via_rpc(self):
        rpc = FakeRpc()
        with mock.patch.object(pi_bridge.oi, "speak") as mock_speak:
            mock_speak.return_value = {"ok": True, "speak_seq": 1}
            result = pi_bridge.execute_command(rpc, {"verb": "speak", "args": {"message": "hello"}})
        mock_speak.assert_called_once_with("hello")
        self.assertEqual(rpc.calls, [])  # no RPC call
        self.assertTrue(result["ok"])

    def test_speak_verb_in_allowed_verbs(self):
        self.assertIn("speak", pi_bridge.ALLOWED_VERBS)

    def test_speak_requires_message(self):
        with self.assertRaises(ValueError):
            pi_bridge.execute_command(FakeRpc(), {"verb": "speak", "args": {}})

    def test_bridge_once_acks_success_and_fails_errors(self):
        commands = [
            {"command_id": "c-1", "seq": 1, "verb": "status", "args": {}},
            {"command_id": "c-2", "seq": 2, "verb": "steer", "args": {}},
        ]
        acked = []
        failed = []
        with mock.patch.object(pi_bridge.oi, "poll_commands", return_value=commands), \
                mock.patch.object(pi_bridge.oi, "ack_command", side_effect=lambda cid, result=None: acked.append((cid, result))), \
                mock.patch.object(pi_bridge.oi, "fail_command", side_effect=lambda cid, error: failed.append((cid, str(error)))):
            latest = pi_bridge.bridge_once("s1", FakeRpc(), after_seq=0)
        self.assertEqual(latest, 2)
        self.assertEqual(acked[0][0], "c-1")
        self.assertEqual(failed[0][0], "c-2")
        self.assertIn("requires args.message", failed[0][1])


if __name__ == "__main__":
    unittest.main()
