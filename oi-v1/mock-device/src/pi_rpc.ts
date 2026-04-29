/**
 * Pi RPC transport adapter — spawn-based JSONL client for `pi --mode rpc --no-session`.
 *
 * This module provides transport and raw JSONL dispatch. Pure protocol shape
 * helpers live in `pi_rpc_protocol.ts`, command builders in
 * `pi_rpc_commands.ts`, and event projections in `pi_rpc_events.ts`.
 */

import { spawn } from "node:child_process";

export {
  mapGetStateToSnapshot,
  mapExtensionUiRequest,
  rpcInboundToEffect,
  applyRpcCommandStatusUpdate,
  type ExtensionUiPrompt,
  type RpcInboundEffect,
} from "./pi_rpc_protocol.ts";
export {
  COMMAND_BUILDERS,
  LOCAL_ONLY_VERBS,
  RPC_SUPPORTED_VERBS,
  buildRpcCommand,
  mapActionToRpcCommand,
  mapPromptAnswerToRpcCommand,
} from "./pi_rpc_commands.ts";
export { EVENT_PROJECTIONS } from "./pi_rpc_events.ts";

// ── JSONL line parser ───────────────────────────────────────────────────────

export interface ParsedLine {
  line: string;
  byteOffsetStart: number;
  byteOffsetEnd: number;
}

/**
 * Strict JSONL parser that handles partial chunks arriving from stdout.
 * LF-based line splitting; trailing \n on the final line is optional.
 * CRLF is normalised to LF before splitting.
 */
export function parseJsonlChunks(chunks: string[], buffer = ""): { lines: ParsedLine[]; remaining: string } {
  const combined = buffer + chunks.join("");
  // Normalise CRLF → LF
  const normalised = combined.replace(/\r\n/g, "\n");
  const lines: ParsedLine[] = [];

  let byteOffset = 0;
  let remaining = "";

  const parts = normalised.split("\n");
  for (let i = 0; i < parts.length; i++) {
    const part = parts[i];
    const isLast = i === parts.length - 1;
    if (isLast) {
      // Last segment after split: if original ended with \n this is empty,
      // otherwise it's an incomplete line that needs buffering
      remaining = part;
    } else {
      if (part.length > 0) {
        lines.push({
          line: part,
          byteOffsetStart: byteOffset,
          byteOffsetEnd: byteOffset + part.length,
        });
      }
      byteOffset += part.length + 1; // +1 for the \n
    }
  }

  return { lines, remaining };
}

/**
 * Parse a complete JSONL string (no chunk boundary concerns) into an
 * array of parsed objects. Throws on invalid JSON lines (excluding blanks/comments).
 */
export function parseJsonlSync(content: string): unknown[] {
  const { lines } = parseJsonlChunks([content]);
  const results: unknown[] = [];
  for (const { line } of lines) {
    if (line.startsWith("#")) continue;
    results.push(JSON.parse(line));
  }
  return results;
}

// ── RPC message types ────────────────────────────────────────────────────────

/** A message received from the Pi RPC process (stdout line). */
export interface RpcInbound {
  type: string;
  [key: string]: unknown;
}

/** A command sent to the Pi RPC process (stdin line). */
export interface RpcCommand {
  type: string;
  [key: string]: unknown;
}

// ── RPC client ──────────────────────────────────────────────────────────────

export interface RpcClientConfig {
  command: string;
  args?: string[];
  env?: Record<string, string>;
}

export interface RpcClient {
  /** Send a command to the child process stdin. */
  send(cmd: RpcCommand): void;
  /** Async iterable that yields inbound messages. Ends when the process exits. */
  messages(): AsyncIterable<RpcInbound> & { [Symbol.asyncIterator](): AsyncIterator<RpcInbound> };
  /** Shut down the child process. */
  close(): Promise<void>;
  /** Whether the client is alive (process running). */
  alive: boolean;
}

/**
 * Spawn a Pi RPC subprocess and return a client for sending commands
 * and receiving JSONL messages.
 *
 * Each outbound message is serialised as a single JSON line + \n to stdin.
 * Each inbound message is parsed from stdout (LF-delimited JSONL).
 */
export function spawnRpcClient(config: RpcClientConfig): RpcClient {
  const cmd = config.command;
  const args = config.args ?? [];
  const shellRequired = cmd.includes(" ");

  const child = spawn(cmd, args, {
    shell: shellRequired,
    env: { ...process.env, ...config.env },
    stdio: ["pipe", "pipe", "pipe"],
  });

  let buffer = "";
  let resolveMsg: ((msg: RpcInbound) => void) | null = null;
  const msgQueue: RpcInbound[] = [];
  let done = false;
  let resolveDone: (() => void) | null = null;
  const donePromise = new Promise<void>((resolve) => { resolveDone = resolve; });

  function flushQueue(): void {
    while (resolveMsg && msgQueue.length > 0) {
      const r = resolveMsg;
      resolveMsg = null;
      r(msgQueue.shift()!);
    }
    if (done && resolveMsg) {
      const r = resolveMsg;
      resolveMsg = null;
      // End the iterator by resolving with undefined — but our AsyncIterable
      // contract uses a sentinel, so let's just not resolve; the iterator
      // will break when `done` is true in `messages()`.
    }
  }

  child.stdout.on("data", (chunk: Buffer) => {
    const text = chunk.toString("utf8");
    const { lines, remaining } = parseJsonlChunks([text], buffer);
    buffer = remaining;
    for (const { line } of lines) {
      let parsed: RpcInbound;
      try {
        parsed = JSON.parse(line);
      } catch {
        // Skip malformed lines silently
        continue;
      }
      msgQueue.push(parsed);
    }
    flushQueue();
  });

  child.stderr.on("data", (_chunk: Buffer) => {
    // Drain stderr to prevent backpressure; logged by caller if needed
  });

  child.on("close", () => {
    done = true;
    flushQueue();
    if (resolveDone) resolveDone();
  });

  child.on("error", (_err) => {
    done = true;
    flushQueue();
    if (resolveDone) resolveDone();
  });

  return {
    alive: !done,

    send(cmd: RpcCommand): void {
      const line = JSON.stringify(cmd) + "\n";
      child.stdin.write(line);
    },

    async *messages(): AsyncIterable<RpcInbound> {
      while (true) {
        if (msgQueue.length > 0) {
          yield msgQueue.shift()!;
          continue;
        }
        if (done) return;
        // Wait for next message or process exit
        const msg = await new Promise<RpcInbound | null>((resolve) => {
          resolveMsg = resolve as (msg: RpcInbound) => void;
          if (done) {
            resolve(null);
          }
        });
        if (msg === null) return;
        yield msg;
      }
    },

    async close(): Promise<void> {
      if (!done) {
        try {
          child.stdin.end();
        } catch {
          // already closed
        }
        // Give process a moment to exit, then kill
        const timeout = setTimeout(() => {
          try { child.kill(); } catch { /* already dead */ }
        }, 3000);
        await donePromise;
        clearTimeout(timeout);
      }
    },
  };
}
