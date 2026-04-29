# Deployment

## Local dev

```text
laptop/server
  python gateway
  local STT/TTS optional
  fake device
```

## Home deployment

```text
Raspberry Pi / mini PC
  gateway service
  agent runtime
  SQLite
  wiki files
  Whisper
  Piper
  Home Assistant adapter
```

Use systemd or similar.

## Suggested services

```text
agent-stick-gateway.service
agent-stick-worker.service
agent-stick-dashboard.service
```

## Network

Local:

```text
stick → ws://agent-stick.local:8787/datp
```

Secure local/remote:

```text
stick/phone relay → wss://gateway.example/datp
```

## Away from home

Preferred early option:

- Tailscale on server and phone/laptop;
- Stick connects via phone relay or known Wi-Fi where possible;
- remote dashboard over Tailscale.

## Backups

Back up:

- SQLite DB;
- wiki;
- policy files;
- device registry;
- audit logs according to retention policy;
- character packs;
- config.

Do not casually back up:

- raw secrets;
- OAuth tokens without encryption;
- large audio unless needed.

## Updates

Firmware:

- signed builds eventually;
- manual flashing early;
- OTA only after auth model is solid.

Server:

- git pull/deploy;
- container optional;
- config migration.

## Hosted future

Hosted relay should be deployable separately from hosted runtime.

Keep protocol open.
