"""Shared browser-side store wrapper for dashboard state reduction."""

DASHBOARD_STORE_JS = r"""
function createDashboardStore(initialState) {
    let state = initialState || { devices: {}, transcripts: [], transcript_limit: 100 };

    return {
        getState() {
            return state;
        },
        apply(message) {
            state = reduceEvent(state, message);
            return state;
        },
    };
}
""".strip()
