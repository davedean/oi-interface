#!/usr/bin/env -S npx tsx
/**
 * fake_pi_rpc.ts — Fake peer that mimics `pi --mode rpc` via JSONL scenarios.
 *
 * Usage: npx tsx tests/harness/fake_pi_rpc.ts <scenario.jsonl>
 *
 * Reads JSONL scenario from file. Speaks JSONL over stdout; reads JSONL from stdin.
 * Each line: expect, emit, comment, or sleep_ms.
 * <echo> in emit lines is replaced with the most recent id from an expect line.
 * Mismatch on expect → print diff to stderr, exit 2.
 * Timeout on expect (5s) → print "timeout waiting for..." to stderr, exit 3.
 * After last line → exit 0.
 */

import { readFileSync, createReadStream } from "node:fs";
import * as readline from "node:readline";

type Step = {
  expect?: Record<string, unknown>;
  emit?: Record<string, unknown>;
  comment?: string;
  sleep_ms?: number;
};

let capturedId: string | null = null;
let stepIndex = 0;
let lines: Step[] = [];

function loadScenario(path: string): Step[] {
  return readFileSync(path, "utf8")
    .split("\n")
    .filter((l) => l.trim() && !l.trim().startsWith("//"))
    .map((l) => JSON.parse(l));
}

function substituteEcho(
  obj: Record<string, unknown> | undefined,
  id: string | null
): Record<string, unknown> {
  if (!obj) return {};
  const result: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(obj)) {
    if (v === "<echo>") {
      result[k] = id;
    } else if (typeof v === "object" && v !== null && !Array.isArray(v)) {
      result[k] = substituteEcho(v as Record<string, unknown>, id);
    } else {
      result[k] = v;
    }
  }
  return result;
}

function deepMatch(actual: unknown, expected: unknown): boolean {
  if (typeof expected === "string" && expected === "<echo>") return true; // wildcard
  if (actual === null || expected === null) return actual === expected;
  if (typeof actual !== "object" || typeof expected !== "object") {
    return actual === expected;
  }
  const ak = Object.keys(actual as object);
  const ek = Object.keys(expected as object);
  if (ak.length !== ek.length) return false;
  for (const k of ek) {
    if (
      !(k in (actual as object)) ||
      !deepMatch(
        (actual as Record<string, unknown>)[k],
        (expected as Record<string, unknown>)[k]
      )
    )
      return false;
  }
  return true;
}

function sleep(ms: number) {
  return new Promise<void>((r) => setTimeout(r, ms));
}

async function waitForInput(
  rl: readline.Interface,
  timeoutMs: number
): Promise<string | null> {
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(null), timeoutMs);
    const onLine = (line: string) => {
      clearTimeout(timer);
      rl.off("line", onLine);
      resolve(line);
    };
    rl.on("line", onLine);
    rl.once("close", () => {
      clearTimeout(timer);
      resolve(null);
    });
  });
}

async function main() {
  const scenarioPath = process.argv[2];
  if (!scenarioPath) {
    console.error("Usage: fake_pi_rpc.ts <scenario.jsonl>");
    process.exit(1);
  }

  lines = loadScenario(scenarioPath);

  const rl = readline.createInterface({ input: process.stdin });

  // Process all steps
  while (stepIndex < lines.length) {
    const step = lines[stepIndex];
    stepIndex++;

    if ("comment" in step) {
      // Just a comment, skip
      continue;
    }

    if ("sleep_ms" in step && !("expect" in step) && !("emit" in step)) {
      if (step.sleep_ms) await sleep(step.sleep_ms);
      continue;
    }

    if ("emit" in step && !("expect" in step)) {
      const payload = substituteEcho(step.emit, capturedId);
      console.log(JSON.stringify(payload));
      // sleep_ms can co-occur with emit
      if (step.sleep_ms) await sleep(step.sleep_ms);
      continue;
    }

    if ("expect" in step) {
      // Wait for input from client
      const raw = await waitForInput(rl, 5000);
      if (raw === null) {
        console.error(
          `fake_pi_rpc: timeout waiting for: ${JSON.stringify(step.expect)}`
        );
        process.exit(3);
      }

      const input = raw.trim();
      if (!input) {
        // empty line — continue to next iteration (we haven't processed expect yet)
        stepIndex--;
        continue;
      }

      let msg: Record<string, unknown>;
      try {
        msg = JSON.parse(input);
      } catch {
        console.error("fake_pi_rpc: could not parse input as JSON:", input);
        process.exit(2);
      }

      const expected = step.expect; // <echo> in expect is a wildcard handled by deepMatch
      if (!deepMatch(msg, expected)) {
        console.error("fake_pi_rpc: MISMATCH");
        console.error("Expected:", JSON.stringify(expected, null, 2));
        console.error("Got:", JSON.stringify(msg, null, 2));
        process.exit(2);
      }

      // Capture id for future echo substitution
      if (typeof msg.id === "string") capturedId = msg.id;
      continue;
    }
  }

  // All steps processed successfully
  process.exit(0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
