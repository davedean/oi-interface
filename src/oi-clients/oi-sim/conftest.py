"""Shared test bootstrap and fixtures for oi-sim."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

# Add oi-gateway/src to sys.path so `from datp import ...` works in tests.
_GW_SRC = Path(__file__).resolve().parents[3] / "src" / "oi-gateway" / "src"
if str(_GW_SRC) not in sys.path:
    sys.path.insert(0, str(_GW_SRC))

from datp.server import DATPServer
from sim.sim import OiSim


async def _wait_for_server_port(srv: DATPServer, timeout_seconds: float = 1.0) -> None:
    """Wait until the DATP test server has bound an ephemeral port."""
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while srv.port == 0:
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError("DATP test server did not bind a port in time")
        await asyncio.sleep(0.01)


@pytest.fixture
async def datp_server():
    """Start the DATP server, yield it, then stop it."""
    srv = DATPServer(host="localhost", port=0)
    task = asyncio.create_task(srv.start())
    await _wait_for_server_port(srv)
    try:
        yield srv
    finally:
        await srv.stop()
        await task
        await asyncio.sleep(0.15)


@pytest.fixture
async def sim(datp_server):
    """Connected OiSim instance (yields, then disconnects automatically)."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-test")
    await device.connect()
    try:
        yield device
    finally:
        await device.disconnect()
