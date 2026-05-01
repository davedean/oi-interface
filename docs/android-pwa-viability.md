# Android PWA oi-client viability assessment

## Verdict

Viable as a small new client, with a gateway audio-format gap to close before voice MVP.

The repository already has the right high-level split for the requested architecture: device clients talk to `oi-gateway` over WebSocket/DATP, and the gateway owns auth/routing/STT/LLM/TTS. A Samsung A10 Chrome PWA can fit this model well if it is implemented as a lightweight browser client that speaks the existing DATP envelope rather than introducing a separate phone-only protocol.

## What already exists

- WebSocket device transport: `src/oi-gateway/src/datp/server.py` accepts DATP WebSocket clients and requires a first `hello` message.
- Device registration/presence/state persistence: `src/oi-gateway/src/registry/service.py` is wired into DATP registration/disconnect/state updates.
- Existing client blueprint: `src/oi-clients/generic_sbc_handheld/oi_client/datp.py` implements connect, hello/ack, reconnect, outbound events, state reports, audio chunks, command handling, and ACKs.
- Gateway STT path: `src/oi-gateway/src/audio/pipeline.py` buffers inbound `audio_chunk` messages and transcribes after `audio.recording_finished`.
- Gateway agent/TTS path: `src/oi-gateway/src/channel/service.py`, `src/oi-gateway/src/text/delivery.py`, and `src/oi-gateway/src/audio/delivery.py` emit display and audio commands back to devices.
- Existing browser code is Python-served/static dashboard code only: `src/oi-dashboard/src/oi_dashboard/*`; it is useful as a serving pattern, but not as the PWA client itself.

## Important protocol mismatch

The requested sketch uses simplified message types such as:

- `device.register`
- `state.set`
- `text.delta` / `text.final`
- `audio.url` / `audio.chunk`
- `input.ptt.start` / `input.ptt.stop`

The current code uses DATP envelopes:

```json
{
  "v": "datp",
  "type": "hello|event|audio_chunk|state|command|ack|error",
  "id": "...",
  "device_id": "...",
  "ts": "2026-05-01T00:00:00.000Z",
  "payload": {}
}
```

So the PWA should register with `type: "hello"`, not `device.register`, unless the gateway is extended with an adapter. The requested registration payload maps cleanly into DATP like this:

```json
{
  "v": "datp",
  "type": "hello",
  "id": "hello_x",
  "device_id": "android-pwa-samsung-a10",
  "ts": "...",
  "payload": {
    "device_type": "android_pwa",
    "protocol": "datp",
    "firmware": "oi-android-pwa/0.1",
    "capabilities": {
      "mic": true,
      "speaker": true,
      "display": true,
      "buttons": true,
      "touch": true
    },
    "state": { "mode": "READY" }
  }
}
```

Gateway-to-phone messages are currently `command` messages with ops such as:

- `display.show_status`
- `display.show_response_delta`
- `display.show_progress`
- `display.show_card`
- `audio.cache.put_begin`
- `audio.cache.put_chunk`
- `audio.cache.put_end`
- `audio.play`
- `audio.stop`
- `device.mute_until`

The PWA can translate those to its local UI states and playback cache.

## Audio viability

### Playback

Feasible. The existing gateway sends PCM16 chunks via `audio.cache.put_*` commands and then `audio.play`. A browser can collect chunks, create a WAV `Blob`, and play it via `HTMLAudioElement` or Web Audio after the user has unlocked audio with a first tap.

A simpler later gateway enhancement would be to add `audio.url` for browser clients, but it is not required for MVP.

### Recording

Partially ready. The PWA can capture microphone input with `MediaRecorder`, but the gateway currently expects `audio_chunk` payloads containing base64 PCM16 (`format: "pcm16"`) and passes raw PCM bytes to STT.

Chrome on Android commonly produces `audio/webm;codecs=opus`. That is good for the phone, but the gateway does not currently transcode WebM/Opus to PCM before STT. Options:

1. Fastest browser MVP: capture via Web Audio API and encode/downsample PCM16 in JS before sending DATP `audio_chunk` messages.
2. Better long-term: allow `audio_chunk.format: "webm_opus"` or binary WebSocket frames and add gateway-side transcoding/normalization.
3. Debug-only fallback: support typed text prompts first via existing `text.prompt` event to validate registration, state, UI, and response playback.

## Required states mapping

Requested state | Existing/mapped state
--- | ---
`idle` | `READY`
`listening` | `RECORDING`
`uploading` | `UPLOADING`
`thinking` | `THINKING` or `display.show_progress`
`response_cached` | `RESPONSE_CACHED`
`playing` | `PLAYING`
`confirm` | `display.show_card`
`muted` | `MUTED`
`offline` | local WebSocket disconnected state / `OFFLINE`
`error` | `ERROR`
`safe_mode` | `SAFE_MODE`
`task_running` | no first-class state; map from progress/task events or add status value
`blocked` | no first-class state; map from error/policy/card or add status value

The existing Python client state machine lacks `CONFIRM`, `TASK_RUNNING`, and `BLOCKED`, but the browser UI can still show them as display states. If these states should be durable/registry-visible, add them to the shared state vocabulary/tests.

## Mobile constraints

- Microphone requires HTTPS or localhost. A phone connecting to a LAN gateway will need HTTPS/WSS via reverse proxy, self-signed local CA, Tailscale HTTPS, Caddy, or similar.
- Audio playback on mobile Chrome must be unlocked by a user gesture. The PWA should perform an explicit first-tap initialization before auto-playing responses.
- Samsung A10-class hardware favours CSS transforms/simple SVG/CSS face animation over canvas/WebGL/heavy libraries.
- Browser WebSocket clients cannot rely on custom headers for auth. Prefer query token, cookie/session, or a gateway-issued pairing token in the DATP hello payload.
- PWA installability needs `manifest.webmanifest`, service worker, and cache rules. None exist yet.

## Recommended implementation shape

Create a new client under `src/oi-clients/android_pwa/` rather than mixing it into `oi-dashboard`.

Suggested files:

- `index.html` - fullscreen UI shell.
- `src/datp.js` - DATP envelope builder/parser, WebSocket lifecycle, reconnect, heartbeat.
- `src/state.js` - state reducer mapping DATP commands to UI states.
- `src/audio-recorder.js` - PTT recording and PCM16/WebM chunk sender.
- `src/audio-player.js` - cache incoming PCM chunks, create WAV blobs, unlock/play audio.
- `src/ui.js` - lightweight face/button/debug drawer rendering.
- `manifest.webmanifest` and `sw.js` - PWA install/offline shell.

Minimal gateway changes for MVP:

1. Serve static PWA assets over HTTPS/WSS-compatible origin, or document reverse proxy setup.
2. Add/confirm browser-safe DATP auth/pairing.
3. Decide browser recording format:
   - JS PCM16 encoding with no gateway change, or
   - gateway WebM/Opus transcoding support.
4. Add tests for an `android_pwa` hello, state reports, audio chunk format, and command ACK path.

## MVP slice

1. PWA connects to `ws(s)://gateway/datp`, sends DATP `hello`, shows connection state.
2. UI handles gateway `command` messages for status/card/text/audio cache and ACKs them.
3. Tap-to-talk records audio; first implementation sends PCM16 DATP chunks and `audio.recording_finished`.
4. Gateway STT -> agent -> TTS path returns text/audio; PWA displays text and plays cached audio.
5. Add reconnect/backoff, heartbeat state, mute toggle event, and optional debug drawer.

## Risk summary

- Low risk: UI, WebSocket registration, reconnect, state labels, debug drawer.
- Medium risk: mobile audio unlock/playback and HTTPS/WSS local setup.
- Highest risk: MediaRecorder WebM/Opus ingestion unless gateway transcoding is added or client sends PCM16.

Overall, this is a good fit for the existing architecture and should be treated as a new browser client plus a small audio/auth hardening pass in the gateway.
