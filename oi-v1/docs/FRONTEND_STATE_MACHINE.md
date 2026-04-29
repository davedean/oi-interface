# Frontend State Machine (Draft)

Status: draft
Owner package: WP-01

## High-level views

- `idle` (no pending prompt, session context visible)
- `session_list` (multi-session switcher)
- `prompt` (pending approval/question)
- `command_menu` (session-scoped commands)
- `settings` (device/local frontend settings)

## Priority rules

1. If pending prompt exists for active session -> `prompt` view priority.
2. Else show session-oriented idle summary.

## Core transitions

- idle -> session_list (user action)
- session_list -> idle (focus session or cancel)
- idle -> command_menu (user action)
- command_menu -> idle (command dispatched or cancel)
- any -> prompt (new pending prompt arrives)
- prompt -> idle (answer/cancel/snapshot refresh clears prompt)

## Failure transitions

- backend unavailable -> retain view, show offline indicator
- stale active session -> show status as offline, keep session selectable

## Determinism requirement

Given identical event/command sequence, reducer output must be identical.

## Test fixture requirement

Each transition above must have at least one fixture test.
