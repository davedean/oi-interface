"""
Oi-Sim Streaming REPL - Interactive virtual device with real-time agent text streaming.

Extends the basic REPL to display agent responses as they stream in,
rather than waiting for the complete response.
"""

import asyncio
import shlex
import sys
from typing import Optional

from sim import OiSim
from sim.state import State
from sim.repl import OiSimREPL


class StreamingOiSimREPL(OiSimREPL):
    """Interactive REPL for OiSim with live agent text streaming."""

    def __init__(
        self,
        gateway: str = "ws://localhost:8787/datp",
        device_id: str = "oi-sim-repl-001",
    ):
        super().__init__(gateway=gateway, device_id=device_id)
        self.streaming_active = False
        self.current_response_text = ""

    async def _receive_loop(self):
        """Background task to receive and display messages from gateway.
        
        Extended to display agent text deltas in real-time.
        """
        while self.running and self.sim:
            await asyncio.sleep(0.1)
            
            # Check for agent_response_delta events (streaming text chunks)
            messages = self.sim.received_messages
            for msg in messages:
                if msg.get("type") == "event":
                    payload = msg.get("payload", {})
                    event = payload.get("event", "")
                    
                    # Display agent text deltas in real-time
                    if event == "agent_response_delta":
                        text_delta = payload.get("text_delta", "")
                        is_final = payload.get("is_final", False)
                        
                        if text_delta:
                            self.current_response_text += text_delta
                            # Print inline without newline for streaming effect
                            print(text_delta, end="", flush=True)
                        
                        if is_final:
                            print()  # Newline after final chunk
                            self.current_response_text = ""
            
            # Print each new command exactly once.
            commands = self.sim.received_commands
            if len(commands) > self._printed_command_count:
                new_commands = commands[self._printed_command_count:]
                for cmd in new_commands:
                    op = cmd.get("op", "unknown")
                    args = cmd.get("args", {})
                    print(f"\n📥 {op}")
                    if op == "display.show_card":
                        title = args.get("title", "")
                        body = args.get("body")
                        if title:
                            print(f"   title: {title}")
                        if body:
                            print(f"   body: {body}")
                self._printed_command_count = len(commands)

    async def _cmd_text(self, args):
        """Send a text prompt to the agent and display streaming response."""
        if not args:
            print("Usage: text <message> or ask \"<message>\"")
            print("Example: text what time is it?")
            return
        text = " ".join(args)
        
        # Clear any previous streaming text
        self.current_response_text = ""
        
        await self.sim.send_text_prompt(text)
        print(f"📤 text.prompt (text=\"{text}\")")
        print(f"📥 State: {self.sim.state.value}")
        print("\n💬 Agent: ", end="", flush=True)  # Ready for streaming output

    async def _cmd_events(self, args):
        """Show event history."""
        msgs = self.sim.received_messages
        if not msgs:
            print("No events yet")
            return
        print(f"Last {len(msgs)} messages:")
        for i, msg in enumerate(msgs[-20:], 1):  # Show last 20 instead of 10
            msg_type = msg.get("type", "?")
            payload = msg.get("payload", {})
            if msg_type == "command":
                print(f"  {i}. 📥 {payload.get('op', '?')}")
            elif msg_type == "event":
                event = payload.get("event", "?")
                if event == "agent_response_delta":
                    text = payload.get("text_delta", "")[:50]
                    print(f"  {i}. 📤 {event}: '{text}'...")
                else:
                    print(f"  {i}. 📤 {event}")
            else:
                print(f"  {i}. {msg_type}")

    async def _cmd_help(self, args):
        """Show help."""
        print("""
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
""".strip())


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
