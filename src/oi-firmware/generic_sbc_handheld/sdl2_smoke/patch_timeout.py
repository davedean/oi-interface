#!/usr/bin/env python3
"""Add timeout for WAITING mode to prevent indefinite hanging."""

import sys
import os

app_path = "/storage/roms/ports/Oi/oi_client/app.py"
if not os.path.exists(app_path):
    print(f"File not found: {app_path}")
    sys.exit(1)

with open(app_path, 'r') as f:
    lines = f.readlines()

# ------------------------------------------------------------------
# 1. Add waiting_start_time to __init__ attributes
# ------------------------------------------------------------------
init_method_line = -1
for i, line in enumerate(lines):
    if 'def __init__' in line and 'self,' in line:
        init_method_line = i
        break

if init_method_line == -1:
    print("Could not find __init__ method")
    sys.exit(1)

# Find the line where attributes are set (after super().__init__ if any)
# We'll insert after the last attribute initialization before the method ends
# Look for the line with "self._running = True"
for i in range(init_method_line, len(lines)):
    if 'self._running = True' in lines[i]:
        # Insert after this line
        lines.insert(i + 1, '        self._waiting_start_time = None\n')
        break

# ------------------------------------------------------------------
# 2. Update _send_prompt to set waiting start time
# ------------------------------------------------------------------
send_prompt_line = -1
for i, line in enumerate(lines):
    if 'async def _send_prompt' in line:
        send_prompt_line = i
        break

if send_prompt_line != -1:
    # Find the line after setting _ui_mode = UIMode.WAITING
    for i in range(send_prompt_line, len(lines)):
        if 'self._ui_mode = UIMode.WAITING' in lines[i]:
            # Insert after this line
            lines.insert(i + 1, '        self._waiting_start_time = time.time()\n')
            break

# ------------------------------------------------------------------
# 3. Update _handle_command to reset timer when leaving WAITING
# ------------------------------------------------------------------
# We need to reset timer when we receive commands that take us out of WAITING
# For example: display.show_card, display.show_status with state != "thinking"
# Actually, _state_to_ui handles state mapping. Simpler: reset in any command
# that changes _ui_mode away from WAITING.
# But we can't easily detect that. Instead, we'll reset when entering CARD mode
# or READY mode, etc.
# Let's find _handle_command method
handle_cmd_line = -1
for i, line in enumerate(lines):
    if 'def _handle_command' in line and 'cmd: dict' in line:
        handle_cmd_line = i
        break

if handle_cmd_line != -1:
    # Find op == "display.show_card" block
    for i in range(handle_cmd_line, len(lines)):
        if 'elif op == "display.show_card":' in lines[i]:
            # Insert at the beginning of this block (after setting _ui_mode)
            # Look for self._ui_mode = UIMode.CARD
            for j in range(i, min(i + 20, len(lines))):
                if 'self._ui_mode = UIMode.CARD' in lines[j]:
                    lines.insert(j + 1, '            self._waiting_start_time = None\n')
                    break
            break

# Also reset for display.show_status when state is not thinking
# Find that block
for i in range(handle_cmd_line, len(lines)):
    if 'elif op == "display.show_status":' in lines[i]:
        # This is tricky because we change _ui_mode based on state
        # We'll reset timer if the new mode is not WAITING
        # Actually, let's just reset timer anytime we get a status update
        # The timeout will restart if we stay in WAITING
        # Find where self._ui_mode is set
        for j in range(i, min(i + 30, len(lines))):
            if 'self._ui_mode = self._state_to_ui(state)' in lines[j]:
                # Insert after
                lines.insert(j + 1, '            if self._ui_mode != UIMode.WAITING:\n')
                lines.insert(j + 2, '                self._waiting_start_time = None\n')
                break
        break

# ------------------------------------------------------------------
# 4. Add timeout check in _tick method
# ------------------------------------------------------------------
tick_method_line = -1
for i, line in enumerate(lines):
    if 'async def _tick' in line:
        tick_method_line = i
        break

if tick_method_line != -1:
    # Find the line "await asyncio.sleep(0.033)" near the end of _tick
    for i in range(tick_method_line, len(lines)):
        if 'await asyncio.sleep(0.033)' in lines[i]:
            # Insert timeout check before the sleep
            timeout_check = '''        # Timeout check for WAITING mode (90 seconds)
        if self._ui_mode == UIMode.WAITING and self._waiting_start_time:
            if time.time() - self._waiting_start_time > 90:
                self._ui_mode = UIMode.ERROR
                self._card.title = "Timeout"
                self._card.body = "Response timed out after 90 seconds"
                self._waiting_start_time = None
'''
            lines.insert(i, timeout_check)
            break

# ------------------------------------------------------------------
# 5. Also reset timer when user cancels with B button
# ------------------------------------------------------------------
# Find B button handling in WAITING mode
for i, range_i in enumerate(lines):
    if 'elif self._ui_mode == UIMode.WAITING:' in lines[i]:
        # Find the B button handler inside
        for j in range(i, min(i + 20, len(lines))):
            if 'if ev.name == "b":' in lines[j]:
                # Insert reset after setting _ui_mode
                for k in range(j, min(j + 10, len(lines))):
                    if 'self._ui_mode = UIMode.HOME' in lines[k]:
                        lines.insert(k + 1, '                self._waiting_start_time = None\n')
                        break
                break
        break

# ------------------------------------------------------------------
# 6. Make sure we have 'import time' at top (it's already there)
# ------------------------------------------------------------------

# Write backup
backup_path = app_path + '.timeout.bak'
with open(backup_path, 'w') as f:
    f.writelines(lines)
print(f"Backup saved to {backup_path}")

# Replace original
with open(app_path, 'w') as f:
    f.writelines(lines)
print(f"Patched {app_path} with timeout handling")