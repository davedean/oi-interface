# Oi Client for Linux SBC Handhelds

## Device support

First target: **RG351P** (AmberELEC / EmulationStation)

## Runtime dependencies

The device is read-only root with no `pip`.  Everything must be vendored.

| Dependency | Source | How to vendor |
|---|---|---|
| `websockets` | PyPI | `pip install --target oi_client/lib websockets` on a Linux machine |
| `pysdl2` | PortMaster | Already on device at `/storage/roms/ports/PortMaster/exlibs/sdl2` |
| SDL2 | System | Already on device at `/usr/lib/libSDL2-2.0.so` |
| SDL2_ttf | System | Already on device at `/usr/lib/libSDL2_ttf-2.0.so` |

## Vendoring websockets

From any Linux machine with `pip`:

```bash
pip install --target vendor_tmp websockets
cp -r vendor_tmp/websockets oi_client/lib/
rm -rf vendor_tmp
```

**Important:** Remove compiled extensions (`.so` files) if they exist — the RG351P is aarch64, not x86_64.

```bash
find oi_client/lib/websockets -name '*.so' -delete
```

## Architecture

```
oi_client/
├── __main__.py      # Entry point (asyncio.run(main()))
├── __init__.py
├── state.py         # Device state machine (from oi-sim)
├── datp.py          # DATP WebSocket client
├── input.py         # SDL2 gamepad → logical events
├── renderer.py      # SDL2 text cards, status, scrolling
├── audio.py         # aplay playback, optional SDL2 mic capture
├── capabilities.py  # DATP command/capability contract
├── device_control.py# local brightness/mute/volume/LED/power handlers
├── telemetry.py     # periodic state payload collection
└── app.py           # Main loop: HOME → CONNECTING → READY → CARD
```

## Running on device

From SSH (for dev/debug):
```bash
cd /storage/roms/ports/Oi
PYTHONPATH=/storage/roms/ports/PortMaster/exlibs:$PYTHONPATH \
PYSDL2_DLL_PATH=/usr/lib \
python3 -m oi_client
```

`config.json` supports:
- `gateway_url`: active gateway WebSocket URL
- `gateway_urls`: optional list of gateway WebSocket URLs to cycle from the Connection menu
- `character_size`: `big` or `small`
- `show_progress_messages`: `true` or `false`
- `show_celebrations`: `true` or `false`
- `brightness`: `0`-`255`
- `volume`: `0`-`100`
- `led_enabled`: `true` or `false`
- `mute_duration_hours`: `1`, `8`, or `24`
- `backend_id`: selected gateway backend profile id
- `agent_id`: selected agent id
- `session_key`: selected conversation session key

Changes made in the Settings menu are persisted automatically to `config.json`.

From EmulationStation (production):
- Drop `Oi.sh` launcher into `/storage/roms/ports/`
- ES shows "Oi" in Ports menu
- Select → launches fullscreen → interact → Start+Select → returns to ES

## Button map (RG351P verified)

| Logical | SDL |
|---|---|
| A | button 0 |
| B | button 1 |
| X | button 2 |
| Y | button 3 |
| L1 | button 4 |
| R1 | button 5 |
| Start | button 6 |
| Select | button 7 |
| D-Pad | hat 0 (1=up, 2=right, 4=down, 8=left) |

Source: `sdl2_button_map.py` wizard on device, 2026-04-29.

## Gateway command support

Implemented locally:
- `display.show_status`, `display.show_card`, `display.show_progress`, `display.show_response_delta`
- `audio.cache.put_begin`, `audio.cache.put_chunk`, `audio.cache.put_end`, `audio.play`, `audio.stop`
- `device.set_brightness`, `device.mute_until`, `device.set_volume`, `device.set_led`
- `character.set_state`

Recognized but not advertised in capability negotiation:
- `device.reboot`, `device.shutdown` are blocked unless `OI_ENABLE_POWER_COMMANDS=1`
- `storage.format`, `wifi.configure` are recognized but currently return local no-op/failure status

The client now also sends periodic DATP `state` reports with any discoverable battery/Wi-Fi/memory info.

## Delightful extras

- `Surprise me ✨` home prompt that cycles through whimsical requests
- `About Gateway` menu card showing `hello_ack` metadata like server name/session/agents
- Settings menu now includes brightness, volume, LED, mute duration, a Connection submenu (gateway / backend / agent / session), diagnostics, and a small system submenu
- secret button-code easter egg for Blob Party mode
- playful connecting/waiting/response quips on-device

## Known issues / TODO

- [ ] DatpClient exposes asyncio.Queue for commands — should this be thread safe?
- [ ] TTF font sizing needs empirical tuning per device
- [ ] No testing for aplay kill (pkill)
- [ ] `aplay` simple, but might need `ffplay` or SDL2 audio for better control
