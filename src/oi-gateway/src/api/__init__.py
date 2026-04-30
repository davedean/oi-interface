"""oi-gateway HTTP API — resource tree endpoint at /api."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from aiohttp import web

from datp import EventBus
from datp.commands import CommandDispatcher
from datp.server import DATPServer
from routing import RoutingPolicy, RouteRequest

if TYPE_CHECKING:
    from audio.tts import TtsBackend
    from coding import CodingWorkflowService

from character_packs import CharacterPackService

logger = logging.getLogger(__name__)


class GatewayAPI:
    """HTTP REST API for oi-gateway resource tree.

    Exposes endpoints at ``/api/*`` to query and drive devices. Used by oi-cli
    and any external agent/consumer.

    Parameters
    ----------
    datp_server : DATPServer
        The DATP server (for sending commands and accessing registry).
    command_dispatcher : CommandDispatcher
        For invoking device commands.
    event_bus : EventBus
        For subscribing to async events.
    host : str, optional
        HTTP bind address (default "localhost").
    port : int, optional
        HTTP port (default 8788).
    tts : TtsBackend, optional
        TTS backend for /api/route endpoint.
    character_pack_service : CharacterPackService, optional
        Service for managing character packs.
    """

    def __init__(
        self,
        datp_server: DATPServer,
        command_dispatcher: CommandDispatcher,
        event_bus: EventBus,
        host: str = "localhost",
        port: int = 8788,
        tts: TtsBackend | None = None,
        character_pack_service: CharacterPackService | None = None,
        coding_service: "CodingWorkflowService | None" = None,
    ) -> None:
        self._datp = datp_server
        self._dispatcher = command_dispatcher
        self._event_bus = event_bus
        self._host = host
        self._port = port
        self._tts = tts
        self._pack_service = character_pack_service
        self._coding_service = coding_service
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._routing_policy: RoutingPolicy | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the HTTP server."""
        self._app = web.Application()
        self._register_routes(self._app)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        # Read back the actual bound port (may differ if port=0 was passed for OS assignment)
        # Try to get port from the server sockets
        for sock in site._server.sockets or []:
            self._port = sock.getsockname()[1]
            break
        logger.info("GatewayAPI listening at http://%s:%d/api", self._host, self._port)

    async def stop(self) -> None:
        """Stop the HTTP server."""
        if self._runner:
            await self._runner.cleanup()
        logger.info("GatewayAPI stopped")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _register_routes(self, app: web.Application) -> None:
        for method, path, handler in self._routes():
            app.router.add_route(method, path, handler)

    def _routes(self) -> tuple[tuple[str, str, Any], ...]:
        return (
            ("GET", "/api/health", self._health),
            ("GET", "/api/devices", self._devices_list),
            ("GET", "/api/devices/{device_id}", self._device_info),
            ("POST", "/api/devices/{device_id}/commands/show_status", self._cmd_show_status),
            ("POST", "/api/devices/{device_id}/commands/mute_until", self._cmd_mute_until),
            ("POST", "/api/devices/{device_id}/commands/audio_play", self._cmd_audio_play),
            ("POST", "/api/devices/{device_id}/character", self._set_device_character),
            ("GET", "/api/character_packs", self._character_packs_list),
            ("GET", "/api/character_packs/{pack_id}", self._character_pack_info),
            ("POST", "/api/route", self._route),
            ("POST", "/api/route/multi", self._route_multi),
            ("POST", "/api/devices/{device_id}/foreground", self._set_foreground),
            ("GET", "/api/devices/{device_id}/health", self._device_health),
            ("POST", "/api/devices/{device_id}/interactions", self._record_interaction),
            ("GET", "/api/coding/status", self._coding_status),
            ("GET", "/api/coding/last_result", self._coding_last_result),
            ("POST", "/api/coding/enable", self._coding_enable),
            ("POST", "/api/coding/disable", self._coding_disable),
            ("POST", "/api/coding/clear_history", self._coding_clear_history),
        )

    def _json_response(self, data: Any, status: int = 200) -> web.Response:
        return web.Response(
            text=json.dumps(data, indent=2),
            content_type="application/json",
            status=status,
        )

    def _format_utc_timestamp(self, value: datetime) -> str:
        return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def _error_response(self, message: str, status: int = 400) -> web.Response:
        return self._json_response({"error": message}, status)

    async def _read_json(self, request: web.Request) -> dict[str, Any]:
        try:
            return await request.json()
        except json.JSONDecodeError:
            raise web.HTTPBadRequest(text=json.dumps({"error": "Invalid JSON body"}))

    def _require_registered_device(self, device_id: str) -> dict[str, Any] | None:
        return self._datp.device_registry.get(device_id)

    def _build_device_info(self, device_entry: dict, *, device_id: str | None = None) -> dict[str, Any]:
        """Build a clean device info dict from a device registry entry."""
        resolved_device_id = device_id or device_entry.get("device_id", "unknown")
        info = {
            "device_id": resolved_device_id,
            "session_id": device_entry.get("session_id"),
            "online": True,
            "capabilities": device_entry.get("capabilities", {}),
        }
        # Merge registry info if available
        registry = self._datp.registry
        if registry:
            dev_info = registry._store.get_device(info["device_id"])
            if dev_info:
                info["device_type"] = dev_info.device_type
                info["connected_at"] = dev_info.connected_at.isoformat() if dev_info.connected_at else None
                info["last_seen"] = dev_info.last_seen.isoformat() if dev_info.last_seen else None
                info["state"] = dev_info.state or {}
                info["muted_until"] = dev_info.muted_until.isoformat() if dev_info.muted_until else None
                info["character_pack_id"] = dev_info.character_pack_id
        return info

    def _get_routing_policy(self) -> RoutingPolicy:
        """Get or create the routing policy instance."""
        if self._routing_policy is None:
            self._routing_policy = RoutingPolicy(self._datp)
        return self._routing_policy

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    async def _health(self, request: web.Request) -> web.Response:
        """GET /api/health — gateway health + device count."""
        online_count = 0
        if self._datp.registry:
            online_count = self._datp.registry.online_count

        # Check DATP server status
        datp_running = (
            self._datp._server is not None
            and not self._datp._stopping
        )

        return self._json_response({
            "status": "ok",
            "datp_running": datp_running,
            "devices_online": online_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    async def _devices_list(self, request: web.Request) -> web.Response:
        """GET /api/devices — list all connected devices."""
        devices = []
        for device_id, entry in self._datp.device_registry.items():
            devices.append(self._build_device_info(entry, device_id=device_id))

        return self._json_response({
            "devices": devices,
            "count": len(devices),
        })

    async def _device_info(self, request: web.Request) -> web.Response:
        """GET /api/devices/{device_id} — full state of one device."""
        device_id = request.match_info["device_id"]

        entry = self._require_registered_device(device_id)
        if entry is None:
            return self._error_response(f"Device '{device_id}' not found", 404)

        return self._json_response(self._build_device_info(entry, device_id=device_id))

    async def _cmd_show_status(self, request: web.Request) -> web.Response:
        """POST /api/devices/{device_id}/commands/show_status — display.show_status."""
        device_id = request.match_info["device_id"]
        body = await self._read_json(request)

        state = body.get("state")
        if not state:
            return self._error_response("Missing required field: state")

        label = body.get("label")

        if self._require_registered_device(device_id) is None:
            return self._error_response(f"Device '{device_id}' not found", 404)

        label_arg = label or None

        ok = await self._dispatcher.show_status(device_id, state, label_arg)
        return self._json_response({
            "ok": ok,
            "device_id": device_id,
            "command": "display.show_status",
            "state": state,
            "label": label,
        })

    async def _cmd_mute_until(self, request: web.Request) -> web.Response:
        """POST /api/devices/{device_id}/commands/mute_until — device.mute_until."""
        device_id = request.match_info["device_id"]
        body = await self._read_json(request)

        minutes = body.get("minutes")
        if minutes is None:
            return self._error_response("Missing required field: minutes")

        try:
            minutes = int(minutes)
        except (TypeError, ValueError):
            return self._error_response("minutes must be an integer")

        if minutes < 0:
            return self._error_response("minutes must be non-negative")

        if self._require_registered_device(device_id) is None:
            return self._error_response(f"Device '{device_id}' not found", 404)

        until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        until_str = self._format_utc_timestamp(until)

        ok = await self._dispatcher.mute_until(device_id, until_str)

        return self._json_response({
            "ok": ok,
            "device_id": device_id,
            "command": "device.mute_until",
            "minutes": minutes,
            "until": until_str,
        })

    async def _cmd_audio_play(self, request: web.Request) -> web.Response:
        """POST /api/devices/{device_id}/commands/audio_play — play cached audio."""
        device_id = request.match_info["device_id"]
        body = await self._read_json(request)

        response_id = body.get("response_id", "latest")

        if self._require_registered_device(device_id) is None:
            return self._error_response(f"Device '{device_id}' not found", 404)

        ok = await self._dispatcher.audio_play(device_id, response_id)

        return self._json_response({
            "ok": ok,
            "device_id": device_id,
            "command": "audio.play",
            "response_id": response_id,
        })

    # ------------------------------------------------------------------
    # Character Pack Routes
    # ------------------------------------------------------------------

    async def _character_packs_list(self, request: web.Request) -> web.Response:
        """GET /api/character_packs — list available character packs."""
        if self._pack_service is None:
            return self._json_response({
                "packs": [],
                "count": 0,
            })

        packs = self._pack_service.list_packs()
        return self._json_response({
            "packs": [pack.to_dict() for pack in packs],
            "count": len(packs),
        })

    async def _character_pack_info(self, request: web.Request) -> web.Response:
        """GET /api/character_packs/{pack_id} — get character pack details."""
        pack_id = request.match_info["pack_id"]

        if self._pack_service is None:
            return self._error_response("Character pack service not configured", 500)

        pack = self._pack_service.get_pack(pack_id)
        if pack is None:
            return self._error_response(f"Character pack '{pack_id}' not found", 404)

        return self._json_response(pack.to_dict())

    async def _set_device_character(self, request: web.Request) -> web.Response:
        """POST /api/devices/{device_id}/character — set character pack for device."""
        device_id = request.match_info["device_id"]
        body = await self._read_json(request)

        if "pack_id" not in body:
            return self._error_response("Missing required field: pack_id")
        pack_id = body.get("pack_id")

        # Check device exists in registry
        registry = self._datp.registry
        if registry is None:
            return self._error_response("Registry not configured", 500)

        info = await registry.get_device(device_id)
        if info is None:
            return self._error_response(f"Device '{device_id}' not found", 404)

        # Validate pack exists if pack_id is provided (not null).
        if pack_id is not None and self._pack_service is not None:
            pack = self._pack_service.get_pack(pack_id)
            if pack is None:
                return self._error_response(f"Character pack '{pack_id}' not found", 404)

        # Set the character pack (use None to clear)
        success = await registry.set_character_pack(device_id, pack_id)

        if not success:
            return self._error_response(f"Failed to set character pack for device '{device_id}'", 500)

        return self._json_response({
            "ok": True,
            "device_id": device_id,
            "character_pack_id": pack_id,
        })

    # ------------------------------------------------------------------
    # Route Endpoints
    # ------------------------------------------------------------------

    async def _route(self, request: web.Request) -> web.Response:
        """POST /api/route — TTS + cache audio to device(s).

        Supports multiple modes:
        1. Single device (backward compatible): { "device_id": "...", "text": "..." }
        2. Multi device explicit: { "device_ids": ["...", "..."], "text": "..." }
        3. Auto-routing (no devices specified): { "text": "...", "force_multiple": bool }

        With multi-device mode, the routing policy is applied to select
        appropriate devices based on content length and capabilities.

        For each selected device:
        1. Synthesizes the text via TTS
        2. Sends audio.cache.put_begin/chunk/end to the device
        3. Returns the response_id(s)
        """
        body = await self._read_json(request)

        text = body.get("text", "").strip()
        if not text:
            return self._error_response("Missing or empty required field: text")

        # Support both single device_id and multiple device_ids
        device_ids_raw = body.get("device_ids")
        single_device_id = body.get("device_id")

        routing_policy = self._get_routing_policy()

        if device_ids_raw is not None:
            # Multi-device mode: device_ids array provided
            if not isinstance(device_ids_raw, list):
                return self._error_response("device_ids must be an array")
            if len(device_ids_raw) == 0:
                return self._error_response("device_ids array cannot be empty")

            # Validate all device IDs exist
            missing_devices = [
                device_id for device_id in device_ids_raw
                if self._require_registered_device(device_id) is None
            ]
            if missing_devices:
                return self._error_response(
                    f"Device(s) not found: {', '.join(missing_devices)}", 404
                )

            route_request = RouteRequest(
                text=text,
                device_ids=device_ids_raw,
            )
        elif single_device_id:
            # Single device mode (backward compatible)
            if self._require_registered_device(single_device_id) is None:
                return self._error_response(f"Device '{single_device_id}' not found", 404)

            route_request = RouteRequest(
                text=text,
                single_device_id=single_device_id,
            )
        else:
            # No devices specified - use routing policy
            force_multiple = body.get("force_multiple", False)
            route_request = RouteRequest(
                text=text,
                force_multiple=force_multiple,
            )

        # Evaluate routing policy
        route_result = routing_policy.evaluate(route_request)

        if not route_result.success:
            errors = "; ".join(route_result.errors) if route_result.errors else "Routing failed"
            return self._error_response(errors, 500)

        # Route to all selected devices
        return await self._route_to_devices(
            text=text,
            device_ids=route_result.device_ids,
            policy_reason=route_result.policy_reason,
            estimated_duration=route_result.estimated_duration,
            is_long_response=route_result.is_long_response,
        )

    async def _route_multi(self, request: web.Request) -> web.Response:
        """POST /api/route/multi — Multi-device routing with policy selection.

        Takes { "text": "...", "force_multiple": bool } and:
        1. Applies routing policy to select appropriate devices
        2. Routes to all selected devices
        3. Returns detailed routing information

        This endpoint always uses the routing policy to select devices
        based on content length and capabilities.
        """
        body = await self._read_json(request)

        text = body.get("text", "").strip()
        if not text:
            return self._error_response("Missing or empty required field: text")

        force_multiple = body.get("force_multiple", False)

        route_request = RouteRequest(
            text=text,
            force_multiple=force_multiple,
        )

        routing_policy = self._get_routing_policy()
        route_result = routing_policy.evaluate(route_request)

        if not route_result.success:
            errors = "; ".join(route_result.errors) if route_result.errors else "Routing failed"
            return self._error_response(errors, 500)

        # Route to all selected devices
        return await self._route_to_devices(
            text=text,
            device_ids=route_result.device_ids,
            policy_reason=route_result.policy_reason,
            estimated_duration=route_result.estimated_duration,
            is_long_response=route_result.is_long_response,
        )

    async def _route_to_devices(
        self,
        text: str,
        device_ids: list[str],
        policy_reason: str,
        estimated_duration: float,
        is_long_response: bool,
    ) -> web.Response:
        """Route TTS audio to multiple devices.

        Parameters
        ----------
        text : str
            Text to synthesize.
        device_ids : list[str]
            Target device IDs.
        policy_reason : str
            Human-readable routing reason.
        estimated_duration : float
            Estimated audio duration.
        is_long_response : bool
            Whether this is a long response.

        Returns
        -------
        web.Response
            JSON response with routing results.
        """
        from audio.tts import StubTtsBackend

        tts = self._tts or StubTtsBackend()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

        # Run TTS synthesis once (shared across devices)
        try:
            wav_bytes = await asyncio.to_thread(tts.synthesize, text)
        except Exception as exc:
            logger.exception("TTS synthesis failed: %s", exc)
            return self._json_response({
                "error": f"TTS synthesis failed: {exc}",
            }, 500)

        if not wav_bytes:
            return self._json_response({
                "error": "TTS returned empty audio",
            }, 500)

        # Extract PCM chunks
        from audio.tts import _wav_to_pcm_chunks

        pcm_chunks = _wav_to_pcm_chunks(wav_bytes, 1024)
        if not pcm_chunks:
            return self._json_response({
                "error": "No PCM data extracted from WAV",
            }, 500)

        # Route to each device
        results: list[dict[str, Any]] = []
        errors: list[str] = []

        for device_id in device_ids:
            response_id = f"resp_{timestamp}_{device_id[:8]}"
            device_result = await self._send_audio_to_device(
                device_id, response_id, pcm_chunks
            )
            if device_result:
                results.append(device_result)
            else:
                errors.append(f"Failed to route to '{device_id}'")

        if not results and errors:
            return self._json_response({
                "error": "; ".join(errors),
                "device_errors": errors,
            }, 500)

        return self._json_response({
            "ok": True,
            "text": text,
            "device_ids": device_ids,
            "devices": results,
            "routing": {
                "policy_reason": policy_reason,
                "estimated_duration_seconds": round(estimated_duration, 1),
                "is_long_response": is_long_response,
            },
            "chunks_per_device": len(pcm_chunks),
        })

    async def _send_audio_to_device(
        self,
        device_id: str,
        response_id: str,
        pcm_chunks: list[bytes],
    ) -> dict[str, Any] | None:
        """Send audio chunks to a single device.

        Parameters
        ----------
        device_id : str
            Target device ID.
        response_id : str
            Response identifier.
        pcm_chunks : list[bytes]
            PCM audio chunks.

        Returns
        -------
        dict or None
            Device result dict if successful, None if failed.
        """
        from audio.tts import encode_pcm_to_base64

        try:
            # Send cache_put_begin
            ok = await self._dispatcher.cache_put_begin(device_id, response_id)
            if not ok:
                logger.warning("cache_put_begin failed for device %s", device_id)
                return None

            # Send chunks
            for seq, pcm_chunk in enumerate(pcm_chunks):
                data_b64 = encode_pcm_to_base64(pcm_chunk)
                ok = await self._dispatcher.cache_put_chunk(device_id, response_id, seq, data_b64)
                if not ok:
                    logger.warning("cache_put_chunk (seq=%d) failed for device %s", seq, device_id)
                    return None

            # Send cache_put_end
            ok = await self._dispatcher.cache_put_end(device_id, response_id)
            if not ok:
                logger.warning("cache_put_end failed for device %s", device_id)
                return None

            return {
                "device_id": device_id,
                "response_id": response_id,
                "chunks_sent": len(pcm_chunks),
            }
        except Exception as exc:
            logger.exception("Error sending audio to device %s: %s", device_id, exc)
            return None

    # ------------------------------------------------------------------
    # Stability / Foreground / Health Endpoints
    # ------------------------------------------------------------------

    async def _set_foreground(self, request: web.Request) -> web.Response:
        """POST /api/devices/{device_id}/foreground — Set device as foreground.

        Sets the device's foreground priority higher than all other devices.
        """
        device_id = request.match_info["device_id"]

        if self._require_registered_device(device_id) is None:
            return self._error_response(f"Device '{device_id}' not found", 404)

        if self._datp.registry is None:
            return self._error_response("Registry not available", 500)

        ok = await self._datp.registry.set_foreground_device(device_id)
        if not ok:
            return self._error_response(f"Could not set device '{device_id}' as foreground", 400)

        return self._json_response({
            "ok": True,
            "device_id": device_id,
            "message": "Device set as foreground",
        })

    async def _device_health(self, request: web.Request) -> web.Response:
        """GET /api/devices/{device_id}/health — Get device health status."""
        device_id = request.match_info["device_id"]

        if self._datp.registry is None:
            return self._error_response("Registry not available", 500)

        health = self._datp.registry.get_health_status(device_id)
        if health is None:
            return self._error_response(f"Device '{device_id}' not found", 404)

        return self._json_response({
            "device_id": device_id,
            "is_healthy": health["is_healthy"],
            "is_online": health["is_online"],
            "last_heartbeat": health["last_heartbeat"],
            "heartbeat_timeout": health["heartbeat_timeout"],
        })

    async def _record_interaction(self, request: web.Request) -> web.Response:
        """POST /api/devices/{device_id}/interactions — Record a device interaction.

        Updates the last_interaction timestamp for foreground selection purposes.
        """
        device_id = request.match_info["device_id"]

        if self._datp.registry is None:
            return self._error_response("Registry not available", 500)

        # Check if device exists
        info = await self._datp.registry.get_device(device_id)
        if info is None:
            return self._error_response(f"Device '{device_id}' not found", 404)

        await self._datp.registry.update_last_interaction(device_id)

        # Get updated info to return the timestamp
        updated = await self._datp.registry.get_device(device_id)
        last_interaction = None
        if updated and updated.last_interaction:
            last_interaction = updated.last_interaction.isoformat()

        return self._json_response({
            "ok": True,
            "device_id": device_id,
            "last_interaction": last_interaction,
        })

    # ------------------------------------------------------------------
    # Coding Workflow Endpoints
    # ------------------------------------------------------------------

    async def _coding_status(self, request: web.Request) -> web.Response:
        """GET /api/coding/status — Get coding workflow status.

        Returns current state including active request and history.
        """
        if self._coding_service is None:
            return self._json_response({
                "enabled": False,
                "status": "not_configured",
                "message": "Coding workflow service not configured",
            })

        status = self._coding_service.get_status()
        return self._json_response({
            "enabled": self._coding_service.enabled,
            **status,
        })

    async def _coding_last_result(self, request: web.Request) -> web.Response:
        """GET /api/coding/last_result — Get last completed workflow result.

        Returns the summary and diff from the last completed coding workflow.
        """
        if self._coding_service is None:
            return self._error_response("Coding workflow service not configured", 500)

        result = self._coding_service.get_last_result()
        if result is None:
            return self._json_response({
                "available": False,
                "message": "No completed coding workflow results",
            })

        return self._json_response({
            "available": True,
            **result,
        })

    async def _coding_enable(self, request: web.Request) -> web.Response:
        """POST /api/coding/enable — Enable the coding workflow service."""
        if self._coding_service is None:
            return self._error_response("Coding workflow service not configured", 500)

        self._coding_service.enable()
        return self._json_response({
            "ok": True,
            "enabled": True,
            "message": "Coding workflow service enabled",
        })

    async def _coding_disable(self, request: web.Request) -> web.Response:
        """POST /api/coding/disable — Disable the coding workflow service."""
        if self._coding_service is None:
            return self._error_response("Coding workflow service not configured", 500)

        self._coding_service.disable()
        return self._json_response({
            "ok": True,
            "enabled": False,
            "message": "Coding workflow service disabled",
        })

    async def _coding_clear_history(self, request: web.Request) -> web.Response:
        """POST /api/coding/clear_history — Clear workflow history."""
        if self._coding_service is None:
            return self._error_response("Coding workflow service not configured", 500)

        self._coding_service.clear_history()
        return self._json_response({
            "ok": True,
            "message": "Coding workflow history cleared",
        })
