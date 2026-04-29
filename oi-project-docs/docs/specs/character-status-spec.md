# Character Status Spec

## Purpose

A character pack is a visual status interface for the agent.

It makes state legible on tiny devices without requiring text.

## Separation of concerns

Agent identity is not the same as character skin.

- Agent identity: persistent chief session, memory, tasks, permissions.
- Character pack: visual embodiment used by one or more devices.

The same agent may appear as different characters on different devices.

## Required semantic states

Every character pack must implement:

```text
idle
listening
uploading
thinking
response_cached
playing
confirm
muted
offline
error
safe_mode
task_running
blocked
```

## Optional overlays

- battery low;
- Wi-Fi weak;
- delegated tool running;
- code task;
- home task;
- calendar task;
- wiki/memory update;
- private/sensitive;
- remote connection;
- cloud model in use.

## Asset model

For tiny devices:

```json
{
  "pack_id": "synth-goblin-v1",
  "target": "tiny_135x240",
  "format": "indexed_png|rgb565|spritesheet",
  "states": {
    "idle": {
      "sprite": "idle.png",
      "label": "Ready"
    },
    "thinking": {
      "sprite": "thinking_anim.png",
      "frames": 4,
      "fps": 2,
      "label": "Thinking"
    }
  }
}
```

## Generated character packs

User prompt:

```text
Make my agent look like a calm cyberpunk fox librarian.
```

Generator output should be a complete pack, not one image.

Required validation:

- all semantic states present;
- states visually distinguishable;
- muted/offline/error are clear;
- text labels remain readable;
- file sizes fit device constraints;
- colour palette works on target screen.

## Device rendering contract

The agent does not push arbitrary art during normal operation.

It requests semantic state:

```json
{
  "op": "character.set_state",
  "args": {
    "state": "thinking",
    "overlay": "code_task",
    "label": "Checking repo"
  }
}
```

The device chooses the local asset.

## Why this matters

The character is a trust surface.

It answers, at a glance:

- Are you listening?
- Are you thinking?
- Are you waiting for me?
- Are you offline?
- Did something go wrong?

## Avoid

- cute but ambiguous states;
- auto-generated skins without state testing;
- state changes that don't match real system state;
- making error states too subtle;
- making the character manipulate the user emotionally.
