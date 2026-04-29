---
name: oi
description: Agent skill for driving Oi personal agent OS. Provides device management, audio routing, and status updates via oi-cli.
license: MIT
metadata:
  version: "0.2"
  tags: [oi, voice, devices, routing, iot]
---

# Oi Skill — Personal Agent OS Integration

## What Is Oi?

Oi is a local-first personal agent OS connecting voice terminals to your agent. It provides:
- **Voice input**: Devices capture audio, Oi runs STT (Whisper), delivers transcript
- **Voice output**: Oi runs TTS (Piper), caches audio, user taps to play
- **Device awareness**: Every message includes context about online devices and capabilities
- **Routing**: Route responses to the right device based on capabilities and content

**Key principle**: Oi owns surfaces and context. The agent owns intelligence and decisions.

---

## Device Context

Every inbound message includes a `device_context` object with available devices and capabilities.

### Context Structure

```json
{
  "source_device": "stick-pocket",
  "foreground": "stick-pocket",
  "online": ["stick-pocket", "pi-screen"],
  "capabilities": {
    "stick-pocket": {"max_spoken_seconds": 12, "private_audio": true, "supports_confirm_buttons": true, "supports_markdown": false},
    "pi-screen": {"max_spoken_seconds": 120, "private_audio": false, "supports_confirm_buttons": true, "supports_markdown": true}
  }
}
```

### Core Fields

| Field | Type | Description |
|-------|------|-------------|
| `source_device` | string | Device user spoke to. Route responses here. |
| `foreground` | string | Primary device for interaction. May differ from source. |
| `online` | array | All connected device IDs. Use for fallback. |
| `capabilities` | object | device_id → capability map. Always check before routing. |

### Capability Fields

| Field | Type | Description |
|-------|------|-------------|
| `max_spoken_seconds` | int | Hard limit on spoken response. 12s = tiny device, 120s = screen. Critical for deciding full vs summary. |
| `private_audio` | bool | Audio should be private. If true, route to pocket device, not speakers. |
| `supports_confirm_buttons` | bool | Can render Yes/No choices. Use for confirmations. |
| `supports_markdown` | bool | Can render rich text. If false, plain text only. |

### Using Device Context

1. Always check `capabilities[device_id]` — assume nothing
2. Use `max_spoken_seconds` to decide if full response or summary fits
3. Check `private_audio` first for sensitive content
4. Use `online` array for fallback if primary device unavailable

### Device States

| State | Meaning | Use When |
|-------|---------|-----------|
| `idle` | Waiting for input | Default |
| `listening` | Recording audio | Don't interrupt |
| `thinking` | Agent deciding | Show during analysis |
| `response_cached` | Response ready | User hasn't tapped yet |
| `playing` | Audio playing | Show while TTS plays |
| `confirm` | Awaiting user choice | Show confirmation buttons |
| `muted` | Suppressed | Audio blocked for privacy |
| `offline` | No connection | Device unreachable |
| `error` | Fault in system | Show error state |
| `task_running` | Long task in progress | Background work |

---

## How Messages Arrive

Oi sends prompts to pi via JSONL RPC (stdin/stdout):
```
The user said: '<transcript>'. Device: <device_id> (foreground), <capabilities>.
```

Example: `The user said: 'mute for 30 minutes'. Device: stick-pocket (foreground), max_spoken_seconds=12, private_audio=True.`

The `device_context` is also in the raw channel message for programmatic access.

---

## oi-cli Commands

Use `oi-cli` as a bash tool. Default output is JSON; use `--human` for readable.

**API base URL**: `http://localhost:8788/api` (CLI base remains configurable via `--api-url`; examples below use the default local gateway)

### List Devices
```bash
oi devices
```
Returns device list with capabilities and state.

### Show Status
```bash
oi show-status --device <device_id> --state <state> [--label "label"]
```
States: idle, thinking, task_running, confirm, muted, error, response_cached, playing

### Mute Device
```bash
oi mute --device <device_id> --minutes <N>
```
Suppress audio for privacy or during sensitive tasks.

### Route Response
```bash
oi route --device <device_id> --text "<text to synthesize>"
```
Synthesize text to speech and cache on device. User taps to hear.

### Play Cached Audio
```bash
oi audio-play --device <device_id> [--response-id <id>]
```
Play latest or specific cached response.

### Gateway Health
```bash
oi status
```

---

## Response Routing Strategy

### Tiny Devices (M5Stick, voice puck)

`max_spoken_seconds=12`, `supports_markdown=false`, `private_audio=true`

- Keep responses under 10 seconds (~20-25 words)
- Plain text only, no markdown
- **Summarize** — don't speak full details
- Show status during long tasks

```bash
oi show-status --device stick-pocket --state thinking --label "Muting"
oi mute --device stick-pocket --minutes 30
oi route --device stick-pocket --text "Muted for 30 minutes."
```

### Screen Devices (Pi screen, desktop)

`max_spoken_seconds=120`, `supports_markdown=true`, `private_audio=false`

- Full responses with markdown, code blocks, lists
- Detailed status with labels
- Up to 2 minutes of spoken content fine

```bash
oi route --device stick-pocket --text "Diff summary on screen."
oi show-status --device pi-screen --state thinking --label "Generating diff"
```

### Multi-Device Routing

1. Route spoken response to `source_device`
2. Update all devices with status so user sees progress anywhere
3. Route confirmations to device with `supports_confirm_buttons=true`
4. Route sensitive content to device with `private_audio=true`

---

## Response Formatting Best Practices

### By Device Type

| Type | Spoken Response | Visual |
|------|-----------------|--------|
| **Pocket Stick** | 1-2 sentences, <15 words | Plain status |
| **Voice Puck** | Brief confirmation | LED indicator |
| **Pi Screen** | Full summary, 30-60s | Rich markdown |
| **Desktop** | Optional | Full content |

### Content Guidelines

**Yes/No Confirmations**: Stick = "Yes" or "Confirm on screen", Screen = Full card with buttons

**Status Updates**: Stick = One sentence, Screen = Full details with bullets

**Lists**: Stick = First 3 + "more on screen", Screen = Complete list

**Errors**: Stick = "Check screen", Screen = Full error + context

**Success**: Stick = Brief word ("Done"), Screen = Detailed result

### Length Heuristics

~2.5 words/second for TTS. 12s ≈ 30 words, 30s ≈ 75 words, 120s ≈ 300 words.

---

## Examples

### 1. Short Spoken Reply
User: "what time is it?" on Stick (max_spoken_seconds=12)
```bash
oi route --device stick-pocket --text "It's 3 PM."
```

### 2. Routing Long Reply
User asks detailed status from Stick.
```bash
oi route --device stick-pocket --text "Found 3 issues. Two minor, one blocked. Details on Pi screen."
oi show-status --device pi-screen --state thinking --label "Status check complete"
```

### 3. Long Task Status
User asks to assess a repo (takes time).
```bash
oi show-status --device stick-pocket --state thinking --label "Assessing repo"
oi show-status --device pi-screen --state task_running --label "Repo analysis"
# ... perform analysis ...
oi show-status --device stick-pocket --state response_cached --label "Done"
oi route --device stick-pocket --text "47 changed files. 3 issues: 2 style, 1 edge case."
oi show-status --device pi-screen --state idle --label "Complete"
```

### 4. Mute for Privacy
User reviewing sensitive content.
```bash
oi mute --device pi-screen --minutes 15
oi route --device stick-pocket --text "Room audio muted. Response on pocket device."
```

### 5. Multi-Device Confirmation
Multiple devices online, task needs confirmation.
```bash
oi show-status --device pi-screen --state confirm --label "Apply changes?"
oi route --device stick-pocket --text "Review needed on Pi screen."
```

### 6. Fallback When Device Offline
Stick offline, Pi screen available.
```bash
# online: ["pi-screen"], source_device: "stick-pocket" (offline)
oi route --device pi-screen --text "Pocket device offline. Responding here."
```

### 7. Confirm Button Flow
User asked to delete file, needs confirmation.
```bash
oi show-status --device stick-pocket --state confirm --label "Delete file.txt?"
# Next message indicates user confirmed
oi route --device stick-pocket --text "File deleted."
```

### 8. Private Response
User asks about salary (sensitive).
```bash
# private_audio: {"stick-pocket": true, "pi-screen": false}
oi route --device stick-pocket --text "Your salary is $85,000 per year."
```

### 9. List Response
User asks for 5 tasks.
```bash
oi route --device stick-pocket --text "5 tasks: Fix login, Update docs, Review PR, Schedule meeting, Send report. See Pi screen."
oi show-status --device pi-screen --state idle --label "5 tasks"
```

### 10. Error Handling
Task fails.
```bash
oi route --device stick-pocket --text "Build failed. Check Pi screen."
oi show-status --device pi-screen --state error --label "Build failed: npm error"
```

### 11. Quick Success
Simple task succeeds immediately.
```bash
oi route --device stick-pocket --text "Added to your todo list."
```

### 12. Three Devices Online
Pocket, Pi screen, and puck all online.
```bash
for device in stick-pocket pi-screen voice-puck; do
  oi show-status --device $device --state thinking --label "Processing"
done
# ... work ...
for device in stick-pocket pi-screen voice-puck; do
  oi show-status --device $device --state idle
done
```

### 13. Long-Form on Screen
User asks to explain OAuth (120s available).
```bash
oi route --device pi-screen --text "OAuth is an authorization framework that lets apps access user data without exposing passwords. Think of it like a valet key - limited access without handing over your full key..."
```

### 14. Thinking to Response Transition
Analysis done, now respond.
```bash
oi show-status --device stick-pocket --state idle
oi route --device stick-pocket --text "Found the issue. Database timeout at 30 seconds."
```

### 15. Interactive Follow-up
Need user choice to continue.
```bash
oi show-status --device stick-pocket --state confirm --label "Email or Slack?"
# Next message has user choice ("Slack")
oi route --device stick-pocket --text "Sending to Slack."
```

---

## Decision Guidelines

**Use `oi route`**: Deliver spoken response that gets TTS-synthesized. User taps to hear.

**Use `oi show-status`**: Update visual state during operations. Indicate thinking, task_running, etc.

**Use `oi mute`**: User requests privacy, sensitive content, or temporarily block audio.

### Routing Priority

1. **Private audio**: Route to device with `private_audio=true`
2. **Long content**: Summary to tiny device, full to screen
3. **Confirmations**: Route to device with `supports_confirm_buttons=true` or foreground
4. **Status during work**: Update all devices so user sees progress anywhere

---

## Common Patterns

### Quick Acknowledge → Long Work → Update
```bash
oi show-status --device <device> --state thinking --label "Working on it"
# ... work ...
oi show-status --device <device> --state response_cached --label "Done"
oi route --device <device> --text "<brief result>"
```

### Summary to Tiny, Full to Screen
```bash
oi route --device stick-pocket --text "5 files updated. Details on Pi."
oi show-status --device pi-screen --state idle --label "Files updated"
```

### Set and Forget (no device feedback needed)
```bash
oi route --device stick-pocket --text "Scheduled for Tuesday."
```

---

## Error Handling

### Device Offline
```json
{"ok": false, "error": "Device offline", "device_id": "stick-pocket"}
```
**Recovery**: Check `online` array for alternatives. Route to foreground if source unavailable.

### Gateway Unreachable
```
Connection error: [Errno 111] Connection refused
```
**Recovery**: Verify gateway running (`pgrep -f oi-gateway` or `oi status`). Check API URL.

### Command Not Acknowledged
```json
{"ok": false, "command": "route", "device_id": "stick-pocket", "note": "Command sent but not acknowledged"}
```
**Recovery**: Device temporarily busy. Retry once, then try alternative device.

### Rate Limiting
**Recovery**: Batch status updates. Add small delays between rapid commands.

### Malformed Response (TTS issues)
**Recovery**: Strip special characters, replace URLs with "link in screen output", use plain text for `supports_markdown=false`

---

## Configuration

```bash
# Custom API URL
oi --api-url http://your-gateway:8788 devices

# Human-readable output
oi --human devices

# Debug mode
oi --debug devices
```

---

## Installation

1. **Run oi-gateway**: Start the gateway service
2. **Connect devices**: Devices connect via DATP WebSocket (`ws://localhost:8788/datp`)
3. **Start pi**: Agent runs separately
4. **Use oi-cli**: Available as bash tool during agent execution

No SDK required — `oi-cli` is a standard CLI callable from any agent framework.

---

## Summary

- Read `device_context` from every message — know what's available
- Use capabilities (`max_spoken_seconds`, `supports_markdown`, `private_audio`) to format appropriately
- Route spoken responses via `oi route --device X --text "..."`
- Show status during long tasks via `oi show-status --device X --state Y`
- Mute for privacy via `oi mute --device X --minutes N`
- Tiny devices get summaries, screens get full content
- Never auto-speak — user taps to hear responses
- Check `online` for fallback when source device unavailable
- Use `confirm` state for interactive choices