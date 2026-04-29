# Integration: Home Assistant

## Why

Home Assistant is likely the easiest path to real-world device and home automation actions.

## Integration options

### REST/WebSocket API

Useful for direct control.

### MQTT

Useful if the user already has MQTT infrastructure.

### Rhasspy/Hermes bridge

Useful for voice-assistant style intent compatibility.

## Recommended posture

Treat Home Assistant as a tool backend.

```text
Chief agent
  → tool broker
    → home_assistant.call_service
      → Home Assistant
```

## Risk classification

Low risk:

- read sensor state;
- turn on desk lamp;
- set non-critical light brightness.

Medium risk:

- climate control;
- media playback in shared space;
- garage door status read.

High risk:

- door locks;
- garage doors;
- alarms;
- ovens/heaters;
- anything that can create safety risk.

## Example tool call

```json
{
  "tool": "home_assistant.call_service",
  "risk": "low",
  "args": {
    "domain": "light",
    "service": "turn_on",
    "target": {
      "entity_id": "light.desk"
    },
    "data": {
      "brightness_pct": 40
    }
  }
}
```

## Voice command examples

```text
turn the desk light down
is the garage closed?
make the house quiet for recording
```

## Safety

Require explicit confirmation for locks, alarms, doors, and appliances.

Also expose "why did you do that?" with service-call audit logs.
