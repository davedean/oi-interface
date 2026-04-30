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

## Known issues / TODO

- [ ] Callbacks for reply streaming
- [ ] DatpClient exposes asyncio.Queue for commands — should this be thread safe?
- [ ] TTF font sizing needs empirical tuning per device
- [ ] Cached audio needs actual WAV file playback (untested)
- [ ] No testing for aplay kill (pkill)
- [ ] `aplay` simple, but might need `ffplay` or SDL2 audio for better control
- [ ] `audioplayer_wavefronts` not implemented (gateway may send WAV, not chunked PCM)
