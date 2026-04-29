#!/usr/bin/env node
/**
 * pi-rpc-gateway — TCP gateway that pipes JSONL between a TCP client and
 * a `pi --mode rpc` subprocess.
 *
 * Design: one TCP connection = one dedicated Pi RPC subprocess.
 * The gateway is stateless; it does not interpret JSONL messages.
 *
 * Usage:
 *   npx tsx scripts/pi-rpc-gateway.ts [--port 8843] [--pi-cmd "pi"] [--pi-args "--mode rpc --no-session"]
 *   npx tsx scripts/pi-rpc-gateway.ts --approval-gate [extensions/approval-gate.ts]
 *
 * The device/firmware connects via plain TCP, sends JSON lines (e.g.
 * {"type":"get_state"}), and receives JSON lines from Pi RPC stdout.
 */

import { spawn, type ChildProcess } from "node:child_process";
import { createServer, type Socket } from "node:net";

interface GatewayConfig {
  port: number;
  piCmd: string;
  piArgs: string[];
  approvalGate?: string | null;
}

function parseArgs(argv: string[]): GatewayConfig {
  let port = 8843;
  let piCmd = "pi";
  let piArgs: string[] = ["--mode", "rpc", "--no-session"];
  let approvalGate: string | null = null;

  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--port" && i + 1 < argv.length) {
      port = parseInt(argv[i + 1], 10);
      i++;
    } else if (argv[i] === "--pi-cmd" && i + 1 < argv.length) {
      piCmd = argv[i + 1];
      i++;
    } else if (argv[i] === "--pi-args" && i + 1 < argv.length) {
      piArgs = argv[i + 1].split(/\s+/).filter(Boolean);
      i++;
    } else if (argv[i] === "--approval-gate") {
      if (i + 1 < argv.length && !argv[i + 1].startsWith("--")) {
        approvalGate = argv[i + 1];
        i++;
      } else {
        approvalGate = "extensions/approval-gate.ts";
      }
    }
  }

  if (approvalGate && !piArgs.includes("--extension")) {
    piArgs = [...piArgs, "--extension", approvalGate];
  }

  return { port, piCmd, piArgs, approvalGate };
}

function log(...args: unknown[]): void {
  const ts = new Date().toISOString();
  console.error(`[${ts}]`, ...args);
}

function spawnPiRpc(piCmd: string, piArgs: string[]): ChildProcess {
  const shellRequired = piCmd.includes(" ");
  const child = spawn(piCmd, piArgs, {
    shell: shellRequired,
    stdio: ["pipe", "pipe", "pipe"],
  });
  return child;
}

function pipeSocketToPi(socket: Socket, pi: ChildProcess, clientId: string): void {
  let socketOpen = true;
  let piOpen = true;

  function cleanup(reason: string): void {
    if (!socketOpen && !piOpen) return;
    log(`[${clientId}] cleanup: ${reason}`);
    socketOpen = false;
    piOpen = false;
    try { socket.destroy(); } catch { /* ignore */ }
    try { pi.kill("SIGTERM"); } catch { /* ignore */ }
    // Force-kill after 3s if still alive
    setTimeout(() => {
      try { pi.kill("SIGKILL"); } catch { /* ignore */ }
    }, 3000);
  }

  socket.on("data", (chunk: Buffer) => {
    if (!piOpen) return;
    try {
      pi.stdin!.write(chunk);
    } catch (e) {
      log(`[${clientId}] write to pi stdin failed:`, e);
      cleanup("stdin write error");
    }
  });

  socket.on("end", () => {
    cleanup("socket end");
  });

  socket.on("error", (err) => {
    log(`[${clientId}] socket error:`, err.message);
    cleanup("socket error");
  });

  pi.stdout!.on("data", (chunk: Buffer) => {
    if (!socketOpen) return;
    try {
      socket.write(chunk);
    } catch (e) {
      log(`[${clientId}] write to socket failed:`, e);
      cleanup("socket write error");
    }
  });

  pi.stderr!.on("data", (chunk: Buffer) => {
    const lines = chunk.toString("utf8").trimEnd().split("\n");
    for (const line of lines) {
      if (line.trim()) {
        log(`[${clientId}] pi stderr:`, line.trim());
      }
    }
  });

  pi.on("exit", (code) => {
    log(`[${clientId}] pi exited with code ${code}`);
    cleanup("pi exit");
  });

  pi.on("error", (err) => {
    log(`[${clientId}] pi process error:`, err.message);
    cleanup("pi error");
  });
}

function main(): void {
  const config = parseArgs(process.argv.slice(2));
  log("Gateway config:", config);

  let connectionCount = 0;

  const server = createServer((socket) => {
    connectionCount++;
    const clientId = `conn-${connectionCount}`;
    const remote = `${socket.remoteAddress}:${socket.remotePort}`;
    log(`[${clientId}] connected from ${remote}`);

    const pi = spawnPiRpc(config.piCmd, config.piArgs);
    log(`[${clientId}] spawned Pi RPC: ${config.piCmd} ${config.piArgs.join(" ")}`);

    pipeSocketToPi(socket, pi, clientId);
  });

  server.on("error", (err) => {
    log("Server error:", err.message);
    process.exit(1);
  });

  server.listen(config.port, () => {
    log(`Gateway listening on TCP port ${config.port}`);
    log(`Waiting for connections...`);
  });

  function shutdown(): void {
    log("Shutting down...");
    server.close(() => {
      process.exit(0);
    });
  }

  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
}

main();
