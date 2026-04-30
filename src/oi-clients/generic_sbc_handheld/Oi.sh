#!/bin/bash
# Generic Oi device runtime launcher for Linux SBC handhelds.
#
# This file is a template. deploy.sh fills in the app directory
# and default device id before copying it to the device.
#
# Example deployed path: /storage/roms/ports/Oi.sh

# Find PortMaster control scripts
XDG_DATA_HOME=${XDG_DATA_HOME:-$HOME/.local/share}

if [ -d "/mnt/mmc/MUOS/PortMaster/" ]; then
  controlfolder="/mnt/mmc/MUOS/PortMaster"
elif [ -d "/storage/roms/ports/PortMaster/" ]; then
  controlfolder="/storage/roms/ports/PortMaster"
elif [ -d "/roms/ports/PortMaster/" ]; then
  controlfolder="/roms/ports/PortMaster"
elif [ -d "/opt/system/Tools/PortMaster/" ]; then
  controlfolder="/opt/system/Tools/PortMaster"
elif [ -d "/opt/tools/PortMaster/" ]; then
  controlfolder="/opt/tools/PortMaster"
elif [ -d "$XDG_DATA_HOME/PortMaster/" ]; then
  controlfolder="$XDG_DATA_HOME/PortMaster"
else
  echo "PortMaster control folder not found."
  sleep 3
  exit 1
fi

source "$controlfolder/control.txt"
[ -f "${controlfolder}/mod_${CFW_NAME}.txt" ] && source "${controlfolder}/mod_${CFW_NAME}.txt"

get_controls

GAMEDIR="/$directory/ports/__OI_APP_DIR__"
mkdir -p "$GAMEDIR"
mkdir -p "$GAMEDIR/oi_client/lib"
cd "$GAMEDIR"

# Environment for SDL2
export PYSDL2_DLL_PATH="/usr/lib"

# Python path: PortMaster pysdl2 + our vendored websockets + our package
if [ -d "$controlfolder/exlibs" ]; then
  PORTMASTER_EXLIBS="$controlfolder/exlibs"
elif [ -d "/storage/roms/ports/PortMaster/exlibs" ]; then
  PORTMASTER_EXLIBS="/storage/roms/ports/PortMaster/exlibs"
elif [ -d "/roms/ports/PortMaster/exlibs" ]; then
  PORTMASTER_EXLIBS="/roms/ports/PortMaster/exlibs"
else
  PORTMASTER_EXLIBS=""
fi

if [ -n "$PORTMASTER_EXLIBS" ]; then
  export PYTHONPATH="$PORTMASTER_EXLIBS:$GAMEDIR/oi_client/lib:$GAMEDIR"
else
  export PYTHONPATH="$GAMEDIR/oi_client/lib:$GAMEDIR"
fi

# Copy source from build directory (or use rsync for deployment)
# In production, the oi_client package would be bundled with this script.
# For now we require it to exist at $GAMEDIR/oi_client/

if [ ! -d "$GAMEDIR/oi_client/" ]; then
  echo "Oi client not found at $GAMEDIR/oi_client/"
  echo "Please install the oi_client package here first."
  sleep 3
  $ESUDO systemctl restart emustation
  exit 1
fi

# Kill any previous instance
$ESUDO pkill -f "python3.*oi_client" 2>/dev/null || true

# Create default config if missing
if [ ! -f "$GAMEDIR/config.json" ]; then
  echo '{"gateway_url": "__OI_DEFAULT_GATEWAY_URL__", "device_id": "__OI_DEFAULT_DEVICE_ID__", "device_type": "sbc-handheld"}' > "$GAMEDIR/config.json"
fi

if ! python3 -c 'import sdl2' >/dev/null 2>&1; then
  echo "PySDL2 not available. Checked PYTHONPATH=$PYTHONPATH"
  echo "Expected PortMaster exlibs under: $controlfolder/exlibs"
  sleep 3
  exit 1
fi

# Run
python3 -m oi_client

# Return to EmulationStation
$ESUDO systemctl restart emustation
