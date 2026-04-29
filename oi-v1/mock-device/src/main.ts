import { readFileSync } from "node:fs";
import * as readline from "node:readline";
import { initialState, reducer } from "./reducer.ts";
import { parseCommand, interactiveHelp } from "./interactive.ts";
import { replayFile, replayJsonl } from "./replay.ts";
import { renderState } from "./render.ts";
import { spawnRpcClient, type RpcClient, type RpcInbound } from "./pi_rpc.ts";
import {
  applyRpcCommandStatusUpdate,
  rpcInboundToEffect,
} from "./pi_rpc_protocol.ts";
import {
  LOCAL_ONLY_VERBS,
  mapActionToRpcCommand,
  mapPromptAnswerToRpcCommand,
} from "./pi_rpc_commands.ts";
import type { FrontendState, ReducerFrame } from "./types.ts";

function extractArg(args: string[], flag: string): string | null {
  const idx = args.indexOf(flag);
  if (idx < 0) return null;
  return args[idx + 1] ?? null;
}

function printHelp(): void {
  console.log(`OI mock-device scaffold

Usage:
  npx tsx mock-device/src/main.ts
  npx tsx mock-device/src/main.ts --interactive [--fixture tests/fixtures/pi-events/X.jsonl]
  npx tsx mock-device/src/main.ts --interactive --pi-rpc [--pi-rpc-cmd "pi --mode rpc --no-session"]
  npx tsx mock-device/src/main.ts --fixture tests/fixtures/pi-events/no-sessions.jsonl
  cat tests/fixtures/pi-events/no-sessions.jsonl | npx tsx mock-device/src/main.ts --stdin

Flags:
  --pi-rpc                 Enable Pi RPC mode (spawns a subprocess for state/actions)
  --pi-rpc-cmd <command>  Command to spawn in Pi RPC mode (default: pi --mode rpc --no-session)

Without --pi-rpc, interactive mode runs in pure local/reducer mode.`);
}

function printInteractiveHelp(): void {
  console.log(interactiveHelp());
}

async function readStdin(): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of process.stdin) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  }
  return Buffer.concat(chunks).toString("utf8");
}

async function interactiveLoop(initial: FrontendState): Promise<void> {
  let state = initial;

  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  });

  console.log("OI mock-device interactive mode (local reducer)");
  console.log("Type ? for help, q to quit.\n");
  console.log(renderState(state));

  const prompt = (): void => {
    rl.setPrompt("> ");
    rl.prompt();
  };

  prompt();

  for await (const line of rl) {
    const result = parseCommand(line, state.sessions.active_session_id);

    if (result.quit) {
      console.log("Bye.");
      rl.close();
      return;
    }

    if (result.error) {
      console.log(result.error);
      prompt();
      continue;
    }

    if (result.sync) {
      console.log("No backend connected in local mode. Start with --pi-rpc for live sync.");
      prompt();
      continue;
    }

    const frame = result.frame;
    if (!frame) {
      prompt();
      continue;
    }

    // Special: 'm' toggles between command_menu and idle
    if (frame.type === "snapshot" && (frame.data as Record<string, unknown>).view === "command_menu") {
      frame.data = { view: state.view === "command_menu" ? "idle" : "command_menu" };
    }

    state = reducer(state, frame);

    console.clear();
    console.log(renderState(state));

    prompt();
  }
}

async function main(): Promise<number> {
  const args = process.argv.slice(2);
  if (args.includes("--help") || args.includes("-h")) {
    printHelp();
    return 0;
  }

  if (args.includes("--oi-server") || args.includes("--oi-token")) {
    console.error("--oi-server/--oi-token have been removed from mock-device.");
    console.error("Use --pi-rpc [--pi-rpc-cmd \"pi --mode rpc --no-session\"] for live backend mode.");
    return 2;
  }

  // Pi RPC mode takes priority (can be combined with --interactive implicitly)
  const piRpc = args.includes("--pi-rpc");
  const piRpcCmd = extractArg(args, "--pi-rpc-cmd") ?? "pi --mode rpc --no-session";
  if (piRpc) {
    return await piRpcMain(piRpcCmd);
  }

  // Interactive mode
  if (args.includes("--interactive")) {
    let state = initialState();
    const fixtureIndex = args.indexOf("--fixture");
    if (fixtureIndex >= 0) {
      const fixturePath = args[fixtureIndex + 1];
      if (!fixturePath) {
        console.error("--fixture requires a JSONL path");
        return 2;
      }
      const result = replayFile(fixturePath);
      state = result.state;
    }

    await interactiveLoop(state);
    return 0;
  }

  const fixtureIndex = args.indexOf("--fixture");
  if (fixtureIndex >= 0) {
    const fixturePath = args[fixtureIndex + 1];
    if (!fixturePath) {
      console.error("--fixture requires a JSONL path");
      return 2;
    }
    const result = replayFile(fixturePath);
    console.log(JSON.stringify(result.state, null, 2));
    return 0;
  }

  if (args.includes("--stdin")) {
    const result = replayJsonl(await readStdin(), "<stdin>");
    console.log(JSON.stringify(result.state, null, 2));
    return 0;
  }

  const replayIndex = args.indexOf("--replay");
  if (replayIndex >= 0) {
    const fixturePath = args[replayIndex + 1];
    if (!fixturePath) {
      console.error("--replay requires a JSONL path");
      return 2;
    }
    const content = readFileSync(fixturePath, "utf8");
    const result = replayJsonl(content, fixturePath);
    console.log(JSON.stringify(result.state, null, 2));
    return 0;
  }

  // Legacy --rpc flag (now superseded by --pi-rpc)
  const rpcIndex = args.indexOf("--rpc");
  if (rpcIndex >= 0) {
    const command = args[rpcIndex + 1] ?? "<missing>";
    console.error(`--rpc is deprecated; use --pi-rpc and --pi-rpc-cmd instead`);
    console.error(`Requested command: ${command}`);
    console.log(JSON.stringify(initialState(), null, 2));
    return 0;
  }

  printHelp();
  console.log(JSON.stringify(initialState(), null, 2));
  return 0;
}

// ── Pi RPC integration ───────────────────────────────────────────────────────

/** Mapping of prompt_id → extension_prompt_id for pending extension prompts. */
const pendingExtensionIds = new Map<string, string>();

/**
 * Interactive mode backed by a Pi RPC subprocess.
 *
 * - On startup: spawn the RPC process, send `get_state`, seed reducer snapshot.
 * - During interaction: route supported command.queue verbs as RPC commands,
 *   handle incoming extension_ui_request messages as prompts, and send
 *   extension_ui_response for prompt.answer when applicable.
 * - Verb `speak` stays local (no RPC mapping) with an informative last_action_result.
 */
async function piRpcMain(rpcCommand: string): Promise<number> {
  let state = initialState();
  let client: RpcClient;

  try {
    const parts = rpcCommand.split(" ");
    client = spawnRpcClient({
      command: parts[0],
      args: parts.slice(1),
    });
  } catch (err) {
    console.error(`Failed to spawn Pi RPC process: ${(err as Error).message}`);
    console.error(`Command: ${rpcCommand}`);
    console.error("Ensure 'pi' is available on PATH or specify --pi-rpc-cmd.");
    return 1;
  }

  // Send get_state to seed initial snapshot
  client.send({ type: "get_state" });

  // Read initial state from RPC (process get_state response)
  const initialStateTimeout = setTimeout(() => {
    console.error("Warning: no response to get_state within 10s; continuing with local state.");
  }, 10_000);

  try {
    // Wait briefly for the first message (get_state response)
    for await (const msg of client.messages()) {
      const effect = rpcInboundToEffect(msg);
      if (effect.kind === "snapshot") {
        state = reducer(state, effect.frame);
        console.log("Pi RPC: received initial state.");
      } else if (effect.kind === "error") {
        console.error(`Pi RPC error: ${effect.message}`);
      }
      break; // Only process first message for initialisation
    }
  } catch (_err) {
    // Process may have exited; continue with local state
  }
  clearTimeout(initialStateTimeout);

  // Interactive loop
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });

  console.log("OI mock-device interactive mode (Pi RPC)");
  console.log(`RPC command: ${rpcCommand}`);
  console.log("Type ? for help, q to quit.\n");
  console.log(renderState(state));

  const prompt_ = (): void => { rl.setPrompt("> "); rl.prompt(); };
  prompt_();

  const renderAndPrompt = (): void => {
    console.clear();
    console.log(renderState(state));
    prompt_();
  };

  const applyFrameAndRender = (frame: ReducerFrame): void => {
    state = reducer(state, frame);
    renderAndPrompt();
  };

  // Background: poll for incoming RPC messages and apply them
  const incomingLoop = async (): Promise<void> => {
    try {
      for await (const msg of client.messages()) {
        handleIncomingMessage(msg);
      }
    } catch {
      // Stream ended
    }
  };
  const incomingPromise = incomingLoop();

  function handleIncomingMessage(msg: RpcInbound): void {
    const effect = rpcInboundToEffect(msg);
    if (effect.kind === "prompt") {
      if (effect.extension_prompt_id) {
        pendingExtensionIds.set(effect.prompt_id, effect.extension_prompt_id);
      }
      applyFrameAndRender(effect.frame);
    } else if (effect.kind === "snapshot") {
      applyFrameAndRender(effect.frame);
    } else if (effect.kind === "command_status") {
      state = applyRpcCommandStatusUpdate(state, {
        command_id: effect.command_id,
        status: effect.status,
      });
      renderAndPrompt();
    } else if (effect.kind === "error") {
      console.error(`Pi RPC error: ${effect.message}`);
    }
  }

  // Main interactive readline loop
  for await (const line of rl) {
    const result = parseCommand(line, state.sessions.active_session_id);

    if (result.quit) {
      console.log("Bye.");
      rl.close();
      await client.close();
      return 0;
    }

    if (result.error) {
      console.log(result.error);
      prompt_();
      continue;
    }

    // Sync from RPC: re-send get_state
    if (result.sync) {
      client.send({ type: "get_state" });
      console.log("Requested state refresh from Pi RPC.");
      prompt_();
      continue;
    }

    const frame = result.frame;
    if (!frame) {
      prompt_();
      continue;
    }

    // Handle prompt.answer: route extension_ui_response if applicable
    if (frame.type === "action" && frame.name === "prompt.answer") {
      const rpcCmd = mapPromptAnswerToRpcCommand(frame.data ?? {}, pendingExtensionIds);
      if (rpcCmd) {
        client.send(rpcCmd);
        // Remove from pending map after sending
        const promptId = String(frame.data?.prompt_id ?? "");
        if (promptId.length > 0) pendingExtensionIds.delete(promptId);
      }
    }

    // For command.queue actions in RPC mode:
    if (frame.type === "action" && frame.name === "command.queue") {
      const data = frame.data ?? {};
      const verb = String(data.verb ?? "");

      const rpcCmd = mapActionToRpcCommand(data, state.sessions.active_session_id);

      if (rpcCmd) {
        // Send to RPC process and also apply locally for responsiveness.
        client.send(rpcCmd);
        applyFrameAndRender(frame);
        continue;
      }

      if (LOCAL_ONLY_VERBS.has(verb)) {
        // speak: local-only, inform the user
        state = reducer(state, frame);
        state = {
          ...state,
          last_action_result: {
            ok: true,
            code: "local_only",
            message: `verb '${verb}' is local-only in Pi RPC mode; not sent to RPC`,
          },
        };
        renderAndPrompt();
        continue;
      }

      // Unknown verb: apply locally with info message
      state = reducer(state, frame);
      state = {
        ...state,
        last_action_result: {
          ok: false,
          code: "unsupported_rpc_verb",
          message: `verb '${verb}' is not supported in Pi RPC mode`,
        },
      };
      renderAndPrompt();
      continue;
    }

    applyFrameAndRender(frame);
  }

  await client.close();
  return 0;
}

main().then((code) => process.exit(code)).catch((error) => {
  console.error((error as Error).message);
  process.exit(1);
});