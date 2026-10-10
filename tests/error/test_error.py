#!/usr/bin/env python3
"""Tests for `ticpak decode`: runtime errors from packaged carts, decoded back
to the sources.

    python tests/error/test_error.py
    python tests/error/test_error.py -k Decode

Each case in CASES is a small project (main.lua and modules) with one bug.
The error it raises is made twice under real Lua 5.3 (lupa), against a stub
of the TIC-80 API:

  - from the sources as written, each file loaded under its own name, which
    gives the error as it should read: `enemies.lua:13: attempt to index ...`;
  - from the bundle as `ticpak bundle` builds it (bundle.build, no TIC-80
    run), loaded as TIC-80 loads it (luaL_loadstring: the chunk is named
    after the code's first line) and its traceback made as TIC-80's message
    handler makes it (luaL_traceback), which gives
    `[string "-- title: ..."]:11: attempt to index ... (field 'd')`.

`ticpak decode` must turn the second into the first, for every minify preset:
each line and name in the message and in every traceback frame.

  Map      the .minify.json a folder build writes (format 2): segments, the
           uses of each renamed variable, the code's hash
  Decode   each case under each preset, decoded == written
  Input    text copied from TIC-80's console rejoined, a log's last error,
           TIC-80's output decoded as `ticpak test` reads it
  Command  `ticpak decode`: -e, stdin, the clipboard and --log, the map file
           or a rebuild, a cart that no longer matches its sources, no
           cart, no location, the options it rejects

Needs lupa (pip install lupa); without it Decode and Command skip.
"""
import contextlib
import functools
import io
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)                    # the ticpak package, installed or not
from ticpak import minify as M  # noqa: E402
from ticpak import bundle, cli, errors  # noqa: E402

try:
    from lupa import lua53
except ImportError:
    lua53 = None
NEEDS_LUA = unittest.skipIf(lua53 is None, "needs lupa (pip install lupa)")

HEADER = """-- title:  Error Test
-- author: ticpak tests
-- desc:   one bug per case
-- site:   https://example.com
-- license: MIT License
-- version: 0.1
-- script: lua
"""
ASSETS = """
-- <TILES>
-- 001:122b598615dcbe810beacd557705a54b5edbbbe5ce7f8fbeebef7a58f99d96fb
-- </TILES>
"""

# name -> {file: source}; main.lua gets HEADER above and ASSETS below
CASES = {
    # a field of nil, in a local function a module's function calls
    "index a field": {
        "main.lua": """
local enemies = require("enemies")

local frame = 0

function TIC()
  cls(0)
  frame = frame + 1
  enemies.update_all(frame)
  enemies.draw_all()
end
""",
        "enemies.lua": """local M = {}

local list = {}

local function spawn(x, y)
  local enemy = {x = x, y = y, speed = 1, target = nil}
  list[#list + 1] = enemy
  return enemy
end

local function chase(enemy)
  -- target is never set
  local dx = enemy.target.x - enemy.x
  enemy.x = enemy.x + dx * enemy.speed
end

function M.update_all(frame)
  if frame == 1 then
    spawn(10, 20)
    spawn(30, 40)
  end
  for i = 1, #list do
    chase(list[i])
  end
end

function M.draw_all()
  for i = 1, #list do
    local enemy = list[i]
    spr(1, enemy.x, enemy.y)
  end
end

return M
""",
    },
    # a nil local called; short names reused all over the module
    "call a local": {
        "main.lua": """
local input = require("input")
local player = {x = 0, y = 0, vy = 0}

function TIC()
  input.handle(player, btn(4) and "jump" or "dash")
  spr(1, player.x, player.y)
end
""",
        "input.lua": """local M = {}

local handlers = {}

function handlers.jump(p)
  local speed = 3
  p.vy = -speed
end

function handlers.left(p)
  local speed = 1
  p.x = p.x - speed
end

function M.handle(p, action)
  local count = 0
  for name in pairs(handlers) do
    count = count + #name
  end
  local handler = handlers[action]
  handler(p)
  return count
end

return M
""",
    },
    # arithmetic on a nil parameter, two calls deep in one module
    "arithmetic on a parameter": {
        "main.lua": """
local combat = require("combat")
local hero = {hp = 10}
local sword = {power = 2}
local stick = {}

function TIC()
  combat.hit(hero, sword)
  combat.hit(hero, stick)
  print(hero.hp)
end
""",
        "combat.lua": """local M = {}

local function damage(target, amount)
  local before = target.hp
  target.hp = before - amount
  return before - target.hp
end

function M.hit(target, weapon)
  local dealt = damage(target, weapon.power)
  return dealt + 0
end

return M
""",
    },
    # error() in a module, its message carrying the position
    "error()": {
        "main.lua": """
local state = require("state")

function TIC()
  state.enter("title")
  state.enter("credits")
end
""",
        "state.lua": """local M = {}

local known = {title = true, play = true}

function M.enter(name)
  if not known[name] then
    error("unknown state: " .. name)
  end
  M.current = name
end

return M
""",
    },
    # a method the object's class does not have
    "call a method": {
        "main.lua": """
local ui = require("ui")
local buttons = {ui.Button.new("start"), ui.Button.new("quit")}

function TIC()
  cls(0)
  ui.draw_all(buttons)
end
""",
        "ui.lua": """local M = {}

local Button = {}
Button.__index = Button
M.Button = Button

function Button.new(label)
  return setmetatable({label = label, width = #label * 6}, Button)
end

function Button:draw(x, y)
  rect(x, y, self.width, 8, 1)
  print(self.label, x + 1, y + 1)
end

function M.draw_all(buttons)
  for i = 1, #buttons do
    buttons[i]:draw(4, i * 10)
    buttons[i]:render_shadow(4, i * 10)
  end
end

return M
""",
    },
    # a misspelt global function: whole-program mode renames globals
    "call a global": {
        "main.lua": """
local world = require("world")

function update_world(dt)
  world.tick(dt)
end

function TIC()
  update_world(1)
  draw_wrld()
end
""",
        "world.lua": """local M = {}

local time_passed = 0

function M.tick(dt)
  time_passed = time_passed + dt
end

return M
""",
    },
}

PRESETS = {
    "none": frozenset(),
    "comments": M.parse_options("comments"),
    "rename-vars": M.parse_options("rename-vars"),       # line breaks kept
    "default": M.DEFAULT_OPTIONS,
    "max": M.ALL_OPTIONS,
}

# Lua: a stand-in TIC-80 API, then run a chunk (load) and TIC a few times,
# returning the error and traceback a message handler made.
RUNNER = r"""
local api = {"cls", "spr", "print", "rect", "rectb", "circ", "line", "pix",
             "map", "sfx", "music", "trace", "btnp", "time"}
for _, f in ipairs(api) do _G[f] = function() return 0 end end
function btn() return false end
return function(load_main)
  local ok, err = xpcall(function()
    load_main()
    for _ = 1, 3 do TIC() end
  end, function(m) return debug.traceback(m, 2) end)
  return not ok and err or nil
end
"""


def project(case):
    """{file: text}: CASES[case] with main.lua's header and asset sections."""
    files = dict(CASES[case])
    files["main.lua"] = HEADER + files["main.lua"] + ASSETS
    return files


def write_project(root, files):
    for name, text in files.items():
        with open(os.path.join(root, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    return os.path.join(root, "main.lua")


def trim(trace):
    """A traceback cut where it leaves the cart: at the runner's xpcall,
    where TIC-80's C code would be."""
    lines = trace.replace("\r\n", "\n").split("\n")
    for i, ln in enumerate(lines):
        if "'xpcall'" in ln or '"<python>"' in ln:
            return "\n".join(lines[:i])
    return "\n".join(lines)


def run_written(files):
    """The error the sources raise as written: each file its own chunk
    (main.lua:12, enemies.lua:13), required modules as package.loaded holds
    them."""
    rt = lua53.LuaRuntime(unpack_returned_tuples=True)
    run = rt.execute(RUNNER)
    g = rt.globals()
    for name, text in files.items():
        if name != "main.lua":
            fn = g.load(text, "@" + name)
            g.package.preload[name[:-4].replace("/", ".")] = fn
    main = g.load(files["main.lua"], "@main.lua")
    return trim(run(main))


def run_packaged(code):
    """The error the bundle raises in TIC-80: loaded with luaL_loadstring,
    so its chunk is named after its first line."""
    rt = lua53.LuaRuntime(unpack_returned_tuples=True)
    run = rt.execute(RUNNER)
    main = rt.globals().load(code, code)
    return trim(run(main))


class Built:
    """A case built with some options in a temp folder: the Target (-o
    X.lua, the bundle beside main.lua), the Built, and its code."""

    def __init__(self, case, options, root):
        self.files = project(case)
        self.main = write_project(root, self.files)
        self.t = bundle.Target(self.main, "game", os.path.join(root, "game.lua"))
        with contextlib.redirect_stdout(io.StringIO()):
            self.b = bundle.build(self.t, options)
        self.code = self.b.code
        with open(self.t.lua, "w", encoding="utf-8", newline="\n") as f:
            f.write(self.b.code + self.b.chunks)


@functools.lru_cache(maxsize=None)
def built(case, preset):
    """(packaged error, decoded error, written error) for a case and preset."""
    root = tempfile.mkdtemp(prefix="ticpak-error-")
    try:
        bl = Built(case, PRESETS[preset], root)
        packaged = run_packaged(bl.code)
        dec = errors.Decoder(bundle.map_doc(bl.b), bl.code)
        decoded = errors.decode(packaged, dec)[0]
        return packaged, decoded, run_written(bl.files)
    finally:
        shutil.rmtree(root, ignore_errors=True)


LOCATION_RE = re.compile(r"([\w/]+\.lua):(\d+)(?:-(\d+))?")


def compare(decoded, written):
    """Does the decoded error read as the written one? Each location must be
    the written one, or a range holding it: a line that calls the same
    function twice can't say which call it was. Returns the problem, or
    None; and how many locations were ranges."""
    a, b = decoded.split("\n"), written.split("\n")
    if len(a) != len(b):
        return f"{len(a)} lines, not {len(b)}", 0
    ranges = 0
    for n, (x, y) in enumerate(zip(a, b), 1):
        if LOCATION_RE.split(x)[::4] != LOCATION_RE.split(y)[::4]:
            return f"line {n}: {x!r} is not {y!r}", ranges
        for m, w in zip(LOCATION_RE.finditer(x), LOCATION_RE.finditer(y)):
            lo, hi = int(m.group(2)), int(m.group(3) or m.group(2))
            if m.group(1) != w.group(1) or not lo <= int(w.group(2)) <= hi:
                return f"line {n}: {m.group(0)} does not hold {w.group(0)}", ranges
            if n == 1 and lo != hi:
                return f"line 1: {m.group(0)}, not the error's own line {w.group(0)}", ranges
            ranges += lo != hi
    return None, ranges


def tic_file(path, code):
    """A .tic holding just the code, in check.py's chunk format (CODE is type
    5): what TIC-80 saves, as far as ticpak reads it."""
    data = code.encode("utf-8")
    with open(path, "wb") as f:
        f.write(struct.pack("<I", 5 | len(data) << 8) + data)


def console_copy(text, width=40):
    """The text printed to TIC-80's console then copied from it (select all,
    Ctrl+C): console.c's consolePrintOffset lays it out in rows of `width`,
    moving a word that would reach the edge to the next row, and
    getSelectionText puts a newline between rows."""
    rows, x = [[]], 0

    def wrap(c):
        return c == "|" or c.isspace()
    for i, c in enumerate(text):
        if c == "\n":
            rows.append([])
            x = 0
            continue
        if not wrap(c):
            word = 0
            while i + word < len(text) and not wrap(text[i + word]):
                word += 1
            if 0 < width - word <= x:
                rows.append([])
                x = 0
        rows[-1].append(c)
        x += 1
        if x >= width:
            rows.append([])
            x = 0
    return "\n".join("".join(r) for r in rows)


def setUpModule():
    import warnings
    warnings.simplefilter("ignore", ResourceWarning)


class TestInput(unittest.TestCase):
    """Where the error text comes from: TIC-80's console (unwrap), a log
    (last_error), its output as it runs (Stream)."""

    def test_unwrap(self):
        for text in ("", "short", "x" * 40, "x" * 40 + "\nnext", "x" * 39 + " y",
                     "a | " * 30, "word " * 20 + "\n\n" + "y" * 85,
                     '[string "-- title:  My Game..."]:37: attempt to index a nil'
                     " value (field 'xy')\nstack traceback:\n\t[C]: in ?"):
            with self.subTest(text=text):
                self.assertEqual(errors.unwrap(console_copy(text)), text)

    def test_unwrap_leaves_long_lines(self):
        text = "x" * 41 + "\n" + "y" * 40 + "\nz"
        self.assertEqual(errors.unwrap(text), text)

    @NEEDS_LUA
    def test_unwrap_cases(self):
        for case in CASES:
            for preset in ("none", "max"):
                with self.subTest(case=case, preset=preset):
                    packaged = built(case, preset)[0]
                    self.assertEqual(errors.unwrap(console_copy(packaged)), packaged)

    def test_last_error(self):
        first = '[string "-- title: a"]:3: first\nstack traceback:\n\t[C]: in ?'
        other = '[string "helper"]:9: not ours'
        last = '[string "-- title: a"]:5: second\nstack traceback:\n\t[C]: in ?'
        log = "\n".join(["boot", first, "trace", last, other, "after", ""])
        self.assertEqual(errors.last_error(log), other)
        self.assertEqual(errors.last_error(log, lambda c: c.startswith("-- title")), last)
        self.assertEqual(errors.last_error(log, lambda c: False), other)
        self.assertIsNone(errors.last_error("no errors\nhere"))

    @NEEDS_LUA
    def test_stream(self):
        """Output passes through as it is, each error decoded once whole:
        when other output follows, or when the output pauses."""
        root = tempfile.mkdtemp(prefix="ticpak-error-")
        self.addCleanup(shutil.rmtree, root, True)
        bl = Built("index a field", M.ALL_OPTIONS, root)
        dec = errors.Decoder(bundle.map_doc(bl.b), bl.code)
        packaged = run_packaged(bl.code)
        decoded = errors.decode(packaged, dec)[0]
        note = errors.source_note(root, ("enemies.lua", 13))
        made = []

        def decoder():
            made.append(1)
            return dec
        for tail in ("after\n", ""):
            with self.subTest(tail=tail):
                out = []
                s = errors.Stream(decoder, root, out.append)
                text = "loaded!\r\ntrace " + "\n" + packaged + "\n" + tail
                for i in range(0, len(text), 7):     # in pieces, as a pipe reads
                    s.feed(text[i:i + 7])
                if not tail:
                    self.assertNotIn(decoded.split("\n")[0], "".join(out))
                s.idle()
                self.assertEqual("".join(out),
                                 "loaded!\ntrace \n" + decoded + note + "\n" + tail)
        self.assertEqual(len(made), 2)
        out = []
        s = errors.Stream(lambda: None, root, out.append)
        s.feed(packaged + "\n")
        s.close()
        self.assertEqual("".join(out), packaged + "\n")    # no map: as it is
        out = []
        s = errors.Stream(decoder, root, out.append)
        s.feed('[string "helper"]:3: boom\npartial')
        s.idle()
        self.assertEqual("".join(out), '[string "helper"]:3: boom\npartial')


class TestMap(unittest.TestCase):
    """The decode map (bundle.map_doc), as a folder build writes it."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="ticpak-error-map-")
        self.addCleanup(shutil.rmtree, self.root, True)

    def folder_build(self, case, options):
        main = write_project(self.root, project(case))
        t = bundle.Target(main, "game", os.path.join(self.root, "dist") + os.sep)
        with contextlib.redirect_stdout(io.StringIO()):
            bundle.bundle(t, options)
        return t

    def test_format(self):
        t = self.folder_build("index a field", M.ALL_OPTIONS)
        with open(t.map_json, encoding="utf-8") as f:
            doc = json.load(f)
        with open(t.lua, encoding="utf-8") as f:
            lua = f.read()
        self.assertEqual(doc["format"], bundle.MAP_FORMAT)
        self.assertEqual(doc["cart"], "game.lua")
        self.assertRegex(doc["build"], r"^\d+\.\d+\.\d+ -m=max$")
        self.assertEqual(doc["code"], bundle.code_hash(lua))
        code = bundle.code_part(lua).split("\n")
        # every code line has segments, each at a token, in column order
        for n, line in enumerate(code, 1):
            if not line.startswith("--"):
                segs = doc["segments"][str(n)]
                cols = [s[0] for s in segs]
                self.assertEqual(cols, sorted(cols))
                offs = []
                M.lex(line, offsets=offs)
                self.assertTrue(set(cols) <= set(offs), (n, line, cols))
                self.assertEqual(doc["lines"][str(n)], segs[0][1:])
        # the bug's line, and the function around it, by segment
        chase = next(n for n, segs in doc["segments"].items()
                     if ["enemies.lua", 13] in [s[1:] for s in segs])
        self.assertTrue(code[int(chase) - 1].startswith("local function"))
        self.assertEqual([s[1:] for s in doc["segments"][chase]],
                         [["enemies.lua", 11], ["enemies.lua", 13], ["enemies.lua", 14],
                          ["enemies.lua", 15]])

    def test_uses(self):
        """Each renamed variable's first and last use sit on its short name,
        and two variables sharing a short name never overlap."""
        t = self.folder_build("call a local", M.ALL_OPTIONS)
        with open(t.map_json, encoding="utf-8") as f:
            doc = json.load(f)
        with open(t.lua, encoding="utf-8") as f:
            code = bundle.code_part(f.read()).split("\n")
        by_new = {}
        for r in doc["renames"]:
            if r["kind"] == "field":
                self.assertNotIn("uses", r)
                continue
            (l1, c1), (l2, c2) = r["uses"]
            self.assertLessEqual((l1, c1), (l2, c2))
            for line, col in r["uses"]:
                self.assertEqual(code[line - 1][col:col + len(r["new"])], r["new"], r)
            if r["kind"] == "local":
                by_new.setdefault(r["new"], []).append(((l1, c1), (l2, c2)))
        for new, spans in by_new.items():
            spans.sort()
            for a, b in zip(spans, spans[1:]):
                self.assertLess(a[1], b[0], new)
        self.assertTrue(any(len(s) > 1 for s in by_new.values()))   # names are reused

    def test_options_samples(self):
        """On every sample cart of tests/options (NOMINIFY-protected bodies,
        kept comments, CRLF, ...) and every option set past comments: each
        segment starts at a token, and each use of a renamed variable is its
        short name."""
        samples = os.path.join(REPO, "tests", "options", "samples")
        keys = bundle.META_KEYS
        sets = sorted({M.parse_options(s) for s in
                       (["rename-vars"], ["whitespace"], ["constants", "whitespace"],
                        ["extra"], "default", "max")}, key=sorted)
        for name in sorted(os.listdir(samples)):
            with open(os.path.join(samples, name), encoding="utf-8") as f:
                text = f.read()
            for opts in sets:
                with self.subTest(sample=name, opts=",".join(sorted(opts))):
                    r = M.minify_cart_ex(text, mode=opts, meta_keys=keys)
                    if r.report is None:                    # a whole-cart NOMINIFY
                        continue
                    lines = r.text.split("\n")
                    offs, starts = [], set()
                    M.lex(r.text, offsets=offs)
                    for off in offs:      # (line, column) of every token
                        line = r.text.count("\n", 0, off) + 1
                        starts.add((line, off - r.text.rfind("\n", 0, off) - 1))
                    for o, segs in r.segments.items():
                        for c, _ in segs:
                            self.assertIn((o, c), starts, lines[o - 1])
                    for (new, old, kind, _), u in zip(r.renames, r.uses):
                        self.assertEqual(u is None, kind == "field", old)
                        for line, col in u or ():
                            self.assertEqual(lines[line - 1][col:col + len(new)], new, old)

    def test_unminified_has_no_map_file(self):
        t = self.folder_build("index a field", frozenset())
        self.assertFalse(os.path.exists(t.map_json))

    def test_in_memory_for_every_preset(self):
        """map_doc() works for builds that write no map file (no -m,
        comments): the code's tokens pair with the unminified bundle's."""
        for preset in ("none", "comments"):
            with self.subTest(preset=preset):
                bl = Built("index a field", PRESETS[preset], self.root)
                doc = bundle.map_doc(bl.b)
                code = bundle.code_part(bl.code).split("\n")
                n = next(i for i, line in enumerate(code, 1) if "enemy.target.x" in line)
                self.assertEqual(doc["lines"][str(n)], ["enemies.lua", 13])
                self.assertEqual(doc["renames"], [])
                self.assertEqual(doc["code"], bundle.code_hash(bl.code))


@NEEDS_LUA
class TestDecode(unittest.TestCase):
    """Each case's error from the packaged cart, decoded, reads as the error
    the sources raise as written - locations, names and traceback."""

    def test_cases(self):
        """Every location the written one (or, in a frame, a range holding
        it), and every name; unminified, all exact."""
        for case in CASES:
            for preset in PRESETS:
                with self.subTest(case=case, preset=preset):
                    packaged, decoded, written = built(case, preset)
                    self.assertTrue(written, "the case raises no error")
                    self.assertIn('[string "-- title:  Error Test..."]', packaged)
                    problem, ranges = compare(decoded, written)
                    self.assertIsNone(problem, f"\ndecoded:\n{decoded}\nwritten:\n{written}"
                                               f"\npackaged:\n{packaged}")
                    if preset in ("none", "comments", "rename-vars"):
                        self.assertEqual(decoded, written)

    def test_compare(self):
        ok = "a.lua:3: boom\nstack traceback:\n\ta.lua:3: in function 'f'\n\tmain.lua:9: in x"
        self.assertEqual(compare(ok, ok), (None, 0))
        self.assertEqual(compare(ok.replace("main.lua:9", "main.lua:8-9"), ok), (None, 1))
        for bad in (ok.replace("main.lua:9", "main.lua:7-8"), ok.replace("'f'", "'g'"),
                    ok.replace("a.lua:3: boom", "a.lua:2-3: boom"), ok + "\nmore"):
            self.assertIsNotNone(compare(bad, ok)[0], bad)

    def test_max_needs_decoding(self):
        """Under max the raw error names nothing a reader would know: the
        decoding is doing the work."""
        packaged, decoded, written = built("index a field", "max")
        self.assertNotIn("'target'", packaged)
        self.assertNotIn("chase", packaged)
        self.assertIn("(field 'target')", decoded)
        self.assertIn("in upvalue 'chase'", decoded)
        self.assertIn("in function 'enemies.update_all'", decoded)

    def test_source_line(self):
        root = tempfile.mkdtemp(prefix="ticpak-error-")
        self.addCleanup(shutil.rmtree, root, True)
        bl = Built("arithmetic on a parameter", M.ALL_OPTIONS, root)
        dec = errors.Decoder(bundle.map_doc(bl.b), bl.code)
        _, first, missing = errors.decode(run_packaged(bl.code), dec)
        self.assertEqual(first, ("combat.lua", 5))
        self.assertEqual(missing, [])
        self.assertEqual(errors.source_line(root, first), "  target.hp = before - amount")

    def test_other_chunks_left_alone(self):
        """Only locations in the cart's chunk are decoded; a retyped chunk
        name (no location matches) is decoded all the same."""
        packaged, _, _ = built("index a field", "max")
        root = tempfile.mkdtemp(prefix="ticpak-error-")
        self.addCleanup(shutil.rmtree, root, True)
        bl = Built("index a field", M.ALL_OPTIONS, root)
        dec = errors.Decoder(bundle.map_doc(bl.b), bl.code)
        other = '\t[string "helper"]:3: in function <[string "helper"]:1>'
        out = errors.decode(packaged + "\n" + other, dec)[0]
        self.assertTrue(out.endswith(other))
        retyped = packaged.replace("-- title:  Error Test...", "-- title: error test")
        self.assertEqual(errors.decode(retyped, dec)[0], built("index a field", "max")[1])

    def test_failed_boot_output(self):
        """`ticpak bundle` quotes a failed boot's TIC-80 output after `   | `:
        decoded the same, the prefix kept."""
        packaged, decoded, _ = built("index a field", "max")
        root = tempfile.mkdtemp(prefix="ticpak-error-")
        self.addCleanup(shutil.rmtree, root, True)
        bl = Built("index a field", M.ALL_OPTIONS, root)
        dec = errors.Decoder(bundle.map_doc(bl.b), bl.code)
        quoted = "\n".join("   | " + ln for ln in packaged.split("\n"))
        self.assertEqual(errors.decode(quoted, dec)[0],
                         "\n".join("   | " + ln for ln in decoded.split("\n")))

    def test_metamethod_frame(self):
        """TIC-80's traceback can put a nameless C frame between the message
        and the error's own frame (`[C]: in metamethod '__index'`): that
        frame is still the message's line, not the whole function."""
        packaged, decoded, _ = built("index a field", "max")
        c_frame = "\t[C]: in metamethod '__index'"
        insert = lambda t: t.replace("stack traceback:\n", "stack traceback:\n" + c_frame
                                     + "\n", 1)                       # noqa: E731
        root = tempfile.mkdtemp(prefix="ticpak-error-")
        self.addCleanup(shutil.rmtree, root, True)
        bl = Built("index a field", M.ALL_OPTIONS, root)
        dec = errors.Decoder(bundle.map_doc(bl.b), bl.code)
        out = errors.decode(insert(packaged), dec)[0]
        self.assertEqual(out, insert(decoded))
        self.assertIn("\n\tenemies.lua:13: in upvalue 'chase'\n", out)

    def test_line_not_in_cart(self):
        root = tempfile.mkdtemp(prefix="ticpak-error-")
        self.addCleanup(shutil.rmtree, root, True)
        bl = Built("index a field", M.ALL_OPTIONS, root)
        dec = errors.Decoder(bundle.map_doc(bl.b), bl.code)
        text = '[string "-- title:  Error Test..."]:999: attempt to call a nil value'
        out, first, missing = errors.decode(text, dec)
        self.assertEqual(out, text)
        self.assertEqual((first, missing), (None, [999]))


@NEEDS_LUA
class TestCommand(unittest.TestCase):
    """`ticpak decode` from the command line."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="ticpak-error-cmd-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.main = write_project(self.root, project("index a field"))

    def run_cmd(self, *argv, stdin=None, tty=False, clipboard=None):
        """(exit status, stdout, stderr) of `ticpak decode ...`: stdin
        redirected from the text given, or a terminal (tty) the text is
        pasted into; clipboard, the clipboard's text."""
        out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        err = io.StringIO()
        status = 0
        old_stdin, old_clip = sys.stdin, errors.clipboard_text
        sys.stdin = Terminal(stdin or "") if tty else io.StringIO(stdin or "")
        errors.clipboard_text = lambda: clipboard
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                cli.main(["decode", *argv])
        except SystemExit as e:
            status = e.code if isinstance(e.code, int) else 1
            if isinstance(e.code, str):
                err.write(e.code)
        finally:
            sys.stdin, errors.clipboard_text = old_stdin, old_clip
        out.flush()
        text = out.buffer.getvalue().decode("utf-8").replace("\r\n", "\n")
        return status, text, err.getvalue()

    def build_folder(self, options=M.ALL_OPTIONS):
        """A folder build (dist/: .lua, maps) and the .tic TIC-80 would save."""
        self.dist = os.path.join(self.root, "dist") + os.sep
        t = bundle.Target(self.main, "error-test", self.dist)
        with contextlib.redirect_stdout(io.StringIO()):
            bundle.bundle(t, options)
        tic_file(t.tic, t.code[:t.code.index("-- <TILES>")])
        return t

    def build_lua(self, options=M.ALL_OPTIONS):
        path = os.path.join(self.root, "game.lua")
        t = bundle.Target(self.main, "game", path)
        with contextlib.redirect_stdout(io.StringIO()):
            b = bundle.build(t, options)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(b.code + b.chunks)
        return path, b.code

    def test_folder_build_uses_map_file(self):
        t = self.build_folder()
        packaged = run_packaged(bundle.built_code(t.tic))
        status, out, _ = self.run_cmd(self.root, "-o", self.dist, "-e", packaged)
        self.assertEqual(status, 0)
        self.assertRegex(out, r"map: \S*error-test\.minify\.json\n")
        self.assertIn("enemies.lua:13: attempt to index a nil value (field 'target')", out)
        self.assertIn("\tenemies.lua:23: in function 'enemies.update_all'", out)
        self.assertIn("source: enemies.lua:13\n    local dx = enemy.target.x - enemy.x", out)

    def test_stale_map_file_rebuilds(self):
        """A map file that is not the .tic's (an older build's) is not used:
        the sources are rebuilt instead."""
        t = self.build_folder()
        with open(t.map_json, encoding="utf-8") as f:
            doc = json.load(f)
        doc["code"] = "sha1:0"
        with open(t.map_json, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        packaged = run_packaged(bundle.built_code(t.tic))
        status, out, _ = self.run_cmd(self.root, "-o", self.dist, "-e", packaged)
        self.assertIn("the sources rebuilt (-m=max); they match", out)
        self.assertIn("(field 'target')", out)

    def test_lua_output_rebuilds_from_its_stamp(self):
        for preset in ("none", "default", "max"):
            with self.subTest(preset=preset):
                path, code = self.build_lua(PRESETS[preset])
                status, out, _ = self.run_cmd(self.main, "-o", path,
                                              stdin=run_packaged(code))
                self.assertEqual(status, 0)
                flag = bundle.minify_flag(PRESETS[preset]) or "no -m"
                self.assertIn(f"map: the sources rebuilt ({flag}); they match", out)
                self.assertIn("enemies.lua:13: attempt to index a nil value"
                              " (field 'target')", out)

    def test_changed_sources(self):
        """Sources changed since the build: a change that leaves the code as
        it was (comments, code the minifier removes) still matches, and
        decodes to the lines as they are now; any other is warned about."""
        path, code = self.build_lua()
        packaged = run_packaged(code)
        mod = os.path.join(self.root, "enemies.lua")
        with open(mod, encoding="utf-8") as f:
            text = f.read()
        with open(mod, "w", encoding="utf-8", newline="\n") as f:
            f.write("-- a new first line\nlocal unused_now = 1\n" + text)
        status, out, _ = self.run_cmd(self.main, "-o", path, "-e", packaged)
        self.assertIn("they match", out)
        self.assertIn("enemies.lua:15: attempt to index a nil value (field 'target')", out)
        with open(mod, "w", encoding="utf-8", newline="\n") as f:
            f.write(text.replace("speed = 1", "speed = 2"))
        status, out, _ = self.run_cmd(self.main, "-o", path, "-e", packaged)
        self.assertEqual(status, 0)
        self.assertIn("WARN", out)
        self.assertIn("does not match the sources built now (-m=max)", out)
        self.assertIn("(field 'target')", out)

    def test_no_cart_built(self):
        status, _, err = self.run_cmd(self.root, "-e", '[string "x"]:1: oops')
        self.assertEqual(status, 1)
        self.assertIn("not found", err)
        path, code = self.build_lua()
        os.remove(path)
        status, out, _ = self.run_cmd(self.root, "-m=max", "-e", run_packaged(code))
        self.assertEqual(status, 0)
        self.assertIn("not found; decoding against the sources built now (-m=max)", out)
        self.assertIn("(field 'target')", out)

    def test_no_location(self):
        self.build_lua()
        status, _, err = self.run_cmd(self.root, "-o", os.path.join(self.root, "game.lua"),
                                      "-e", "attempt to index a nil value")
        self.assertEqual(status, 1)
        self.assertIn("no location in the cart found", err)

    def test_rejected_options(self):
        for argv in (["-f"], ["-r"], ["-q"]):
            with self.subTest(argv=argv):
                status, _, err = self.run_cmd(self.root, *argv, "-e", "x")
                self.assertEqual(status, 2, err)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.parse_args(["check", "-e", "x"])

    def test_indent_kept(self):
        """The traceback keeps its tabs: it is not passed through the
        flush-left console."""
        path, code = self.build_lua()
        _, out, _ = self.run_cmd(self.main, "-o", path, stdin=run_packaged(code))
        self.assertRegex(out, r"\n\tenemies\.lua:13: in upvalue 'chase'\n")
        self.assertIn("\n\tmain.lua:16: in function 'TIC'\n", out)

    def test_clipboard(self):
        """At a terminal the clipboard comes first, copied from TIC-80's
        console (40-column rows); without an error in it, a paste."""
        path, code = self.build_lua()
        copied = console_copy(run_packaged(code))
        status, out, _ = self.run_cmd(self.main, "-o", path, tty=True, clipboard=copied)
        self.assertEqual(status, 0)
        self.assertIn("error: the clipboard\n", out)
        self.assertIn("enemies.lua:13: attempt to index a nil value (field 'target')", out)
        status, out, err = self.run_cmd(self.main, "-o", path, tty=True, clipboard="hello",
                                        stdin=copied)
        self.assertEqual(status, 0)
        self.assertIn("the clipboard holds no error from a cart: paste", err)
        self.assertIn("(field 'target')", out)
        status, _, err = self.run_cmd(self.main, "-o", path, clipboard=None)
        self.assertEqual(status, 1)
        self.assertIn("no error to translate", err)
        status, out, _ = self.run_cmd(self.main, "-o", path, stdin=copied, clipboard="x")
        self.assertNotIn("the clipboard", out)       # redirected stdin comes first
        self.assertIn("(field 'target')", out)

    def test_log(self):
        """--log: the last error in a log of TIC-80's output."""
        path, code = self.build_lua()
        packaged = run_packaged(code)
        earlier = packaged.replace("a nil value", "a number value", 1)
        log = os.path.join(self.root, "tic80.log")
        with open(log, "w", encoding="utf-8") as f:
            f.write("TIC-80 tiny computer\nloaded!\n" + earlier + "\nrestarted\n"
                    + packaged + "\n" + '[string "other"]:1: not this cart\nbye\n')
        status, out, _ = self.run_cmd(self.main, "-o", path, "--log", log)
        self.assertEqual(status, 0, out)
        self.assertIn("error: the last error in", out)
        decoded = errors.decode(packaged, errors.find_map(
            bundle.Target(self.main, "game", path))[0])[0]
        self.assertIn("\n" + decoded + "\n", out)
        self.assertNotIn("restarted", out)
        self.assertNotIn("number value", out)
        status, _, err = self.run_cmd(self.main, "-o", path, "--log", log + ".missing")
        self.assertEqual(status, 1)
        self.assertIn("can't read", err)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.parse_args(["decode", "--log", log, "-e", "x"])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.parse_args(["test", "--log", log])
        for argv in (["run", "-m"], ["run", "-o", "x.tic"], ["run", "-f"], ["run", "-q"]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                cli.parse_args(argv)
        self.assertEqual(cli.parse_args(["run", self.main])[0], "run")


class Terminal(io.StringIO):
    """stdin at a terminal, the text given pasted into it."""

    def isatty(self):
        return True


if __name__ == "__main__":
    unittest.main()
