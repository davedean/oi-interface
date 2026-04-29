# Frontend Fixture Schema (Draft)

Status: draft
Owner package: WP-07a

Goal: replay backend events/snapshots deterministically through frontend reducer tests.

## JSONL fixture event types

- `snapshot` - full authoritative state snapshot; replaces frontend session, prompt, and queue slices
- `event` - incremental backend update
- `action` - user/frontend-dispatched action
- `expect` - partial expected frontend state assertion

## Implemented frame shape

```json
{"type":"snapshot","data":{"sessions":{"active_session_id":"s1","list":[]},"prompts":[],"queued_commands":[]}}
{"type":"event","name":"command.queued","data":{"command_id":"c1","session_id":"s1","verb":"status","status":"queued"}}
{"type":"action","name":"session.focus","data":{"session_id":"s1"}}
{"type":"expect","data":{"view":"idle","sessions":{"active_session_id":"s1"}}}
```

## Supported WP-07b names

Actions:
- `session.focus` with `{ "session_id": "s1" }`
- `session.cycle` with `{ "direction": "next" }` or `{ "direction": "prev" }`
- `prompt.answer` with `{ "prompt_id": "p1", "value": "approve" }`
- `command.queue` with `{ "session_id": "s1", "verb": "status", "command_id": "c1" }`

Events:
- `prompt.pending` / `prompt.created`
- `prompt.answered` / `prompt.cancelled`
- `command.queued`
- `command.acked`
- `session.updated`

## Rules

- fixtures must be self-contained
- no wall-clock sleeps; use explicit timestamps if needed
- assertions should use stable ids/fields
- `expect.data` is a deep partial match against reducer state

## Current fixture set

1. `no-sessions.jsonl`
2. `multi-session-switch.jsonl`
3. `prompt-approve-deny.jsonl`
4. `command-queue-ack.jsonl`
5. `reconnect-snapshot-reconcile.jsonl`

## Future fixture coverage still needed

- stale active session beyond snapshot reconcile
- command queued -> failed/cancelled
- cleanup-session bulk cancellation
