#!/bin/bash
# Launcher for Oi SDL2 Smoke Test on AmberELEC / RG351P
# Drop into /storage/roms/ports/ as oi_smoke.sh

if [ -d "/storage/roms/ports/PortMaster/" ]; then
  controlfolder="/storage/roms/ports/PortMaster"
else
  controlfolder="/roms/ports/PortMaster"
fi

source $controlfolder/control.txt

get_controls

GAMEDIR="/$directory/ports/oi"
mkdir -p "$GAMEDIR"

cd "$GAMEDIR"

export PYSDL2_DLL_PATH="/usr/lib"
export PYTHONPATH="/storage/roms/ports/PortMaster/exlibs"

cp /tmp/sdl2_smoke_test.py "$GAMEDIR/" 2>/dev/null || true

python3 "$GAMEDIR/sdl2_smoke_test.py"

# Restart ES on return
$ESUDO systemctl restart emustation
