import test from 'node:test';
import assert from 'node:assert/strict';
import { DatpClient } from '../../src/datp/client.js';
import { buildEnvelope } from '../../src/datp/envelope.js';
import { actionsForCommand } from '../../src/state/map-command.js';
import { createInitialState, reduceState } from '../../src/state/model.js';

class FakeWebSocket extends EventTarget {
  static OPEN = 1; static instances = [];
  constructor() { super(); this.readyState = 0; this.sent = []; FakeWebSocket.instances.push(this); }
  open() { this.readyState = 1; this.dispatchEvent(new Event('open')); }
  receive(message) { this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(message) })); }
  send(data) { this.sent.push(JSON.parse(data)); }
  close() { this.readyState = 3; this.dispatchEvent(new Event('close')); }
}

test('scripted gateway session drives UI state and returns command ACKs', () => {
  FakeWebSocket.instances = [];
  const client = new DatpClient({ url: 'ws://gw/datp', WebSocketImpl: FakeWebSocket, heartbeatMs: 0 });
  let state = createInitialState();
  client.addEventListener('connected', () => { state = reduceState(state, { type: 'connection.online' }); });
  client.addEventListener('command', (event) => {
    for (const action of actionsForCommand(event.detail.message)) state = reduceState(state, action);
    event.detail.ack(true);
  });
  client.connect();
  const ws = FakeWebSocket.instances[0];
  ws.open();
  ws.receive(buildEnvelope({ type: 'hello_ack', deviceId: client.deviceId, payload: { session_id: 'abc' } }));
  ws.receive(buildEnvelope({ type: 'command', id: 'cmd_status', deviceId: client.deviceId, payload: { op: 'display.show_status', args: { state: 'THINKING', label: 'Thinking' } } }));
  ws.receive(buildEnvelope({ type: 'command', id: 'cmd_text', deviceId: client.deviceId, payload: { op: 'display.show_response_delta', args: { text_delta: 'Done', is_final: true } } }));
  assert.equal(state.connected, true);
  assert.equal(state.status, 'response_cached');
  assert.equal(state.text, 'Done');
  assert.deepEqual(ws.sent.filter((m) => m.type === 'ack').map((m) => m.payload.command_id), ['cmd_status', 'cmd_text']);
});
