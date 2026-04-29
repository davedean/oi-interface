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
If you use `./start-oi.sh start openclaw`, the launcher will also source `~/.oi/secrets/oi-gateway/openclaw.env.local` and `~/.oi/config/oi-gateway/openclaw.env.local` when they exist.
Use `./start-oi.sh test all` to check whether `pi`, `hermes`, and `openclaw` are all configured on this machine.

## Local OpenClaw config

Your OpenClaw Gateway config is already compatible with the defaults used by oi-gateway:

- `gateway.port = 18789`
- `gateway.mode = local`
- `gateway.bind = lan`
- `gateway.auth.mode = token`

For Oi, the browser `controlUi.allowedOrigins` list is not the important part. What matters is that the gateway is up and accepting WebSocket RPC on port `18789`, and that the token exported in `OI_OPENCLAW_TOKEN` matches the OpenClaw auth token.

For a copy-paste env file, see [`openclaw.env.example`](openclaw.env.example).

If you prefer the launcher path, put the token in `~/.oi/secrets/oi-gateway/openclaw.env.local` as `OPENCLAW_GATEWAY_TOKEN` or `OI_OPENCLAW_TOKEN` and the script will map it for `oi-gateway`.

## Start order

1. Start OpenClaw Gateway.
2. Export the environment variables above in the same shell that launches oi-gateway.
3. Start `oi-gateway`.

Example:

```bash
cd src/oi-gateway
export OI_AGENT_BACKEND=openclaw
export OI_OPENCLAW_URL=ws://127.0.0.1:18789
export OI_OPENCLAW_TOKEN='<your-openclaw-token>'
python3 -m oi_gateway
```

## Validation

The backend is covered by unit tests in `tests/test_openclaw_backend.py` and factory coverage in `tests/test_backend_factory.py`.

If you want to exercise the live integration adapter tests, set:

```bash
export RUN_OPENCLAW_TESTS=1
```

Those tests require a running OpenClaw server.
