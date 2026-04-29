import assert from "node:assert/strict";
import { readdirSync } from "node:fs";
import test from "node:test";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { initialState, reducer } from "../../src/reducer.ts";

// Resolve fixtures relative to this test file's location, not process.cwd()
// (tsx --test sets cwd to each test file's directory, not the repo root).
const __testDir = dirname(fileURLToPath(import.meta.url));
const FIXTURE_DIR = join(__testDir, "../../../tests/fixtures/pi-events");
import { replayFile } from "../../src/replay.ts";
import type { ReducerFrame } from "../../src/types.ts";

// ── Existing tests ──

test("prompt view is only prioritized for the active session", () => {
  let state = initialState();
  const snapshot: ReducerFrame = {
    type: "snapshot",
    data: {
      sessions: {
        active_session_id: "s1",
        list: [
          { session_id: "s1", name: "one", status: "idle", pending_count: 0, stale: false, last_seen_age_s: 0 },
          { session_id: "s2", name: "two", status: "waiting", pending_count: 1, stale: false, last_seen_age_s: 0 },
        ],
      },
      prompts: [
        { prompt_id: "p-s2", session_id: "s2", title: "Question", body: "For s2", options: [], status: "pending" },
      ],
    },
  };

  state = reducer(state, snapshot);
  assert.equal(state.view, "idle");
  assert.equal(state.prompt.pending, false);

  state = reducer(state, { type: "action", name: "session.focus", data: { session_id: "s2" } });
  assert.equal(state.view, "prompt");
  assert.equal(state.prompt.prompt_id, "p-s2");
});

test("prompt.answer clears pending prompt and records action result", () => {
  let state = reducer(initialState(), {
    type: "snapshot",
    data: {
      sessions: {
        active_session_id: "s1",
        list: [{ session_id: "s1", name: "one", status: "waiting", pending_count: 1, stale: false, last_seen_age_s: 0 }],
      },
      prompts: [{ prompt_id: "p-1", session_id: "s1", title: "Q", body: "B", options: [], status: "pending" }],
    },
  });

  state = reducer(state, { type: "action", name: "prompt.answer", data: { prompt_id: "p-1", value: "approve" } });
  assert.equal(state.view, "idle");
  assert.equal(state.prompt.pending, false);
  assert.equal(state.last_action_result.ok, true);
  assert.equal(state.last_action_result.code, "prompt_answered");
});

// ── command.cancel ──

test("command.cancel removes a queued command", () => {
  let state = reducer(initialState(), {
    type: "snapshot",
    data: {
      sessions: {
        active_session_id: "s1",
        list: [{ session_id: "s1", name: "alpha", status: "idle", pending_count: 0, stale: false, last_seen_age_s: 0 }],
      },
      prompts: [],
      queued_commands: [{ command_id: "c-1", session_id: "s1", verb: "status", status: "queued" }],
    },
  });

  state = reducer(state, { type: "action", name: "command.cancel", data: { command_id: "c-1" } });
  assert.equal(state.queued_commands.length, 0);
  assert.equal(state.last_action_result.ok, true);
  assert.equal(state.last_action_result.code, "command_cancelled");
});

test("command.cancel on finished command returns unchanged", () => {
  let state = reducer(initialState(), {
    type: "snapshot",
    data: {
      sessions: {
        active_session_id: "s1",
        list: [{ session_id: "s1", name: "alpha", status: "idle", pending_count: 0, stale: false, last_seen_age_s: 0 }],
      },
      prompts: [],
      queued_commands: [{ command_id: "c-1", session_id: "s1", verb: "status", status: "acked" }],
    },
  });

  state = reducer(state, { type: "action", name: "command.cancel", data: { command_id: "c-1" } });
  assert.equal(state.queued_commands.length, 1);
  assert.equal(state.last_action_result.ok, true);
  assert.equal(state.last_action_result.code, "command_unchanged");
});

test("command.cancel on unknown command returns error", () => {
  const state = reducer(initialState(), {
    type: "action",
    name: "command.cancel",
    data: { command_id: "c-nonexistent" },
  });
  assert.equal(state.last_action_result.ok, false);
  assert.equal(state.last_action_result.code, "command_not_found");
});

test("command.cancel without command_id returns validation error", () => {
  const state = reducer(initialState(), {
    type: "action",
    name: "command.cancel",
    data: {},
  });
  assert.equal(state.last_action_result.ok, false);
  assert.equal(state.last_action_result.code, "validation_error");
});

// ── command.cancel_all ──

test("command.cancel_all removes all queued commands for a session", () => {
  let state = reducer(initialState(), {
    type: "snapshot",
    data: {
      sessions: {
        active_session_id: "s1",
        list: [
          { session_id: "s1", name: "alpha", status: "idle", pending_count: 0, stale: false, last_seen_age_s: 0 },
          { session_id: "s2", name: "beta", status: "idle", pending_count: 0, stale: false, last_seen_age_s: 0 },
        ],
      },
      prompts: [],
      queued_commands: [
        { command_id: "c-1", session_id: "s1", verb: "status", status: "queued" },
        { command_id: "c-2", session_id: "s1", verb: "abort", status: "queued" },
        { command_id: "c-3", session_id: "s2", verb: "status", status: "queued" },
        { command_id: "c-4", session_id: "s1", verb: "follow_up", status: "acked" },
      ],
    },
  });

  state = reducer(state, { type: "action", name: "command.cancel_all", data: { session_id: "s1" } });
  // c-1, c-2 cancelled (queued for s1); c-3 kept (s2); c-4 kept (acked, not queued)
  assert.equal(state.queued_commands.length, 2);
  assert.equal(state.queued_commands[0].command_id, "c-3");
  assert.equal(state.queued_commands[1].command_id, "c-4");
  assert.equal(state.last_action_result.ok, true);
  assert.equal(state.last_action_result.code, "command_cancel_all");
});

test("command.cancel_all without session_id cancels all queued commands globally", () => {
  let state = reducer(initialState(), {
    type: "snapshot",
    data: {
      sessions: {
        active_session_id: "s1",
        list: [{ session_id: "s1", name: "alpha", status: "idle", pending_count: 0, stale: false, last_seen_age_s: 0 }],
      },
      prompts: [],
      queued_commands: [
        { command_id: "c-1", session_id: "s1", verb: "status", status: "queued" },
        { command_id: "c-2", session_id: "s1", verb: "abort", status: "acked" },
      ],
    },
  });

  state = reducer(state, { type: "action", name: "command.cancel_all", data: {} });
  assert.equal(state.queued_commands.length, 1);
  assert.equal(state.queued_commands[0].command_id, "c-2");
  assert.equal(state.last_action_result.ok, true);
});

test("command.cancel_all dry_run does not mutate state", () => {
  let state = reducer(initialState(), {
    type: "snapshot",
    data: {
      sessions: {
        active_session_id: "s1",
        list: [{ session_id: "s1", name: "alpha", status: "idle", pending_count: 0, stale: false, last_seen_age_s: 0 }],
      },
      prompts: [],
      queued_commands: [
        { command_id: "c-1", session_id: "s1", verb: "status", status: "queued" },
      ],
    },
  });

  state = reducer(state, { type: "action", name: "command.cancel_all", data: { dry_run: true } });
  assert.equal(state.queued_commands.length, 1);
  assert.equal(state.last_action_result.ok, true);
  assert.equal(state.last_action_result.code, "command_cancel_all_dry_run");
});

// ── session.cleanup ──

test("session.cleanup cancels pending prompts and queued commands for active session", () => {
  let state = reducer(initialState(), {
    type: "snapshot",
    data: {
      sessions: {
        active_session_id: "s1",
        list: [
          { session_id: "s1", name: "alpha", status: "waiting", pending_count: 2, stale: false, last_seen_age_s: 0 },
          { session_id: "s2", name: "beta", status: "idle", pending_count: 1, stale: false, last_seen_age_s: 0 },
        ],
      },
      prompts: [
        { prompt_id: "p-1", session_id: "s1", title: "Q1", body: "B1", options: [], status: "pending" },
        { prompt_id: "p-2", session_id: "s1", title: "Q2", body: "B2", options: [], status: "pending" },
        { prompt_id: "p-3", session_id: "s2", title: "Q3", body: "B3", options: [], status: "pending" },
      ],
      queued_commands: [
        { command_id: "c-1", session_id: "s1", verb: "status", status: "queued" },
        { command_id: "c-2", session_id: "s1", verb: "abort", status: "acked" },
        { command_id: "c-3", session_id: "s2", verb: "status", status: "queued" },
      ],
    },
  });

  state = reducer(state, { type: "action", name: "session.cleanup", data: {} });
  // s1's 2 pending prompts removed, s1's 1 queued command removed, s2 unaffected
  assert.equal(state.prompts.length, 1);
  assert.equal(state.prompts[0].prompt_id, "p-3");
  assert.equal(state.queued_commands.length, 2);
  assert.equal(state.queued_commands[0].command_id, "c-2"); // acked, not removed
  assert.equal(state.queued_commands[1].command_id, "c-3"); // different session
  assert.equal(state.last_action_result.ok, true);
  assert.equal(state.last_action_result.code, "session_cleanup");
  // pending_count on s1 reduced
  assert.equal(state.sessions.list[0].pending_count, 0);
});

test("session.cleanup with explicit session_id", () => {
  let state = reducer(initialState(), {
    type: "snapshot",
    data: {
      sessions: {
        active_session_id: "s1",
        list: [{ session_id: "s1", name: "alpha", status: "idle", pending_count: 0, stale: false, last_seen_age_s: 0 }],
      },
      prompts: [],
      queued_commands: [],
    },
  });

  // Focus on s1, cleanup s1 explicitly (no prompts/commands so counts are 0)
  state = reducer(state, { type: "action", name: "session.cleanup", data: { session_id: "s1" } });
  assert.equal(state.last_action_result.ok, true);
  assert.equal(state.last_action_result.code, "session_cleanup");
});

test("session.cleanup dry_run does not mutate state", () => {
  let state = reducer(initialState(), {
    type: "snapshot",
    data: {
      sessions: {
        active_session_id: "s1",
        list: [{ session_id: "s1", name: "alpha", status: "waiting", pending_count: 1, stale: false, last_seen_age_s: 0 }],
      },
      prompts: [{ prompt_id: "p-1", session_id: "s1", title: "Q1", body: "B1", options: [], status: "pending" }],
      queued_commands: [{ command_id: "c-1", session_id: "s1", verb: "status", status: "queued" }],
    },
  });

  const before = JSON.parse(JSON.stringify(state));
  state = reducer(state, { type: "action", name: "session.cleanup", data: { dry_run: true } });
  assert.equal(state.prompts.length, 1);
  assert.equal(state.queued_commands.length, 1);
  assert.equal(state.last_action_result.ok, true);
  assert.equal(state.last_action_result.code, "session_cleanup_dry_run");
});

test("session.cleanup without active session returns validation error", () => {
  const state = reducer(initialState(), { type: "action", name: "session.cleanup", data: {} });
  assert.equal(state.last_action_result.ok, false);
  assert.equal(state.last_action_result.code, "validation_error");
});

// ── healthcheck ──

test("healthcheck passes when no thresholds are violated", () => {
  let state = reducer(initialState(), {
    type: "snapshot",
    data: {
      sessions: {
        active_session_id: "s1",
        list: [{ session_id: "s1", name: "alpha", status: "idle", pending_count: 0, stale: false, last_seen_age_s: 0 }],
      },
      queue_health: { oldest_pending_prompt_age_s: 10, oldest_queued_command_age_s: 5 },
    },
  });

  state = reducer(state, { type: "action", name: "healthcheck", data: { max_oldest_prompt_s: 60, max_oldest_command_s: 60, max_stale_sessions: 2 } });
  assert.equal(state.last_action_result.ok, true);
  assert.equal(state.last_action_result.code, "healthcheck_ok");
});

test("healthcheck detects stale session count violation", () => {
  let state = reducer(initialState(), {
    type: "snapshot",
    data: {
      sessions: {
        active_session_id: "s1",
        list: [
          { session_id: "s1", name: "alpha", status: "idle", pending_count: 0, stale: true, last_seen_age_s: 500 },
          { session_id: "s2", name: "beta", status: "idle", pending_count: 0, stale: true, last_seen_age_s: 600 },
        ],
      },
      queue_health: { oldest_pending_prompt_age_s: null, oldest_queued_command_age_s: null },
    },
  });

  state = reducer(state, { type: "action", name: "healthcheck", data: { max_stale_sessions: 1 } });
  assert.equal(state.last_action_result.ok, false);
  assert.equal(state.last_action_result.code, "healthcheck_violations");
  assert.ok(state.last_action_result.message!.includes("stale_sessions=2 > 1"));
});

test("healthcheck detects prompt age violation", () => {
  let state = reducer(initialState(), {
    type: "snapshot",
    data: {
      sessions: {
        active_session_id: "s1",
        list: [{ session_id: "s1", name: "alpha", status: "idle", pending_count: 0, stale: false, last_seen_age_s: 0 }],
      },
      queue_health: { oldest_pending_prompt_age_s: 300, oldest_queued_command_age_s: null },
    },
  });

  state = reducer(state, { type: "action", name: "healthcheck", data: { max_oldest_prompt_s: 60 } });
  assert.equal(state.last_action_result.ok, false);
  assert.equal(state.last_action_result.code, "healthcheck_violations");
  assert.ok(state.last_action_result.message!.includes("oldest_pending_prompt_age_s=300 > 60"));
});

test("healthcheck detects command age violation", () => {
  let state = reducer(initialState(), {
    type: "snapshot",
    data: {
      sessions: {
        active_session_id: "s1",
        list: [{ session_id: "s1", name: "alpha", status: "idle", pending_count: 0, stale: false, last_seen_age_s: 0 }],
      },
      queue_health: { oldest_pending_prompt_age_s: null, oldest_queued_command_age_s: 120 },
    },
  });

  state = reducer(state, { type: "action", name: "healthcheck", data: { max_oldest_command_s: 60 } });
  assert.equal(state.last_action_result.ok, false);
  assert.equal(state.last_action_result.code, "healthcheck_violations");
  assert.ok(state.last_action_result.message!.includes("oldest_queued_command_age_s=120 > 60"));
});

test("healthcheck with no thresholds is always ok", () => {
  const state = reducer(initialState(), { type: "action", name: "healthcheck", data: {} });
  assert.equal(state.last_action_result.ok, true);
  assert.equal(state.last_action_result.code, "healthcheck_ok");
});

test("healthcheck with null age values skips those checks", () => {
  let state = reducer(initialState(), {
    type: "snapshot",
    data: {
      sessions: {
        active_session_id: null,
        list: [],
      },
      queue_health: { oldest_pending_prompt_age_s: null, oldest_queued_command_age_s: null },
    },
  });

  state = reducer(state, { type: "action", name: "healthcheck", data: { max_oldest_prompt_s: 60, max_oldest_command_s: 60 } });
  assert.equal(state.last_action_result.ok, true);
  assert.equal(state.last_action_result.code, "healthcheck_ok");
});

// ── Fixture replays ──

test("fixture replays pass", () => {
  const fixtureDir = FIXTURE_DIR;
  const fixturePaths = readdirSync(fixtureDir)
    .filter((name) => name.endsWith(".jsonl"))
    .sort()
    .map((name) => join(fixtureDir, name));

  const expected = [
    "cleanup-session.jsonl",
    "command-failed-cancel.jsonl",
    "command-queue-ack.jsonl",
    "multi-session-switch.jsonl",
    "no-sessions.jsonl",
    "prompt-approve-deny.jsonl",
    "reconnect-snapshot-reconcile.jsonl",
  ];

  assert.deepEqual(
    fixturePaths.map((path) => path.split("/").at(-1)),
    expected,
  );

  for (const fixturePath of fixturePaths) {
    const result = replayFile(fixturePath);
    assert.ok(result.steps.length > 0, `${fixturePath} should contain replay steps`);
  }
});