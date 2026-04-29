# Apple Ecosystem Strategy

## Thesis

Apple Watch + iPhone + AirPods can reproduce much of the Oi device model with a huge installed base and no custom hardware.

The M5Stick proves the interaction model.  
The Apple ecosystem distributes it.

## Roles

```text
Apple Watch:
  status, complication, haptic, quick confirmation, capture trigger

iPhone:
  app runtime, network bridge, notifications, settings, pairing

AirPods / earbuds:
  private audio input and output
```

## Why it matters

Many people already own the needed hardware.

A paid app can be cheaper than an M5Stick and much easier to adopt.

```text
Buy $10 app
Pair with hosted oi-gateway
Add channel URL to OpenClaw/Hermes/etc
Talk to your agent from wrist or earbuds
```

## Watch as Oi device

The Watch can replace much of the Stick role:

```text
tiny screen:
  complication / Smart Stack / app view

button-ish input:
  complication tap / app button / Action Button on Ultra / notification action

response ready:
  haptic + complication state

confirm/deny:
  notification actions or app buttons

status character:
  tiny state icon or face
```

## iPhone as bridge

The iPhone app exposes:

```json
{
  "id": "iphone-user",
  "type": "mobile_gateway",
  "capabilities": {
    "network": ["https", "tailscale", "hosted_relay"],
    "notifications": true,
    "audio_route": ["airpods", "speaker", "car"],
    "watch_companion": true
  }
}
```

## Watch device document

```json
{
  "id": "watch-user",
  "type": "wrist_status_terminal",
  "capabilities": {
    "input": ["tap", "confirm", "dictation"],
    "output": ["complication", "haptic", "short_text"],
    "preferred_for": ["status", "approval", "quick_capture"]
  }
}
```

## AirPods as route

AirPods are probably not a directly managed Oi device at first. They are an audio route provided by iPhone.

```json
{
  "id": "airpods-route",
  "type": "audio_route",
  "capabilities": {
    "input": ["private_mic"],
    "output": ["private_audio"]
  },
  "provided_by": "iphone-user"
}
```

## Interaction flow

```text
1. Tap Oi complication.
2. Capture request.
3. iPhone sends to oi-gateway or oi-server.
4. Watch shows thinking.
5. Haptic: response ready.
6. Tap play.
7. Response plays privately through AirPods.
8. Long detail opens on phone or another rich surface.
```

## Monetisation

Possible model:

```text
Free/open:
  oi-server
  web dashboard
  M5Stick firmware
  local OpenClaw plugin

Paid app:
  iPhone + Watch + AirPods client

Hosted gateway:
  relay, push notifications, channel URL, pairing

Pro:
  multiple devices/channels, longer retention, richer routing
```

## Constraints

Apple platform constraints are real:

- background execution limits;
- recording limitations;
- notification policies;
- App Store review;
- limited control over AirPods gestures;
- audio session complexity.

The product should fit Apple affordances rather than fight them.

## Strategic point

Build Oi as protocol/runtime first, hardware as proof, Apple app as reach.
