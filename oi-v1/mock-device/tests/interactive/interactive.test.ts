import assert from "node:assert/strict";
import test from "node:test";
import { parseCommand, interactiveHelp } from "../../src/interactive.ts";

// ── parseCommand: quit / empty ──

test("parseCommand: empty input returns null frame", () => {
  const result = parseCommand("", null);
  assert.equal(result.frame, null);
  assert.equal(result.quit, false);
  assert.equal(result.error, undefined);
});

test("parseCommand: whitespace-only returns null frame", () => {
  const result = parseCommand("   ", null);
  assert.equal(result.frame, null);
  assert.equal(result.quit, false);
});

test("parseCommand: q quits", () => {
  const result = parseCommand("q", null);
  assert.equal(result.frame, null);
  assert.equal(result.quit, true);
});

test("parseCommand: ? returns help error", () => {
  const result = parseCommand("?", null);
  assert.equal(result.frame, null);
  assert.equal(result.quit, false);
  assert.ok(result.error!.includes("session.cycle"));
});

// ── Existing commands ──

test("parseCommand: n → session.cycle next", () => {
  const result = parseCommand("n", null);
  assert.deepEqual(result.frame, { type: "action", name: "session.cycle", data: { direction: "next" } });
});

test("parseCommand: p → session.cycle prev", () => {
  const result = parseCommand("p", null);
  assert.deepEqual(result.frame, { type: "action", name: "session.cycle", data: { direction: "prev" } });
});

test("parseCommand: f <id> → session.focus", () => {
  const result = parseCommand("f s1", null);
  assert.deepEqual(result.frame, { type: "action", name: "session.focus", data: { session_id: "s1" } });
});

test("parseCommand: f without id → error", () => {
  const result = parseCommand("f", null);
  assert.equal(result.frame, null);
  assert.ok(result.error!.includes("Usage"));
});

test("parseCommand: m → snapshot command_menu", () => {
  const result = parseCommand("m", null);
  assert.equal(result.frame!.type, "snapshot");
  assert.equal((result.frame!.data as Record<string, unknown>).view, "command_menu");
});

test("parseCommand: a <pid> <val> → prompt.answer", () => {
  const result = parseCommand("a p1 approve", null);
  assert.deepEqual(result.frame, {
    type: "action",
    name: "prompt.answer",
    data: { prompt_id: "p1", value: "approve" },
  });
});

test("parseCommand: a with multi-word value", () => {
  const result = parseCommand("a p1 yes please", null);
  assert.equal(result.frame!.type, "action");
  const data = result.frame!.data as Record<string, unknown>;
  assert.equal(data.value, "yes please");
});

test("parseCommand: a without value → error", () => {
  const result = parseCommand("a p1", null);
  assert.equal(result.frame, null);
  assert.ok(result.error!.includes("Usage"));
});

test("parseCommand: a without args → error", () => {
  const result = parseCommand("a", null);
  assert.equal(result.frame, null);
  assert.ok(result.error!.includes("Usage"));
});

test("parseCommand: c <verb> → command.queue with active session", () => {
  const result = parseCommand("c status", "s1");
  const data = result.frame!.data as Record<string, unknown>;
  assert.equal(result.frame!.type, "action");
  assert.equal((result.frame! as { name: string }).name, "command.queue");
  assert.equal(data.verb, "status");
  assert.equal(data.session_id, "s1");
});

test("parseCommand: c with JSON args", () => {
  const result = parseCommand('c status {"foo":"bar"}', "s1");
  const data = result.frame!.data as Record<string, unknown>;
  assert.equal(result.frame!.type, "action");
  assert.equal(data.verb, "status");
  assert.equal(data.foo, "bar");
  assert.equal(data.session_id, "s1");
});

test("parseCommand: c without verb → error", () => {
  const result = parseCommand("c", null);
  assert.equal(result.frame, null);
  assert.ok(result.error!.includes("Usage"));
});

test("parseCommand: unknown command → error", () => {
  const result = parseCommand("z", null);
  assert.equal(result.frame, null);
  assert.ok(result.error!.includes("Unknown command"));
});

// ── New WP-04 commands ──

// x <command_id> → command.cancel
test("parseCommand: x <command_id> → command.cancel", () => {
  const result = parseCommand("x c-1", null);
  assert.deepEqual(result.frame, {
    type: "action",
    name: "command.cancel",
    data: { command_id: "c-1" },
  });
});

test("parseCommand: x without command_id → error", () => {
  const result = parseCommand("x", null);
  assert.equal(result.frame, null);
  assert.ok(result.error!.includes("Usage"));
});

// X [session_id] [--dry-run] → command.cancel_all
test("parseCommand: X (no args) → cancel all globally", () => {
  const result = parseCommand("X", null);
  assert.deepEqual(result.frame, {
    type: "action",
    name: "command.cancel_all",
    data: {},
  });
});

test("parseCommand: X <session_id> → cancel all for session", () => {
  const result = parseCommand("X s1", null);
  assert.deepEqual(result.frame, {
    type: "action",
    name: "command.cancel_all",
    data: { session_id: "s1" },
  });
});

test("parseCommand: X --dry-run → cancel all dry run", () => {
  const result = parseCommand("X --dry-run", null);
  assert.deepEqual(result.frame, {
    type: "action",
    name: "command.cancel_all",
    data: { dry_run: true },
  });
});

test("parseCommand: X s1 --dry-run → cancel all for session dry run", () => {
  const result = parseCommand("X s1 --dry-run", null);
  assert.deepEqual(result.frame, {
    type: "action",
    name: "command.cancel_all",
    data: { session_id: "s1", dry_run: true },
  });
});

test("parseCommand: X --dry-run s1 → session before flag", () => {
  const result = parseCommand("X --dry-run s1", null);
  assert.deepEqual(result.frame, {
    type: "action",
    name: "command.cancel_all",
    data: { session_id: "s1", dry_run: true },
  });
});

// k [session_id] [--dry-run] → session.cleanup
test("parseCommand: k (no args) → cleanup active session", () => {
  const result = parseCommand("k", null);
  assert.deepEqual(result.frame, {
    type: "action",
    name: "session.cleanup",
    data: {},
  });
});

test("parseCommand: k <session_id> → cleanup specific session", () => {
  const result = parseCommand("k s1", null);
  assert.deepEqual(result.frame, {
    type: "action",
    name: "session.cleanup",
    data: { session_id: "s1" },
  });
});

test("parseCommand: k --dry-run → cleanup dry run", () => {
  const result = parseCommand("k --dry-run", null);
  assert.deepEqual(result.frame, {
    type: "action",
    name: "session.cleanup",
    data: { dry_run: true },
  });
});

test("parseCommand: k s1 --dry-run → cleanup session dry run", () => {
  const result = parseCommand("k s1 --dry-run", null);
  assert.deepEqual(result.frame, {
    type: "action",
    name: "session.cleanup",
    data: { session_id: "s1", dry_run: true },
  });
});

// h [jsonThresholds] → healthcheck
test("parseCommand: h (no args) → healthcheck with empty thresholds", () => {
  const result = parseCommand("h", null);
  assert.deepEqual(result.frame, {
    type: "action",
    name: "healthcheck",
    data: {},
  });
});

test("parseCommand: h with thresholds JSON", () => {
  const result = parseCommand('h {"max_oldest_prompt_s":60}', null);
  assert.deepEqual(result.frame, {
    type: "action",
    name: "healthcheck",
    data: { max_oldest_prompt_s: 60 },
  });
});

test("parseCommand: h with multiple thresholds", () => {
  const result = parseCommand('h {"max_oldest_prompt_s":60,"max_stale_sessions":2}', null);
  assert.equal((result.frame! as { name: string }).name, "healthcheck");
  assert.equal((result.frame!.data as Record<string, unknown>).max_oldest_prompt_s, 60);
  assert.equal((result.frame!.data as Record<string, unknown>).max_stale_sessions, 2);
});

test("parseCommand: h with invalid JSON → error", () => {
  const result = parseCommand("h {bad", null);
  assert.equal(result.frame, null);
  assert.ok(result.error!.includes("Usage"));
});

// ── interactiveHelp ──

test("interactiveHelp returns non-empty string with all commands", () => {
  const help = interactiveHelp();
  assert.ok(help.length > 0);
  // Existing commands
  assert.ok(help.includes("session.cycle"));
  assert.ok(help.includes("focus session"));
  assert.ok(help.includes("prompt.answer"));
  assert.ok(help.includes("queue command"));
  // New WP-04 commands
  assert.ok(help.includes("cancel a single command"));
  assert.ok(help.includes("cancel all queued commands"));
  assert.ok(help.includes("cleanup session"));
  assert.ok(help.includes("healthcheck"));
  // Sync command
  assert.ok(help.includes("sync from backend"));
  // Short keys
  assert.ok(help.includes("x <command_id>"));
  assert.ok(help.includes("X [session_id]"));
  assert.ok(help.includes("k [session_id]"));
  assert.ok(help.includes("h [jsonThresholds]"));
  assert.ok(help.includes("u"));
});

// ── 'u' sync command ──

test("parseCommand: u → sync=true, no frame", () => {
  const result = parseCommand("u", null);
  assert.equal(result.frame, null);
  assert.equal(result.quit, false);
  assert.equal(result.error, undefined);
  assert.equal(result.sync, true);
});