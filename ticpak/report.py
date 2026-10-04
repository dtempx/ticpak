#!/usr/bin/env python3
"""The check for ticpak: check.py's report on the .tic, written flat to
<out>/<name>.txt, and the closing size summary on screen.
"""
import contextlib
import io
import re
import sys

from . import console                    # console.VERBOSE is read live (-v)
from .bundle import FREE_LIMIT
from .check import check_tic, parse_tic, CHUNK_RAM_LIMIT, CODE_CHUNKS, COVER_CHUNKS
from .console import detail, flat_line, show
from .header import META_KEYS

NEAR = 0.90           # the detail flags anything at or above this share of a limit
TIC_FILE_LIMIT = 256 * 1024


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


def size_summary(tic, unminified=None):
    """The closing summary, as lines: the .tic's total size;
    its code and its assets with their shares of that total; the code against
    the 64K free-editor limit; and, when known, the unminified code size and
    the reduction (or `not minified`)."""
    with open(tic, "rb") as f:
        data = f.read()
    chunks, _ = parse_tic(data)
    total = len(data)
    code = sum(size for name, _, size, _ in chunks if name in CODE_CHUNKS)
    asset = sum(size for name, _, size, _ in chunks if name in CHUNK_RAM_LIMIT)

    def share(n):
        return f"{100 * n / total:.0f}%" if total else "0%"

    used = round(100 * code / FREE_LIMIT)
    lines = [f"size: {kb(total)}",
             f"code: {kb(code)} ({share(code)})",
             f"assets: {kb(asset)} ({share(asset)})",
             f"{kb(code)} / {kb(FREE_LIMIT)} code size limit"
             + (f" ({used}% used) - over the free editor's limit, fine on PRO (up to 512K)"
                if code > FREE_LIMIT else f" ({used}% used, {100 - used}% free)")]
    if unminified is not None and unminified - code > 16:
        lines.append(f"{kb(unminified)} unminified"
                     f" ({100 * (1 - code / unminified):.0f}% reduction)")
    elif unminified is not None:
        lines.append("not minified")
    return lines


def check_summary(t, unminified=None, write_report=True, full=False):
    """The check: check.py's full report plus the size summary to t.txt; on
    screen the summary last, with the report's detail (sizes, anything near
    (>= 90%) or past a limit, every flagged line) only with -v, or the whole
    report with full (`check -v`). Violations always show. Exits 1 on one."""
    tic = t.tic
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ok = check_tic(tic)
    summary = size_summary(tic, unminified)
    if write_report:
        with open(t.txt, "w", encoding="utf-8") as f:
            f.write(f"check: {show(tic)}\n" + flatten_report(buf.getvalue())
                    + "\n" + "\n".join(summary) + "\n")

    if full and console.VERBOSE:         # `check -v`: the whole check report
        print(f"check:  {show(tic)}")
        print(buf.getvalue(), end="")
        print("\n".join(summary))
        if not ok:
            sys.exit(1)
        return

    with open(tic, "rb") as f:
        data = f.read()
    chunks, _ = parse_tic(data)
    code = sum(size for name, _, size, _ in chunks if name in CODE_CHUNKS)
    total = len(data)
    detail(f"check:  {show(tic)} {total:,} bytes ({100 * total / TIC_FILE_LIMIT:.0f}%"
           f" of 256 KB); code {code:,} chars ({100 * code / FREE_LIMIT:.0f}% of the"
           " 64 KB free-editor limit)")

    near = []
    if total >= NEAR * TIC_FILE_LIMIT:
        near.append(f"file {100 * total / TIC_FILE_LIMIT:.0f}%")
    if code >= NEAR * FREE_LIMIT:
        near.append(f"code {100 * code / FREE_LIMIT:.0f}%")
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
            print(line)                     # violations show without -v
        elif re.match(r"\s+(WARN|INFO)\b", line):
            detail(line)
    if console.VERBOSE or not ok:
        print(("check:  all checks OK" if ok else "check:  VIOLATIONS FOUND")
              + (f" - full report in {show(t.txt)}" if write_report else ""))
    print("\n".join(summary))
    if not ok:
        sys.exit(1)
