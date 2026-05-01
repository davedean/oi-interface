import { AudioCache } from './audio/cache.js';
import { AudioPlayback } from './audio/playback.js';
import { PttRecorder } from './audio/recorder.js';
import { DatpClient } from './datp/client.js';
import { actionsForCommand } from './state/map-command.js';
import { createInitialState, reduceState } from './state/model.js';
import { bindControls } from './ui/controller.js';
import { renderApp } from './ui/render.js';

const params = new URLSearchParams(location.search);
const wsUrl = params.get('ws') || `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.hostname}:8787/datp`;
const root = document.getElementById('app');
const client = new DatpClient({ url: wsUrl });
const cache = new AudioCache();
const playback = new AudioPlayback();
const recorder = new PttRecorder({ client });
let state = createInitialState();

function dispatch(action) {
  state = reduceState(state, action);
  renderApp(root, state);
  bindControls(root, { client, recorder, playback, dispatch });
}

client.addEventListener('connected', () => dispatch({ type: 'connection.online' }));
client.addEventListener('disconnected', () => dispatch({ type: 'connection.offline' }));
client.addEventListener('gateway.error', (event) => dispatch({ type: 'error', error: event.detail.message?.payload?.message || 'Gateway error' }));
client.addEventListener('command', async (event) => {
  const { message, ack } = event.detail;
  const { op, args = {} } = message.payload || {};
  try {
    if (op === 'audio.cache.put_begin') cache.begin(args);
    if (op === 'audio.cache.put_chunk') cache.putChunk(args);
    if (op === 'audio.cache.put_end') cache.end(args);
    if (op === 'audio.play') await playback.play(cache.get(args.response_id || 'latest'));
    if (op === 'audio.stop') playback.stop();
    for (const action of actionsForCommand(message)) dispatch(action);
    ack(true);
  } catch (error) {
    dispatch({ type: 'error', error: error.message });
    ack(false);
  }
});

if ('serviceWorker' in navigator) navigator.serviceWorker.register('./sw.js').catch(() => {});
dispatch({ type: 'connection.offline' });
client.connect();
