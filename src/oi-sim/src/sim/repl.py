"""
Oi-Sim REPL: Interactive virtual device command line.

A simple REPL that lets humans interact with oi-gateway using typed commands.
"""

from __future__ import annotations

import asyncio
import shlex
from typing import Any

from sim import OiSim

TEXT_PROMPT_USAGE = (
    "Usage: text <message> or ask \"<message>\"\n"
    "Example: text what time is it?"
)

HELP_TEXT = """
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
""".strip()


class OiSimREPL:
    """Interactive REPL for OiSim virtual device."""

    event_history_limit = 10
    help_text = HELP_TEXT
    text_prompt_usage = TEXT_PROMPT_USAGE

    def __init__(
        self,
        gateway: str = "ws://localhost:8787/datp",
        device_id: str = "oi-sim-repl-001",
    ):
        self.gateway = gateway
        self.device_id = device_id
        self.sim: OiSim | None = None
        self.running = False
        self._printed_command_count = 0
        self._receive_task: asyncio.Task[None] | None = None

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
        self._receive_task = asyncio.create_task(self._receive_loop())

        try:
            await self._repl_loop()
        finally:
            self.running = False
            await self._stop_receive_task()
            if self.sim:
                await self.sim.disconnect()
            print("✓ Disconnected")

    async def _repl_loop(self):
        """Main REPL loop."""
        while self.running:
            try:
                line = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: input("> ").strip()
                )
                if line:
                    await self._handle_command(line)
            except EOFError:
                self.running = False
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

        handler = self._command_handlers().get(cmd)
        if handler is None:
            print(f"Unknown command: {cmd}. Type 'help' for available commands.")
            return

        try:
            await handler(args)
        except Exception as e:
            print(f"✗ Error: {e}")

    def _command_handlers(self) -> dict[str, Any]:
        """Map command names to handler methods."""
        return {
            "hold": self._cmd_hold,
            "release": self._cmd_release,
            "tap": self._cmd_tap,
            "double": self._cmd_double,
            "mute": self._cmd_mute,
            "play": self._cmd_play,
            "stop": self._cmd_stop,
            "text": self._cmd_text,
            "ask": self._cmd_text,
            "battery": self._cmd_battery,
            "charging": self._cmd_charging,
            "wifi": self._cmd_wifi,
            "connect": self._cmd_connect,
            "disconnect": self._cmd_disconnect,
            "state": self._cmd_state,
            "events": self._cmd_events,
            "help": self._cmd_help,
            "quit": self._cmd_quit,
            "exit": self._cmd_quit,
        }

    async def _receive_loop(self):
        """Background task to receive and display messages from gateway."""
        while self.running and self.sim:
            await asyncio.sleep(0.1)
            self._print_pending_commands(self._live_command_printer)

    def _live_command_printer(self, command: dict[str, Any]) -> None:
        """Print a command received during the live REPL session."""
        self._print_command(command)

    async def _stop_receive_task(self) -> None:
        """Cancel and await the background receive task if it is running."""
        if self._receive_task is None:
            return
        self._receive_task.cancel()
        try:
            await self._receive_task
        except asyncio.CancelledError:
            pass
        finally:
            self._receive_task = None

    def _print_pending_commands(self, printer: Any) -> None:
        """Print commands received since the last REPL refresh."""
        assert self.sim is not None
        commands = self.sim.received_commands
        if len(commands) <= self._printed_command_count:
            return

        for command in commands[self._printed_command_count:]:
            printer(command)
        self._printed_command_count = len(commands)

    def _print_command(self, command: dict[str, Any], *, leading_newline: bool = False) -> None:
        """Print a received command in a compact human-friendly format."""
        prefix = "\n" if leading_newline else ""
        op = command.get("op", "unknown")
        args = command.get("args", {})
        print(f"{prefix}📥 {op}")
        if op == "display.show_card":
            title = args.get("title", "")
            body = args.get("body")
            if title:
                print(f"   title: {title}")
            if body:
                print(f"   body: {body}")

    def _print_text_prompt_usage(self) -> None:
        """Show usage for text-prompt commands."""
        print(self.text_prompt_usage)

    def _print_event_history(self, messages: list[dict[str, Any]]) -> None:
        """Print recent message history."""
        if not messages:
            print("No events yet")
            return

        recent_messages = messages[-self.event_history_limit :]
        print(f"Last {len(recent_messages)} of {len(messages)} messages:")
        for i, msg in enumerate(recent_messages, 1):
            print(self._format_message_history_entry(i, msg))

    def _format_message_history_entry(self, index: int, msg: dict[str, Any]) -> str:
        """Format a single event-history row."""
        msg_type = msg.get("type", "?")
        payload = msg.get("payload", {})
        if msg_type == "command":
            return f"  {index}. 📥 {payload.get('op', '?')}"
        if msg_type == "event":
            return f"  {index}. 📤 {payload.get('event', '?')}"
        return f"  {index}. {msg_type}"

    async def _cmd_hold(self, args):
        """Long hold - start recording."""
        assert self.sim is not None
        await self.sim.press_long_hold()
        print("📤 button.long_hold_started (button=main)")
        print(f"📥 State: {self.sim.state.value}")

    async def _cmd_release(self, args):
        """Release - stop recording."""
        assert self.sim is not None
        await self.sim.release()
        print("📤 audio.recording_finished")
        print(f"📥 State: {self.sim.state.value}")

    async def _cmd_tap(self, args):
        """Short tap."""
        assert self.sim is not None
        await self.sim.press_button()
        print("📤 button.pressed (button=main)")

    async def _cmd_double(self, args):
        """Double tap."""
        assert self.sim is not None
        await self.sim.double_tap()
        print("📤 button.double_tap (button=main)")
        print(f"📥 State: {self.sim.state.value}")

    async def _cmd_mute(self, args):
        """Very long hold - mute."""
        assert self.sim is not None
        await self.sim.press_very_long_hold()
        print("📤 button.very_long_hold_started (button=main)")
        print(f"📥 State: {self.sim.state.value}")

    async def _cmd_play(self, args):
        """Start playback."""
        assert self.sim is not None
        response_id = args[0] if args else "latest"
        await self.sim.send_playback_started(response_id)
        print(f"📤 audio.playback_started (response_id={response_id})")
        print(f"📥 State: {self.sim.state.value}")

    async def _cmd_stop(self, args):
        """Stop playback."""
        assert self.sim is not None
        await self.sim.send_playback_finished()
        print("📤 audio.playback_finished")
        print(f"📥 State: {self.sim.state.value}")

    async def _cmd_text(self, args):
        """Send a text prompt to the agent."""
        text = await self._send_text_prompt(args)
        if text is not None:
            self._after_text_prompt_sent(text)

    async def _send_text_prompt(self, args: list[str]) -> str | None:
        """Send a text prompt and print the common REPL status output."""
        assert self.sim is not None
        if not args:
            self._print_text_prompt_usage()
            return None

        text = " ".join(args)
        await self.sim.send_text_prompt(text)
        print(f'📤 text.prompt (text="{text}")')
        print(f"📥 State: {self.sim.state.value}")
        return text

    def _after_text_prompt_sent(self, text: str) -> None:
        """Hook for subclasses that want extra output after sending text."""
        del text

    async def _cmd_battery(self, args):
        """Send battery update."""
        assert self.sim is not None
        if not args:
            print("Usage: battery <0-100>")
            return
        percent = int(args[0])
        await self.sim.send_battery_update(percent)
        print(f"📤 sensor.battery_update (battery_percent={percent})")

    async def _cmd_charging(self, args):
        """Send charging state."""
        assert self.sim is not None
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
        assert self.sim is not None
        if not args:
            print("Usage: wifi <-100 to 0>")
            return
        rssi = int(args[0])
        await self.sim.send_wifi_update(rssi)
        print(f"📤 sensor.wifi_update (rssi={rssi})")

    async def _cmd_connect(self, args):
        """Reconnect to gateway."""
        assert self.sim is not None
        if self.sim.is_connected:
            print("Already connected")
            return
        await self.sim.connect()
        print("✓ Reconnected")

    async def _cmd_disconnect(self, args):
        """Disconnect from gateway."""
        assert self.sim is not None
        await self.sim.disconnect()
        print("✓ Disconnected")

    async def _cmd_state(self, args):
        """Show device state."""
        assert self.sim is not None
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
        assert self.sim is not None
        self._print_event_history(self.sim.received_messages)

    async def _cmd_help(self, args):
        """Show help."""
        print(self.help_text)

    async def _cmd_quit(self, args):
        """Quit the REPL."""
        self.running = False


async def run_repl_app(repl_cls: type[OiSimREPL], description: str) -> None:
    """Parse standard REPL CLI args and start the requested REPL class."""
    import argparse

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--gateway", default="ws://localhost:8787/datp", help="Gateway WebSocket URL")
    parser.add_argument("--device-id", default="oi-sim-repl-001", help="Device ID")
    args = parser.parse_args()

    repl = repl_cls(gateway=args.gateway, device_id=args.device_id)
    await repl.start()


async def main():
    """Main entry point."""
    await run_repl_app(OiSimREPL, "Oi-Sim REPL - Interactive virtual device")


if __name__ == "__main__":
    asyncio.run(main())
