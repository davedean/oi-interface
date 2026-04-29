#!/bin/bash
# Oi SDL2 Smoke Test — Port launcher for AmberELEC / RG351P
# Drop as /storage/roms/ports/OiSmokeTest.sh

# Find PortMaster control scripts (sets up get_controls, ESUDO, etc.)
if [ -d "/storage/roms/ports/PortMaster/" ]; then
  controlfolder="/storage/roms/ports/PortMaster"
elif [ -d "/roms/ports/PortMaster/" ]; then
  controlfolder="/roms/ports/PortMaster"
else
  controlfolder="/storage/roms/ports/PortMaster"
fi

source $controlfolder/control.txt

get_controls

# Game directory
GAMEDIR="/$directory/ports/OiSmokeTest"
mkdir -p "$GAMEDIR"

cd "$GAMEDIR"

# Environment for SDL2 (PortMaster's pysdl2 + system SDL2)
export PYSDL2_DLL_PATH="/usr/lib"
export PYTHONPATH="/storage/roms/ports/PortMaster/exlibs"

# Kill any stray previous instance
$ESUDO pkill -f sdl2_text_test.py 2>/dev/null || true
$ESUDO pkill -f sdl2_smoke_test.py 2>/dev/null || true

# Run the mic capture test
python3 "$GAMEDIR/sdl2_mic_test.py"

# On exit, restart EmulationStation so it comes back to the Ports menu
$ESUDO systemctl restart emustation
