"""Command dispatcher for sending DATP commands to devices and awaiting acknowledgement."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from .messages import (
    build_audio_cache_chunk,
    build_audio_cache_put_begin,
    build_audio_cache_put_end,
    build_audio_play,
    build_audio_stop,
    build_command,
    build_device_mute_until,
    build_device_set_brightness,
    build_display_show_card,
    build_display_show_progress,
    build_display_show_response_delta,
    build_display_show_status,
)

if TYPE_CHECKING:
    from .server import DATPServer

logger = logging.getLogger(__name__)


class CommandDispatcher:
    """Sends DATP commands to connected devices and waits for acknowledgements.

    Parameters
    ----------
    server : DATPServer
        The DATP server instance. Used to send messages to devices and access the event bus.
    """

    def __init__(self, server: DATPServer) -> None:
        self._server = server
        # Map command_id → asyncio.Future that resolves when ack arrives
        self._pending: dict[str, asyncio.Future[bool]] = {}
        # Subscribe to inbound acks (callback signature: event_type, device_id, payload)
        server.event_bus.subscribe(self._on_event)
        # Character renderer — initialized on first use
        self._character_renderer = None

    def _on_event(self, event_type: str, device_id: str, payload: dict[str, Any]) -> None:
        """Callback when any event is received. Filter for acks and resolve pending futures."""
        if event_type != "ack":
            return

        command_id = payload.get("command_id")
        ok = payload.get("ok", False)

        future = self._pending.pop(command_id, None)
        if future and not future.done():
            future.set_result(ok)

    async def send(
        self,
        device_id: str,
        op: str,
        args: dict[str, Any] | None = None,
        timeout: float = 5.0,
    ) -> bool:
        """Send a command to a device and wait for acknowledgement.

        Parameters
        ----------
        device_id : str
            Target device ID.
        op : str
            Command operator (e.g. 'display.show_status').
        args : dict, optional
            Command arguments.
        timeout : float, optional
            How long to wait for the ack (seconds). Default 5.0.

        Returns
        -------
        bool
            True if the device acknowledged success; False on timeout, send failure, or nack.
        """
        msg = build_command(device_id, op, args or {})
        command_id = msg["id"]

        # Render character state based on the command (non-blocking)
        if self._character_renderer is not None:
            try:
                await self._character_renderer.render_for_command_async(device_id, op, args or {})
            except Exception as exc:
                logger.debug("Character render error (non-critical): %s", exc)

        # Create a future to wait for the ack
        loop = asyncio.get_event_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self._pending[command_id] = future

        # Send the command
        sent = await self._server.send_to_device(device_id, msg)
        if not sent:
            del self._pending[command_id]
            logger.warning("Failed to send command %s to device %s", command_id, device_id)
            return False

        # Wait for ack with timeout
        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout)
        except asyncio.TimeoutError:
            self._pending.pop(command_id, None)
            logger.warning("Command %s to device %s timed out after %.1f s", command_id, device_id, timeout)
            return False

    async def _send_built_command(self, device_id: str, message: dict[str, Any], timeout: float) -> bool:
        """Send a pre-built DATP command envelope via the standard ack path."""
        payload = message["payload"]
        return await self.send(device_id, payload["op"], payload["args"], timeout)

    # ------------------------------------------------------------------
    # Convenience methods for specific command types
    # ------------------------------------------------------------------

    async def show_status(
        self,
        device_id: str,
        state: str,
        label: str | None = None,
        timeout: float = 5.0,
    ) -> bool:
        """Show a semantic status state on the device.

        Parameters
        ----------
        device_id : str
            Target device.
        state : str
            Status state (e.g. 'thinking', 'response_cached', 'muted', 'offline').
        label : str, optional
            Optional label to display alongside state.
        timeout : float, optional
            Ack timeout in seconds.

        Returns
        -------
        bool
            True if ack'd by device.
        """
        return await self._send_built_command(
            device_id,
            build_display_show_status(device_id, state, label),
            timeout,
        )

    async def show_card(
        self,
        device_id: str,
        title: str,
        options: list[dict[str, Any]],
        body: str | None = None,
        timeout: float = 5.0,
    ) -> bool:
        """Show a confirmation card with button options.

        Parameters
        ----------
        device_id : str
            Target device.
        title : str
            Card title.
        options : list[dict]
            Button options, each with 'id' and 'label' keys.
        body : str, optional
            Body text to display below the title.
        timeout : float, optional
            Ack timeout in seconds.

        Returns
        -------
        bool
            True if ack'd.
        """
        return await self._send_built_command(
            device_id,
            build_display_show_card(device_id, title, options, body),
            timeout,
        )

    async def show_response_delta(
        self,
        device_id: str,
        text_delta: str,
        is_final: bool = False,
        sequence: int | None = None,
        timeout: float = 5.0,
    ) -> bool:
        return await self._send_built_command(
            device_id,
            build_display_show_response_delta(device_id, text_delta, is_final, sequence),
            timeout,
        )

    async def show_progress(
        self,
        device_id: str,
        text: str,
        kind: str | None = None,
        sequence: int | None = None,
        timeout: float = 5.0,
    ) -> bool:
        return await self._send_built_command(
            device_id,
            build_display_show_progress(device_id, text, kind, sequence),
            timeout,
        )

    async def cache_put_begin(
        self,
        device_id: str,
        response_id: str,
        timeout: float = 5.0,
    ) -> bool:
        """Start an audio cache sequence.

        Parameters
        ----------
        device_id : str
            Target device.
        response_id : str
            Unique response identifier.
        timeout : float, optional
            Ack timeout in seconds.

        Returns
        -------
        bool
            True if ack'd.
        """
        return await self._send_built_command(
            device_id,
            build_audio_cache_put_begin(device_id, response_id),
            timeout,
        )

    async def cache_put_chunk(
        self,
        device_id: str,
        response_id: str,
        seq: int,
        data_b64: str,
        timeout: float = 5.0,
    ) -> bool:
        """Send an audio chunk during a cache sequence.

        Parameters
        ----------
        device_id : str
            Target device.
        response_id : str
            Response ID (must match put_begin).
        seq : int
            Chunk sequence number (0-indexed).
        data_b64 : str
            Base64-encoded PCM audio data.
        timeout : float, optional
            Ack timeout in seconds.

        Returns
        -------
        bool
            True if ack'd.
        """
        return await self._send_built_command(
            device_id,
            build_audio_cache_chunk(device_id, response_id, seq, data_b64),
            timeout,
        )

    async def cache_put_end(
        self,
        device_id: str,
        response_id: str,
        sha256: str | None = None,
        timeout: float = 5.0,
    ) -> bool:
        """Complete an audio cache sequence.

        Parameters
        ----------
        device_id : str
            Target device.
        response_id : str
            Response ID (must match put_begin).
        sha256 : str | None, optional
            Optional SHA-256 hash of the complete audio data for verification.
        timeout : float, optional
            Ack timeout in seconds.

        Returns
        -------
        bool
            True if ack'd. Device should transition to RESPONSE_CACHED state.
        """
        return await self._send_built_command(
            device_id,
            build_audio_cache_put_end(device_id, response_id, sha256),
            timeout,
        )

    async def audio_play(
        self,
        device_id: str,
        response_id: str = "latest",
        timeout: float = 5.0,
    ) -> bool:
        """Play cached audio on the device.

        Parameters
        ----------
        device_id : str
            Target device.
        response_id : str, optional
            Which cached response to play. Default 'latest' plays the most recent.
        timeout : float, optional
            Ack timeout in seconds.

        Returns
        -------
        bool
            True if ack'd. Device should transition to PLAYING state.
        """
        return await self._send_built_command(
            device_id,
            build_audio_play(device_id, response_id),
            timeout,
        )

    async def audio_stop(
        self,
        device_id: str,
        timeout: float = 5.0,
    ) -> bool:
        """Stop audio playback on the device.

        Parameters
        ----------
        device_id : str
            Target device.
        timeout : float, optional
            Ack timeout in seconds.

        Returns
        -------
        bool
            True if ack'd. Device should transition to READY state.
        """
        return await self._send_built_command(device_id, build_audio_stop(device_id), timeout)

    async def set_brightness(
        self,
        device_id: str,
        level: int,
        timeout: float = 5.0,
    ) -> bool:
        """Set device screen brightness.

        Parameters
        ----------
        device_id : str
            Target device.
        level : int
            Brightness level (0-255).
        timeout : float, optional
            Ack timeout in seconds.

        Returns
        -------
        bool
            True if ack'd.
        """
        return await self._send_built_command(
            device_id,
            build_device_set_brightness(device_id, level),
            timeout,
        )

    async def mute_until(
        self,
        device_id: str,
        until: str,
        timeout: float = 5.0,
    ) -> bool:
        """Mute the device until a specific ISO-8601 timestamp.

        Parameters
        ----------
        device_id : str
            Target device.
        until : str
            ISO-8601 timestamp (e.g. '2026-04-28T15:30:00.000Z').
        timeout : float, optional
            Ack timeout in seconds.

        Returns
        -------
        bool
            True if ack'd. Device should transition to MUTED state.
        """
        return await self._send_built_command(
            device_id,
            build_device_mute_until(device_id, until),
            timeout,
        )

    # ------------------------------------------------------------------
    # Character rendering
    # ------------------------------------------------------------------

    def set_character_renderer(self, renderer) -> None:
        """Set the character renderer service.

        Parameters
        ----------
        renderer : CharacterRendererService
            The character renderer instance.
        """
        self._character_renderer = renderer

    async def set_character_pack(
        self,
        device_id: str,
        pack_id: str | None,
        timeout: float = 5.0,
    ) -> bool:
        """Set or clear the character pack for a device.

        Parameters
        ----------
        device_id : str
            Target device.
        pack_id : str or None
            The character pack ID to assign, or None to clear.
        timeout : float, optional
            Ack timeout in seconds.

        Returns
        -------
        bool
            True if the device acknowledged success.
        """
        return await self._send_built_command(
            device_id,
            build_command(device_id, "character.set_state", {"pack_id": pack_id}),
            timeout,
        )
