import test from 'node:test';
import assert from 'node:assert/strict';
import { actionsForCommand, normalizeStatus } from '../../src/state/map-command.js';

const command = (op, args = {}) => ({ type: 'command', id: 'cmd', payload: { op, args } });

test('normalizes existing and required UI states', () => {
  assert.equal(normalizeStatus('READY'), 'idle');
  assert.equal(normalizeStatus('THINKING'), 'thinking');
  assert.equal(normalizeStatus('task_running'), 'task_running');
  assert.equal(normalizeStatus('blocked'), 'blocked');
  assert.equal(normalizeStatus('??'), 'error');
});

test('maps display commands to state/text/confirm actions', () => {
  assert.deepEqual(actionsForCommand(command('display.show_status', { state: 'THINKING', label: 'Hmm' }))[0], { type: 'state.set', status: 'thinking', label: 'Hmm' });
  assert.equal(actionsForCommand(command('display.show_progress', { text: 'Working' }))[0].status, 'task_running');
  assert.equal(actionsForCommand(command('display.show_progress', { text: 'No', kind: 'blocked' }))[0].status, 'blocked');
  assert.deepEqual(actionsForCommand(command('display.show_response_delta', { text_delta: 'a' }))[0], { type: 'text.delta', text: 'a' });
  assert.deepEqual(actionsForCommand(command('display.show_response_delta', { text_delta: 'done', is_final: true }))[0], { type: 'text.final', text: 'done' });
  assert.equal(actionsForCommand(command('display.show_card', { title: 'Confirm' }))[0].type, 'confirm.show');
});

test('maps audio and device commands', () => {
  assert.equal(actionsForCommand(command('audio.cache.put_begin', {}))[0].status, 'thinking');
  assert.equal(actionsForCommand(command('audio.cache.put_end', {}))[0].status, 'response_cached');
  assert.equal(actionsForCommand(command('audio.play', {}))[0].status, 'playing');
  assert.equal(actionsForCommand(command('audio.stop', {}))[0].status, 'idle');
  assert.equal(actionsForCommand(command('device.mute_until', {}))[0].status, 'muted');
  assert.deepEqual(actionsForCommand(command('unknown', {})), []);
});
