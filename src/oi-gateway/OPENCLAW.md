# OpenClaw Backend Setup

Oi-gateway can talk to OpenClaw through the `openclaw` backend in `src/oi-gateway/src/channel/openclaw_backend.py`.

## Required environment

Set these before starting `oi-gateway`:

```bash
export OI_AGENT_BACKEND=openclaw
export OI_OPENCLAW_URL=ws://127.0.0.1:18789
export OI_OPENCLAW_TOKEN='<your-openclaw-token>'
```

Optional:

```bash
export OI_OPENCLAW_TIMEOUT_SECONDS=120
```

The backend factory defaults `OI_OPENCLAW_URL` to `ws://127.0.0.1:18789`, so you only need to override it if OpenClaw is listening somewhere else.
`oi-gateway` now loads TOML config directly on startup.
Use `./start-oi.sh test` to check gateway health.

## Local OpenClaw config

Your OpenClaw Gateway config is already compatible with the defaults used by oi-gateway:

- `gateway.port = 18789`
- `gateway.mode = local`
- `gateway.bind = lan`
- `gateway.auth.mode = token`

For Oi, the browser `controlUi.allowedOrigins` list is not the important part. What matters is that the gateway is up and accepting WebSocket RPC on port `18789`, and that the token exported in `OI_OPENCLAW_TOKEN` matches the OpenClaw auth token.

For copy-paste TOML examples, see:
- [`config.toml.example`](config.toml.example)
- [`secrets.toml.example`](secrets.toml.example)

Set `OI_OPENCLAW_TOKEN` in `~/.oi/secrets/oi-gateway/secrets.toml`.

## Start order

1. Start OpenClaw Gateway.
2. Put values in `~/.oi/config/oi-gateway/config.toml` and `~/.oi/secrets/oi-gateway/secrets.toml`.
3. Start `oi-gateway`.

Example:

```bash
./start-oi.sh start openclaw
```

## Validation

The backend is covered by unit tests in `tests/test_openclaw_backend.py` and factory coverage in `tests/test_backend_factory.py`.

If you want to exercise the live integration adapter tests, set:

```bash
export RUN_OPENCLAW_TESTS=1
```

Those tests require a running OpenClaw server.
