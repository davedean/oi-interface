# Observability

## User-facing observability

The user should be able to ask:

```text
what are you doing?
what did you change?
what can you access?
why did you ask for approval?
show recent errors
```

## Developer observability

Track:

- device connections;
- protocol messages;
- audio upload/download;
- STT latency;
- TTS latency;
- model latency;
- tool calls;
- permission decisions;
- task state transitions;
- failed commands;
- firmware crashes;
- reconnects;
- cache usage.

## Logs

Suggested files:

```text
logs/gateway.log
logs/agent.log
logs/tools.log
logs/security.log
logs/device/{device_id}.log
events/events.jsonl
```

## Metrics

- time from release to transcript;
- time from transcript to response text;
- time from response text to audio cached;
- failed audio chunks;
- command ack latency;
- tool call count by risk;
- confirmations approved/denied;
- offline duration by device.

## Dashboard

Minimum dashboard:

- devices online;
- current foreground device;
- active tasks;
- pending confirmations;
- recent tool calls;
- recent errors;
- latest transcript/response;
- protocol logs.

## Trace id

Each user utterance gets a trace id.

Propagate through:

- audio recording;
- STT;
- agent decision;
- tool calls;
- TTS;
- device cache;
- playback.

## Privacy

Do not dump secrets or full private transcripts into generic logs by default.

Separate audit and debug modes.
