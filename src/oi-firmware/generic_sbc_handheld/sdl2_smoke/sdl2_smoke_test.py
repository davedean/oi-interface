#!/usr/bin/env python3
"""Minimal SDL2 smoke test for RG351P (AmberELEC).

Opens a 480x320 fullscreen SDL2 window, draws a few lines of text,
polls for joystick button presses, and quits cleanly.

Usage on device:
    PYTHONPATH=/storage/roms/ports/PortMaster/exlibs \
    PYSDL2_DLL_PATH=/usr/lib \
    python3 sdl2_smoke_test.py

Keys:
    D-Pad directions — print to stdout
    A (button 1)     — flash green
    B (button 0)     — flash red
    Start (button 6) — quit
"""

from __future__ import annotations

import ctypes
import os
import sys
import time

# Ensure PYSDL2_DLL_PATH is set if not already.
if not os.environ.get("PYSDL2_DLL_PATH"):
    os.environ["PYSDL2_DLL_PATH"] = "/usr/lib"

# PortMaster ships pysdl2; add it to path if sdl2 not importable.
try:
    import sdl2
except ImportError:
    pm_exlibs = "/storage/roms/ports/PortMaster/exlibs"
    if os.path.isdir(pm_exlibs) and pm_exlibs not in sys.path:
        sys.path.insert(0, pm_exlibs)
    import sdl2

from sdl2 import (
    SDL_INIT_VIDEO,
    SDL_INIT_JOYSTICK,
    SDL_INIT_EVENTS,
    SDL_WINDOW_FULLSCREEN_DESKTOP,
    SDL_WINDOW_SHOWN,
    SDL_WINDOWPOS_CENTERED,
    SDL_QUIT,
    SDL_KEYDOWN,
    SDL_JOYBUTTONDOWN,
    SDL_JOYBUTTONUP,
    SDL_JOYHATMOTION,
    SDLK_q,
    SDLK_ESCAPE,
    SDL_Event,
    SDL_PollEvent,
    SDL_CreateWindow,
    SDL_CreateRenderer,
    SDL_SetRenderDrawColor,
    SDL_RenderClear,
    SDL_RenderFillRect,
    SDL_RenderPresent,
    SDL_DestroyRenderer,
    SDL_DestroyWindow,
    SDL_Quit,
    SDL_Init,
    SDL_QuitSubSystem,
    SDL_NumJoysticks,
    SDL_IsGameController,
    SDL_GameControllerOpen,
    SDL_GameControllerName,
    SDL_GameControllerClose,
    SDL_JoystickOpen,
    SDL_JoystickClose,
    SDL_Rect,
)
from sdl2.ext import Color


# Screen dimensions for RG351P
SCREEN_W, SCREEN_H = 480, 320

# Named colors
BLACK = Color(0, 0, 0, 255)
WHITE = Color(255, 255, 255, 255)
GREEN = Color(0, 200, 50, 255)
RED = Color(200, 40, 40, 255)
YELLOW = Color(230, 200, 40, 255)
BLUE = Color(60, 120, 230, 255)
GRAY = Color(120, 120, 120, 255)


def draw_rect_fill(renderer, x, y, w, h, color):
    SDL_SetRenderDrawColor(renderer, color.r, color.g, color.b, color.a)
    rect = SDL_Rect(x, y, w, h)
    SDL_RenderFillRect(renderer, ctypes.byref(rect))


def draw_text(renderer, x, y, text, size="normal"):
    """Fallback text renderer using colored rectangles.

    Real code will use SDL_ttf with a .ttf font.
    """
    char_w = 6 if size == "small" else 10
    char_h = 8 if size == "small" else 14
    spacing = 1
    for i, ch in enumerate(text):
        hue = (ord(ch) * 17) % 256
        c = Color(hue, 200, 255 - hue, 255)
        draw_rect_fill(renderer, x + i * (char_w + spacing), y, char_w, char_h, c)


def main():
    print("SDL2 Smoke Test starting...")

    ret = SDL_Init(SDL_INIT_VIDEO | SDL_INIT_JOYSTICK | SDL_INIT_EVENTS)
    if ret != 0:
        print(f"SDL_Init failed: {ret}")
        return 1

    print(f"SDL2 initialized. Joysticks: {SDL_NumJoysticks()}")

    # Open game controller if available
    controller = None
    controller_name = None
    for i in range(SDL_NumJoysticks()):
        if SDL_IsGameController(i):
            controller = SDL_GameControllerOpen(i)
            controller_name = SDL_GameControllerName(controller)
            print(f"Opened game controller {i}: {controller_name}")
            break
        else:
            joy = SDL_JoystickOpen(i)
            print(f"Opened joystick {i}")
            SDL_JoystickClose(joy)

    if controller is None:
        print("WARNING: no game controller found!")

    # Create fullscreen window
    window = SDL_CreateWindow(
        b"Oi Smoke Test",
        SDL_WINDOWPOS_CENTERED,
        SDL_WINDOWPOS_CENTERED,
        SCREEN_W,
        SCREEN_H,
        SDL_WINDOW_FULLSCREEN_DESKTOP | SDL_WINDOW_SHOWN,
    )
    if not window:
        print("Failed to create window")
        SDL_Quit()
        return 1

    renderer = SDL_CreateRenderer(window, -1, 0)
    if not renderer:
        print("Failed to create renderer")
        SDL_DestroyWindow(window)
        SDL_Quit()
        return 1

    running = True
    flash_color: Color | None = None
    flash_frames = 0
    message = "SDL2 Smoke Test"

    print("Running. Press Start to quit.")

    event = SDL_Event()
    while running:
        # --- Poll events ---
        while SDL_PollEvent(ctypes.byref(event)) != 0:
            if event.type == SDL_QUIT:
                running = False
                break

            elif event.type == SDL_KEYDOWN:
                key = event.key.keysym.sym
                if key in (SDLK_q, SDLK_ESCAPE):
                    running = False

            elif event.type == SDL_JOYBUTTONDOWN:
                btn = event.jbutton.button
                print(f"  Button DOWN: {btn}")
                if btn == 0:      # B
                    flash_color = RED
                    flash_frames = 10
                    message = "B pressed (back)"
                elif btn == 1:    # A
                    flash_color = GREEN
                    flash_frames = 10
                    message = "A pressed (confirm)"
                elif btn == 2:    # X
                    flash_color = BLUE
                    flash_frames = 10
                    message = "X pressed"
                elif btn == 3:    # Y
                    flash_color = YELLOW
                    flash_frames = 10
                    message = "Y pressed"
                elif btn == 6:    # Start
                    flash_color = WHITE
                    flash_frames = 5
                    running = False
                elif btn == 7:    # Select
                    flash_color = GRAY
                    flash_frames = 5
                    message = "Select pressed"
                elif btn == 8:    # L3
                    message = "L3 pressed"
                elif btn == 9:    # R3
                    message = "R3 pressed"
                elif btn == 10:   # L1
                    message = "L1 pressed"
                elif btn == 11:   # R1
                    message = "R1 pressed"

            elif event.type == SDL_JOYBUTTONUP:
                btn = event.jbutton.button
                print(f"  Button UP: {btn}")

            elif event.type == SDL_JOYHATMOTION:
                hat = event.jhat.hat
                val = event.jhat.value
                dirs = []
                if val & 1:
                    dirs.append("UP")
                if val & 2:
                    dirs.append("RIGHT")
                if val & 4:
                    dirs.append("DOWN")
                if val & 8:
                    dirs.append("LEFT")
                if dirs:
                    print(f"  D-Pad: {','.join(dirs)}")

        # --- Render frame ---
        if flash_color and flash_frames > 0:
            SDL_SetRenderDrawColor(renderer, flash_color.r, flash_color.g, flash_color.b, 255)
            flash_frames -= 1
        else:
            SDL_SetRenderDrawColor(renderer, BLACK.r, BLACK.g, BLACK.b, 255)

        SDL_RenderClear(renderer)

        # Title
        draw_text(renderer, 20, 20, message, size="normal")
        # Instructions
        draw_text(renderer, 20, 60, "A=Green B=Red Start=Quit", size="small")
        draw_text(renderer, 20, 80, "D-pad prints to stdout", size="small")

        # Border
        border = 4
        draw_rect_fill(renderer, 0, 0, SCREEN_W, border, WHITE)
        draw_rect_fill(renderer, 0, SCREEN_H - border, SCREEN_W, border, WHITE)
        draw_rect_fill(renderer, 0, 0, border, SCREEN_H, WHITE)
        draw_rect_fill(renderer, SCREEN_W - border, 0, border, SCREEN_H, WHITE)

        SDL_RenderPresent(renderer)

        # ~30fps
        time.sleep(0.033)

    # --- Cleanup ---
    print("Quitting...")
    if controller:
        SDL_GameControllerClose(controller)
    SDL_DestroyRenderer(renderer)
    SDL_DestroyWindow(window)
    SDL_QuitSubSystem(SDL_INIT_VIDEO | SDL_INIT_JOYSTICK | SDL_INIT_EVENTS)
    SDL_Quit()
    print("SDL2 Smoke Test done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
