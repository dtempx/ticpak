#!/usr/bin/env python3
"""`ticpak error`: a runtime error from a packaged cart, translated back to
the sources.

TIC-80 reports a line of the bundle, `[string "-- title: ..."]:37:`, and once
minified that line holds a whole function or more, its names shortened. The
decode map (bundle.map_doc) turns each such location into file:line and each
name the message or a traceback frame quotes back into the original. The
name also picks out which of the output line's source lines it came from: a
`(field 'd')` that occurs once on line 37 is on that occurrence's line.

The map is a folder build's <name>.minify.json when it matches the cart,
else made in memory: the sources rebuilt with the cart's own -m (from its
`-- ticpak:` line; the minifier is deterministic) and checked against the
cart's code.
"""
import json
import os
import re

from . import __version__
from . import minify as minifier
from .bundle import (MAP_FORMAT, build, built_code, code_hash, code_part, flag_options,
                     map_doc, minify_flag)
from .check import read_stamp
from .console import show

# TIC-80 loads the code with luaL_loadstring, so the chunk is named after its
# first line: [string "-- title:  My Game..."]
LOC = r'\[string "(?P<chunk>.*?)"\]:(?P<line>\d+)'
LOC_RE = re.compile(LOC)
# (a frame's indent may follow the `   | ` a failed `ticpak bundle` boot
# quotes TIC-80's output with)
FRAME_RE = re.compile(r"^(?P<indent>[\s|]*)" + LOC + r":\s*in (?P<what>.*)$")
FUNC_AT_RE = re.compile("<" + LOC + ">")     # a function without a name: where it starts
C_FRAME_RE = re.compile(r"^[\s|]*\[C\]:\s*in (?P<what>.*)$")
# A frame's name: how its caller called it (Lua 5.3's luaL_traceback)
FRAME_NAME_RE = re.compile(r"^(local|upvalue|global|field|method|function) '([^']+)'")
# A value named in a runtime error (Lua 5.3's varinfo), or the function a
# library error is about
VAR_RE = re.compile(r"\((local|upvalue|global|field|method|constant) '([^']+)'\)")
FUNC_RE = re.compile(r"((?:bad argument #\d+ to|calling) )'([^']+)'")

KIND = {"local": "local", "upvalue": "local", "global": "global", "field": "field",
        "method": "field"}
ARITH = {"+", "-", "*", "/", "//", "%", "^", "&", "|", "~", "<<", ">>"}


def calls(prev, nxt):
    return nxt[1] in ("(", "{") or nxt[0] == "string"


def context(msg):
    """What a value the message names is doing on its line, as a test of
    (previous token, next token), or None."""
    if "attempt to index" in msg:
        return lambda prev, nxt: nxt[1] in (".", "[", ":")
    if "attempt to call" in msg or FUNC_RE.search(msg):
        return calls
    if ("arithmetic" in msg or "bitwise" in msg or "integer representation" in msg):
        return lambda prev, nxt: prev[1] in ARITH or nxt[1] in ARITH
    if "concatenate" in msg:
        return lambda prev, nxt: ".." in (prev[1], nxt[1])
    if "get length" in msg:
        return lambda prev, nxt: prev[1] == "#"
    return None


class Decoder:
    """A decode map (map_doc) and the code it describes."""

    def __init__(self, doc, code):
        self.lines = {int(k): v for k, v in doc["lines"].items()}
        self.segments = {int(k): v for k, v in doc.get("segments", {}).items()}
        self.code = code_part(code).split("\n")
        self.fields, self.globals, self.locals = {}, {}, {}
        for r in doc["renames"]:
            if r["kind"] == "field":
                self.fields[r["new"]] = r
            elif r["kind"] == "global":
                self.globals[r["new"]] = r
            else:
                self.locals.setdefault(r["new"], []).append(r)

    def ours(self, chunk):
        """Is [string "chunk"] this cart's code? Lua names it after the
        code's first line, cut short with "..."."""
        first = self.code[0] if self.code else ""
        return bool(chunk) and first.startswith(chunk[:-3] if chunk.endswith("...")
                                                else chunk)

    def tokens(self, line):
        """(kind, text, column) of each token on output line `line`; [] where
        the line does not lex on its own (inside a long string)."""
        if not 0 < line <= len(self.code):
            return []
        offs = []
        try:
            toks = minifier.lex(self.code[line - 1], offsets=offs)
        except (SyntaxError, ValueError, IndexError):
            return []
        return [(k, t, o) for (k, t), o in zip(toks, offs)]

    def find(self, line, name, role=None, test=None):
        """Columns where `name` occurs on output line `line`: as a field
        (after . or :), a variable (role "var"), or either (None); with test,
        only where test(previous token, next token) holds - if any does."""
        toks = self.tokens(line)
        none = ("", "", -1)
        hits, tested = [], []
        for i, (kind, text, col) in enumerate(toks):
            if kind != "name" or text != name:
                continue
            prev = toks[i - 1] if i else none
            nxt = toks[i + 1] if i + 1 < len(toks) else none
            field = prev[1] in (".", ":")
            if role == "field" and not field or role == "var" and field:
                continue
            hits.append(col)
            if test and test(prev, nxt):
                tested.append(col)
        return tested or hits

    def sources(self, line, cols=()):
        """The source lines output line `line` holds, [(file, line)] in
        order: those at cols if given, else all of them. None: no such line."""
        segs = self.segments.get(line)
        if not segs:
            first = self.lines.get(line)
            return [tuple(first)] if first else None
        if cols:
            picked = []
            for col in cols:
                seg = [s for s in segs if s[0] <= col] or segs[:1]
                picked.append(tuple(seg[-1][1:]))
            return list(dict.fromkeys(picked))
        own = [tuple(s[1:]) for s in segs if s[1]]
        return list(dict.fromkeys(own or [tuple(s[1:]) for s in segs]))

    def where(self, line, cols=()):
        """file:line for output line `line` (the occurrences at cols pick
        the source line), file:first-last when it holds several; None for
        a line the cart does not have."""
        srcs = self.sources(line, cols)
        if srcs is None:
            return None
        by_file = {}
        for f, n in srcs:
            by_file.setdefault(f, []).append(n)
        out = []
        for f, ns in by_file.items():
            if f is None:
                out.append(f"bundle line {line} (added by ticpak)")
            elif min(ns) == max(ns):
                out.append(f"{f}:{ns[0]}")
            else:
                out.append(f"{f}:{min(ns)}-{max(ns)}")
        return " or ".join(out)

    def start(self, line):
        """file:line of output line `line`'s first token (where a function
        starts: each starts its own line); None for a line ticpak added or
        the cart does not have."""
        first = self.lines.get(line)
        return f"{first[0]}:{first[1]}" if first and first[0] else None

    def exact(self, line, cols=()):
        """(file, line) when output line `line` (at cols) is one source line."""
        srcs = self.sources(line, cols)
        return srcs[0] if srcs and len(srcs) == 1 and srcs[0][0] else None

    def original(self, kind, name, line=None, cols=()):
        """The source name of a short name of `kind` (local, global, field, or
        None: any) used on output line `line` (at cols); None if not renamed."""
        if kind == "field":
            r = self.fields.get(name)
            return r and r["old"]
        if kind == "global":
            r = self.globals.get(name)
            return r and r["old"]
        cands = self.locals.get(name, [])
        if line is not None:
            def covers(r, pos):
                u = r.get("uses")
                return u is not None and tuple(u[0]) <= pos <= tuple(u[1])
            if cols:
                at = [r for r in cands if any(covers(r, (line, c)) for c in cols)]
            else:
                at = [r for r in cands
                      if r.get("uses") and r["uses"][0][0] <= line <= r["uses"][1][0]]
            cands = at
        olds = list(dict.fromkeys(r["old"] for r in cands))
        if olds:
            return "' or '".join(olds)
        if kind is None:
            return self.original("global", name) or self.original("field", name)
        return None

    def function_name(self, name, line=None, cols=()):
        """A traceback's `function 'x'`: a global, `_G.x`, or `module.field`
        (Lua 5.3 names a function by where package.loaded holds it)."""
        head, dot, last = name.rpartition(".")
        if dot and head != "_G":
            return head + "." + (self.original("field", last) or last)
        new = self.original("global", last) or self.original(None, last, line, cols)
        return (head + dot if dot else "") + (new or last)


def frame_call(frame):
    """(role, short name) that finds the call to a frame's function in its
    caller's line; None when it has no name to look for."""
    m = FRAME_NAME_RE.match(frame["what"])
    if not m:
        return None
    what, name = m.groups()
    if what == "function":
        head, dot, last = name.rpartition(".")
        return ("field", last) if dot and head != "_G" else ("var", last)
    return ("field" if KIND[what] == "field" else "var"), name


def decode(text, dec):
    """The error text with every location in the cart and short name
    translated. Returns (text, the error's own source line as (file, line)
    or None, the output lines the cart does not have). Only locations in a
    chunk named after the cart's first line are the cart's, unless none is
    (the name retyped, say): then all of them are."""
    lines = text.lstrip("﻿").replace("\r\n", "\n").split("\n")
    strict = any(dec.ours(m.group("chunk")) for m in LOC_RE.finditer(text))

    def ours(m):
        return not strict or dec.ours(m.group("chunk"))
    items = []
    for ln in lines:
        m = FRAME_RE.match(ln)
        if m:
            items.append({"type": "frame" if ours(m) else "other",
                          "line": int(m.group("line")), "what": m.group("what")})
            continue
        m = C_FRAME_RE.match(ln)
        if m:
            items.append({"type": "cframe", "what": m.group("what")})
            continue
        m = next((m for m in LOC_RE.finditer(ln) if ours(m)), None)
        items.append({"type": "msg", "line": int(m.group("line")), "at": m.end()}
                     if m else {"type": "text"})

    # Where each line is: a message by the name it quotes; a frame by the
    # call, on its line, to the frame above it (the function it called).
    above = None
    for i, it in enumerate(items):
        it["cols"] = []
        if it["type"] == "msg":
            msg = lines[i][it["at"]:]
            test = context(msg)
            m = VAR_RE.search(msg)
            if m and m.group(1) != "constant":
                kind = KIND[m.group(1)]
                it["name"] = (m.group(2), kind)
                it["cols"] = dec.find(it["line"], m.group(2),
                                      "field" if kind == "field" else "var", test)
            else:
                m = FUNC_RE.search(msg)
                if m:
                    it["name"] = (m.group(2), None)
                    it["cols"] = dec.find(it["line"], m.group(2), "var", test)
        elif it["type"] == "frame" and above:
            if above["type"] == "msg" and above["line"] == it["line"]:
                it["cols"] = above["cols"]           # the error's own frame
            elif above["type"] in ("frame", "cframe"):
                call = frame_call(above)
                if call:
                    it["cols"] = dec.find(it["line"], call[1], call[0], calls)
                    above["caller"] = (it["line"], it["cols"])
        if it["type"] != "text":                     # "stack traceback:" in between
            above = it
    # A message that names nothing (error("...")) is where the frame below
    # it is, found by its call to the C function that raised it
    for i, it in enumerate(items):
        if it["type"] == "msg" and not it["cols"]:
            below = next((x for x in items[i + 1:] if x["type"] not in ("text", "cframe")),
                         None)
            if below and below["type"] == "frame" and below["line"] == it["line"]:
                it["cols"] = below["cols"]

    out, missing, first = [], [], None

    def loc(m, it):
        if not ours(m):
            return m.group(0)
        n = int(m.group("line"))
        w = dec.where(n, it["cols"] if it.get("line") == n else ())
        if w is None:
            missing.append(n)
            return m.group(0)
        return w

    def start(m):
        if not ours(m):
            return m.group(0)
        return "<" + (dec.start(int(m.group("line"))) or m.group(0)[1:-1]) + ">"
    for i, it in enumerate(items):
        ln = lines[i]
        if it["type"] in ("text", "other"):
            out.append(ln)
            continue
        if it["type"] == "msg":
            if first is None:
                first = dec.exact(it["line"], it["cols"])
            head, rest = ln[:it["at"]], ln[it["at"]:]
            if "name" in it:
                name, kind = it["name"]
                new = dec.original(kind, name, it["line"], it["cols"])
                if new:
                    rest = rest.replace(f"'{name}'", f"'{new}'", 1)
            out.append(LOC_RE.sub(lambda m: loc(m, it), head)
                       + LOC_RE.sub(lambda m: loc(m, it), FUNC_AT_RE.sub(start, rest)))
            continue
        # a frame's name is how its caller called it: look it up there
        line, cols = it.get("caller", (it.get("line"), it["cols"]))
        what = it["what"]
        m = FRAME_NAME_RE.match(what)
        if m:
            kind, name = m.groups()
            if kind == "function":
                new = dec.function_name(name, line, cols)
            else:
                new = dec.original(KIND[kind], name, line, cols)
            if new:
                what = f"{kind} '{new}'" + what[m.end():]
        what = FUNC_AT_RE.sub(start, what)
        if it["type"] == "cframe":
            out.append(ln[:len(ln) - len(it["what"])] + what)
        else:
            fm = FRAME_RE.match(ln)
            out.append(fm.group("indent")
                       + LOC_RE.sub(lambda m: loc(m, it), ln[fm.end("indent"):fm.end("line")])
                       + ": in " + what)
    return "\n".join(out), first, list(dict.fromkeys(missing))


def find_map(t, options=None):
    """(Decoder, notes) for the cart t describes. options: the -m it was
    built with, else its `-- ticpak:` line says. Exits when neither tells."""
    code = built_code(t.output) if os.path.isfile(t.output) else None
    stamp = read_stamp(code) if code is not None else None
    notes = []
    if options is None:
        if code is None:
            raise SystemExit(f"ticpak: {show(t.output)} not found - give -o with the cart"
                             " the error came from, or -m with the options it was built"
                             " with to decode against a fresh build")
        if stamp is None:
            raise SystemExit(f"ticpak: {show(t.output)} has no `-- ticpak:` line (built"
                             " before ticpak 0.3.4?) - give -m with the options it was"
                             " built with")
        options = flag_options(stamp[1])
    flag = minify_flag(options) or "no -m"
    if code is not None and t.map_json and os.path.isfile(t.map_json):
        try:
            with open(t.map_json, encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, ValueError):
            doc = {}
        if doc.get("format") == MAP_FORMAT and doc.get("code") == code_hash(code):
            notes.append(f"map: {show(t.map_json)}")
            return Decoder(doc, code), notes
    b = build(t, options)
    doc = map_doc(b)
    if code is None:
        notes.append(f"map: {show(t.output)} not found; decoding against the sources"
                     f" built now ({flag}), which is right only if the cart was built"
                     " from these sources the same way")
        return Decoder(doc, b.code), notes
    if doc["code"] == code_hash(code):
        notes.append(f"map: the sources rebuilt ({flag}); they match {show(t.output)}")
        return Decoder(doc, code), notes
    why = "the sources or -m changed since it was built"
    if stamp and stamp[0] != __version__:
        why = f"it was built by ticpak {stamp[0]}, this is {__version__}; or " + why
    notes.append(f"  WARN  {show(t.output)} does not match the sources built now"
                 f" ({flag}): {why}. Lines and names below may be wrong - decode"
                 " with the sources as they were, or rebuild and reproduce the error")
    return Decoder(doc, b.code), notes


def source_line(cart_dir, where):
    """The text of source line (file, line) beside the cart, or None."""
    f, n = where
    try:
        with open(os.path.join(cart_dir, f), encoding="utf-8") as fh:
            lines = fh.read().split("\n")
    except OSError:
        return None
    return lines[n - 1].rstrip() if 0 < n <= len(lines) else None
