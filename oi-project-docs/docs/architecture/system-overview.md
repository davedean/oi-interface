# System Overview

## Layers

```text
Human
  ↓
Embodiments
  - M5Stick voice terminal
  - desktop client
  - phone/watch client
  - web dashboard
  - terminal client
  ↓
Device Gateway
  - DATP connections
  - authentication
  - device registry
  - command routing
  ↓
Chief Agent Runtime
  - persistent session
  - memory context
  - task planner
  - routing policy
  - subagent manager
  ↓
Tool Broker
  - permissions
  - confirmations
  - audit log
  - sandboxing
  ↓
Capabilities
  - filesystem/wiki
  - repo tools
  - shell sandboxes
  - calendar/email
  - Home Assistant
  - OpenClaw/Hermes/MCP
  - browser/research
```

## First implementation

```text
M5StickS3 firmware
  ↕ WebSocket DATP
Pi or home server gateway
  ↕ local Python service
Chief agent
  ↕ tool broker
Whisper / Piper / wiki / repo / todo
```

## Responsibilities

### Device firmware

- record audio on long-hold;
- upload audio chunks;
- cache response audio;
- play cached audio on double-tap;
- show status cards;
- expose battery, Wi-Fi, heap, cache, mode;
- preserve button grammar;
- reject illegal mode transitions;
- survive server disconnects.

### Gateway

- authenticate devices;
- maintain connection state;
- normalize device events;
- expose `/devices` tree;
- route commands to devices;
- persist recent device state;
- handle reconnection and protocol versioning.

### Chief agent

- understand user intent;
- decide immediate/deferred/delegated/refused;
- choose reply surface;
- maintain active tasks;
- delegate to subagents;
- ask for confirmation;
- summarize state.

### Tool broker

- map intents to tool invocations;
- enforce policy;
- record audit log;
- require confirmation for risky tools;
- provide dry-runs;
- isolate third-party skills;
- manage credentials.

### Memory/wiki

- store canonical user-editable project knowledge;
- store agent summaries separately from accepted facts;
- provide retrieval context;
- expose changes as diffs.

## Data flow: simple voice request

```text
1. Human long-holds.
2. Device enters RECORDING and streams audio.
3. Human releases.
4. Device sends audio end event.
5. Gateway stores recording.
6. STT produces transcript.
7. Chief agent handles transcript.
8. Agent generates response and maybe task/tool calls.
9. TTS renders short response.
10. Gateway sends audio cache command to device.
11. Device stores response and shows RESPONSE_CACHED.
12. Human double-taps to play.
```

## Data flow: delegated coding request

```text
1. Human asks for assessment.
2. Chief agent creates task.
3. Tool broker grants read-only repo access to code assessment subagent.
4. Subagent inspects code and writes report.
5. Chief agent decides whether change is viable.
6. If write is required, chief requests confirmation.
7. Confirmation appears on Stick and desktop.
8. User approves.
9. Tool broker applies patch in sandbox or branch.
10. Tests run.
11. Result is summarized on Stick and full report goes to dashboard/wiki.
```

## Architectural bet

The system should treat devices, tools, and agents as nodes in a personal capability graph. The chief agent navigates this graph under user-owned policy.
