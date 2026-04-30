"""Shared browser-side dashboard view module."""

DASHBOARD_VIEW_JS = r"""
function formatTime(iso) {
    if (!iso) return '';
    return new Date(iso).toLocaleTimeString();
}

function formatBytes(bytes) {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function getModeClass(mode) {
    if (!mode) return '';
    const normalized = mode.toLowerCase();
    if (normalized.includes('idle')) return 'idle';
    if (normalized.includes('listen')) return 'listening';
    if (normalized.includes('think')) return 'thinking';
    if (normalized.includes('speak') || normalized.includes('audio')) return 'speaking';
    return '';
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function createDashboardView(store) {
    const gatewayDot = document.getElementById('gateway-dot');
    const gatewayStatus = document.getElementById('gateway-status');
    const devicesList = document.getElementById('devices-list');
    const audioCache = document.getElementById('audio-cache');
    const transcriptsList = document.getElementById('transcripts-list');

    function renderStats() {
        const state = store.getState();
        const devices = Object.values(state.devices);
        const online = devices.filter(device => device.online).length;
        document.getElementById('stat-devices').textContent = devices.length;
        document.getElementById('stat-online').textContent = online;
        document.getElementById('stat-transcripts').textContent = state.transcripts.length;
    }

    function renderDevices() {
        const state = store.getState();
        const devices = Object.values(state.devices);
        if (devices.length === 0) {
            devicesList.innerHTML = '<div class="empty">No devices connected</div>';
            return;
        }

        devicesList.innerHTML = devices.map(device => {
            const mode = device.state?.mode || 'unknown';
            const modeClass = getModeClass(mode);
            const battery = device.state?.battery_percent;
            const rssi = device.state?.wifi_rssi;

            return `
                <div class="device">
                    <div class="status-dot ${device.online ? 'online' : 'offline'}"></div>
                    <div class="device-meta">
                        <div class="device-name">${escapeHtml(device.device_id || 'Unknown')}</div>
                        <div class="device-type">${escapeHtml(device.device_type || 'Unknown device')}</div>
                        <div class="state-info">
                            <span class="state-badge ${modeClass}">${escapeHtml(mode)}</span>
                            ${battery ? `<span class="state-badge">🔋 ${battery}%</span>` : ''}
                            ${rssi ? `<span class="state-badge">📶 ${rssi} dBm</span>` : ''}
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    }

    function renderAudioCache() {
        const state = store.getState();
        const devices = Object.values(state.devices);
        const withCache = devices.filter(device => device.audio_cache_bytes > 0);

        if (withCache.length === 0) {
            audioCache.innerHTML = '<div class="empty">No audio cached</div>';
            return;
        }

        audioCache.innerHTML = withCache.map(device => `
            <div class="audio-item">
                <span>${escapeHtml(device.device_id)}</span>
                <span class="state-badge">${formatBytes(device.audio_cache_bytes)}</span>
            </div>
        `).join('');
    }

    function renderTranscripts() {
        const state = store.getState();
        const transcripts = state.transcripts.slice(-10).reverse();
        if (transcripts.length === 0) {
            transcriptsList.innerHTML = '<div class="empty">No conversations yet</div>';
            return;
        }

        transcriptsList.innerHTML = transcripts.map(transcript => `
            <div class="transcript">
                <div class="transcript-time">${formatTime(transcript.timestamp)} — ${escapeHtml(transcript.device_id)}</div>
                <div class="transcript-text">👤 ${escapeHtml(transcript.transcript)}</div>
                ${transcript.response ? `<div class="response-text">🤖 ${escapeHtml(transcript.response)}</div>` : ''}
            </div>
        `).join('');
    }

    return {
        render() {
            renderStats();
            renderDevices();
            renderAudioCache();
            renderTranscripts();
        },
        updateGatewayStatus(connected, text) {
            gatewayDot.className = 'status-dot ' + (connected ? 'online' : 'offline');
            gatewayStatus.textContent = text;
        },
    };
}
""".strip()
