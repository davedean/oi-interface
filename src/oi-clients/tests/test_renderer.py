"""Tests for handheld renderer helpers."""
from __future__ import annotations

import sys
from pathlib import Path


client_src = Path(__file__).parent.parent / "generic_sbc_handheld"
if str(client_src) not in sys.path:
    sys.path.insert(0, str(client_src))

import oi_client.renderer as renderer_mod
from oi_client.renderer import Sdl2Renderer


def test_find_font_returns_first_existing_candidate(monkeypatch) -> None:
    seen = []

    def fake_isfile(path: str) -> bool:
        seen.append(path)
        return path == renderer_mod._FONT_CANDIDATES[1]

    monkeypatch.setattr(renderer_mod.os.path, "isfile", fake_isfile)

    assert renderer_mod._find_font() == renderer_mod._FONT_CANDIDATES[1]
    assert seen[:2] == renderer_mod._FONT_CANDIDATES[:2]


def test_wrap_text_splits_on_word_boundaries(monkeypatch) -> None:
    renderer = Sdl2Renderer()
    renderer._destroy_tex = lambda tex: None
    renderer._text = lambda font, text, color: (object(), len(text) * 10, 10)

    lines = renderer._wrap_text("alpha beta gamma", font=None, max_width=60)

    assert lines == ["alpha", "beta", "gamma"]


def test_wrap_text_forces_single_long_word_when_needed(monkeypatch) -> None:
    renderer = Sdl2Renderer()
    renderer._destroy_tex = lambda tex: None
    renderer._text = lambda font, text, color: (object(), 999, 10)

    lines = renderer._wrap_text("superlongword", font=None, max_width=20)

    assert lines == ["superlongword"]


def test_init_returns_false_when_no_font_found(monkeypatch) -> None:
    monkeypatch.setattr(renderer_mod.sdl2, "SDL_Init", lambda flags: 0)
    monkeypatch.setattr(renderer_mod, "TTF_Init", lambda: 0)
    monkeypatch.setattr(renderer_mod, "_find_font", lambda: None)
    renderer = Sdl2Renderer()

    assert renderer.init() is False



def test_draw_helpers_render_text_when_texture_exists(monkeypatch) -> None:
    renderer = Sdl2Renderer()
    renderer._font_title = object()
    renderer._font_hint = object()
    renderer._font_body = object()
    renderer._renderer = object()
    drawn = []
    destroyed = []
    rects = []
    renderer._text = lambda font, text, color: (object(), len(text), 10)
    renderer._draw_tex = lambda tex, x, y, w, h: drawn.append((x, y, w, h))
    renderer._destroy_tex = lambda tex: destroyed.append(tex)
    renderer._rect = lambda x, y, w, h, color: rects.append((x, y, w, h))

    renderer.draw_title("Oi", online=True)
    renderer.draw_hints("A=OK", version="abc123")
    renderer.draw_spinner(1, 2, 1)

    assert len(drawn) >= 4
    assert len(destroyed) >= 4
    assert rects  # status dot + version background



def test_effective_text_grid_is_fixed() -> None:
    renderer = Sdl2Renderer()
    assert renderer.effective_text_grid() == (40, 18)
