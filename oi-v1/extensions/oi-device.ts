import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

const SERVER_URL = (process.env.OI_SERVER_URL || "http://127.0.0.1:8842").replace(/\/$/, "");
const SESSION_ID = process.env.OI_SESSION_ID || `pi-${process.pid}`;
const SESSION_NAME = process.env.OI_SESSION_NAME || SESSION_ID;
const POLL_MS = Number(process.env.OI_POLL_MS || "1000");
const APPROVE_TIMEOUT_MS = Number(process.env.OI_APPROVE_TIMEOUT_MS || "60000");
const APPROVE_TOOLS = new Set((process.env.OI_APPROVE_TOOLS || "bash,write,edit")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean));
const API_TOKEN = process.env.OI_API_TOKEN;
const AUTO_SPEAK = process.env.OI_AUTO_SPEAK !== "false";

type OiCommand = {
  command_id: string;
  seq: number;
  session_id: string;
  verb: string;
  args?: Record<string, unknown>;
};

function headers(extra: Record<string, string> = {}) {
  return API_TOKEN ? { ...extra, Authorization: `Bearer ${API_TOKEN}` } : extra;
}

async function oiGet(path: string) {
  const res = await fetch(`${SERVER_URL}${path}`, { headers: headers() });
  if (!res.ok) throw new Error(`GET ${path} -> ${res.status}`);
  return res.json() as Promise<any>;
}

async function oiPost(path: string, payload: unknown) {
  const res = await fetch(`${SERVER_URL}${path}`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`POST ${path} -> ${res.status}: ${await res.text()}`);
  return res.json() as Promise<any>;
}

function shortToolHint(toolName: string, input: any): string {
  if (toolName === "bash") return String(input?.command || "").slice(0, 150);
  if (toolName === "write") {
    const path = input?.path || input?.file_path || "?";
    const content = String(input?.content || "");
    return `write ${path} (${content.length}b)`.slice(0, 150);
  }
  if (toolName === "edit") return `edit ${input?.path || input?.file_path || "?"}`.slice(0, 150);
  return `${toolName}: ${JSON.stringify(input || {})}`.slice(0, 150);
}

async function upsertSession(ctx: any, status = "idle", summary?: string) {
  return oiPost("/oi/sessions/upsert", {
    session_id: SESSION_ID,
    name: SESSION_NAME,
    cwd: ctx.cwd,
    kind: "pi-extension",
    status,
    summary,
    model: ctx.model?.name || ctx.model?.id,
  });
}

async function waitForPromptAnswer(promptId: string, timeoutMs: number) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const data = await oiGet("/oi/answers");
    const hit = (data.answers || []).find((a: any) => a.prompt_id === promptId || a.id === promptId);
    if (hit) return hit.value;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  return undefined;
}

async function requestToolApproval(event: any, ctx: any) {
  if (!APPROVE_TOOLS.has(event.toolName)) return undefined;
  try {
    await upsertSession(ctx, "needs_approval", event.toolName);
    const prompt = (await oiPost("/oi/prompts", {
      session_id: SESSION_ID,
      tool_use_id: event.toolCallId,
      kind: "approval",
      title: `approve: ${event.toolName}`.slice(0, 15),
      body: shortToolHint(event.toolName, event.input),
      options: [
        { label: "approve", value: "approve" },
        { label: "notes", value: "notes" },
        { label: "deny", value: "deny" },
      ],
    })).prompt;
    const answer = await waitForPromptAnswer(prompt.prompt_id, APPROVE_TIMEOUT_MS);
    if (answer === "deny") return { block: true, reason: "Denied via oi device" };
    if (answer === "notes") return { block: true, reason: "oi requested notes" };
    return undefined; // approve, timeout, or unknown: fail open
  } catch (err) {
    ctx.ui?.notify?.(`oi approval unavailable: ${String(err).slice(0, 80)}`, "warn");
    return undefined;
  } finally {
    try { await upsertSession(ctx, ctx.isIdle?.() ? "idle" : "running"); } catch {}
  }
}

function messageFor(command: OiCommand) {
  const msg = command.args?.message;
  if (typeof msg !== "string" || !msg.trim()) throw new Error(`${command.verb} requires args.message`);
  return msg;
}

async function speakText(text: string, ctx: any) {
  try {
    await oiPost("/oi/speak", { text });
  } catch (err) {
    ctx.ui?.notify?.(`oi speak failed: ${String(err).slice(0, 80)}`, "warn");
  }
}

async function executeCommand(pi: ExtensionAPI, ctx: any, command: OiCommand, onVoicePrompt?: () => void) {
  switch (command.verb) {
    case "status":
      await upsertSession(ctx, ctx.isIdle?.() ? "idle" : "running", ctx.isIdle?.() ? "idle" : "running");
      return { ok: true, idle: ctx.isIdle?.(), pending: ctx.hasPendingMessages?.() };
    case "abort":
      await ctx.abort?.();
      await upsertSession(ctx, "idle", "aborted from oi");
      return { ok: true };
    case "steer":
      pi.sendUserMessage(messageFor(command), { deliverAs: "steer" });
      await upsertSession(ctx, "running", "steer from oi");
      return { ok: true };
    case "follow_up":
      pi.sendUserMessage(messageFor(command), { deliverAs: "followUp" });
      await upsertSession(ctx, "running", "follow-up from oi");
      return { ok: true };
    case "speak":
      await speakText(messageFor(command), ctx);
      return { ok: true };
    case "prompt":
      if (ctx.isIdle?.()) pi.sendUserMessage(messageFor(command));
      else pi.sendUserMessage(messageFor(command), { deliverAs: "followUp" });
      await upsertSession(ctx, "running", "prompt from oi");
      if (AUTO_SPEAK && command.args?.source === "voice") onVoicePrompt?.();
      return { ok: true };
    default:
      throw new Error(`unsupported command verb: ${command.verb}`);
  }
}

export default function oiDeviceExtension(pi: ExtensionAPI) {
  let timer: NodeJS.Timeout | undefined;
  let latestSeq = 0;
  let polling = false;
  let latestCtx: any;
  let pendingSpeakResponse = false;

  async function pollCommands(ctx: any) {
    if (polling) return;
    polling = true;
    try {
      const data = await oiGet(`/oi/commands?session_id=${encodeURIComponent(SESSION_ID)}&after_seq=${latestSeq}&status=queued`);
      for (const command of (data.commands || []) as OiCommand[]) {
        try {
          const result = await executeCommand(pi, ctx, command, () => { pendingSpeakResponse = true; });
          await oiPost(`/oi/commands/${command.command_id}/ack`, { result });
          latestSeq = Math.max(latestSeq, Number(command.seq || 0));
        } catch (err) {
          await oiPost(`/oi/commands/${command.command_id}/fail`, { error: String(err) });
          latestSeq = Math.max(latestSeq, Number(command.seq || 0));
        }
      }
    } catch (err) {
      // Keep quiet to avoid noisy UI when the oi server is down.
    } finally {
      polling = false;
    }
  }

  pi.on("session_start", async (_event, ctx) => {
    latestCtx = ctx;
    try {
      await upsertSession(ctx, ctx.isIdle?.() ? "idle" : "running", "oi device attached");
      ctx.ui.notify(`oi device attached: ${SESSION_NAME}`, "info");
    } catch (err) {
      ctx.ui.notify(`oi device unavailable: ${String(err).slice(0, 80)}`, "warn");
    }
    timer = setInterval(() => {
      if (latestCtx) void pollCommands(latestCtx);
    }, POLL_MS);
  });

  pi.on("session_shutdown", async (_event, ctx) => {
    if (timer) clearInterval(timer);
    timer = undefined;
    try { await upsertSession(ctx, "offline", "session shutdown"); } catch {}
  });

  pi.on("tool_call", async (event, ctx) => {
    latestCtx = ctx;
    return requestToolApproval(event, ctx);
  });

  pi.on("turn_start", async (_event, ctx) => {
    latestCtx = ctx;
    try { await upsertSession(ctx, "running"); } catch {}
  });

  pi.on("turn_end", async (event, ctx) => {
    latestCtx = ctx;
    try { await upsertSession(ctx, ctx.hasPendingMessages?.() ? "waiting" : "idle"); } catch {}
    if (pendingSpeakResponse) {
      pendingSpeakResponse = false;
      try {
        let paceHint: string | undefined;
        try {
          const state = await oiGet("/oi/state");
          paceHint = state?.device?.response_pace_hint;
        } catch {
          // Optional hint lookup only.
        }

        const msg = event.message as any;
        if (msg?.role === "assistant") {
          const text: string = (msg.content || [])
            .filter((b: any) => b.type === "text")
            .map((b: any) => b.text as string)
            .join(" ")
            .trim();
          if (text) await speakText(text, ctx);
        }

        if (paceHint === "possibly_delayed") {
          ctx.ui?.notify?.("oi: device audio muted/quiet; user response may be delayed", "info");
        }
      } catch (err) {
        ctx.ui?.notify?.(`oi auto-speak failed: ${String(err).slice(0, 80)}`, "warn");
      }
    }
  });
}
