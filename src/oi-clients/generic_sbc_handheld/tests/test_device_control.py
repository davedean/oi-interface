from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from oi_client.device_control import DeviceController  # noqa: E402


class FakeClock:
    def __init__(self, now: float) -> None:
        self.value = now

    def __call__(self) -> float:
        return self.value


def test_mute_until_tracks_and_expires() -> None:
    clock = FakeClock(1_000.0)
    ctl = DeviceController(now=clock)
    result = ctl.apply("device.mute_until", {"until": "1970-01-01T00:20:00.000Z"})
    assert result.ok is True
    assert ctl.is_muted() is True
    clock.value = 1_300.0
    assert ctl.is_muted() is False
    assert ctl.muted_until is None


def test_brightness_and_led_cache_without_sysfs() -> None:
    writes: list[tuple[str, str]] = []

    def write_text(path: Path, data: str) -> None:
        writes.append((str(path), data))
        raise OSError("no sysfs")

    ctl = DeviceController(write_text=write_text)
    brightness = ctl.apply("device.set_brightness", {"value": 999})
    led = ctl.apply("device.set_led", {"enabled": False})
    assert brightness.ok is True
    assert ctl.brightness == 255
    assert led.ok is True
    assert ctl.led_enabled is False
    assert writes == []


def test_invalid_numeric_args_fall_back_without_crashing() -> None:
    ctl = DeviceController()
    assert ctl.apply("device.set_brightness", {"value": "abc"}).ok is True
    assert ctl.brightness == 100
    assert ctl.apply("device.set_volume", {"level": "abc"}).ok is True
    assert ctl.volume == 80


def test_volume_and_power_commands_are_safe_by_default() -> None:
    seen: list[list[str]] = []

    def run_command(command: list[str]):
        seen.append(command)
        class Result:
            returncode = 0
            stdout = ""
            stderr = ""
        return Result()

    ctl = DeviceController(run_command=run_command)
    volume = ctl.apply("device.set_volume", {"level": 42})
    reboot = ctl.apply("device.reboot", {})
    shutdown = ctl.apply("device.shutdown", {})
    assert volume.ok is True
    assert ctl.volume == 42
    assert reboot.ok is False
    assert shutdown.ok is False
    assert seen == []
