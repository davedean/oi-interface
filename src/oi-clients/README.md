# oi-clients

Device client target work for Oi devices (firmware and higher-level client runtimes).

## Current targets

- `generic_sbc_handheld/` — Linux handheld runtime sketch and implementation notes.
- `m5stack_stickS3/` — hardware target workspace. **TODO:** document toolchain, build, and flash flow.
- `pico8/` — PICO-8 target workspace. **TODO:** document cartridge workflow and deployment steps.
- `tools/` — shared helper scripts/assets. **TODO:** document supported scripts and usage.

## How to work in this folder

- Keep docs and code scoped per target folder.
- Prefer small, testable changes.
- If target setup details are unknown, add explicit `TODO:` placeholders instead of guessing commands or toolchains.
- Add or update each target's `README.md` when behavior or workflow changes.
