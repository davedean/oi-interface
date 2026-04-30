#!/usr/bin/env python3
"""Controller + SDL2 diagnostic for RG351P.

Shows every button press, hat movement, and keyboard event on screen.
Auto-quits after 30 seconds so it can't hang the device.
"""

from __future__ import annotations

import ctypes
import os
import sys
import time

os.environ.setdefault("PYSDL2_DLL_PATH", "/usr/lib")

try:
    import sdl2
except ImportError:
    pm_exlibs = "/storage/roms/ports/PortMaster/exlibs"
    if os.path.isdir(pm_exlibs) and pm_exlibs not in sys.path:
        sys.path.insert(0, pm_exlibs)
    import sdl2

from sdl2 import (
    SDL_INIT_VIDEO, SDL_INIT_JOYSTICK, SDL_INIT_EVENTS,
    SDL_WINDOW_FULLSCREEN_DESKTOP, SDL_WINDOW_SHOWN,
    SDL_WINDOWPOS_CENTERED,
    SDL_QUIT, SDL_KEYDOWN, SDL_KEYUP,
    SDL_JOYBUTTONDOWN, SDL_JOYBUTTONUP, SDL_JOYHATMOTION,
    SDL_JOYDEVICEADDED, SDL_JOYDEVICEREMOVED,
    SDLK_q, SDLK_ESCAPE, SDLK_UP, SDLK_DOWN, SDLK_LEFT, SDLK_RIGHT,
    SDLK_RETURN, SDLK_BACKSPACE, SDLK_LSHIFT, SDLK_RSHIFT,
    SDL_Event, SDL_PollEvent,
    SDL_CreateWindow, SDL_DestroyWindow, SDL_Quit, SDL_Init, SDL_QuitSubSystem,
    SDL_GetError,
    SDL_NumJoysticks, SDL_IsGameController,
    SDL_GameControllerOpen, SDL_GameControllerName, SDL_GameControllerClose,
    SDL_JoystickOpen, SDL_JoystickClose, SDL_JoystickInstanceID,
)
from sdl2 import SDL_Color
from sdl2.sdlttf import TTF_Init, TTF_Quit, TTF_OpenFont, TTF_CloseFont, TTF_RenderText_Solid

SCREEN_W, SCREEN_H = 480, 320

BG = SDL_Color(10, 10, 20, 255)
FG = SDL_Color(220, 220, 220, 255)
ACCENT = SDL_Color(80, 200, 120, 255)
WARN = SDL_Color(230, 100, 60, 255)

FONT_PATHS = [
    "/usr/share/retroarch-assets/fonts/OpenSans-Regular.ttf",
    "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
]


def find_font():
    for p in FONT_PATHS:
        if os.path.isfile(p):
            return p
    return None


def load_font(path: str, size: int):
    f = TTF_OpenFont(path.encode(), size)
    if not f:
        raise RuntimeError(f"TTF_OpenFont failed: {path}")
    return f


def render_tex(renderer, font, text: str, color):
    surf = TTF_RenderText_Solid(font, text.encode(), color)
    if not surf:
        return None, 0, 0
    from sdl2 import SDL_CreateTextureFromSurface, SDL_FreeSurface
    tex = SDL_CreateTextureFromSurface(renderer, surf)
    w, h = surf.contents.w, surf.contents.h
    SDL_FreeSurface(surf)
    return tex, w, h


def draw_rect(renderer, x, y, w, h, color):
    from sdl2 import SDL_SetRenderDrawColor, SDL_RenderFillRect, SDL_Rect
    SDL_SetRenderDrawColor(renderer, color.r, color.g, color.b, 255)
    rect = SDL_Rect(x, y, w, h)
    SDL_RenderFillRect(renderer, ctypes.byref(rect))


def draw_texture(renderer, tex, x, y, w, h):
    from sdl2 import SDL_RenderCopy, SDL_Rect
    dst = SDL_Rect(x, y, w, h)
    SDL_RenderCopy(renderer, tex, None, ctypes.byref(dst))


# Common guess mappings for RG351P — these are *guesses* we'll verify
def guess_button(btn: int) -> str:
    guesses = {
        0: "B",
        1: "A",
        2: "X",
        3: "Y",
        4: "L1",
        5: "R1",
        6: "Select?",
        7: "Start?",
        8: "L3",
        9: "R3",
        10: "L2",
        11: "R2",
    }
    return guesses.get(btn, f"btn{btn}")


def guess_hat(val: int) -> str:
    dirs = []
    if val == 0:
        return "center"
    if val & 1:
        dirs.append("UP")
    if val & 2:
        dirs.append("RIGHT")
    if val & 4:
        dirs.append("DOWN")
    if val & 8:
        dirs.append("LEFT")
    return "+".join(dirs) if dirs else f"raw={val}"


def main():
    print("diag: init SDL2...")
    if SDL_Init(SDL_INIT_VIDEO | SDL_INIT_JOYSTICK | SDL_INIT_EVENTS) != 0:
        print(f"SDL_Init failed: {SDL_GetError()}")
        return 1

    if TTF_Init() != 0:
        print("TTF_Init failed")
        SDL_Quit()
        return 1

    font_path = find_font()
    if not font_path:
        print("No font!")
        TTF_Quit(); SDL_Quit(); return 1

    font = load_font(font_path, 16)
    font_small = load_font(font_path, 13)

    window = SDL_CreateWindow(
        b"Oi Diag", SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
        SCREEN_W, SCREEN_H, SDL_WINDOW_FULLSCREEN_DESKTOP | SDL_WINDOW_SHOWN,
    )
    if not window:
        print(f"Window fail: {SDL_GetError()}")
        return 1

    from sdl2 import SDL_CreateRenderer, SDL_DestroyRenderer, SDL_RenderPresent
    renderer = SDL_CreateRenderer(window, -1, 0)
    if not renderer:
        print("Renderer fail")
        SDL_DestroyWindow(window); SDL_Quit(); return 1

    # Log lines: [(text, color_name), ...]
    log_lines: list[tuple[str, str]] = [
        ("Oi Controller Diagnostic", "accent"),
        ("Press every button. D-pad directions. Keys.", "fg"),
        ("Auto-quit in 30s. DO NOT RESET.", "warn"),
        ("", "fg"),
    ]
    MAX_LINES = 12

    controller = None
    for i in range(SDL_NumJoysticks()):
        if SDL_IsGameController(i):
            controller = SDL_GameControllerOpen(i)
            name = SDL_GameControllerName(controller)
            log_lines.append((f"Controller {i}: {name.decode() if name else '???'}", "fg"))
            break

    running = True
    event = SDL_Event()
    start_time = time.time()

    while running:
        # Auto-quit after 30s
        elapsed = time.time() - start_time
        if elapsed > 30:
            log_lines.append(("AUTO-QUIT (timeout)", "warn"))
            running = False

        while SDL_PollEvent(ctypes.byref(event)) != 0:
            et = event.type

            if et == SDL_QUIT:
                log_lines.append(("SDL_QUIT received", "warn"))
                running = False

            elif et == SDL_KEYDOWN:
                k = event.key.keysym.sym
                sym_name = {
                    SDLK_q: "Q", SDLK_ESCAPE: "ESC",
                    SDLK_UP: "KEY_UP", SDLK_DOWN: "KEY_DOWN",
                    SDLK_LEFT: "KEY_LEFT", SDLK_RIGHT: "KEY_RIGHT",
                    SDLK_RETURN: "ENTER", SDLK_BACKSPACE: "BACKSPACE",
                    SDLK_LSHIFT: "LSHIFT", SDLK_RSHIFT: "RSHIFT",
                }.get(k, f"key_{k}")
                log_lines.append((f"KEY DOWN: {sym_name}", "accent"))

            elif et == SDL_JOYBUTTONDOWN:
                btn = event.jbutton.button
                guess = guess_button(btn)
                log_lines.append((f"BUTTON DOWN: {btn}  ({guess})", "fg"))
                if btn in (6, 7, 8, 9):  # common Start/Select candidates
                    log_lines.append((f"  ^^ maybe Start/Select?", "accent"))

            elif et == SDL_JOYBUTTONUP:
                btn = event.jbutton.button
                log_lines.append((f"BUTTON UP: {btn}", "fg"))

            elif et == SDL_JOYHATMOTION:
                hat = event.jhat.hat
                val = event.jhat.value
                guess = guess_hat(val)
                log_lines.append((f"HAT {hat}: val={val}  ({guess})", "fg"))

            elif et == SDL_JOYDEVICEADDED:
                log_lines.append((f"DEVICE ADDED: {event.jdevice.which}", "accent"))

            elif et == SDL_JOYDEVICEREMOVED:
                log_lines.append((f"DEVICE REMOVED: {event.jdevice.which}", "warn"))

        # Trim log
        while len(log_lines) > MAX_LINES:
            log_lines.pop(3)  # keep header lines 0-2

        # Render
        draw_rect(renderer, 0, 0, SCREEN_W, SCREEN_H, BG)

        y = 8
        for text, color_name in log_lines:
            color = ACCENT if color_name == "accent" else (WARN if color_name == "warn" else FG)
            tex, w, h = render_tex(renderer, font if y < 60 else font_small, text, color)
            if tex:
                draw_texture(renderer, tex, 10, y, w, h)
                from sdl2 import SDL_DestroyTexture
                SDL_DestroyTexture(tex)
            y += h + 4

        # Timeout bar
        bar_w = int((elapsed / 30.0) * (SCREEN_W - 20))
        draw_rect(renderer, 10, SCREEN_H - 10, bar_w, 6, WARN)

        SDL_RenderPresent(renderer)
        time.sleep(0.02)

    # Cleanup
    print("diag: quitting...")
    if controller:
        SDL_GameControllerClose(controller)
    TTF_CloseFont(font); TTF_CloseFont(font_small)
    TTF_Quit()
    SDL_DestroyRenderer(renderer); SDL_DestroyWindow(window)
    SDL_QuitSubSystem(SDL_INIT_VIDEO | SDL_INIT_JOYSTICK | SDL_INIT_EVENTS)
    SDL_Quit()
    print("diag: done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
