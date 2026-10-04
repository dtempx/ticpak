#!/usr/bin/env python3
"""Write the sample TIC-80 text carts the minify-option tests run on.

Each cart is a metadata header + a code body from code/ + asset sections in
one of several layouts (ASSET_LAYOUTS). The asset data is deterministic
pseudo-random hex in TIC-80's real text-cart line formats, so a rerun writes
identical files. Outputs (committed, regenerate after editing code/):

    samples/<name>.lua     one cart per entry in SAMPLES
    project/main.lua       the entry stub of the ticpak integration project

    python tests/options/make_samples.py
"""
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))

# Hex characters per data line, by section, as TIC-80 Pro writes them.
LINE_HEX = {
    "TILES": 64, "SPRITES": 64,       # 8x8 sprite, 4 bpp
    "MAP": 480,                       # 240 cells
    "WAVES": 32,                      # 32 4-bit samples
    "SFX": 132,
    "PATTERNS": 384,
    "TRACKS": 102,
    "PALETTE": 96,                    # 16 RGB colours
    "FLAGS": 512,
    "SCREEN": 240,                    # 240 px at 4 bpp, 136 lines
}

# section name (with optional bank digit) -> line numbers to fill
ASSET_LAYOUTS = {
    "none": [],
    "bank0": [("TILES", [1, 2, 17]), ("SPRITES", [0, 1]), ("MAP", [0, 1]),
              ("WAVES", [0, 1]), ("SFX", [0]), ("PATTERNS", [0]),
              ("TRACKS", [0]), ("PALETTE", [0])],
    "banks": [("TILES", [1]), ("TILES1", [0, 5]), ("MAP2", [0]),
              ("SPRITES7", [3]), ("FLAGS", [0]), ("PALETTE", [0]),
              ("PALETTE1", [0])],
    "screen": [("TILES", [1]), ("PALETTE", [0]), ("SCREEN", list(range(136)))],
    "minimal": [("PALETTE", [0])],
}

# name -> (code body, asset layout, header extras, line ending)
SAMPLES = {
    "basic": ("basic.lua", "bank0", {"saveid": "minitest_basic"}, "\n"),
    "basic_crlf": ("basic.lua", "bank0", {}, "\r\n"),
    "bundle": ("bundle.lua", "banks", {"saveid": "minitest_bundle"}, "\n"),
    "syntax": ("syntax.lua", "none", {}, "\n"),
    "nominify": ("nominify.lua", "screen", {"input": "gamepad"}, "\n"),
    "markers": ("markers.lua", "minimal", {}, "\n"),
    "nominify_funcs": ("nominify_funcs.lua", "bank0", {}, "\n"),
    "nominify_modules": ("nominify_modules.lua", "banks", {}, "\n"),
    # "_note" adds a plain comment line to the header block (not a tag)
    "nominify_main": ("nominify_main.lua", "minimal",
                      {"_note": "NOMINIFY: this whole cart ships as written"}, "\n"),
}


def header(title, extras):
    extras = dict(extras)
    note = extras.pop("_note", None)
    tags = [("title", title), ("author", "minify-option tests"),
            ("desc", f"sample cart '{title}' for tests/options"),
            ("site", "https://tic80.com"), ("license", "MIT License"),
            ("version", "0.1"), ("script", "lua")] + list(extras.items())
    return ("".join(f"-- {k + ':':<7} {v}\n" for k, v in tags)
            + (f"-- {note}\n" if note else ""))


def assets(layout, rng):
    out = []
    for section, lines in ASSET_LAYOUTS[layout]:
        width = LINE_HEX[section.rstrip("0123456789")]
        out.append(f"-- <{section}>\n")
        for n in lines:
            out.append(f"-- {n:03d}:" + "".join(rng.choice("0123456789abcdef")
                                                for _ in range(width)) + "\n")
        out.append(f"-- </{section}>\n\n")
    return "".join(out)


def cart(title, code_file, layout, extras, seed):
    code = open(os.path.join(HERE, "code", code_file), encoding="utf-8").read()
    rng = random.Random(seed)
    body = header(title, extras) + "\n" + code
    tail = assets(layout, rng)
    return body + ("\n" + tail if tail else "")


def write(path, text, newline="\n"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text.replace("\n", newline))
    print(f"wrote {os.path.relpath(path, HERE)}")


def main():
    for i, (name, (code_file, layout, extras, nl)) in enumerate(SAMPLES.items()):
        write(os.path.join(HERE, "samples", f"{name}.lua"),
              cart(name, code_file, layout, extras, seed=i), nl)
    write(os.path.join(HERE, "project", "main.lua"),
          cart("project", "project_main.lua", "bank0",
               {"saveid": "minitest_project"}, seed=99))


if __name__ == "__main__":
    main()
