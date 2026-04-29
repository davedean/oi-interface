import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

// Inventory-driven set-coverage tests for the mock-device side.
//
// These tests mirror tests/test_pi_rpc_inventory.py for the TS client. Until
// Step 2 of PI_RPC_FULL_PARITY_PLAN.md lands, the imports below resolve to
// stubs (or throw) and these tests fail with the missing items listed.
//
// Modules expected (Track B — mock-device):
//   mock-device/src/pi_rpc_commands.ts  -> COMMAND_BUILDERS: Record<string, (...args: any[]) => object>
//   mock-device/src/pi_rpc_events.ts    -> EVENT_PROJECTIONS: Record<string, (state: any, msg: any) => any>
//   mock-device/src/pi_rpc_protocol.ts  -> UI_METHOD_HANDLERS: Record<string, (...args: any[]) => any>

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, "..", "..", "..");
const INVENTORY_PATH = resolve(REPO_ROOT, "docs", "pi_rpc_protocol_inventory.json");

type Inventory = {
  commands: Array<{ name: string; slice: string }>;
  events: Array<{ name: string }>;
  ui_methods: {
    dialog: Array<{ name: string }>;
    fire_and_forget: Array<{ name: string }>;
  };
};

function loadInventory(): Inventory {
  return JSON.parse(readFileSync(INVENTORY_PATH, "utf-8"));
}

function expectedCommands(inv: Inventory): Set<string> {
  return new Set(inv.commands.map((c) => c.name));
}

function expectedEvents(inv: Inventory): Set<string> {
  return new Set(inv.events.map((e) => e.name));
}

function expectedUiMethods(inv: Inventory): Set<string> {
  return new Set([
    ...inv.ui_methods.dialog.map((m) => m.name),
    ...inv.ui_methods.fire_and_forget.map((m) => m.name),
  ]);
}

async function tryLoadRegistry(
  modulePath: string,
  exportName: string,
): Promise<{ registry: Record<string, unknown> | null; error: string | null }> {
  try {
    const mod = await import(modulePath);
    const reg = mod[exportName];
    if (reg === undefined) {
      return {
        registry: null,
        error: `module ${modulePath} loaded but export '${exportName}' is missing`,
      };
    }
    if (typeof reg !== "object" || reg === null) {
      return {
        registry: null,
        error: `${modulePath}.${exportName} is ${typeof reg}, expected object`,
      };
    }
    return { registry: reg as Record<string, unknown>, error: null };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return { registry: null, error: `module ${modulePath} not importable yet: ${msg}` };
  }
}

function diffSets(actual: Set<string>, expected: Set<string>): { missing: string[]; extra: string[] } {
  const missing: string[] = [];
  const extra: string[] = [];
  for (const name of expected) if (!actual.has(name)) missing.push(name);
  for (const name of actual) if (!expected.has(name)) extra.push(name);
  missing.sort();
  extra.sort();
  return { missing, extra };
}

// ── Coverage tests ────────────────────────────────────────────────────────────

test("inventory: command builders match inventory", async () => {
  const inv = loadInventory();
  const expected = expectedCommands(inv);
  const { registry, error } = await tryLoadRegistry(
    "../../src/pi_rpc_commands.ts",
    "COMMAND_BUILDERS",
  );
  if (error) {
    assert.fail(
      `Command coverage gate cannot evaluate: ${error}\n` +
        `Expected commands: ${[...expected].sort().join(", ")}`,
    );
    return;
  }
  const actual = new Set(Object.keys(registry!));
  const { missing, extra } = diffSets(actual, expected);
  if (missing.length || extra.length) {
    assert.fail(
      `Command builder set does not match inventory.\n` +
        (missing.length ? `  missing (${missing.length}): ${JSON.stringify(missing)}\n` : "") +
        (extra.length ? `  extra (${extra.length}): ${JSON.stringify(extra)}` : ""),
    );
  }
});

test("inventory: event projections match inventory", async () => {
  const inv = loadInventory();
  const expected = expectedEvents(inv);
  const { registry, error } = await tryLoadRegistry(
    "../../src/pi_rpc_events.ts",
    "EVENT_PROJECTIONS",
  );
  if (error) {
    assert.fail(
      `Event coverage gate cannot evaluate: ${error}\n` +
        `Expected events: ${[...expected].sort().join(", ")}`,
    );
    return;
  }
  const actual = new Set(Object.keys(registry!));
  const { missing, extra } = diffSets(actual, expected);
  if (missing.length || extra.length) {
    assert.fail(
      `Event projection set does not match inventory.\n` +
        (missing.length ? `  missing (${missing.length}): ${JSON.stringify(missing)}\n` : "") +
        (extra.length ? `  extra (${extra.length}): ${JSON.stringify(extra)}` : ""),
    );
  }
});

test("inventory: UI method handlers match inventory", async () => {
  const inv = loadInventory();
  const expected = expectedUiMethods(inv);
  const { registry, error } = await tryLoadRegistry(
    "../../src/pi_rpc_protocol.ts",
    "UI_METHOD_HANDLERS",
  );
  if (error) {
    assert.fail(
      `UI method coverage gate cannot evaluate: ${error}\n` +
        `Expected UI methods: ${[...expected].sort().join(", ")}`,
    );
    return;
  }
  const actual = new Set(Object.keys(registry!));
  const { missing, extra } = diffSets(actual, expected);
  if (missing.length || extra.length) {
    assert.fail(
      `UI method handler set does not match inventory.\n` +
        (missing.length ? `  missing (${missing.length}): ${JSON.stringify(missing)}\n` : "") +
        (extra.length ? `  extra (${extra.length}): ${JSON.stringify(extra)}` : ""),
    );
  }
});

// ── Casing trap (passes immediately; guards against later normalization) ─────

test("inventory: camelCase setters are not normalized", () => {
  const names = expectedUiMethods(loadInventory());
  for (const camel of ["setStatus", "setWidget", "setTitle"]) {
    assert.ok(names.has(camel), `${camel} must remain camelCase`);
  }
});

test("inventory: set_editor_text remains snake_case", () => {
  const names = expectedUiMethods(loadInventory());
  assert.ok(names.has("set_editor_text"), "set_editor_text must remain snake_case");
});
