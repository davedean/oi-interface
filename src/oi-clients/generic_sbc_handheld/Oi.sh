#!/bin/bash
# Generic Oi device runtime launcher for Linux SBC handhelds.
#
# This file is a template. deploy.sh fills in the app directory
# and default device id before copying it to the device.
#
# Example deployed path: /storage/roms/ports/Oi.sh

# Find PortMaster control scripts
if [ -d "/storage/roms/ports/PortMaster/" ]; then
  controlfolder="/storage/roms/ports/PortMaster"
elif [ -d "/roms/ports/PortMaster/" ]; then
  controlfolder="/roms/ports/PortMaster"
else
  controlfolder="/storage/roms/ports/PortMaster"
fi

source $controlfolder/control.txt

get_controls

GAMEDIR="/$directory/ports/__OI_APP_DIR__"
mkdir -p "$GAMEDIR"
mkdir -p "$GAMEDIR/oi_client/lib"
cd "$GAMEDIR"

# Environment for SDL2
export PYSDL2_DLL_PATH="/usr/lib"

# Python path: PortMaster pysdl2 + our vendored websockets + our package
export PYTHONPATH="/storage/roms/ports/PortMaster/exlibs:$GAMEDIR/oi_client/lib:$GAMEDIR"

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
  echo '{"gateway_url": "ws://gateway.local:8788/datp", "device_id": "__OI_DEFAULT_DEVICE_ID__", "device_type": "sbc-handheld"}' > "$GAMEDIR/config.json"
fi

# Run
python3 -m oi_client

# Return to EmulationStation
$ESUDO systemctl restart emustation
