#!/usr/bin/env python3
import os, sys, time
os.environ["PYSDL2_DLL_PATH"] = "/usr/lib"
sys.path.insert(0, "/storage/roms/ports/PortMaster/exlibs")
import sdl2
from sdl2 import SDL_INIT_VIDEO, SDL_WINDOW_SHOWN, SDL_WINDOWPOS_CENTERED, SDL_WINDOW_FULLSCREEN_DESKTOP
from sdl2 import SDL_CreateWindow, SDL_CreateRenderer, SDL_SetRenderDrawColor, SDL_RenderClear, SDL_RenderPresent
from sdl2 import SDL_DestroyRenderer, SDL_DestroyWindow, SDL_Quit, SDL_Init, SDL_QuitSubSystem
print("init...")
SDL_Init(SDL_INIT_VIDEO)
print("create window...")
win = SDL_CreateWindow(b"test", SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED, 480, 320, SDL_WINDOW_FULLSCREEN_DESKTOP | SDL_WINDOW_SHOWN)
print("create renderer...")
rend = SDL_CreateRenderer(win, -1, 0)
print(f"renderer: {rend}")
print("draw frame...")
SDL_SetRenderDrawColor(rend, 200, 50, 50, 255)
SDL_RenderClear(rend)
SDL_RenderPresent(rend)
print("sleep 2...")
time.sleep(2)
print("cleanup...")
SDL_DestroyRenderer(rend)
SDL_DestroyWindow(win)
SDL_QuitSubSystem(SDL_INIT_VIDEO)
SDL_Quit()
print("OK")
