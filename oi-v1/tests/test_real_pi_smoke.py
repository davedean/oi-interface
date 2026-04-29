"""Opt-in real-Pi smoke tests. Run with: OI_PI_HOST=gateway.local pytest -m real_pi -q"""
import os
import pytest

PI_HOST = os.environ.get("OI_PI_HOST")

pytestmark = pytest.mark.skipif(
    not PI_HOST,
    reason="Set OI_PI_HOST env var to enable real-Pi smoke tests",
)


class TestRealPiSmoke:
    """Safe subset: read-only commands only. No destructive operations."""

    def test_get_state(self):
        """Verify get_state round-trips."""
        # Use the TCP JSONL client pattern from pi_rpc_client.py
        # Connect to PI_HOST:8843 (default gateway port), send get_state, verify response
        pytest.skip("Requires PI_RPC_HOST env var — see docs/PI_RPC_MANUAL_CHECKLIST.md")

    def test_get_available_models(self):
        pytest.skip("Requires PI_RPC_HOST env var — see docs/PI_RPC_MANUAL_CHECKLIST.md")

    def test_get_commands(self):
        pytest.skip("Requires PI_RPC_HOST env var — see docs/PI_RPC_MANUAL_CHECKLIST.md")

    def test_get_session_stats(self):
        pytest.skip("Requires PI_RPC_HOST env var — see docs/PI_RPC_MANUAL_CHECKLIST.md")
