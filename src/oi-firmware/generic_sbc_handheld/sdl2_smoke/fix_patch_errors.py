#!/usr/bin/env python3
"""Fix errors introduced by previous patch."""

import os

APP_PATH = "/storage/roms/ports/Oi/oi_client/app.py"

def fix_send_prompt():
    with open(APP_PATH, 'r') as f:
        lines = f.readlines()
    
    # Find _send_prompt method
    start = -1
    for i, line in enumerate(lines):
        if 'async def _send_prompt' in line:
            start = i
            break
    
    if start == -1:
        print("Could not find _send_prompt")
        return False
    
    # Find end of method (next method or end of class)
    end = -1
    for i in range(start + 1, len(lines)):
        if lines[i].strip() and not lines[i].startswith('    ') and not lines[i].startswith('\t'):
            # Line not indented, end of method
            end = i
            break
    
    if end == -1:
        end = len(lines)
    
    # Replace the method with correct version
    correct_method = '''    async def _send_prompt(self, text: str) -> None:
        if not self.datp or not self.datp.is_connected:
            self._ui_mode = UIMode.OFFLINE
            return
        # Clear previous response before sending new prompt
        self._card = CardData(title="Oi", body="")
        self._ui_mode = UIMode.WAITING
        self._waiting_start_time = time.time()
        # Optimistic local character update so UI reflects waiting immediately.
        self._character_label = "Waiting"
        self._character_animation = "pulse"
        try:
            await self.datp.send_text_prompt(text)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error("Failed to send prompt: %s", e)
            self._ui_mode = UIMode.ERROR
            self._card.body = f"Send failed: {e}"
            self._waiting_start_time = None
'''
    
    lines[start:end] = correct_method.splitlines(keepends=True)
    
    # Also check for duplicate line in error handler
    # Look for the problematic line and fix it
    for i, line in enumerate(lines):
        if 'self._waiting_start_time = None        await self.datp.send_text_prompt(text)' in line:
            lines[i] = '            self._waiting_start_time = None\n'
            print(f"Fixed duplicate line at {i+1}")
            break
    
    with open(APP_PATH, 'w') as f:
        f.writelines(lines)
    
    print("Fixed _send_prompt method")
    return True

def check_timeout_logic():
    """Verify timeout logic is correct."""
    with open(APP_PATH, 'r') as f:
        lines = f.readlines()
    
    # Check for the timeout check in _tick
    found = False
    for i, line in enumerate(lines):
        if 'if self._ui_mode == UIMode.WAITING and self._waiting_start_time:' in line:
            found = True
            # Check next few lines
            for j in range(i, min(i+10, len(lines))):
                if 'self._card.body = "Response timed out after 90 seconds"' in lines[j]:
                    print("Timeout logic looks correct")
                    return True
    
    if not found:
        print("Warning: Timeout check not found")
    
    return False

def main():
    print("Fixing patch errors...")
    if fix_send_prompt():
        print("Successfully fixed _send_prompt")
    else:
        print("Failed to fix _send_prompt")
    
    check_timeout_logic()
    print("Done.")

if __name__ == "__main__":
    main()