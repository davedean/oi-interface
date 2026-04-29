# Application Protocol

## Purpose

The application protocol sits above DATP and represents agent-level interactions: tasks, confirmations, status, routing, and cards.

## Concepts

- utterance;
- response;
- task;
- confirmation;
- notification;
- status character;
- route;
- capability invocation.

## Event: user utterance

```json
{
  "type": "user_utterance",
  "id": "utt_123",
  "source_device": "stick-pocket",
  "input": {
    "modality": "voice",
    "transcript": "mute the device for thirty minutes",
    "audio_ref": "blob://recordings/rec_42.wav"
  },
  "context": {
    "foreground_device": "stick-pocket",
    "local_time": "2026-04-27T14:41:00+10:00"
  }
}
```

## Response object

```json
{
  "type": "agent_response",
  "id": "resp_123",
  "task_id": null,
  "summary": "Muted until 3:11 PM.",
  "spoken_text": "Muted until 3:11 PM.",
  "display_card": {
    "state": "muted",
    "label": "Muted until 15:11"
  },
  "routes": [
    {
      "device_id": "stick-pocket",
      "outputs": ["cached_audio", "status_character"]
    }
  ]
}
```

## Task object

```json
{
  "type": "task",
  "id": "task_001",
  "title": "Assess retry worker change",
  "state": "running",
  "created_by": "user",
  "owner_agent": "chief",
  "subagents": ["subagent_repo_assessor_001"],
  "risk": "medium",
  "requires_confirmation": false,
  "human_visible_summary": "Checking retry worker design.",
  "created_at": "2026-04-27T04:44:00Z",
  "updated_at": "2026-04-27T04:44:30Z"
}
```

## Confirmation object

```json
{
  "type": "confirmation_request",
  "id": "confirm_001",
  "task_id": "task_001",
  "risk": "medium",
  "title": "Apply retry patch?",
  "summary": "Change worker retries to jittered exponential backoff.",
  "details_ref": "dashboard://tasks/task_001/diff",
  "options": [
    {"id": "approve", "label": "Apply"},
    {"id": "deny", "label": "Cancel"}
  ],
  "expires_at": "2026-04-27T05:15:00Z",
  "routes": [
    {
      "device_id": "stick-pocket",
      "display": "compact_confirm",
      "buttons": {
        "A": "approve",
        "B": "deny"
      }
    },
    {
      "device_id": "desktop-main",
      "display": "full_confirm"
    }
  ]
}
```

## Route policy

The chief agent chooses routes. The gateway executes them.

Routing dimensions:

- device capability;
- length;
- sensitivity;
- urgency;
- foreground score;
- user preference;
- interruption policy;
- confirmation requirement.

## Status card

A status card is short:

```json
{
  "state": "thinking",
  "label": "Checking repo",
  "progress": null,
  "task_id": "task_001"
}
```

## Long-form output

Long-form content should go to:

- dashboard;
- wiki draft;
- desktop notification;
- email draft;
- terminal;
- artifact store.

The Stick gets a pointer and a short summary.

## App protocol anti-goals

- Do not stream arbitrary markdown to tiny devices.
- Do not let subagents directly spam devices.
- Do not let devices infer high-level tasks.
- Do not force everything through voice.
