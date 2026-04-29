"""Pytest configuration and shared fixtures for oi-dashboard tests."""
from __future__ import annotations

import asyncio

import pytest

# Configure asyncio mode for pytest-asyncio
pytest_plugins = ["pytest_asyncio"]


@pytest.fixture(scope="session")
def event_loop_policy():
    """Use the default event loop policy."""
    return asyncio.DefaultEventLoopPolicy()
