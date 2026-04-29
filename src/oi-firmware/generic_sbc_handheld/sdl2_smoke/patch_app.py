#!/usr/bin/env python3
"""Patch app.py to add error handling in _send_prompt method."""

import sys
import os

app_path = "/storage/roms/ports/Oi/oi_client/app.py"
if not os.path.exists(app_path):
    print(f"File not found: {app_path}")
    sys.exit(1)

with open(app_path, 'r') as f:
    lines = f.readlines()

# 1. Add logging import after import asyncio
for i, line in enumerate(lines):
    if 'import asyncio' in line:
        lines.insert(i+1, 'import logging\n')
        break

# 2. Find _send_prompt method
for i, line in enumerate(lines):
    if 'async def _send_prompt(self, text: str) -> None:' in line:
        start = i
        # Find end of method (next line with less indentation)
        indent = len(line) - len(line.lstrip())
        j = i + 1
        while j < len(lines) and (lines[j].startswith(' ' * (indent + 4)) or lines[j].strip() == ''):
            j += 1
        end = j
        # Build new method
        new_method = '''    async def _send_prompt(self, text: str) -> None:
        if not self.datp or not self.datp.is_connected:
            self._ui_mode = UIMode.OFFLINE
            return
        # Clear previous response before sending new prompt
        self._card = CardData(title="Oi", body="")
        self._ui_mode = UIMode.WAITING
        # Optimistic local character update so UI reflects waiting immediately.
        self._character_label = "Waiting"
        self._character_animation = "pulse"
        try:
            await self.datp.send_text_prompt(text)
        except Exception as e:
            logging.getLogger(__name__).error("Failed to send prompt: %s", e)
            self._ui_mode = UIMode.ERROR
            self._card.body = f"Send failed: {e}"
'''
        # Replace lines[start:end] with new_method lines
        new_lines = new_method.splitlines(keepends=True)
        lines[start:end] = new_lines
        print(f"Replaced _send_prompt method at line {start}")
        break

# Write backup
backup_path = app_path + '.bak'
with open(backup_path, 'w') as f:
    f.writelines(lines)
print(f"Backup saved to {backup_path}")

# Replace original
with open(app_path, 'w') as f:
    f.writelines(lines)
print(f"Patched {app_path}")