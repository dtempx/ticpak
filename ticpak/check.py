#!/usr/bin/env python3
"""Check a TIC-80 .tic binary cart against machine limits.

Parses the .tic chunk stream (format verified against TIC-80 source cart.c)
and reports every chunk's size vs its RAM region maximum, code budget usage,
which of the 8 memory banks carry data, total file size, and whether the cart
carries a cover screenshot (a bank-0 SCREEN chunk — the `-- <SCREEN>` section
of a text cart; a missing one is a warning, not a failure). It also checks the cart's metadata
header, the `-- title:` / `-- author:` ... comments at the top of the code
that tic80.com and the cart browser read: every field in REQUIRED_META must be
present and filled in (not empty, not TIC-80's `new`-cart placeholder text).
A missing or incomplete header is a failure. Exits 0 if all checks pass, 1 if
any violation is found.

Given a text cart (.lua) instead of a .tic, it checks the header and reports
bank usage from the `-- <MAP1>`-style section tags, so the dev source and the
bundle can be checked with the same rule:

    ticpak check <game>.tic
    ticpak check main.lua                  # header + bank usage
    ticpak check -q <game>.tic             # violations and the exit code only

Banks and PRO. Every TIC-80 build's cart loader reads all 8 banks, and sync()
works in every build: TIC_BANKS is 8 unconditionally in tic.h, and neither
cart.c's loader nor core.c's tic_api_sync has a TIC80_PRO check (read in the
upstream source 2026-09-28, not yet confirmed on a live free/web player).
What PRO adds is authoring: the editors' bank switcher, a code editor past
64 KB, and text-format .lua carts. So code over 64 KB and data in banks 1-7
are reported as INFO lines marked (non-PRO), never as warnings or failures.

Chunk header layout (little-endian u32):
  bits 0-4:   type (5 bits, ChunkType enum)
  bits 5-7:   bank (3 bits, 0-7)
  bits 8-23:  size (16 bits; 0 means 64K for CODE/BINARY)
  bits 24-31: temp (8 bits, unused)
"""
import re
import struct
import sys
import zlib

CHUNK_TYPES = {
    1: "TILES", 2: "SPRITES", 3: "COVER_DEP", 4: "MAP", 5: "CODE", 6: "FLAGS",
    9: "SAMPLES", 10: "WAVEFORM", 12: "PALETTE", 14: "MUSIC",
    15: "PATTERNS", 16: "CODE_ZIP", 17: "DEFAULT", 18: "SCREEN",
    19: "BINARY", 20: "LANG",
}

CHUNK_RAM_LIMIT = {
    "TILES":    8192,
    "SPRITES":  8192,
    "MAP":      32640,
    "FLAGS":    512,
    "SAMPLES":  4224,
    "WAVEFORM": 256,
    "PATTERNS": 11520,
    "MUSIC":    408,
    "PALETTE":  96,
    "SCREEN":   16320,   # 240x136 at 4 bpp
}

# The cover image shown by tic80.com and the cart browser: a bank-0 SCREEN
# chunk, or the pre-0.80 GIF cover (COVER_DEP) that newer builds still read.
# A SCREEN in banks 1-7 is just a full-screen image loadable with sync(128, b).
COVER_CHUNKS = ("SCREEN", "COVER_DEP")

# Code is one program in one buffer (tic.h: tic_code.data[TIC_CODE_SIZE], 512 KB),
# never swapped by sync(). The .tic file stores it in 64 KB CODE chunks whose
# 3-bit "bank" field is only the chunk's position (cart.c), and the loader joins
# them back together. 64 KB is the free editor's cap; PRO edits up to 512 KB.
FREE_LIMIT = 65536
CODE_LIMIT = 8 * FREE_LIMIT
BANKS = 8

# Chunks that are per-bank asset data (what sync() swaps). CODE/BINARY
# chunks are one continuous program, not swappable data, and are reported apart;
# DEFAULT and LANG are cart-wide flags.
CODE_CHUNKS = ("CODE", "CODE_ZIP", "BINARY")
# Display order; a text cart's WAVES/SFX/TRACKS are the WAVEFORM/SAMPLES/MUSIC chunks.
BANK_ORDER = ("TILES", "SPRITES", "MAP", "FLAGS", "WAVEFORM", "WAVES", "SAMPLES",
              "SFX", "PATTERNS", "MUSIC", "TRACKS", "PALETTE", "SCREEN", "COVER_DEP")
# Text-cart section tags; banks 1-7 carry a digit suffix (`-- <MAP1>`).
TEXT_SECTION_RE = re.compile(
    r"^-- <(TILES|SPRITES|MAP|FLAGS|WAVES|SFX|PATTERNS|TRACKS|PALETTE|SCREEN)([1-7]?)>",
    re.M)

# The metadata header: the fields TIC-80's `new` cart template writes, all of
# which tic80.com shows on a cart's page. Every one must be present and filled.
REQUIRED_META = ("title", "author", "desc", "site", "license", "version", "script")
# Tags TIC-80 also reads but a cart may leave out.
OPTIONAL_META = ("saveid", "input", "menu")
# TIC-80's `new`-cart placeholder values: present but never filled in.
PLACEHOLDER_META = {
    "title": ("game title",),
    "author": ("game developer", "game developer, email, etc."),
    "desc": ("short description",),
    "site": ("website link",),
    "license": ("mit license (change this to your license of choice)",),
}
META_LINE_RE = re.compile(r"^--\s*([A-Za-z]+)\s*:(.*)$")


def parse_header(code):
    """Read the metadata tags from the code's leading comment block.

    Scans from the top through comment and blank lines, stopping at the first
    line of code, and returns {tag: value} for every known tag found there
    (the first occurrence wins, as it does in TIC-80).
    """
    known = REQUIRED_META + OPTIONAL_META
    meta = {}
    for line in code.splitlines():
        s = line.strip()
        if s and not s.startswith("--"):
            break
        m = META_LINE_RE.match(s)
        if m and m.group(1).lower() in known:
            meta.setdefault(m.group(1).lower(), m.group(2).strip())
    return meta


def check_header(code, quiet=False):
    """Check the metadata header in `code`. Returns True if complete."""
    meta = parse_header(code)
    ok = True
    if not meta:
        if not quiet:
            print("  MISSING  no metadata header - the code must start with"
                  " `-- title:`, `-- author:` ... comments")
        return False
    for tag in REQUIRED_META:
        value = meta.get(tag)
        if value is None:
            problem = "missing"
        elif not value:
            problem = "empty"
        elif value.lower() in PLACEHOLDER_META.get(tag, ()):
            problem = f"still TIC-80's placeholder ({value!r})"
        else:
            continue
        ok = False
        if not quiet:
            print(f"  MISSING  header field `-- {tag}:` {problem}")
    if not quiet:
        width = max(len(t) for t in meta)
        print("check:  header " + ("complete" if ok else "INCOMPLETE"))
        for tag in REQUIRED_META + OPTIONAL_META:
            if tag in meta:
                print(f"        {tag + ':':{width + 1}s} {meta[tag]}")
    return ok


def parse_tic(data):
    """Walk the .tic chunk stream. Returns list of (name, bank, size, offset)
    tuples, offset being where the chunk's payload starts."""
    chunks = []
    pos = 0
    while pos + 4 <= len(data):
        hdr = struct.unpack_from("<I", data, pos)[0]
        ctype = hdr & 0x1F
        bank = (hdr >> 5) & 0x07
        size_field = (hdr >> 8) & 0xFFFF
        if size_field == 0 and ctype in (5, 19):
            size = 65536
        else:
            size = size_field
        name = CHUNK_TYPES.get(ctype, f"?({ctype})")
        chunks.append((name, bank, size, pos + 4))
        pos += 4 + size
    return chunks, pos


def tic_code(data, chunks):
    """The cart's code as text: the CODE chunks joined from the highest bank
    down, as cart.c's loader does (RFOR) - TIC-80 saves the start of the code,
    and so the header, in the highest bank and the end in bank 0 - or a
    legacy zlib CODE_ZIP chunk."""
    banks = sorted(((b, off, size) for name, b, size, off in chunks if name == "CODE"),
                   reverse=True)
    code = b"".join(data[off:off + size] for _, off, size in banks)
    if not code:
        for name, _, size, off in chunks:
            if name == "CODE_ZIP":
                try:
                    code = zlib.decompress(data[off:off + size])
                except zlib.error:
                    pass
                break
    return code.rstrip(b"\0").decode("utf-8", errors="replace")


def bank_ranges(banks):
    """[2, 3, 4, 7] -> '2-4, 7'."""
    out, run = [], []
    for b in sorted(banks):
        if run and b != run[-1] + 1:
            out.append(run)
            run = []
        run.append(b)
    if run:
        out.append(run)
    return ", ".join(f"{r[0]}-{r[-1]}" if len(r) > 1 else f"{r[0]}" for r in out)


def report_banks(usage, code_banks=(), code_size=0, code=None, quiet=False):
    """Print which of the 8 banks carry asset data, plus the (non-PRO) INFO
    notes. usage maps bank -> [(section, bytes or None)]. When `code` is the
    cart's whole program, also warn if banks 1-7 carry data that no sync()
    call could ever load. Informational only: never fails the check."""
    if quiet:
        return
    used = sorted(b for b in usage if usage[b])
    print(f"check:  banks  {len(used)} of {BANKS} carry asset data"
          " (bank 0 boots; 1-7 load via sync())")
    for b in used:
        rows = sorted(usage[b], key=lambda r: BANK_ORDER.index(r[0])
                      if r[0] in BANK_ORDER else len(BANK_ORDER))
        parts = [f"{n} {s:,}" if s is not None else n for n, s in rows]
        print(f"        bank {b}   " + ", ".join(parts))
    unused = [b for b in range(BANKS) if b not in used]
    if unused:
        print(f"        unused   bank{'s' if len(unused) > 1 else ''} {bank_ranges(unused)}")
    if code_banks:
        nb = len(code_banks)
        split = f", stored as {nb} 64 KB chunks" if nb > 1 else ""
        print(f"        code     {code_size:,} chars{split} (one program, not banked;"
              f" limit {CODE_LIMIT // 1024} KB with PRO, {FREE_LIMIT // 1024} KB without)")
    if code_size > FREE_LIMIT:
        print(f"  INFO  (non-PRO) code is {code_size:,} chars, over the 64 KB free-editor"
              " cap; fine on PRO, and every build's player loads it")
    extra = [b for b in used if b > 0]
    if extra:
        print(f"  INFO  (non-PRO) bank{'s' if len(extra) > 1 else ''} {bank_ranges(extra)}"
              " carry data: the free editors show bank 0 only; fine on PRO,"
              " and every build's player loads them")
        if code is not None and not re.search(r"\bsync\s*\(", code):
            print(f"  WARN  bank{'s' if len(extra) > 1 else ''} {bank_ranges(extra)}"
                  " carry data but the code never calls sync() - it can never be"
                  " loaded at run time")


def check_lua(path, quiet=False):
    """Check a text cart's metadata header and report its bank usage.
    Returns True if the header is complete."""
    text = open(path, encoding="utf-8").read()
    if not quiet:
        print(f"check:  {path} (text cart - header and banks)")
    ok = check_header(text, quiet=quiet)
    usage = {}
    for m in TEXT_SECTION_RE.finditer(text):
        usage.setdefault(int(m.group(2) or 0), []).append((m.group(1), None))
    # A dev cart's code lives in the modules beside it, so the stub alone
    # cannot say whether sync() is called: skip that check here.
    report_banks(usage, quiet=quiet)
    return ok


def check_tic(path, quiet=False):
    """Parse the .tic binary and check limits. Returns True if clean."""
    data = open(path, "rb").read()
    total = len(data)
    ok = True
    chunks, end_pos = parse_tic(data)

    if end_pos != len(data) and not quiet:
        print(f"  WARN  {len(data) - end_pos} trailing bytes after last chunk")

    code_size = 0
    code_banks = set()
    usage = {}
    for name, bank, size, _ in chunks:
        if name in CODE_CHUNKS:
            code_banks.add(bank)
            code_size += size
        elif name in BANK_ORDER:
            usage.setdefault(bank, []).append((name, size))
        limit = CHUNK_RAM_LIMIT.get(name)
        if limit and size > limit:
            if not quiet:
                print(f"  OVER  {name} bank {bank}: {size:,} > {limit:,} bytes")
            ok = False

    if not quiet:
        print(f"check:  .tic file {total:,} bytes ({total / 1024:.1f} KB)")
        # code is saved start-first from the highest bank down: part 1 is the
        # highest-numbered CODE chunk
        top = {n: max((b for c, b, _, _ in chunks if c == n), default=0)
               for n in CODE_CHUNKS}
        for name, bank, size, _ in chunks:
            if name in CODE_CHUNKS:
                label = f"{name}" + (f" part {top[name] - bank + 1}" if top[name] else "")
            else:
                label = f"{name}" + (f" bank {bank}" if bank else "")
            if name in ("CODE", "CODE_ZIP"):
                pct = f" ({100 * size / FREE_LIMIT:.0f}% of a {FREE_LIMIT // 1024} KB chunk)"
            else:
                limit = CHUNK_RAM_LIMIT.get(name)
                pct = f" ({100 * size / limit:.0f}%)" if limit else ""
            print(f"        {label:20s} {size:>6,} bytes{pct}")

    code = tic_code(data, chunks)
    report_banks(usage, code_banks, code_size, code, quiet=quiet)

    if not check_header(code, quiet=quiet):
        ok = False

    has_screen = any(name in COVER_CHUNKS and bank == 0 for name, bank, _, _ in chunks)
    if not quiet:
        if has_screen:
            print("check:  screenshot (SCREEN) present")
        else:
            print("  WARN  no SCREEN chunk - the cart has no cover screenshot"
                  " (press F7 in-game to capture one, then save)")

    if total > 256 * 1024:
        if not quiet:
            print(f"  OVER  total file {total:,} bytes exceeds 256 KB")
        ok = False

    if not quiet:
        print("check:  all checks OK" if ok else "check:  VIOLATIONS FOUND")
    return ok
