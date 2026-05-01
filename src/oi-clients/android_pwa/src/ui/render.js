export function renderApp(root, state) {
  root.innerHTML = `
    <main class="app app--${state.status}">
      <div class="topbar"><span data-testid="connection" class="connection ${state.connected ? 'online' : 'offline'}"></span><span data-testid="state-label">${escapeHtml(state.label || state.status)}</span></div>
      <section class="face" aria-label="Oi character face"><div class="eye"></div><div class="eye"></div><div class="mouth"></div></section>
      <section class="transcript" data-testid="transcript">${escapeHtml(state.text || '')}</section>
      ${state.confirm ? renderConfirm(state.confirm) : ''}
      <nav class="controls">
        <button data-action="ptt" class="ptt">Hold to talk</button>
        <button data-action="mute">${state.muted ? 'Unmute' : 'Mute'}</button>
        <button data-action="debug">Debug</button>
      </nav>
      <aside data-testid="debug" class="debug ${state.debugOpen ? 'open' : ''}">${state.events.map((e) => `<p>${escapeHtml(e.summary)}</p>`).join('')}</aside>
    </main>`;
}

function renderConfirm(confirm) {
  return `<section class="confirm"><h2>${escapeHtml(confirm.title || 'Confirm')}</h2><p>${escapeHtml(confirm.body || '')}</p>${(confirm.options || []).map((option) => `<button data-action="confirm" data-confirm-id="${escapeHtml(option.id)}">${escapeHtml(option.label || option.id)}</button>`).join('')}</section>`;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[char]));
}
