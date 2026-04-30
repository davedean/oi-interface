# AGENTS.md — generic_sbc_handheld SDL2 / audio guidance

This folder targets Linux handhelds (RG351P / AmberELEC) using SDL2 + PySDL2.

## Critical SDL2 setup order (do not skip)

1. Set `PYSDL2_DLL_PATH` before importing `sdl2`.
2. Add PortMaster exlibs to `sys.path` when running on device.
3. Then import `sdl2` / PySDL2 APIs.

Reference pattern (already used in `oi_client/__main__.py`):

```python
import os, sys
os.environ.setdefault("PYSDL2_DLL_PATH", "/usr/lib")
pm_exlibs = "/storage/roms/ports/PortMaster/exlibs"
if os.path.isdir(pm_exlibs) and pm_exlibs not in sys.path:
    sys.path.insert(0, pm_exlibs)
import sdl2
```

If you import `sdl2` too early, module resolution can fail on-device.

## Audio capture gotchas on AmberELEC / RG351P

### 1) Default capture device may fail even when mic exists

`SDL_OpenAudioDevice(None, iscapture=1, ...)` may choose a bad/default path and fail.

Observed failure:
- ALSA dmix playback-only error during capture open.

**Preferred behavior:** enumerate capture devices and choose one explicitly:
- Prefer names containing `usb`, `mic`, or `capture`.
- Fallback to first capture device index if present.

### 2) PySDL2 constructor differences (`format` vs `aformat`)

Across bundled versions, `SDL_AudioSpec(...)` may expect:
- `format=...` **or**
- `aformat=...`

Use try/fallback construction to support both.

### 3) Verify capture with a direct on-device probe before app-level changes

Use this exact check via SSH (includes PortMaster path):

```bash
ssh anbernic 'PYTHONPATH=/storage/roms/ports/Oi/oi_client python3 - <<"PY"
import os,sys,time
pm="/storage/roms/ports/PortMaster/exlibs"
if os.path.isdir(pm) and pm not in sys.path:
    sys.path.insert(0,pm)
os.environ.setdefault("PYSDL2_DLL_PATH","/usr/lib")
from audio import HandheldAudio
import sdl2

a=HandheldAudio()
print("recording_init:", a.recording_init())
if sdl2.SDL_Init(sdl2.SDL_INIT_AUDIO)==0:
    n=sdl2.SDL_GetNumAudioDevices(1)
    print("capture_device_count:", n)
    for i in range(n):
        name=sdl2.SDL_GetAudioDeviceName(i,1)
        print(i, name.decode() if name else None)
    sdl2.SDL_QuitSubSystem(sdl2.SDL_INIT_AUDIO)

ok=a.start_recording()
print("start_recording:", ok)
if ok:
    time.sleep(0.3)
    print("bytes:", len(a.read_recording()))
    a.stop_recording()
PY'
```

## Input / long-press behavior

SDL usually emits one `JOYBUTTONDOWN` and one `JOYBUTTONUP`; it does **not** emit repeated downs while held.

Therefore long-press detection must be frame/tick based (increment hold counters each poll/tick), not event-repeat based.

## UX expectations for current handheld app

- Prompt send: short A press/release.
- Voice capture: long-hold X.
- Recording state must be visibly indicated (e.g. “Hold X…”, “Listening…”, recording dot).

When changing controls, update:
- handler logic
- `_hint_for_mode()` text

## Deployment workflow

Preferred generic deploy script:

```bash
./src/oi-clients/generic_sbc_handheld/deploy.sh --host anbernic
```

Back-compat RG351P wrapper still works:

```bash
./deploy_to_rg351p.sh
```

Defaults deploy to:
- `/storage/roms/ports/Oi/oi_client/`
- `/storage/roms/ports/Oi/capability-profile.json`
- `/storage/roms/ports/Oi.sh`

Useful options:
- `--dry-run`
- `--backup`
- `--verbose`
- `--target-root /storage/roms/ports`
- `--app-dir Oi`
- `--launcher Oi.sh`

## Logging location on device

- `/storage/roms/ports/Oi/oi_client/oi.log`

Always check this first for:
- input events
- recording start/stop path
- SDL/ALSA errors
- playback/capture outcomes

## Don’t rediscover these

- PySDL2 import path needs PortMaster exlibs on device.
- `SDL_AudioSpec` kwarg may be `aformat` not `format`.
- default capture device can fail; select explicit capture device.
- long-press logic must advance per poll frame, not on repeated down events.
