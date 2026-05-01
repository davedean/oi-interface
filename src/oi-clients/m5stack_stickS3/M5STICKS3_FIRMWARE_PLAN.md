# M5Stack StickS3 Firmware v2 — Implementation Plan

**Purpose:** Implement DATP-compliant firmware for the M5Stack StickS3 device that connects to oi-gateway v2.

**Reference:** See `oi-project-docs/docs/specs/datp-wire-protocol.md` for the full DATP spec.

**Status:** Planned — not yet implemented

---

## 1. Overview

### 1.1 What This Firmware Does

The M5Stack StickS3 firmware is the "body" side of Oi — it runs on the device and:

1. **Connects to gateway** via DATP over WebSocket
2. **Sends events** — button presses, audio recordings, state changes
3. **Receives commands** — display status, play audio, mute, etc.
4. **Handles local I/O** — buttons, display, audio I/O, WiFi

### 1.2 Key Difference from v1

| v1 Firmware | v2 Firmware |
|-------------|-------------|
| Pi RPC over TCP | DATP over WebSocket |
| Complex protocol with state sync | Lightweight event/command protocol |
| Gateway does less | Gateway handles STT, TTS, agent integration |
| ~15KB MicroPython | ~8-10KB expected (simpler) |

### 1.3 Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      M5Stack StickS3                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   Events   │  │  Commands  │  │  DATP Client        │  │
│  │ - buttons  │  │ - display  │  │  - WebSocket        │  │
│  │ - audio    │  │ - audio    │  │  - message parse    │  │
│  │ - state    │  │ - device   │  │  - hello/ack        │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              Hardware Abstraction                   │    │
│  │  - display (ST7789)  - audio (ES8311)               │    │
│  │  - buttons (GPIO)     - WiFi (network)               │    │
│  │  - power (M5PM1)     - state machine                │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ DATP over WebSocket
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      oi-gateway                              │
│  - DATP server (WebSocket)                                  │
│  - Device registry                                          │
│  - STT (Whisper) → prompt to agent                          │
│  - TTS (Piper) ← response from agent                        │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. File Structure

### 2.1 Proposed Directory Layout

```
m5stack_stickS3/             # Device: M5Stack StickS3
├── boot.py                 # Boot initialization (hardware init)
├── main.py                 # Main event loop
├── version.py              # Firmware version
├── secrets.py.example      # WiFi credentials template
│
├── datp/                   # DATP protocol layer (NEW)
│   ├── __init__.py
│   ├── client.py           # WebSocket DATP client
│   ├── messages.py         # Message parsing/building
│   ├── state.py            # Device state machine
│   └── events.py           # Event builders
│
├── hw/                     # Hardware abstraction (REUSE from v1)
│   ├── __init__.py
│   ├── display.py         # ST7789 display driver
│   ├── buttons.py         # Button input handling
│   ├── audio.py           # ES8311 audio codec
│   ├── power.py           # M5PM1 power management
│   └── wifi.py            # WiFi connectivity
│
├── ui/                     # UI rendering (ADAPTED from v1)
│   ├── __init__.py
│   ├── status.py          # Status display
│   ├── card.py            # Card/message display
│   └── renderer.py        # Display primitives
│
└── lib/                    # Shared libraries
    ├── st7789py.py        # Display driver (from v1)
    ├── vga2_8x16.py       # Font (from v1)
    └── vga2_bold_16x16.py # Font (from v1)
```

---

## 3. DATP Implementation

### 3.1 Client Requirements

The DATP client must:

1. **Connect** — Establish WebSocket to `ws://<gateway>/datp`
2. **Hello** — Send hello with device_id, firmware version, capabilities
3. **Receive hello_ack** — Get session_id, server_time
4. **Send events** — button, audio, state reports
5. **Receive commands** — Parse and execute display, audio, device commands
6. **Send acks** — Confirm command execution
7. **Handle errors** — Reconnect on disconnect, handle protocol errors

### 3.2 Message Types to Implement

| Direction | Type | Implementation |
|-----------|------|----------------|
| Device → Gateway | `hello` | Connect with device_id, firmware, capabilities |
| Gateway → Device | `hello_ack` | Store session_id, server_time |
| Device → Gateway | `event` | button.*, audio.*, device.* events |
| Device → Gateway | `audio_chunk` | PCM16 audio data |
| Device → Gateway | `audio.recording_finished` | Recording complete with format info (see note below) |
| Device → Gateway | `state` | Periodic state reports |
| Device → Gateway | `ack` | Command acknowledgment |
| Device → Gateway | `error` | Device-generated protocol errors (see Section 3.2.1) |
| Gateway → Device | `command` | display.*, audio.*, device.* commands |
| Gateway → Device | `error` | Command failures (from gateway) |

> **⚠️ Audio Format Mismatch:** The device records at 44.1kHz stereo due to ES8311 hardware constraints (see Section 4.2), but the DATP spec expects `audio_chunk` to be 16kHz mono for STT processing. The `audio.recording_finished` event includes `original_sample_rate` and `original_channels` fields so the gateway knows the actual format and can convert accordingly.

**audio.recording_finished Payload** (Device → Gateway):
```json
{
  "v": "datp",
  "type": "event",
  "id": "msg_002",
  "device_id": "stick-001",
  "event": "audio.recording_finished",
  "payload": {
    "duration_ms": 2500,
    "original_sample_rate": 44100,
    "original_channels": 2,
    "samples": 110250
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `duration_ms` | int | Recording duration in milliseconds |
| `original_sample_rate` | int | Actual sample rate of the recording (device sends 44100) |
| `original_channels` | int | Actual channel count (device sends 2 for stereo) |
| `samples` | int | Total sample count (original_channels × original_sample_rate × duration_ms/1000) |

#### 3.2.1 Error Messages (Device → Gateway)

The device sends `error` messages when it encounters protocol-level errors that aren't tied to a specific command. For command failures, use `ack` with `ok: false` instead.

**Error Message Format** (Device → Gateway):
```json
{
  "v": "datp",
  "type": "error",
  "id": "err_001",
  "device_id": "stick-001",
  "payload": {
    "code": "INVALID_STATE",
    "message": "Cannot record while in PLAYING state",
    "related_id": null
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `code` | string | Error code (see Error Codes below) |
| `message` | string | Human-readable error description |
| `related_id` | string? | Related message ID (command ID, event ID, or null) |

**When to Use `error` vs `ack` with `ok: false`:**

| Scenario | Response | Reason |
|----------|----------|--------|
| Command received but cannot execute (invalid state) | `ack` with `ok: false` | The command was understood but rejected due to device state |
| Command has invalid/missing arguments | `ack` with `ok: false` | Command was malformed, device understood it but arguments are wrong |
| Protocol-level error (malformed message, parse failure) | `error` | The message itself was invalid, not just the command |
| Unexpected internal error (hardware failure, memory) | `error` | Internal error not triggered by a specific command |
| WebSocket connection lost | `error` | Transport-level protocol error |

**Device Error Codes:**

| Code | Description | Example |
|------|-------------|---------|
| `INVALID_STATE` | Command rejected due to current device state | Cannot play audio while recording |
| `BUFFER_OVERFLOW` | Audio buffer exceeded capacity | Recording too long, buffer full |
| `AUDIO_ERROR` | Audio hardware failure | Microphone or speaker initialization failed |
| `DISPLAY_ERROR` | Display hardware failure | Display driver error |
| `WIFI_ERROR` | WiFi connection failed | Cannot connect to gateway |
| `PROTOCOL_ERROR` | Malformed message received | Invalid JSON or missing required fields |
| `PARSE_ERROR` | Cannot parse message payload | Command args are invalid |
| `UNKNOWN_COMMAND` | Unknown operation requested | Gateway sent unrecognized command op |
| `MEMORY_ERROR` | Insufficient memory for operation | Cannot allocate buffer |
| `TIMEOUT` | Operation timed out | Audio upload timeout |

> **Note:** The device should NOT generate error codes for expected operational rejections — use `ack` with `ok: false` for those (e.g., command rejected because device is in wrong state). Reserve `error` for unexpected failures and protocol violations.

**Hello Payload** (Device → Gateway):
```json
{
  "v": "datp",
  "type": "hello",
  "id": "msg_001",
  "device_id": "stick-001",
  "ts": "2026-04-27T04:40:00.000Z",
  "payload": {
    "device_type": "stickS3",
    "protocol": "datp",
    "firmware": "oi-fw/0.1.0",
    "capabilities": {
      "audio_in": true,
      "audio_out": true,
      "display": "st7789_135x240",
      "buttons": ["main", "a", "b"],
      "commands_supported": [
        "display.show_status",
        "display.show_card",
        "audio.cache.put_begin",
        "audio.cache.put_chunk",
        "audio.cache.put_end",
        "audio.play",
        "audio.stop",
        "device.set_brightness",
        "device.mute_until",
        "device.set_volume",
        "device.set_led",
        "device.reboot",
        "device.shutdown",
        "wifi.configure",
        "storage.format"
      ]
    },
    "state": {
      "mode": "READY",
      "battery_percent": 95,
      "charging": false,
      "wifi_rssi": -55,
      "heap_free": 200000,
      "uptime_s": 0,
      "audio_cache_used_bytes": 0,
      "muted_until": null
    },
    "resume_token": null,
    "nonce": "abc123def456"
  }
}
```

> **Note:** The `capabilities` field includes device-specific capabilities. For extensions beyond the DATP spec (like `device.set_volume`), list them in `commands_supported`.

> **Capabilities Hash Alternative:** For memory-constrained devices, consider implementing `capabilities_hash` as an optional optimization (SHA256 hash of capabilities JSON). The gateway currently expects full capabilities object.

> **✅ Note:** The gateway implementation sends `audio.cache.put_chunk`. The firmware should implement this operation name.

### 3.3 DATP Client State Machine

```
DISCONNECTED → CONNECTING → HELLO_SENT → CONNECTED
                                      ↓
                              RECONNECTING (on error)
```

### 3.4 WebSocket Library

For MicroPython on ESP32-S3, use `websocket` module (built into MicroPython 1.19+):

```python
import websocket
ws = websocket.WebSocket()
ws.connect("ws://gateway.local:8787/datp")
```

**Note:** If WebSocket is not available in the MicroPython build, implement a minimal frame parser using `usocket`.

---

## 4. Hardware Drivers

### 4.1 Display (ST7789)

From legacy firmware: `st7789py.py` already works. Copy from `src/oi-clients/m5stack_stickS3/lib/st7789py.py`.

**GPIO mapping:**
- MOSI: G39
- SCK: G40
- RS/DC: G45
- CS: G41
- RST: G21
- BL: G38

**Resolution:** 135 × 240

### 4.2 Audio (ES8311)

From v1: `oi_audio.py` handles audio I/O. Copy and adapt.

**I2S pins:**
- MCLK: G18
- BCLK: G17
- LRCK: G15
- DOUT: G14
- DIN: G16

**I2C control:** SDA=G47, SCL=G48

**Audio format for DATP:**
- Format: PCM16
- Sample rate: 44100 Hz (ES8311 hardware requirement - see note below)
- Channels: 2 (stereo)

> **⚠️ ES8311 PLL Constraint:** The ES8311 codec has a PLL lower limit of ~1.4MHz for BCLK. At 16kHz mono (256kHz BCLK), the PLL cannot lock. Therefore the device must record at 44.1kHz stereo (BCLK = 1.4112 MHz). The gateway is responsible for converting to mono and/or resampling to 16kHz for STT processing.

> **⚠️ Format Mismatch with DATP Spec:** The DATP wire protocol specifies that `audio_chunk` should be 16kHz mono, but the ES8311 hardware requires 44.1kHz stereo. This mismatch is resolved by including `original_sample_rate` (44100) and `original_channels` (2) in the `audio.recording_finished` event, allowing the gateway to perform the necessary conversion before STT processing.

### 4.3 Buttons

From v1: G11 (BtnA) and G12 (BtnB) with pull-ups.

**Events to send:**
- `button.pressed` — short press
- `button.long_hold_started` — long press started
- `button.long_hold_ended` — long press released
- `button.released` — button released

**Long-hold threshold:** ~1 second (configurable)

### 4.4 WiFi

Use MicroPython's `network.WLAN`:

```python
import network
wlan = network.WLAN(network.STA_IF)
wlan.connect(ssid, password)
```

**Configuration:** Store in `secrets.py`

---

## 5. Commands to Implement

### 5.1 Required Commands

From DATP spec, the device must implement:

| Command | Description |
|---------|-------------|
| `display.show_status` | Show state + label on display |
| `display.show_card` | Show title, body, buttons |
| `audio.cache.put_begin` | Start receiving audio cache (response_id, format, sample_rate, bytes, label) |
| `audio.cache.put_chunk` | Receive audio chunk |
| `audio.cache.put_end` | End audio cache transfer |
| `audio.play` | Play cached audio |
| `audio.stop` | Stop audio playback |
| `device.set_brightness` | Set display brightness (args: `value`, 0-255) |
| `device.set_volume` | Set speaker volume (args: `level` 0-100) |
| `device.set_led` | Set LED enabled state (args: `enabled` boolean) |
| `device.reboot` | Reboot the device (no args) |
| `device.shutdown` | Shutdown the device (no args) |
| `wifi.configure` | Configure WiFi credentials (args: `ssid`, `password`) |
| `storage.format` | Clear audio cache (no args) |
| `device.mute_until` | Mute until timestamp |

### 5.2 Command Handling Pattern

```python
def handle_command(payload):
    op = payload.get("op")
    args = payload.get("args", {})

    if op == "display.show_status":
        show_status(args["state"], args.get("label", ""))
    elif op == "audio.play":
        play_audio(args.get("response_id", "latest"))
    # ... etc

    # Send ACK
    send_ack(command_id, ok=True)
```

### 5.3 Device Control Commands

#### device.set_volume

Set the speaker volume level.

**Arguments:**
- `level` (int, 0-100): Volume level, 0 = mute, 100 = max

**Implementation:**
```python
elif op == "device.set_volume":
    volume = args.get("level", 50)
    set_volume(min(100, max(0, volume)))
```

#### device.set_led

Enable or disable the device LED.

**Arguments:**
- `enabled` (boolean): True to enable LED, False to disable

**Implementation:**
```python
elif op == "device.set_led":
    led_enabled = args.get("enabled", True)
    set_led(led_enabled)
```

#### device.reboot

Reboot the device. Transitions to BOOTING state.

**Arguments:** None

**Implementation:**
```python
elif op == "device.reboot":
    log("Reboot command received")
    machine.reset()
```

#### device.shutdown

Shutdown the device. Transitions to OFFLINE state.

**Arguments:** None

**Implementation:**
```python
elif op == "device.shutdown":
    log("Shutdown command received")
    go_to_state("OFFLINE")
    # Optionally power off hardware
    power_off()
```

### 5.4 WiFi Configuration Command

#### wifi.configure

Configure WiFi credentials and reconnect.

**Arguments:**
- `ssid` (string): WiFi network name
- `password` (string): WiFi password

**Implementation:**
```python
elif op == "wifi.configure":
    ssid = args.get("ssid")
    password = args.get("password")
    if ssid and password:
        save_wifi_config(ssid, password)
        wifi_connect(ssid, password)
```

**Note:** WiFi credentials should be persisted to non-volatile storage so they survive reboot.

### 5.5 Storage Commands

#### storage.format

Clear the audio cache. Use when gateway wants to free device storage.

**Arguments:** None

**Implementation:**
```python
elif op == "storage.format":
    clear_audio_cache()
    log("Audio cache cleared")
```

---

## 6. State Machine

### 6.1 Device States (12 states)

```
BOOTING → PAIRING → READY → RECORDING → UPLOADING → THINKING → RESPONSE_CACHED → PLAYING
                                      ↓              ↓                                 ↓
                                    MUTED        OFFLINE ←──────────────────────→ READY
                                      ↓                                                   ↓
                                   ERROR ←──────────────────────────────────────→ SAFE_MODE
```

**States:**
- `BOOTING` — Initializing hardware, loading config, establishing WiFi connection. Entry point on device power-on or reboot.
- `PAIRING` — First-time setup mode. Waiting for user to configure WiFi and pair with gateway. The device enters this state if no saved gateway address exists or after a factory reset.
- `READY` — Idle, ready for input. This is the normal listening state. Waiting for button press to start recording.
- `RECORDING` — Recording audio. Activated when user long-holds the button. Audio is captured and buffered for upload.
- `UPLOADING` — Uploading audio to gateway. After recording finishes, the device transfers the audio data to the gateway for STT processing.
- `THINKING` — Waiting for gateway to process request and generate response. The device has uploaded the audio and is waiting for the agent response to be cached.
- `RESPONSE_CACHED` — Agent response audio has been downloaded and cached on the device. Ready to play.
- `PLAYING` — Playing audio response. The cached response audio is being played through the speaker.
- `MUTED` — Device muted. Audio playback is suppressed, typically until a specified timestamp or until the user unmutes.
- `OFFLINE` — Disconnected from gateway. Network connectivity lost or gateway unreachable. Device remains in this state until reconnection.
- `ERROR` — Error state. A critical error occurred (e.g., audio capture failure, protocol error). Transition to SAFE_MODE for recovery.
- `SAFE_MODE` — Safe mode for recovery. Limited functionality, typically triggered after an ERROR. Allows basic operations like factory reset or firmware update.

### 6.2 State Transitions

```
BOOTING → PAIRING (no saved gateway config)
BOOTING → READY (gateway config exists)
BOOTING → OFFLINE (WiFi connection failed)

PAIRING → READY (successfully paired with gateway)
PAIRING → ERROR (pairing failed)

READY → RECORDING (button long-hold started)
READY → MUTED (device.mute_until command)
READY → OFFLINE (connection lost)
READY → BOOTING (device.reboot command)

RECORDING → UPLOADING (button released, recording complete)
RECORDING → READY (recording cancelled/stopped)

UPLOADING → THINKING (audio upload complete)

THINKING → RESPONSE_CACHED (response audio downloaded)
THINKING → READY (timeout or cancelled)
THINKING → ERROR (gateway error)

RESPONSE_CACHED → PLAYING (audio.play command)
RESPONSE_CACHED → READY (response cleared or expired)

PLAYING → RESPONSE_CACHED (playback paused)
PLAYING → READY (playback finished or stopped)

MUTED → READY (mute time expired or unmute)
MUTED → OFFLINE (connection lost)

OFFLINE → READY (reconnected successfully)
OFFLINE → ERROR (max reconnection attempts exceeded)

ERROR → SAFE_MODE (critical error)
ERROR → READY (recoverable error)

SAFE_MODE → BOOTING (exit safe mode / reboot)

# Universal transitions (from any state)
* → ERROR (any critical failure)
* → SAFE_MODE (force safe mode)
* → BOOTING (reboot command)
```

### 6.3 Transition Logic Notes

- **First-time setup:** Device starts in BOOTING, checks for saved gateway config. If none exists, transitions to PAIRING. After successful pairing, saves config and transitions to READY.
- **Normal operation:** From READY, user long-holds button to record. Recording → UPLOADING → THINKING → RESPONSE_CACHED → PLAYING → READY.
- **Reconnection:** If OFFLINE, device attempts reconnection with exponential backoff. After max attempts, transitions to ERROR.
- **Error recovery:** Non-critical errors return to READY. Critical errors go to SAFE_MODE for manual intervention.
- **Reboot:** Any state can transition to BOOTING via device.reboot command.

### 6.4 Command Handling by State

When commands arrive from the gateway, the device must decide how to handle them based on the current state:

| Command | BOOTING | PAIRING | READY | RECORDING | UPLOADING | THINKING | RESPONSE_CACHED | PLAYING | MUTED | OFFLINE | ERROR | SAFE_MODE |
|---------|---------|---------|-------|-----------|-----------|----------|-----------------|---------|-------|---------|-------|------------|
| `display.show_status` | queue | queue | execute | queue | queue | queue | execute | queue | execute | ignore | ignore | execute |
| `display.show_card` | queue | queue | execute | queue | queue | queue | execute | queue | execute | ignore | ignore | execute |
| `audio.play` | reject | reject | execute | reject | reject | queue | execute | queue | reject | reject | ignore | reject |
| `audio.stop` | reject | reject | reject | execute | queue | queue | execute | execute | reject | reject | ignore | reject |
| `audio.cache.put_begin` | queue | queue | queue | queue | queue | queue | clear+execute | queue | queue | ignore | ignore | ignore |
| `audio.cache.put_chunk` | reject | reject | reject | queue | execute | queue | execute | queue | queue | ignore | ignore | reject |
| `device.set_volume` | ignore | ignore | execute | ignore | ignore | ignore | execute | ignore | execute | ignore | ignore | ignore |
| `device.set_brightness` | ignore | ignore | execute | ignore | ignore | ignore | execute | ignore | execute | ignore | ignore | ignore |
| `device.mute_until` | ignore | ignore | execute | ignore | ignore | ignore | execute | ignore | execute | ignore | ignore | ignore |
| `device.reboot` | ignore | execute | execute | execute | execute | execute | execute | execute | execute | execute | execute | execute |
| `device.shutdown` | ignore | execute | execute | execute | execute | execute | execute | execute | execute | ignore | ignore | ignore |
| `wifi.configure` | ignore | execute | execute | ignore | ignore | ignore | execute | ignore | execute | ignore | ignore | ignore |
| `storage.format` | ignore | ignore | execute | ignore | ignore | ignore | execute | ignore | execute | ignore | ignore | ignore |

**Key:**
- `execute` - Handle command immediately
- `queue` - Queue command for later (execute when state changes)
- `reject` - Reject command with ACK `ok: false`, stay in current state
- `ignore` - Ignore command silently (no ACK sent)


**Conflict Resolution Rules:**
1. **Recording conflicts:** If a display command arrives during RECORDING, queue it. When recording finishes, process queued display before returning to READY.
2. **Playback conflicts:** If `audio.play` arrives during PLAYING, restart playback from the beginning (don't queue).
3. **Cache overwrite:** If `audio.cache.put_begin` arrives while a response is cached, clear the old cache first.
4. **State transition on reject:** Rejecting a command does NOT change device state - stay in current state.
5. **Queue limit:** Limit queued commands to 5 to prevent memory overflow. If queue full, reject new commands.

---

## 7. Implementation Steps

### Step 1: Core DATP Client (Priority: HIGH)

**Goal:** Establish WebSocket connection and hello handshake.

**Files:**
- `datp/client.py` — WebSocket client with reconnection
- `datp/messages.py` — Message parsing/building
- `datp/state.py` — Connection state machine

**Tests:**
- Connect to gateway (use oi-sim or local gateway)
- Receive hello_ack
- Handle connection loss and reconnect

**Verification:**
```python
# Should print hello_ack received
client = DATPClient("gateway.local", "stick-001")
await client.connect()
print("Connected, session:", client.session_id)
```

### Step 2: Event Emission (Priority: HIGH)

**Goal:** Send button and state events to gateway.

**Files:**
- `datp/events.py` — Event builders
- `hw/buttons.py` — Button input handling

**Events to implement:**
- `button.pressed`
- `button.long_hold_started`
- `button.released`
- `device.state_changed` — on mode change

**Tests:**
- Press button → event sent to gateway
- Long-hold → long_hold_started event

### Step 3: State Reporting (Priority: MEDIUM)

**Goal:** Periodically send state to gateway.

**Files:**
- `datp/state.py` — Add state reporting

**State to report:**
- mode (READY, RECORDING, etc.)
- battery_percent
- charging
- wifi_rssi
- heap_free
- uptime_s
- audio_cache_used_bytes
- muted_until

**Frequency:** Every 30 seconds or on state change

### Step 4: Audio Recording (Priority: HIGH)

**Goal:** Record audio and send chunks to gateway.

**Files:**
- `hw/audio.py` — Audio recording
- `datp/client.py` — Add audio_chunk sending

**Implementation:**
1. On button long-hold start: start recording
2. Collect PCM16 chunks
3. On button release: send recording_finished event
4. During recording: send audio_chunk messages (every ~500ms)

**Audio format:**
- PCM16
- 44100 Hz (gateway will resample to 16kHz for STT)
- Mono (gateway converts from stereo)

### Step 5: Command Handling — Display (Priority: HIGH)

**Goal:** Implement display commands.

**Files:**
- `hw/display.py` — (or reuse from v1)
- `ui/status.py` — Status display
- `ui/card.py` — Card display

**Commands:**
- `display.show_status(state, label)` — Show status icon + text
- `display.show_card(title, options)` — Show message with options (options: list of {id, label})

### Step 6: Command Handling — Audio (Priority: HIGH)

> **Note:** The gateway sends `audio.cache.put_chunk`. Implement handling for this operation name.

**Goal:** Implement audio playback commands.

**Files:**
- `hw/audio.py` — Audio playback
- `datp/client.py` — Handle cache commands

**Commands:**
- `audio.cache.put_begin(response_id, format, ...)` — Prepare for cache
- `audio.cache.put_chunk(response_id, seq, data_b64)` — Store chunk
- `audio.cache.put_end(response_id, sha256)` — Finalize cache (sha256 optional, may be `null`)
- `audio.play(response_id)` — Play cached audio
- `audio.stop()` — Stop playback

### Step 7: Command Handling — Device (Priority: MEDIUM)

**Goal:** Implement device control commands.

**Files:**
- `hw/power.py` — Brightness control
- `datp/client.py` — Mute handling

**Commands:**
- `device.set_brightness(value)` — 0-255 brightness level
- `device.mute_until(timestamp)` — Mute until time

### Step 8: Display UI (Priority: MEDIUM)

**Goal:** Render status, cards, and character packs.

**Files:**
- `ui/renderer.py` — Drawing primitives
- `ui/status.py` — Status icons
- `ui/card.py` — Message cards

**Status states to display:**
- idle (blank or logo)
- listening (recording indicator)
- thinking (processing indicator)
- response_cached (downloaded indicator)
- playing (playback indicator)
- confirm (yes/no buttons)
- muted (muted indicator)
- offline (disconnected indicator)
- error (error indicator)

**Character packs:** Support rendering character sprites from `oi-gateway/src/character_packs/`

### Step 9: Error Handling & Reconnection (Priority: HIGH)

**Goal:** Handle network errors gracefully.

**Files:**
- `datp/client.py` — Reconnection logic

**Features:**
- Exponential backoff on disconnect (1s, 2s, 4s, 8s, max 30s)
- Resume token support for session recovery
- State preservation during reconnect

### Step 10: Testing & Integration (Priority: HIGH)

**Goal:** Verify end-to-end with gateway.

**Test scenarios:**
1. Device connects → gateway shows online
2. Button press → gateway receives event
3. Long-hold → audio upload → STT → response → TTS → audio play
4. Gateway sends display.show_status → device shows status
5. Disconnect → reconnect → state preserved

---

## 8. Testing Strategy

### 8.1 Unit Tests (MicroPython)

Not practical for embedded — test on host with `unittest.mock`.

### 8.2 Integration Tests with Gateway

Use oi-sim pattern — or connect real device to gateway:

```python
# In test script
import asyncio
from datp.client import DATPClient

async def test_device():
    client = DATPClient("localhost", "stick-test")
    await client.connect()

    # Wait for hello_ack
    await asyncio.sleep(1)

    # Press button (simulate)
    simulate_button_press()

    # Verify event received by gateway
    # ... check gateway logs

    await client.disconnect()

asyncio.run(test_device())
```

### 8.3 Manual Testing

1. Flash firmware to device
2. Configure WiFi in `secrets.py`
3. Start oi-gateway
4. Watch device connect
5. Test button interactions
6. Test audio recording/response cycle

---

## 9. Dependencies

### 9.1 MicroPython Version

MicroPython 1.20+ recommended for:
- `websocket` module
- `asyncio` improvements
- Better memory management

### 9.2 Required Modules

| Module | Source |
|--------|--------|
| `network` | Built-in |
| `websocket` | Built-in (1.19+) |
| `usocket` | Built-in |
| `ujson` | Built-in |
| `ure` | Built-in |
| `utime` | Built-in |
| `machine` | Built-in |
| `st7789py` | From v1 firmware |
| `vga2_*` | From v1 firmware |
| `m5pm1` | From v1 firmware |

### 9.3 Memory Considerations

**Memory Budget (ESP32-S3 ~300KB available heap):**

| Component | Size | Notes |
|-----------|------|-------|
| Audio buffer | ~344KB | 2 sec × 44100 samples/sec × 2 bytes × 2 channels (stereo PCM16) |
| Display framebuffer | ~63KB | 135×240 × 2 bytes (RGB565) |
| WebSocket buffer | ~8KB | RX/TX buffers |
| MicroPython runtime | ~40KB | Interpreter overhead, GC headroom |
| **Subtotal** | **~455KB** | |
| Safety margin | ~10KB | For allocations, stack, network buffers |
| **Total** | **~465KB+** | Exceeds ~300KB heap - optimization required |

#### Memory Reduction Options

| Option | Reduction | Resulting Audio Buffer | Total Memory |
|--------|-----------|------------------------|--------------|
| A: Mono audio | Halved | ~172KB | ~283KB ✅ |
| B: 1 second buffer | Halved | ~172KB (stereo) | ~283KB ✅ |
| C: 1 second mono | Quartered | ~86KB | ~197KB ✅ |

**Recommended:** Use **mono audio** (Option A) — halves buffer to ~172KB, bringing total to ~283KB with comfortable safety margin. The device records stereo but drops one channel before buffering, or the gateway handles mono conversion at the other end.

> **⚠️ Memory Exceeded:** The raw calculation (~465KB) exceeds available ~300KB heap. One of the above optimizations is required.

> **Note:** The ES8311 must record at 44.1kHz stereo due to PLL constraints (BCLK must be ~1.4MHz). For mono, record stereo and drop one channel before buffering, or convert to mono in software before storing. The gateway is responsible for converting to mono and resampling to 16kHz for STT.

---

## 10. Configuration

### 10.1 Device ID

Generate at first boot or hardcode:

```python
# In secrets.py or generated
DEVICE_ID = "stick-001"  # Or use MAC address
```

### 10.2 Gateway Address

```python
# In secrets.py
GATEWAY_HOST = "gateway.local"  # Or another local DNS/mDNS name
GATEWAY_PORT = 8787
```

### 10.3 WiFi Credentials

```python
# In secrets.py
WIFI_SSID = "MyNetwork"
WIFI_PASSWORD = "mypassword"
```

---

## 11. Future Enhancements

After initial implementation:

- **Character packs** — Render avatar sprites from gateway
- **IR remote** — Receive IR signals
- **Battery optimization** — Deep sleep when not in use
- **OTA updates** — Firmware over-the-air
- **BLE mode** — Connect via Bluetooth to phone relay

---

## 12. References

- DATP spec: `oi-project-docs/docs/specs/datp-wire-protocol.md`
- Hardware ref: `src/oi-clients/m5stack_stickS3/HARDWARE.md`
- Legacy firmware: `src/oi-clients/m5stack_stickS3/lib/` (for display/audio drivers)
- oi-gateway: `src/oi-gateway/` (DATP server implementation)
- oi-sim: `src/oi-clients/oi-sim/` (virtual DATP device for testing)

---

## 13. Quick Start (for future agents)

To implement this firmware:

1. **Read the DATP spec** — `oi-project-docs/docs/specs/datp-wire-protocol.md`
2. **Copy hardware drivers** — Copy `st7789py.py`, `vga2_*.py`, `m5pm1.py` from `src/oi-clients/m5stack_stickS3/lib/`
3. **Implement DATP client** — Start with `datp/client.py` WebSocket connection
4. **Test with gateway** — Run `oi-gateway` and connect device
5. **Implement events** — Button, audio, state events
6. **Implement commands** — Display, audio, device commands
7. **Verify** — Full input/output loop works

**Test command:**
```bash
cd <repo>
python -m oi_gateway.src.datp.server  # Start gateway
# ... flash firmware to device and test
```
