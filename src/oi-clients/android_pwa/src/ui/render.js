export function renderApp(root, state) {
  root.innerHTML = `
    <main class="app app--${state.status}">
      ${renderTopbar(state)}
      ${renderFace()}
      ${renderTranscript(state)}
      ${state.confirm ? renderConfirm(state.confirm) : ''}
      ${renderControls(state)}
      ${renderDebug(state)}
    </main>`;
}

function renderTopbar(state) {
  const connectionClass = state.connected ? 'online' : 'offline';
  const label = escapeHtml(state.label || state.status);
  return `
    <div class="topbar">
      <span data-testid="connection" class="connection ${connectionClass}"></span>
      <span data-testid="state-label">${label}</span>
    </div>`;
}

function renderFace() {
  return `
    <section class="face" aria-label="Oi character face">
      <div class="eye"></div><div class="eye"></div><div class="mouth"></div>
    </section>`;
}

function renderTranscript(state) {
  return `<section class="transcript" data-testid="transcript">${escapeHtml(state.text || '')}</section>`;
}

function renderControls(state) {
  return `
    <nav class="controls">
      <button data-action="ptt" class="ptt">Hold to talk</button>
      <button data-action="mute">${state.muted ? 'Unmute' : 'Mute'}</button>
      <button data-action="debug">Debug</button>
    </nav>`;
}

function renderDebug(state) {
  const className = state.debugOpen ? 'debug open' : 'debug';
  const events = state.events.map((event) => `<p>${escapeHtml(event.summary)}</p>`).join('');
  return `<aside data-testid="debug" class="${className}">${events}</aside>`;
}

function renderConfirm(confirm) {
  const options = (confirm.options || []).map(renderConfirmOption).join('');
  return `
    <section class="confirm">
      <h2>${escapeHtml(confirm.title || 'Confirm')}</h2>
      <p>${escapeHtml(confirm.body || '')}</p>
      ${options}
    </section>`;
}

function renderConfirmOption(option) {
  const id = escapeHtml(option.id);
  const label = escapeHtml(option.label || option.id);
  return `<button data-action="confirm" data-confirm-id="${id}">${label}</button>`;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[char]));
}
