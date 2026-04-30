#!/usr/bin/env python3
"""SDL2 text renderer for Oi handheld client.

Draws status bars, text cards, and button hints, adapting to the active
fullscreen display size.
"""

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass

os.environ.setdefault("PYSDL2_DLL_PATH", "/usr/lib")

import sdl2
from sdl2 import (
    SDL_INIT_VIDEO,
    SDL_WINDOW_FULLSCREEN_DESKTOP,
    SDL_WINDOW_SHOWN,
    SDL_WINDOWPOS_CENTERED,
    SDL_CreateWindow,
    SDL_DestroyWindow,
    SDL_CreateRenderer,
    SDL_DestroyRenderer,
    SDL_SetRenderDrawColor,
    SDL_RenderClear,
    SDL_RenderFillRect,
    SDL_RenderPresent,
    SDL_RenderCopy,
    SDL_Rect,
    SDL_Color,
    SDL_QuitSubSystem,
    SDL_Quit,
)
from sdl2.sdlttf import TTF_Init, TTF_Quit, TTF_OpenFont, TTF_CloseFont, TTF_RenderUTF8_Solid


_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
    "/usr/share/retroarch-assets/fonts/DejaVuSansMono.ttf",
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

    BASE_WIDTH = 480
    BASE_HEIGHT = 320

    def __init__(self, width: int = 480, height: int = 320) -> None:
        self.width = width
        self.height = height
        self._window = None
        self._renderer = None
        self._font_title = None
        self._font_body = None
        self._font_hint = None
        self._font_title_size = 20
        self._font_body_size = 15
        self._font_hint_size = 12

    def init(self) -> bool:
        if sdl2.SDL_Init(SDL_INIT_VIDEO) != 0:
            print("SDL_Init(video) failed")
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

        self._window = SDL_CreateWindow(
            b"Oi",
            SDL_WINDOWPOS_CENTERED,
            SDL_WINDOWPOS_CENTERED,
            self.width,
            self.height,
            SDL_WINDOW_FULLSCREEN_DESKTOP | SDL_WINDOW_SHOWN,
        )
        if not self._window:
            print("Window creation failed")
            return False

        self._renderer = SDL_CreateRenderer(self._window, -1, 0)
        if not self._renderer:
            print("Renderer creation failed")
            return False

        self._refresh_output_size()
        scale = min(self.width / self.BASE_WIDTH, self.height / self.BASE_HEIGHT)
        self._font_title_size = max(18, int(round(20 * scale)))
        self._font_body_size = max(13, int(round(15 * scale)))
        self._font_hint_size = max(10, int(round(12 * scale)))

        self._font_title = TTF_OpenFont(font_path.encode(), self._font_title_size)
        self._font_body = TTF_OpenFont(font_path.encode(), self._font_body_size)
        self._font_hint = TTF_OpenFont(font_path.encode(), self._font_hint_size)
        if not self._font_title or not self._font_body:
            print("Font load failed")
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

    def _scaled_px(self, value: int) -> int:
        scale = min(self.width / self.BASE_WIDTH, self.height / self.BASE_HEIGHT)
        return max(1, int(round(value * scale)))

    def _refresh_output_size(self) -> None:
        getter = getattr(sdl2, "SDL_GetRendererOutputSize", None)
        if not getter or not self._renderer:
            return
        out_w = ctypes.c_int()
        out_h = ctypes.c_int()
        if getter(self._renderer, ctypes.byref(out_w), ctypes.byref(out_h)) == 0:
            if out_w.value > 0:
                self.width = out_w.value
            if out_h.value > 0:
                self.height = out_h.value

    def center_x(self, object_width: int) -> int:
        return max(0, (self.width - object_width) // 2)

    def spinner_y(self) -> int:
        return max(self._scaled_px(140), int(self.height * 0.56))

    def character_box_rect(self) -> tuple[int, int, int, int]:
        box_x = self._scaled_px(10)
        box_y = self._scaled_px(34)
        box_w = min(self.width - (box_x * 2), max(self._scaled_px(160), int(self.width * 0.34)))
        box_h = max(self._scaled_px(26), self._font_hint_size + self._scaled_px(8))
        return box_x, box_y, box_w, box_h

    def line_height(self) -> int:
        return max(self._scaled_px(18), self._font_body_size + self._scaled_px(3))

    def _rect(self, x, y, w, h, color):
        SDL_SetRenderDrawColor(self._renderer, color.r, color.g, color.b, 255)
        rect = SDL_Rect(int(x), int(y), int(w), int(h))
        SDL_RenderFillRect(self._renderer, ctypes.byref(rect))

    def _text(self, font, text: str, color: SDL_Color) -> tuple:
        surf = TTF_RenderUTF8_Solid(font, text.encode("utf-8"), color)
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

    def clear(self) -> None:
        SDL_SetRenderDrawColor(self._renderer, 12, 12, 20, 255)
        SDL_RenderClear(self._renderer)

    def present(self) -> None:
        SDL_RenderPresent(self._renderer)

    def draw_title(self, text: str, online: bool = False) -> None:
        c = RenderColors.online if online else RenderColors.offline
        dot = max(8, self._scaled_px(8))
        dot_x = self._scaled_px(12)
        dot_y = self._scaled_px(10)
        self._rect(dot_x, dot_y, dot, dot, c)
        tex, w, h = self._text(self._font_title, text, RenderColors.fg)
        if tex:
            self._draw_tex(tex, dot_x + dot + self._scaled_px(6), self._scaled_px(8), w, h)
            self._destroy_tex(tex)

    def draw_card(self, title: str, body_lines: list[str], scroll_y: int = 0, card_y: int | None = None, ascii_bg_lines: list[str] | None = None) -> None:
        card_x = self._scaled_px(10)
        card_y = card_y if card_y is not None else self._scaled_px(62)
        card_w = self.width - (card_x * 2)
        card_h = max(self._scaled_px(140), self.height - self._scaled_px(90))
        line_h = self.line_height()
        self._rect(card_x, card_y, card_w, card_h, RenderColors.card_bg)

        if ascii_bg_lines:
            ay = card_y + self._scaled_px(42)
            ax = card_x + max(self._scaled_px(10), card_w - self._scaled_px(220))
            for line in ascii_bg_lines:
                tex, lw, lh = self._text(self._font_body, line, RenderColors.dim)
                if tex:
                    self._draw_tex(tex, ax, ay, lw, lh)
                    self._destroy_tex(tex)
                ay += line_h

        tex, w, h = self._text(self._font_title, title, RenderColors.accent)
        if tex:
            self._draw_tex(tex, card_x + self._scaled_px(8), card_y + self._scaled_px(6), w, h)
            self._destroy_tex(tex)

        y = card_y + self._scaled_px(30) - scroll_y
        body_margin = self._scaled_px(10)
        bottom_pad = self._scaled_px(16)
        for line in body_lines:
            if y > card_y + card_h - bottom_pad:
                break
            if y >= card_y + self._scaled_px(30) and line:
                wrapped = self._wrap_text(line, self._font_body, card_w - (body_margin * 2))
                for wline in wrapped:
                    if y > card_y + card_h - bottom_pad:
                        break
                    tex, lw, lh = self._text(self._font_body, wline, RenderColors.fg)
                    if tex:
                        self._draw_tex(tex, card_x + body_margin, y, lw, lh)
                        self._destroy_tex(tex)
                    y += line_h
                continue
            y += line_h

    def _wrap_text(self, text: str, font, max_width: int) -> list[str]:
        if not text or not text.strip():
            return [text] if text else []
        words = text.split()
        lines = []
        current_line = []

        for word in words:
            test_line = current_line + [word]
            test_text = " ".join(test_line)
            tex, w, _ = self._text(font, test_text, RenderColors.fg)
            if tex:
                fits = w <= max_width
                self._destroy_tex(tex)
            else:
                fits = False

            if fits:
                current_line = test_line
            else:
                if current_line:
                    lines.append(" ".join(current_line))
                if not current_line:
                    lines.append(word)
                    current_line = []
                else:
                    current_line = [word]

        if current_line:
            lines.append(" ".join(current_line))
        return lines if lines else [text]

    def draw_hints(self, hints: str, version: str = "") -> None:
        tex, w, h = self._text(self._font_hint, hints, RenderColors.dim)
        if tex:
            self._draw_tex(tex, self._scaled_px(10), self.height - self._scaled_px(22), w, h)
            self._destroy_tex(tex)

        if version:
            tex2, w2, h2 = self._text(self._font_hint, version, RenderColors.dim)
            self._rect(
                self.width - w2 - self._scaled_px(14),
                self.height - self._scaled_px(24),
                w2 + self._scaled_px(8),
                h2 + self._scaled_px(4),
                RenderColors.card_bg,
            )
            if tex2:
                self._draw_tex(tex2, self.width - w2 - self._scaled_px(10), self.height - self._scaled_px(22), w2, h2)
                self._destroy_tex(tex2)

    def draw_spinner(self, x: int, y: int, frame: int) -> None:
        dots = [".", "..", "..."]
        tex, w, h = self._text(self._font_body, dots[frame % 3], RenderColors.dim)
        if tex:
            self._draw_tex(tex, x, y, w, h)
            self._destroy_tex(tex)

    def draw_recording_indicator(self) -> None:
        import time

        pulse = abs((time.time() * 2) % 2 - 1)
        alpha = int(150 + 105 * pulse)
        red = SDL_Color(230, 60, 60, alpha)
        dot_outer = self._scaled_px(14)
        dot_inner = self._scaled_px(8)
        dot_x = self.width - self._scaled_px(30)
        dot_y = self._scaled_px(12)
        self._rect(dot_x, dot_y, dot_outer, dot_outer, red)
        self._rect(dot_x + self._scaled_px(3), dot_y + self._scaled_px(3), dot_inner, dot_inner, SDL_Color(255, 255, 255, alpha))

    def effective_text_grid(self) -> tuple[int, int]:
        cols = max(20, int(round(40 * (self.width / self.BASE_WIDTH))))
        rows = max(8, int(round(18 * (self.height / self.BASE_HEIGHT))))
        return cols, rows
