"""Shared test setup for oi-clients."""
from __future__ import annotations

import sys
import types
from ctypes import Structure, c_int


class _SDLKeysym(Structure):
    _fields_ = [("sym", c_int)]


class _SDLKeyboardEvent(Structure):
    _fields_ = [("keysym", _SDLKeysym)]


class _SDLJoyButtonEvent(Structure):
    _fields_ = [("button", c_int)]


class _SDLJoyHatEvent(Structure):
    _fields_ = [("hat", c_int), ("value", c_int)]


class SDL_Event(Structure):
    _fields_ = [
        ("type", c_int),
        ("key", _SDLKeyboardEvent),
        ("jbutton", _SDLJoyButtonEvent),
        ("jhat", _SDLJoyHatEvent),
    ]


if "sdl2" not in sys.modules:
    sdl2 = types.ModuleType("sdl2")
    sdl2.SDL_INIT_JOYSTICK = 1
    sdl2.SDL_INIT_EVENTS = 2
    sdl2.SDL_INIT_VIDEO = 4
    sdl2.SDL_JOYBUTTONDOWN = 10
    sdl2.SDL_JOYBUTTONUP = 11
    sdl2.SDL_JOYHATMOTION = 12
    sdl2.SDL_KEYDOWN = 13
    sdl2.SDL_QUIT = 14
    sdl2.SDLK_UP = 1000
    sdl2.SDLK_DOWN = 1001
    sdl2.SDLK_LEFT = 1002
    sdl2.SDLK_RIGHT = 1003
    sdl2.SDLK_RETURN = 1004
    sdl2.SDLK_BACKSPACE = 1005
    sdl2.SDLK_q = 1006
    sdl2.SDLK_ESCAPE = 1007
    sdl2.SDL_WINDOW_FULLSCREEN_DESKTOP = 0
    sdl2.SDL_WINDOW_SHOWN = 0
    sdl2.SDL_WINDOWPOS_CENTERED = 0
    sdl2.SDL_GameControllerName = lambda controller: b"stub"
    sdl2.SDL_GetTicks = lambda: 0
    sdl2.SDL_Init = lambda flags: 0
    sdl2.SDL_QuitSubSystem = lambda flags: None
    sdl2.SDL_Quit = lambda: None
    sdl2.SDL_NumJoysticks = lambda: 0
    sdl2.SDL_IsGameController = lambda i: False
    sdl2.SDL_GameControllerOpen = lambda i: object()
    sdl2.SDL_GameControllerClose = lambda c: None
    sdl2.SDL_JoystickOpen = lambda i: object()
    sdl2.SDL_JoystickClose = lambda j: None
    sdl2.SDL_JoystickInstanceID = lambda j: 1
    sdl2.SDL_PollEvent = lambda ptr: 0
    sdl2.SDL_Event = SDL_Event
    sdl2.SDL_CreateWindow = lambda *args, **kwargs: object()
    sdl2.SDL_DestroyWindow = lambda window: None
    sdl2.SDL_CreateRenderer = lambda *args, **kwargs: object()
    sdl2.SDL_DestroyRenderer = lambda renderer: None
    sdl2.SDL_SetRenderDrawColor = lambda *args, **kwargs: None
    sdl2.SDL_RenderClear = lambda *args, **kwargs: None
    sdl2.SDL_RenderFillRect = lambda *args, **kwargs: None
    sdl2.SDL_RenderPresent = lambda *args, **kwargs: None
    sdl2.SDL_RenderCopy = lambda *args, **kwargs: None
    sdl2.SDL_CreateTextureFromSurface = lambda *args, **kwargs: object()
    sdl2.SDL_FreeSurface = lambda *args, **kwargs: None
    sdl2.SDL_DestroyTexture = lambda *args, **kwargs: None
    sdl2.SDL_Color = lambda r, g, b, a: types.SimpleNamespace(r=r, g=g, b=b, a=a)
    sdl2.SDL_Rect = lambda x, y, w, h: types.SimpleNamespace(x=x, y=y, w=w, h=h)
    sys.modules["sdl2"] = sdl2

    sdlttf = types.ModuleType("sdl2.sdlttf")
    sdlttf.TTF_Init = lambda: 0
    sdlttf.TTF_Quit = lambda: None
    sdlttf.TTF_OpenFont = lambda *args, **kwargs: object()
    sdlttf.TTF_CloseFont = lambda *args, **kwargs: None
    sdlttf.TTF_RenderUTF8_Solid = lambda *args, **kwargs: None
    sys.modules["sdl2.sdlttf"] = sdlttf
