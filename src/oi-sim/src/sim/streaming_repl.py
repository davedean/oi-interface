"""
Oi-Sim Streaming REPL - Interactive virtual device with real-time agent text streaming.

Extends the basic REPL to display agent responses as they stream in,
rather than waiting for the complete response.
"""

from __future__ import annotations

import asyncio
from typing import Any

from sim.repl import OiSimREPL, run_repl_app

HELP_TEXT = OiSimREPL.help_text.replace(
    "text <msg>  - Send text prompt to agent",
    "text <msg>  - Send text prompt to agent (shows streaming response!)",
).replace(
    "events      - Show event history",
    "events      - Show event history (includes agent text deltas)",
) + "\n\nStreaming: Agent responses appear in real-time as the text streams in!"


class StreamingOiSimREPL(OiSimREPL):
    """Interactive REPL for OiSim with live agent text streaming."""

    event_history_limit = 20
    help_text = HELP_TEXT

    def __init__(
        self,
        gateway: str = "ws://localhost:8787/datp",
        device_id: str = "oi-sim-repl-001",
    ):
        super().__init__(gateway=gateway, device_id=device_id)
        self.current_response_text = ""

    def _live_command_printer(self, command: dict[str, Any]) -> None:
        """Print a command received during the live streaming REPL session."""
        self._print_streaming_command(command)

    def _print_streaming_command(self, command: dict[str, Any]) -> None:
        """Print a received command, handling streamed text specially."""
        op = command.get("op", "unknown")
        args = command.get("args", {})

        if op == "display.show_progress":
            text = args.get("text", "")
            if text:
                print(f"⚙️  {text}")
            return

        if op == "display.show_response_delta":
            text_delta = args.get("text_delta", "")
            is_final = args.get("is_final", False)
            stripped = text_delta.strip()
            is_progress = (
                stripped.startswith("[")
                and "]" in stripped
                and text_delta.startswith("\n")
            )

            if text_delta:
                if is_progress:
                    print(f"⚙️  {stripped}")
                else:
                    self.current_response_text += text_delta
                    print(text_delta, end="", flush=True)

            if is_final:
                print()
                self.current_response_text = ""
            return

        self._print_command(command, leading_newline=True)

    def _format_message_history_entry(self, index: int, msg: dict[str, Any]) -> str:
        """Format a single event-history row with streamed text previews."""
        msg_type = msg.get("type", "?")
        payload = msg.get("payload", {})
        if msg_type == "command" and payload.get("op") == "display.show_response_delta":
            text = payload.get("args", {}).get("text_delta", "")[:50]
            return f"  {index}. 📥 display.show_response_delta: '{text}'..."
        if msg_type == "event" and payload.get("event") == "agent_response_delta":
            text = payload.get("text_delta", "")[:50]
            return f"  {index}. 📤 agent_response_delta: '{text}'..."
        return super()._format_message_history_entry(index, msg)

    def _after_text_prompt_sent(self, text: str) -> None:
        """Reset the streaming buffer and show the streaming response prompt."""
        del text
        self.current_response_text = ""
        print("\n💬 Agent: ", end="", flush=True)


async def main():
    """Main entry point."""
    await run_repl_app(
        StreamingOiSimREPL,
        "Oi-Sim Streaming REPL - Interactive virtual device",
    )


if __name__ == "__main__":
    asyncio.run(main())
