#!/usr/bin/env python3
"""Oi device runtime for Linux SBC handhelds.

Entry point. Usage on device:
    cd /storage/roms/ports/Oi
    python3 -m oi_client
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# Ensure SDL2 DLL path before any sdl2 import
os.environ.setdefault("PYSDL2_DLL_PATH", "/usr/lib")

# Vendor path — add before other imports so vendored deps take precedence
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VENDOR_LIB = os.path.join(_SCRIPT_DIR, "lib")
if os.path.isdir(VENDOR_LIB) and VENDOR_LIB not in sys.path:
    sys.path.insert(0, VENDOR_LIB)

# PortMaster fallback for pysdl2
if "sdl2" not in sys.modules:
    for pm_exlibs in (
        "/mnt/mmc/MUOS/PortMaster/exlibs",
        "/storage/roms/ports/PortMaster/exlibs",
        "/roms/ports/PortMaster/exlibs",
    ):
        if os.path.isdir(pm_exlibs) and pm_exlibs not in sys.path:
            sys.path.insert(0, pm_exlibs)
            break


# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------

CONFIG_DIR = os.path.expanduser("~/.config/oi")
LOG_PATH = os.path.join(_SCRIPT_DIR, "oi.log")
DEFAULT_CONFIG = {
    "gateway_url": "ws://localhost:8788/datp",
    "device_id": "sbc-handheld-001",
    "device_type": "sbc-handheld",
    "character_size": "big",
    "show_progress_messages": True,
    "show_celebrations": True,
    "brightness": 255,
    "volume": 80,
    "led_enabled": True,
    "mute_duration_hours": 24,
    "backend_id": None,
    "agent_id": None,
    "session_key": None,
}


def setup_logging():
    import logging
    handler = logging.FileHandler(LOG_PATH, mode="a")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    return handler


def load_config() -> tuple[dict, str]:
    # First: try GAMEDIR/config.json (where launcher writes)
    gamedir_conf = os.path.join(os.path.dirname(_SCRIPT_DIR), "config.json")
    print(f"[config] checking {gamedir_conf}")
    if os.path.isfile(gamedir_conf):
        try:
            with open(gamedir_conf) as fh:
                return {**DEFAULT_CONFIG, **json.load(fh)}, gamedir_conf
        except Exception as exc:
            print(f"[config] gamedir config error: {exc}")

    # Second: try ~/.config/oi/config.json
    path = os.path.join(CONFIG_DIR, "config.json")
    print(f"[config] checking {path}")
    if os.path.isfile(path):
        try:
            with open(path) as fh:
                return {**DEFAULT_CONFIG, **json.load(fh)}, path
        except Exception as exc:
            print(f"[config] user config error: {exc}")

    print("[config] using defaults")
    return dict(DEFAULT_CONFIG), path


def save_config(path: str, updates: dict[str, object]) -> None:
    cfg = dict(DEFAULT_CONFIG)
    p = Path(path)
    try:
        if p.is_file():
            cfg.update(json.loads(p.read_text()))
    except Exception:
        pass
    cfg.update(updates)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2, sort_keys=True) + "\n")


def config_int(config: dict[str, object], key: str) -> int:
    default = int(DEFAULT_CONFIG[key])
    try:
        return int(config.get(key, default))
    except (TypeError, ValueError):
        return default


# ------------------------------------------------------------------
# Button map — verified on RG351P (AmberELEC)
# ------------------------------------------------------------------

RG351P_BUTTON_MAP = {
    "a":      {"type": "button", "value": 0},
    "b":      {"type": "button", "value": 1},
    "x":      {"type": "button", "value": 2},
    "y":      {"type": "button", "value": 3},
    "l1":     {"type": "button", "value": 4},
    "r1":     {"type": "button", "value": 5},
    "start":  {"type": "button", "value": 6},
    "select": {"type": "button", "value": 7},
    "l3":     {"type": "button", "value": 8},
    "r3":     {"type": "button", "value": 9},
    "l2":     {"type": "button", "value": 10},
    "r2":     {"type": "button", "value": 11},
    "up":     {"type": "hat", "hat": 0, "value": 1},
    "down":   {"type": "hat", "hat": 0, "value": 4},
    "left":   {"type": "hat", "hat": 0, "value": 8},
    "right":  {"type": "hat", "hat": 0, "value": 2},
}


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

async def main():
    setup_logging()
    logging = __import__("logging").getLogger("__main__")
    config, config_path = load_config()
    logging.info(f"config loaded: gateway={config['gateway_url']}")

    from oi_client.app import HandheldApp

    app = HandheldApp(
        gateway_url=config["gateway_url"],
        device_id=config["device_id"],
        device_type=config["device_type"],
        character_size=config.get("character_size", "big"),
        show_progress_messages=bool(config.get("show_progress_messages", True)),
        show_celebrations=bool(config.get("show_celebrations", True)),
        brightness=config_int(config, "brightness"),
        volume=config_int(config, "volume"),
        led_enabled=bool(config.get("led_enabled", True)),
        mute_duration_hours=config_int(config, "mute_duration_hours"),
        backend_id=config.get("backend_id"),
        agent_id=config.get("agent_id"),
        session_key=config.get("session_key"),
        settings_persist=lambda updates: save_config(config_path, updates),
    )

    try:
        await app.run()
    except KeyboardInterrupt:
        pass
    finally:
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
