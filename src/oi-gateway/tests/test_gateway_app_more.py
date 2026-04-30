from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway_app import GatewayRuntime, main, run_forever


class DummyBackend:
    mode = "dummy"
    name = "dummy"


@pytest.mark.asyncio
async def test_gateway_runtime_start_and_stop(monkeypatch):
    runtime = GatewayRuntime(agent_backend=DummyBackend())
    runtime.server.start = AsyncMock()
    runtime.api.start = AsyncMock()
    runtime.api.stop = AsyncMock()
    runtime.server.stop = AsyncMock()
    original_close = runtime.store.close
    runtime.store.close = MagicMock(side_effect=original_close)

    await runtime.start()
    runtime.server.start.assert_awaited_once()
    runtime.api.start.assert_awaited_once()

    await runtime.stop()
    runtime.api.stop.assert_awaited_once()
    runtime.server.stop.assert_awaited_once()
    runtime.store.close.assert_called_once()


@pytest.mark.asyncio
async def test_run_forever_stops_on_cancellation():
    runtime = GatewayRuntime(agent_backend=DummyBackend())
    runtime.start = AsyncMock()
    runtime.stop = AsyncMock()

    task = asyncio.create_task(run_forever(runtime))
    await asyncio.sleep(0)
    task.cancel()
    await task

    runtime.start.assert_awaited_once()
    runtime.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_main_loads_config_builds_backend_and_runs(monkeypatch):
    backend = DummyBackend()
    fake_runtime = MagicMock(spec=GatewayRuntime)
    with patch("gateway_app.load_gateway_toml_config") as load_cfg, patch("gateway_app.create_backend_from_env", return_value=backend) as create_backend, patch("gateway_app.GatewayRuntime", return_value=fake_runtime) as runtime_cls, patch("gateway_app.run_forever", new=AsyncMock()) as run_loop:
        monkeypatch.setenv("OI_GATEWAY_PORT", "9991")
        monkeypatch.setenv("OI_GATEWAY_API_PORT", "9992")
        await main()

    load_cfg.assert_called_once()
    create_backend.assert_called_once()
    runtime_cls.assert_called_once()
    kwargs = runtime_cls.call_args.kwargs
    assert kwargs["agent_backend"] is backend
    assert kwargs["datp_port"] == 9991
    assert kwargs["api_port"] == 9992
    run_loop.assert_awaited_once_with(fake_runtime)
