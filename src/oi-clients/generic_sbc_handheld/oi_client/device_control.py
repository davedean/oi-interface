from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


def _coerce_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    message: str = ""


class DeviceController:
    def __init__(
        self,
        *,
        run_command: Callable[[list[str]], subprocess.CompletedProcess] | None = None,
        write_text: Callable[[Path, str], None] | None = None,
        now: Callable[[], float] | None = None,
        allow_destructive: bool | None = None,
    ) -> None:
        self._run_command = run_command or self._default_run_command
        self._write_text = write_text or self._default_write_text
        self._now = now or time.time
        self._allow_destructive = allow_destructive if allow_destructive is not None else os.getenv("OI_ENABLE_POWER_COMMANDS") == "1"
        self._muted_until_epoch: float | None = None
        self._muted_until_raw: str | None = None
        self._brightness = 100
        self._volume = 80
        self._led_enabled = True

    @staticmethod
    def _default_run_command(command: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(command, capture_output=True, text=True)

    @staticmethod
    def _default_write_text(path: Path, data: str) -> None:
        path.write_text(data)

    @property
    def muted_until(self) -> str | None:
        if not self.is_muted():
            return None
        return self._muted_until_raw

    @property
    def brightness(self) -> int:
        return self._brightness

    @property
    def volume(self) -> int:
        return self._volume

    @property
    def led_enabled(self) -> bool:
        return self._led_enabled

    def is_muted(self) -> bool:
        if self._muted_until_epoch is None:
            return False
        if self._now() >= self._muted_until_epoch:
            self.clear_mute()
            return False
        return True

    def clear_mute(self) -> None:
        self._muted_until_epoch = None
        self._muted_until_raw = None

    def apply(self, op: str, args: dict | None = None) -> CommandResult:
        args = args or {}
        if op == "device.mute_until":
            return self._mute_until(str(args.get("until", "")))
        if op == "device.set_brightness":
            return self._set_brightness(_coerce_int(args.get("value", self._brightness), self._brightness))
        if op == "device.set_volume":
            return self._set_volume(_coerce_int(args.get("level", self._volume), self._volume))
        if op == "device.set_led":
            return self._set_led(bool(args.get("enabled", self._led_enabled)))
        if op == "device.reboot":
            return self._power_command(["reboot"], "reboot blocked")
        if op == "device.shutdown":
            return self._power_command(["shutdown", "-h", "now"], "shutdown blocked")
        if op == "storage.format":
            return CommandResult(False, "storage.format not supported on generic handheld")
        if op == "wifi.configure":
            return CommandResult(False, "wifi.configure not supported on generic handheld")
        return CommandResult(False, f"unsupported device op: {op}")

    def _mute_until(self, until: str) -> CommandResult:
        try:
            dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return CommandResult(False, f"invalid mute timestamp: {until}")
        self._muted_until_epoch = dt.timestamp()
        self._muted_until_raw = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        if self._muted_until_epoch <= self._now():
            self.clear_mute()
            return CommandResult(True, "mute expired")
        return CommandResult(True, f"muted until {self._muted_until_raw}")

    def _set_brightness(self, value: int) -> CommandResult:
        clamped = max(0, min(255, value))
        self._brightness = clamped
        for path in self._brightness_paths():
            try:
                self._write_text(path, str(clamped))
                return CommandResult(True, f"brightness set to {clamped}")
            except OSError:
                continue
        return CommandResult(True, f"brightness cached at {clamped}")

    def _set_volume(self, level: int) -> CommandResult:
        clamped = max(0, min(100, level))
        self._volume = clamped
        if shutil.which("amixer"):
            result = self._run_command(["amixer", "sset", "Master", f"{clamped}%"])
            if result.returncode == 0:
                return CommandResult(True, f"volume set to {clamped}")
        return CommandResult(True, f"volume cached at {clamped}")

    def _set_led(self, enabled: bool) -> CommandResult:
        self._led_enabled = enabled
        for path in self._led_paths():
            try:
                self._write_text(path, "1" if enabled else "0")
                return CommandResult(True, f"led {'enabled' if enabled else 'disabled'}")
            except OSError:
                continue
        return CommandResult(True, f"led {'enabled' if enabled else 'disabled'} (cached)")

    def _power_command(self, command: list[str], blocked_message: str) -> CommandResult:
        if not self._allow_destructive:
            return CommandResult(False, blocked_message)
        result = self._run_command(command)
        if result.returncode == 0:
            return CommandResult(True, "ok")
        return CommandResult(False, (result.stderr or result.stdout or blocked_message).strip())

    @staticmethod
    def _brightness_paths() -> list[Path]:
        return sorted(Path("/sys/class/backlight").glob("*/brightness"))

    @staticmethod
    def _led_paths() -> list[Path]:
        return sorted(Path("/sys/class/leds").glob("*/brightness"))
