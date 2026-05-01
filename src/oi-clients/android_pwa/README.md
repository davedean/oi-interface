# Android PWA oi-client

A lightweight browser/PWA oi-client target for turning an old Android phone (tested target: Samsung A10 class Chrome) into a desk/wrist-style Oi terminal.

## Scope

The phone is only an I/O terminal:

- captures push-to-talk microphone audio
- sends DATP events/audio/state over WebSocket to `oi-gateway`
- renders visible device states, streamed text, confirmation cards, and a simple animated face
- plays TTS audio returned by the gateway
- makes no direct OpenAI, LLM, STT, or TTS API calls

## Protocol

This target speaks the existing gateway DATP protocol on `/datp`.

On connect it sends a DATP `hello` envelope with:

- `device_type: "android_pwa"`
- `device_name: "Samsung A10"`
- capabilities for mic, speaker, display, buttons, and touch

Gateway commands are mapped locally:

- `display.show_status` -> visible state label/face state
- `display.show_response_delta` -> streamed/final text
- `display.show_card` -> confirmation UI
- `audio.cache.put_begin/chunk/end` -> browser-side PCM cache
- `audio.play` / `audio.stop` -> HTML audio playback
- `device.mute_until` -> muted state

PTT sends:

- `input.ptt.start`
- `audio_chunk` DATP messages with PCM16/16k/mono payloads
- `input.ptt.stop`
- `audio.recording_finished`

## Required UI states

The state model explicitly supports:

`idle`, `listening`, `uploading`, `thinking`, `response_cached`, `playing`, `confirm`, `muted`, `offline`, `error`, `safe_mode`, `task_running`, `blocked`.

## Running locally

```bash
cd src/oi-clients/android_pwa
npm test
npm run test:coverage
npm run dev
```

Open `http://localhost:8080` for local development. For phone microphone access on a LAN, serve over HTTPS and connect to the gateway over WSS, for example with a local reverse proxy or trusted development certificate.

You can override the gateway URL:

```text
https://phone-host/index.html?ws=wss://gateway.example/datp
```

## Test quality gates

The client uses Node's built-in test runner and coverage tooling. `npm run test:coverage` enforces minimum coverage thresholds:

- lines: 95%
- branches: 80%
- functions: 90%

Current coverage is higher than the thresholds for the implemented modules.

## Mobile notes

- Android Chrome requires HTTPS or localhost for microphone capture.
- Audio playback is locked until the first user gesture; the PTT press unlocks playback.
- The UI intentionally uses DOM/CSS only: no framework, canvas, WebGL, or heavy animation library.
- The service worker caches only the app shell, not conversations or audio data.

## Known limitations / next hardening

- Add pairing/auth before exposing beyond a trusted LAN. Browser WebSocket auth should use a pairing token/query parameter/cookie rather than custom headers.
- Add real-device smoke testing on the Samsung A10 to tune buffer size and latency.
- Consider a gateway `audio.url` or WebM/Opus transcoding path later; this MVP sends PCM16 to match the current gateway STT pipeline.
