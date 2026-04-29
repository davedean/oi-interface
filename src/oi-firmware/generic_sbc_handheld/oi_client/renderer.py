#!/usr/bin/env python3
"""SDL2 text renderer for Oi handheld client.

Draws status bars, text cards, and button hints on a 480x320 screen.
"""

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass

os.environ.setdefault("PYSDL2_DLL_PATH", "/usr/lib")

import sdl2
from sdl2 import (
    SDL_INIT_VIDEO,
    SDL_WINDOW_FULLSCREEN_DESKTOP, SDL_WINDOW_SHOWN,
    SDL_WINDOWPOS_CENTERED,
    SDL_CreateWindow, SDL_DestroyWindow,
    SDL_CreateRenderer, SDL_DestroyRenderer,
    SDL_SetRenderDrawColor,
    SDL_RenderClear, SDL_RenderFillRect, SDL_RenderPresent, SDL_RenderCopy,
    SDL_Rect,
    SDL_Color,
    SDL_QuitSubSystem, SDL_Quit,
)
from sdl2.sdlttf import TTF_Init, TTF_Quit, TTF_OpenFont, TTF_CloseFont, TTF_RenderText_Solid


# Try a few system fonts
_FONT_CANDIDATES = [
    "/usr/share/retroarch-assets/fonts/OpenSans-Regular.ttf",
    "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
    "/usr/share/retroarch-assets/fonts/DejaVuSans.ttf",
]


def _find_font() -> str | None:
    for p in _FONT_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


@dataclass
class RenderColors:
    bg = SDL_Color(12, 12, 20, 255)
    card_bg = SDL_Color(30, 30, 45, 255)
    accent = SDL_Color(80, 200, 120, 255)
    warn = SDL_Color(230, 100, 60, 255)
    dim = SDL_Color(130, 130, 140, 255)
    fg = SDL_Color(220, 220, 230, 255)
    border = SDL_Color(60, 60, 80, 255)
    online = SDL_Color(80, 200, 120, 255)
    offline = SDL_Color(200, 60, 60, 255)


class Sdl2Renderer:
    """Fullscreen SDL2 renderer with TTF text support."""

    def __init__(self, width: int = 480, height: int = 320) -> None:
        self.width = width
        self.height = height
        self._window = None
        self._renderer = None
        self._font_title = None
        self._font_body = None
        self._font_hint = None

    def init(self) -> bool:
        if sdl2.SDL_Init(SDL_INIT_VIDEO) != 0:
            print(f"SDL_Init(video) failed")
            return False

        if TTF_Init() != 0:
            print("TTF_Init failed")
            sdl2.SDL_QuitSubSystem(SDL_INIT_VIDEO)
            sdl2.SDL_Quit()
            return False

        font_path = _find_font()
        if not font_path:
            print("No font found")
            TTF_Quit()
            sdl2.SDL_QuitSubSystem(SDL_INIT_VIDEO)
            sdl2.SDL_Quit()
            return False

        self._font_title = TTF_OpenFont(font_path.encode(), 20)
        self._font_body = TTF_OpenFont(font_path.encode(), 15)
        self._font_hint = TTF_OpenFont(font_path.encode(), 12)
        if not self._font_title or not self._font_body:
            print("Font load failed")
            return False

        self._window = SDL_CreateWindow(
            b"Oi",
            SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
            self.width, self.height,
            SDL_WINDOW_FULLSCREEN_DESKTOP | SDL_WINDOW_SHOWN,
        )
        if not self._window:
            print("Window creation failed")
            return False

        self._renderer = SDL_CreateRenderer(self._window, -1, 0)
        if not self._renderer:
            print("Renderer creation failed")
            return False

        return True

    def shutdown(self) -> None:
        for f in (self._font_title, self._font_body, self._font_hint):
            if f:
                TTF_CloseFont(f)
        TTF_Quit()
        if self._renderer:
            SDL_DestroyRenderer(self._renderer)
        if self._window:
            SDL_DestroyWindow(self._window)
        sdl2.SDL_QuitSubSystem(SDL_INIT_VIDEO)
        sdl2.SDL_Quit()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rect(self, x, y, w, h, color):
        SDL_SetRenderDrawColor(self._renderer, color.r, color.g, color.b, 255)
        rect = SDL_Rect(int(x), int(y), int(w), int(h))
        SDL_RenderFillRect(self._renderer, ctypes.byref(rect))

    def _text(self, font, text: str, color: SDL_Color) -> tuple:
        surf = TTF_RenderText_Solid(font, text.encode(), color)
        if not surf:
            return None, 0, 0
        tex = sdl2.SDL_CreateTextureFromSurface(self._renderer, surf)
        w, h = surf.contents.w, surf.contents.h
        sdl2.SDL_FreeSurface(surf)
        return tex, w, h

    def _draw_tex(self, tex, x, y, w, h):
        dst = SDL_Rect(int(x), int(y), int(w), int(h))
        SDL_RenderCopy(self._renderer, tex, None, ctypes.byref(dst))

    def _destroy_tex(self, tex):
        if tex:
            sdl2.SDL_DestroyTexture(tex)

    # ------------------------------------------------------------------
    # Public draw methods
    # ------------------------------------------------------------------

    def clear(self) -> None:
        SDL_SetRenderDrawColor(self._renderer, 12, 12, 20, 255)
        SDL_RenderClear(self._renderer)

    def present(self) -> None:
        SDL_RenderPresent(self._renderer)

    def draw_title(self, text: str, online: bool = False) -> None:
        c = RenderColors.online if online else RenderColors.offline
        # Status dot
        self._rect(12, 10, 8, 8, c)
        # Title text
        tex, w, h = self._text(self._font_title, text, RenderColors.fg)
        if tex:
            self._draw_tex(tex, 26, 8, w, h)
            self._destroy_tex(tex)

    def draw_card(self, title: str, body_lines: list[str], scroll_y: int = 0) -> None:
        # Card background
        card_x, card_y = 10, 42
        card_w = self.width - 20
        card_h = self.height - 90
        self._rect(card_x, card_y, card_w, card_h, RenderColors.card_bg)

        # Card title
        tex, w, h = self._text(self._font_title, title, RenderColors.accent)
        if tex:
            self._draw_tex(tex, card_x + 8, card_y + 6, w, h)
            self._destroy_tex(tex)

        # Body text (scrollable)
        y = card_y + 30 - scroll_y
        for line in body_lines:
            if y > card_y + card_h - 16:
                break
            if y >= card_y + 30 and line:
                tex, lw, lh = self._text(self._font_body, line, RenderColors.fg)
                if tex:
                    self._draw_tex(tex, card_x + 10, y, lw, lh)
                    self._destroy_tex(tex)
            y += 18

    def draw_hints(self, hints: str) -> None:
        tex, w, h = self._text(self._font_hint, hints, RenderColors.dim)
        if tex:
            self._draw_tex(tex, 10, self.height - 22, w, h)
            self._destroy_tex(tex)

    def draw_spinner(self, x: int, y: int, frame: int) -> None:
        """Draw a simple spinner animation at (x, y)."""
        dots = [".", "..", "..."]
        tex, w, h = self._text(self._font_body, dots[frame % 3], RenderColors.dim)
        if tex:
            self._draw_tex(tex, x, y, w, h)
            self._destroy_tex(tex)

    def draw_recording_indicator(self) -> None:
        """Draw a pulsing red recording dot in the top-right area."""
        import time
        pulse = abs((time.time() * 2) % 2 - 1)  # 0..1..0
        alpha = int(150 + 105 * pulse)
        red = SDL_Color(230, 60, 60, alpha)
        self._rect(self.width - 30, 12, 14, 14, red)
        # Draw a smaller white dot inside
        self._rect(self.width - 27, 15, 8, 8, SDL_Color(255, 255, 255, alpha))

    def effective_text_grid(self) -> tuple[int, int]:
        """Return approximate (cols, rows) at current font size."""
        return (40, 18)

