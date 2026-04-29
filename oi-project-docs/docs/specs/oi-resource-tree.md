# Oi Resource Tree

## API first, proc view second

The source of truth should be API/events.

The proc-style filesystem is a projection for humans, tools, and agents.

```text
devices register → oi-server stores state → agent/tools use API/events
                                      ↘
                                       proc-like resource tree
```

## Why

API gives correctness:

- authentication;
- versioning;
- streaming;
- reconnect;
- command acknowledgements;
- policy enforcement.

Proc-style tree gives cognition:

- agents can inspect a stable world model;
- humans can debug;
- the system feels like an OS.

## Resource operations

Each node may support:

```text
read
watch
invoke
write-config
```

State should be read-only. Commands should be invoked.

Avoid:

```bash
echo 20 > /devices/stick/state/brightness
```

Prefer:

```bash
oi call /devices/stick/commands/set_brightness --value 20
```

## Tree

```text
/
  server/
  devices/
  agents/
  tasks/
  tools/
  permissions/
  routes/
  memory/
  audio/
  events/
```

## Device example

```text
/devices/oi-stick-001/
  identity.json
  capabilities.json
  state.json
  attention.json
  theme.json
  events/
  commands/
    set_brightness
    mute_until
    show_status
    cache_audio
    play
```

## CLI examples

```bash
oi ls /devices
oi cat /devices/oi-stick-001/state
oi watch /tasks/active
oi call /devices/oi-stick-001/commands/mute_until --until 2026-04-27T15:30:00+10:00
```

## Agent tools

Expose resource access to agents through structured tools:

```json
{
  "tool": "resource.read",
  "path": "/devices/oi-stick-001/state"
}
```

```json
{
  "tool": "resource.invoke",
  "path": "/devices/oi-stick-001/commands/set_brightness",
  "args": {
    "value": 20
  }
}
```

## Optional FUSE

A real FUSE mount would be cool later:

```bash
mount -t oi oi://localhost ~/oi
cat ~/oi/devices/oi-stick-001/state.json
```

But FUSE should be an adapter over the API, not the core implementation.

## Implementation order

```text
1. Internal resource graph
2. HTTP API
3. CLI: oi ls/cat/watch/call
4. Web dashboard
5. Agent resource tools
6. Optional FUSE/proc mount
```
