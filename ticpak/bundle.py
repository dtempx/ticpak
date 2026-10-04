#!/usr/bin/env python3
"""The bundle for ticpak: find the cart, inline every module its entry
stub requires as a package.preload entry, minify (minify.py), and write
<out>/<name>.lua plus, when minified past comments, the decode maps.
"""
import json
import os
import re
import sys

from . import minify as minifier
from .check import TEXT_SECTION_RE, check_header
from .console import detail, fwd, show
from .header import CHUNK_RE, META_KEYS, cart_code

FREE_LIMIT = 65536  # the free editor's code cap (PRO edits up to 512 KB; every player loads it all)


class Target:
    """One build's paths: the cart, the folder its modules sit in, and the
    outputs <out>/<name>.lua, .tic, .txt, .minify.txt and .minify.json."""

    def __init__(self, cart, name, out_dir):
        self.cart = os.path.abspath(cart)
        self.cart_dir = os.path.dirname(self.cart)
        self.name = name
        self.dist_dir = os.path.abspath(out_dir)
        out = os.path.join(self.dist_dir, name)
        self.lua, self.tic, self.txt = out + ".lua", out + ".tic", out + ".txt"
        self.map_txt, self.map_json = out + ".minify.txt", out + ".minify.json"

    def module_path(self, module):
        return os.path.join(self.cart_dir, *module.split(".")) + ".lua"


def find_cart(source=None):
    """The cart: SOURCE (a file, or a directory searched like the cwd), else
    ./main.lua, else ./src/main.lua. None if there is none."""
    if source and os.path.isfile(source):
        return os.path.abspath(source)
    base = source or os.getcwd()
    for rel in ("main.lua", os.path.join("src", "main.lua")):
        p = os.path.join(base, rel)
        if os.path.isfile(p):
            return os.path.abspath(p)
    return None


def stub_requires(code):
    """Every literal require in the entry stub, in order, including assigned
    ones (`local audio = require "sfx"`, `require("x")`); comments are
    skipped. Returns (names, offset of the first require line)."""
    names, first = [], None
    pos = 0
    for line in code.splitlines(keepends=True):
        for name in re.findall(r'\brequire\s*\(?\s*["\']([\w.]+)["\']',
                               line.split("--", 1)[0]):
            if first is None:
                first = pos
            if name not in names:
                names.append(name)
        pos += len(line)
    return names, first


def freshness(t):
    """(up_to_date, status line) for an existing package: is the .tic (and the
    .lua bundle beside it) newer than the cart and every module it requires?
    Timestamps only - a changed option (--minify) or tool does not count."""
    built = os.path.getmtime(t.tic)
    names, _ = stub_requires(cart_code(t.cart))
    sources = [t.cart] + [t.module_path(n) for n in names]
    changed = [fwd(p) for p in sources
               if not os.path.isfile(p) or os.path.getmtime(p) > built]
    missing = [] if os.path.isfile(t.lua) else [f"{fwd(t.lua)} missing"]
    if not changed and not missing:
        return True, f"cart: {fwd(t.tic)} (up-to-date)"
    listed = ", ".join(changed[:5]) + (f" and {len(changed) - 5} more"
                                       if len(changed) > 5 else "")
    why = "; ".join(([f"{listed} changed"] if changed else []) + missing)
    return False, f"cart: {fwd(t.tic)} (out-of-date: {why})"


def assemble(t):
    """Inline every module the stub requires; nothing is written.

    Returns (code, chunks, names, origin): code is the cart's header + code with
    each module wrapped in a package.preload entry, chunks the asset sections
    verbatim, names the modules in require order, and origin[k] the
    (file, line) that line k+1 of code came from (file None for lines ticpak
    added itself).
    """
    cart = open(t.cart, encoding="utf-8").read()
    m = CHUNK_RE.search(cart)
    if not m:
        sys.exit(f"bundle: no asset chunks found in {show(t.cart)}")
    code, chunks = cart[:m.start()], cart[m.start():]
    if not check_header(code, quiet=True):
        check_header(code)
        sys.exit(f"bundle: {show(t.cart)} metadata header is"
                 " incomplete - fill in the fields above before packaging")

    names, first = stub_requires(code)
    if not names:
        sys.exit("bundle: entry stub requires no modules - nothing to inline")

    cart_name = os.path.basename(t.cart)
    parts, origin = [], []
    def add(text, fname, start):
        parts.append(text)
        n = text.count("\n")
        origin.extend((fname, start + i if fname else 0) for i in range(n))
    add(code[:first], cart_name, 1)
    add("-- modules inlined by ticpak - edit the *.lua modules "
        "beside the dev cart, never this file\n", None, 0)
    for name in names:
        path = t.module_path(name)
        if not os.path.isfile(path):
            sys.exit(f"bundle: module '{name}' not found at {show(path)}")
        src = open(path, encoding="utf-8").read()
        module_sections(src, f"{name.replace('.', '/')}.lua")
        add(f'package.preload["{name}"] = function(...)\n', None, 0)
        add(src + "\n", f"{name.replace('.', '/')}.lua", 1)
        add("end\n\n", None, 0)
    add(code[first:], cart_name, code[:first].count("\n") + 1)
    if not code.endswith("\n"):
        origin.append((cart_name, code.count("\n") + 1))
    return "".join(parts), chunks, names, origin


# A section tag alone on its line, as TIC-80 writes one; `-- <MAP> notes`
# is prose, left to tag_lines() (unminified) or stripped as a comment.
SECTION_LINE_RE = re.compile(TEXT_SECTION_RE.pattern + r"[ \t]*$", re.M)


def module_sections(src, fname):
    """Stop on an asset section in a module: only the cart's are packaged.
    Unminified, TIC-80 would cut the code at its tag; minified, it is
    comments and would vanish without a word."""
    m = SECTION_LINE_RE.search(src)
    if m:
        line = src.count("\n", 0, m.start()) + 1
        sys.exit(f"bundle: {fname}:{line} starts an asset section ({m.group(0).strip()}),"
                 " but only main.lua's asset sections are packaged - move it"
                 " into main.lua")


def unminified_size(t):
    """The bundle's code size before minification, re-assembled (for `check`,
    which did not build); None if the modules cannot be assembled now."""
    import contextlib
    import io
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            return len(assemble(t)[0].encode("utf-8"))
    except SystemExit:
        return None


def minify_label(options):
    """'comments, rename, ...' in OPTIONS order, 'all', or 'none'."""
    if not options:
        return "none"
    if set(options) == set(minifier.OPTIONS):
        return "all"
    return ", ".join(o for o in minifier.OPTIONS if o in options)


TIC80_TAG_RE = re.compile(r"^-- <[A-Za-z]")


def tag_lines(code, origin=None):
    """Stop if a code line reads as an asset-section tag to TIC-80's loader:
    `-- <` at column 0 (in an inlined module's comment, say) ends the code
    there, so the cart would fail to boot with a confusing syntax error.
    Comments are kept when the bundle is not minified, so that is when this
    bites; origin maps bundle lines to their source file:line."""
    bad = [i for i, line in enumerate(code.split("\n"), 1) if TIC80_TAG_RE.match(line)]
    if not bad:
        return
    def where(n):
        if origin and n <= len(origin) and origin[n - 1][0]:
            return f"{origin[n - 1][0]}:{origin[n - 1][1]}"
        return f"bundle line {n}"
    for n in bad:
        print(f"  ERROR  {where(n)}: {code.split(chr(10))[n - 1][:60]!r}")
    sys.exit("bundle: TIC-80 reads a line starting `-- <` as the start of the asset"
             " sections and would cut the code there. Reword that comment (no"
             " `-- <` at the start of a line), or minify with at least `comments`"
             " (--minify=comments), which removes it.")


def bundle(t, minify_options=frozenset()):
    """Write <out>/<name>.lua; returns its code size before minification (bytes)."""
    out, chunks, names, origin = assemble(t)
    raw = len(out.encode("utf-8"))

    try:
        res = minifier.minify_cart_ex(out, mode=minify_options, meta_keys=META_KEYS)
    except ValueError as e:
        sys.exit(f"bundle: {e}")
    out = res.text
    tag_lines(out, origin if not minify_options else None)

    os.makedirs(t.dist_dir, exist_ok=True)
    with open(t.lua, "w", encoding="utf-8") as f:
        f.write(out + chunks)
    if res.report is not None:
        write_maps(t, res, origin)
    else:
        # Maps from an earlier minified build would decode this bundle wrongly.
        for path in (t.map_txt, t.map_json):
            if os.path.isfile(path):
                os.remove(path)
    if not check_header(out, quiet=True):
        check_header(out)
        sys.exit(f"bundle: {show(t.lua)} lost header fields"
                 " in bundling - fix META_KEYS / minifier.split_cart")

    size = len(out)
    detail(f"bundle: {len(names)} modules inlined -> {show(t.lua)}")
    if minify_options:
        detail(f"        code {raw} -> {size} chars "
               f"({100 * (1 - size / raw):.1f}% smaller; minify: {minify_label(minify_options)})")
    else:
        detail(f"        code {size} chars (not minified)")
    detail(f"        {100 * size / FREE_LIMIT:.1f}% of the {FREE_LIMIT} char free-editor code limit")
    if size > FREE_LIMIT:
        detail(f"  INFO  (non-PRO) code is over the 64 KB free-editor limit; fine on PRO"
               " (up to 512 KB), and every build's player loads it")
    if res.report is not None:
        detail(f"        report and name/line maps -> {show(t.map_txt)},"
               f" {os.path.basename(t.map_json)}")
    return raw


def write_maps(t, res, origin):
    """Any option past comments: the pass report, plus the maps that decode a
    TIC-80 error.

    lines: output cart line -> the source file and line of its first token.
    renames: every renamed identifier with its original name and source line.
    """
    def src(line):
        return list(origin[line - 1]) if 0 < line <= len(origin) else [None, 0]
    doc = {
        "cart": os.path.basename(t.lua),
        "lines": {str(o): src(i) for o, i in res.line_map},
        "renames": [{"new": n, "old": o, "kind": k, "source": src(l)}
                    for n, o, k, l in res.renames],
    }
    with open(t.map_json, "w", encoding="utf-8") as f:
        f.write(json.dumps(doc, indent=1) + "\n")
    def where(line):
        f, n = src(line)
        return f"{f}:{n}" if f else f"bundle line {line}"
    with open(t.map_txt, "w", encoding="utf-8") as f:
        f.write(res.report.text(where))
