#!/bin/bash
# Gateway smoke test — spawns gateway with a fake pi process, then runs
# the test client to verify bidirectional JSONL flow.

cd "$(dirname "$0")/.."

PORT=19999

# Fake pi process: reads JSONL, responds to get_state and other commands
FAKE_PI='node -e "
const rl = require(\"readline\").createInterface({ input: process.stdin });
rl.on(\"line\", (line) => {
  try {
    const msg = JSON.parse(line);
    if (msg.type === \"get_state\") {
      console.log(JSON.stringify({
        type: \"response\",
        command: \"get_state\",
        success: true,
        data: { sessionId: \"test-1\", sessionName: \"test\", isStreaming: false }
      }));
    } else {
      console.log(JSON.stringify({ type: \"response\", command: msg.type, success: true }));
    }
  } catch (e) {
    console.error(\"parse error:\", e.message);
  }
});
"
'

echo "[test] Starting gateway on port $PORT..."
npx tsx scripts/pi-rpc-gateway.ts --port "$PORT" --pi-cmd "$FAKE_PI" &
GW_PID=$!

# Wait for gateway to bind
for i in {1..10}; do
  if nc -z localhost "$PORT" 2>/dev/null; then
    break
  fi
  sleep 0.5
done

echo "[test] Running client..."
npx tsx scripts/test-gateway-client.ts "$PORT"
RESULT=$?

echo "[test] Stopping gateway..."
kill $GW_PID 2>/dev/null
wait $GW_PID 2>/dev/null

if [ $RESULT -eq 0 ]; then
  echo "[test] PASS"
else
  echo "[test] FAIL"
fi
exit $RESULT
