import test from 'node:test';
import assert from 'node:assert/strict';
import { DatpClient } from '../../src/datp/client.js';
import { buildEnvelope } from '../../src/datp/envelope.js';

class FakeWebSocket extends EventTarget {
  static OPEN = 1;
  static instances = [];
  constructor(url) { super(); this.url = url; this.readyState = 0; this.sent = []; FakeWebSocket.instances.push(this); }
  open() { this.readyState = FakeWebSocket.OPEN; this.dispatchEvent(new Event('open')); }
  receive(message) { this.dispatchEvent(new MessageEvent('message', { data: typeof message === 'string' ? message : JSON.stringify(message) })); }
  send(data) { this.sent.push(JSON.parse(data)); }
  close() { this.readyState = 3; this.dispatchEvent(new Event('close')); }
}

const timers = () => {
  const calls = [];
  return { calls, setInterval(fn, ms) { calls.push(['interval', ms, fn]); return fn; }, clearInterval() {}, setTimeout(fn, ms) { calls.push(['timeout', ms, fn]); return fn; }, clearTimeout() {} };
};

test('client sends hello, accepts hello_ack, flushes queue and heartbeats', () => {
  FakeWebSocket.instances = [];
  const t = timers();
  const client = new DatpClient({ url: 'ws://gateway/datp', WebSocketImpl: FakeWebSocket, timers: t, heartbeatMs: 10 });
  const events = [];
  client.addEventListener('connected', () => events.push('connected'));
  client.sendEvent('queued.before.connect');
  client.connect();
  const ws = FakeWebSocket.instances[0];
  ws.open();
  assert.equal(ws.sent[0].type, 'hello');
  ws.receive(buildEnvelope({ type: 'hello_ack', deviceId: client.deviceId, payload: { session_id: 's' } }));
  assert.equal(client.connected, true);
  assert.equal(events[0], 'connected');
  assert.equal(ws.sent[1].payload.event, 'queued.before.connect');
  client.sendState('RECORDING');
  t.calls.find((call) => call[0] === 'interval')[2]();
  assert.equal(ws.sent.at(-2).payload.event, 'heartbeat');
  assert.equal(ws.sent.at(-1).type, 'state');
  assert.equal(ws.sent.at(-1).payload.mode, 'RECORDING');
  assert.equal(ws.sent.at(-1).payload.heartbeat, true);
});

test('repeated hello_ack replaces heartbeat timer instead of stacking intervals', () => {
  FakeWebSocket.instances = [];
  const t = timers();
  let cleared = 0;
  t.clearInterval = () => { cleared += 1; };
  const client = new DatpClient({ url: 'ws://x', WebSocketImpl: FakeWebSocket, timers: t, heartbeatMs: 10 });
  client.connect();
  const ws = FakeWebSocket.instances[0];
  ws.open();
  ws.receive(buildEnvelope({ type: 'hello_ack', deviceId: client.deviceId, payload: { session_id: 's1' } }));
  ws.receive(buildEnvelope({ type: 'hello_ack', deviceId: client.deviceId, payload: { session_id: 's1' } }));
  assert.equal(t.calls.filter((call) => call[0] === 'interval').length, 2);
  assert.equal(cleared, 1);
});

test('client emits command and ACKs only when handler requests it', () => {
  FakeWebSocket.instances = [];
  const client = new DatpClient({ url: 'ws://x', WebSocketImpl: FakeWebSocket, heartbeatMs: 0 });
  let command;
  client.addEventListener('command', (event) => { command = event.detail.message; event.detail.ack(true); });
  client.connect();
  const ws = FakeWebSocket.instances[0];
  ws.open();
  ws.receive(buildEnvelope({ type: 'hello_ack', deviceId: client.deviceId, payload: {} }));
  ws.receive(buildEnvelope({ type: 'command', id: 'cmd_1', deviceId: client.deviceId, payload: { op: 'audio.stop', args: {} } }));
  assert.equal(command.id, 'cmd_1');
  assert.equal(ws.sent.at(-1).type, 'ack');
  assert.equal(ws.sent.at(-1).payload.command_id, 'cmd_1');
});

test('client reports protocol errors and schedules reconnect on close', () => {
  FakeWebSocket.instances = [];
  const t = timers();
  const client = new DatpClient({ url: 'ws://x', WebSocketImpl: FakeWebSocket, timers: t });
  const errors = [];
  client.addEventListener('protocol.error', (event) => errors.push(event.detail.error));
  client.connect();
  const ws = FakeWebSocket.instances[0];
  ws.receive('{bad');
  assert.match(errors[0], /JSON/);
  ws.open();
  ws.receive(buildEnvelope({ type: 'hello_ack', deviceId: client.deviceId, payload: {} }));
  ws.close();
  assert.equal(client.connected, false);
  assert.equal(t.calls.some((call) => call[0] === 'timeout'), true);
});

test('manual close does not reconnect', () => {
  FakeWebSocket.instances = [];
  const t = timers();
  const client = new DatpClient({ url: 'ws://x', WebSocketImpl: FakeWebSocket, timers: t });
  client.connect();
  client.close();
  assert.equal(t.calls.some((call) => call[0] === 'timeout'), false);
});
