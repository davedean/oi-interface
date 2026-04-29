# Pi RPC Wire Protocol Fixtures

Status: draft
Purpose: Replay wire-protocol exchanges for command tests, event projection tests, and UI method round-trips.

---

## Format

Each line is a valid JSON object on its own line (JSONL / newline-delimited JSON). No commas between lines. LF (`\n`) only — no CRLF.

### Envelope types

| Top-level key | Direction | Meaning |
|---------------|-----------|---------|
| `expect` | client → server | The next thing the client is expected to send. Runner validates actual message against this shape. |
| `emit` | server → client | The next thing the server emits. Runner sends this to the client. |
| `comment` | — | Human-readable note; ignored by the runner. |
| `sleep_ms` | — | Milliseconds to wait before processing the next line (for timing tests; default 0). |

### `<echo>` placeholder

Inside any `emit` line, the literal string `"<echo>"` is replaced at runtime with the `id` captured from the most recent `expect` line. This lets response fixtures correlate without hardcoding request ids.

In `expect` lines, `"<echo>"` means "any string; capture it for later echo resolution". It is **not** literally the string `<echo>`.

Example:

```jsonl
{"expect": {"type": "get_state", "id": "<echo>"}}
{"emit":   {"type": "response", "command": "get_state", "id": "<echo>", "success": true, "data": {"sessionId": "s1"}}}
```

When the client sends `{"type": "get_state", "id": "req-42"}`, the runner:
1. Validates the shape matches `expect`.
2. Captures `"req-42"` as the current echo value.
3. Sends `{"type": "response", "command": "get_state", "id": "req-42", "success": true, "data": ...}`.

### Mismatch handling

A mismatch between an `expect` line and the actual client message produces a structured diff and fails the scenario immediately.

---

## Framing rules

RPC mode uses strict JSONL semantics:

- Record delimiter: LF (`\n`) only.
- Clients should accept optional trailing `\r` on each line.
- Do **not** use generic line readers that split on Unicode separators (`U+2028`, `U+2029`) — these are valid inside JSON strings.

See `rpc.md` lines 27–37 for the upstream framing spec.

---

## Relationship to reducer fixtures

The sibling directory `tests/fixtures/pi-events/` contains **reducer-state fixtures** for the frontend reducer tests. Those files have a different format (`snapshot`, `event`, `action`, `expect` envelopes) and test frontend state transitions.

These wire-protocol fixtures are orthogonal — they test the JSON wire format and request/response correlation, not frontend state.

---

## Naming convention

| Pattern | Purpose |
|---------|---------|
| `<command>.jsonl` | Command round-trip test (e.g. `get_state.jsonl`, `bash.jsonl`) |
| `event_<event>.jsonl` | Event projection test (e.g. `event_message_update.jsonl`) |
| `ext_ui_<method>.jsonl` | Extension UI method test (e.g. `ext_ui_select.jsonl`) |

---

## Current fixture set

Place new fixtures here as Steps 3, 4, and 5 progress. The minimal set required to land Step 1:

- `example_get_state.jsonl` — canonical format example (one command, one response)

Planned (to be added by later briefs):

```
event_agent_start.jsonl
event_agent_end.jsonl
event_message_start.jsonl
event_message_update.jsonl
event_message_end.jsonl
event_tool_execution_start.jsonl
event_tool_execution_update.jsonl
event_tool_execution_end.jsonl
event_queue_update.jsonl
event_compaction_start.jsonl
event_compaction_end.jsonl
event_auto_retry_start.jsonl
event_auto_retry_end.jsonl
event_extension_error.jsonl
```

---

## Runner expectations

A wire-fixture runner (see `tests/harness/fake_pi_rpc.ts` in Step 7) should:

1. Read the `.jsonl` file line by line.
2. For `expect` lines: read a line from the client, validate it matches the shape, capture any `<echo>` value.
3. For `emit` lines: send the constructed JSON to the client, replacing `<echo>` with the captured value.
4. For `comment`/`sleep_ms`: skip or wait as appropriate.
5. Report a clear diff on mismatch.
6. Exit 0 if all lines processed; exit non-zero on first failure.
