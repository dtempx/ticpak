#!/usr/bin/env python3
"""`ticpak init`: a new multi-file project - main.lua (the metadata header,
an entry stub that requires one module, TIC-80's default palette) and the
module it requires, game.lua. Never prompts: the header takes the same
defaults the interactive build offers for missing tags.
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


def lua_string(text):
    """text as a double-quoted Lua string literal."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def cart_text(meta):
    tags = "".join(f"-- {tag + ':':<8} {meta[tag]}\n" for tag in
                   ("title", "author", "desc", "site", "license", "version", "script"))
    return (f"{tags}\n"
            f'local {MODULE} = require "{MODULE}"\n'
            "\n"
            f"function BOOT() {MODULE}.init() end\n"
            f"function TIC() {MODULE}.update() {MODULE}.draw() end\n"
            "\n" + PALETTE)


def module_text(title):
    return f"""\
-- {MODULE}: a sample module. main.lua requires it, so ticpak inlines it into
-- the package. Add more modules beside it, and require each one in main.lua.

local M = {{}}

local TITLE = {lua_string(title)}
local t

local function centre(text, y, colour, small)
  local w = print(text, 0, -8, 0, false, 1, small)   -- off screen: just the width
  print(text, (240 - w) // 2, y, colour, false, 1, small)
end

function M.init()
  t = 0
end

function M.update()
  t = t + 1
end

function M.draw()
  cls(0)
  centre(TITLE, 50, 12)
  centre("edit {MODULE}.lua, then Ctrl+R", 62, 13, true)
  circ(120 + math.sin(t / 30) * 40, 86, 4, 6)
end

return M
"""


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
    meta = header_defaults({}, os.path.abspath(cart))
    for path, text in ((cart, cart_text(meta)), (module, module_text(meta["title"]))):
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    print(f"init: wrote {fwd(cart)} (the cart: header, entry stub, palette)"
          f" and {fwd(module)} (the module it requires)")
    print(f"header: title {meta['title']!r}, author {meta['author']!r},"
          f" site {meta['site']} - edit main.lua's header to change them")
    run = "tic80 main.lua" if folder == "." else f"cd {folder} && tic80 main.lua"
    print("hint: " + highlight(run) + " to run it in TIC-80 Pro (from the cart's folder)")
    print("hint: " + highlight("ticpak bundle" + ("" if folder == "." else " " + folder))
          + " to package it")
