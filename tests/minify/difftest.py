#!/usr/bin/env python3
"""Differential test for minify max mode: original vs minified, frame by frame.

Bundles a TIC-80 port exactly as ticpak does (no minification), minifies the
bundle with minify max mode, then runs both in two real Lua 5.3 states (lupa)
side by side under one deterministic stub of the TIC-80 API: RAM, map and
sprite flags loaded from the cart's own asset chunks, scripted button input,
a frame clock for time(), and an order-stable pairs(). Every API call that
produces output (drawing, sound, poke/memset/memcpy, pmem writes, trace, ...) is
logged with its exact arguments; the logs of the two runs must match frame for
frame. Any difference is a minify bug (or nondeterminism in the harness).

    python tests/minify/difftest.py path/to/game/tic80            # 3600 frames
    python tests/minify/difftest.py path/to/game/tic80 --frames=600 --seed=7
    python tests/minify/difftest.py --all                         # every port
    python tests/minify/difftest.py --all --coverage              # + lines executed

A port is a folder holding a TIC-80 cart's main.lua and its modules. --all
runs every <game>/tic80/ under $TICPAK_GAMES (e.g. the retrodev repo's games/).

Needs lupa (`pip install lupa`), a test-only dependency. Docs: docs/minify.md "Testing".
"""
import os, random, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)                    # the ticpak package, installed or not
from ticpak import minify  # noqa: E402

try:
    from lupa import lua53
except ImportError:
    sys.exit("difftest: needs lupa (pip install lupa) -- a real Lua 5.3 to run both builds")

STUB = r"""
local LOG, nlog = {}, 0
local fmt_num = function(v)
  if math.type(v) == "integer" then return tostring(v) end
  return string.format("%.17g", v)
end
local function fmt(v)
  local t = type(v)
  if t == "number" then return fmt_num(v)
  elseif t == "string" then return string.format("%q", v)
  elseif t == "boolean" or t == "nil" then return tostring(v)
  else return t end
end
local function log(name, ...)
  local n = select("#", ...)
  local p = {name, "("}
  for i = 1, n do p[#p + 1] = fmt((select(i, ...))); p[#p + 1] = "," end
  p[#p + 1] = ")"
  nlog = nlog + 1; LOG[nlog] = table.concat(p)
  if __H.trap == name then __H.hits = (__H.hits or "") .. debug.traceback(LOG[nlog], 3) .. "\n--\n" end
end
__H = {frame = 0, btn = 0, prev = 0, mem = {}, pmem = {}}
function __H.take()
  local s = table.concat(LOG, "\n", 1, nlog); LOG, nlog = {}, 0; return s
end
local mem = __H.mem
local function rd(a) return mem[a] or 0 end
local function bits_rd(addr, b)
  if b == 8 then return rd(addr) end
  local bit = addr * b
  return (rd(bit // 8) >> (bit % 8)) & ((1 << b) - 1)
end
local function bits_wr(addr, v, b)
  if b == 8 then mem[addr] = v & 0xff; return end
  local bit = addr * b
  local a, sh, m = bit // 8, bit % 8, (1 << b) - 1
  mem[a] = (rd(a) & ~(m << sh)) | ((v & m) << sh)
end
function peek(a, b) return bits_rd(a, b or 8) end
function peek1(a) return bits_rd(a, 1) end
function peek2(a) return bits_rd(a, 2) end
function peek4(a) return bits_rd(a, 4) end
function poke(a, v, b) log("poke", a, v, b); bits_wr(a, v, b or 8) end
function poke1(a, v) log("poke1", a, v); bits_wr(a, v, 1) end
function poke2(a, v) log("poke2", a, v); bits_wr(a, v, 2) end
function poke4(a, v) log("poke4", a, v); bits_wr(a, v, 4) end
function memcpy(d, s, n) log("memcpy", d, s, n)
  local t = {} for i = 0, n - 1 do t[i] = rd(s + i) end
  for i = 0, n - 1 do mem[d + i] = t[i] end end
function memset(d, v, n) log("memset", d, v, n) for i = 0, n - 1 do mem[d + i] = v end end
function mget(x, y)
  if x < 0 or y < 0 or x >= 240 or y >= 136 then return 0 end
  return rd(0x8000 + y * 240 + x) end
function mset(x, y, v) log("mset", x, y, v)
  if x >= 0 and y >= 0 and x < 240 and y < 136 then mem[0x8000 + y * 240 + x] = v end end
function fget(id, f) return (rd(0x14404 + id) >> f) & 1 == 1 end
function fset(id, f, v) log("fset", id, f, v)
  local a = 0x14404 + id
  if v then mem[a] = rd(a) | (1 << f) else mem[a] = rd(a) & ~(1 << f) end end
function pmem(i, v)
  local old = __H.pmem[i] or 0
  if v ~= nil then log("pmem", i, v); __H.pmem[i] = v end
  return old end
function btn(i)
  if i == nil then return __H.btn end
  return (__H.btn >> i) & 1 == 1 end
function btnp(i, hold, period)
  local edge = __H.btn & ~__H.prev
  if i == nil then return edge end
  return (edge >> i) & 1 == 1 end
function key() return false end
function keyp() return false end
function mouse() return 0, 0, false, false, false, 0, 0 end
function time() return __H.frame * (1000 / 60) end
function tstamp() return 1700000000 + __H.frame // 60 end
function print(t, ...) log("print", t, ...) return #tostring(t) * 6 end
function font(t, ...) log("font", t, ...) return #tostring(t) * 8 end
function trace(...) log("trace", ...) end
function exit() error("__EXIT__", 0) end
function reset() error("__RESET__", 0) end
-- sync(mask, bank, tocart): copy the chosen bank's sections into RAM
function sync(mask, bank, tocart)
  log("sync", mask, bank, tocart)
  mask, bank = mask or 0, bank or 0
  if mask == 0 then mask = 255 end
  if tocart then return end
  local b = __H.banks and __H.banks[bank] or {}
  for bit, sec in pairs(__H.secs or {}) do
    if mask & bit ~= 0 then
      local base, size, data = sec[1], sec[2], b[bit] or {}
      for a = base, base + size - 1 do mem[a] = data[a] end
    end
  end
end
for _, n in ipairs({"cls", "spr", "map", "rect", "rectb", "circ", "circb", "elli", "ellib",
                    "line", "tri", "trib", "textri", "ttri", "clip", "paint", "sfx", "music"}) do
  _G[n] = function(...) log(n, ...) end
end
function pix(x, y, c) if c == nil then return 0 end log("pix", x, y, c) end
function vbank(id) log("vbank", id) return 0 end
function fft() return 0 end
function ffts() return 0 end
-- order-stable pairs: two Lua states hash strings with different seeds
local _next, _type, _sort = next, type, table.sort
local function keycmp(a, b)
  local ta, tb = _type(a), _type(b)
  if ta ~= tb then return ta < tb end
  if ta == "number" or ta == "string" then return a < b end
  if ta == "boolean" then return (a and 1 or 0) < (b and 1 or 0) end
  return tostring(a) < tostring(b)
end
function pairs(t)
  local mt = getmetatable(t)
  if mt and mt.__pairs then return mt.__pairs(t) end
  local keys = {}
  for k in _next, t do keys[#keys + 1] = k end
  _sort(keys, keycmp)
  local i = 0
  return function()
    while true do
      i = i + 1
      local k = keys[i]
      if k == nil then return nil end
      local v = t[k]
      if v ~= nil then return k, v end
    end
  end, t, nil
end
-- Lua 5.3's math.random is C rand(): ONE generator shared by every Lua state in
-- the process, so two builds stepped in lockstep would draw each other's
-- numbers. Each state gets its own 64-bit LCG with the same interface instead.
local rng = 12345
local function rnext()
  rng = rng * 6364136223846793005 + 1442695040888963407
  return (rng >> 11) * (1.0 / 9007199254740992.0)
end
function math.randomseed(x) rng = math.tointeger(x) or math.floor(x) end
function math.random(m, n)
  local r = rnext()
  if m == nil then return r end
  if n == nil then m, n = 1, m end
  return m + math.floor(r * (n - m + 1))
end
function __H.load(code)
  local f, err = load(code, "=cart")
  if not f then return "SYNTAX:" .. err end
  local ok, e = pcall(f)
  if not ok then return "ERR:" .. tostring(e) end
  if BOOT then ok, e = pcall(BOOT) if not ok then return "ERR:" .. tostring(e) end end
  return "OK"
end
function __H.step(mask)
  __H.prev, __H.btn = __H.btn, mask
  __H.frame = __H.frame + 1
  local ok, e = pcall(TIC)
  if ok and OVR then ok, e = pcall(OVR) end
  if ok and (BDR or SCN) then
    local f = BDR or SCN
    for r = 0, 143 do ok, e = pcall(f, r) if not ok then break end end
  end
  if not ok then return "ERR:" .. tostring(e) end
  return "OK"
end
"""

# RAM layout of the asset chunks loaded into the stub (bank 0 only)
CHUNK_RAM = {"TILES": 0x4000, "SPRITES": 0x6000, "MAP": 0x8000, "FLAGS": 0x14404,
             "PALETTE": 0x3FC0}
LINE_BYTES = {"TILES": 32, "SPRITES": 32, "MAP": 240, "FLAGS": 256, "PALETTE": 48}


SYNC_BITS = {"TILES": 1, "SPRITES": 2, "MAP": 4, "FLAGS": 64, "PALETTE": 32}
SECTION_SIZE = {"TILES": 0x2000, "SPRITES": 0x2000, "MAP": 240 * 136, "FLAGS": 512, "PALETTE": 48}


def chunk_banks(chunks):
    """{bank: {section: {addr: byte}}} from the cart's asset chunks (all 8 banks)."""
    banks = {}
    for m in re.finditer(r"^-- <([A-Z]+)(\d?)>\n(.*?)^-- </\1\2>", chunks, re.S | re.M):
        name, bank, body = m.group(1), int(m.group(2) or 0), m.group(3)
        if name not in CHUNK_RAM:
            continue
        base, per = CHUNK_RAM[name], LINE_BYTES[name]
        sec = banks.setdefault(bank, {}).setdefault(name, {})
        for ln in body.splitlines():
            mm = re.match(r"-- (\d+):([0-9a-fA-F]+)", ln)
            if not mm:
                continue
            row, hx = int(mm.group(1)), mm.group(2)
            for k in range(len(hx) // 2):
                byte = int(hx[2 * k:2 * k + 2], 16)
                if name != "PALETTE":
                    byte = ((byte & 15) << 4) | (byte >> 4)
                if byte:
                    sec[base + row * per + k] = byte
    return banks


def chunk_memory(chunks):
    mem = {}
    for sec in chunk_banks(chunks).get(0, {}).values():
        mem.update(sec)
    return mem


def install_banks(rt, H, chunks):
    """Bank 0 into RAM, every bank into __H.banks for the stub's sync()."""
    banks = chunk_banks(chunks)
    for sec in banks.get(0, {}).values():
        for a, v in sec.items():
            H.mem[a] = v
    lb = rt.eval("{}")
    for bank, secs in banks.items():
        t = rt.eval("{}")
        for name, data in secs.items():
            d = rt.eval("{}")
            for a, v in data.items():
                d[a] = v
            t[SYNC_BITS[name]] = d
        lb[bank] = t
    H.banks = lb
    sizes = rt.eval("{}")
    for name, bit in SYNC_BITS.items():
        sizes[bit] = rt.eval("{}")
        sizes[bit][1] = CHUNK_RAM[name]; sizes[bit][2] = SECTION_SIZE[name]
    H.secs = sizes


class _Bundler:
    """ticpak's bundle for one port, with its header rule switched off (a
    packaging rule, not a test concern): assemble() and META_KEYS."""

    def __init__(self, port):
        from ticpak import bundle, header
        self.bundle, self.META_KEYS = bundle, header.META_KEYS
        self.target = bundle.Target(os.path.join(port, "main.lua"), "difftest", port)

    def assemble(self):
        saved = self.bundle.check_header
        self.bundle.check_header = lambda code, quiet=False: True
        try:
            return self.bundle.assemble(self.target)
        finally:
            self.bundle.check_header = saved


def load_ticpak(port):
    return _Bundler(port)


def inputs(seed, frames):
    """Per-frame button masks: idle (attract), then start presses and play."""
    rnd = random.Random(seed)
    out, hold, mask = [], 0, 0
    for f in range(frames):
        if f < 200:
            out.append(0); continue
        if hold == 0:
            r = rnd.random()
            if r < 0.15: mask, hold = 1 << 4, rnd.randint(2, 6)         # A: start / fire
            elif r < 0.25: mask, hold = 1 << 5, rnd.randint(2, 6)       # B
            elif r < 0.35: mask, hold = 0, rnd.randint(5, 40)
            else:
                mask = (1 << rnd.randint(0, 3)) | ((1 << 4) if rnd.random() < 0.4 else 0)
                hold = rnd.randint(5, 60)
        hold -= 1
        out.append(mask)
    return out


def norm_err(e):
    e = re.sub(r"cart:\d+:", "cart:?:", e)
    return re.sub(r"'[A-Za-z_][A-Za-z0-9_]*'", "'?'", e)


def run_port(port, frames, seed, passes=None, quiet=False, coverage=False):
    port = os.path.abspath(port)
    tp = load_ticpak(port)
    try:
        code, chunks, names, origin = tp.assemble()
    except SystemExit as e:
        print(f"{os.path.basename(os.path.dirname(port))}: SKIP (cannot bundle: {e})")
        return None
    t0 = time.time()
    opts = {"passes": passes} if passes is not None else {}
    try:
        res = minify.minify_cart_ex(code, mode="max", meta_keys=tp.META_KEYS, **opts)
    except ValueError:                       # no metadata header at all
        res = minify.minify_ex(code, mode="max", **opts)
    t_min = time.time() - t0
    rts = []
    for src in (code, res.text):
        rt = lua53.LuaRuntime(unpack_returned_tuples=True)
        rt.execute(STUB)
        H = rt.globals().__H
        install_banks(rt, H, chunks)
        rts.append((rt, H, src))
    game = os.path.basename(os.path.dirname(port))
    if not quiet:
        print(f"{game}: {len(code):,} -> {len(res.text):,} chars ({t_min:.1f}s), "
              f"{len(names)} modules, {frames} frames, seed {seed}")
    st = [H.load(src) for rt, H, src in rts]
    logs = [H.take() for rt, H, src in rts]
    if st[0].startswith("SYNTAX") or st[1].startswith("SYNTAX"):
        print(f"  FAIL load: original={st[0][:200]!r} minified={st[1][:200]!r}")
        return False
    if not compare(game, 0, logs, st):
        return False
    if st[0] != "OK":
        print(f"  note: both stopped at load: {st[0][:160]}")
        return True
    masks = inputs(seed, frames)
    if coverage:
        rts[0][0].execute("__COV = {} debug.sethook(function(_, l) __COV[l] = true end, 'l')")
    t0, last = time.time(), time.time()
    for f, m in enumerate(masks, 1):
        st = [H.step(m) for rt, H, src in rts]
        logs = [H.take() for rt, H, src in rts]
        if not compare(game, f, logs, st):
            return False
        if st[0] != "OK":
            print(f"  both stopped at frame {f}: {st[0][:160]}")
            return True
        now = time.time()
        if not quiet and now - last > 10:
            rate = f / (now - t0)
            print(f"  ... {100 * f / frames:.0f}% ({f}/{frames} frames, {rate:.0f} f/s, "
                  f"ETA {(frames - f) / rate:.0f}s)")
            last = now
    if not quiet:
        print(f"  OK: {frames} frames identical ({time.time() - t0:.1f}s)")
    if coverage:
        report_coverage(rts[0][0], code)
    return True


def report_coverage(rt, code):
    """Share of the original's code lines that ran (lines holding a token)."""
    cov = rt.globals().__COV
    hit = {int(k) for k in cov.keys()}
    code_lines = {ln for kind, text, ln in minify.lex_lines(code)}
    _, body, _ = minify.split_cart(code)
    print(f"  coverage: {len(hit & code_lines)}/{len(code_lines)} code lines executed "
          f"({100 * len(hit & code_lines) / max(1, len(code_lines)):.0f}%)")


def compare(game, frame, logs, st):
    sa, sb = st
    if sa != sb and not (sa.startswith("ERR:") and sb.startswith("ERR:")
                         and norm_err(sa) == norm_err(sb)):
        print(f"  FAIL frame {frame}: original -> {sa[:200]!r}\n"
              f"                 minified -> {sb[:200]!r}")
        show(logs)
        return False
    if logs[0] != logs[1]:
        print(f"  FAIL frame {frame}: API call logs differ")
        show(logs)
        return False
    return True


def show(logs):
    a, b = logs[0].split("\n"), logs[1].split("\n")
    for i in range(max(len(a), len(b))):
        x = a[i] if i < len(a) else "<none>"
        y = b[i] if i < len(b) else "<none>"
        if x != y:
            for j in range(max(0, i - 3), i):
                print(f"      = {a[j][:150]}")
            print(f"      - {x[:150]}\n      + {y[:150]}")
            return


def all_ports():
    """Every port under $TICPAK_GAMES: a folder of <game>/tic80/main.lua (the
    retrodev repo's games/, say). [] when it isn't set."""
    g = os.environ.get("TICPAK_GAMES")
    if not g or not os.path.isdir(g):
        return []
    return sorted(os.path.join(g, d, "tic80") for d in os.listdir(g)
                  if os.path.exists(os.path.join(g, d, "tic80", "main.lua")))


if __name__ == "__main__":
    args = sys.argv[1:]
    frames, seed, passes, coverage = 3600, 1, None, False
    ports = []
    for a in args:
        if a.startswith("--frames="): frames = int(a.split("=", 1)[1])
        elif a.startswith("--seed="): seed = int(a.split("=", 1)[1])
        elif a.startswith("--passes="): passes = [p for p in a.split("=", 1)[1].split(",") if p]
        elif a == "--all": ports = all_ports()
        elif a == "--coverage": coverage = True
        else: ports.append(a)
    if not ports:
        sys.exit(__doc__)
    results = {p: run_port(p, frames, seed, passes, coverage=coverage) for p in ports}
    bad = [p for p, r in results.items() if r is False]
    skipped = [p for p, r in results.items() if r is None]
    print(f"difftest: {len(ports) - len(bad) - len(skipped)}/{len(ports)} ports identical"
          + (f", {len(skipped)} skipped" if skipped else ""))
    sys.exit(1 if bad else 0)
