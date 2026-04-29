# Server, Device, Agent, and Session Topology

## MVP topology

Build this first:

```text
N devices
  → 1 oi-server
    → 1 chief agent
```

This gives multi-device routing without identity chaos.

## Later topologies

### Many devices, one server, many subagents

```text
N devices
  → 1 oi-server
    → 1 chief agent
      → many subagents
```

This is the first useful expansion.

### Many devices, one server, many named agents

```text
N devices
  → 1 oi-server
    → chief agent
    → coding agent
    → home agent
    → wiki agent
```

The chief should remain default. Direct targeting is advanced mode.

### Many devices, many servers, many agents

```text
N devices
  → many server profiles
    → many agent runtimes
```

This is post-MVP and should be treated carefully.

## Definitions

```text
Device:
  physical or software embodiment.

Server:
  gateway/runtime that devices connect to.

Agent:
  reasoning identity or role.

Session:
  current model conversation/context for an agent.

Task:
  durable unit of work that may outlive a session.
```

Important rule:

```text
Tasks belong to agents, not sessions.
Sessions are disposable.
```

## Device server profiles

A device may eventually know multiple server profiles:

```json
{
  "device_id": "oi-stick-001",
  "profiles": [
    {
      "id": "home",
      "name": "Home Oi",
      "url": "wss://oi-home.local/device",
      "default": true
    },
    {
      "id": "laptop",
      "name": "Laptop Oi",
      "url": "wss://gateway.example.com/device"
    }
  ],
  "active_profile": "home"
}
```

MVP can support only one active server while keeping the protocol fields.

## Agent targeting

All device utterances should target the chief agent in MVP:

```json
{
  "source_device": "oi-stick-001",
  "target_server": "home",
  "target_agent": "chief",
  "routing_hint": null
}
```

Later:

```text
"ask the coding agent..."
"switch to lab server"
"talk directly to home agent"
```

These are advanced mode features.

## Session cycling

Existing device-side session cycling is useful for development, but should not become the main user model.

Better framing:

```text
normal mode:
  talk to Oi

advanced/debug mode:
  choose server / agent / session
```

## Rule of thumb

A device has one active uplink.  
A server has one default chief.  
The chief can have many workers.

This gives:

```text
many bodies
one coordinator
many hands
```
