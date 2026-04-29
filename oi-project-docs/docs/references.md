# References

These were used as contextual references while drafting the design docs.

## OpenClaw

- Website: https://openclaw.ai/
- GitHub: https://github.com/openclaw/openclaw

Relevant notes:

- Personal AI assistant run on user devices.
- Gateway/control-plane architecture.
- Many messaging channels.
- Voice support and live Canvas.
- Useful ecosystem target, but third-party skills require sandboxing and review.

## Hermes Agent

- GitHub: https://github.com/NousResearch/hermes-agent

Relevant notes:

- Self-improving agent framework.
- Built-in learning loop and skill creation/improvement.
- Memory and cross-session recall.
- Subagents and multiple terminal backends.
- Useful as delegated worker or optional chief-agent runtime.

## Rhasspy / Hermes MQTT

- Docs: https://rhasspy.readthedocs.io/

Relevant notes:

- Fully offline voice assistant toolkit.
- Works with Hermes protocol-compatible services.
- Integrates with Home Assistant, Node-RED, OpenHAB.
- Uses MQTT, HTTP, and WebSocket services.
- Useful as a bridge, not necessarily the core device protocol.

## Open Interpreter 01 Light

- Docs: https://01.openinterpreter.com/hardware/01-light/introduction

Relevant notes:

- ESP32 handheld push-to-talk voice interface.
- Sends voice over Wi-Fi to server and plays back received audio.
- Similar hardware/server split; different interaction and system architecture goals.

## Security reporting around open agent skill ecosystems

Recent reporting has highlighted risks in open skill/plugin ecosystems where agents may execute instructions and code with local credentials. The design docs therefore treat third-party skills as untrusted until sandboxed and audited.
