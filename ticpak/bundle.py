#!/usr/bin/env python3
"""The bundle for ticpak: find the cart, inline every module its entry
stub requires as a package.preload entry, minify (minify.py), and write
the bundle .lua (for a folder output, plus the decode maps when minified
past comments). Target decides which outputs a build keeps (see -o).
"""
import json
import os
import re
import sys

from . import __version__
from . import minify as minifier
from .check import (META_LINE_RE, STAMP_RE, TEXT_SECTION_RE, check_header, parse_header,
                    parse_tic, read_stamp, tic_code)
from .console import detail, fwd, show, step
from .header import CHUNK_RE, META_KEYS, cart_code

FREE_LIMIT = 65536  # the free editor's code cap (PRO edits up to 512 KB; every player loads it all)
MINIFY_RATE = 300_000         # bytes/s minify_max measures savings at, for the progress bar
ADDED = "(added by ticpak)"   # the savings row for the bundle's own lines: preload wrappers
DEFAULT_DIR = "dist/"         # the interactive build's default output folder


def out_kind(out):
    """What an -o value names: "tic" or "lua" for a file with that extension,
    else "dir" (a name ending in / or \\, or with neither extension)."""
    if out.endswith(("/", "\\")):
        return "dir"
    ext = os.path.splitext(out)[1].lower()
    return ext[1:] if ext in (".tic", ".lua") else "dir"


class Target:
    """One build's paths: the cart, the folder its modules sit in, and the
    outputs it keeps. Any output not kept is None.

      out None        <cart dir>/<name>.tic only (the default)
      out "x.tic"     x.tic only
      out "x.lua"     x.lua (the bundle) only
      out "dir/"      dir/<name>.lua and .tic, and with minification past
                      comments .minify.txt and .minify.json

    The name in a file -o is the file's own; `name` is used otherwise.
    report (-r; a folder build passes True without it): None for no report
    file (txt None), True for
    <name>.ticpak.txt beside the output, else a path: a folder (ending in /
    or \\, or one that exists) to put <name>.ticpak.txt in, or the file."""

    def __init__(self, cart, name, out=None, report=None):
        self.cart = os.path.abspath(cart)
        self.cart_dir = os.path.dirname(self.cart)
        self.kind = "tic" if out is None else out_kind(out)
        self.lua = self.tic = self.txt = self.map_txt = self.map_json = None
        if self.kind == "dir":
            self.name = name
            self.dist_dir = os.path.abspath(out)
            base = os.path.join(self.dist_dir, name)
            self.lua, self.tic = base + ".lua", base + ".tic"
            self.map_txt, self.map_json = base + ".minify.txt", base + ".minify.json"
        else:
            path = (os.path.join(self.cart_dir, name + ".tic") if out is None
                    else os.path.abspath(out))
            self.name = os.path.splitext(os.path.basename(path))[0]
            self.dist_dir = os.path.dirname(path)
            setattr(self, self.kind, path)
        report_name = self.name + ".ticpak.txt"
        if report is True:
            self.txt = os.path.join(self.dist_dir, report_name)
        elif report and (report.endswith(("/", "\\")) or os.path.isdir(report)):
            self.txt = os.path.join(os.path.abspath(report), report_name)
        elif report:
            self.txt = os.path.abspath(report)
        self.output = self.tic or self.lua      # the file the status line is about
        self.code = None                        # the bundle text, once built
        self.savings = None                     # minified: (by file, Savings, options)

    def module_path(self, module):
        return os.path.join(self.cart_dir, *module.split(".")) + ".lua"


def built_target(cart, name, report=None):
    """The package as already built, for a run without -o that only reads it
    (the bare command, check): <name>.tic beside the cart, or the folder build
    in DEFAULT_DIR (the interactive build's default), the newer if both
    exist. Neither built: the default, beside the cart."""
    default = Target(cart, name, None, report)
    built = [t for t in (default, Target(cart, name, DEFAULT_DIR, report))
             if os.path.isfile(t.output)]
    return max(built, key=lambda t: os.path.getmtime(t.output)) if built else default


def is_cart(path):
    """A file is a cart (rather than a module on its own) if it is main.lua or
    has asset sections or a metadata header. Both are read strictly, as a
    module's comments can look like either: a header needs two tags or more
    (state_title.lua opens `-- title: two planes sky-write...`), and asset
    sections run to the end of the file (a2boot.lua has a comment line
    `-- <MAP> region ...` mid-code)."""
    if os.path.basename(path).lower() == "main.lua":
        return True
    text = open(path, encoding="utf-8").read()
    return bool(minifier.split_cart(text)[2]) or len(parse_header(text)) >= 2


def find_cart(source=None):
    """The cart: SOURCE (a .lua file, or a directory searched like the cwd),
    else ./main.lua, else ./src/main.lua. None if there is none; exits if
    SOURCE does not exist or is a file other than .lua."""
    if source and not os.path.exists(source):
        sys.exit(f"ticpak: {source} not found")
    if source and os.path.isfile(source):
        if not source.lower().endswith(".lua"):
            sys.exit(f"ticpak: {source} is not a .lua file - give the cart"
                     " (main.lua), a module (.lua), or the folder holding main.lua")
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


def freshness(t, module=False):
    """(up_to_date, status line) for an existing package: is its output (and,
    for a folder output, the .lua bundle beside the .tic) newer than the cart
    and every module it requires? A folder output's report, or a module's,
    must exist too: only a build writes it in full. module: t.cart is a
    module on its own. Timestamps only - a changed option (--minify) or tool
    does not count."""
    built = os.path.getmtime(t.output)
    names = [] if module else stub_requires(cart_code(t.cart))[0]
    sources = [t.cart] + [t.module_path(n) for n in names]
    changed = [fwd(p) for p in sources
               if not os.path.isfile(p) or os.path.getmtime(p) > built]
    kept = [t.lua] + ([t.txt] if t.kind == "dir" or module else [])
    missing = [f"{fwd(p)} missing" for p in kept
               if p and p != t.output and not os.path.isfile(p)]
    label = "output" if module else "cart"
    if not changed and not missing:
        return True, f"{label}: {fwd(t.output)} (up-to-date)"
    listed = ", ".join(changed[:5]) + (f" and {len(changed) - 5} more"
                                       if len(changed) > 5 else "")
    why = "; ".join(([f"{listed} changed"] if changed else []) + missing)
    return False, f"{label}: {fwd(t.output)} (out-of-date: {why})"


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
    which did not build), with the output's `-- ticpak:` line as bundle()
    counts it; None if the modules cannot be assembled now."""
    import contextlib
    import io
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            size = len(assemble(t)[0].encode("utf-8"))
    except SystemExit:
        return None
    stamp = built_stamp(t.output)
    return size + (len(f"-- ticpak: {' '.join(stamp)}".rstrip()) + 1 if stamp else 0)


def minify_label(options):
    """'comments, rename, ...' in OPTIONS order, 'all', or 'none'."""
    if not options:
        return "none"
    if set(options) == set(minifier.OPTIONS):
        return "all"
    return ", ".join(o for o in minifier.OPTIONS if o in options)


def minify_flag(options):
    """The -m flag for options as the command line spells it: "-m" for every
    option, "-m=a,b" (in OPTIONS order) for some, "" for none."""
    if not options:
        return ""
    if options == minifier.ALL_OPTIONS:
        return "-m"
    return "-m=" + ",".join(o for o in minifier.OPTIONS if o in options)


def flag_options(flag):
    """minify_flag() read back: the options a -m flag names (options this
    version does not know are dropped)."""
    if flag == "-m":
        return minifier.ALL_OPTIONS
    items = [o for o in flag[3:].split(",") if o in minifier.OPTIONS] \
        if flag.startswith("-m=") else []
    return minifier.parse_options(items) if items else frozenset()


def add_stamp(code, options):
    """code with the `-- ticpak: VERSION [-m...]` line that records the build:
    after the last metadata tag of the leading comment block, or first when
    there is none (a module), replacing one already there. Added after
    minifying, which would strip it. Returns (code, n): the stamp is line n
    + 1, and lines from there on moved down one (n None: replaced in place)."""
    stamp = f"-- ticpak: {__version__} {minify_flag(options)}".rstrip()
    lines = code.split("\n")
    at = 0
    for i, line in enumerate(lines):
        s = line.strip()
        if s and not s.startswith("--"):
            break
        if STAMP_RE.match(s):
            lines[i] = stamp
            return "\n".join(lines), None
        m = META_LINE_RE.match(s)
        if m and m.group(1).lower() in META_KEYS:
            at = i + 1
    lines.insert(at, stamp)
    return "\n".join(lines), at


def built_stamp(path):
    """read_stamp() of an existing output (.tic or .lua); None if it has no
    `-- ticpak:` line or cannot be read."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    if path.lower().endswith(".tic"):
        code = tic_code(data, parse_tic(data)[0])
    else:
        code = data.decode("utf-8", errors="replace")
    return read_stamp(code)


def built_options(path):
    """The minify options an existing output was built with; None if unknown."""
    stamp = built_stamp(path)
    return flag_options(stamp[1]) if stamp else None


def options_label(options):
    """options for a message: the -m flag, or "no minification"."""
    return minify_flag(options) or "no minification"


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
    """Build the bundle into t.code, and write it to t.lua (plus, for a folder
    output, the decode maps) when the target keeps one. Returns its code size
    before minification (bytes)."""
    step("inline", "inlining modules")
    out, chunks, names, origin = assemble(t)
    raw = len(out.encode("utf-8"))

    if minify_options:
        step("minify", f"minifying {len(names)} modules ({minify_label(minify_options)})",
             raw / MINIFY_RATE)
    try:
        res = minifier.minify_cart_ex(out, mode=minify_options, meta_keys=META_KEYS,
                                      savings=bool(minify_options))
    except minifier.NominifyError as e:      # name the source file and line
        n = e.line
        where = (f"{origin[n - 1][0]}:{origin[n - 1][1]}"
                 if 0 < n <= len(origin) and origin[n - 1][0] else f"bundle line {n}")
        sys.exit(f"bundle: {where}: {e.msg}")
    except ValueError as e:
        sys.exit(f"bundle: {e}")
    out = res.text
    tag_lines(out, origin if not minify_options else None)
    out, at = add_stamp(out, minify_options)
    if at is not None:      # the decode map's output lines move down past it
        res.line_map = [(o + (o > at), i) for o, i in res.line_map]
    # The stamp is ticpak's own line, as the preload wrappers are: in the
    # size before minifying too, so the reduction compares like with like.
    stamp = len(out.encode("utf-8")) - len(res.text.encode("utf-8"))
    raw += stamp
    if res.savings is not None:
        def file_of(line):
            f = origin[line - 1][0] if 0 < line <= len(origin) else None
            return f or ADDED
        groups = res.savings.group(file_of)
        added = groups.pop(ADDED, {})               # last
        added["source"] = added.get("source", 0) + stamp
        added["final"] = added.get("final", 0) + stamp
        groups[ADDED] = added
        t.savings = (groups, res.savings, minify_options)
    if not check_header(out, quiet=True):
        check_header(out)
        sys.exit("bundle: the bundle lost header fields"
                 " in bundling - fix META_KEYS / minifier.split_cart")
    t.code = out + chunks

    if t.kind == "dir":     # a lone .lua is saved once it boots (save_bundle)
        save_bundle(t)
    if t.map_txt and res.report is not None:
        write_maps(t, res, origin)
    elif t.map_txt:
        # Maps from an earlier minified build would decode this bundle wrongly.
        for path in (t.map_txt, t.map_json):
            if os.path.isfile(path):
                os.remove(path)

    size = len(out)
    detail(f"bundle: {len(names)} modules inlined"
           + (f" -> {show(t.lua)}" if t.lua else " (kept in memory)"))
    if minify_options:
        detail(f"        code {raw} -> {size} chars "
               f"({100 * (1 - size / raw):.1f}% smaller; minify: {minify_label(minify_options)})")
    else:
        detail(f"        code {size} chars (not minified)")
    detail(f"        {100 * size / FREE_LIMIT:.1f}% of the {FREE_LIMIT} char free-editor code limit")
    if size > FREE_LIMIT:
        detail(f"  INFO  (non-PRO) code is over the 64 KB free-editor limit; fine on PRO"
               " (up to 512 KB), and every build's player loads it")
    if t.map_txt and res.report is not None:
        detail(f"        report and name/line maps -> {show(t.map_txt)},"
               f" {os.path.basename(t.map_json)}")
    return raw


def save_bundle(t):
    """Write the built bundle t.code to t.lua."""
    os.makedirs(os.path.dirname(t.lua), exist_ok=True)
    with open(t.lua, "w", encoding="utf-8") as f:
        f.write(t.code)


def minify_module(t, minify_options=frozenset()):
    """A module on its own (t.cart, no header or asset sections): minified as
    a fragment, so its globals are left alone, and written to t.lua. Returns
    (size before, size after) in bytes."""
    src = open(t.cart, encoding="utf-8").read()
    module_sections(src, os.path.basename(t.cart))
    step("minify", f"minifying {os.path.basename(t.cart)}", len(src) / MINIFY_RATE)
    try:
        res = minifier.minify_ex(src, mode=minify_options, whole_program=False,
                                 savings=bool(minify_options))
    except (ValueError, minifier.LuaSyntaxError) as e:
        sys.exit(f"minify: {show(t.cart)}: {e}")
    out = add_stamp(res.text, minify_options)[0]
    if res.savings is not None:
        name = os.path.basename(t.cart)
        t.savings = (res.savings.group(lambda line: name), res.savings, minify_options)
    os.makedirs(os.path.dirname(t.lua), exist_ok=True)
    with open(t.lua, "w", encoding="utf-8") as f:
        f.write(out)
    return len(src.encode("utf-8")), len(out.encode("utf-8"))


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
