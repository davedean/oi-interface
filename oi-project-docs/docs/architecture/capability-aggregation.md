# Capability Aggregation

## Principle

Devices advertise local affordances.  
Servers aggregate system capabilities.  
Agents choose routes and actions.  
Policies decide what is allowed.

## Capability classes

### Native server capabilities

Things the server can do without devices:

```text
STT
TTS
agent runtime
task ledger
wiki
tool broker
repo tools
OpenClaw bridge
Hermes adapter
MCP adapter
```

### Device-provided capabilities

Things connected devices add:

```text
tiny screen
cached audio
private audio
room speaker
rich display
touch confirmation
physical button
battery presence
watch complication
phone notification
```

### Integration-provided capabilities

Things external systems add:

```text
Home Assistant lights
OpenClaw channels
MCP GitHub
calendar
email
Hermes/Rhasspy voice services
Kimi-style agent endpoint
generic webhook
```

## Effective server capabilities

The server's effective capabilities are the union of:

```text
native server capabilities
+ connected device capabilities
+ configured tool capabilities
+ active integrations
```

Example:

```json
{
  "capability": "display.rich_markdown",
  "provided_by": "device:pi-kiosk-desk",
  "available": true,
  "constraints": {
    "max_chars": 20000,
    "supports_touch_confirm": true
  }
}
```

## Raspberry Pi screen example

When the Pi display registers, it adds a larger output surface to the server.

Before:

```text
/server/effective_capabilities/output:
  tiny_screen
  cached_audio
```

After:

```text
/server/effective_capabilities/output:
  tiny_screen
  cached_audio
  rich_display
  markdown
  diff_review
  touch_confirmation
```

The agent can then route:

```text
Stick:
  "I put the detailed review on the Pi screen."

Pi screen:
  full report, diff, buttons
```

## Apple ecosystem example

When the iOS/watch app registers, it may add:

```text
private_audio_output
watch_status_complication
watch_confirmation
phone_push_notification
mobile_network_bridge
```

If AirPods are active, the server may infer:

```text
private spoken response is acceptable
```

## Device-to-device actions

Post-MVP, devices may trigger actions involving other devices.

Example:

```text
Stick triple-click → wake Pi display
```

But the Stick should not command the Pi directly.

Correct flow:

```text
Stick emits button.triple_click
server policy receives event
server invokes /devices/pi-kiosk/commands/wake_display
```

Devices emit events.  
Server/policy routes actions.

## Resource graph

```text
/server
  identity.json
  capabilities.json
  effective_capabilities.json
  agents/
  policy.json

/devices
  /oi-stick-001
    identity.json
    capabilities.json
    state.json
    events
    commands
  /pi-kiosk-desk
    identity.json
    capabilities.json
    state.json
    events
    commands

/routes
  foreground_device
  available_outputs
  attention_policy

/agents
  /chief
  /coding
  /wiki

/tasks
  active
  pending_confirmations
```

## MVP boundary

MVP:

```text
N devices register to 1 server.
Server knows all devices.
Device receives server identity and default agent.
All user input goes to chief.
Server routes output.
No device-to-device automations.
No device-selected agents.
```
