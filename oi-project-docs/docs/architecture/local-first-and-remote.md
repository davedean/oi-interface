# Local-first and Remote Operation

## Default posture

The primary deployment is local:

```text
M5Stick/device → home Wi-Fi → home server/Pi → local services/tools
```

This gives privacy, low latency, and user ownership.

## Away from home

The system should support remote operation without changing the mental model.

Recommended stages:

### Stage 1: Tailscale/WireGuard

Use a private mesh VPN.

```text
device/phone/laptop → Tailscale → home server
```

Pros:

- simple;
- private;
- works across NAT;
- does not require exposing ports;
- good for technical users.

Cons:

- microcontrollers may not run Tailscale directly;
- Stick may need to connect to a phone hotspot or relay;
- onboarding for non-technical users is harder.

### Stage 2: Phone relay

A phone app can act as a bridge:

```text
M5Stick BLE/Wi-Fi local → phone app → Tailscale/HTTPS → home server
```

Pros:

- mobile connectivity;
- better auth UX;
- can use phone notifications and audio if needed.

Cons:

- requires mobile app;
- battery and background limits.

### Stage 3: Hosted relay

A small hosted relay can forward encrypted events:

```text
device → hosted relay → home server
```

The relay should not see plaintext if possible.

Pros:

- easier onboarding;
- works without VPN;
- supports push notifications.

Cons:

- central service;
- trust and billing;
- reliability expectations.

### Stage 4: Hosted agent runtime

For users without home servers:

```text
device → hosted gateway/runtime → tools/connectors
```

This should remain portable and exportable.

## Remote auth model

Use device pairing plus rotating session tokens.

Suggested layers:

- device identity key;
- gateway-issued session token;
- TLS transport;
- per-command authorization;
- replay protection;
- revocation list.

## Offline behaviour

When away and disconnected:

- device displays offline;
- cached playback still works;
- local notes may be queued;
- unsafe actions are unavailable;
- user can ask "sync later" if storage allows.

## Remote execution safety

When the user is remote, raise confirmation thresholds:

- never apply destructive home automation without explicit approval;
- never run shell writes without high-confidence identity;
- prefer draft mode for communication;
- show which network path is being used.

## Hosted option product line

Possible offerings:

1. Free/self-hosted local runtime.
2. Paid hosted relay only.
3. Paid managed runtime.
4. Enterprise/user-owned VPC deployment.
5. Hardware bundle with default local gateway.

The open protocol should remain usable without the hosted service.
