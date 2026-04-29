# Device Adapter Plan (Actionable)

Status: actionable (WP-05a done, WP-05b ready for implementation)
Owner packages: WP-05a, WP-05b

## Objective

Map the frontend contract (`docs/FRONTEND_CONTRACT.md`) to M5StickS3 input/output constraints without changing backend semantics.

This plan is derived directly from live firmware behavior in `firmware/main.py`, `firmware/lib/oi_interaction.py`, and `firmware/lib/oi_session_ui.py`.

---

## 1. Input timing thresholds

All thresholds are defined in `firmware/lib/oi_interaction.py` and used in `firmware/main.py`.

| Constant | Value | Source | Meaning |
|----------|-------|--------|---------|
| `DEFAULT_DEBOUNCE_MS` | 30 ms | `oi_interaction.py:10` | Minimum stable pin state before edge is accepted |
| `DEFAULT_LONG_MS` | 800 ms | `oi_interaction.py:11` | Hold ≥ 800 ms → long press (emitted on release) |
| `DEFAULT_DOUBLE_MS` | 400 ms | `oi_interaction.py:12` | Second press within 400 ms → double press |
| `LOOP_SLEEP_MS` | 30 ms | `main.py:62` | Main loop cadence (keeps buttons responsive) |
| `SENT_FLASH_MS` | 1 000 ms | `main.py:63` | Feedback flash duration after POST actions |
| `IDLE_SLEEP_MS` | 30 000 ms | `main.py:64` | Inactivity before display sleep |
| `POLL_INTERVAL_MS` | 5 000 ms | `main.py:60` | GET `/oi/state` cadence while awake |
| `SLEEP_POLL_INTERVAL_MS` | 30 000 ms | `main.py:61` | GET `/oi/state` cadence while display asleep |
| `BAT_REFRESH_MS` | 10 000 ms | `main.py:65` | Battery I²C read cache expiry |

**Gesture semantics** (`oi_interaction.py` `GestureDetector.poll()`):
- Long press is emitted **on release** after the hold threshold, not immediately at 800 ms.
- Double press is emitted on the debounced second press; the pending single is suppressed.
- Single press is emitted only after the double window (400 ms) expires without a second press.
- Constructing the detector while the button is held does **not** fire; it arms only after observing a release.

**Wake-on-press** (`main.py` wake loop):
- While display is asleep, a simple `DebouncedPress` (30 ms debounce) wakes the device.
- Pattern detectors are reset after wake so the wake press is not double-counted.
- A currently-held button resets the idle-sleep timer so long-presses near the boundary are not swallowed.

---

## 2. Display constraints

### Hardware
- Controller: ST7789 (`firmware/lib/st7789py.py`)
- Resolution: **240 × 135 pixels**, landscape orientation (`main.py:81` `W=240, H=135`)
- Color: RGB565
- Backlight: PWM-controlled, presets 25 % / 60 % / 100 % (`main.py:68`)

### Fonts
| Font | Width | Height | File |
|------|-------|--------|------|
| `vga2_bold_16x32` (large) | 16 px | 32 px | `firmware/lib/vga2_bold_16x32.py` |
| `vga2_8x16` (small) | 8 px | 16 px | `firmware/lib/vga2_8x16.py` |

### Character capacity
| Zone | Font | Pixels | Chars per line |
|------|------|--------|----------------|
| Title | large (16×32) | 240 | **15** |
| Body / options / status | small (8×16) | 240 | **30** |

### Layout zones (landscape)
```
y=0..32    Title row   (1 large line, or 2-line cap with wrap)
y=32..119  Body rows   (87 px = 5 small-font rows)
y=119..135 Status/options row (1 small line, 16 px)
```

**Measurable limits** (`main.py:83-91`):
- `TITLE_H = 32`
- `BODY_Y = 32`
- `STATUS_Y = 119`
- `BODY_H = 87` (5 rows of small font at 16 px each)

---

## 3. Rendering priority rules

Deterministic precedence (`main.py` main loop, ~line 1200-1350):

1. **Prompt view** (`draw_question`) — highest priority. Triggered when `state.get("id")` is not None (legacy prompt ID) or when the reducer reports a pending prompt for the active session.
2. **Session idle** (`draw_session_idle`) — when no prompt is pending and an active session exists.
3. **Dashboard** (`draw_dashboard`) — when no prompt and no active session, but a snapshot (`state.get("snapshot")`) is present.
4. **Idle logo** (`draw_idle`) — fallback when nothing else applies.

**State change detection**:
- Full redraw happens only when `state.get("id")` changes, `active_session_id` changes, or dashboard `ts` changes.
- Offline indicator (`draw_offline_indicator`) is drawn as a small overlay and cleared on the next full redraw.

---

## 4. Truncation and scroll policy

### Word-wrap (`main.py` `_wrap`)
- Breaks on spaces where possible; hard-breaks words longer than `chars_per_line`.
- Does **not** hyphenate.

### Title (`draw_question`)
- Large font, 15 chars/line, **max 2 lines** (`max_lines=2`).
- Overflow beyond 2 lines is silently truncated.

### Body (`draw_question`)
- Small font, 30 chars/line, **max 5 lines** (`max_body_rows = BODY_H // font_sm.HEIGHT = 5`).
- Overflow beyond 5 lines is silently truncated.

### Options bottom row (`_draw_options_bottom`)
- Horizontal layout in the 30-char status row.
- Highlighted option gets inverted colors (BLACK on YELLOW).
- If total label width > 30 chars, a **sliding window** is used:
  - Leading `< ` if options before window are hidden.
  - Trailing ` >` if options after window are hidden.
  - Window always includes the highlighted option and expands left/right greedily to fit.

### Session picker (`draw_sessions_menu`)
- Vertical sliding window over the 5 body rows.
- `visible_window_start(highlighted, count, max_rows=5)` ensures the highlighted row is always visible.
- Each row: prefix `>` for highlighted, `*` for active session, name (truncated to 12 chars), status (truncated to 12 chars).

### Command menu (`draw_command_menu`)
- Lists all 7 commands vertically in the body area.
- **Current firmware quirk**: commands 6 and 7 (indices 5 and 6) draw below `STATUS_Y` and overlap the hint row because there is no vertical windowing. Adapter implementation may add windowing or reduce visible rows.

### Settings (`draw_settings`)
- All items drawn vertically; no vertical windowing currently.
- Highlighted row uses YELLOW fg in edit mode, WHITE fg otherwise.

### General text block (`_draw_text_block`)
- Each row is padded with spaces to exactly `cpl` chars and drawn with bg color to erase old text.
- Returns the y-coordinate after the last drawn row.

---

## 5. View definitions and button mapping

### View summary

| View | Trigger | Primary renderer |
|------|---------|------------------|
| `idle` | No session, no prompt, no snapshot | `draw_idle` |
| `session_list` | User opens picker (BtnB.tap from idle, or B.single in picker) | `draw_sessions_menu` |
| `prompt` | Pending prompt for active session | `draw_question` |
| `command_menu` | BtnA.tap from session idle (when no speak pending) | `draw_command_menu` |
| `settings` | BtnB.long from any non-settings screen | `draw_settings` |

### Button → action mapping table

Derived from `oi_interaction.py:_ACTIONS` and `main.py` ad-hoc handlers.

#### Idle (no active session)
| Button | Gesture | Action | Firmware behavior |
|--------|---------|--------|-------------------|
| BtnA | single | `ACTION_PING` | POST `/oi/ping` |
| BtnA | double | `ACTION_PING` | POST `/oi/ping` |
| BtnA | long | `ACTION_NONE` | Ignored |
| BtnB | single | *(ad-hoc)* | Open session picker (`_run_session_picker`) |
| BtnB | long | `ACTION_OPEN_SETTINGS` | Enter settings menu |

#### Session idle (active session visible)
| Button | Gesture | Action | Firmware behavior |
|--------|---------|--------|-------------------|
| BtnA | single | `ACTION_OPEN_MENU` | If `_speak_pending`: fetch+play TTS; else open command menu |
| BtnA | double | `ACTION_PING` | POST `/oi/ping` |
| BtnA | long | `ACTION_NONE` | Ignored |
| BtnB | single | `ACTION_NEXT_SESSION` | Cycle to next session; POST `/oi/sessions/active` |
| BtnB | long | `ACTION_OPEN_SETTINGS` | Enter settings menu |

#### Prompt (pending approval/question)
| Button | Gesture | Action | Firmware behavior |
|--------|---------|--------|-------------------|
| BtnA | single | `ACTION_ANSWER` | POST `/oi/answer` with selected option value |
| BtnA | long | `ACTION_NONE` | Ignored |
| BtnB | single | `ACTION_NEXT` | Cycle highlighted option (bottom row) |
| BtnB | double | `ACTION_NONE` | Ignored |
| BtnB | long | `ACTION_OPEN_SETTINGS` | Enter settings menu (prompt remains in background) |

#### Settings menu
| Button | Gesture | Action | Firmware behavior |
|--------|---------|--------|-------------------|
| BtnA | single | `ACTION_EDIT` | Cycle value for highlighted item |
| BtnA | long | `ACTION_SAVE_EXIT` | Save to flash (`/settings.json`), exit menu |
| BtnB | single | `ACTION_NEXT` | Cycle highlighted item |
| BtnB | long | `ACTION_SAVE_EXIT` | Save to flash, exit menu |

#### Session picker (modal, ad-hoc in main.py)
| Button | Gesture | Behavior |
|--------|---------|----------|
| BtnB | single | Next session |
| BtnB | double | Previous session |
| BtnB | long | Exit without selecting |
| BtnA | single | Focus selected session (POST `/oi/sessions/active`) |
| BtnA | long | Open command menu for selected session |

#### Command menu (modal, ad-hoc in main.py)
| Button | Gesture | Behavior |
|--------|---------|----------|
| BtnB | single | Next command |
| BtnB | double | Previous command |
| BtnB | long | Exit menu |
| BtnA | single | Send command (POST `/oi/commands`) or run local voice handler |

### Settings items
1. **brightness** — cycles `low` → `medium` → `high` → `low`
2. **volume** — cycles `mute` → `20%` → `40%` → `60%` → `80%` → `100%` → `mute`
3. **wake chirp** — toggles `on` / `off`

---

## 6. Audio constraints

- `speak` output: server queues a TTS WAV; device shows yellow hint `A:play msg` (`main.py` `_speak_pending`).
- BtnA tap while pending fetches WAV (`GET /oi/speak`, timeout 10 s) and plays via `OiAudio.play_wav()`.
- Volume is local-only; never blocks state transitions.
- Mute is modeled as `volume = 0` internally.
- Voice command (`voice`) is handled locally on-device, not sent to server.

---

## 7. Error / offline rendering

- **Offline indicator**: red `OFFLINE` tag, 7 chars × 8 px = 56 px wide, drawn at top-right (`x = 184, y = 0`) (`main.py:draw_offline_indicator`).
- **Network timeouts**: 4 s for standard GET/POST; 10 s for TTS fetch; 30 s for audio upload.
- **Retry behavior**: non-blocking; poll loop continues at 5 s (awake) or 30 s (asleep).
- **Flash feedback**: `draw_flash` shows green text for success (e.g. `sent: ok`) or failure (`send failed - retry?`) for 600–1000 ms.

---

## 8. Transport decision (frozen for WP-05b)

**Chosen: TCP JSONL gateway (`scripts/pi-rpc-gateway.ts`) + MicroPython TCP client (`firmware/lib/pi_rpc_client.py`)**

Rationale:
- M5StickS3 cannot spawn `pi --mode rpc` locally; it needs a network transport.
- MicroPython has built-in `usocket` TCP client (no extra dependencies).
- The firmware speaks the exact same JSONL protocol as `mock-device/src/pi_rpc.ts`, maximising code reuse.
- The gateway is stateless: one TCP connection = one dedicated `pi` subprocess, with transparent bidirectional JSONL piping.
- HTTP/WebSocket would require more firmware code and parsing overhead.

Trade-offs:
- Single-session for v1: real Pi RPC `get_state` returns one session; multi-session listing requires gateway enhancements or Pi RPC extensions (deferred).
- Mixed transport: Pi RPC handles state/commands/prompts; legacy HTTP retains audio/TTS (`/oi/speak`, `/oi/audio`) until those endpoints are rehosted.

Gateway usage:
```bash
npx tsx scripts/pi-rpc-gateway.ts [--port 8843] [--pi-cmd "pi"] [--pi-args "--mode rpc --no-session"]
```

Firmware config (device-local `/secrets.py`, sourced from `~/.oi/secrets/firmware/oi-v1/secrets.py`):
```python
PI_RPC_HOST = "gateway.local"
PI_RPC_PORT = 8843
```

## 9. Adapter implementation checklist

- [x] Implement TCP JSONL gateway (`scripts/pi-rpc-gateway.ts`)
- [x] Implement MicroPython TCP JSONL client (`firmware/lib/pi_rpc_client.py`)
- [x] Implement Pi RPC state mapper (`PiRpcStateMapper` in `pi_rpc_client.py`)
- [x] Refactor `firmware/main.py` to use Pi RPC for state/commands/prompts
- [x] Update device-local `/secrets.py` with `PI_RPC_HOST`/`PI_RPC_PORT`
- [ ] Implement or port `GestureDetector` / `DebouncedPress` semantics exactly (30/400/800 ms) — already in `firmware/lib/oi_interaction.py`.
- [x] Map five views (`idle`, `session_list`, `prompt`, `command_menu`, `settings`) to the priority rules above.
- [x] Respect 15-char large title cap and 30-char small body/options cap.
- [x] Implement horizontal sliding window for prompt options and vertical sliding window for session picker.
- [x] Keep command menu within visible rows by using a reduced 3-item test command set (`status`, `prompt`, `abort`).
- [x] Preserve local settings persistence (`/settings.json`) for brightness/volume/wake_chirp.
- [x] Keep speak-pending indicator and one-shot TTS fetch/play semantics.
- [ ] Hardware smoke test: switch session (single-session mode only), answer a prompt, queue a command, adjust settings — all in ≤ 3 button actions per workflow.
  - ✅ Transport: device connects to Pi RPC TCP gateway, sends get_state, receives session data
  - ✅ State display: device shows session name/status from Pi RPC get_state
  - ✅ Commands: "status" and "ping" buttons send RPC commands and receive responses
  - [ ] Prompt answering: Pi extension_ui_request → device prompt → button answer → extension_ui_response
  - [x] Command verbs (test set): status, prompt, approve, abort via command menu
  - [ ] Settings: brightness, volume, wake chirp cycles persist
- [ ] Fixture replay produces identical reducer state on device and mock.
