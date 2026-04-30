#!/usr/bin/env python3
"""Fix app issues: timeout, error handling, WebSocket resilience."""

import re
import os
import sys

APP_PATH = "/storage/roms/ports/Oi/oi_client/app.py"
DATP_PATH = "/storage/roms/ports/Oi/oi_client/datp.py"

def patch_datp():
    """Add error handling to datp.py _send method."""
    if not os.path.exists(DATP_PATH):
        print(f"{DATP_PATH} not found")
        return False
    
    with open(DATP_PATH, 'r') as f:
        content = f.read()
    
    # Find _send method pattern
    # We'll replace from "async def _send(" to the line before next method at same indent level
    # Simpler: replace the method body
    pattern = r'(\s*)async def _send\(self, msg_type: str, payload: dict\) -> None:\s*\n\s*if not self\._ws:\s*\n\s*return\s*\n\s*msg = \{.*?\}\s*\n\s*await self\._ws\.send\(json\.dumps\(msg\)\)'
    
    # Use DOTALL to match across lines
    new_method = '''    async def _send(self, msg_type: str, payload: dict) -> None:
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
            import logging
            logging.getLogger(__name__).error("WebSocket send failed: %s", e)
            self._connected = False
            self._ws = None
            raise'''
    
    # Try a simpler approach: replace the exact lines we know
    old = '''    async def _send(self, msg_type: str, payload: dict) -> None:
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
        await self._ws.send(json.dumps(msg))'''
    
    if old in content:
        content = content.replace(old, new_method)
        with open(DATP_PATH + '.new', 'w') as f:
            f.write(content)
        print("Patched datp.py _send method")
        return True
    else:
        print("Could not find exact _send method pattern")
        # Try to find it with regex
        lines = content.splitlines()
        in_send = False
        send_start = -1
        send_end = -1
        indent = ""
        for i, line in enumerate(lines):
            if 'async def _send' in line:
                in_send = True
                send_start = i
                # Get indentation
                indent = line[:len(line) - len(line.lstrip())]
            elif in_send and line.startswith(indent + ' ') and not line.startswith(indent + '    '):
                # Still in method (indented)
                continue
            elif in_send and line.startswith(indent) and not line.startswith(indent + ' '):
                # Method ended
                send_end = i
                break
        
        if send_start != -1 and send_end != -1:
            # Replace lines[send_start:send_end] with new_method
            new_lines = lines[:send_start] + new_method.splitlines() + lines[send_end:]
            with open(DATP_PATH + '.new', 'w') as f:
                f.write('\n'.join(new_lines))
            print("Patched datp.py using line detection")
            return True
        else:
            print("Could not locate _send method boundaries")
            return False

def patch_app():
    """Patch app.py with timeout and error handling."""
    if not os.path.exists(APP_PATH):
        print(f"{APP_PATH} not found")
        return False
    
    with open(APP_PATH, 'r') as f:
        lines = f.readlines()
    
    modified = False
    
    # 1. Add waiting_start_time to __init__
    for i, line in enumerate(lines):
        if 'self._running = True' in line:
            lines.insert(i + 1, '        self._waiting_start_time = None\n')
            modified = True
            break
    
    # 2. Update _send_prompt to set waiting time and add try-catch
    send_prompt_start = -1
    for i, line in enumerate(lines):
        if 'async def _send_prompt' in line:
            send_prompt_start = i
            break
    
    if send_prompt_start != -1:
        # Find the await line and wrap it
        for i in range(send_prompt_start, min(send_prompt_start + 30, len(lines))):
            if 'await self.datp.send_text_prompt(text)' in lines[i]:
                # Insert before: set waiting time
                # Actually we already set _ui_mode = UIMode.WAITING above
                # Find that line
                for j in range(send_prompt_start, i):
                    if 'self._ui_mode = UIMode.WAITING' in lines[j]:
                        lines.insert(j + 1, '        self._waiting_start_time = time.time()\n')
                        break
                
                # Wrap the await line in try-except
                old_line = lines[i]
                indent = old_line[:len(old_line) - len(old_line.lstrip())]
                new_block = f'''{indent}try:
{indent}    await self.datp.send_text_prompt(text)
{indent}except Exception as e:
{indent}    import logging
{indent}    logging.getLogger(__name__).error("Failed to send prompt: %s", e)
{indent}    self._ui_mode = UIMode.ERROR
{indent}    self._card.body = f"Send failed: {{e}}"
{indent}    self._waiting_start_time = None'''
                
                lines[i] = new_block
                modified = True
                break
    
    # 3. Add timeout check in _tick
    tick_start = -1
    for i, line in enumerate(lines):
        if 'async def _tick' in line:
            tick_start = i
            break
    
    if tick_start != -1:
        # Find the await asyncio.sleep line
        for i in range(tick_start, len(lines)):
            if 'await asyncio.sleep(0.033)' in lines[i]:
                timeout_check = '''        # Timeout check for WAITING mode (90 seconds)
        if self._ui_mode == UIMode.WAITING and self._waiting_start_time:
            if time.time() - self._waiting_start_time > 90:
                self._ui_mode = UIMode.ERROR
                self._card.title = "Timeout"
                self._card.body = "Response timed out after 90 seconds"
                self._waiting_start_time = None
'''
                lines.insert(i, timeout_check)
                modified = True
                break
    
    # 4. Reset timer when leaving WAITING mode via B button
    for i, line in enumerate(lines):
        if 'elif self._ui_mode == UIMode.WAITING:' in line:
            # Find B handler
            for j in range(i, min(i + 20, len(lines))):
                if 'if ev.name == "b":' in lines[j]:
                    # Find where _ui_mode is set to HOME
                    for k in range(j, min(j + 10, len(lines))):
                        if 'self._ui_mode = UIMode.HOME' in lines[k]:
                            lines.insert(k + 1, '                self._waiting_start_time = None\n')
                            modified = True
                            break
                    break
            break
    
    # 5. Reset timer when receiving display.show_card
    for i, line in enumerate(lines):
        if 'elif op == "display.show_card":' in line:
            # Find where _ui_mode is set to CARD
            for j in range(i, min(i + 10, len(lines))):
                if 'self._ui_mode = UIMode.CARD' in lines[j]:
                    lines.insert(j + 1, '            self._waiting_start_time = None\n')
                    modified = True
                    break
            break
    
    if modified:
        with open(APP_PATH + '.new', 'w') as f:
            f.writelines(lines)
        print("Created patched app.py.new")
        return True
    else:
        print("No changes made to app.py")
        return False

def main():
    print("Patching Oi client for better error handling and timeout...")
    
    # Backup original files
    import shutil
    for path in [APP_PATH, DATP_PATH]:
        if os.path.exists(path):
            shutil.copy2(path, path + '.backup_' + str(int(os.path.getmtime(path))))
    
    datp_ok = patch_datp()
    app_ok = patch_app()
    
    if datp_ok and os.path.exists(DATP_PATH + '.new'):
        os.rename(DATP_PATH + '.new', DATP_PATH)
        print(f"Updated {DATP_PATH}")
    
    if app_ok and os.path.exists(APP_PATH + '.new'):
        os.rename(APP_PATH + '.new', APP_PATH)
        print(f"Updated {APP_PATH}")
    
    print("Done.")

if __name__ == "__main__":
    main()