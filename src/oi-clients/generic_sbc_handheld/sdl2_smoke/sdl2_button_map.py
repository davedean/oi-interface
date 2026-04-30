#!/usr/bin/env python3
"""Guided button mapping wizard for RG351P.

Shows one instruction at a time. You press the button it asks for.
Builds a mapping of logical names → SDL button numbers / hat values.
Auto-quits when done or after 10s idle per step.
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
    SDL_QUIT, SDL_KEYDOWN,
    SDL_JOYBUTTONDOWN, SDL_JOYHATMOTION,
    SDL_JOYDEVICEADDED,
    SDLK_q, SDLK_ESCAPE,
    SDL_Event, SDL_PollEvent,
    SDL_CreateWindow, SDL_DestroyWindow, SDL_Quit, SDL_Init, SDL_QuitSubSystem,
    SDL_GetError, SDL_RenderPresent,
    SDL_NumJoysticks, SDL_IsGameController,
    SDL_GameControllerOpen, SDL_GameControllerName, SDL_GameControllerClose,
)
from sdl2 import SDL_Color
from sdl2.sdlttf import TTF_Init, TTF_Quit, TTF_OpenFont, TTF_CloseFont, TTF_RenderText_Solid

SCREEN_W, SCREEN_H = 480, 320

BG = SDL_Color(10, 10, 20, 255)
FG = SDL_Color(220, 220, 220, 255)
ACCENT = SDL_Color(80, 200, 120, 255)
WARN = SDL_Color(230, 100, 60, 255)
DIM = SDL_Color(120, 120, 120, 255)

STEPS = [
    ("Press the RIGHT face button", "a", "button"),
    ("Press the BOTTOM face button", "b", "button"),
    ("Press the TOP face button", "x", "button"),
    ("Press the LEFT face button", "y", "button"),
    ("Press DPAD UP", "up", "hat_up"),
    ("Press DPAD DOWN", "down", "hat_down"),
    ("Press DPAD LEFT", "left", "hat_left"),
    ("Press DPAD RIGHT", "right", "hat_right"),
    ("Press START", "start", "button"),
    ("Press SELECT", "select", "button"),
    ("Press L1 (left shoulder)", "l1", "button"),
    ("Press R1 (right shoulder)", "r1", "button"),
]

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


class App:
    def __init__(self):
        self.font = None
        self.font_big = None
        self.font_small = None
        self.renderer = None
        self.window = None
        self.controller = None
        self.mapping = {}
        self.step_idx = 0
        self.step_start = time.time()
        self.flash_until = 0.0
        self.flash_color = SDL_Color(255, 255, 255, 255)

    def init(self) -> bool:
        if SDL_Init(SDL_INIT_VIDEO | SDL_INIT_JOYSTICK | SDL_INIT_EVENTS) != 0:
            print(f"SDL_Init failed: {SDL_GetError()}")
            return False
        if TTF_Init() != 0:
            print("TTF_Init failed")
            SDL_Quit()
            return False

        font_path = find_font()
        if not font_path:
            print("No font found")
            TTF_Quit(); SDL_Quit()
            return False

        self.font = load_font(font_path, 22)
        self.font_big = load_font(font_path, 32)
        self.font_small = load_font(font_path, 14)

        self.window = SDL_CreateWindow(
            b"Oi Button Map",
            SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
            SCREEN_W, SCREEN_H,
            SDL_WINDOW_FULLSCREEN_DESKTOP | SDL_WINDOW_SHOWN,
        )
        if not self.window:
            print(f"Window fail: {SDL_GetError()}")
            return False

        from sdl2 import SDL_CreateRenderer, SDL_DestroyRenderer
        self.renderer = SDL_CreateRenderer(self.window, -1, 0)
        if not self.renderer:
            print("Renderer fail")
            return False

        for i in range(SDL_NumJoysticks()):
            if SDL_IsGameController(i):
                self.controller = SDL_GameControllerOpen(i)
                name = SDL_GameControllerName(self.controller)
                print(f"Controller: {name.decode() if name else '???'}")
                break

        self.step_start = time.time()
        return True

    def draw_screen(self, instruction: str, sub: str, progress: str):
        r = self.renderer
        now = time.time()

        # Background flash on press
        if now < self.flash_until:
            draw_rect(r, 0, 0, SCREEN_W, SCREEN_H, self.flash_color)
        else:
            draw_rect(r, 0, 0, SCREEN_W, SCREEN_H, BG)

        # Progress
        tex, w, h = render_tex(r, self.font_small, progress, DIM)
        if tex:
            draw_texture(r, tex, 10, 10, w, h)
            from sdl2 import SDL_DestroyTexture
            SDL_DestroyTexture(tex)

        # Main instruction (big)
        tex, w, h = render_tex(r, self.font_big, instruction, ACCENT)
        if tex:
            x = (SCREEN_W - w) // 2
            y = (SCREEN_H - h) // 2 - 30
            draw_texture(r, tex, x, y, w, h)
            from sdl2 import SDL_DestroyTexture
            SDL_DestroyTexture(tex)

        # Sub hint
        tex, w, h = render_tex(r, self.font, sub, FG)
        if tex:
            x = (SCREEN_W - w) // 2
            y = (SCREEN_H - h) // 2 + 30
            draw_texture(r, tex, x, y, w, h)
            from sdl2 import SDL_DestroyTexture
            SDL_DestroyTexture(tex)

        # Timeout bar
        elapsed = now - self.step_start
        ratio = min(elapsed / 10.0, 1.0)
        bar_w = int(ratio * (SCREEN_W - 20))
        draw_rect(r, 10, SCREEN_H - 16, bar_w, 8, WARN)

        SDL_RenderPresent(r)

    def flash(self, color):
        self.flash_color = color
        self.flash_until = time.time() + 0.15

    def run(self) -> dict:
        running = True
        event = SDL_Event()
        done = False

        while running and not done:
            instruction, logical, kind = STEPS[self.step_idx]
            progress = f"Step {self.step_idx + 1} of {len(STEPS)}"
            sub = "Press the button now"

            # Check idle timeout for this step
            if time.time() - self.step_start > 10.0:
                # Skip this step
                self.mapping[logical] = None
                self.step_idx += 1
                self.step_start = time.time()
                if self.step_idx >= len(STEPS):
                    done = True
                continue

            # Draw
            self.draw_screen(instruction, sub, progress)

            # Poll events
            while SDL_PollEvent(ctypes.byref(event)) != 0:
                et = event.type
                if et == SDL_QUIT:
                    running = False
                elif et == SDL_KEYDOWN:
                    k = event.key.keysym.sym
                    if k in (SDLK_q, SDLK_ESCAPE):
                        running = False

                elif et == SDL_JOYBUTTONDOWN:
                    btn = event.jbutton.button
                    print(f"  [{logical}] = button {btn}")
                    self.mapping[logical] = {"type": "button", "value": btn}
                    self.flash(ACCENT)
                    self.step_idx += 1
                    self.step_start = time.time()
                    if self.step_idx >= len(STEPS):
                        done = True

                elif et == SDL_JOYHATMOTION:
                    val = event.jhat.value
                    if val == 0:
                        continue  # ignore center
                    print(f"  [{logical}] = hat {event.jhat.hat} val={val}")
                    self.mapping[logical] = {"type": "hat", "hat": event.jhat.hat, "value": val}
                    self.flash(ACCENT)
                    self.step_idx += 1
                    self.step_start = time.time()
                    if self.step_idx >= len(STEPS):
                        done = True

            time.sleep(0.02)

        # Write results before showing them
        out_path = "/storage/roms/ports/OiSmokeTest/button_map.json"
        try:
            import json
            with open(out_path, "w") as fh:
                json.dump(self.mapping, fh, indent=2)
        except Exception as exc:
            print(f"Could not write mapping: {exc}")

        # Show results screen briefly
        if done:
            result_lines = ["Mapping done!", ""]
            for logical, info in self.mapping.items():
                if info is None:
                    result_lines.append(f"{logical}: SKIPPED")
                elif info["type"] == "button":
                    result_lines.append(f"{logical}: btn {info['value']}")
                else:
                    result_lines.append(f"{logical}: hat {info['hat']} val={info['value']}")

            y = 10
            for line in result_lines[:18]:  # fit on screen
                color = ACCENT if "SKIPPED" not in line else WARN
                tex, w, h = render_tex(self.renderer, self.font_small, line, color)
                if tex:
                    draw_texture(self.renderer, tex, 10, y, w, h)
                    from sdl2 import SDL_DestroyTexture
                    SDL_DestroyTexture(tex)
                y += h + 4
            SDL_RenderPresent(self.renderer)
            time.sleep(5)

        return self.mapping

    def cleanup(self):
        if self.controller:
            SDL_GameControllerClose(self.controller)
        for f in (self.font, self.font_big, self.font_small):
            if f:
                TTF_CloseFont(f)
        TTF_Quit()
        if self.renderer:
            from sdl2 import SDL_DestroyRenderer
            SDL_DestroyRenderer(self.renderer)
        if self.window:
            SDL_DestroyWindow(self.window)
        SDL_QuitSubSystem(SDL_INIT_VIDEO | SDL_INIT_JOYSTICK | SDL_INIT_EVENTS)
        SDL_Quit()


def main():
    app = App()
    if not app.init():
        return 1
    mapping = app.run()
    app.cleanup()
    print("\n--- Button Map ---")
    print(mapping)
    return 0


if __name__ == "__main__":
    sys.exit(main())
