"""Shared browser-side dashboard application bootstrap."""

from .browser_reducer import DASHBOARD_REDUCER_JS
from .browser_store import DASHBOARD_STORE_JS
from .browser_transport import DASHBOARD_TRANSPORT_JS
from .browser_view import DASHBOARD_VIEW_JS

DASHBOARD_BROWSER_APP_JS = r"""
const store = createDashboardStore({ devices: {}, transcripts: [], transcript_limit: 100 });
const view = createDashboardView(store);
startDashboardTransport(store, view);
""".strip()

DASHBOARD_APP_JS = (
    f"{DASHBOARD_REDUCER_JS}\n\n"
    f"{DASHBOARD_STORE_JS}\n\n"
    f"{DASHBOARD_VIEW_JS}\n\n"
    f"{DASHBOARD_TRANSPORT_JS}\n\n"
    f"{DASHBOARD_BROWSER_APP_JS}"
)
