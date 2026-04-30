"""Shared browser-side dashboard transport module."""

DASHBOARD_TRANSPORT_JS = r"""
function startDashboardTransport(store, view) {
    let esConnected = false;
    const es = new EventSource('/events');

    es.onopen = () => {
        esConnected = true;
        view.updateGatewayStatus(true, 'Connected to gateway');
        fetchGatewayHealth();
    };

    es.onmessage = (event) => {
        try {
            const message = JSON.parse(event.data);
            store.apply(message);
            view.render();
        } catch (error) {
            console.error('SSE parse error:', error);
        }
    };

    es.onerror = () => {
        esConnected = false;
        view.updateGatewayStatus(false, 'SSE disconnected (reconnecting...)');
        setTimeout(() => {
            if (!esConnected) {
                view.updateGatewayStatus(false, 'SSE disconnected - will retry automatically');
            }
        }, 5000);
    };

    async function fetchGatewayHealth() {
        try {
            const response = await fetch('/api/health');
            if (response.ok) {
                const data = await response.json();
                view.updateGatewayStatus(true, `Gateway OK — ${data.devices_online || 0} device(s) online`);
            } else {
                view.updateGatewayStatus(false, `Gateway error: ${response.status}`);
            }
        } catch {
            view.updateGatewayStatus(false, 'Gateway unreachable');
        }
    }

    setInterval(fetchGatewayHealth, 30000);
    fetchGatewayHealth();
}
""".strip()
