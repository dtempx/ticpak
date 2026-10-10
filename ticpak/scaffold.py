#!/usr/bin/env python3
"""`ticpak init`: a new multi-file project - main.lua (the metadata header,
an entry stub that requires one module, TIC-80's default palette) and the
module it requires, game.lua. Never prompts: the header has placeholders
for the tags only the user can fill in.
"""
import os
import sys

from .console import fwd, highlight, show
from .header import header_defaults

MODULE = "game"

# TIC-80's default palette (sweetie-16): a cart needs one asset section
# before anything has been drawn, and ticpak packages none without one.
PALETTE = ("-- <PALETTE>\n"
           "-- 000:1a1c2c5d275db13e53ef7d57ffcd75a7f07038b76425717929366f3b5dc941a6f6"
           "73eff7f4f4f494b0c2566c86333c57\n"
           "-- </PALETTE>\n")


# Placeholders for the tags only the user can fill in (TIC-80's own `new`-cart
# ones, and ticpak's title and author): check reports them, and the
# interactive build asks for them.
PLACEHOLDERS = {
    "title": "my game",
    "author": "your name or email",
    "desc": "short description",
    "site": "website link",
    "license": "MIT License (change this to your license of choice)",
}


def cart_text(meta):
    tags = "".join(f"-- {tag + ':':<8} {meta[tag]}\n" for tag in
                   ("title", "author", "desc", "site", "license", "version", "script"))
    return (f"{tags}\n"
            f'require "{MODULE}"\n'
            "\n"
            "function BOOT()\n"
            f"  {MODULE}.init()\n"
            "end\n"
            "\n"
            "function TIC()\n"
            f"  {MODULE}.update()\n"
            f"  {MODULE}.draw()\n"
            "end\n"
            "\n" + PALETTE)


def module_text():
    return f"""{MODULE} = {{}}

local TRAIL = {{2, 14, 15}}
local t

local function set_color(slot, rgb)
  local addr = 0x3FC0 + slot * 3
  poke(addr, rgb >> 16)
  poke(addr + 1, (rgb >> 8) & 0xFF)
  poke(addr + 2, rgb & 0xFF)
end

local function print_center(text, y, color, small)
  local w = print(text, 0, -8, 0, false, 1, small)
  print(text, (240 - w) // 2, y, color, false, 1, small)
end

local function dot_x(frame)
  return 120 + math.sin(frame / 15) * 60
end

function {MODULE}.init()
  t = 0
  set_color(3, 0xff9cab)
  set_color(14, 0x73283a)
  set_color(15, 0x3e161d)
end

function {MODULE}.update()
  t = t + 1
end

function {MODULE}.draw()
  cls(0)
  print_center("Edit {MODULE}.lua, then hit CTRL+R", 62, 13, true)
  for i = #TRAIL, 1, -1 do
    circ(dot_x(t - i * 2), 86, 4, TRAIL[i])
  end
  circ(dot_x(t), 86, 4, 2)
  circ(dot_x(t), 86, 1, 3)
end
"""


# What a project's .gitignore needs: ticpak's outputs, and the cache TIC-80
# keeps in the folder `ticpak run` gives it (--fs)
IGNORES = ("*.tic", "dist/", ".local/")


def add_ignores(path):
    """Add each of IGNORES the .gitignore at path lacks (made if missing);
    returns those added."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        text = ""
    have = {line.strip() for line in text.splitlines()}
    added = [p for p in IGNORES if p not in have]
    if added:
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            if text and not text.endswith("\n"):
                f.write("\n")
            f.write("".join(p + "\n" for p in added))
    return added


def init_project(folder=None):
    """Write main.lua and game.lua into folder (default: the current folder;
    made if missing). Stops, writing nothing, if there is a cart already
    (main.lua or src/main.lua) or game.lua is taken."""
    folder = folder or "."
    if os.path.isfile(folder):
        sys.exit(f"ticpak: init takes a folder, not a file: {show(folder)}")
    cart = os.path.join(folder, "main.lua")
    module = os.path.join(folder, MODULE + ".lua")
    for existing in (cart, os.path.join(folder, "src", "main.lua")):
        if os.path.isfile(existing):
            sys.exit(f"ticpak: {fwd(existing)} already exists - init starts a new"
                     " project only (ticpak bundle packages this one)")
    if os.path.exists(module):
        sys.exit(f"ticpak: {fwd(module)} already exists - init would overwrite it")
    os.makedirs(folder, exist_ok=True)
    meta = {**header_defaults({}, os.path.abspath(cart)), **PLACEHOLDERS}
    for path, text in ((cart, cart_text(meta)), (module, module_text())):
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    print(f"init: wrote {fwd(cart)} (the cart: header, entry stub, palette)"
          f" and {fwd(module)} (the module it requires)")
    ignore = os.path.join(folder, ".gitignore")
    added = add_ignores(ignore)
    if added:
        print(f"init: {fwd(ignore)} ignores {', '.join(added)}")
    print(f"header: {', '.join(PLACEHOLDERS)} are placeholders - fill them in"
          " before packaging")
    run = "ticpak run" + ("" if folder == "." else " " + folder)
    print("hint: " + highlight(run) + " to run it in TIC-80")
