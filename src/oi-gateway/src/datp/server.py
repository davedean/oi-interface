"""DATP WebSocket server using the websockets library."""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
from typing import TYPE_CHECKING, Any

import websockets

from .events import EventBus
from .messages import UNKNOWN_DEVICE, build_error, build_hello_ack, parse_message

if TYPE_CHECKING:
    from registry.service import RegistryService

logger = logging.getLogger(__name__)

# Logging: call `logging.getLogger("datp.server")` and configure a handler
# to see DEBUG-level messages. INFO+ messages are printed by default if no
# handler is set.
if not logger.handlers and not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

# Type alias for the per-device session entry.
DeviceEntry = dict[str, Any]


class DATPServer:
    """asyncio WebSocket server for the Device Agent Transport Protocol.

    Parameters
    ----------
    host : str
        Bind address (default "localhost").
    port : int
        TCP port (default 8787).
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8787,
        event_bus: EventBus | None = None,
        registry: RegistryService | None = None,
        available_backends: list[dict[str, Any]] | None = None,
        default_backend_id: str | None = None,
        default_agent: dict[str, Any] | None = None,
        available_agents: list[dict[str, Any]] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        # Share the same event bus with RegistryService if one is provided;
        # otherwise create a private one (backward-compatible for tests).
        self.event_bus: EventBus = event_bus if event_bus is not None else EventBus()
        self.registry: RegistryService | None = registry
        self._stopping = False
        self._server: websockets.WebSocketServer | None = None
        self.device_registry: dict[str, DeviceEntry] = {}
        self.available_backends = available_backends or []
        self.default_backend_id = default_backend_id or (self.available_backends[0]["id"] if self.available_backends else None)
        self.default_agent = default_agent
        self.available_agents = available_agents or ([] if default_agent is None else [default_agent])

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the WebSocket server."""
        self._stopping = False
        self._server = await websockets.serve(
            self._handle_connection,
            self.host,
            self.port,
        )
        # Read back the actual bound port (may differ if port=0 was passed for OS assignment).
        if self._server:
            for sock in self._server.sockets or []:
                self.port = sock.getsockname()[1]
                break
        uri = f"ws://{self.host}:{self.port}/datp"
        logger.info("DATP server listening at %s", uri)

    async def stop(self) -> None:
        """Initiate graceful shutdown.

        Notifies all remaining devices of disconnect and waits for the
        WebSocket server to stop accepting new connections.
        """
        self._stopping = True
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        # Notify registry of any remaining connected devices.
        if self.registry is not None:
            for device_id in list(self.device_registry.keys()):
                self.registry.device_disconnected(device_id)
        logger.info("DATP server stopped")

    # ------------------------------------------------------------------
    # Connection handling
    # ------------------------------------------------------------------

    async def _handle_connection(self, ws) -> None:
        """Handle a single WebSocket client connection.

        The connection is tracked in device_registry while it is alive.
        On exit the entry is removed so stale connections are not tracked.
        """
        if self._stopping:
            await ws.close()
            return

        device_id: str | None = None
        try:
            async for raw in ws:
                device_id = await self._dispatch(ws, raw)
        except websockets.ConnectionClosed:
            # Normal disconnect — no error to report.
            pass
        finally:
            # Only clear the registry entry if this connection still owns it.
            entry = self.device_registry.get(device_id) if device_id else None
            if device_id and entry and entry.get("ws") is ws:
                del self.device_registry[device_id]
                if self.registry is not None:
                    self.registry.device_disconnected(device_id)

    # ------------------------------------------------------------------
    # Message dispatch
    # ------------------------------------------------------------------

    async def _dispatch(self, ws, raw: str) -> str | None:
        """Parse and route a message; return device_id or None."""
        try:
            msg = parse_message(raw)
        except ValueError as exc:
            error = build_error(
                device_id=UNKNOWN_DEVICE,
                code="INVALID_JSON",
                message=str(exc),
                related_id=None,
            )
            await ws.send(json.dumps(error))
            return None

        # parse_message returns a validated dict
        msg_dict = msg
        msg_type = msg_dict["type"]
        device_id = msg_dict.get("device_id", "")
        logger.debug("dispatch: type=%r device=%r id=%r", msg_type, device_id, msg_dict.get("id"))

        if msg_type == "hello":
            await self._handle_hello(ws, msg_dict)
        elif msg_type == "event":
            if await self._maybe_handle_conversation_update(ws, msg_dict):
                return device_id
            self.event_bus.emit("event", device_id, msg_dict["payload"])
        elif msg_type == "audio_chunk":
            self.event_bus.emit("audio_chunk", device_id, msg_dict["payload"])
        elif msg_type == "state":
            self.event_bus.emit("state", device_id, msg_dict["payload"])
            if self.registry is not None:
                await self.registry.device_state_update(device_id, msg_dict["payload"])
        elif msg_type == "command":
            # DATP commands flow gateway→device. A device must not send commands.
            error = build_error(
                device_id=device_id,
                code="INVALID_MESSAGE_DIRECTION",
                message="Commands are sent by the gateway, not received from devices",
                related_id=msg_dict.get("id"),
            )
            await ws.send(json.dumps(error))
        elif msg_type == "ack":
            self.event_bus.emit("ack", device_id, msg_dict["payload"])
        elif msg_type == "error":
            self.event_bus.emit("error", device_id, msg_dict["payload"])
        elif msg_type == "hello_ack":
            # Server never receives hello_ack from a device.
            pass
        else:
            error = build_error(
                device_id=device_id,
                code="UNKNOWN_MESSAGE_TYPE",
                message=f"Unhandled message type: {msg_type}",
                related_id=msg_dict.get("id"),
            )
            await ws.send(json.dumps(error))

        return device_id

    # ------------------------------------------------------------------
    # Hello handshake
    # ------------------------------------------------------------------

    def get_device_conversation(self, device_id: str) -> dict[str, Any]:
        entry = self.device_registry.get(device_id) or {}
        conversation = entry.get("conversation")
        return conversation if isinstance(conversation, dict) else {}

    async def _maybe_handle_conversation_update(self, ws, msg: dict[str, Any]) -> bool:
        payload = msg.get("payload") if isinstance(msg.get("payload"), dict) else {}
        if payload.get("event") != "conversation.update":
            return False

        device_id = msg.get("device_id", "")
        requested_conversation = payload.get("conversation") if isinstance(payload.get("conversation"), dict) else {}
        updated = await self.update_device_conversation(
            device_id,
            backend_id=requested_conversation.get("backend_id"),
            agent_id=requested_conversation.get("agent_id"),
            session_key=requested_conversation.get("session_key"),
            notify_device=True,
        )
        if updated is None:
            error = build_error(
                device_id=device_id,
                code="UNKNOWN_DEVICE",
                message="Device must complete hello before updating conversation",
                related_id=msg.get("id"),
            )
            await ws.send(json.dumps(error))
        return True

    def _resolve_conversation(
        self,
        device_id: str,
        requested_conversation: dict[str, Any] | None = None,
        *,
        current_conversation: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        requested = requested_conversation or {}
        current = current_conversation or {}

        available_backend_ids = {
            str(item.get("id"))
            for item in self.available_backends
            if isinstance(item, dict) and item.get("id")
        }
        available_agent_ids = {
            str(agent.get("id"))
            for agent in self.available_agents
            if isinstance(agent, dict) and agent.get("id")
        }

        backend_candidate = requested.get("backend_id", current.get("backend_id"))
        if backend_candidate in available_backend_ids:
            selected_backend = backend_candidate
        else:
            selected_backend = self.default_backend_id

        default_agent_id = (self.default_agent or {}).get("id")
        agent_candidate = requested.get("agent_id", current.get("agent_id"))
        if agent_candidate in available_agent_ids:
            selected_agent_id = agent_candidate
        else:
            selected_agent_id = default_agent_id

        selected_agent = next(
            (agent for agent in self.available_agents if isinstance(agent, dict) and agent.get("id") == selected_agent_id),
            self.default_agent,
        )
        selected_session_key = (
            requested.get("session_key")
            or current.get("session_key")
            or f"oi:device:{device_id}"
        )
        return {
            "backend_id": selected_backend,
            "agent_id": selected_agent_id,
            "session_key": selected_session_key,
        }, selected_agent

    async def update_device_conversation(
        self,
        device_id: str,
        *,
        backend_id: str | None = None,
        agent_id: str | None = None,
        session_key: str | None = None,
        notify_device: bool = False,
    ) -> dict[str, Any] | None:
        entry = self.device_registry.get(device_id)
        if entry is None:
            return None

        conversation, selected_agent = self._resolve_conversation(
            device_id,
            {
                "backend_id": backend_id,
                "agent_id": agent_id,
                "session_key": session_key,
            },
            current_conversation=self.get_device_conversation(device_id),
        )
        entry["conversation"] = conversation

        if notify_device:
            ack = build_hello_ack(
                session_id=entry.get("session_id", f"sess_{secrets.token_hex(8)}"),
                device_id=device_id,
                default_agent=self.default_agent,
                available_agents=self.available_agents,
                available_backends=self.available_backends,
                selected_backend=conversation.get("backend_id"),
                selected_agent=selected_agent,
                selected_session_key=conversation.get("session_key"),
            )
            await entry["ws"].send(json.dumps(ack))

        return conversation

    async def _handle_hello(self, ws, msg: dict[str, Any]) -> None:
        """Process a hello handshake, register device, and send hello_ack."""
        device_id = msg["device_id"]
        payload: dict[str, Any] = msg.get("payload", {})
        requested_conversation = payload.get("conversation") if isinstance(payload.get("conversation"), dict) else {}
        session_id = f"sess_{secrets.token_hex(8)}"

        # Mark this device online BEFORE closing the old WebSocket.
        # This prevents the old connection's _handle_connection finally block
        # from incorrectly calling device_disconnected and marking the new session offline.
        if self.registry is not None:
            self.registry._mark_online(device_id)

        # Disconnect any prior connection for this device_id before replacing.
        # This prevents a stale WebSocket from receiving commands after a reconnect.
        if device_id in self.device_registry:
            old_entry = self.device_registry[device_id]
            try:
                await old_entry["ws"].close()
            except websockets.ConnectionClosed:
                pass

        # TODO (Step 3+): validate nonce for replay-attack prevention.
        #   Track recent nonces in a bounded set; reject a hello whose nonce
        #   matches a recently seen value.
        # TODO (Step 3+): resume_token support.
        #   If resume_token is provided, look up the previous session and
        #   restore state rather than starting fresh.
        conversation, selected_agent = self._resolve_conversation(device_id, requested_conversation)

        entry: DeviceEntry = {
            "ws": ws,
            "session_id": session_id,
            "capabilities": payload.get("capabilities", {}),
            "resume_token": payload.get("resume_token"),
            "nonce": payload.get("nonce"),
            "conversation": conversation,
        }
        self.device_registry[device_id] = entry

        ack = build_hello_ack(
            session_id=session_id,
            device_id=device_id,
            default_agent=self.default_agent,
            available_agents=self.available_agents,
            available_backends=self.available_backends,
            selected_backend=conversation.get("backend_id"),
            selected_agent=selected_agent,
            selected_session_key=conversation.get("session_key"),
        )
        await ws.send(json.dumps(ack))
        logger.info("device registered: device_id=%r session_id=%r", device_id, session_id)

        # Integrate with registry service if available
        if self.registry is not None:
            await self.registry.device_registered(
                device_id=device_id,
                device_type=payload.get("device_type", "unknown"),
                session_id=session_id,
                capabilities=payload.get("capabilities", {}),
                resume_token=payload.get("resume_token"),
                nonce=payload.get("nonce"),
                state=payload.get("state"),
            )

    # ------------------------------------------------------------------
    # Outbound messaging
    # ------------------------------------------------------------------

    async def send_to_device(self, device_id: str, message: dict[str, Any]) -> bool:
        """Send a DATP message to a connected device.

        Parameters
        ----------
        device_id:
            Target device ID.
        message:
            DATP envelope dict. Must contain ``v``, ``type``, and ``id`` at minimum.

        Returns
        -------
        bool
            True if the device was found and the message was sent;
            False if the device is not connected or the envelope is malformed.
        """
        entry = self.device_registry.get(device_id)
        if entry is None:
            logger.warning("send_to_device: device %r not connected", device_id)
            return False
        if not isinstance(message, dict):
            logger.warning("send_to_device: message is not a dict: %r", type(message))
            return False
        for field in ("v", "type", "id"):
            if field not in message:
                logger.warning("send_to_device: missing field %r in envelope", field)
                return False
        try:
            await entry["ws"].send(json.dumps(message))
            logger.debug("sent to device %r: type=%r id=%r", device_id, message.get("type"), message.get("id"))
        except websockets.ConnectionClosed:
            logger.warning("send_to_device: device %r disconnected mid-send", device_id)
            return False
        return True
