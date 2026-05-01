import test from 'node:test';
import assert from 'node:assert/strict';
import { UI_STATES, createInitialState, reduceState, setStatus } from '../../src/state/model.js';

test('all required states are accepted', () => {
  let state = createInitialState();
  for (const status of UI_STATES) {
    state = setStatus(state, status);
    assert.equal(state.status, status);
  }
});

test('reducer covers connection, PTT, text, mute, confirm and error flows', () => {
  let state = createInitialState();
  state = reduceState(state, { type: 'connection.online' });
  assert.equal(state.status, 'idle');
  state = reduceState(state, { type: 'ptt.start' });
  assert.equal(state.status, 'listening');
  state = reduceState(state, { type: 'ptt.stop' });
  assert.equal(state.status, 'uploading');
  state = reduceState(state, { type: 'text.delta', text: 'hel' });
  state = reduceState(state, { type: 'text.delta', text: 'lo' });
  assert.equal(state.text, 'hello');
  state = reduceState(state, { type: 'text.final', text: 'final' });
  assert.equal(state.status, 'response_cached');
  state = reduceState(state, { type: 'mute.toggle' });
  assert.equal(state.status, 'muted');
  state = reduceState(state, { type: 'confirm.show', title: 'OK?', options: [{ id: 'yes' }] });
  assert.equal(state.status, 'confirm');
  state = reduceState(state, { type: 'confirm.clear' });
  assert.equal(state.confirm, null);
  state = reduceState(state, { type: 'error', error: 'bad' });
  assert.equal(state.status, 'error');
  assert.equal(state.error, 'bad');
  assert.ok(state.events.length >= 8);
});

test('unknown states are rejected and unknown actions are no-ops', () => {
  const state = createInitialState();
  assert.throws(() => setStatus(state, 'bogus'), /Unknown/);
  assert.equal(reduceState(state, { type: 'missing' }), state);
});
