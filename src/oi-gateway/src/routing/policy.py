"""Routing policy for selecting devices based on content and capabilities."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .capabilities import DeviceCapabilities, get_capabilities_for_device_type

if TYPE_CHECKING:
    from datp.server import DATPServer

logger = logging.getLogger(__name__)

# Threshold for considering a response "long" (in estimated seconds)
# Based on ~150 words per minute speaking rate
LONG_RESPONSE_WORD_THRESHOLD = 100  # ~40 seconds of speech


@dataclass
class RouteRequest:
    """Request to route content to one or more devices.

    Parameters
    ----------
    text : str
        The text content to route.
    device_ids : list[str], optional
        Explicit list of device IDs to route to. If provided, policy
        is bypassed and content goes to these devices directly.
    single_device_id : str, optional
        Single device ID for backward compatibility.
    prefer_foreground : bool, optional
        Prefer foreground devices when selecting automatically.
        Default True.
    force_multiple : bool, optional
        Force routing to multiple devices even for short responses.
        Default False.
    """

    text: str
    device_ids: list[str] | None = None
    single_device_id: str | None = None
    prefer_foreground: bool = True
    force_multiple: bool = False

    @property
    def explicit_device_ids(self) -> list[str] | None:
        """Return explicit device IDs if provided."""
        return self.device_ids

    @property
    def has_explicit_devices(self) -> bool:
        """Check if explicit device IDs were provided."""
        return self.device_ids is not None and len(self.device_ids) > 0

    def get_all_device_ids(self) -> list[str]:
        """Get all device IDs (explicit or single)."""
        if self.device_ids:
            return list(self.device_ids)
        if self.single_device_id:
            return [self.single_device_id]
        return []

    def estimate_duration(self) -> float:
        """Estimate audio duration in seconds.

        Based on ~150 words per minute speaking rate.

        Returns
        -------
        float
            Estimated duration in seconds.
        """
        word_count = len(self.text.split())
        return (word_count / 150) * 60


@dataclass
class RouteResult:
    """Result of routing policy evaluation.

    Attributes
    ----------
    device_ids : list[str]
        Selected device IDs for routing.
    policy_reason : str
        Human-readable reason for device selection.
    estimated_duration : float
        Estimated audio duration in seconds.
    is_long_response : bool
        Whether this is considered a long response.
    suitable_foreground : list[str]
        Devices that are suitable as foreground.
    suitable_background : list[str]
        Devices that are suitable as background/dashboard.
    errors : list[str]
        Any errors encountered during routing (e.g., device not found).
    """

    device_ids: list[str] = field(default_factory=list)
    policy_reason: str = ""
    estimated_duration: float = 0.0
    is_long_response: bool = False
    suitable_foreground: list[str] = field(default_factory=list)
    suitable_background: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """Check if routing was successful."""
        return len(self.device_ids) > 0 and len(self.errors) == 0


@dataclass
class DeviceRouteInfo:
    """Internal device routing information."""

    device_id: str
    capabilities: DeviceCapabilities
    device_type: str | None = None


class RoutingPolicy:
    """Policy for selecting devices based on content length and capabilities.

    Routing rules:
    1. If explicit device_ids provided, use them directly (no policy).
    2. Short responses (under LONG_RESPONSE_WORD_THRESHOLD words / ~40s)
       → single foreground device.
    3. Long responses → multiple devices or dashboard if available.
    4. Devices filtered by max_spoken_seconds capability.
    5. If no foreground device available, fall back to any available device.
    """

    def __init__(self, datp_server: DATPServer) -> None:
        """Initialize routing policy.

        Parameters
        ----------
        datp_server : DATPServer
            DATP server for accessing device registry.
        """
        self._datp = datp_server

    def evaluate(self, request: RouteRequest) -> RouteResult:
        """Evaluate routing policy and select target devices.

        Parameters
        ----------
        request : RouteRequest
            Routing request with text and optional device constraints.

        Returns
        -------
        RouteResult
            Policy evaluation result with selected devices.
        """
        # If explicit device IDs provided, use them directly
        if request.has_explicit_devices:
            return self._evaluate_explicit(request)

        # Get all online devices
        device_infos = self._get_online_devices()
        if not device_infos:
            return RouteResult(
                errors=["No devices available for routing"],
                policy_reason="No online devices found",
            )

        # Categorize devices by capability
        foreground = [d for d in device_infos if d.capabilities.is_foreground_device]
        background = [d for d in device_infos if d.capabilities.is_background_device]
        all_suitable = [d for d in device_infos if d.capabilities.is_suitable_for_short_response()]

        result = RouteResult(
            estimated_duration=request.estimate_duration(),
            is_long_response=self._is_long_response(request),
            suitable_foreground=[d.device_id for d in foreground],
            suitable_background=[d.device_id for d in background],
        )

        # Apply routing rules
        if result.is_long_response or request.force_multiple:
            result = self._route_long_response(request, device_infos, foreground, background, result)
        else:
            result = self._route_short_response(request, foreground, all_suitable, result)

        return result

    def _evaluate_explicit(self, request: RouteRequest) -> RouteResult:
        """Handle explicit device selection (no policy).

        Parameters
        ----------
        request : RouteRequest
            Request with explicit device IDs.

        Returns
        -------
        RouteResult
            Result with explicit devices validated.
        """
        device_ids = request.get_all_device_ids()
        result = RouteResult(
            device_ids=device_ids,
            estimated_duration=request.estimate_duration(),
            is_long_response=self._is_long_response(request),
            policy_reason=f"Explicit device selection: {device_ids}",
        )

        # Validate devices exist
        for device_id in device_ids:
            if device_id not in self._datp.device_registry:
                result.errors.append(f"Device '{device_id}' not found")
            else:
                # Get capabilities
                entry = self._datp.device_registry[device_id]
                caps_data = entry.get("capabilities", {})
                caps = DeviceCapabilities.from_dict(caps_data)
                if caps.is_foreground_device:
                    result.suitable_foreground.append(device_id)
                if caps.is_background_device:
                    result.suitable_background.append(device_id)

        if result.errors:
            result.policy_reason = "Explicit selection with errors"
        else:
            result.policy_reason = f"Routed to explicit devices: {device_ids}"

        return result

    def _get_online_devices(self) -> list[DeviceRouteInfo]:
        """Get all online devices with parsed capabilities.

        Returns
        -------
        list[DeviceRouteInfo]
            List of online device info.
        """
        devices: list[DeviceRouteInfo] = []
        for device_id in self._datp.device_registry:
            entry = self._datp.device_registry[device_id]
            caps_data = entry.get("capabilities", {})

            # Try to get device type from registry for profile lookup
            device_type = None
            if self._datp.registry:
                dev_info = self._datp.registry._store.get_device(device_id)
                if dev_info:
                    device_type = dev_info.device_type

            # Parse capabilities
            try:
                caps = DeviceCapabilities.from_dict(caps_data)
            except (TypeError, AttributeError):
                # Fall back to default or profile
                if device_type:
                    caps = get_capabilities_for_device_type(device_type)
                else:
                    caps = DeviceCapabilities()

            devices.append(DeviceRouteInfo(
                device_id=device_id,
                capabilities=caps,
                device_type=device_type,
            ))

        return devices

    def _is_long_response(self, request: RouteRequest) -> bool:
        """Determine if the response is considered "long".

        Parameters
        ----------
        request : RouteRequest
            Routing request.

        Returns
        -------
        bool
            True if response is long.
        """
        word_count = len(request.text.split())
        return word_count > LONG_RESPONSE_WORD_THRESHOLD

    def _route_short_response(
        self,
        request: RouteRequest,
        foreground: list[DeviceRouteInfo],
        all_suitable: list[DeviceRouteInfo],
        result: RouteResult,
    ) -> RouteResult:
        """Route a short response to a single foreground device.

        Parameters
        ----------
        request : RouteRequest
            Routing request.
        foreground : list[DeviceRouteInfo]
            Available foreground devices.
        all_suitable : list[DeviceRouteInfo]
            All suitable devices.
        result : RouteResult
            Result to update.

        Returns
        -------
        RouteResult
            Updated result.
        """
        estimated_duration = request.estimate_duration()

        # Filter by duration capability
        capable_foreground = [
            d for d in foreground
            if d.capabilities.can_speak_duration(estimated_duration)
        ]

        if capable_foreground:
            selected = capable_foreground[0]  # Pick first capable foreground
            result.device_ids = [selected.device_id]
            result.policy_reason = (
                f"Short response (~{estimated_duration:.0f}s) routed to "
                f"foreground device '{selected.device_id}'"
            )
        elif all_suitable:
            # Fall back to any suitable device
            selected = all_suitable[0]
            result.device_ids = [selected.device_id]
            result.policy_reason = (
                f"No capable foreground device; routed to '{selected.device_id}'"
            )
        else:
            result.errors.append("No suitable devices available for short response")
            result.policy_reason = "No suitable devices found"

        return result

    def _route_long_response(
        self,
        request: RouteRequest,
        all_devices: list[DeviceRouteInfo],
        foreground: list[DeviceRouteInfo],
        background: list[DeviceRouteInfo],
        result: RouteResult,
    ) -> RouteResult:
        """Route a long response to multiple devices.

        Parameters
        ----------
        request : RouteRequest
            Routing request.
        all_devices : list[DeviceRouteInfo]
            All available devices.
        foreground : list[DeviceRouteInfo]
            Available foreground devices.
        background : list[DeviceRouteInfo]
            Available background/dashboard devices.
        result : RouteResult
            Result to update.

        Returns
        -------
        RouteResult
            Updated result.
        """
        estimated_duration = request.estimate_duration()
        selected_ids: list[str] = []

        # Filter by duration capability
        capable_foreground = [
            d for d in foreground
            if d.capabilities.can_speak_duration(estimated_duration)
        ]
        capable_background = [
            d for d in background
            if d.capabilities.can_speak_duration(estimated_duration)
        ]

        # Long response strategy:
        # 1. Primary foreground device (audio)
        # 2. Dashboard/background devices (visual notification)
        if capable_foreground:
            selected_ids.append(capable_foreground[0].device_id)

        if capable_background:
            selected_ids.extend([d.device_id for d in capable_background])

        # If no background available, route to all capable foreground devices
        if not selected_ids and capable_foreground:
            selected_ids = [d.device_id for d in capable_foreground]

        if selected_ids:
            result.device_ids = selected_ids
            result.policy_reason = (
                f"Long response (~{estimated_duration:.0f}s) routed to {len(selected_ids)} device(s)"
            )
        else:
            # Last resort: any device that can handle the duration
            capable_any = [
                d for d in all_devices
                if d.capabilities.can_speak_duration(estimated_duration)
            ]
            if capable_any:
                result.device_ids = [capable_any[0].device_id]
                result.policy_reason = (
                    f"No optimal devices found; routed to '{capable_any[0].device_id}'"
                )
            else:
                result.errors.append(
                    f"No devices can handle ~{estimated_duration:.0f}s audio duration"
                )
                result.policy_reason = "No devices capable of long response"

        return result


def route_to_devices(
    datp_server: DATPServer,
    request: RouteRequest,
) -> RouteResult:
    """Convenience function to route content to devices.

    Parameters
    ----------
    datp_server : DATPServer
        DATP server instance.
    request : RouteRequest
        Routing request.

    Returns
    -------
    RouteResult
        Routing result.
    """
    policy = RoutingPolicy(datp_server)
    return policy.evaluate(request)
