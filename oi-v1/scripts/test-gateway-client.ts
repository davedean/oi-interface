#!/usr/bin/env npx tsx
/**
 * Simple TCP client to smoke-test the Pi RPC gateway.
 * Sends get_state, waits for response, prints it, exits.
 */

import { connect } from "node:net";

const PORT = parseInt(process.argv[2] || "19999", 10);

const socket = connect(PORT, "localhost", () => {
  console.log("[client] connected");
  socket.write(JSON.stringify({ type: "get_state" }) + "\n");
});

let buffer = "";

socket.on("data", (chunk: Buffer) => {
  buffer += chunk.toString("utf8");
  const lines = buffer.split("\n");
  buffer = lines.pop() || "";
  for (const line of lines) {
    if (!line.trim()) continue;
    try {
      const msg = JSON.parse(line);
      console.log("[client] received:", JSON.stringify(msg, null, 2));
      if (msg.type === "response" && msg.command === "get_state") {
        console.log("[client] got expected response — exiting");
        socket.end();
        process.exit(0);
      }
    } catch (e) {
      console.error("[client] parse error:", line);
    }
  }
});

socket.on("error", (err) => {
  console.error("[client] socket error:", err.message);
  process.exit(1);
});

setTimeout(() => {
  console.error("[client] timeout waiting for response");
  process.exit(1);
}, 5000);
