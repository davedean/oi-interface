"""
Oi-Sim Streaming REPL - Interactive virtual device with real-time agent text streaming.

Extends the basic REPL to display agent responses as they stream in,
rather than waiting for the complete response.
"""

from __future__ import annotations

import asyncio
from typing import Any

from sim.repl import OiSimREPL

HELP_TEXT = """
Commands:
  hold        - Long press (start recording)
  release     - Release button (stop recording)
  tap         - Short button press
  double      - Double tap
  mute        - Very long hold (mute)
  text <msg>  - Send text prompt to agent (shows streaming response!)
  ask <msg>   - Same as text (alias)
  play [id]   - Start audio playback (default: latest)
  stop        - Stop audio playback
  battery N   - Send battery N%
  charging    - charging start|stop
  wifi N      - Send wifi RSSI N
  connect     - Connect to gateway
  disconnect  - Disconnect
  state       - Show device state
  events      - Show event history (includes agent text deltas)
  help        - Show this help
  quit        - Exit

Streaming: Agent responses appear in real-time as the text streams in!
""".strip()


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
        self.streaming_active = False
        self.current_response_text = ""

    async def _receive_loop(self):
        """Background task to receive and display messages from gateway."""
        while self.running and self.sim:
            await asyncio.sleep(0.1)
            commands = self.sim.received_commands
            if len(commands) > self._printed_command_count:
                for command in commands[self._printed_command_count:]:
                    self._print_streaming_command(command)
                self._printed_command_count = len(commands)

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
        if msg_type == "event" and payload.get("event") == "agent_response_delta":
            text = payload.get("text_delta", "")[:50]
            return f"  {index}. 📤 agent_response_delta: '{text}'..."
        return super()._format_message_history_entry(index, msg)

    async def _cmd_text(self, args):
        """Send a text prompt to the agent and display streaming response."""
        assert self.sim is not None
        if not args:
            self._print_text_prompt_usage()
            return
        text = " ".join(args)
        self.current_response_text = ""

        await self.sim.send_text_prompt(text)
        print(f'📤 text.prompt (text="{text}")')
        print(f"📥 State: {self.sim.state.value}")
        print("\n💬 Agent: ", end="", flush=True)


async def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Oi-Sim Streaming REPL - Interactive virtual device")
    parser.add_argument("--gateway", default="ws://localhost:8787/datp", help="Gateway WebSocket URL")
    parser.add_argument("--device-id", default="oi-sim-repl-001", help="Device ID")
    args = parser.parse_args()

    repl = StreamingOiSimREPL(gateway=args.gateway, device_id=args.device_id)
    await repl.start()


if __name__ == "__main__":
    asyncio.run(main())
