"""Device capability definitions and validation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class CapabilityError(ValueError):
    """Raised when device capabilities are invalid or missing required fields."""


@dataclass
class DeviceCapabilities:
    """Parsed and validated device capability record.

    Parameters
    ----------
    max_spoken_seconds : float, optional
        Maximum duration of audio this device can speak. Used to determine
        if a response should be routed here. Default 120 seconds.
    supports_confirm_buttons : bool, optional
        Whether the device supports interactive confirmation buttons.
        Default False.
    supports_display : bool, optional
        Whether the device has a display for showing cards/status.
        Default False.
    is_foreground_device : bool, optional
        Whether this device is a primary foreground device (e.g., speaker).
        Default True.
    is_background_device : bool, optional
        Whether this device is a background/dashboard device.
        Default False.
    supports_long_audio : bool, optional
        Whether the device can handle long-form audio responses.
        Default True.
    capabilities : dict, optional
        Raw capabilities dict for extensibility.
    """

    max_spoken_seconds: float = 120.0
    supports_confirm_buttons: bool = False
    supports_display: bool = False
    is_foreground_device: bool = True
    is_background_device: bool = False
    supports_long_audio: bool = True
    display_width: int = 0
    display_height: int = 0
    has_audio_input: bool = False
    has_audio_output: bool = False
    capabilities: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> DeviceCapabilities:
        """Parse capabilities from a raw device hello payload.

        Parameters
        ----------
        data : dict or None
            Raw capabilities dict from device hello.

        Returns
        -------
        DeviceCapabilities
            Validated capability record.
        """
        if data is None:
            return cls()

        return cls(
            max_spoken_seconds=data.get("max_spoken_seconds", 120.0),
            supports_confirm_buttons=data.get("supports_confirm_buttons", False),
            supports_display=data.get("supports_display", False),
            is_foreground_device=data.get("is_foreground_device", True),
            is_background_device=data.get("is_background_device", False),
            supports_long_audio=data.get("supports_long_audio", True),
            display_width=data.get("display_width", 0),
            display_height=data.get("display_height", 0),
            has_audio_input=data.get("has_audio_input", False),
            has_audio_output=data.get("has_audio_output", False),
            capabilities=data,
        )

    def can_speak_duration(self, duration_seconds: float) -> bool:
        """Check if this device can handle audio of the given duration.

        Parameters
        ----------
        duration_seconds : float
            Estimated audio duration.

        Returns
        -------
        bool
            True if duration fits within max_spoken_seconds.
        """
        return duration_seconds <= self.max_spoken_seconds

    def is_suitable_for_short_response(self) -> bool:
        """Check if this device is suitable for short responses (<30s).

        Short responses should go to a single foreground device.

        Returns
        -------
        bool
            True if this is a foreground device.
        """
        return self.is_foreground_device

    def is_suitable_for_long_response(self) -> bool:
        """Check if this device can handle long responses.

        Long responses may be routed to multiple devices.

        Returns
        -------
        bool
            True if this device supports long audio.
        """
        return self.supports_long_audio

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON responses.

        Returns
        -------
        dict
            Capability record as dict.
        """
        return {
            "max_spoken_seconds": self.max_spoken_seconds,
            "supports_confirm_buttons": self.supports_confirm_buttons,
            "supports_display": self.supports_display,
            "is_foreground_device": self.is_foreground_device,
            "is_background_device": self.is_background_device,
            "supports_long_audio": self.supports_long_audio,
            "display_width": self.display_width,
            "display_height": self.display_height,
            "has_audio_input": self.has_audio_input,
            "has_audio_output": self.has_audio_output,
        }


# ------------------------------------------------------------------
# Default capability profiles
# ------------------------------------------------------------------

DEFAULT_CAPABILITIES = DeviceCapabilities()


def get_capabilities_for_device_type(
    device_type: str,
    overrides: dict[str, Any] | None = None,
) -> DeviceCapabilities:
    """Get a capability profile for a known device type.

    Parameters
    ----------
    device_type : str
        Device type identifier (e.g., 'speaker', 'display', 'dashboard').
    overrides : dict, optional
        Override specific capability fields.

    Returns
    -------
    DeviceCapabilities
        Capability profile for the device type.
    """
    profiles: dict[str, dict[str, Any]] = {
        "speaker": {
            "max_spoken_seconds": 120.0,
            "supports_confirm_buttons": True,
            "supports_display": False,
            "is_foreground_device": True,
            "is_background_device": False,
            "supports_long_audio": True,
            "display_width": 0,
            "display_height": 0,
            "has_audio_input": False,
            "has_audio_output": True,
        },
        "display": {
            "max_spoken_seconds": 60.0,
            "supports_confirm_buttons": True,
            "supports_display": True,
            "is_foreground_device": True,
            "is_background_device": False,
            "supports_long_audio": True,
            "display_width": 80,
            "display_height": 10,
            "has_audio_input": False,
            "has_audio_output": True,
        },
        "cli": {
            "max_spoken_seconds": 120.0,
            "supports_confirm_buttons": False,
            "supports_display": False,
            "is_foreground_device": True,
            "is_background_device": False,
            "supports_long_audio": True,
            "display_width": 80,
            "display_height": 10,
            "has_audio_input": False,
            "has_audio_output": False,
        },
        "dashboard": {
            "max_spoken_seconds": 300.0,
            "supports_confirm_buttons": False,
            "supports_display": True,
            "is_foreground_device": False,
            "is_background_device": True,
            "supports_long_audio": True,
            "display_width": 160,
            "display_height": 64,
            "has_audio_input": False,
            "has_audio_output": True,
        },
        "watch": {
            "max_spoken_seconds": 30.0,
            "supports_confirm_buttons": True,
            "supports_display": True,
            "is_foreground_device": True,
            "is_background_device": False,
            "supports_long_audio": False,
            "display_width": 40,
            "display_height": 8,
            "has_audio_input": True,
            "has_audio_output": True,
        },
        "phone": {
            "max_spoken_seconds": 180.0,
            "supports_confirm_buttons": True,
            "supports_display": True,
            "is_foreground_device": True,
            "is_background_device": False,
            "supports_long_audio": True,
            "display_width": 48,
            "display_height": 20,
            "has_audio_input": True,
            "has_audio_output": True,
        },
        "stick": {
            "max_spoken_seconds": 60.0,
            "supports_confirm_buttons": True,
            "supports_display": True,
            "is_foreground_device": True,
            "is_background_device": False,
            "supports_long_audio": True,
            "display_width": 24,
            "display_height": 6,
            "has_audio_input": True,
            "has_audio_output": True,
        },
        "unknown": {
            "max_spoken_seconds": 120.0,
            "supports_confirm_buttons": False,
            "supports_display": False,
            "is_foreground_device": True,
            "is_background_device": False,
            "supports_long_audio": True,
            "display_width": 0,
            "display_height": 0,
            "has_audio_input": False,
            "has_audio_output": False,
        },
    }

    profile = profiles.get(device_type.lower(), profiles["unknown"]).copy()
    if overrides:
        profile.update(overrides)

    return DeviceCapabilities(**profile)
