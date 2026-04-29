#!/usr/bin/env python3
"""DATP WebSocket client for Oi handheld devices.

Adapted from OiSim (src/oi-sim/src/sim/sim.py).
"""

from __future__ import annotations

import asyncio
import base64
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from oi_client.state import InvalidTransition, State, StateMachine


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _new_id(prefix: str = "msg") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class DatpClient:
    """Async DATP WebSocket client for Linux SBC handhelds.

    Wraps the OiSim protocol logic without the simulator extras.
    """

    def __init__(
        self,
        gateway: str,
        device_id: str,
        device_type: str,
        capabilities: dict[str, Any],
        reconnect_backoff: float = 1.0,
    ) -> None:
        self.gateway = gateway
        self.device_id = device_id
        self.device_type = device_type
        self.capabilities = capabilities
        self.reconnect_backoff = reconnect_backoff

        self._ws = None
        self._connected = False
        self._state_machine = StateMachine(State.READY)
        self._session_id: str | None = None
        self._listen_task: asyncio.Task | None = None
        self._received_commands: list[dict] = []

        # Command queue for the UI thread
        self._cmd_queue: asyncio.Queue[dict] = asyncio.Queue()

    @property
    def state(self) -> State:
        return self._state_machine.state

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """Connect to gateway, send hello, wait for hello_ack."""
        import websockets

        try:
            self._ws = await websockets.connect(self.gateway, ping_interval=20, ping_timeout=10)
            self._connected = True
        except Exception as exc:
            print(f"Connection failed: {exc}")
            return False

        hello = {
            "v": "datp",
            "type": "hello",
            "id": _new_id("hello"),
            "device_id": self.device_id,
            "ts": _now_iso(),
            "payload": {
                "device_type": self.device_type,
                "protocol": "datp",
                "firmware": f"oi-sbc-client/0.1",
                "capabilities": self.capabilities,
                "state": {
                    "mode": "READY",
                },
                "nonce": secrets.token_hex(8),
            },
        }
        await self._ws.send(json.dumps(hello))

        # Wait for hello_ack
        try:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=5.0)
            resp = json.loads(raw)
            if resp.get("type") != "hello_ack":
                await self.disconnect()
                return False
            self._session_id = resp.get("payload", {}).get("session_id")
        except asyncio.TimeoutError:
            await self.disconnect()
            return False

        # Start background listener
        self._listen_task = asyncio.create_task(self._listen_loop())
        return True

    async def disconnect(self) -> None:
        """Close connection cleanly."""
        self._connected = False
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def reconnect(self) -> bool:
        await self.disconnect()
        self._session_id = None
        self._received_commands.clear()
        self._state_machine = StateMachine(State.READY)
        await asyncio.sleep(self.reconnect_backoff)
        return await self.connect()

    # ------------------------------------------------------------------
    # Background listener
    # ------------------------------------------------------------------

    async def _listen_loop(self) -> None:
        import websockets
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                await self._handle_message(msg)
        except websockets.ConnectionClosed:
            self._connected = False
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"Listen error: {exc}")
            self._connected = False

    async def _handle_message(self, msg: dict) -> None:
        msg_type = msg.get("type", "")
        payload = msg.get("payload", {})

        if msg_type == "command":
            op = payload.get("op", "")
            args = payload.get("args", {})
            try:
                self._state_machine.receive_command(op, args)
            except InvalidTransition:
                pass
            self._received_commands.append(payload)
            await self._ack(msg.get("id", ""))
            await self._cmd_queue.put(payload)

        elif msg_type == "error":
            code = payload.get("code", "")
            print(f"Gateway error: {code}")
            try:
                self._state_machine.transition(State.ERROR)
            except InvalidTransition:
                pass

        elif msg_type == "ack":
            pass  # Not yet used for outbound commands

    async def _ack(self, command_id: str) -> None:
        if not self._ws:
            return
        ack = {
            "v": "datp",
            "type": "ack",
            "id": _new_id("ack"),
            "device_id": self.device_id,
            "ts": _now_iso(),
            "payload": {"command_id": command_id, "ok": True},
        }
        await self._ws.send(json.dumps(ack))

    # ------------------------------------------------------------------
    # Outbound helpers
    # ------------------------------------------------------------------

    async def _send(self, msg_type: str, payload: dict) -> None:
        if not self._ws:
            return
        msg = {
            "v": "datp",
            "type": msg_type,
            "id": _new_id(msg_type[:4]),
            "device_id": self.device_id,
            "ts": _now_iso(),
            "payload": payload,
        }
        await self._ws.send(json.dumps(msg))

    # ------------------------------------------------------------------
    # Public event API
    # ------------------------------------------------------------------

    async def send_button(self, button: str, action: str = "pressed") -> None:
        event_type = "button.pressed" if action == "pressed" else "button.released"
        await self._send("event", {"event": event_type, "button": button})

    async def send_text_prompt(self, text: str) -> None:
        await self._send("event", {"event": "text.prompt", "text": text})

    async def send_state_report(self) -> None:
        await self._send("state", {
            "mode": self._state_machine.state.value,
            "muted_until": None,
        })

    async def send_audio_chunk(self, stream_id: str, seq: int, pcm16_data: bytes, sample_rate: int = 16000) -> None:
        await self._send("audio_chunk", {
            "stream_id": stream_id,
            "seq": seq,
            "format": "pcm16",
            "sample_rate": sample_rate,
            "channels": 1,
            "data_b64": base64.b64encode(pcm16_data).decode(),
        })

    async def send_recording_finished(self, stream_id: str, duration_ms: int) -> None:
        await self._send("event", {
            "event": "audio.recording_finished",
            "stream_id": stream_id,
            "duration_ms": duration_ms,
        })

    # ------------------------------------------------------------------
    # Command queue
    # ------------------------------------------------------------------

    def get_commands(self) -> list[dict]:
        """Drain the command queue (called by UI thread each frame)."""
        cmds = []
        while not self._cmd_queue.empty():
            try:
                cmds.append(self._cmd_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return cmds

    def transition(self, new_state: State) -> None:
        """Advance the state machine."""
        try:
            self._state_machine.transition(new_state)
        except InvalidTransition:
            pass
