# Testing

## Test categories

### Protocol tests

- valid hello;
- invalid protocol version;
- command ack;
- error response;
- reconnect/resume;
- out-of-order audio chunks;
- oversized payloads.

### Firmware state machine tests

- legal transitions;
- illegal transitions;
- playback during recording denied;
- offline fallback;
- safe mode gesture.

### Gateway tests

- fake device connects;
- device state updates;
- command routing;
- audio blob persistence;
- reconnect behaviour.

### Agent tests

- "mute for 30 minutes";
- "make screen dimmer";
- "what are you doing?";
- "add this to my wiki";
- "assess repo change";
- ambiguous request handling;
- short response style.

### Tool broker tests

- low-risk allowed;
- high-risk confirmation required;
- denied tool blocked;
- audit log written;
- sandbox timeout;
- secret redaction.

### Routing tests

- Stick gets short response;
- desktop gets long detail;
- sensitive content avoids public display;
- offline devices not selected;
- foreground device wins.

## Fake device simulator

Build a simulator early.

It should emulate:

- button events;
- audio upload;
- state reports;
- cache limits;
- command acks/errors;
- offline/reconnect.

## Golden transcript tests

Keep examples:

```text
input: mute yourself for thirty minutes
expected:
  tool: device.mute_until
  response <= 8 words
  route: stick cached audio
```

## Manual smoke test

Daily dev loop:

1. start gateway;
2. connect fake device;
3. run "mute";
4. run "what are you doing";
5. inspect task ledger;
6. connect real Stick;
7. perform full voice loop.
