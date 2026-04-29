import type { ReducerFrame } from "./types.ts";

/** Parsed result of a single interactive command line. */
export interface ParsedCommand {
  /** null if the input is empty or unrecognised */
  frame: ReducerFrame | null;
  /** If the command should exit the interactive loop */
  quit: boolean;
  /** If non-empty, an error/usage message to display */
  error?: string;
  /** If true, request a sync-from-server snapshot refresh */
  sync?: boolean;
}

/**
 * Parse an interactive command line into a ReducerFrame (or quit/error).
 * Pure function — no I/O, no side-effects.
 */
export function parseCommand(
  input: string,
  activeSessionId: string | null,
): ParsedCommand {
  const trimmed = input.trim();
  if (!trimmed) return { frame: null, quit: false };

  const parts = trimmed.split(/\s+/);
  const cmd = parts[0];

  if (cmd === "q") return { frame: null, quit: true };
  if (cmd === "?") return { frame: null, quit: false, error: interactiveHelp() };

  switch (cmd) {
    case "n":
      return {
        frame: { type: "action", name: "session.cycle", data: { direction: "next" } },
        quit: false,
      };
    case "p":
      return {
        frame: { type: "action", name: "session.cycle", data: { direction: "prev" } },
        quit: false,
      };
    case "f": {
      const sessionId = parts[1];
      if (!sessionId) return { frame: null, quit: false, error: "Usage: f <session_id>" };
      return {
        frame: { type: "action", name: "session.focus", data: { session_id: sessionId } },
        quit: false,
      };
    }
    case "m":
      return { frame: { type: "snapshot", data: { view: "command_menu" } }, quit: false };
    case "a": {
      const promptId = parts[1];
      const value = parts.slice(2).join(" ");
      if (!promptId || !value) return { frame: null, quit: false, error: "Usage: a <prompt_id> <value>" };
      return {
        frame: { type: "action", name: "prompt.answer", data: { prompt_id: promptId, value } },
        quit: false,
      };
    }
    case "c": {
      const verb = parts[1];
      if (!verb) return { frame: null, quit: false, error: "Usage: c <verb> [jsonArgs]" };
      let args: Record<string, unknown> = {};
      if (parts[2]) {
        try {
          args = JSON.parse(parts.slice(2).join(" "));
        } catch {
          // If not valid JSON, treat as verb-only
        }
      }
      return {
        frame: {
          type: "action",
          name: "command.queue",
          data: { verb, ...args, session_id: args.session_id ?? activeSessionId ?? undefined },
        },
        quit: false,
      };
    }
    // --- New WP-04 commands ---
    case "x": {
      const commandId = parts[1];
      if (!commandId) return { frame: null, quit: false, error: "Usage: x <command_id>" };
      return {
        frame: { type: "action", name: "command.cancel", data: { command_id: commandId } },
        quit: false,
      };
    }
    case "X": {
      // cancel_all [session_id] [--dry-run]
      let sessionId: string | undefined;
      let dryRun = false;
      for (let i = 1; i < parts.length; i++) {
        if (parts[i] === "--dry-run") dryRun = true;
        else if (!sessionId) sessionId = parts[i];
      }
      return {
        frame: {
          type: "action",
          name: "command.cancel_all",
          data: { ...(sessionId ? { session_id: sessionId } : {}), ...(dryRun ? { dry_run: true } : {}) },
        },
        quit: false,
      };
    }
    case "k": {
      // cleanup [session_id] [--dry-run]
      let sessionId: string | undefined;
      let dryRun = false;
      for (let i = 1; i < parts.length; i++) {
        if (parts[i] === "--dry-run") dryRun = true;
        else if (!sessionId) sessionId = parts[i];
      }
      return {
        frame: {
          type: "action",
          name: "session.cleanup",
          data: { ...(sessionId ? { session_id: sessionId } : {}), ...(dryRun ? { dry_run: true } : {}) },
        },
        quit: false,
      };
    }
    case "h": {
      // healthcheck [jsonThresholds]
      let thresholds: Record<string, unknown> = {};
      if (parts[1]) {
        try {
          thresholds = JSON.parse(parts.slice(1).join(" "));
        } catch {
          return { frame: null, quit: false, error: "Usage: h [jsonThresholds]  e.g. h {\"max_oldest_prompt_s\":60}" };
        }
      }
      return {
        frame: { type: "action", name: "healthcheck", data: thresholds },
        quit: false,
      };
    }
    case "u":
      return { frame: null, quit: false, sync: true };
    default:
      return { frame: null, quit: false, error: `Unknown command: ${cmd}. Type ? for help.` };
  }
}

/** Return the interactive help text. */
export function interactiveHelp(): string {
  return `
Interactive controls:
  n              next session (session.cycle next)
  p              previous session (session.cycle prev)
  f <id>         focus session
  m              toggle command menu view
  a <pid> <val>  prompt.answer
  c <verb> [json] queue command for active session
  x <command_id> cancel a single command
  X [session_id] [--dry-run]  cancel all queued commands
  k [session_id] [--dry-run]  cleanup session (cancel prompts + commands)
  h [jsonThresholds]          healthcheck
  u              sync from backend (Pi RPC when --pi-rpc is enabled)
  q              quit
  ?              show this help
`;
}