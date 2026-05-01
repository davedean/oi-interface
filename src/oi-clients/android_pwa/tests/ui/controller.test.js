import test from 'node:test';
import assert from 'node:assert/strict';
import { bindControls } from '../../src/ui/controller.js';

class FakeElement {
  constructor(dataset = {}) { this.dataset = dataset; this.listeners = {}; }
  addEventListener(type, handler) { this.listeners[type] = handler; }
  closest(selector) {
    if (selector === '[data-action]' && this.dataset.action) return this;
    if (selector === `[data-action="${this.dataset.action}"]`) return this;
    return null;
  }
}

class FakeRoot extends FakeElement {
  constructor() { super(); this.listenerLists = {}; }
  addEventListener(type, handler) { this.listenerLists[type] ||= []; this.listenerLists[type].push(handler); }
  fire(type, target) { return Promise.all((this.listenerLists[type] || []).map((handler) => handler({ target }))); }
}

test('bindControls wires delegated PTT, mute, debug and confirm actions', async () => {
  const root = new FakeRoot();
  const actions = [];
  const events = [];
  const recorder = { started: 0, stopped: 0, async start() { this.started += 1; }, async stop() { this.stopped += 1; } };
  const playback = { unlocked: false, async unlock() { this.unlocked = true; } };
  const client = { sendEvent: (...args) => events.push(args) };
  bindControls(root, { client, recorder, playback, dispatch: (action) => actions.push(action) });

  await root.fire('pointerdown', new FakeElement({ action: 'ptt' }));
  await root.fire('pointerup', new FakeElement({ action: 'ptt' }));
  await root.fire('click', new FakeElement({ action: 'mute' }));
  await root.fire('click', new FakeElement({ action: 'debug' }));
  await root.fire('click', new FakeElement({ action: 'confirm', confirmId: 'yes' }));

  assert.equal(playback.unlocked, true);
  assert.equal(recorder.started, 1);
  assert.equal(recorder.stopped, 1);
  assert.deepEqual(actions.map((a) => a.type), ['ptt.start', 'ptt.stop', 'mute.toggle', 'debug.toggle', 'confirm.clear']);
  assert.deepEqual(events, [['input.mute.toggle'], ['button.pressed', { button: 'yes', role: 'confirm' }], ['ui.confirm', { id: 'yes' }]]);
});

test('PTT stops even when pointerup happens away from the button', async () => {
  const root = new FakeRoot();
  const actions = [];
  const recorder = { stopped: 0, async start() {}, async stop() { this.stopped += 1; } };
  bindControls(root, { client: { sendEvent() {} }, recorder, playback: { async unlock() {} }, dispatch: (action) => actions.push(action) });
  await root.fire('pointerdown', new FakeElement({ action: 'ptt' }));
  await root.fire('pointerup', new FakeElement());
  await root.fire('pointerup', new FakeElement());
  assert.equal(recorder.stopped, 1);
  assert.deepEqual(actions.map((a) => a.type), ['ptt.start', 'ptt.stop']);
});

test('pointercancel also stops active PTT recording', async () => {
  const root = new FakeRoot();
  const recorder = { stopped: 0, async start() {}, async stop() { this.stopped += 1; } };
  bindControls(root, { client: { sendEvent() {} }, recorder, playback: { async unlock() {} }, dispatch() {} });
  await root.fire('pointerdown', new FakeElement({ action: 'ptt' }));
  await root.fire('pointercancel', new FakeElement());
  assert.equal(recorder.stopped, 1);
});

test('bindControls is idempotent across re-renders', async () => {
  const root = new FakeRoot();
  const events = [];
  const controls = { client: { sendEvent: (...args) => events.push(args) }, recorder: {}, playback: {}, dispatch() {} };
  bindControls(root, controls);
  bindControls(root, controls);
  await root.fire('click', new FakeElement({ action: 'mute' }));
  assert.equal(root.listenerLists.click.length, 1);
  assert.deepEqual(events, [['input.mute.toggle']]);
});

test('click ignores non-action targets', async () => {
  const root = new FakeRoot();
  const actions = [];
  bindControls(root, { client: { sendEvent() {} }, recorder: {}, playback: {}, dispatch: (action) => actions.push(action) });
  await root.fire('click', new FakeElement());
  assert.deepEqual(actions, []);
});
