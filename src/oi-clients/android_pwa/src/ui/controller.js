export function bindControls(root, { client, recorder, playback, dispatch }) {
  root.__oiControls = { client, recorder, playback, dispatch, pttActive: root.__oiControls?.pttActive || false };
  if (root.__oiControlsBound) return;
  root.__oiControlsBound = true;

  root.addEventListener('pointerdown', async (event) => {
    if (!event.target.closest?.('[data-action="ptt"]')) return;
    const controls = root.__oiControls;
    controls.pttActive = true;
    controls.playback?.unlock?.().catch?.(() => {});
    controls.dispatch({ type: 'ptt.start' });
    await controls.recorder.start();
  });

  const stopPtt = async () => {
    const controls = root.__oiControls;
    if (!controls.pttActive) return;
    controls.pttActive = false;
    controls.dispatch({ type: 'ptt.stop' });
    await controls.recorder.stop();
  };

  root.addEventListener('pointerup', stopPtt);
  root.addEventListener('pointercancel', stopPtt);
  root.addEventListener('pointerleave', stopPtt);

  root.addEventListener('click', (event) => {
    const controls = root.__oiControls;
    const target = event.target.closest?.('[data-action]');
    const action = target?.dataset?.action;
    if (action === 'mute') {
      controls.dispatch({ type: 'mute.toggle' });
      controls.client.sendEvent('input.mute.toggle');
      return;
    }
    if (action === 'debug') {
      controls.dispatch({ type: 'debug.toggle' });
      return;
    }
    if (action === 'confirm') {
      controls.client.sendEvent('button.pressed', { button: target.dataset.confirmId, role: 'confirm' });
      controls.client.sendEvent('ui.confirm', { id: target.dataset.confirmId });
      controls.dispatch({ type: 'confirm.clear' });
    }
  });
}
