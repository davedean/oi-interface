import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { initialState, reducer } from "./reducer.ts";
import type { FrontendState, ReducerFrame } from "./types.ts";

export interface ReplayStep {
  line: number;
  frame: ReducerFrame;
  state: FrontendState;
}

export interface ReplayResult {
  fixturePath: string;
  state: FrontendState;
  steps: ReplayStep[];
}

export function replayFile(fixturePath: string): ReplayResult {
  const absolutePath = resolve(fixturePath);
  const content = readFileSync(absolutePath, "utf8");
  return replayJsonl(content, absolutePath);
}

export function replayJsonl(content: string, fixturePath = "<inline>"): ReplayResult {
  let state = initialState();
  const steps: ReplayStep[] = [];

  content.split(/\r?\n/).forEach((line, index) => {
    const lineNumber = index + 1;
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) {
      return;
    }

    let frame: ReducerFrame;
    try {
      frame = JSON.parse(trimmed) as ReducerFrame;
    } catch (error) {
      throw new Error(`${fixturePath}:${lineNumber}: invalid JSON: ${(error as Error).message}`);
    }

    if (frame.type === "expect") {
      assertPartialMatch(state, frame.data, `${fixturePath}:${lineNumber}`);
    } else {
      state = reducer(state, frame);
    }
    steps.push({ line: lineNumber, frame, state });
  });

  return { fixturePath, state, steps };
}

export function assertPartialMatch(actual: unknown, expected: unknown, path = "state"): void {
  if (Array.isArray(expected)) {
    assert.equal(Array.isArray(actual), true, `${path}: expected array`);
    const actualArray = actual as unknown[];
    expected.forEach((item, index) => assertPartialMatch(actualArray[index], item, `${path}[${index}]`));
    return;
  }

  if (expected !== null && typeof expected === "object") {
    assert.equal(actual !== null && typeof actual === "object", true, `${path}: expected object`);
    const actualObject = actual as Record<string, unknown>;
    for (const [key, expectedValue] of Object.entries(expected as Record<string, unknown>)) {
      assertPartialMatch(actualObject[key], expectedValue, `${path}.${key}`);
    }
    return;
  }

  assert.deepEqual(actual, expected, path);
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const fixturePath = process.argv[2];
  if (!fixturePath) {
    console.error("usage: npx tsx mock-device/src/replay.ts tests/fixtures/pi-events/<fixture>.jsonl");
    process.exit(2);
  }

  try {
    const result = replayFile(fixturePath);
    console.log(JSON.stringify(result.state, null, 2));
  } catch (error) {
    console.error((error as Error).message);
    process.exit(1);
  }
}
