#!/usr/bin/env python3
"""minify test suite (needs lupa: pip install lupa).

    python tests/minify/run.py            # all three suites
    python tests/minify/run.py fixtures   # or: fold, bytecode, fixtures

fold      constant evaluator vs real Lua 5.3: random constant expressions are
          evaluated by minify (spec D7) and by Lua; every value it folds must
          match exactly (type, integer/float subtype, bytes), and the literal it
          would emit must read back as the same value.
bytecode  spec R10c: with only comment removal, layout and local renaming
          (fragment mode, the rename-vars pass), every port's bundle compiles
          to the same stripped bytecode before and after.
fixtures  fixtures.lua: small programs (printing through trace(), a reserved
          TIC-80 name, since whole-program mode renames unknown globals) aimed at the risky transforms (scoping,
          shadowing, multiple assignment, varargs, goto, negative inlining,
          and/or folding, dead branches with locals, table keys, ...). Each is
          run original and minified (max: every option); the printed output
          must be identical. A "table keys" case must have rename-tables on,
          or off when its name says "(pass off)".

The whole-program behaviour check is difftest.py.
"""
import os, random, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)                    # the ticpak package, installed or not
sys.path.insert(0, HERE)
from ticpak import minify as L  # noqa: E402

try:
    from lupa import lua53
except ImportError:
    sys.exit("run.py: needs lupa (pip install lupa)")


def lua():
    return lua53.LuaRuntime(unpack_returned_tuples=True, encoding=None)


# ----------------------------------------------------------------- fold fuzz

ATOMS = ["0", "1", "2", "3", "7", "-1", "-7", "10", "255", "0x7f", "0xff", "1.5", "0.5", "-2.5",
         "2.0", "0.0", "-0.0", "1e3", "3.25", "9223372036854775807", "0x7fffffffffffffff",
         "64", "63", "-64", "100", '"a"', '"10"', "'xy'", "true", "false", "nil", "1/3",
         "0.1", "0.2", "1e15", "1e16", "123456789012", "2^53", "-0x8000000000000000"]
BIN = ["+", "-", "*", "/", "//", "%", "^", "&", "|", "~", "<<", ">>", "..", "==", "~=",
       "<", "<=", ">", ">=", "and", "or"]
UN = ["-", "not ", "~", "#"]


def gen(rnd, d):
    if d <= 0 or rnd.random() < 0.3:
        return rnd.choice(ATOMS)
    r = rnd.random()
    if r < 0.15:
        return rnd.choice(UN) + "(" + gen(rnd, d - 1) + ")"
    return "(" + gen(rnd, d - 1) + " " + rnd.choice(BIN) + " " + gen(rnd, d - 1) + ")"


def lua_value(rt, expr):
    f = rt.eval('function(s) local f = load("return " .. s) local ok, v = pcall(f) '
                'if not ok then return "E" end '
                'if math.type(v) == "integer" then return "i" .. string.format("%d", v) end '
                'if math.type(v) == "float" then return "f" .. string.format("%a", v) end '
                'if type(v) == "string" then return "s" .. v end '
                'return "o" .. tostring(v) end')
    return f(expr.encode())


def mine(v):
    k = v[0]
    if k == "int": return b"i%d" % v[1]
    if k == "float": return b"f" + float.hex(v[1]).encode()
    if k == "str": return b"s" + v[1]
    if k == "bool": return b"o" + (b"true" if v[1] else b"false")
    return b"onil"


def norm_hex(b):
    # C's %a and Python's float.hex spell the same double differently; compare as floats
    if b[:1] == b"f":
        s = b[1:].decode()
        try:
            return b"f" + repr(float.fromhex(s.replace("0x0p+0", "0x0p0"))).encode()
        except ValueError:
            return b
    return b


def suite_fold(n=4000):
    rt, rnd = lua(), random.Random(11)
    folded = bad = 0
    for _ in range(n):
        src = gen(rnd, rnd.randint(1, 4))
        e = L.parse(L.lex_lines("return " + src)).stmts[0].exprs[0]
        v = L.const_eval(e)
        if v is None:
            continue
        folded += 1
        want = lua_value(rt, src)
        got = mine(v)
        if norm_hex(want) != norm_hex(got):
            bad += 1
            if bad <= 10: print(f"  fold MISMATCH {src}: lua={want!r} minify={got!r}")
            continue
        r = L.value_lit(v, 0)
        if r is None:
            continue
        text = "".join(t[1] if t[0] != "op" else t[1] for t in L.emit_tree(r[0]))
        back = lua_value(rt, " ".join(t[1] for t in L.emit_tree(r[0])))
        if norm_hex(back) != norm_hex(want):
            bad += 1
            if bad <= 10: print(f"  literal MISMATCH {src}: emitted {text!r} reads back {back!r}, want {want!r}")
    print(f"fold: {folded} of {n} random expressions folded, {bad} mismatches")
    return bad == 0


# ------------------------------------------------------------ bytecode proof

def renamed_on_source_lines(src):
    """Fragment-mode local renaming, each token kept on its source line.

    string.dump(f, true) drops line info but still writes every function's
    linedefined / lastlinedefined (Lua 5.3 ldump.c), so the proof keeps the
    line structure and varies only what renaming changes.
    """
    prog = L.reparse(L.lex_lines(src))
    L.pass_rename(L.Info(prog, False), L.Report())
    out, line, prev = [], 1, None
    for kind, text, ln in L.strip_nl(L.emit_tree(prog)):
        if ln > line:
            out.append("\n" * (ln - line)); line = ln; prev = None
        if prev is not None and L._needs_space(prev[0], prev[1], kind, text):
            out.append(" ")
        out.append(text); prev = (kind, text)
        line += text.count("\n")
    return "".join(out)


def suite_bytecode():
    import difftest as D
    rt = lua()
    dump = rt.eval('function(s) local f, e = load(s, "=x") if not f then return "ERR " .. e end '
                   'return string.dump(f, true) end')
    ok = True
    ports = D.all_ports()
    if not ports:
        print("  skipped: set TICPAK_GAMES to a folder of <game>/tic80/ ports")
    for port in ports:
        game = os.path.basename(os.path.dirname(port))
        tp = D.load_ticpak(port)
        try:
            code, chunks, names, origin = tp.assemble()
        except SystemExit:
            print(f"  {game}: skip"); continue
        _, body, _ = L.split_cart(code)
        out = renamed_on_source_lines(body)
        a, b = dump(body.encode()), dump(out.encode())
        same = a == b
        ok &= same
        print(f"  {game}: {len(body):,} -> {len(out):,} chars, stripped bytecode "
              f"{'IDENTICAL' if same else 'DIFFERS'} ({len(a):,} bytes)")
    print(f"bytecode: {'all identical' if ok else 'MISMATCH'}")
    return ok


# ----------------------------------------------------------------- fixtures

def suite_fixtures():
    text = open(os.path.join(HERE, "fixtures.lua"), encoding="utf-8").read()
    cases = re.split(r"^-- @@ (.+)$", text, flags=re.M)[1:]
    ok = True
    for name, src in zip(cases[::2], cases[1::2]):
        outs = []
        try:
            res = L.minify_ex(src, mode="max")
            mini = res.text
        except Exception as e:
            print(f"  FAIL {name}: minify raised {type(e).__name__}: {e}")
            ok = False; continue
        for s in (src, mini):
            rt = lua()
            rt.execute(b"OUT = {} function trace(...) local t = table.pack(...) "
                       b"for i = 1, t.n do t[i] = math.type(t[i]) == 'float' and string.format('%.17g', t[i]) "
                       b"or tostring(t[i]) end OUT[#OUT + 1] = table.concat(t, ' ', 1, t.n) end")
            r = rt.eval(b'function(s) local f, e = load(s, "=fx") if not f then return "SYNTAX " .. e end '
                        b'local ok, e2 = pcall(f) if not ok then return "ERROR " .. tostring(e2) end '
                        b'return table.concat(OUT, "\\n") end')(s.encode())
            outs.append(r)
        if outs[0].startswith((b"ERROR", b"SYNTAX")) or not outs[0]:
            ok = False
            print(f"  FAIL {name}: the ORIGINAL fixture does not run: {outs[0][:200]!r}")
        elif outs[0] != outs[1]:
            ok = False
            print(f"  FAIL {name}\n    original: {outs[0][:300]!r}\n    minified: {outs[1][:300]!r}\n"
                  f"    code: {mini[:400]}")
        else:
            shrink = 100 * (1 - len(mini) / max(1, len(src)))
            rep = res.report
            keys = (f"; keys kept: {rep.keys_off}" if rep.keys_off else
                    f"; {rep.keys_renamed} keys renamed" if rep.keys_renamed else "")
            print(f"  ok   {name} ({shrink:.0f}% smaller{keys})")
            want_off = name.endswith("(pass off)")
            if name.startswith("table keys") and (want_off != bool(rep.keys_off)
                                                  or not (want_off or rep.keys_renamed)):
                ok = False
                print(f"  FAIL {name}: rename-tables should "
                      f"{'be off' if want_off else 'rename keys'} here")
    print(f"fixtures: {'all identical' if ok else 'FAILURES'}")
    return ok


if __name__ == "__main__":
    which = sys.argv[1:] or ["fold", "bytecode", "fixtures"]
    results = []
    for w in which:
        print(f"== {w}")
        results.append({"fold": suite_fold, "bytecode": suite_bytecode,
                        "fixtures": suite_fixtures}[w]())
    sys.exit(0 if all(results) else 1)
