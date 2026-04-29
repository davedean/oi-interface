# Implementation Plan

## Suggested repo structure

```text
agent-stick/
  firmware/
    m5stick/
  server/
    gateway/
    agent/
    tools/
    broker/
    stt/
    tts/
  clients/
    web-dashboard/
    desktop/
  schemas/
  docs/
  examples/
  tests/
```

## Server modules

### `gateway`

- WebSocket DATP server;
- device sessions;
- state registry;
- command routing;
- audio blob handling.

### `agent`

- chief agent loop;
- prompt templates;
- task planner;
- response router;
- subagent manager.

### `broker`

- tool registry;
- permission policy;
- audit log;
- confirmations;
- sandbox invocation.

### `tools`

- device tools;
- wiki tools;
- todo tools;
- repo tools;
- shell sandbox;
- Home Assistant;
- OpenClaw/Hermes/MCP adapters.

### `stt`

- Whisper local adapter;
- future remote STT adapter.

### `tts`

- Piper local adapter;
- response audio cache pipeline.

## Data stores

Start:

```text
data/
  agent.db
  events.jsonl
  audio/
  wiki/
  logs/
```

SQLite tables:

- devices;
- device_events;
- tasks;
- task_events;
- tool_calls;
- confirmations;
- artifacts;
- permissions.

## Firmware modules

```text
firmware/m5stick/
  main.cpp
  datp_client.cpp
  state_machine.cpp
  audio_capture.cpp
  audio_cache.cpp
  display_status.cpp
  buttons.cpp
  power.cpp
  config.cpp
```

## Protocol-first development

Before adding more agent complexity:

1. implement `hello`;
2. implement state report;
3. implement button events;
4. implement audio upload;
5. implement audio cache download;
6. implement display status;
7. implement command ack/error.

## Testing approach

- protocol golden files;
- fake device simulator;
- gateway integration tests;
- audio loopback test;
- state machine tests;
- tool broker policy tests;
- prompt regression tests for common commands.

## First tools

```text
device.mute_until
device.set_brightness
device.show_status
todo.add
wiki.append_inbox
task.list
task.cancel
repo.assess_readonly
```

## First prompts

System prompt should include:

- device capabilities;
- human interaction model;
- short spoken response style;
- tool permission rules;
- active task summary;
- current foreground device.

## Development sequence

1. freeze current working prototype as baseline;
2. add structured event log;
3. add device state schema;
4. introduce gateway boundary;
5. migrate device commands to DATP-like shape;
6. add task ledger;
7. add tool broker;
8. add wiki inbox;
9. add repo read-only assessment;
10. add dashboard.
