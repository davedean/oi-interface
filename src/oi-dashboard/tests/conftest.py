"""Pytest configuration and shared fixtures for oi-dashboard tests."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

# Configure asyncio mode for pytest-asyncio
pytest_plugins = ["pytest_asyncio"]

DASHBOARD_SRC = Path(__file__).parent.parent / "src"
if str(DASHBOARD_SRC) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_SRC))

from oi_dashboard.dashboard import Dashboard


@pytest.fixture(scope="session")
def event_loop_policy():
    """Use the default event loop policy."""
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture
async def dashboard() -> Dashboard:
    """Create a dashboard instance with an ephemeral port for tests."""
    dash = Dashboard(
        api_base_url="http://localhost:9999",
        host="localhost",
        port=0,
        poll_interval=60.0,
    )
    await dash.start()
    yield dash
    await dash.stop()
