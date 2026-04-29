"""
Oi-Sim REPL: Interactive virtual device command line.

A simple REPL that lets humans interact with oi-gateway using typed commands.
"""

import asyncio
import shlex
import sys
from typing import Optional

from sim import OiSim
from sim.state import State


class OiSimREPL:
    """Interactive REPL for OiSim virtual device."""

    def __init__(
        self,
        gateway: str = "ws://localhost:8787/datp",
        device_id: str = "oi-sim-repl-001",
    ):
        self.gateway = gateway
        self.device_id = device_id
        self.sim: Optional[OiSim] = None
        self.running = False
        self._printed_command_count = 0

    async def start(self):
        """Start the REPL."""
        self.sim = OiSim(
            gateway=self.gateway,
            device_id=self.device_id,
            device_type="oi-stick",
        )

        print(f"Connecting to {self.gateway}...")
        try:
            await self.sim.connect()
            print(f"✓ Connected as {self.device_id}")
            print("Type 'help' for commands, 'quit' to exit.\n")
        except Exception as e:
            print(f"✗ Connection failed: {e}")
            return

        self.running = True

        # Start background task to receive gateway messages
        self._receive_task = asyncio.create_task(self._receive_loop())

        # Main REPL loop
        await self._repl_loop()

        # Cleanup
        if self.sim:
            await self.sim.disconnect()
        print("✓ Disconnected")

    async def _repl_loop(self):
        """Main REPL loop."""
        while self.running:
            try:
                line = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: input("> ").strip()
                )
                if line:
                    await self._handle_command(line)
            except EOFError:
                break
            except KeyboardInterrupt:
                print("\n(Use 'quit' to exit)")
                continue

    async def _handle_command(self, line: str):
        """Handle a single command."""
        try:
            parts = shlex.split(line)
        except ValueError as exc:
            print(f"Invalid command syntax: {exc}")
            return
        cmd = parts[0].lower() if parts else ""
        args = parts[1:]

        # Map commands to OiSim methods
        commands = {
            # Button events
            "hold": self._cmd_hold,
            "release": self._cmd_release,
            "tap": self._cmd_tap,
            "double": self._cmd_double,
            "mute": self._cmd_mute,
            # Playback
            "play": self._cmd_play,
            "stop": self._cmd_stop,
            # Text input
            "text": self._cmd_text,
            "ask": self._cmd_text,
            # Power
            "battery": self._cmd_battery,
            "charging": self._cmd_charging,
            # Network
            "wifi": self._cmd_wifi,
            "connect": self._cmd_connect,
            "disconnect": self._cmd_disconnect,
            # Info
            "state": self._cmd_state,
            "events": self._cmd_events,
            "help": self._cmd_help,
            # Quit
            "quit": self._cmd_quit,
            "exit": self._cmd_quit,
        }

        if cmd in commands:
            try:
                await commands[cmd](args)
            except Exception as e:
                print(f"✗ Error: {e}")
        else:
            print(f"Unknown command: {cmd}. Type 'help' for available commands.")

    async def _receive_loop(self):
        """Background task to receive and display messages from gateway."""
        while self.running and self.sim:
            await asyncio.sleep(0.1)
            # Print each new command exactly once.
            commands = self.sim.received_commands
            if len(commands) > self._printed_command_count:
                new_commands = commands[self._printed_command_count:]
                for cmd in new_commands:
                    op = cmd.get("op", "unknown")
                    args = cmd.get("args", {})
                    print(f"📥 {op}")
                    if op == "display.show_card":
                        title = args.get("title", "")
                        body = args.get("body")
                        if title:
                            print(f"   title: {title}")
                        if body:
                            print(f"   body: {body}")
                self._printed_command_count = len(commands)

    # Command implementations
    async def _cmd_hold(self, args):
        """Long hold - start recording."""
        await self.sim.press_long_hold()
        print("📤 button.long_hold_started (button=main)")
        print(f"📥 State: {self.sim.state.value}")

    async def _cmd_release(self, args):
        """Release - stop recording."""
        await self.sim.release()
        print("📤 audio.recording_finished")
        print(f"📥 State: {self.sim.state.value}")

    async def _cmd_tap(self, args):
        """Short tap."""
        await self.sim.press_button()
        print("📤 button.pressed (button=main)")

    async def _cmd_double(self, args):
        """Double tap."""
        await self.sim.double_tap()
        print("📤 button.double_tap (button=main)")
        print(f"📥 State: {self.sim.state.value}")

    async def _cmd_mute(self, args):
        """Very long hold - mute."""
        await self.sim.press_very_long_hold()
        print("📤 button.very_long_hold_started (button=main)")
        print(f"📥 State: {self.sim.state.value}")

    async def _cmd_play(self, args):
        """Start playback."""
        response_id = args[0] if args else "latest"
        await self.sim.send_playback_started(response_id)
        print(f"📤 audio.playback_started (response_id={response_id})")
        print(f"📥 State: {self.sim.state.value}")

    async def _cmd_stop(self, args):
        """Stop playback."""
        await self.sim.send_playback_finished()
        print("📤 audio.playback_finished")
        print(f"📥 State: {self.sim.state.value}")

    async def _cmd_text(self, args):
        """Send a text prompt to the agent."""
        if not args:
            print("Usage: text <message> or ask \"<message>\"")
            print("Example: text what time is it?")
            return
        text = " ".join(args)
        await self.sim.send_text_prompt(text)
        print(f"📤 text.prompt (text=\"{text}\")")
        print(f"📥 State: {self.sim.state.value}")

    async def _cmd_battery(self, args):
        """Send battery update."""
        if not args:
            print("Usage: battery <0-100>")
            return
        percent = int(args[0])
        await self.sim.send_battery_update(percent)
        print(f"📤 sensor.battery_update (battery_percent={percent})")

    async def _cmd_charging(self, args):
        """Send charging state."""
        if not args:
            print("Usage: charging start|stop")
            return
        if args[0] == "start":
            await self.sim.send_charging_started()
            print("📤 charging_started")
        elif args[0] == "stop":
            await self.sim.send_charging_stopped()
            print("📤 charging_stopped")

    async def _cmd_wifi(self, args):
        """Send WiFi update."""
        if not args:
            print("Usage: wifi <-100 to 0>")
            return
        rssi = int(args[0])
        await self.sim.send_wifi_update(rssi)
        print(f"📤 sensor.wifi_update (rssi={rssi})")

    async def _cmd_connect(self, args):
        """Reconnect to gateway."""
        if self.sim.is_connected:
            print("Already connected")
            return
        await self.sim.connect()
        print("✓ Reconnected")

    async def _cmd_disconnect(self, args):
        """Disconnect from gateway."""
        await self.sim.disconnect()
        print("✓ Disconnected")

    async def _cmd_state(self, args):
        """Show device state."""
        state = self.sim.state.value
        display = self.sim.display_state or "none"
        label = self.sim.display_label or ""
        muted = self.sim.muted_until or "no"
        print(f"State: {state}")
        print(f"Display: {display} {label}")
        print(f"Muted until: {muted}")
        print(f"Volume: {self.sim.volume}")
        print(f"Brightness: {self.sim.brightness}")

    async def _cmd_events(self, args):
        """Show event history."""
        msgs = self.sim.received_messages
        if not msgs:
            print("No events yet")
            return
        print(f"Last {len(msgs)} messages:")
        for i, msg in enumerate(msgs[-10:], 1):
            msg_type = msg.get("type", "?")
            payload = msg.get("payload", {})
            if msg_type == "command":
                print(f"  {i}. 📥 {payload.get('op', '?')}")
            elif msg_type == "event":
                print(f"  {i}. 📤 {payload.get('event', '?')}")
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
  text <msg>  - Send text prompt to agent
  ask <msg>  - Same as text (alias)
  play [id]   - Start audio playback (default: latest)
  stop        - Stop audio playback
  battery N   - Send battery N%
  charging    - charging start|stop
  wifi N      - Send wifi RSSI N
  connect     - Connect to gateway
  disconnect  - Disconnect
  state       - Show device state
  events      - Show event history
  help        - Show this help
  quit        - Exit
        """.strip())

    async def _cmd_quit(self, args):
        """Quit the REPL."""
        self.running = False


async def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Oi-Sim REPL - Interactive virtual device")
    parser.add_argument("--gateway", default="ws://localhost:8787/datp", help="Gateway WebSocket URL")
    parser.add_argument("--device-id", default="oi-sim-repl-001", help="Device ID")
    args = parser.parse_args()

    repl = OiSimREPL(gateway=args.gateway, device_id=args.device_id)
    await repl.start()


if __name__ == "__main__":
    asyncio.run(main())
