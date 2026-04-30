"""Shared browser shell for the dashboard HTML and CSS."""

DASHBOARD_SHELL_CSS = r"""
* { box-sizing: border-box; }
body {
    font-family: system-ui, -apple-system, sans-serif;
    margin: 0;
    padding: 20px;
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    color: #eee;
    min-height: 100vh;
}
h1 {
    color: #00d4ff;
    margin-bottom: 24px;
    display: flex;
    align-items: center;
    gap: 12px;
}
.container {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
    max-width: 1400px;
    margin: 0 auto;
}
.card {
    background: rgba(22, 33, 62, 0.8);
    border: 1px solid rgba(0, 212, 255, 0.2);
    border-radius: 12px;
    padding: 20px;
    backdrop-filter: blur(10px);
}
.card h2 {
    color: #00d4ff;
    margin-top: 0;
    font-size: 1rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    display: flex;
    align-items: center;
    gap: 8px;
}
.status-bar {
    background: rgba(22, 33, 62, 0.8);
    border: 1px solid rgba(0, 212, 255, 0.2);
    border-radius: 12px;
    padding: 16px 24px;
    max-width: 1400px;
    margin: 0 auto 20px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 16px;
}
.status-indicator {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 0.95rem;
}
.status-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    animation: pulse 2s infinite;
}
.status-dot.online { background: #00ff88; box-shadow: 0 0 8px #00ff88; }
.status-dot.offline { background: #ff4757; animation: none; }
.status-dot.connecting { background: #ffa502; }
@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
}
.device {
    display: flex;
    align-items: flex-start;
    padding: 14px;
    margin: 10px 0;
    background: rgba(15, 52, 96, 0.6);
    border-radius: 8px;
    transition: all 0.2s ease;
}
.device:hover {
    background: rgba(15, 52, 96, 0.9);
    transform: translateX(4px);
}
.device-meta { flex: 1; }
.device-name {
    font-weight: 600;
    color: #fff;
    font-size: 1rem;
    display: flex;
    align-items: center;
    gap: 10px;
}
.device-type {
    color: #7f8c8d;
    font-size: 0.85em;
    margin-top: 4px;
}
.state-info {
    margin-top: 8px;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
}
.state-badge {
    display: inline-flex;
    align-items: center;
    padding: 4px 10px;
    border-radius: 20px;
    font-size: 0.75em;
    font-weight: 500;
    background: rgba(0, 212, 255, 0.15);
    color: #00d4ff;
}
.state-badge.idle { background: rgba(108, 117, 125, 0.2); color: #6c757d; }
.state-badge.listening { background: rgba(0, 255, 136, 0.2); color: #00ff88; }
.state-badge.thinking { background: rgba(255, 193, 7, 0.2); color: #ffc107; }
.state-badge.speaking { background: rgba(0, 212, 255, 0.2); color: #00d4ff; }
.transcript {
    padding: 14px;
    margin: 10px 0;
    background: rgba(15, 52, 96, 0.6);
    border-radius: 8px;
    border-left: 3px solid #00d4ff;
}
.transcript-time {
    color: #7f8c8d;
    font-size: 0.75em;
    margin-bottom: 6px;
}
.transcript-text {
    color: #fff;
    margin: 4px 0;
    line-height: 1.4;
}
.response-text {
    color: #00d4ff;
    font-size: 0.9em;
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid rgba(0, 212, 255, 0.2);
    line-height: 1.4;
}
.audio-item {
    padding: 10px;
    margin: 6px 0;
    background: rgba(15, 52, 96, 0.5);
    border-radius: 6px;
    display: flex;
    justify-content: space-between;
    align-items: center;
}
.empty {
    color: #7f8c8d;
    font-style: italic;
    text-align: center;
    padding: 30px;
}
.full-width { grid-column: 1 / -1; }
.stat-group {
    display: flex;
    gap: 24px;
    flex-wrap: wrap;
}
.stat { text-align: center; }
.stat-value {
    font-size: 1.5rem;
    font-weight: 700;
    color: #00d4ff;
}
.stat-label {
    font-size: 0.75rem;
    color: #7f8c8d;
    text-transform: uppercase;
}
@media (max-width: 900px) {
    .container { grid-template-columns: 1fr; }
    .full-width { grid-column: auto; }
}
""".strip()


def dashboard_shell_html() -> str:
    """Return the shared dashboard HTML shell."""
    return """<!DOCTYPE html>
<html>
<head>
    <title>Oi Dashboard</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="stylesheet" href="/dashboard-shell.css">
</head>
<body>
    <h1>
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect>
            <line x1="8" y1="21" x2="16" y2="21"></line>
            <line x1="12" y1="17" x2="12" y2="21"></line>
        </svg>
        Oi Dashboard
    </h1>

    <div class="status-bar">
        <div class="status-indicator">
            <div class="status-dot connecting" id="gateway-dot"></div>
            <span id="gateway-status">Connecting to gateway...</span>
        </div>
        <div class="stat-group">
            <div class="stat">
                <div class="stat-value" id="stat-devices">0</div>
                <div class="stat-label">Devices</div>
            </div>
            <div class="stat">
                <div class="stat-value" id="stat-online">0</div>
                <div class="stat-label">Online</div>
            </div>
            <div class="stat">
                <div class="stat-value" id="stat-transcripts">0</div>
                <div class="stat-label">Transcripts</div>
            </div>
        </div>
    </div>

    <div class="container">
        <div class="card">
            <h2>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="5" y="2" width="14" height="20" rx="2" ry="2"></rect>
                    <line x1="12" y1="18" x2="12.01" y2="18"></line>
                </svg>
                Connected Devices
            </h2>
            <div id="devices-list"><div class="empty">No devices connected</div></div>
        </div>

        <div class="card">
            <h2>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M9 18V5l12-2v13"></path>
                    <circle cx="6" cy="18" r="3"></circle>
                    <circle cx="18" cy="16" r="3"></circle>
                </svg>
                Audio Cache
            </h2>
            <div id="audio-cache"><div class="empty">No audio cached</div></div>
        </div>

        <div class="card full-width">
            <h2>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
                </svg>
                Recent Conversations
            </h2>
            <div id="transcripts-list"><div class="empty">No conversations yet</div></div>
        </div>
    </div>

    <script src="/dashboard-app.js"></script>
</body>
</html>"""
