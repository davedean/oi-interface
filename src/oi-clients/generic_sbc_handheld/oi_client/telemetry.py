from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


class TelemetryCollector:
    def __init__(self, *, start_time: float | None = None) -> None:
        self._start_time = start_time or time.time()

    def collect(self, *, mode: str, muted_until: str | None, audio_cache_used_bytes: int = 0) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "mode": mode,
            "muted_until": muted_until,
            "uptime_s": max(0, int(time.time() - self._start_time)),
            "audio_cache_used_bytes": max(0, audio_cache_used_bytes),
        }
        battery = self._battery_info()
        if battery:
            payload.update(battery)
        wifi_rssi = self._wifi_rssi()
        if wifi_rssi is not None:
            payload["wifi_rssi"] = wifi_rssi
        heap_free = self._heap_free()
        if heap_free is not None:
            payload["heap_free"] = heap_free
        return payload

    def _battery_info(self) -> dict[str, Any]:
        for supply in Path("/sys/class/power_supply").glob("*"):
            battery_type = (supply / "type")
            try:
                if battery_type.read_text().strip().lower() != "battery":
                    continue
            except OSError:
                continue

            info: dict[str, Any] = {}
            capacity = _read_int(supply / "capacity")
            if capacity is not None:
                info["battery_percent"] = capacity
            try:
                status = (supply / "status").read_text().strip().lower()
                info["charging"] = status == "charging"
            except OSError:
                pass
            if info:
                return info
        return {}

    def _wifi_rssi(self) -> int | None:
        if not shutil.which("iwconfig"):
            return None
        try:
            result = subprocess.run(["iwconfig"], capture_output=True, text=True, timeout=2)
        except (OSError, subprocess.SubprocessError):
            return None
        for token in result.stdout.split():
            if token.startswith("level="):
                try:
                    return int(token.split("=", 1)[1].rstrip("dBm"))
                except ValueError:
                    return None
        return None

    def _heap_free(self) -> int | None:
        try:
            pages = os.sysconf("SC_AVPHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
        except (ValueError, OSError, AttributeError):
            return None
        return int(pages * page_size)
