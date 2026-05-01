import test from 'node:test';
import assert from 'node:assert/strict';
import { renderApp } from '../../src/ui/render.js';
import { createInitialState } from '../../src/state/model.js';

test('renderApp renders required controls, state, transcript and debug events', () => {
  const root = { innerHTML: '' };
  renderApp(root, createInitialState({ connected: true, status: 'listening', label: 'Listening', text: '<hello>', debugOpen: true, events: [{ summary: 'evt' }] }));
  assert.match(root.innerHTML, /app--listening/);
  assert.match(root.innerHTML, /Hold to talk/);
  assert.match(root.innerHTML, /Mute/);
  assert.match(root.innerHTML, /Debug/);
  assert.match(root.innerHTML, /online/);
  assert.match(root.innerHTML, /&lt;hello&gt;/);
  assert.match(root.innerHTML, /evt/);
});

test('renderApp renders confirm cards with escaped labels', () => {
  const root = { innerHTML: '' };
  renderApp(root, createInitialState({ confirm: { title: 'Confirm <x>', body: 'Body', options: [{ id: 'yes', label: 'Yes' }] } }));
  assert.match(root.innerHTML, /Confirm &lt;x&gt;/);
  assert.match(root.innerHTML, /data-confirm-id="yes"/);
});
