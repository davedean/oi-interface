# Generic SBC Handheld Plan

**Status:** active sketch — first target verified (RG351P)

Plain English: this target treats the handheld as a small Linux computer, not a microcontroller. The user launches it like a game from the front-end (EmulationStation), it connects to `oi-gateway`, sends/receives messages, and when the user quits it returns to the front-end. No daemon, no boot-time service, no deep-sleep/resume logic.

---

## 1. Goal

Build a reusable Oi device runtime for Linux-based retro handhelds and SBC consoles, starting with **RG351P-class AmberELEC devices**.

The runtime should:
- be launched as a **foreground app** from the handheld's game front-end
- connect to `oi-gateway` over Wi-Fi
- register as a DATP device
- accept button/gamepad input via SDL2
- render a full-screen card/status UI via SDL2
- play TTS/audio output locally via ALSA/SDL2
- optionally capture audio from a USB microphone (later)
- quit cleanly, returning the user to the front-end

## 2. Why this target is promising

Compared with microcontroller firmware:
- easier networking (WebSocket from Python)
- easier logging/debugging
- easier iteration and packaging
- easier use of USB peripherals

Compared with PICO-8:
- real sockets/WebSockets
- real file system
- real audio and input device access
- one codebase covers many handhelds

## 3. Product stance

This is a **handheld Oi terminal** — a foreground app, not a service.

The user drops in and out like a game:
```
EmulationStation  →  [select "Oi"]  →  runtime launches  →  user interacts  →  [press QUIT]  →  back to ES
```

Split the design into:
1. core runtime (DATP client + state machine, adapted from `oi-sim`)
2. hardware/input/audio adapters (SDL2)
3. packaging/launcher integration (Port-style `.sh` script)

## 4. Reuse strategy: start from `oi-sim`

Plain English: we do **not** invent DATP from scratch.
The nearest working implementation is `src/oi-clients/oi-sim/`, and it is our first code donor.

### Directly reusable

#### `src/oi-clients/oi-sim/src/sim/sim.py`
- DATP WebSocket lifecycle
- `hello` construction and `hello_ack` handling
- capability advertisement
- event sending patterns
- command receive + ack

#### `src/oi-clients/oi-sim/src/sim/state.py`
- canonical device state machine
- valid transitions (`READY → THINKING → RESPONSE_CACHED` etc.)
- command-driven state updates

### Adapted, not copied blindly

#### `src/oi-clients/oi-sim/src/sim/repl.py`
Replaced with:
- SDL2 gamepad input adapter
- SDL2 full-screen renderer
- ALSA/SDL2 audio playback adapter

### Architectural consequence

A future `oi-sbc-client` should be built by:
- importing/extracting the DATP client/session layer from `oi-sim`
- importing the device state machine from `state.py`
- adding SDL2 input, renderer, and audio adapters
- writing a main loop that glues them together
- packaging as a Port-style launcher

## 5. Proposed architecture

```text
┌─────────────────────────────────────────────────────────┐
│ handheld runtime (foreground app)                       │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ SDL2 input   │  │ SDL2 renderer│  │ audio adapter │  │
│  │  (gamepad)   │  │  (480x320)   │  │  (aplay/sdl2) │  │
│  └──────┬───────┘  └──────┬───────┘  └───────┬───────┘  │
│         │                  │                  │          │
│         └──────────────────┼──────────────────┘          │
│                            ▼                            │
│                     device controller                   │
│                     (adapts from OiSim)                 │
│                            │                            │
│                      datp client                        │
│                            │                            │
│               connect / retry / quit                    │
└────────────────────────────┼────────────────────────────┘
                             │  WebSocket
                             ▼
                        oi-gateway
```

## 6. Suggested implementation language

**Python** is the right first move.

Why:
- matches the rest of the v2 repo
- fast iteration
- Python 3.11 already installed on target
- SDL2 Python bindings work via PortMaster's `pysdl2`

No external packages are available (`pip` is not installed, rootfs is read-only).
Everything must be **vendored**.

## 7. Capability profile

This target advertises itself as a button-first handheld with a decent screen.

Suggested `device_type`:
- `sbc-handheld`

Suggested capabilities (MVP — no mic):

```json
{
  "input": ["buttons", "dpad", "confirm_buttons"],
  "output": ["screen", "cached_audio"],
  "sensors": ["battery", "wifi_rssi"],
  "commands_supported": [
    "display.show_status",
    "display.show_card",
    "audio.cache.put_begin",
    "audio.cache.put_chunk",
    "audio.cache.put_end",
    "audio.play",
    "audio.stop",
    "device.set_brightness",
    "device.mute_until"
  ],
  "display_width": 40,
  "display_height": 20,
  "has_audio_input": false,
  "has_audio_output": true,
  "supports_text_input": false,
  "supports_confirm_buttons": true,
  "supports_scrolling_cards": true,
  "supports_voice": false,
  "max_spoken_duration_s": 120
}
```

Notes:
- `display_width` / `display_height` are **text grid dimensions** at the chosen font size, not pixels. Measured empirically on target.
- If a USB mic is plugged in later, flip `has_audio_input` and `supports_voice` to `true` and add `"hold_to_record"` to `input`.

## 8. Input model

No freeform keyboard entry.

### Core button grammar
- `up/down` — move selection / page card text
- `left/right` — change quick actions or dismiss
- `a` — confirm / send selected prompt
- `b` — back / dismiss card / stop playback
- `menu` / `start` — open top-level actions or quit
- `select` — reserved for future (e.g., mute toggle)
- `hold a` — start recording, if mic exists (Phase 2)
- `release a` — stop recording and upload

### Input backend
**SDL2 Joystick / GameController** (not `evdev`).

Reason: `evdev` is not installed and cannot be installed on read-only rootfs. SDL2
is already present on the system (`libSDL2-2.0.so`) and PortMaster ships `pysdl2`.
SDL2 correctly detects the built-in gamepad (`OpenSimHardware OSH PB Controller`).

## 9. UI model

### App states
1. `HOME` — show status, canned prompts, or last activity
2. `CONNECTING` — attempting gateway connection with spinner
3. `MENU` — top-level actions (quit, mute, etc.)
4. `WAITING` — sent to gateway, awaiting response
5. `CARD` — showing a text card response from the agent
6. `ERROR` — connection or gateway error, retry/quit options
7. `OFFLINE` — no Wi-Fi or no gateway

### Display principles
- always show connection state
- keep text short — card body is paged
- show explicit button hints on screen (A=send, B=back, etc.)
- optimize for low cognitive load

### Rendering backend
**SDL2** (not curses, not raw framebuffer).

Reasons:
- SDL2 is already the display framework used by EmulationStation and every Port
- KMS/DRM fullscreen works without fighting the compositor
- Hardware-accelerated text rendering via `sdl2.ext` or `pygame`
- Can coexist with the existing front-end (we take over display while running, ES resumes when we quit)

Alternate (fallback): direct `/dev/fb0` write for extremely minimal distros.

## 10. Audio model

### MVP audio path (playback only)
- Receive cached audio from gateway (`audio.cache.put_begin/chunk/end`)
- Write to a temp `.wav` file
- Play via `aplay` or SDL2 audio

### Phase 2: USB mic recording
- SDL2 audio capture API or `arecord` (if available on target)
- Stream PCM chunks as `audio_chunk` events while holding record button
- Emit `audio.recording_finished` on release

### Degradation rule
- no mic → text/card-only device (MVP)
- no speaker → still usable with text UI

## 11. DATP behavior

### Device → Gateway
- `hello`
- `event`
- `audio_chunk`
- `state`
- `ack`
- `error`

### Gateway → Device
- `hello_ack`
- `command`
- `error`

### Event mapping
- D-pad press → `button.pressed` with `button` field
- A press (short) → `button.pressed` with `button: "a"`
- A long hold start → `button.long_hold_started`
- A release after long hold → `audio.recording_finished`
- B press → `button.pressed` with `button: "b"`
- Start/Menu press → used for local UI (quit, etc.), may also send event

## 12. Adapter split

Three adapter seams keep the runtime generic.

### 12.1 Input adapter
- normalize device buttons to logical actions
- expose pressed/released/held events

### 12.2 Renderer adapter
- draw status/card/menu screens
- report effective text dimensions for capability hints

### 12.3 Audio adapter
- discover input/output availability
- record/capture audio chunks (Phase 2)
- playback gateway-returned audio

This lets us support:
- RG351P-specific button mappings
- other handhelds with different SDL2 controller layouts
- headless debug mode on a laptop (mock input, print renderer)

## 13. MVP for RG351P

A realistic first milestone:

1. user launches "Oi" from EmulationStation Ports menu
2. runtime opens fullscreen SDL2 window
3. attempts Wi-Fi + gateway connection
4. registers as `sbc-handheld` (no mic)
5. shows online/offline status
6. presents 4 canned prompts (e.g., "What time is it?", "Status check")
7. user D-pads to select, presses A
8. sends `text.prompt` event to gateway
9. shows `WAITING` / `THINKING` status
10. receives `display.show_card` + cached audio
11. shows paged text card
12. user presses B to dismiss or A to replay audio
13. user presses Start+Select (or Menu) to quit, returns to ES

That proves the full target.

## 14. Packaging strategy

PortMaster-style Port packaging for AmberELEC / EmulationStation front-ends.

```
/storage/roms/ports/
├── oi.sh                    # launcher script
└── oi/                      # application directory
    ├── control.txt          # sourced from launcher (get_controls, etc.)
    ├── main.py              # entry point
    ├── oi_client/           # our package
    │   ├── __init__.py
    │   ├── app.py           # SDL2 app loop + input handler
    │   ├── renderer.py      # SDL2 drawing
    │   ├── audio.py         # ALSA/SDL2 playback
    │   └── state.py         # device state machine (from oi-sim)
    ├── lib/                 # vendored pure-Python dependencies
    │   ├── websockets/
    │   └── sdl2/            # optional: pysdl2 if not on system path
    └── assets/
        └── font.ttf
```

**Launcher `.sh` responsibilities:**
- source `$controlfolder/control.txt` to get `get_controls`, `ESUDO`, `GAMEDIR`
- set `PYTHONPATH` to include `oi/lib/`
- set `PYSDL2_DLL_PATH=/usr/lib` (system SDL2)
- set `CUR_TTY=/dev/tty0` and clear screen
- launch `python3 main.py`
- on exit, clear screen and restart EmulationStation (standard Port pattern)

**Phases:**
1. run from shell on device (`ssh` in, run Python directly)
2. add launcher `.sh`, test from Ports menu
3. add ES theme entry / artwork
4. later: package as a `.zip` for PortMaster / community stores

**No autostart.** The user chooses when to launch Oi. This avoids:
- fighting for the display with EmulationStation
- battery drain from a background WebSocket
- unexpected network traffic when the device is "off"

## 15. Verified environment (RG351P / AmberELEC)

| Capability | Status | Detail |
|---|---|---|
| Python 3.11 | ✅ | `/usr/bin/python3` |
| SDL2 library | ✅ | `/usr/lib/libSDL2-2.0.so.0.2600.2` |
| SDL2 Python | ✅ | PortMaster bundles `pysdl2` in `/storage/roms/ports/PortMaster/exlibs/sdl2` |
| `websockets` | ❌ | not installed; must vendor |
| `evdev` | ❌ | not installed; use SDL2 instead |
| framebuffer | ✅ | `/dev/fb0` writable; 480×320 |
| ALSA playback | ✅ | `aplay` present; speaker works |
| ALSA capture | ❌ | no `arecord`; mic not wired |
| WiFi | ✅ | USB MT7601U adapter |
| writable storage | ✅ | `/storage/` is ext4 |
| read-only root | ⚠️ | `/` is squashfs; no system-wide installs |
| EmulationStation | ✅ | systemd service at boot |
| Port infrastructure | ✅ | `control.txt`, `get_controls`, launcher pattern well established |

## 16. Key unknowns to test

1. WebSocket latency over WiFi (MT7601U is 2.4GHz only, not fast)
2. SDL2 fullscreen + text readability at 480×320
3. Audio playback latency with `aplay` vs. SDL2 audio
4. Memory footprint (~900MB total; Python + SDL2 + websockets should fit easily)
5. Whether SDL2 takes exclusive DRM/KMS access (may block ES from resuming cleanly)
6. Gateway URL discovery — hardcode? mDNS? config file?

## 17. Dependency vendoring

Everything vendored into `lib/`:

| Package | Size | Why |
|---|---|---|
| `websockets` | ~150KB | DATP WebSocket client |
| `pysdl2` | ~500KB | If system copy unavailable; PortMaster already provides it |

No compiled extensions needed. Pure Python only.

## 18. Suggested repo shape

Current:
```text
src/oi-clients/generic_sbc_handheld/
├── README.md
├── GENERIC_SBC_HANDHELD_PLAN.md
├── capability-profile.json
└── runtime_sketch.py
```

Future (when real code exists):
```text
src/oi-clients/generic_sbc_handheld/
├── README.md
├── GENERIC_SBC_HANDHELD_PLAN.md
├── capability-profile.json
├── oi.sh                  # launcher
├── main.py                # entry point
├── oi_client/
│   ├── __init__.py
│   ├── app.py             # SDL2 loop, input, quit
│   ├── datp_client.py     # adapted from oi-sim/sim.py
│   ├── state_machine.py   # adapted from oi-sim/state.py
│   ├── renderer.py        # SDL2 drawing
│   ├── input_adapter.py   # SDL2 joystick → logical events
│   ├── audio_adapter.py   # aplay/SDL2 playback
│   └── config.py          # gateway URL, device ID
├── lib/
│   └── websockets/
└── assets/
    └── font.ttf
```

A real implementation may later move to `src/oi-sbc-client/` if it outgrows the `src/oi-clients/` directory.

## 19. Recommendation

**Proceed with this target.**

Best next step:
1. Write a **stand-alone SDL2 test app** that opens fullscreen, renders text, reads D-pad + A/B, and quits cleanly — verify the I/O stack works on the real device.
2. Wire in the DATP client (adapted from `oi-sim`) + gateway connection.
3. Add canned prompts + `text.prompt` event sending.
4. Add card rendering + `display.show_card` response handling.
5. Package as a Port launcher and test from EmulationStation.

Why this order:
- proves the SDL2 stack on real hardware first
- DATP reuse minimizes protocol risk
- text-first MVP avoids audio complexity
- Port packaging comes last, after behavior is proven
