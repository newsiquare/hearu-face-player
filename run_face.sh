#!/usr/bin/env bash
# Launch the companion face player.
cd "$(dirname "$0")"

# --- display backend ---
# Bookworm defaults to Wayland; SDL2 usually auto-detects. If you see a black
# screen or wrong placement, force one of these:
# export SDL_VIDEODRIVER=wayland
# export SDL_VIDEODRIVER=x11

# --- options ---
export FACE_TCP=1          # command hook on 127.0.0.1:8765 (your pipeline talks to it)
# export FACE_WINDOWED=1   # run in a window instead of fullscreen (for testing)
# export FACE_DEBUG=1      # show the state name in the corner

exec python3 face_player.py
