#!/usr/bin/env python3
"""The check for ticpak: check.py's report on the .tic, the closing size
summary on screen, the --verbose detail (minify savings included), and the
full report written flat to the -r file (<name>.bundle.txt).
"""
import contextlib
import io
import os
import re
import sys

from . import console                    # console.VERBOSE is read live (--verbose)
from . import minify as minifier
from .bundle import flag_options, minify_label
from .check import (check_tic, parse_tic, read_stamp, tic_code, CHUNK_RAM_LIMIT,
                    CODE_CHUNKS, CODE_LIMIT, COVER_CHUNKS, FREE_LIMIT)
from .console import detail, flat_line, fwd, show, tint
from .header import META_KEYS

NEAR = 0.90           # anything at or above this share of a limit is flagged


def flatten_report(text):
    """the checker's screen report as a flat file: no indentation, no `check:`
    prefixes, and `tag: value` header lines without their alignment padding.
    Spacing inside a line (the size table's columns) is kept."""
    meta = re.compile(r"^(%s):\s+" % "|".join(META_KEYS))
    out = []
    for line in text.splitlines():
        line = re.sub(r"^check:\s+", "", line.strip())
        out.append(meta.sub(r"\1: ", flat_line(line)))
    return "\n".join(out) + "\n"


def kb(n):
    """Bytes as K: two decimals under 1K, one under 10K, whole K above."""
    if n < 1024:
        return f"{n / 1024:.2f}K"
    return f"{n / 1024:.1f}K" if n < 10240 else f"{n / 1024:.0f}K"


def savings_table(groups, options):
    """The minify savings, as lines: per source file (groups: {file: {key:
    bytes}}, Savings.group's) and in total, the code's source size, what
    each option took off it, and the code after (total), in bytes, then
    the reduction as a percentage; a blank line ends it. A column for
    each of options, whitespace (every option relexes the code), and any
    other option that changed something."""
    total = {}
    for g in groups.values():
        for k, n in g.items():
            total[k] = total.get(k, 0) + n
    cols = [k for k in minifier.SAVINGS
            if k in options or k == "whitespace" or total.get(k)]
    rows = list(groups.items()) + ([("total", total)] if len(groups) > 1 else [])
    keys = ["source"] + cols + ["final"]
    heads = ["source"] + cols + ["total", "reduction"]
    cells = [[f"{g.get(k, 0):,}" for k in keys] + [reduction(g)] for _, g in rows]
    w = max(len(f) for f, _ in rows)
    ws = [max([len(h)] + [len(c[i]) for c in cells]) for i, h in enumerate(heads)]
    out = ["minify: bytes saved, by file and option (negative: the option added bytes)",
           f"{'file':<{w}}" + "".join(f"  {h:>{n}}" for h, n in zip(heads, ws))]
    for (f, g), row in zip(rows, cells):
        line = f"{f:<{w}}" + "".join(f"  {c:>{n}}" for c, n in zip(row, ws))
        if g.get("source") and not g.get("final") and f != "total":
            line += "  (removed: unused)"
        out.append(line)
    return out + [""]


def reduction(g):
    """A savings row's source-to-final reduction, as a percentage."""
    source = g.get("source", 0)
    return f"{100 * (1 - g.get('final', 0) / source):.0f}%" if source else "-"


def made_of_lines(sv):
    """What the minified code is made of, and the biggest names that stayed,
    as lines (empty when the minifier did not say: comments only)."""
    if not sv.left:
        return []
    w = max(len(what) for what, _ in sv.left)
    n_w = max(len(f"{n:,}") for _, n in sv.left)
    out = ["minify: what the minified code is made of (bytes)"]
    out += [f"{what:<{w}}  {n:>{n_w},}" for what, n in sv.left]
    if sv.names:
        out.append("biggest names that stayed (bytes, all uses): "
                   + ", ".join(f"{name} {n:,}" for name, n in sv.names[:8]))
    return out


def write_report(t, text):
    """The -r report: text to t.txt, when the build asked for one, and a
    `report:` line naming it."""
    if t.txt is None:
        return
    os.makedirs(os.path.dirname(t.txt), exist_ok=True)
    with open(t.txt, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"report: {fwd(t.txt)}")


def size_summary(tic, unminified=None, colour=False):
    """The closing summary, as lines: the .tic's total size;
    its code and its assets with their shares of that total; the code against
    TIC-80's 512K code limit, yellow from NEAR and red at the limit (colour:
    for the screen, when it shows colour); when known, the unminified code
    size and the reduction (or `not minified`); and last, for code over 64K,
    that editing it in TIC-80 needs PRO."""
    with open(tic, "rb") as f:
        data = f.read()
    chunks, _ = parse_tic(data)
    total = len(data)
    code = sum(size for name, _, size, _ in chunks if name in CODE_CHUNKS)
    asset = sum(size for name, _, size, _ in chunks if name in CHUNK_RAM_LIMIT)

    def share(n):
        return f"{100 * n / total:.0f}%" if total else "0%"

    used = round(100 * code / CODE_LIMIT)
    limit = f"code limit: {kb(code)} / {kb(CODE_LIMIT)}"
    if code >= CODE_LIMIT:      # a .tic made elsewhere: TIC-80 cuts the code off
        level, limit = "error", limit + f" ({used}% used) - over TIC-80's code limit"
    elif code >= NEAR * CODE_LIMIT:
        level = "warn"
        limit += f" ({used}% used, {100 - used}% free) - close to TIC-80's code limit"
    else:
        level, limit = None, limit + f" ({used}% used, {100 - used}% free)"
    lines = [f"cart size: {kb(total)}",
             f"code: {kb(code)} ({share(code)})",
             f"assets: {kb(asset)} ({share(asset)})",
             tint(limit, level) if colour else limit]
    stamp = read_stamp(tic_code(data, chunks))
    if stamp:               # built by ticpak 0.3.4+: it says how it was minified
        options = flag_options(stamp[1], stamp[0])
        if not options:
            lines.append("not minified")
        elif unminified is not None:
            lines.append(f"original code size: {kb(unminified)}"
                         f" ({100 * (1 - code / unminified):.0f}% reduction"
                         f" with minify: {minify_label(options)})")
        else:
            lines.append(f"minify: {minify_label(options)}")
    elif unminified is not None and unminified - code > 16:
        lines.append(f"original code size: {kb(unminified)}"
                     f" ({100 * (1 - code / unminified):.0f}% reduction)")
    elif unminified is not None:
        lines.append("not minified")
    if code > FREE_LIMIT:
        lines.append("info: code over 64K needs TIC-80 PRO to edit it in TIC-80"
                     " (the cart plays in every TIC-80)")
    return lines


def check_summary(t, unminified=None, full=False, tic=None):
    """The check of tic (default t.tic). On screen the summary last, with
    the report's detail (sizes, anything near (>= 90%) or past a limit,
    every flagged line, and after a minified build (t.savings) what each
    option saved and what the code is made of) only with --verbose, or the
    whole check report with full (`check --verbose`). Violations always
    show. With -r (t.txt), all of it - check.py's full report, the savings
    and the summary - also goes to t.txt. Exits 1 on a violation."""
    tic = tic or t.tic
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ok = check_tic(tic)
    summary = size_summary(tic, unminified)
    shown = size_summary(tic, unminified, colour=True)
    saved = []
    if t.savings is not None:
        groups, sv, options = t.savings
        saved = savings_table(groups, options) + made_of_lines(sv)
    report = (f"check: {show(tic)}\n" + flatten_report(buf.getvalue()) + "\n"
              + "".join(line + "\n" for line in saved) + "\n".join(summary) + "\n")

    if full and console.VERBOSE:         # `check --verbose`: the whole check report
        print(f"check:  {show(tic)}")
        print(buf.getvalue(), end="")
        print("\n".join(shown))
        write_report(t, report)
        if not ok:
            sys.exit(1)
        return

    with open(tic, "rb") as f:
        data = f.read()
    chunks, _ = parse_tic(data)
    code = sum(size for name, _, size, _ in chunks if name in CODE_CHUNKS)
    total = len(data)
    where = show(tic) if tic == t.tic else "the .tic (not kept)"
    detail(f"check:  {where} {total:,} bytes; code {code:,} chars"
           f" ({100 * code / CODE_LIMIT:.0f}% of TIC-80's {CODE_LIMIT // 1024} KB code limit)")

    near = []
    if code >= NEAR * CODE_LIMIT:
        near.append(f"code {100 * code / CODE_LIMIT:.0f}%")
    for name, bank, size, _ in chunks:
        limit = CHUNK_RAM_LIMIT.get(name)
        # a cover is always a full 240x136 image: its 100% is no warning
        if limit and size >= NEAR * limit and not (name in COVER_CHUNKS and bank == 0):
            near.append(f"{name}{f' bank {bank}' if bank else ''}"
                        f" {100 * size / limit:.0f}%")
    if near:
        detail(f"  NEAR  at or near capacity: {', '.join(near)}")
    for line in buf.getvalue().splitlines():
        if re.match(r"\s+(OVER|MISSING)\b", line):
            print(line)                     # violations show without --verbose
        elif re.match(r"\s+(WARN|INFO)\b", line):
            detail(line)
    if console.VERBOSE or not ok:
        print("check:  all checks OK" if ok else "check:  VIOLATIONS FOUND")
    for line in saved:
        detail(line)
    print("\n".join(shown))
    write_report(t, report)
    if not ok:
        sys.exit(1)
