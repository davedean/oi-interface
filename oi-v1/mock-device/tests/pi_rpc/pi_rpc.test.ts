import assert from "node:assert/strict";
import test from "node:test";
import {
  parseJsonlChunks,
  parseJsonlSync,
  mapGetStateToSnapshot,
  mapExtensionUiRequest,
  mapActionToRpcCommand,
  mapPromptAnswerToRpcCommand,
  RPC_SUPPORTED_VERBS,
  LOCAL_ONLY_VERBS,
} from "../../src/pi_rpc.ts";
import type { SnapshotData } from "../../src/types.ts";
import { initialState, reducer } from "../../src/reducer.ts";

// ── JSONL parser: chunk boundary handling ─────────────────────────────────────

test("parseJsonlChunks: single complete line", () => {
  const result = parseJsonlChunks(['{"type":"state","session_id":"s1"}\n']);
  assert.equal(result.lines.length, 1);
  assert.equal(result.lines[0].line, '{"type":"state","session_id":"s1"}');
  assert.equal(result.remaining, "");
});

test("parseJsonlChunks: multiple complete lines", () => {
  const result = parseJsonlChunks([
    '{"type":"state","session_id":"s1"}\n{"type":"event","name":"prompt.pending"}\n',
  ]);
  assert.equal(result.lines.length, 2);
  assert.equal(result.lines[0].line, '{"type":"state","session_id":"s1"}');
  assert.equal(result.lines[1].line, '{"type":"event","name":"prompt.pending"}');
  assert.equal(result.remaining, "");
});

test("parseJsonlChunks: line split across chunks", () => {
  let result = parseJsonlChunks(['{"type":'], "");
  assert.equal(result.lines.length, 0);
  assert.equal(result.remaining, '{"type":');

  result = parseJsonlChunks(['"state"}\n'], result.remaining);
  assert.equal(result.lines.length, 1);
  assert.equal(result.lines[0].line, '{"type":"state"}');
  assert.equal(result.remaining, "");
});

test("parseJsonlChunks: line split across three chunks", () => {
  let result = parseJsonlChunks(['{"ty'], "");
  assert.equal(result.lines.length, 0);

  result = parseJsonlChunks(["pe\":\""], result.remaining);
  assert.equal(result.lines.length, 0);

  result = parseJsonlChunks(['state"}\n'], result.remaining);
  assert.equal(result.lines.length, 1);
  assert.equal(result.lines[0].line, '{"type":"state"}');
});

test("parseJsonlChunks: empty lines are skipped", () => {
  const result = parseJsonlChunks(['\n\n{"type":"state"}\n\n']);
  assert.equal(result.lines.length, 1);
  assert.equal(result.lines[0].line, '{"type":"state"}');
});

test("parseJsonlChunks: final line without LF stays in remaining", () => {
  const result = parseJsonlChunks(['{"type":"state"}']);
  assert.equal(result.lines.length, 0);
  assert.equal(result.remaining, '{"type":"state"}');
});

test("parseJsonlChunks: CRLF normalised to LF", () => {
  const result = parseJsonlChunks(['{"type":"a"}\r\n{"type":"b"}\r\n']);
  assert.equal(result.lines.length, 2);
  assert.equal(result.lines[0].line, '{"type":"a"}');
  assert.equal(result.lines[1].line, '{"type":"b"}');
});

test("parseJsonlChunks: accumulated buffer across multiple calls", () => {
  let result = parseJsonlChunks(['{"a":1}\n{"b":'], "");
  assert.equal(result.lines.length, 1);
  assert.equal(result.remaining, '{"b":');

  result = parseJsonlChunks(["2}\n"], result.remaining);
  assert.equal(result.lines.length, 1);
  assert.equal(result.lines[0].line, '{"b":2}');
  assert.equal(result.remaining, "");
});

test("parseJsonlChunks: byte offsets are tracked correctly", () => {
  const result = parseJsonlChunks(['abc\ndef\n']);
  assert.equal(result.lines.length, 2);
  assert.equal(result.lines[0].byteOffsetStart, 0);
  assert.equal(result.lines[0].byteOffsetEnd, 3);
  assert.equal(result.lines[1].byteOffsetStart, 4);
  assert.equal(result.lines[1].byteOffsetEnd, 7);
});

// ── parseJsonlSync ───────────────────────────────────────────────────────────

test("parseJsonlSync: parses complete JSONL string", () => {
  const results = parseJsonlSync('{"type":"state"}\n{"type":"event","name":"x"}\n');
  assert.equal(results.length, 2);
  assert.equal((results[0] as Record<string, unknown>).type, "state");
  assert.equal((results[1] as Record<string, unknown>).name, "x");
});

test("parseJsonlSync: skips comment lines", () => {
  const results = parseJsonlSync('# comment\n{"type":"state"}\n');
  assert.equal(results.length, 1);
});

test("parseJsonlSync: throws on invalid JSON", () => {
  assert.throws(() => parseJsonlSync("not json\n"));
});

// ── get_state mapping ─────────────────────────────────────────────────────────

test("mapGetStateToSnapshot: single-session response (bare)", () => {
  const response = {
    type: "state",
    session_id: "sess-1",
    name: "My Session",
    status: "active",
    pending_count: 2,
  };
  const snapshot = mapGetStateToSnapshot(response);

  assert.equal(snapshot.sessions?.active_session_id, "sess-1");
  assert.equal(snapshot.sessions?.list?.length, 1);
  assert.equal(snapshot.sessions?.list?.[0]?.session_id, "sess-1");
  assert.equal(snapshot.sessions?.list?.[0]?.name, "My Session");
  assert.equal(snapshot.sessions?.list?.[0]?.status, "active");
  assert.equal(snapshot.sessions?.list?.[0]?.pending_count, 2);
});

test("mapGetStateToSnapshot: real envelope format", () => {
  const response = {
    type: "response",
    command: "get_state",
    success: true,
    data: {
      session_id: "sess-1",
      name: "My Session",
      status: "active",
      pending_count: 2,
    },
  };
  const snapshot = mapGetStateToSnapshot(response);

  assert.equal(snapshot.sessions?.active_session_id, "sess-1");
  assert.equal(snapshot.sessions?.list?.length, 1);
  assert.equal(snapshot.sessions?.list?.[0]?.session_id, "sess-1");
  assert.equal(snapshot.sessions?.list?.[0]?.name, "My Session");
  assert.equal(snapshot.sessions?.list?.[0]?.status, "active");
  assert.equal(snapshot.sessions?.list?.[0]?.pending_count, 2);
});

test("mapGetStateToSnapshot: envelope with sessions array", () => {
  const response = {
    type: "response",
    command: "get_state",
    success: true,
    data: {
      sessions: [
        { session_id: "s1", name: "Session 1", status: "idle" },
        { session_id: "s2", name: "Session 2", status: "active" },
      ],
      active_session_id: "s2",
    },
  };
  const snapshot = mapGetStateToSnapshot(response);
  assert.equal(snapshot.sessions?.list?.length, 2);
  assert.equal(snapshot.sessions?.active_session_id, "s2");
});

test("mapGetStateToSnapshot: envelope without data falls back to bare", () => {
  // Gracefully handles objects that don't match envelope format
  const response = {
    session_id: "s1",
    name: "Fallback",
    status: "idle",
  };
  const snapshot = mapGetStateToSnapshot(response);
  assert.equal(snapshot.sessions?.active_session_id, "s1");
  assert.equal(snapshot.sessions?.list?.[0]?.name, "Fallback");
});

test("mapGetStateToSnapshot: empty response gives safe defaults", () => {
  const snapshot = mapGetStateToSnapshot({});
  assert.equal(snapshot.sessions?.active_session_id, null);
  assert.equal(snapshot.sessions?.list?.length, 0);
  assert.equal(snapshot.prompts?.length, 0);
});

test("mapGetStateToSnapshot: with sessions array overrides top-level", () => {
  const response = {
    session_id: "top-level-id",
    sessions: [
      { session_id: "s1", name: "Session 1", status: "idle" },
      { session_id: "s2", name: "Session 2", status: "active" },
    ],
    active_session_id: "s2",
  };
  const snapshot = mapGetStateToSnapshot(response);
  assert.equal(snapshot.sessions?.list?.length, 2);
  assert.equal(snapshot.sessions?.active_session_id, "s2");
});

test("mapGetStateToSnapshot: with pending_prompt", () => {
  const response = {
    session_id: "s1",
    status: "active",
    pending_prompt: {
      prompt_id: "p1",
      title: "Which option?",
      body: "Pick one",
      options: [{ label: "A", value: "a" }, { label: "B", value: "b" }],
    },
  };
  const snapshot = mapGetStateToSnapshot(response);
  assert.equal(snapshot.prompts?.length, 1);
  assert.equal(snapshot.prompts?.[0]?.prompt_id, "p1");
  assert.equal(snapshot.prompts?.[0]?.title, "Which option?");
  assert.equal(snapshot.prompts?.[0]?.options?.length, 2);
});

test("mapGetStateToSnapshot: with queue_health and queued_commands", () => {
  const response = {
    session_id: "s1",
    queue_health: {
      oldest_pending_prompt_age_s: 120,
      oldest_queued_command_age_s: 30,
    },
    queued_commands: [
      { command_id: "c1", session_id: "s1", verb: "status", status: "queued" },
    ],
  };
  const snapshot = mapGetStateToSnapshot(response);
  assert.equal(snapshot.queue_health?.oldest_pending_prompt_age_s, 120);
  assert.equal(snapshot.queue_health?.oldest_queued_command_age_s, 30);
  assert.equal(snapshot.queued_commands?.length, 1);
  assert.equal(snapshot.queued_commands?.[0]?.command_id, "c1");
});

test("mapGetStateToSnapshot: with stale session", () => {
  const response = {
    session_id: "s1",
    name: "Stale",
    status: "idle",
    pending_count: 0,
    stale: true,
    last_seen_age_s: 500,
  };
  const snapshot = mapGetStateToSnapshot(response);
  assert.equal(snapshot.sessions?.list?.[0]?.stale, true);
  assert.equal(snapshot.sessions?.list?.[0]?.last_seen_age_s, 500);
});

test("mapGetStateToSnapshot: envelope with pending_prompt in data", () => {
  const response = {
    type: "response",
    command: "get_state",
    success: true,
    data: {
      session_id: "s1",
      pending_prompt: {
        prompt_id: "p1",
        title: "Pick one",
        options: [{ label: "Y", value: "yes" }],
      },
    },
  };
  const snapshot = mapGetStateToSnapshot(response);
  assert.equal(snapshot.prompts?.length, 1);
  assert.equal(snapshot.prompts?.[0]?.prompt_id, "p1");
  assert.equal(snapshot.prompts?.[0]?.title, "Pick one");
});

// ── extension_ui_request mapping ───────────────────────────────────────────────

test("mapExtensionUiRequest: select type with options", () => {
  const msg = {
    type: "extension_ui_request",
    ui_type: "select",
    prompt_id: "ext-123",
    extension_prompt_id: "ep-456",
    title: "Pick an option",
    body: "Choose wisely",
    options: [
      { label: "Yes", value: "yes" },
      { label: "No", value: "no" },
    ],
    session_id: "s1",
  };
  const result = mapExtensionUiRequest(msg);
  assert.equal(result.prompt_id, "ext-123");
  assert.equal(result.extension_prompt_id, "ep-456");
  assert.equal(result.ui_type, "select");
  assert.equal(result.title, "Pick an option");
  assert.equal(result.body, "Choose wisely");
  assert.equal(result.options.length, 2);
  assert.equal(result.session_id, "s1");
});

test("mapExtensionUiRequest: real protocol shape with id, method, message", () => {
  const msg = {
    type: "extension_ui_request",
    id: "req-789",
    method: "confirm",
    title: "Confirm action?",
    message: "This will proceed with the operation.",
    options: [
      { label: "OK", value: "ok" },
      { label: "Cancel", value: "cancel" },
    ],
    session_id: "s2",
  };
  const result = mapExtensionUiRequest(msg);
  assert.equal(result.prompt_id, "req-789");
  assert.equal(result.extension_prompt_id, "req-789");
  assert.equal(result.ui_type, "confirm");
  assert.equal(result.title, "Confirm action?");
  assert.equal(result.body, "This will proceed with the operation.");
  assert.equal(result.options.length, 2);
  assert.equal(result.session_id, "s2");
});

test("mapExtensionUiRequest: method maps to ui_type", () => {
  const msg = {
    type: "extension_ui_request",
    id: "req-input",
    method: "input",
    title: "Enter value",
  };
  const result = mapExtensionUiRequest(msg);
  assert.equal(result.ui_type, "input");
  assert.equal(result.prompt_id, "req-input");
  assert.equal(result.extension_prompt_id, "req-input");
});

test("mapExtensionUiRequest: confirm type without options", () => {
  const msg = {
    type: "extension_ui_request",
    ui_type: "confirm",
    prompt_id: "ext-789",
    title: "Confirm?",
  };
  const result = mapExtensionUiRequest(msg);
  assert.equal(result.prompt_id, "ext-789");
  assert.equal(result.ui_type, "confirm");
  assert.equal(result.options.length, 0);
});

test("mapExtensionUiRequest: input type", () => {
  const msg = {
    type: "extension_ui_request",
    ui_type: "input",
    id: "ext-input-1",
    title: "Enter value",
    body: "Type something",
  };
  const result = mapExtensionUiRequest(msg);
  assert.equal(result.prompt_id, "ext-input-1");
  assert.equal(result.extension_prompt_id, "ext-input-1");
  assert.equal(result.ui_type, "input");
});

test("mapExtensionUiRequest: missing prompt_id generates one", () => {
  const msg = {
    type: "extension_ui_request",
    ui_type: "confirm",
    title: "OK?",
  };
  const result = mapExtensionUiRequest(msg);
  assert.ok(result.prompt_id !== null && result.prompt_id.startsWith("ext-"));
  assert.ok(result.prompt_id !== null && result.prompt_id.length > 4);
});

test("mapExtensionUiRequest: editor type", () => {
  const msg = {
    type: "extension_ui_request",
    ui_type: "editor",
    prompt_id: "ext-edit",
    title: "Edit file",
  };
  const result = mapExtensionUiRequest(msg);
  assert.equal(result.ui_type, "editor");
});

test("mapExtensionUiRequest: message field maps to body", () => {
  const msg = {
    type: "extension_ui_request",
    id: "msg-test",
    method: "select",
    title: "Choose",
    message: "Pick from the list",
  };
  const result = mapExtensionUiRequest(msg);
  assert.equal(result.body, "Pick from the list");
});

test("mapExtensionUiRequest: body takes precedence over message", () => {
  const msg = {
    type: "extension_ui_request",
    id: "prec-test",
    body: "Use this body",
    message: "Not this message",
  };
  const result = mapExtensionUiRequest(msg);
  assert.equal(result.body, "Use this body");
});

// ── action → rpc command mapping ──────────────────────────────────────────────

test("mapActionToRpcCommand: status verb maps to get_state type", () => {
  const result = mapActionToRpcCommand(
    { verb: "status", session_id: "s1" },
    "s1",
  );
  assert.notEqual(result, null);
  assert.equal(result!.type, "get_state");
  assert.equal(result!.session_id, "s1");
});

test("mapActionToRpcCommand: abort verb", () => {
  const result = mapActionToRpcCommand(
    { verb: "abort", session_id: "s1" },
    "s1",
  );
  assert.notEqual(result, null);
  assert.equal(result!.type, "abort");
});

test("mapActionToRpcCommand: follow_up verb with message", () => {
  const result = mapActionToRpcCommand(
    { verb: "follow_up", session_id: "s1", message: "continue" },
    "s1",
  );
  assert.notEqual(result, null);
  assert.equal(result!.type, "follow_up");
  assert.equal(result!.message, "continue");
});

test("mapActionToRpcCommand: steer verb with message", () => {
  const result = mapActionToRpcCommand(
    { verb: "steer", session_id: "s1", message: "change direction" },
    "s1",
  );
  assert.notEqual(result, null);
  assert.equal(result!.type, "steer");
  assert.equal(result!.message, "change direction");
});

test("mapActionToRpcCommand: prompt verb with message", () => {
  const result = mapActionToRpcCommand(
    { verb: "prompt", session_id: "s1", message: "what is 2+2?" },
    "s1",
  );
  assert.notEqual(result, null);
  assert.equal(result!.type, "prompt");
  assert.equal(result!.message, "what is 2+2?");
});

test("mapActionToRpcCommand: status verb does not include message", () => {
  const result = mapActionToRpcCommand(
    { verb: "status", session_id: "s1", message: "ignored" },
    "s1",
  );
  assert.notEqual(result, null);
  assert.equal(result!.type, "get_state");
  assert.equal((result as Record<string, unknown>).message, undefined);
});

test("mapActionToRpcCommand: speak verb returns null (local only)", () => {
  const result = mapActionToRpcCommand(
    { verb: "speak", session_id: "s1" },
    "s1",
  );
  assert.equal(result, null);
});

test("mapActionToRpcCommand: unknown verb returns null", () => {
  const result = mapActionToRpcCommand(
    { verb: "unknown_verb", session_id: "s1" },
    "s1",
  );
  assert.equal(result, null);
});

test("mapActionToRpcCommand: uses activeSessionId as fallback", () => {
  const result = mapActionToRpcCommand(
    { verb: "status" },
    "active-session",
  );
  assert.notEqual(result, null);
  assert.equal(result!.session_id, "active-session");
});

test("mapActionToRpcCommand: includes request_id when present", () => {
  const result = mapActionToRpcCommand(
    { verb: "status", session_id: "s1", request_id: "r1" },
    "s1",
  );
  assert.notEqual(result, null);
  assert.equal(result!.request_id, "r1");
});

test("mapActionToRpcCommand: follow_up without message omits message field", () => {
  const result = mapActionToRpcCommand(
    { verb: "follow_up", session_id: "s1" },
    "s1",
  );
  assert.notEqual(result, null);
  assert.equal(result!.type, "follow_up");
  assert.equal((result as Record<string, unknown>).message, undefined);
});

test("mapActionToRpcCommand: null verb returns null", () => {
  const result = mapActionToRpcCommand({}, "s1");
  assert.equal(result, null);
});

// ── Verb classification ──────────────────────────────────────────────────────

test("RPC_SUPPORTED_VERBS includes expected verbs", () => {
  assert.equal(RPC_SUPPORTED_VERBS.has("status"), true);
  assert.equal(RPC_SUPPORTED_VERBS.has("abort"), true);
  assert.equal(RPC_SUPPORTED_VERBS.has("follow_up"), true);
  assert.equal(RPC_SUPPORTED_VERBS.has("steer"), true);
  assert.equal(RPC_SUPPORTED_VERBS.has("prompt"), true);
  assert.equal(RPC_SUPPORTED_VERBS.size, 5);
});

test("LOCAL_ONLY_VERBS includes speak", () => {
  assert.equal(LOCAL_ONLY_VERBS.has("speak"), true);
  assert.equal(LOCAL_ONLY_VERBS.size, 1);
});

// ── prompt.answer → extension_ui_response mapping ────────────────────────────

test("mapPromptAnswerToRpcCommand: routes to extension_ui_response with id", () => {
  const pendingIds = new Map<string, string>();
  pendingIds.set("p-1", "ep-abc-123");
  const result = mapPromptAnswerToRpcCommand(
    { prompt_id: "p-1", value: "yes" },
    pendingIds,
  );
  assert.notEqual(result, null);
  assert.equal(result!.type, "extension_ui_response");
  assert.equal(result!.id, "ep-abc-123");
  assert.equal(result!.value, "yes");
});

test("mapPromptAnswerToRpcCommand: returns null for unknown prompt_id", () => {
  const pendingIds = new Map<string, string>();
  const result = mapPromptAnswerToRpcCommand(
    { prompt_id: "p-unknown", value: "maybe" },
    pendingIds,
  );
  assert.equal(result, null);
});

test("mapPromptAnswerToRpcCommand: returns null for missing prompt_id", () => {
  const pendingIds = new Map<string, string>();
  pendingIds.set("p-1", "ep-123");
  const result = mapPromptAnswerToRpcCommand(
    { value: "yes" },
    pendingIds,
  );
  assert.equal(result, null);
});

test("mapPromptAnswerToRpcCommand: returns null for missing value", () => {
  const pendingIds = new Map<string, string>();
  pendingIds.set("p-1", "ep-123");
  const result = mapPromptAnswerToRpcCommand(
    { prompt_id: "p-1" },
    pendingIds,
  );
  assert.equal(result, null);
});

// ── Integration: mapGetStateToSnapshot → reducer ──────────────────────────────

test("mapGetStateToSnapshot output is valid reducer input", () => {
  const response = {
    type: "state",
    session_id: "s1",
    name: "Test",
    status: "active",
    pending_count: 1,
    pending_prompt: {
      prompt_id: "p1",
      title: "Q?",
      options: [{ label: "Y", value: "y" }],
    },
  };
  const snapshot = mapGetStateToSnapshot(response);
  const state = reducer(initialState(), { type: "snapshot", data: snapshot });
  assert.equal(state.sessions.active_session_id, "s1");
  assert.equal(state.sessions.list.length, 1);
  assert.equal(state.prompt.pending, true);
  assert.equal(state.prompt.prompt_id, "p1");
});

test("mapGetStateToSnapshot: envelope output is valid reducer input", () => {
  const response = {
    type: "response",
    command: "get_state",
    success: true,
    data: {
      session_id: "s1",
      name: "Test Envelope",
      status: "active",
      pending_count: 1,
      pending_prompt: {
        prompt_id: "p1",
        title: "Q?",
        options: [{ label: "Y", value: "y" }],
      },
    },
  };
  const snapshot = mapGetStateToSnapshot(response);
  const state = reducer(initialState(), { type: "snapshot", data: snapshot });
  assert.equal(state.sessions.active_session_id, "s1");
  assert.equal(state.sessions.list.length, 1);
  assert.equal(state.sessions.list[0].name, "Test Envelope");
  assert.equal(state.prompt.pending, true);
  assert.equal(state.prompt.prompt_id, "p1");
});

// ── Integration: mapExtensionUiRequest → reducer ─────────────────────────────

test("mapExtensionUiRequest output is valid reducer event input", () => {
  const msg = {
    type: "extension_ui_request",
    ui_type: "select",
    prompt_id: "ext-1",
    session_id: "s1",
    title: "Which?",
    body: "Pick one",
    options: [{ label: "A", value: "a" }],
    extension_prompt_id: "ep-1",
  };
  const ext = mapExtensionUiRequest(msg);
  let state = reducer(initialState(), {
    type: "snapshot",
    data: {
      sessions: {
        active_session_id: "s1",
        list: [{ session_id: "s1", name: "Test", status: "active", pending_count: 0, stale: false, last_seen_age_s: 0 }],
      },
    },
  });
  state = reducer(state, {
    type: "event",
    name: "prompt.pending",
    data: {
      prompt_id: ext.prompt_id,
      session_id: ext.session_id,
      title: ext.title,
      body: ext.body,
      options: ext.options,
      status: "pending",
    },
  });
  assert.equal(state.prompt.pending, true);
  assert.equal(state.prompt.prompt_id, "ext-1");
  assert.equal(state.prompt.title, "Which?");
});

test("mapExtensionUiRequest: real protocol shape works through reducer", () => {
  const msg = {
    type: "extension_ui_request",
    id: "req-42",
    method: "confirm",
    title: "Proceed?",
    message: "Confirm this action",
    options: [{ label: "Yes", value: "yes" }, { label: "No", value: "no" }],
    session_id: "s1",
  };
  const ext = mapExtensionUiRequest(msg);
  assert.equal(ext.prompt_id, "req-42");
  assert.equal(ext.extension_prompt_id, "req-42");
  assert.equal(ext.ui_type, "confirm");
  assert.equal(ext.body, "Confirm this action");

  let state = reducer(initialState(), {
    type: "snapshot",
    data: {
      sessions: {
        active_session_id: "s1",
        list: [{ session_id: "s1", name: "Test", status: "active", pending_count: 0, stale: false, last_seen_age_s: 0 }],
      },
    },
  });
  state = reducer(state, {
    type: "event",
    name: "prompt.pending",
    data: {
      prompt_id: ext.prompt_id,
      session_id: ext.session_id,
      title: ext.title,
      body: ext.body,
      options: ext.options,
      status: "pending",
    },
  });
  assert.equal(state.prompt.pending, true);
  assert.equal(state.prompt.prompt_id, "req-42");
});

// ── Integration: action mapping round-trip ────────────────────────────────────

test("mapActionToRpcCommand: all supported verbs produce type field with correct mapping", () => {
  const expectedMapping: Record<string, string> = {
    status: "get_state",
    abort: "abort",
    follow_up: "follow_up",
    steer: "steer",
    prompt: "prompt",
  };
  for (const [verb, expectedType] of Object.entries(expectedMapping)) {
    const result = mapActionToRpcCommand({ verb, session_id: "s1" }, "s1");
    assert.notEqual(result, null, `expected non-null for verb '${verb}'`);
    assert.equal(result!.type, expectedType, `expected type '${expectedType}' for verb '${verb}'`);
  }
});

test("mapActionToRpcCommand: message verbs forward message payload", () => {
  const messageVerbs = ["follow_up", "steer", "prompt"];
  for (const verb of messageVerbs) {
    const result = mapActionToRpcCommand(
      { verb, session_id: "s1", message: `hello from ${verb}` },
      "s1",
    );
    assert.notEqual(result, null, `expected non-null for verb '${verb}'`);
    assert.equal(result!.message, `hello from ${verb}`, `expected message for verb '${verb}'`);
  }
});