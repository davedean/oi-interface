# WORKLOG

- 2026-04-29: Fixed HOME menu vertical spacing jitter by normalizing whitespace tokenization in `oi_client/renderer.py` (`_wrap_text` now uses `split()` instead of `split(" ")`). This prevents empty tokens from padded menu lines causing inconsistent wrapping/line heights when selection changes.
- 2026-04-30: Audio playback smoke test SUCCESS. Verified RG351P audio output via ALSA (`aplay`). Created test scripts that use `HandheldAudio` module to generate and play sine wave tones. Confirmed audio hardware detection, WAV file creation, and playback through same code path used by production HandheldApp.
