#!/usr/bin/env python3
"""SDL2_ttf text rendering test for RG351P.

Usage on device (from OiSmokeTest Port or ssh):
    PYTHONPATH=/storage/roms/ports/PortMaster/exlibs \
    PYSDL2_DLL_PATH=/usr/lib \
    python3 sdl2_text_test.py

Shows:
- A title in a real font
- A scrolling card body
- Button hint overlay
- D-pad scrolls text, A changes color, Start quits
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
    SDL_QUIT, SDL_KEYDOWN, SDL_JOYBUTTONDOWN, SDL_JOYHATMOTION,
    SDLK_q, SDLK_ESCAPE,
    SDL_Event, SDL_PollEvent,
    SDL_CreateWindow, SDL_DestroyWindow, SDL_Quit, SDL_Init, SDL_QuitSubSystem,
    SDL_GetError,
)
from sdl2.sdlttf import (
    TTF_Init, TTF_Quit, TTF_OpenFont, TTF_CloseFont,
    TTF_RenderText_Solid, TTF_RenderText_Blended_Wrapped,
    TTF_SizeText, TTF_FontHeight,
)
from sdl2 import SDL_Color


# Try a few system fonts in order of preference
FONT_CANDIDATES = [
    "/usr/share/retroarch-assets/fonts/OpenSans-Regular.ttf",
    "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
    "/usr/share/retroarch-assets/fonts/DejaVuSans.ttf",
]

SCREEN_W, SCREEN_H = 480, 320

COLORS = {
    "bg": SDL_Color(20, 20, 30, 255),
    "fg": SDL_Color(230, 230, 230, 255),
    "dim": SDL_Color(140, 140, 140, 255),
    "accent": SDL_Color(80, 180, 120, 255),
    "warn": SDL_Color(200, 80, 60, 255),
    "card_bg": SDL_Color(35, 35, 50, 255),
    "border": SDL_Color(60, 60, 80, 255),
}


def find_font() -> str | None:
    for path in FONT_CANDIDATES:
        if os.path.isfile(path):
            return path
    return None


def load_font(path: str, size: int):
    font = TTF_OpenFont(path.encode(), size)
    if not font:
        raise RuntimeError(f"TTF_OpenFont failed for {path}")
    return font


def render_text_surf(renderer, font, text: str, color, wrap_w: int = 0):
    """Render text to an SDL surface using TTF, then create a texture."""
    if wrap_w > 0:
        surf = TTF_RenderText_Blended_Wrapped(
            font, text.encode(), color, wrap_w
        )
    else:
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


def main():
    print("SDL2 TTF Text Test starting...")

    # Init SDL2
    if SDL_Init(SDL_INIT_VIDEO | SDL_INIT_JOYSTICK | SDL_INIT_EVENTS) != 0:
        print(f"SDL_Init failed: {SDL_GetError()}")
        return 1

    if TTF_Init() != 0:
        print(f"TTF_Init failed")
        SDL_Quit()
        return 1

    font_path = find_font()
    if not font_path:
        print("No font found!")
        TTF_Quit()
        SDL_Quit()
        return 1
    print(f"Using font: {font_path}")

    # Open fonts at different sizes
    try:
        font_title = load_font(font_path, 22)
        font_body = load_font(font_path, 16)
        font_hint = load_font(font_path, 12)
    except RuntimeError as exc:
        print(f"Font load failed: {exc}")
        TTF_Quit()
        SDL_Quit()
        return 1

    # Create window
    window = SDL_CreateWindow(
        b"Oi Text Test",
        SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
        SCREEN_W, SCREEN_H,
        SDL_WINDOW_FULLSCREEN_DESKTOP | SDL_WINDOW_SHOWN,
    )
    if not window:
        print(f"Window failed: {SDL_GetError()}")
        return 1

    from sdl2 import SDL_CreateRenderer, SDL_DestroyRenderer
    renderer = SDL_CreateRenderer(window, -1, 0)
    if not renderer:
        print("Renderer failed")
        SDL_DestroyWindow(window)
        SDL_Quit()
        return 1

    # Long card body to test scrolling
    card_body_full = (
        "Welcome to Oi on RG351P.\n"
        "This is a text rendering test.\n"
        "The device is 480x320.\n"
        "We can scroll long responses.\n"
        "Line five is here.\n"
        "Line six follows.\n"
        "And this is line seven.\n"
        "D-pad up/down scrolls.\n"
        "A changes accent color.\n"
        "Start quits back to ES.\n"
    )

    title = "Oi — Status: Online"
    scroll_y = 0
    accent_idx = 0
    accent_colors = ["accent", "warn", "dim"]

    running = True
    event = SDL_Event()

    print("Running. Start to quit.")

    # Pre-render title texture
    title_tex, title_w, title_h = render_text_surf(renderer, font_title, title, COLORS["fg"])

    while running:
        while SDL_PollEvent(ctypes.byref(event)) != 0:
            if event.type == SDL_QUIT:
                running = False
            elif event.type == SDL_KEYDOWN:
                if event.key.keysym.sym in (SDLK_q, SDLK_ESCAPE):
                    running = False
            elif event.type == SDL_JOYBUTTONDOWN:
                btn = event.jbutton.button
                print(f"Button: {btn}")
                if btn == 0:  # B
                    scroll_y = max(0, scroll_y - 20)
                elif btn == 1:  # A
                    accent_idx = (accent_idx + 1) % len(accent_colors)
                elif btn == 6:  # Start
                    running = False
            elif event.type == SDL_JOYHATMOTION:
                val = event.jhat.value
                if val & 1:
                    scroll_y = max(0, scroll_y - 20)
                if val & 4:
                    scroll_y += 20

        # --- Render ---
        draw_rect(renderer, 0, 0, SCREEN_W, SCREEN_H, COLORS["bg"])

        # Title bar
        draw_rect(renderer, 0, 0, SCREEN_W, title_h + 12, COLORS["card_bg"])
        if title_tex:
            draw_texture(renderer, title_tex, 12, 6, title_w, title_h)

        # Card body area
        card_top = title_h + 18
        card_h = SCREEN_H - card_top - 30
        draw_rect(renderer, 8, card_top, SCREEN_W - 16, card_h, COLORS["card_bg"])

        # Render body text (naive: render each line)
        y = card_top + 8 - scroll_y
        lines = card_body_full.split("\n")
        for line in lines:
            if y > card_top + card_h:
                break
            if y + 16 >= card_top and line:
                tex, w, h = render_text_surf(renderer, font_body, line, COLORS["fg"])
                if tex:
                    draw_texture(renderer, tex, 16, y, w, h)
                    from sdl2 import SDL_DestroyTexture
                    SDL_DestroyTexture(tex)
            y += TTF_FontHeight(font_body) + 4

        # Bottom hints
        hint = "A=color  B=up  D-pad=scroll  Start=quit"
        hint_tex, hw, hh = render_text_surf(renderer, font_hint, hint, COLORS["dim"])
        if hint_tex:
            draw_texture(renderer, hint_tex, 8, SCREEN_H - hh - 6, hw, hh)
            from sdl2 import SDL_DestroyTexture
            SDL_DestroyTexture(hint_tex)

        # Accent color indicator
        from sdl2 import SDL_RenderPresent
        draw_rect(renderer, SCREEN_W - 20, 6, 10, 10, COLORS[accent_colors[accent_idx]])
        SDL_RenderPresent(renderer)

        time.sleep(0.033)

    # Cleanup
    print("Quitting...")
    if title_tex:
        from sdl2 import SDL_DestroyTexture
        SDL_DestroyTexture(title_tex)
    TTF_CloseFont(font_title)
    TTF_CloseFont(font_body)
    TTF_CloseFont(font_hint)
    TTF_Quit()
    SDL_DestroyRenderer(renderer)
    SDL_DestroyWindow(window)
    SDL_QuitSubSystem(SDL_INIT_VIDEO | SDL_INIT_JOYSTICK | SDL_INIT_EVENTS)
    SDL_Quit()
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
