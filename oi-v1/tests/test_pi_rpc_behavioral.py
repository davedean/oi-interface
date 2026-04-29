"""
Behavioral contract tests for Pi RPC parity.

Each test verifies a specific wire-shape or protocol invariant called out
in the Pi RPC parity plan. No running Pi server is required — all tests
exercise the pure builders/handlers in firmware/lib/.

Coverage targets:
1. Prompt streaming conflict (streamingBehavior only on prompt)
2. Prompt with images (ImageContent wire shape)
3. Steer command shape (never includes streamingBehavior)
4. Abort idempotency (identical wire shapes across calls)
5. Switch_session shape (sessionPath field)
6. Bash + abort_bash sequence (independent wire shapes)
7. Fork and clone shapes (entryId on fork, bare type on clone)
8. Extension UI response shapes (value / confirmed / cancelled)
9. Casing trap (UI_METHOD_HANDLERS key names)
"""

import sys
import unittest
from pathlib import Path

# Import from firmware/lib using the same pattern as test_pi_rpc_inventory.py
FIRMWARE_LIB = Path(__file__).resolve().parents[1] / "firmware" / "lib"
if str(FIRMWARE_LIB) not in sys.path:
    sys.path.insert(0, str(FIRMWARE_LIB))

from pi_rpc_commands import COMMAND_BUILDERS, build_command
from pi_rpc_protocol import (
    UI_METHOD_HANDLERS,
    build_extension_ui_response,
)
from pi_rpc_events import project_message_update, project_message_end


# ============================================================================
# 1. Prompt streaming conflict
# ============================================================================

class TestPromptStreamingConflict(unittest.TestCase):
    """streamingBehavior is only valid on the prompt command.

    The Pi server checks for this field server-side to reject conflicting
    prompts during streaming, but the client builder must support the
    optional field while correctly omitting it from non-prompt commands.
    """

    def test_prompt_without_streaming_behavior(self):
        """Prompt command WITHOUT streamingBehavior produces correct wire shape."""
        cmd = COMMAND_BUILDERS["prompt"]("prompt", message="Hello world")
        self.assertEqual(cmd["type"], "prompt")
        self.assertEqual(cmd["message"], "Hello world")
        self.assertNotIn("streamingBehavior", cmd)

    def test_prompt_with_streaming_behavior_steer(self):
        """Prompt command WITH streamingBehavior='steer' includes it."""
        cmd = COMMAND_BUILDERS["prompt"](
            "prompt", message="New instruction", streamingBehavior="steer",
        )
        self.assertEqual(cmd["type"], "prompt")
        self.assertEqual(cmd["message"], "New instruction")
        self.assertIn("streamingBehavior", cmd)
        self.assertEqual(cmd["streamingBehavior"], "steer")

    def test_prompt_with_streaming_behavior_follow_up(self):
        """Prompt command WITH streamingBehavior='followUp' includes it."""
        cmd = COMMAND_BUILDERS["prompt"](
            "prompt", message="Wait for me", streamingBehavior="followUp",
        )
        self.assertEqual(cmd["streamingBehavior"], "followUp")

    def test_build_command_helper_accepts_streaming_behavior(self):
        """The build_command() convenience wrapper passes through streamingBehavior."""
        cmd = build_command("prompt", message="hi", streamingBehavior="steer")
        self.assertEqual(cmd["streamingBehavior"], "steer")


# ============================================================================
# 2. Prompt with images
# ============================================================================

class TestPromptWithImages(unittest.TestCase):
    """Images field uses the ImageContent wire shape from the Pi RPC spec."""

    def test_prompt_with_single_image(self):
        images = [
            {
                "type": "image",
                "data": "base64data",
                "mimeType": "image/png",
            }
        ]
        cmd = COMMAND_BUILDERS["prompt"](
            "prompt", message="What's in this?", images=images,
        )
        self.assertEqual(cmd["type"], "prompt")
        self.assertEqual(cmd["message"], "What's in this?")
        self.assertIn("images", cmd)
        self.assertEqual(len(cmd["images"]), 1)
        self.assertEqual(cmd["images"][0]["type"], "image")
        self.assertEqual(cmd["images"][0]["data"], "base64data")
        self.assertEqual(cmd["images"][0]["mimeType"], "image/png")

    def test_prompt_with_multiple_images(self):
        images = [
            {"type": "image", "data": "data1", "mimeType": "image/png"},
            {"type": "image", "data": "data2", "mimeType": "image/jpeg"},
        ]
        cmd = COMMAND_BUILDERS["prompt"](
            "prompt", message="Compare these", images=images,
        )
        self.assertEqual(len(cmd["images"]), 2)
        self.assertEqual(cmd["images"][1]["mimeType"], "image/jpeg")

    def test_prompt_without_images_omits_field(self):
        """No images → no images key in the wire shape."""
        cmd = COMMAND_BUILDERS["prompt"]("prompt", message="Text only")
        self.assertNotIn("images", cmd)


# ============================================================================
# 3. Steer command shape
# ============================================================================

class TestSteerCommand(unittest.TestCase):
    """Steer is always a steering message — it must NOT carry streamingBehavior.

    The RPC spec defines steer as:
        {"type": "steer", "message": "..."}
    with an optional images field, but never streamingBehavior.
    """

    def test_steer_basic_shape(self):
        cmd = COMMAND_BUILDERS["steer"](
            "steer", message="Stop and do this instead",
        )
        self.assertEqual(cmd["type"], "steer")
        self.assertEqual(cmd["message"], "Stop and do this instead")
        self.assertNotIn("streamingBehavior", cmd)

    def test_steer_with_images(self):
        images = [
            {"type": "image", "data": "imgdata", "mimeType": "image/png"},
        ]
        cmd = COMMAND_BUILDERS["steer"](
            "steer", message="Look at this instead", images=images,
        )
        self.assertEqual(cmd["type"], "steer")
        self.assertEqual(cmd["message"], "Look at this instead")
        self.assertIn("images", cmd)
        self.assertNotIn("streamingBehavior", cmd)

    def test_steer_never_gets_streaming_behavior_even_if_passed(self):
        """Even if streamingBehavior kwarg is passed to steer, it must not appear."""
        cmd = COMMAND_BUILDERS["steer"](
            "steer", message="redirect", streamingBehavior="steer",
        )
        self.assertNotIn("streamingBehavior", cmd)


# ============================================================================
# 4. Abort idempotency
# ============================================================================

class TestAbortIdempotency(unittest.TestCase):
    """Two abort commands must produce identical wire shapes.

    Abort is a pure signal — no accumulated state between calls.
    """

    def test_abort_idempotent(self):
        cmd1 = COMMAND_BUILDERS["abort"]("abort")
        cmd2 = COMMAND_BUILDERS["abort"]("abort")
        self.assertEqual(cmd1, cmd2)

    def test_abort_wire_shape(self):
        cmd = COMMAND_BUILDERS["abort"]("abort")
        self.assertEqual(cmd["type"], "abort")
        self.assertEqual(len(cmd), 1)  # only the "type" key

    def test_abort_with_request_id(self):
        cmd = COMMAND_BUILDERS["abort"]("abort", id="req-42")
        self.assertEqual(cmd["type"], "abort")
        self.assertEqual(cmd["id"], "req-42")


# ============================================================================
# 5. Switch_session shape
# ============================================================================

class TestSwitchSessionShape(unittest.TestCase):
    """switch_session must include sessionPath in the wire shape.

    RPC spec: {"type":"switch_session","sessionPath":"/path/to/session.jsonl"}
    """

    def test_switch_session_with_path(self):
        cmd = COMMAND_BUILDERS["switch_session"](
            "switch_session", sessionPath="/home/user/sessions/foo.jsonl",
        )
        self.assertEqual(cmd["type"], "switch_session")
        self.assertIn("sessionPath", cmd)
        self.assertEqual(cmd["sessionPath"], "/home/user/sessions/foo.jsonl")

    def test_switch_session_without_path(self):
        """Bare switch_session (path optional) still has correct type."""
        cmd = COMMAND_BUILDERS["switch_session"]("switch_session")
        self.assertEqual(cmd["type"], "switch_session")
        self.assertNotIn("sessionPath", cmd)


# ============================================================================
# 6. Bash + abort_bash sequence
# ============================================================================

class TestBashAndAbortBash(unittest.TestCase):
    """Bash and abort_bash produce correct, independent wire shapes."""

    def test_bash_command(self):
        cmd = COMMAND_BUILDERS["bash"]("bash", command="pwd")
        self.assertEqual(cmd["type"], "bash")
        self.assertEqual(cmd["command"], "pwd")

    def test_bash_command_with_working_directory(self):
        cmd = COMMAND_BUILDERS["bash"](
            "bash", command="ls", workingDirectory="/tmp",
        )
        self.assertEqual(cmd["type"], "bash")
        self.assertEqual(cmd["command"], "ls")
        self.assertIn("workingDirectory", cmd)
        self.assertEqual(cmd["workingDirectory"], "/tmp")

    def test_abort_bash_command(self):
        cmd = COMMAND_BUILDERS["abort_bash"]("abort_bash")
        self.assertEqual(cmd["type"], "abort_bash")
        self.assertEqual(len(cmd), 1)  # only "type"

    def test_bash_and_abort_bash_independent(self):
        """Building both commands does not affect each other's output."""
        bash_cmd = COMMAND_BUILDERS["bash"]("bash", command="pwd")
        abort_cmd = COMMAND_BUILDERS["abort_bash"]("abort_bash")

        self.assertEqual(bash_cmd["type"], "bash")
        self.assertIn("command", bash_cmd)

        self.assertEqual(abort_cmd["type"], "abort_bash")
        self.assertNotIn("command", abort_cmd)


# ============================================================================
# 7. Fork and clone shapes
# ============================================================================

class TestForkAndCloneShapes(unittest.TestCase):
    """Fork includes entryId; clone is a bare type command."""

    def test_fork_with_entry_id(self):
        cmd = COMMAND_BUILDERS["fork"]("fork", entryId="abc123")
        self.assertEqual(cmd["type"], "fork")
        self.assertIn("entryId", cmd)
        self.assertEqual(cmd["entryId"], "abc123")

    def test_fork_without_entry_id(self):
        cmd = COMMAND_BUILDERS["fork"]("fork")
        self.assertEqual(cmd["type"], "fork")
        self.assertNotIn("entryId", cmd)

    def test_clone_shape(self):
        cmd = COMMAND_BUILDERS["clone"]("clone")
        self.assertEqual(cmd["type"], "clone")
        self.assertEqual(len(cmd), 1)  # only "type"

    def test_clone_with_request_id(self):
        cmd = COMMAND_BUILDERS["clone"]("clone", id="req-99")
        self.assertEqual(cmd["type"], "clone")
        self.assertEqual(cmd["id"], "req-99")


# ============================================================================
# 8. Extension UI response shapes
# ============================================================================

class TestExtensionUIResponseShapes(unittest.TestCase):
    """Verify exact JSON shapes for each extension_ui_response variant.

    Dialog methods (select/input/editor) → {"id":..., "value":...}
    Confirm → {"id":..., "confirmed": true/false}
    Cancellation → {"id":..., "cancelled": true}
    """

    # --- Value responses (select, input, editor) ---

    def test_select_value_response(self):
        resp = build_extension_ui_response("uuid-1", value="Allow")
        self.assertEqual(resp["type"], "extension_ui_response")
        self.assertEqual(resp["id"], "uuid-1")
        self.assertEqual(resp["value"], "Allow")
        self.assertNotIn("confirmed", resp)
        self.assertNotIn("cancelled", resp)

    def test_input_value_response(self):
        resp = build_extension_ui_response("uuid-3", value="hello world")
        self.assertEqual(resp["type"], "extension_ui_response")
        self.assertEqual(resp["id"], "uuid-3")
        self.assertEqual(resp["value"], "hello world")

    def test_editor_value_response(self):
        resp = build_extension_ui_response(
            "uuid-4", value="Line 1\nLine 2\nLine 3",
        )
        self.assertEqual(resp["type"], "extension_ui_response")
        self.assertEqual(resp["id"], "uuid-4")
        self.assertEqual(resp["value"], "Line 1\nLine 2\nLine 3")

    # --- Confirmation responses (confirm) ---

    def test_confirm_true_response(self):
        resp = build_extension_ui_response("uuid-2", confirmed=True)
        self.assertEqual(resp["type"], "extension_ui_response")
        self.assertEqual(resp["id"], "uuid-2")
        self.assertEqual(resp["confirmed"], True)
        self.assertNotIn("value", resp)
        self.assertNotIn("cancelled", resp)

    def test_confirm_false_response(self):
        resp = build_extension_ui_response("uuid-2", confirmed=False)
        self.assertEqual(resp["type"], "extension_ui_response")
        self.assertEqual(resp["id"], "uuid-2")
        self.assertIs(resp["confirmed"], False)

    # --- Cancellation responses ---

    def test_cancellation_response(self):
        resp = build_extension_ui_response("uuid-1", cancelled=True)
        self.assertEqual(resp["type"], "extension_ui_response")
        self.assertEqual(resp["id"], "uuid-1")
        self.assertIs(resp["cancelled"], True)
        self.assertNotIn("value", resp)
        self.assertNotIn("confirmed", resp)

    def test_cancellation_overrides_value(self):
        """Cancelled must not also include a value field."""
        resp = build_extension_ui_response("uuid-1", value="oops", cancelled=True)
        self.assertNotIn("value", resp)
        self.assertIs(resp["cancelled"], True)

    def test_cancellation_overrides_confirmed(self):
        """Cancelled must not also include a confirmed field."""
        resp = build_extension_ui_response("uuid-2", confirmed=True, cancelled=True)
        self.assertNotIn("confirmed", resp)
        self.assertIs(resp["cancelled"], True)

    # --- Type field present ---

    def test_all_responses_have_type_field(self):
        for resp in [
            build_extension_ui_response("u1", value="x"),
            build_extension_ui_response("u2", confirmed=True),
            build_extension_ui_response("u3", cancelled=True),
        ]:
            self.assertEqual(resp["type"], "extension_ui_response")


# ============================================================================
# 9. Casing trap
# ============================================================================

class TestCasingTrap(unittest.TestCase):
    """Guard against normalization of UI method handler keys.

    The Pi RPC spec uses exact casing:
      - "setStatus"    (not "set_status")
      - "setWidget"    (not "set_widget")
      - "setTitle"     (not "set_title")
      - "set_editor_text" (not "setEditorText")
    """

    def test_set_status_camel_case(self):
        self.assertIn(
            "setStatus", UI_METHOD_HANDLERS,
            "UI_METHOD_HANDLERS must have 'setStatus' (camelCase), not 'set_status'",
        )

    def test_set_widget_camel_case(self):
        self.assertIn(
            "setWidget", UI_METHOD_HANDLERS,
            "UI_METHOD_HANDLERS must have 'setWidget' (camelCase), not 'set_widget'",
        )

    def test_set_title_camel_case(self):
        self.assertIn(
            "setTitle", UI_METHOD_HANDLERS,
            "UI_METHOD_HANDLERS must have 'setTitle' (camelCase), not 'set_title'",
        )

    def test_set_editor_text_snake_case(self):
        self.assertIn(
            "set_editor_text", UI_METHOD_HANDLERS,
            "UI_METHOD_HANDLERS must have 'set_editor_text' (snake_case), not 'setEditorText'",
        )

    def test_wrong_casing_absent(self):
        """Normalized snake_case variants for camelCase methods must NOT exist."""
        self.assertNotIn("set_status", UI_METHOD_HANDLERS)
        self.assertNotIn("set_widget", UI_METHOD_HANDLERS)
        self.assertNotIn("set_title", UI_METHOD_HANDLERS)

    def test_wrong_casing_absent_setEditorText(self):
        """setEditorText must NOT be present — the key is set_editor_text."""
        self.assertNotIn("setEditorText", UI_METHOD_HANDLERS)

    def test_all_expected_ui_methods_present(self):
        """Full inventory of UI method handler keys."""
        expected = {
            "select", "confirm", "input", "editor",
            "notify", "setStatus", "setWidget", "setTitle",
            "set_editor_text",
        }
        self.assertEqual(set(UI_METHOD_HANDLERS.keys()), expected)


class TestLastAssistantText(unittest.TestCase):
    """Verify that last_assistant_text is captured from event projections."""

    def test_text_end_sets_last_assistant_text(self):
        state = {"current_text": ""}
        msg = {
            "type": "message_update",
            "messageId": "m1",
            "messageType": "assistant",
            "assistantMessageEvent": {
                "type": "text_end",
                "content": "The answer is 42."
            }
        }
        result = project_message_update(state, msg)
        self.assertEqual(result.get("last_assistant_text"), "The answer is 42.")

    def test_message_end_sets_last_assistant_text(self):
        state = {"current_text": "Hello world"}
        msg = {
            "type": "message_end",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "Hello world"}]}
        }
        result = project_message_end(state, msg)
        self.assertEqual(result.get("last_assistant_text"), "Hello world")

    def test_message_end_no_text_no_last_assistant_text(self):
        state = {}
        msg = {
            "type": "message_end",
            "message": {"role": "assistant", "content": ""}
        }
        result = project_message_end(state, msg)
        self.assertNotIn("last_assistant_text", result)


if __name__ == "__main__":
    unittest.main()
