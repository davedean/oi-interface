"""Drive fake_pi_rpc.ts against each wire fixture and verify exit 0."""
import json
import os
import subprocess
import unittest

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "pi-rpc-wire")
REPO_ROOT = os.path.dirname(os.path.dirname(__file__))


class FakePeerMatrix(unittest.TestCase):
    """Note: These tests verify the fake peer itself works (can load and run scenarios).

    Full matrix coverage is exercised by Step 7.1 agent-brief fixture addition.
    """

    # ===== EXISTING TESTS =====

    def test_fake_peer_loads_get_state_scenario(self):
        """Verify fake peer can load and process the get_state scenario."""
        scenario = os.path.join(FIXTURES_DIR, "example_get_state.jsonl")
        # Scenario has an expect line, so we must send a matching message
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input=b'{"type": "get_state", "id": "req-1"}\n',
            capture_output=True,
            timeout=15,
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())
        # Verify the fake peer emitted a response
        self.assertIn(b"response", result.stdout)

    def test_fake_peer_loads_agent_start_scenario(self):
        """Verify fake peer can load and process the agent_start scenario."""
        scenario = os.path.join(FIXTURES_DIR, "agent_start.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input="",
            capture_output=True,
            timeout=15,
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_agent_end_scenario(self):
        """Verify fake peer can load and process the agent_end scenario."""
        scenario = os.path.join(FIXTURES_DIR, "agent_end.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input="",
            capture_output=True,
            timeout=15,
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_message_update_scenario(self):
        """Verify fake peer can load and process the message_update scenario."""
        scenario = os.path.join(FIXTURES_DIR, "message_update.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input="",
            capture_output=True,
            timeout=15,
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_tool_execution_start_scenario(self):
        """Verify fake peer can load and process the tool_execution_start scenario."""
        scenario = os.path.join(FIXTURES_DIR, "tool_execution_start.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input="",
            capture_output=True,
            timeout=15,
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_tool_execution_end_scenario(self):
        """Verify fake peer can load and process the tool_execution_end scenario."""
        scenario = os.path.join(FIXTURES_DIR, "tool_execution_end.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input="",
            capture_output=True,
            timeout=15,
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_compaction_start_scenario(self):
        """Verify fake peer can load and process the compaction_start scenario."""
        scenario = os.path.join(FIXTURES_DIR, "compaction_start.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input="",
            capture_output=True,
            timeout=15,
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_auto_retry_start_scenario(self):
        """Verify fake peer can load and process the auto_retry_start scenario."""
        scenario = os.path.join(FIXTURES_DIR, "auto_retry_start.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input="",
            capture_output=True,
            timeout=15,
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_extension_error_scenario(self):
        """Verify fake peer can load and process the extension_error scenario."""
        scenario = os.path.join(FIXTURES_DIR, "extension_error.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input="",
            capture_output=True,
            timeout=15,
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_ext_ui_notify_scenario(self):
        """Verify fake peer can load and process the ext_ui_notify scenario."""
        scenario = os.path.join(FIXTURES_DIR, "ext_ui_notify.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input="",
            capture_output=True,
            timeout=15,
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    # ===== NEW EMIT-ONLY TESTS (fire-and-forget, no stdin needed) =====

    def test_fake_peer_loads_AUTO_RETRY_END_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "auto_retry_end.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input="", capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_COMPACTION_END_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "compaction_end.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input="", capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_MESSAGE_END_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "message_end.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input="", capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_MESSAGE_START_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "message_start.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input="", capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_QUEUE_UPDATE_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "queue_update.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input="", capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_TOOL_EXECUTION_UPDATE_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "tool_execution_update.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input="", capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_TURN_START_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "turn_start.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input="", capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_TURN_END_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "turn_end.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input="", capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_EXT_UI_SET_EDITOR_TEXT_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "ext_ui_set_editor_text.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input="", capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_EXT_UI_SET_TITLE_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "ext_ui_setTitle.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input="", capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_EXT_UI_SET_WIDGET_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "ext_ui_setWidget.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input="", capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    # ===== NEW COMMAND TESTS (expect line → send matching JSON) =====

    def test_fake_peer_loads_ABORT_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "abort.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input=(json.dumps({"type": "abort", "id": "req-1"}) + "\n").encode(),
            capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_ABORT_BASH_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "abort_bash.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input=(json.dumps({"type": "abort_bash", "id": "req-1"}) + "\n").encode(),
            capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_ABORT_RETRY_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "abort_retry.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input=(json.dumps({"type": "abort_retry", "id": "req-1"}) + "\n").encode(),
            capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_BASH_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "bash.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input=(json.dumps({"type": "bash", "id": "req-1", "command": "pwd"}) + "\n").encode(),
            capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_CLONE_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "clone.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input=(json.dumps({"type": "clone", "id": "req-1"}) + "\n").encode(),
            capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_COMPACT_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "compact.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input=(json.dumps({"type": "compact", "id": "req-1"}) + "\n").encode(),
            capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_CYCLE_MODEL_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "cycle_model.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input=(json.dumps({"type": "cycle_model", "id": "req-1"}) + "\n").encode(),
            capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_CYCLE_THINKING_LEVEL_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "cycle_thinking_level.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input=(json.dumps({"type": "cycle_thinking_level", "id": "req-1"}) + "\n").encode(),
            capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_EXPORT_HTML_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "export_html.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input=(json.dumps({"type": "export_html", "id": "req-1", "outputPath": "/tmp/session.html"}) + "\n").encode(),
            capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_FOLLOW_UP_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "follow_up.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input=(json.dumps({"type": "follow_up", "id": "req-1", "message": "After you're done, also summarize the changes"}) + "\n").encode(),
            capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_FORK_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "fork.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input=(json.dumps({"type": "fork", "id": "req-1", "entryId": "entry-1"}) + "\n").encode(),
            capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_GET_AVAILABLE_MODELS_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "get_available_models.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input=(json.dumps({"type": "get_available_models", "id": "req-1"}) + "\n").encode(),
            capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_GET_COMMANDS_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "get_commands.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input=(json.dumps({"type": "get_commands", "id": "req-1"}) + "\n").encode(),
            capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_GET_FORK_MESSAGES_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "get_fork_messages.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input=(json.dumps({"type": "get_fork_messages", "id": "req-1"}) + "\n").encode(),
            capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_GET_LAST_ASSISTANT_TEXT_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "get_last_assistant_text.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input=(json.dumps({"type": "get_last_assistant_text", "id": "req-1"}) + "\n").encode(),
            capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_GET_MESSAGES_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "get_messages.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input=(json.dumps({"type": "get_messages", "id": "req-1"}) + "\n").encode(),
            capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_GET_SESSION_STATS_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "get_session_stats.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input=(json.dumps({"type": "get_session_stats", "id": "req-1"}) + "\n").encode(),
            capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_NEW_SESSION_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "new_session.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input=(json.dumps({"type": "new_session", "id": "req-1"}) + "\n").encode(),
            capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_PROMPT_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "prompt.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input=(json.dumps({"type": "prompt", "id": "req-1", "message": "hello"}) + "\n").encode(),
            capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_SET_AUTO_COMPACTION_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "set_auto_compaction.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input=(json.dumps({"type": "set_auto_compaction", "id": "req-1", "enabled": True}) + "\n").encode(),
            capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_SET_AUTO_RETRY_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "set_auto_retry.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input=(json.dumps({"type": "set_auto_retry", "id": "req-1", "enabled": True}) + "\n").encode(),
            capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_SET_FOLLOW_UP_MODE_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "set_follow_up_mode.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input=(json.dumps({"type": "set_follow_up_mode", "id": "req-1", "mode": "all"}) + "\n").encode(),
            capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_SET_MODEL_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "set_model.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input=(json.dumps({"type": "set_model", "id": "req-1", "provider": "anthropic", "modelId": "claude-sonnet-4-20250514"}) + "\n").encode(),
            capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_SET_SESSION_NAME_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "set_session_name.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input=(json.dumps({"type": "set_session_name", "id": "req-1", "name": "my-feature-work"}) + "\n").encode(),
            capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_SET_STEERING_MODE_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "set_steering_mode.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input=(json.dumps({"type": "set_steering_mode", "id": "req-1", "mode": "one-at-a-time"}) + "\n").encode(),
            capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_SET_THINKING_LEVEL_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "set_thinking_level.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input=(json.dumps({"type": "set_thinking_level", "id": "req-1", "level": "high"}) + "\n").encode(),
            capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_STEER_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "steer.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input=(json.dumps({"type": "steer", "id": "req-1", "message": "Stop and focus on error handling instead"}) + "\n").encode(),
            capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_SWITCH_SESSION_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "switch_session.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input=(json.dumps({"type": "switch_session", "id": "req-1", "sessionPath": "/tmp/other-session.jsonl"}) + "\n").encode(),
            capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    # ===== NEW UI DIALOG TESTS (emit extension_ui_request, expect extension_ui_response) =====

    def test_fake_peer_loads_EXT_UI_CONFIRM_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "ext_ui_confirm.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input=(json.dumps({"type": "extension_ui_response", "id": "req-2", "confirmed": True}) + "\n").encode(),
            capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_EXT_UI_EDITOR_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "ext_ui_editor.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input=(json.dumps({"type": "extension_ui_response", "id": "req-1", "value": "Edited Line 1\nEdited Line 2\nLine 3"}) + "\n").encode(),
            capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_EXT_UI_INPUT_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "ext_ui_input.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input=(json.dumps({"type": "extension_ui_response", "id": "req-1", "value": "hello world"}) + "\n").encode(),
            capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_EXT_UI_SELECT_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "ext_ui_select.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input=(json.dumps({"type": "extension_ui_response", "id": "req-1", "value": "a"}) + "\n").encode(),
            capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fake_peer_loads_EXT_UI_SET_STATUS_scenario(self):
        scenario = os.path.join(FIXTURES_DIR, "ext_ui_setStatus.jsonl")
        result = subprocess.run(
            ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario],
            input="",
            capture_output=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.decode())

    def test_fixture_count(self):
        """Verify we have at least 50 fixture scenarios."""
        fixtures = [f for f in os.listdir(FIXTURES_DIR) if f.endswith(".jsonl")]
        self.assertGreaterEqual(
            len(fixtures), 50, f"Expected ≥50 fixtures, found {len(fixtures)}: {fixtures}"
        )


if __name__ == "__main__":
    unittest.main()
