# Integration: Hermes MQTT / Rhasspy / Snips-style Voice Protocols

## Current understanding

Rhasspy is an open-source, fully offline voice assistant toolkit. Its docs describe compatibility with Hermes protocol services, Home Assistant, Node-RED, OpenHAB, and MQTT/HTTP/WebSocket integration. Rhasspy 2.5 is composed of independent services coordinating over MQTT using a superset of the Hermes protocol.

## Why this matters

This is a different "Hermes" from Hermes Agent.

Hermes MQTT is useful as a voice-service interoperability layer:

- audio input/output services;
- wake/listen events;
- intent recognition;
- text-to-speech;
- Home Assistant style integrations.

## Agent Stick relationship

Agent Stick does not need to adopt Hermes MQTT internally, but it should be able to bridge to it.

Possible bridge:

```text
DATP device events
  ↔ gateway
    ↔ Hermes MQTT topics
      ↔ Rhasspy/STT/TTS/Home Assistant services
```

## Use cases

- swap in Rhasspy STT/TTS services;
- integrate with existing Home Assistant voice workflows;
- expose Agent Stick as a Hermes-compatible satellite;
- reuse MQTT infrastructure for local automation.

## Bridge examples

DATP event:

```json
{
  "event": "audio.recording_finished",
  "stream_id": "rec_42"
}
```

Could map to Hermes/Rhasspy-style audio or intent pipeline.

Agent intent:

```json
{
  "intent": {
    "name": "DeviceMute"
  },
  "slots": {
    "duration": "PT30M"
  }
}
```

Could map back into Agent Stick application protocol.

## Recommendation

Do not make Hermes MQTT the primary protocol for the device. DATP should stay simpler and more embodiment-specific.

Provide a bridge for users already in the Rhasspy/Home Assistant/MQTT world.
