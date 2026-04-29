# oi

A tiny screen + buttons sitting on a desk that the agent uses to interact with its operator.

## Why

The agent currently can only nudge its operator through files they might never check or by waiting for an interactive session. A glanceable screen + a few buttons closes async loops the agent currently can't:

- Surface a question with button-mapped options ("Which Adam?" → [Wilson / G / Other])
- Show INBOX count, today's workout, what's pending
- Show heartbeat activity in real time so 3am runs aren't a black box
- Ack / snooze for things the agent surfaces

Future: hook into agent's own `AskUserQuestion` so it can route questions to the device, and (eventually) push-to-talk → Whisper → cleaned text → next prompt.

## Hardware

**M5Stack StickS3** — ESP32-S3-PICO-1, 8MB flash, 8MB octal PSRAM, WiFi/BT5, 1.14" ST7789v2 TFT (135×240), 2 buttons (BtnA front-large, BtnB side), IMU, PDM mic, IR transmitter, internal battery, USB-C.

(Originally identified as Core S3 — corrected after seeing the order line item. Different device, similar chip.)

MAC: configure per device
WiFi IP: assign via DHCP or local network config

**Button interaction model:**
- BtnA (front, large) = primary / select / "yes"
- BtnB (side) = secondary / cycle next / dismiss
- Normal gestures are debounced `tap`, `double-tap`, and `long-press`; double-tap is recognised by firmware but currently reserved/no-op in the live UI.
- Asleep: BtnA or BtnB tap wakes the display only; the wake press is not also treated as an action.
- Idle/dashboard: BtnA tap pings the agent; BtnA long-press opens settings; BtnB is reserved.
- Multi-option question: BtnB tap cycles options; BtnA tap confirms; BtnA long-press opens settings.
- Settings: BtnB tap moves to the next row; BtnA tap edits/cycles the selected value; BtnA long-press saves and exits. Brightness and volume are local device settings and are not overridden by server control.
- Future gestures planned for the interaction layer: ordered A+B / B+A chords for system-level mode switching, plus optional IMU shortcuts (shake/tilt/face-down) with button equivalents.

## Architecture

- **Device runs MicroPython** (stock, v1.28.0) — `boot.py` joins WiFi, `main.py` runs the polling loop.
- **The host runs a small HTTP server** (`server/`) that holds current state. Device polls `GET /oi/state`, posts `POST /oi/answer` for question responses and `POST /oi/ping` for idle BtnA pings.
- **Server target:** configure `OI_SERVER_URL` in a local `secrets.py` file. Keep the source copy at `~/.oi/secrets/firmware/oi-v1/secrets.py` and copy it to the device as `/secrets.py` during firmware setup.
- **Runtime is WiFi-only.** USB only matters for flashing/dev.

## Model selection overrides (agent orchestration)

When delegating sub-agents for this repo, use cheap-first routing by default (see global `AGENTS.md`).

If needed, define repo-level overrides here:

### Preferred Models

- Claude (general reasoning / planning / code review)
- OpenAI (general reasoning / implementation / editing)
- OpenCode Go low-cost: Qwen3.5 Plus, DeepSeek V4 Flash, MiniMax M2.5 (scouting/mechanical work)

### Blacklisted Models

- (none currently)

Notes:
- This is an operator policy surface for agents; it may be enforced by tooling later.
- If both global guidance and repo README differ, this README section wins for this repo.
- For model-strength tie-breakers (after cost/fit), refer to `~/meta/README.md` (includes Artificial Analysis benchmark notes).

## Pi RPC TCP Gateway

For firmware deployments that cannot spawn `pi --mode rpc` locally, a lightweight TCP gateway bridges the device to a Pi RPC subprocess over the network:

```bash
# Start the gateway (listens on TCP 8843 by default)
npx tsx scripts/pi-rpc-gateway.ts

# With custom port or pi command
npx tsx scripts/pi-rpc-gateway.ts --port 8843 --pi-cmd "pi" --pi-args "--mode rpc --no-session"

# Optional: enable deterministic approval-dialog test harness
npx tsx scripts/pi-rpc-gateway.ts --approval-gate
# (or pass an explicit extension path)
npx tsx scripts/pi-rpc-gateway.ts --approval-gate /abs/path/to/approval-gate.ts
```

The gateway is **stateless** — one TCP connection spawns one dedicated `pi` subprocess, and JSONL lines flow bidirectionally without interpretation. The firmware (`firmware/main.py`) connects to the gateway via `PI_RPC_HOST`/`PI_RPC_PORT` from the device-local `/secrets.py`, sourced from `~/.oi/secrets/firmware/oi-v1/secrets.py`.

`--approval-gate` is opt-in and intended for validation only; default runtime should stay extension-free so the device behaves like a normal Pi RPC frontend.

Architecture:
- **Device** ← TCP JSONL → **Gateway** ← stdin/stdout JSONL → **Pi RPC process**
- HTTP endpoints (`/oi/speak`, `/oi/audio`) remain for TTS/STT until those services are rehosted.

## Terminal mock frontend

The `mock-device/` TypeScript scaffold provides a deterministic reducer and interactive CLI for exercising device state without hardware or a live server.

```bash
# Interactive mode — keyboard-driven state exploration
./scripts/pi-oi-mock
./scripts/pi-oi-mock --fixture tests/fixtures/pi-events/multi-session-switch.jsonl

# Non-interactive JSON dump
npx tsx mock-device/src/main.ts --fixture tests/fixtures/pi-events/no-sessions.jsonl

# Run reducer + parser tests
npx tsx --test 'mock-device/tests/**/*.test.ts'
```

Available interactive commands: `n`/`p` cycle sessions, `f <id>` focus, `m` toggle menu, `a <pid> <val>` answer prompt, `c <verb> [json]` queue command, `x <cmd_id>` cancel command, `X [session_id] [--dry-run]` cancel all, `k [session_id] [--dry-run]` cleanup session, `h [jsonThresholds]` healthcheck, `u` sync from backend (`get_state` in Pi RPC mode), `q` quit.

## Pi RPC mode

The mock-device can operate in **Pi RPC mode**, connecting to a live `pi` process either directly (subprocess) or via the TCP gateway:

```bash
# Interactive mode backed by a Pi RPC subprocess (local)
./scripts/pi-oi-mock --pi-rpc
./scripts/pi-oi-mock --pi-rpc --pi-rpc-cmd "pi --mode rpc --no-session"

# Or connect the mock-device to the TCP gateway
./scripts/pi-oi-mock --pi-rpc --pi-rpc-cmd "nc localhost 8843"
```

Flags:
- `--pi-rpc` — enable Pi RPC mode (spawns a subprocess for state/actions)
- `--pi-rpc-cmd <command>` — command to spawn (default: `pi --mode rpc --no-session`)

Behaviour:
- On startup: spawns the RPC client, sends `get_state`, seeds the reducer snapshot.
- Supported `command.queue` verbs (`status`, `abort`, `follow_up`, `steer`, `prompt`) are routed to the RPC subprocess.
- `speak` stays local-only (no RPC mapping) with an informative `last_action_result`.
- Incoming `extension_ui_request` messages appear as pending prompts; answering them sends `extension_ui_response` back to the RPC process.
- Press `u` to request a fresh state sync from the RPC process.

If `get_state` includes `sessions` + `active_session_id`, the mock renders multi-session state directly.

## Status

- [x] MicroPython flashed (v1.28.0 on ESP32_GENERIC_S3-SPIRAM_OCT)
- [x] WiFi joins on boot via `boot.py`
- [x] Bidirectional reachability with the host confirmed
- [x] LCD driver — ST7789 over SPI (russhughes/st7789py_mpy), but only after powering the L3B rail via M5PM1
- [x] Buttons read cleanly (BtnA=G11, BtnB=G12, active-low w/ pull-up)
- [x] Boot auto-run (boot.py → main.py, no manual steps)
- [x] HTTP server on the host (`server/oi_server.py`, port 8842)
- [x] Polling loop on device — GET /oi/state every 5s
- [x] Agent → device push (server stages question, device renders, button confirms)
- [x] Device → agent ping (BtnA idle press)
- [x] WebREPL OTA push via `scripts/push.sh`
- [x] **Level-a power management** — display sleep after 30s idle (backlight + ST7789 SLPIN), BtnA/BtnB wake
- [ ] **Level-b power management** — `machine.lightsleep()` during display-asleep (parked — see Power Management)
- [x] Systemd unit template checked in (`deploy/oi-server.service`)
- [ ] Server installed/enabled as systemd unit on `.85`
- [ ] Heartbeat surfaces `/oi/pings` into INBOX.md
- [ ] Audio capture + local STT (parked — see `audio-stt-research.md`; whisper.cpp base.en is the pick)
- [x] Multi-session backend routing — session registry, prompt queue projected through legacy `/oi/state`, session-aware approval hook, and oi→pi command queue/bridge foundation
- [x] Multi-session firmware UI — `B.long` opens session picker; `A.tap` focuses; `A.long` opens canned command menu (`status`/`prompt`/`approve`/`abort`) tuned for gateway reply testing
- [ ] Consider BLE Nordic UART Service for desktop pairing (parked — different use case than ours, only matters if desktop permission prompts become a target)

## File index

> **Before changing firmware:** skim [`reference/esp32-micropython/INDEX.md`](../../reference/esp32-micropython/INDEX.md) — has authoritative docs for the full ESP32-S3 + MicroPython stack (sleep modes, WiFi power save, machine module, WLAN, etc.). Cached locally so agents can grep instead of web-searching.

- `HARDWARE.md` — full M5StickS3 pin/I²C/spec reference (from M5 docs)
- `OPERATOR_CHEATSHEET.md` — common health/status, helper, firmware push, and systemd commands
- `NEXT_STEPS.md` — handoff plan for device session UI, command menu, bridge smoke tests, and lifecycle polish
- `sleep-research.md` — ESP32-S3 MicroPython sleep + WiFi deep-dive (read before trying level-b again)
- `firmware/boot.py` — PMIC → LCD → buttons → WiFi → WebREPL
- `firmware/main.py` — polling loop, UI, buttons, display sleep
- `~/.oi/secrets/firmware/oi-v1/secrets.py` — source copy for device-local WiFi + WebREPL creds; copy to the device as `/secrets.py`
- `firmware/test_screen.py` — proves LCD wakes up correctly (run after M5PM1 init)
- `firmware/lib/m5pm1.py` — minimal M5PM1 PMIC driver (just enough to enable LCD power rail)
- `firmware/lib/st7789py.py` — pure-python ST7789 LCD driver (russhughes/st7789py_mpy)
- `firmware/lib/vga2_8x16.py`, `vga2_bold_16x32.py` — bitmap fonts
- `server/oi_server.py` — stdlib HTTP server
- `server/oi_sessions.py` — persisted session registry, prompt projection, and command queue
- `agent/oi.py` — helper/CLI for questions, session prompts, command queue, snapshots, control, status, and healthcheck/cleanup operations
- `agent/pi_bridge.py` — allowlisted bridge from oi command queue to a pi RPC session
- `hooks/preapprove.py` — session-aware approval hook for routing Claude Code tool approvals to oi
- `extensions/oi-device.ts` — pi extension for device-driven pi session control and tool approval routing
- `scripts/pi-oi` — starts a pi session with the oi device extension loaded
- `tests/` — stdlib `unittest` smoke/regression coverage for server + agent/helper/hooks/bridge
- `deploy/oi-server.user.service` — preferred user-level systemd unit for running the server on `.85`
- `deploy/oi-server.service` — system-level systemd unit template, if we later want root-managed `/var/lib/oi` state
- `scripts/push.sh` — OTA push via WebREPL (`./push.sh main.py`, `--all`, plus `--dry-run` / `--status` safety helpers)
- `scripts/webrepl_cli.py` — vendored from micropython/webrepl, with a local `--command` extension used by `scripts/push.sh --reset`

## Deployment notes

Server process:

```bash
python3 server/oi_server.py --host 0.0.0.0 --port 8842 --state-dir /var/lib/oi
```

Preferred user-level systemd service:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/oi-server.user.service ~/.config/systemd/user/oi-server.service
systemctl --user daemon-reload
systemctl --user enable --now oi-server.service
systemctl --user status oi-server.service
```

The user service stores runtime state outside the repo and does not need root for install/start. `scripts/push.sh` reads WebREPL credentials from `~/.oi/secrets/firmware/oi-v1/webrepl.env` by default; override with `OI_ENV_FILE` if needed. If the service should start at boot before login, enable user lingering once:

```bash
sudo loginctl enable-linger "$USER"
```

System-level alternative:

```bash
sudo install -d -o "$USER" -g "$USER" /var/lib/oi
sudo cp deploy/oi-server.service /etc/systemd/system/oi-server.service
sudo systemctl daemon-reload
sudo systemctl enable --now oi-server.service
```

Agent helper defaults to `http://127.0.0.1:8842`; set `OI_SERVER_URL` if calling it from another host. Firmware should read its target from the device-local `/secrets.py` file:

```python
OI_SERVER_URL = "http://gateway.local:8842"
```

Run tests before changing server/agent behavior:

```bash
python3 -m unittest discover -s tests -v
```

Useful operator commands are collected in [`OPERATOR_CHEATSHEET.md`](OPERATOR_CHEATSHEET.md). For the new session/prompt/command routes, set `OI_API_TOKEN` on both the server and helper/hook/bridge processes if the server is reachable from anything other than trusted localhost/LAN clients.

Session lifecycle tuning env vars (optional):
- `OI_SESSION_STALE_S` (default `900`) — age threshold before a session is marked stale/offline in summaries.
- `OI_SESSION_RETENTION_S` (default `1209600`) — prune inactive sessions older than this when they have no pending prompts/queued commands.
- `OI_MAX_COMPLETED_PROMPTS` (default `500`) — retained non-pending prompts in `router.json`.
- `OI_MAX_FINISHED_COMMANDS` (default `500`) — retained non-queued commands in `router.json`.

Command queue dedupe: `/oi/commands` accepts optional `request_id`; if a queued command with the same `session_id + request_id` already exists, the existing command is returned instead of enqueueing a duplicate.

Queue ops and cleanup endpoints:
- list endpoints support `limit` (`GET /oi/prompts`, `GET /oi/commands`)
- bulk cleanup (`POST /oi/prompts/cancel`, `POST /oi/commands/cancel`, `POST /oi/sessions/cleanup`)

## Power Management

**Level-a (live):** after 30s idle on the "oi" screen, backlight turns off and ST7789 enters SLPIN sleep. Poll cadence slows 5s → 30s. BtnA or BtnB wakes the display (wake-only — button press doesn't also fire an action). Server-pushed questions also wake the display. Biggest win: backlight (~30-40mA) → 0.

**Level-b (parked — tried 2026-04-24, reverted):** wrapping the asleep-loop in `machine.lightsleep()` with `esp32.wake_on_ext0(btnA)` failed in practice: zero polls reached the server across a 90s asleep window, webrepl went "no route to host" after the first sleep. BtnA EXT0 wake DID work correctly.

**Root cause** (researched 2026-04-24, full writeup in [`sleep-research.md`](sleep-research.md)): ESP-IDF explicitly does not maintain WiFi across lightsleep — *"Wi-Fi connections are not maintained in Deep-sleep or Light-sleep mode, even if these functions are not called."* MicroPython doesn't stop WiFi cleanly before lightsleep either (PR #9004 was closed without merge). `PM_POWERSAVE` is modem-sleep while the CPU is awake — it does **not** help lightsleep survive.

**Right pattern:** `machine.deepsleep()` + full reconnect each cycle. ~3-7s reconnect cost, ~10µA during sleep, ~17mA average on a 30s cycle. Significant rewrite since deepsleep re-runs `main.py` from scratch — state has to move to `machine.RTC().memory()`. S3-specific gotcha: use `esp32.wake_on_ext1()` not `wake_on_ext0()` for deepsleep button wake.

**Suggested next approach** (spelled out in `sleep-research.md`): hybrid. Keep current awake-loop for active questions. Only deepsleep when idle. Build a standalone `sleep_test.py` first to verify wake-reason handling, RTC memory persistence, and WiFi reconnect timing before touching main firmware.

**Keep device on USB** until level-b lands. Level-a alone still burns 40-60mA continuous — battery-only is maybe 4-6 hours.

## Bringup gotchas (so we don't waste time again)

1. **ESP32-S3 USB-OTG CDC doesn't honor `SET_CONTROL_LINE_STATE`** — DTR/RTS toggling fails with `EPROTO` regardless of host (LXC or bare metal). esptool's auto-bootloader-entry strategies all fail.
2. **Workaround:** put device into ROM bootloader manually (long-press side button to power off, single-press to wake). The ROM bootloader exposes USB-Serial/JTAG class which IS spec-compliant. Run esptool with `--before no-reset --after no-reset` while in that window.
3. **`/dev/ttyACM0` perms in LXC are a separate hassle** — host udev rule sets 666 on the device, but the LXC's tmpfs view has its own perms. Used `pct exec <vmid> -- chmod 666 /dev/ttyACM0` as a one-shot.
4. **mpremote works fine over CDC** for the running MicroPython REPL — it's only the bootloader entry that needs the DTR/RTS dance.

## Naming

`oi` — short, direct, and accurately describes the device's function.
