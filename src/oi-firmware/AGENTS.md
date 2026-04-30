# AGENTS.md — src/oi-firmware

Scope: applies to everything under `src/oi-firmware/`.

## Guidance

- Treat each target directory as independent unless shared code is explicit.
- Follow existing patterns in the target you are editing.
- Keep changes minimal and verifiable; run relevant local checks where available.
- Do **not** invent build/flash/toolchain instructions.
  - If unknown, write `TODO:` placeholders in docs.
- When adding a new target, include:
  - `README.md` with status and known workflow
  - explicit `TODO:` items for unknown setup steps
