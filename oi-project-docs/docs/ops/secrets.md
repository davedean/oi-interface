# Secrets

## Rules

- Devices do not store API keys.
- Devices store only pairing/session credentials.
- Server stores provider keys and OAuth tokens.
- Tool broker mediates secret access.
- Agents do not receive raw secrets unless absolutely necessary.

## Storage

Local dev:

- `.env` for throwaway prototypes.

Real local deployment:

- OS keychain where available;
- encrypted secrets file;
- sops/age;
- 1Password/Bitwarden CLI;
- systemd credentials.

## Secret classes

```text
device_pairing_key
model_api_key
oauth_refresh_token
home_assistant_token
github_token
tailscale_auth
encryption_key
```

## Redaction

All logs redact:

- API keys;
- OAuth tokens;
- cookies;
- SSH keys;
- passwords;
- seed phrases;
- private keys.

## Third-party tools

Third-party tools get scoped credentials, not ambient access.

## User command

```text
what secrets can you access?
```

Should answer by class/scope, not reveal values.
