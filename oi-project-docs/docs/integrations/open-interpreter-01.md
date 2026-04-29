# Integration: Open Interpreter 01 / 01 Light

## Current understanding

Open Interpreter's 01 Light is a handheld push-to-talk voice interface powered by an ESP32 chip. It sends the user's voice over Wi-Fi to a 01 Server and plays back received audio.

## Similarities

Agent Stick shares the hardware/server split:

```text
ESP32-class handheld
  → Wi-Fi audio transport
    → server-side agent/STT/TTS/tools
```

## Differences

Agent Stick emphasizes:

- cached response playback controlled by the user;
- multi-device embodiment registry;
- character/status state;
- task ledger;
- tool broker and permissions;
- device-agnostic runtime;
- local-first personal wiki;
- multiple agent ecosystem integrations.

## Possible reuse

- hardware lessons;
- ESP32 audio transport ideas;
- case/build inspiration;
- server-client separation;
- safety docs.

## Adapter possibility

If 01 clients expose a usable protocol, Agent Stick could support them as devices.

```text
01 Light client
  → compatibility adapter
    → Agent Stick gateway
```

## Recommendation

Study 01, but keep Agent Stick's protocol independent. The interaction model is different enough to justify DATP.
