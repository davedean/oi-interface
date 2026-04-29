#!/usr/bin/env python3
"""Patch datp.py to add error handling in _send method."""

import sys
import os

datp_path = "/storage/roms/ports/Oi/oi_client/datp.py"
if not os.path.exists(datp_path):
    print(f"File not found: {datp_path}")
    sys.exit(1)

with open(datp_path, 'r') as f:
    lines = f.readlines()

# 1. Add logging import after other imports
import_line = -1
for i, line in enumerate(lines):
    if line.startswith('import ') or line.startswith('from '):
        import_line = i
    elif line.strip() and not line.startswith('#') and import_line != -1:
        # Insert after the last import block
        # Find where to insert (after the last consecutive import line)
        j = i
        while j > 0 and (lines[j-1].startswith('import ') or lines[j-1].startswith('from ')):
            j -= 1
        # Insert after line j-1? Actually we need to insert after the last import line.
        # Let's just insert after line import_line (the last import line we found)
        # But we need to ensure we don't insert in middle of class.
        # Simpler: insert after the first block of imports at top of file.
        pass

# Let's do simpler: insert after the line containing 'import json'
for i, line in enumerate(lines):
    if 'import json' in line:
        lines.insert(i+1, 'import logging\n')
        break

# 2. Replace _send method
new_send = '''    async def _send(self, msg_type: str, payload: dict) -> None:
        if not self._ws:
            return
        msg = {
            "v": "datp",
            "type": msg_type,
            "id": _new_id(msg_type[:4]),
            "device_id": self.device_id,
            "ts": _now_iso(),
            "payload": payload,
        }
        try:
            await self._ws.send(json.dumps(msg))
        except Exception as e:
            logging.getLogger(__name__).error("WebSocket send failed: %s", e)
            self._connected = False
            self._ws = None
            raise
'''

# Find start of _send method
in_class = False
for i, line in enumerate(lines):
    if 'class DatpClient:' in line:
        in_class = True
    if in_class and 'async def _send(self, msg_type: str, payload: dict) -> None:' in line:
        # Find end of method (next line with same indentation as class method)
        indent = len(line) - len(line.lstrip())
        j = i + 1
        while j < len(lines) and (lines[j].startswith(' ' * (indent + 4)) or lines[j].strip() == ''):
            j += 1
        # Replace lines[i:j] with new_send
        # Ensure new_send lines have proper indentation
        new_lines = new_send.splitlines(keepends=True)
        # Replace
        lines[i:j] = new_lines
        print(f"Replaced _send method at line {i}")
        break

# Write back
backup_path = datp_path + '.bak'
with open(backup_path, 'w') as f:
    f.writelines(lines)
print(f"Backup saved to {backup_path}")

# Now replace original
with open(datp_path, 'w') as f:
    f.writelines(lines)
print(f"Patched {datp_path}")