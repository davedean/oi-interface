import type { FrontendState } from "./types.ts";

export function renderState(state: FrontendState): string {
  const lines: string[] = [];

  // Active session
  const active = state.sessions.active_session_id;
  const activeSession = state.sessions.list.find((s) => s.session_id === active);

  lines.push("═══════════════════════════════════════");
  lines.push(`View: ${state.view}`);
  if (activeSession) {
    const markers = [];
    if (activeSession.stale) markers.push("STALE");
    if (activeSession.pending_count > 0) markers.push(`${activeSession.pending_count} pending`);
    const markerStr = markers.length > 0 ? ` [${markers.join(", ")}]` : "";
    lines.push(`Active: ${activeSession.session_id} (${activeSession.name}) status=${activeSession.status}${markerStr}`);
  } else {
    lines.push("Active: none");
  }
  lines.push("───────────────────────────────────────");

  // Session list
  if (state.sessions.list.length > 0) {
    lines.push("Sessions:");
    for (const s of state.sessions.list) {
      const indicator = s.session_id === active ? "→" : " ";
      const staleMarker = s.stale ? " ⚠STALE" : "";
      const pending = s.pending_count > 0 ? ` (${s.pending_count} pending)` : "";
      const age = s.last_seen_age_s !== null ? ` age=${s.last_seen_age_s}s` : "";
      lines.push(`  ${indicator} ${s.session_id} ${s.name} [${s.status}]${staleMarker}${pending}${age}`);
    }
  } else {
    lines.push("Sessions: (none)");
  }

  // Current prompt
  lines.push("───────────────────────────────────────");
  if (state.prompt.pending) {
    lines.push(`Prompt: ${state.prompt.prompt_id}`);
    if (state.prompt.title) lines.push(`  Title: ${state.prompt.title}`);
    if (state.prompt.body) lines.push(`  Body: ${state.prompt.body}`);
    if (state.prompt.options.length > 0) {
      lines.push(`  Options: ${state.prompt.options.map((o) => `${o.label}=${o.value}`).join(", ")}`);
    }
  } else {
    lines.push("Prompt: (none)");
  }

  // Queued commands
  lines.push("───────────────────────────────────────");
  if (state.queued_commands.length > 0) {
    lines.push("Queued commands:");
    for (const c of state.queued_commands) {
      lines.push(`  ${c.command_id} ${c.verb} [${c.status}] session=${c.session_id}`);
    }
  } else {
    lines.push("Queued commands: (none)");
  }

  // Queue health
  const qh = state.queue_health;
  if (qh.oldest_pending_prompt_age_s !== null || qh.oldest_queued_command_age_s !== null) {
    lines.push("───────────────────────────────────────");
    lines.push("Queue health:");
    if (qh.oldest_pending_prompt_age_s !== null) lines.push(`  Oldest prompt: ${qh.oldest_pending_prompt_age_s}s`);
    if (qh.oldest_queued_command_age_s !== null) lines.push(`  Oldest command: ${qh.oldest_queued_command_age_s}s`);
  }

  // Last action result
  lines.push("───────────────────────────────────────");
  const r = state.last_action_result;
  const rMarker = r.ok ? "✓" : "✗";
  lines.push(`Last action: ${rMarker} ${r.code ?? ""} ${r.message ?? ""}`);

  lines.push("═══════════════════════════════════════");
  return lines.join("\n");
}
