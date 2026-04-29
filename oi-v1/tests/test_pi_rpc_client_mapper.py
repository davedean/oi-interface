import sys
import unittest
from pathlib import Path


FIRMWARE_LIB = Path(__file__).resolve().parents[1] / "firmware" / "lib"
if str(FIRMWARE_LIB) not in sys.path:
    sys.path.insert(0, str(FIRMWARE_LIB))

from pi_rpc_client import PiRpcStateMapper


class PiRpcStateMapperCase(unittest.TestCase):
    def test_streaming_text_delta_updates_snapshot(self):
        mapper = PiRpcStateMapper()

        mapper.handle_messages([
            {"type": "message_update", "assistantMessageEvent": {"type": "text_start", "contentIndex": 1}},
            {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "contentIndex": 1, "delta": "Hel"}},
            {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "contentIndex": 1, "delta": "lo"}},
            {"type": "message_update", "assistantMessageEvent": {"type": "text_end", "contentIndex": 1, "content": ""}},
        ])

        snap = mapper.state()["snapshot"]
        self.assertIsNotNone(snap)
        self.assertEqual(snap["msg"], "Hello")
        self.assertIsInstance(snap["ts"], int)

    def test_message_end_extracts_assistant_text(self):
        mapper = PiRpcStateMapper()

        mapper.handle_messages([
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "..."},
                        {"type": "text", "text": "OK"},
                    ],
                },
            }
        ])

        snap = mapper.state()["snapshot"]
        self.assertEqual(snap["msg"], "OK")

    def test_agent_events_update_session_status(self):
        mapper = PiRpcStateMapper()

        mapper.handle_messages([
            {
                "type": "response",
                "command": "get_state",
                "success": True,
                "data": {
                    "sessionId": "s1",
                    "sessionName": "test",
                    "isStreaming": False,
                    "pendingMessageCount": 0,
                },
            }
        ])

        mapper.handle_messages([{"type": "agent_start"}])
        self.assertEqual(mapper.state()["sessions"]["sessions"][0]["status"], "streaming")

        mapper.handle_messages([{"type": "agent_end"}])
        self.assertEqual(mapper.state()["sessions"]["sessions"][0]["status"], "idle")

    def test_extension_ui_select_maps_prompt_and_answer_payload(self):
        mapper = PiRpcStateMapper()

        mapper.handle_messages([
            {
                "type": "extension_ui_request",
                "id": "ui-1",
                "method": "select",
                "title": "Approve bash?",
                "message": "pwd",
                "options": ["Approve", "Deny"],
            }
        ])

        state = mapper.state()
        self.assertEqual(state["id"], "ext-ui-1")
        self.assertEqual(state["title"], "Approve bash?")
        self.assertEqual(state["body"], "pwd")
        self.assertEqual(
            state["options"],
            [
                {"label": "Approve", "value": "Approve"},
                {"label": "Deny", "value": "Deny"},
            ],
        )

        payload = mapper.prompt_answer_payload("ext-ui-1", "Approve")
        self.assertEqual(
            payload,
            {"type": "extension_ui_response", "id": "ui-1", "value": "Approve"},
        )

    def test_prompt_answer_payload_rejects_mismatched_prompt_and_clear(self):
        mapper = PiRpcStateMapper()
        mapper.handle_messages([
            {
                "type": "extension_ui_request",
                "id": 42,
                "method": "confirm",
                "title": "Allow?",
                "message": "dangerous op",
            }
        ])

        self.assertIsNone(mapper.prompt_answer_payload("ext-999", "yes"))

        mapper.clear_prompt()
        state = mapper.state()
        self.assertIsNone(state["id"])
        self.assertIsNone(state["title"])
        self.assertIsNone(state["body"])
        self.assertEqual(state["options"], [])
        self.assertIsNone(mapper.prompt_answer_payload("ext-42", "yes"))


if __name__ == "__main__":
    unittest.main()
