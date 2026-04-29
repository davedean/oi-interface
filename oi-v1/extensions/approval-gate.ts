import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

const GUARDED_TOOLS = new Set(["bash", "write", "edit"]);

function hintFor(toolName: string, input: any): string {
  if (toolName === "bash") return String(input?.command || "").slice(0, 180);
  if (toolName === "write") {
    const path = input?.path || "?";
    const size = String(input?.content || "").length;
    return `write ${path} (${size}b)`;
  }
  if (toolName === "edit") {
    const path = input?.path || "?";
    return `edit ${path}`;
  }
  return `${toolName}`;
}

export default function approvalGate(pi: ExtensionAPI) {
  pi.on("tool_call", async (event, ctx) => {
    if (!GUARDED_TOOLS.has(event.toolName)) return;

    const hint = hintFor(event.toolName, event.input);
    const choice = await ctx.ui.select(
      `Approve ${event.toolName}?\n${hint}`,
      ["Approve", "Deny"],
    );

    if (choice !== "Approve") {
      return { block: true, reason: `Denied ${event.toolName} via approval gate` };
    }

    return;
  });
}
