#!/usr/bin/env python3
"""Unit tests for every combination of the minifier's options, on sample carts.

    python tests/options/test_options.py        # all tests
    python tests/options/test_options.py -k Behaviour
    TICPAK_BOOT=1 python tests/options/test_options.py -k Boot

The seven options (comments, rename-vars, rename-functions, rename-tables,
constants, whitespace, extra) give 128 subsets; since every option but
`comments` implies it, they collapse to 65 distinct effective sets, and each
runs on each cart in samples/ (built by make_samples.py) and on the ticpak
project in project/. Per combination:

  OptionParsing  empty set, the `default` and `max` presets, unknown names
                 rejected, implied `comments`, raw subset == its effective set
  CommandLine    --minify absent = none, bare = default, =max, =a,b = those
                 only; other names rejected; a path after --minify hinted;
                 -m, -o/--output (and --out), -f/--force, --verbose, -v/--version;
                 `check -f` and -n with -o FILE rejected; -q; -r [PATH]
  Outputs        -o NAME.tic / NAME.lua / folder and the default <name>.tic
                 beside main.lua; cart vs module; a bad SOURCE; the
                 interactive output questions and the rerun hint
  Summary        the closing size summary's lines and arithmetic, on a .tic
                 built by hand (no TIC-80 run); minify savings only with
                 --verbose and in the -r report
  Structure      output re-lexes and re-parses; metadata header and asset
                 sections byte-identical; header still complete for check.py;
                 deterministic; a pass report exactly when an option past
                 `comments` is on
  OptionEffects  each option's visible signature, on and off: comments gone,
                 renameme_*, renamefn_* and renamekey_* shortened, keepkey_*
                 kept, CONST_* inlined and removed, lines
                 packed to 120 columns, unused/dead code and call sugar
  RenameTables   rename-tables (spec R13) on small programs: what is
                 renamed and what keeps its name (library keys, metamethods,
                 keys also written as strings, keys a built string could
                 spell), each reason the pass turns off, the decode map,
                 and the same behaviour under real Lua 5.3
  Behaviour      the original and the minified cart run under real Lua 5.3
                 (lupa) against a logging stand-in TIC-80 API (harness.lua);
                 the logs must be identical, value types included
  Sizes          adding an option never makes the code longer; `whitespace`
                 never adds lines
  Savings        what each option saved (savings=True): bytes balance per
                 line and in total, options that are off save nothing,
                 constants and extra split, the bundle's per-file table
  Nominify       NOMINIFY-kept variables (spec R8g): marked after or above
                 their statement; never renamed, inlined or removed
  NominifyFunctionsAndModules  function- and module-level NOMINIFY (R8h):
                 same line / block above / closing line of a declaration,
                 nested and unused functions, a block in a body keeping only
                 itself, a module's top block, module level winning, a blank
                 line ending a block, the whole cart; bodies byte for byte
                 and the functions' names kept under every option set, used
                 names pinned
  NominifyComments  comments a directive keeps (R8i): where they may sit,
                 moved out of a call, removed with unused code, `-- <` stops
  Bundle         the project bundled by bundle.bundle() for every set behaves
                 like the unminified bundle, keeps its assets and header
  BundleAssets   every asset layout (and CRLF) survives bundle.bundle(); no
                 sections, or a section in a module, stops the build
  Boot           (TICPAK_BOOT=1 only - runs TIC-80) each bundle boots headless
                 and saves a .tic that passes check.py and holds main.lua's
                 assets byte for byte

Behaviour and Bundle need lupa (pip install lupa); without it they skip.
"""
import argparse
import contextlib
import functools
import io
import itertools
import os
import random
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)                    # the ticpak package, installed or not
sys.path.insert(0, HERE)                    # make_samples, for its asset layouts
from ticpak import minify as M  # noqa: E402
from ticpak import __version__, bundle, check, cli, header, report, run  # noqa: E402
import make_samples  # noqa: E402

try:
    from lupa import lua53
except ImportError:
    lua53 = None
NEEDS_LUA = unittest.skipIf(lua53 is None, "needs lupa (pip install lupa)")

META_KEYS = check.REQUIRED_META + check.OPTIONAL_META
OPTIONS = M.OPTIONS
SUBSETS = [frozenset(c) for r in range(len(OPTIONS) + 1)
           for c in itertools.combinations(OPTIONS, r)]
EFFECTIVE = sorted({M.parse_options(s) for s in SUBSETS},
                   key=lambda s: (len(s), [o for o in OPTIONS if o in s]))
FRAMES = 12


def label(opts):
    return ",".join(o for o in OPTIONS if o in opts) or "none"


def read(path):
    with open(path, encoding="utf-8", newline="") as f:     # keep CRLF as is
        return f.read()


SAMPLE_DIR = os.path.join(HERE, "samples")
SAMPLES = {os.path.splitext(f)[0]: read(os.path.join(SAMPLE_DIR, f))
           for f in sorted(os.listdir(SAMPLE_DIR)) if f.endswith(".lua")}
HARNESS = read(os.path.join(HERE, "harness.lua"))


@functools.lru_cache(maxsize=None)
def minified(name, opts):
    return M.minify_cart_ex(SAMPLES[name], mode=opts, meta_keys=META_KEYS)


def parts(text):
    """(header, code, chunks) of a cart."""
    return M.split_cart(text, META_KEYS)


def code_of(text):
    return parts(text)[1]


@functools.lru_cache(maxsize=None)
def run_lua(text):
    rt = lua53.LuaRuntime(unpack_returned_tuples=True)
    rt.execute(HARNESS)
    return rt.globals().RUN(text, FRAMES)


def names(pattern, text):
    return set(re.findall(pattern, text))


def setUpModule():
    # some modules use open(...).read()/.write() one-liners; unittest would
    # report each unclosed file as a ResourceWarning - noise, not a failure
    warnings.simplefilter("ignore", ResourceWarning)


def protected(name):
    """The NOMINIFY-protected function/module bodies of a sample's code."""
    code = code_of(SAMPLES[name])
    return [code[a:b] for a, b in M.nominify_regions(code)]


def kept_comments(name):
    """The comments a NOMINIFY directive keeps in a sample's code (spec R8i).
    (top=False: a cart's top block is its header, not the code's.)"""
    return [c[3] for c in M.directives(code_of(SAMPLES[name]), top=False).comments]


def whole_cart_kept(name):
    """Does the sample's top comment block turn minification off?"""
    return minified(name, M.ALL_OPTIONS).text == SAMPLES[name]


def without_protected(name, code):
    """code with every protected body and kept comment cut out (they keep
    their comments)."""
    for body in protected(name):
        code = code.replace(body, "(...)end")
    for text in kept_comments(name):
        code = code.replace(text, "")
    return code


def combos():
    """(sample name, effective option set) for every combination."""
    return [(n, o) for n in SAMPLES for o in EFFECTIVE]


PROJECT_MAIN = os.path.join(HERE, "project", "main.lua")
# Every asset layout make_samples writes, plus bank 0's with CRLF line endings
ASSET_PROJECTS = [(lay, "\n") for lay in make_samples.ASSET_LAYOUTS if lay != "none"] \
    + [("bank0", "\r\n")]


def read_text(path):
    """A file in text mode, line endings normalised, as ticpak reads carts."""
    with open(path, encoding="utf-8") as f:
        return f.read()


def asset_project(root, layout, newline="\n", seed=7):
    """A copy of project/ whose main.lua carries make_samples' `layout` of
    asset sections, written with `newline`; returns its main.lua's path."""
    os.makedirs(root)
    src = os.path.dirname(PROJECT_MAIN)
    for f in os.listdir(src):
        if f.endswith(".lua") and f != "main.lua":
            shutil.copy(os.path.join(src, f), root)
    text = read_text(PROJECT_MAIN)
    code = text[:bundle.CHUNK_RE.search(text).start()]
    main = os.path.join(root, "main.lua")
    with open(main, "w", encoding="utf-8", newline="") as f:
        f.write((code + make_samples.assets(layout, random.Random(seed)))
                .replace("\n", newline))
    return main


# Text-cart section -> (.tic chunk, bytes per text line, nibbles swapped in
# the hex); TIC-80's BinarySections table in src/studio/project.c.
TEXT_TO_TIC = {
    "TILES": ("TILES", 32, True), "SPRITES": ("SPRITES", 32, True),
    "MAP": ("MAP", 240, True), "FLAGS": ("FLAGS", 256, True),
    "WAVES": ("WAVEFORM", 16, True), "SFX": ("SAMPLES", 66, True),
    "PATTERNS": ("PATTERNS", 192, True), "TRACKS": ("MUSIC", 51, True),
    "SCREEN": ("SCREEN", 120, True), "PALETTE": ("PALETTE", 48, False),
}


def text_assets(chunks):
    """{(.tic chunk name, bank): bytes} decoded from a text cart's asset
    sections, trailing zeros trimmed as the .tic stores them."""
    out = {}
    for m in re.finditer(r"^-- <([A-Z]+)(\d?)>\n(.*?)^-- </\1\2>", chunks, re.S | re.M):
        name, per, swap = TEXT_TO_TIC[m.group(1)]
        buf = bytearray()
        for row, hx in re.findall(r"^-- (\d+):([0-9a-fA-F]+)", m.group(3), re.M):
            if swap:
                hx = "".join(hx[i + 1] + hx[i] for i in range(0, len(hx), 2))
            data, at = bytes.fromhex(hx), int(row) * per
            buf.extend(bytes(max(0, at + len(data) - len(buf))))
            buf[at:at + len(data)] = data
        out[(name, int(m.group(2) or 0))] = bytes(buf).rstrip(b"\0")
    return out


def tic_assets(path):
    """{(chunk name, bank): bytes} of a .tic's non-code chunks."""
    with open(path, "rb") as f:
        data = f.read()
    return {(n, b): data[o:o + s].rstrip(b"\0")
            for n, b, s, o in check.parse_tic(data)[0] if n not in check.CODE_CHUNKS}


class TestOptionParsing(unittest.TestCase):
    def test_empty_and_presets(self):
        self.assertEqual(M.parse_options(""), frozenset())
        self.assertEqual(M.parse_options([]), frozenset())
        self.assertEqual(M.ALL_OPTIONS, set(OPTIONS))
        self.assertEqual(M.parse_options("max"), M.ALL_OPTIONS)
        self.assertEqual(M.parse_options("default"), M.ALL_OPTIONS - {"rename-tables"})
        self.assertEqual(M.parse_options("default"), M.DEFAULT_OPTIONS)
        self.assertEqual(M.parse_options("default,rename-tables"), M.ALL_OPTIONS)

    def test_spelling(self):
        self.assertEqual(M.parse_options(" rename-vars , whitespace "),
                         {"comments", "rename-vars", "whitespace"})
        self.assertEqual(M.parse_options(["constants"]), {"comments", "constants"})

    def test_unknown_rejected(self):
        for bad in ("bogus", "dead", "fold", "comments,unused", "Rename-vars",
                    "rename", "all", "none", "rename_vars", "fields", "rename-keys"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                M.parse_options(bad)

    def test_any_option_implies_comments(self):
        for s in SUBSETS:
            with self.subTest(opts=label(s)):
                p = M.parse_options(s)
                self.assertEqual(p, s | {"comments"} if s else frozenset())

    def test_raw_subset_equals_effective(self):
        for name in SAMPLES:
            for s in SUBSETS:
                with self.subTest(sample=name, opts=sorted(s)):
                    raw = M.minify_cart_ex(SAMPLES[name], mode=s, meta_keys=META_KEYS)
                    self.assertEqual(raw.text, minified(name, M.parse_options(s)).text)

    def test_sixty_five_effective_sets(self):
        self.assertEqual(len(SUBSETS), 128)
        self.assertEqual(len(EFFECTIVE), 65)


class TestCommandLine(unittest.TestCase):
    """ticpak's command line: --minify absent = none (default, as the
    interactive question's default), bare = default, =max every option, =a,b
    = those only; -f/--force, --verbose and -v/--version."""

    def parse(self, *argv):
        with contextlib.redirect_stderr(io.StringIO()):
            return cli.parse_args(list(argv))

    def test_absent_is_none(self):
        for argv in (["bundle"], ["bundle", "-f", "src/main.lua"], ["check"]):
            with self.subTest(argv=argv):
                self.assertEqual(self.parse(*argv)[1].minify, frozenset())

    def test_interactive_default_is_default(self):
        """No command: the interactive question offers the default options
        first."""
        self.assertEqual(self.parse()[1].minify, M.DEFAULT_OPTIONS)

    def test_bare_is_default(self):
        """A bare --minify: every option but the opt-in rename-tables."""
        for argv in (["--minify"], ["bundle", "-f", "--minify"],
                     ["bundle", "src/main.lua", "--minify"],
                     ["bundle", "-m"], ["bundle", "-m", "-f"]):
            with self.subTest(argv=argv):
                self.assertEqual(self.parse(*argv)[1].minify, M.DEFAULT_OPTIONS)
        self.assertIn("rename-functions", M.DEFAULT_OPTIONS)
        self.assertNotIn("rename-tables", M.DEFAULT_OPTIONS)
        self.assertIn("rename-tables", M.ALL_OPTIONS)

    def test_presets(self):
        for argv, want in ((["-m=max"], M.ALL_OPTIONS), (["--minify=max"], M.ALL_OPTIONS),
                           (["-m", "max"], M.ALL_OPTIONS),
                           (["-m=default"], M.DEFAULT_OPTIONS),
                           (["-m=default,rename-functions"], M.DEFAULT_OPTIONS),
                           (["-m=default,rename-tables"], M.ALL_OPTIONS)):
            with self.subTest(argv=argv):
                self.assertEqual(self.parse(*argv)[1].minify, want)

    def test_listed_options(self):
        for argv, want in ((["--minify=rename-vars,extra"],
                            {"comments", "rename-vars", "extra"}),
                           (["-m", "rename-vars,extra"], {"comments", "rename-vars", "extra"}),
                           (["-m=rename-vars"], {"comments", "rename-vars"}),
                           (["-mrename-functions"], {"comments", "rename-functions"}),
                           (["-m=rename-tables"], {"comments", "rename-tables"}),
                           (["--minify", "whitespace"], {"comments", "whitespace"}),
                           (["--minify=comments"], {"comments"})):
            with self.subTest(argv=argv):
                self.assertEqual(self.parse(*argv)[1].minify, want)

    def test_rejected(self):
        for argv in (["--minify=all"], ["--minify=none"], ["--minify=rename"],
                     ["--minify=rename-vars,bogus"], ["--minify="],
                     ["--minify", "src/main.lua"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                self.parse(*argv)

    def test_path_hint(self):
        with self.assertRaises(argparse.ArgumentTypeError) as e:
            cli.minify_arg("src/main.lua")
        self.assertIn("put SOURCE before --minify", str(e.exception))

    def test_out(self):
        self.assertEqual(self.parse("bundle", "--output", "x")[1].out, "x")
        self.assertEqual(self.parse("bundle", "--out", "x")[1].out, "x")
        self.assertEqual(self.parse("bundle", "-o", "x")[1].out, "x")
        self.assertIsNone(self.parse("build")[0])   # the old command name is gone
        self.assertIsNone(self.parse("bundle")[1].out)

    def test_force_and_verbose(self):
        _, args, _ = self.parse("bundle", "-f", "--verbose")
        self.assertTrue(args.force and args.verbose)
        _, args, _ = self.parse("bundle", "--force", "--verbose")
        self.assertTrue(args.force and args.verbose)
        _, args, _ = self.parse("bundle")
        self.assertFalse(args.force or args.verbose)
        _, args, _ = self.parse("check", "--verbose")
        self.assertTrue(args.verbose)

    def test_v_is_version(self):
        for flag in ("-v", "--version"):
            out = io.StringIO()
            with self.subTest(flag=flag), contextlib.redirect_stdout(out), \
                    self.assertRaises(SystemExit) as e:
                self.parse("bundle", flag)
            self.assertEqual(e.exception.code, 0)
            self.assertIn("ticpak ", out.getvalue())

    def test_check_force_rejected(self):
        with self.assertRaises(SystemExit):
            self.parse("check", "-f")

    def test_quiet(self):
        for argv in (["bundle", "-q"], ["bundle", "--quiet", "-f"], ["check", "-q"],
                     ["check", "-q", os.path.join(HERE, "README.md")]):
            with self.subTest(argv=argv):
                self.assertTrue(self.parse(*argv)[1].quiet)
        for argv in (["-q"], ["bundle", "-q", "--verbose"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                self.parse(*argv)

    def test_report(self):
        self.assertIsNone(self.parse("bundle")[1].report)
        for argv, want in ((["bundle", "-r"], True), (["bundle", "-r", "-f"], True),
                           (["bundle", "--report"], True),
                           (["bundle", "-r", "out.txt"], "out.txt"),
                           (["bundle", "-r=out.txt"], "out.txt"),
                           (["bundle", "--report=logs/"], "logs/"),
                           (["bundle", "src", "-r"], True)):
            with self.subTest(argv=argv):
                self.assertEqual(self.parse(*argv)[1].report, want)
        for argv in (["bundle", "-r", "main.lua"], ["bundle", "--report=x.tic"],
                     ["bundle", "--report="],
                     ["check", os.path.join(HERE, "README.md"), "-r"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                self.parse(*argv)

    def test_name_with_file_out_rejected(self):
        for out in ("x.tic", "x.lua", "a/X.TIC"):
            with self.subTest(out=out), self.assertRaises(SystemExit):
                self.parse("bundle", "-n", "y", "-o", out)
        self.assertEqual(self.parse("bundle", "-n", "y", "-o", "dist")[1].out, "dist")


class TestMinifyCommand(unittest.TestCase):
    """`ticpak minify FILE`: one flag per option (none = the default
    options, --max = every option); a cart
    that requires no modules is the whole program, anything else a module
    whose globals stay."""

    HEADER = "-- title: t\n-- author: a\n-- script: lua\n\n"
    # a module whose comments look like a header tag and an asset section
    MODULE = ("-- title: the title screen, drawn\n\n"
              "function title_draw()\n print(\"hi\", 1, 2) -- greet\nend\n"
              "-- <MAP> region of RAM, reused\n"
              "function unused_helper_fn() return 1 end\n")

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="minify-cmd-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name, text):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def run_cmd(self, *argv):
        out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["minify", *argv])
        return out.buffer.getvalue().decode("utf-8")

    def test_module_keeps_globals(self):
        path = self.write("title.lua", self.MODULE)
        self.assertFalse(bundle.is_cart(path))
        out = self.run_cmd(path)
        self.assertIn("function title_draw()", out)
        self.assertIn("function unused_helper_fn()", out)
        self.assertNotIn("--", out)

    def test_whole_cart(self):
        path = self.write("game.lua", self.HEADER + "function unused_helper_fn() return 1 end\n"
                          "function TIC() cls(0) end\n")
        self.assertTrue(bundle.is_cart(path))
        out = self.run_cmd(path)
        self.assertTrue(out.startswith(self.HEADER.strip()))
        self.assertIn("function TIC()", out)
        self.assertNotIn("unused_helper_fn", out)

    def test_cart_with_modules_keeps_globals(self):
        path = self.write("main.lua", "keepme_speed = 3\nrequire \"util\"\n"
                          "function TIC() cls(0) end\n")
        self.assertIn("keepme_speed", self.run_cmd(path))

    def test_option_flags(self):
        path = self.write("title.lua", self.MODULE)
        out = self.run_cmd("--comments", path)
        self.assertIn("function title_draw()\n print(\"hi\", 1, 2)", out)
        self.assertNotIn("--", out)
        out = self.run_cmd("--comments", "--whitespace", path)
        self.assertIn('print("hi",1,2)', out)

    def test_functions_renamed(self):
        """No flag (the default options), --max and --rename-functions rename
        functions; options without rename-functions keep their names."""
        path = self.write("game.lua", self.HEADER + "function renamefn_hud() print(1) end\n"
                          "function TIC() renamefn_hud() end\n")
        self.assertIn("renamefn_hud", self.run_cmd("--rename-vars", "--whitespace", path))
        for flags in ([], ["--max"], ["--rename-functions"],
                      ["--rename-vars", "--rename-functions"]):
            with self.subTest(flags=flags):
                out = self.run_cmd(*flags, path)
                self.assertNotIn("renamefn_hud", out)
                self.assertIn("function TIC()", out)

    def test_keys_renamed_only_on_request(self):
        """No flag: the default options, which keep table keys; --max and
        --rename-tables rename them."""
        path = self.write("game.lua", self.HEADER + "local hero = {renamekey_health = 3}\n"
                          "function TIC() trace(hero.renamekey_health) end\n")
        self.assertIn("renamekey_health", self.run_cmd(path))
        for flags in (["--max"], ["--rename-tables"]):
            with self.subTest(flags=flags):
                self.assertNotIn("renamekey_health", self.run_cmd(*flags, path))

    def test_old_flags_rejected(self):
        path = self.write("title.lua", self.MODULE)
        for flag in ("--mode=max", "--cart", "--fragment", "--report=r.txt",
                     "--passes=fold", "--width=80", "--inline=all"):
            with self.subTest(flag=flag), self.assertRaises(SystemExit):
                self.run_cmd(flag, path)


class TestInit(unittest.TestCase):
    """`ticpak init [FOLDER]`: main.lua (a header with placeholders for
    title, author, desc, site and license, a stub requiring game, an asset
    section) and game.lua, which bundle and minify; stops,
    writing nothing, when there is a cart already or game.lua is taken."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="init-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def init(self, *argv):
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            cli.main(["init", *argv])

    def test_new_project_bundles(self):
        folder = os.path.join(self.tmp, "space race")   # made; the title asked for
        self.init(folder)
        cart = os.path.join(folder, "main.lua")
        self.assertTrue(bundle.is_cart(cart))
        code = bundle.cart_code(cart)
        meta = check.parse_header(code)
        self.assertEqual(meta["title"], "my game")
        self.assertEqual(header.incomplete_fields(meta),
                         ["title", "author", "desc", "site", "license"])
        header.write_header(cart, header.header_defaults(meta, cart))  # as asked
        code = bundle.cart_code(cart)
        self.assertTrue(check.check_header(code, quiet=True))
        self.assertEqual(check.parse_header(code)["title"], "space race")
        self.assertEqual(bundle.stub_requires(code)[0], ["game"])
        t = bundle.Target(cart, "space-race", None)
        source, chunks, names, _ = bundle.assemble(t)
        self.assertEqual(names, ["game"])
        self.assertIn("-- <PALETTE>", chunks)
        for preset in (M.DEFAULT_OPTIONS, M.ALL_OPTIONS):
            M.minify_cart_ex(source, mode=preset, meta_keys=META_KEYS)

    def test_gitignore(self):
        """init adds *.tic, dist/ and .local/ to the folder's .gitignore,
        keeping what is there and adding none twice."""
        folder = os.path.join(self.tmp, "g")
        os.makedirs(folder)
        with open(os.path.join(folder, ".gitignore"), "w", encoding="utf-8") as f:
            f.write("build/\ndist/")
        self.init(folder)
        with open(os.path.join(folder, ".gitignore"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "build/\ndist/\n*.tic\n.local/\n")

    def test_run_problems(self):
        """Before `ticpak run`: a missing module, and what would run but not
        package (a module only another requires, a `-- <` line)."""
        folder = os.path.join(self.tmp, "r")
        self.init(folder)
        cart = os.path.join(folder, "main.lua")
        self.assertEqual(bundle.run_problems(cart), ([], []))
        with open(os.path.join(folder, "game.lua"), "a", encoding="utf-8") as f:
            f.write('require "helper"\nrequire "gone"\n')
        with open(os.path.join(folder, "helper.lua"), "w", encoding="utf-8") as f:
            f.write("-- <MAP> notes\nreturn {}\n")
        missing, warnings = bundle.run_problems(cart)
        self.assertEqual([(m[0], m[2]) for m in missing], [("gone", "game")])
        self.assertEqual(len(warnings), 2)
        self.assertTrue(warnings[0].startswith("helper.lua is required by game.lua"))
        self.assertTrue(warnings[1].startswith("helper.lua:1 starts `-- <`"))

    def test_backup_restore(self):
        """`run` copies the file it runs to .local/backup/; `restore` puts
        it back only when they differ, asking first (or with -y; without a
        terminal it needs -y)."""
        folder = os.path.join(self.tmp, "b")
        self.init(folder)
        cart = os.path.join(folder, "main.lua")
        with self.assertRaises(SystemExit) as e:        # no backup yet
            self.init_free("restore", folder, "-y")
        self.assertIn("no backup", str(e.exception.code))
        backup = run.make_backup(cart)
        self.assertEqual(backup, os.path.join(folder, ".local", "backup", "main.lua"))
        self.assertIn("not modified", self.init_free("restore", folder, "-y"))
        original = open(cart, encoding="utf-8").read()
        with open(cart, "a", encoding="utf-8") as f:
            f.write("-- changed\n")
        with self.assertRaises(SystemExit) as e:        # no terminal, no -y
            with mock.patch.object(cli, "has_terminal", lambda: False):
                self.init_free("restore", folder)
        self.assertIn("give -y", str(e.exception.code))
        changed = open(cart, encoding="utf-8").read()
        out = self.init_free("restore", folder, "-y")
        self.assertIn("1 line differs", out)
        self.assertIn("again to swap them back", out)
        self.assertEqual(open(cart, encoding="utf-8").read(), original)
        self.assertEqual(open(backup, encoding="utf-8").read(), changed)    # a swap
        out = self.init_free("restore", folder, "-y")       # ...so it undoes
        self.assertIn("1 line differs", out)                # (a `--` line counts)
        self.assertEqual(open(cart, encoding="utf-8").read(), changed)
        self.assertEqual(open(backup, encoding="utf-8").read(), original)
        self.assertEqual(cli.ago(59), "59 seconds")
        self.assertEqual(cli.ago(-7200), "2 hours")

    def init_free(self, *argv):
        """cli.main(argv), its output."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            cli.main(list(argv))
        return out.getvalue()

    def test_stops_on_existing_project(self):
        for existing in ("main.lua", os.path.join("src", "main.lua"), "game.lua"):
            with self.subTest(existing=existing):
                folder = tempfile.mkdtemp(dir=self.tmp)
                path = os.path.join(folder, existing)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    f.write("-- mine\n")
                with self.assertRaises(SystemExit) as e:
                    self.init(folder)
                self.assertIn("already exists", str(e.exception.code))
                self.assertEqual(open(path, encoding="utf-8").read(), "-- mine\n")
                self.assertEqual(sorted(os.listdir(folder)),
                                 [existing.split(os.sep)[0]])

    def test_takes_only_a_folder(self):
        for argv in (["-f"], ["-m"], ["-o", "x.tic"], ["-n", "x"], ["a", "b"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit) as e:
                self.init(*argv)
            self.assertEqual(e.exception.code, 2)


class TestOutputs(unittest.TestCase):
    """-o: a .tic alone, a .lua alone, or a folder of .tic + .lua + .txt
    (and maps); no -o is <name>.tic beside main.lua. Interactive questions
    and the rerun hint for each."""

    MAIN = os.path.join(HERE, "project", "main.lua")

    def test_out_kind(self):
        for out, kind in (("x.tic", "tic"), ("a/b/X.TIC", "tic"), ("x.lua", "lua"),
                          ("dist/", "dir"), ("dist", "dir"), ("x.lua/", "dir"),
                          ("out\\", "dir"), ("build.v2", "dir"), ("x.txt", "dir")):
            with self.subTest(out=out):
                self.assertEqual(bundle.out_kind(out), kind)

    def test_targets(self):
        d = os.path.dirname(self.MAIN)
        t = bundle.Target(self.MAIN, "game")
        self.assertEqual((t.tic, t.lua, t.txt, t.map_txt), (os.path.join(d, "game.tic"),
                                                             None, None, None))
        t = bundle.Target(self.MAIN, "game", "x/my.tic")
        self.assertEqual((t.name, t.tic, t.lua, t.txt), ("my", os.path.abspath("x/my.tic"),
                                                         None, None))
        t = bundle.Target(self.MAIN, "game", "my.lua")
        self.assertEqual((t.name, t.lua, t.tic, t.txt, t.output),
                         ("my", os.path.abspath("my.lua"), None, None, t.lua))
        t = bundle.Target(self.MAIN, "game", "dist/")
        base = os.path.join(os.path.abspath("dist"), "game")
        self.assertEqual((t.lua, t.tic, t.txt, t.map_json, t.output),
                         (base + ".lua", base + ".tic", None,
                          base + ".minify.json", base + ".tic"))

    def test_report_paths(self):
        """-r: <name>.bundle.txt beside the output; -r PATH: that file, or
        <name>.bundle.txt in a folder."""
        d = os.path.dirname(self.MAIN)
        self.assertEqual(bundle.Target(self.MAIN, "game", None, True).txt,
                         os.path.join(d, "game.bundle.txt"))
        self.assertEqual(bundle.Target(self.MAIN, "game", "dist/", True).txt,
                         os.path.join(os.path.abspath("dist"), "game.bundle.txt"))
        self.assertEqual(bundle.Target(self.MAIN, "game", "x/my.tic", True).txt,
                         os.path.join(os.path.abspath("x"), "my.bundle.txt"))
        self.assertEqual(bundle.Target(self.MAIN, "game", None, "r.txt").txt,
                         os.path.abspath("r.txt"))
        self.assertEqual(bundle.Target(self.MAIN, "game", None, "logs/").txt,
                         os.path.join(os.path.abspath("logs"), "game.bundle.txt"))
        self.assertEqual(bundle.Target(self.MAIN, "game", None, HERE).txt,
                         os.path.join(HERE, "game.bundle.txt"))     # an existing folder

    def test_folder_build_report(self):
        """A build to a folder writes the report there without -r; a file
        output only with -r. -r PATH still wins."""
        self.assertIs(cli.build_report(None, "dist/"), True)
        self.assertIs(cli.build_report(None, "dist"), True)
        self.assertIsNone(cli.build_report(None, None))
        self.assertIsNone(cli.build_report(None, "x.tic"))
        self.assertIsNone(cli.build_report(None, "x.lua"))
        self.assertIs(cli.build_report(True, "x.tic"), True)
        self.assertEqual(cli.build_report("r.txt", "dist/"), "r.txt")

    def test_folder_report_missing_is_stale(self):
        """A folder build whose report is gone is out of date."""
        tmp = tempfile.mkdtemp(prefix="outputs-")
        try:
            t = bundle.Target(self.MAIN, "game", tmp + "/", True)
            for p in (t.tic, t.lua):
                with open(p, "w") as f:
                    f.write("x")
            fresh, status = bundle.freshness(t)
            self.assertFalse(fresh)
            self.assertIn("game.bundle.txt missing", status)
            with open(t.txt, "w") as f:
                f.write("x")
            self.assertTrue(bundle.freshness(t)[0])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_is_cart(self):
        d = os.path.dirname(self.MAIN)
        self.assertTrue(bundle.is_cart(self.MAIN))
        self.assertFalse(bundle.is_cart(os.path.join(d, "util.lua")))

    def test_find_cart_errors(self):
        with self.assertRaises(SystemExit) as e:
            bundle.find_cart(os.path.join(HERE, "nope.lua"))
        self.assertIn("not found", str(e.exception))
        with self.assertRaises(SystemExit) as e:
            bundle.find_cart(os.path.join(HERE, "README.md"))
        self.assertIn("not a .lua file", str(e.exception))

    def test_lone_lua_written_after_boot(self):
        """bundle() keeps a lone .lua in memory: it is saved once it boots, so
        a failed boot can't leave a bundle that looks up to date."""
        tmp = tempfile.mkdtemp(prefix="outputs-")
        try:
            t = bundle.Target(self.MAIN, "game", os.path.join(tmp, "x.lua"))
            with contextlib.redirect_stdout(io.StringIO()):
                bundle.bundle(t, M.ALL_OPTIONS)
            self.assertTrue(t.code and not os.listdir(tmp))
            bundle.save_bundle(t)
            self.assertEqual(os.listdir(tmp), ["x.lua"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    class UI:
        """Scripted answers for Prompts: one per question, in order."""
        def __init__(self, *answers):
            self.answers, self.asked = list(answers), []

        def _next(self, message, default):
            """The scripted answer; None takes the default."""
            self.asked.append(message)
            a = self.answers.pop(0)
            return default if a is None else a

        def text(self, message, default="", suffix=""):
            return self._next(message, default)

        def select(self, message, choices, default):
            self.choices = [key for key, _ in choices]
            return self._next(message, default)

        def checkbox(self, message, choices, checked):
            return self._next(message, checked)

    def test_interactive_tic_default(self):
        ui = self.UI(None, "default", None)
        self.assertEqual(cli.ask_build_settings(ui, frozenset(), "game", None),
                         (M.DEFAULT_OPTIONS, "game", None))
        self.assertEqual(ui.asked[-1], "Output:")

    def test_interactive_minify_menu(self):
        """default, comments, max, none, then the checkboxes; the default
        options preselected."""
        for answer, want in (("default", M.DEFAULT_OPTIONS), ("max", M.ALL_OPTIONS),
                             ("comments", frozenset({"comments"})), ("none", frozenset())):
            with self.subTest(answer=answer):
                ui = self.UI(answer)
                self.assertEqual(cli.ask_minify(ui, M.DEFAULT_OPTIONS), want)
                self.assertEqual(ui.choices, ["default", "comments", "max", "none", "pick"])
        ui = self.UI(None)                              # the default answer
        self.assertEqual(cli.ask_minify(ui, M.DEFAULT_OPTIONS), M.DEFAULT_OPTIONS)
        ui = self.UI("pick", ["rename-functions"])
        self.assertEqual(cli.ask_minify(ui, M.DEFAULT_OPTIONS),
                         {"comments", "rename-functions"})

    def test_interactive_folder(self):
        ui = self.UI("Other Name", "none", "dir", None)
        self.assertEqual(cli.ask_build_settings(ui, frozenset(), "game", None),
                         (frozenset(), "other-name", "dist/"))
        ui = self.UI(None, None, None, "x.lua")
        self.assertEqual(cli.ask_build_settings(ui, frozenset(), "game", "out")[2], "x.lua/")

    def test_interactive_file_out_asks_minify_only(self):
        ui = self.UI("max")
        self.assertEqual(cli.ask_build_settings(ui, frozenset(), "game", "a.tic"),
                         (M.ALL_OPTIONS, "game", "a.tic"))
        self.assertEqual(ui.asked, ["Minification:"])

    def test_build_command(self):
        self.assertEqual(cli.build_command(None, M.DEFAULT_OPTIONS, "g", "g", None),
                         "ticpak bundle -m")
        self.assertEqual(cli.build_command(None, M.ALL_OPTIONS, "g", "g", None),
                         "ticpak bundle -m=max")
        self.assertEqual(cli.build_command(None, frozenset(), "h", "g", "dist/"),
                         "ticpak bundle -n h -o dist/")
        self.assertEqual(cli.build_command("src", frozenset(), "a", "g", "a.tic"),
                         "ticpak bundle src -o a.tic")
        self.assertEqual(cli.build_command(None, frozenset(), "g", "g", None, True),
                         "ticpak bundle -r")
        self.assertEqual(cli.build_command(None, frozenset(), "g", "g", None, "my r.txt"),
                         'ticpak bundle "--report=my r.txt"')


class TestSummary(unittest.TestCase):
    """report.size_summary() on a .tic made by hand from check.py's chunk format
    (u32 header: type | bank << 5 | size << 8, then the payload)."""

    @staticmethod
    def tic(chunks):
        import struct
        out = b""
        for ctype, bank, size in chunks:
            out += struct.pack("<I", ctype | bank << 5 | (size % 65536) << 8) + b"x" * size
        return out

    def summary(self, chunks, unminified, colour=False):
        d = tempfile.mkdtemp(prefix="minify-summary-")
        try:
            path = os.path.join(d, "game.tic")
            with open(path, "wb") as f:
                f.write(self.tic(chunks))
            return report.size_summary(path, unminified, colour)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_minified_under_limit(self):
        # CODE 42K (type 5), MAP 30K (4), PALETTE 48 B (12), all bank 0
        # total = 43008 + 30720 + 48 + 3 chunk headers of 4 bytes = 73788
        lines = self.summary([(5, 0, 43008), (4, 0, 30720), (12, 0, 48)], 157696)
        self.assertEqual(lines, ["cart size: 72K",
                                     "code: 42K (58%)",
                                     "assets: 30K (42%)",
                                     "code limit: 42K / 512K (8% used, 92% free)",
                                     "original code size: 154K (73% reduction)"])

    def test_unminified_over_64k_two_banks(self):
        # code split over two chunks (64K + 6K), maps in banks 0 and 1;
        # total = 65535 + 6145 + 1024 + 1024 + 4 headers = 73744
        lines = self.summary([(5, 1, 65535), (5, 0, 6145), (4, 0, 1024), (4, 1, 1024)],
                             71680)
        self.assertEqual(lines, ["cart size: 72K",
                                     "code: 70K (97%)",
                                     "assets: 2.0K (3%)",
                                     "code limit: 70K / 512K (14% used, 86% free)",
                                     "not minified",
                                     "info: code over 64K needs TIC-80 PRO to edit it"
                                     " in TIC-80 (the cart plays in every TIC-80)"])

    def test_near_and_over_512k(self):
        """From 90% of the 512K code limit the line says so (yellow on
        screen); at the limit it is over (red). The PRO note stays last."""
        full = [(5, b, 65536) for b in range(7, 0, -1)]
        near = self.summary(full + [(5, 0, 1024)], None)           # 449K of code
        self.assertEqual(near[3], "code limit: 449K / 512K (88% used, 12% free)")
        near = self.summary(full + [(5, 0, 20000)], None)          # 468K: 91%
        self.assertEqual(near[3], "code limit: 468K / 512K (91% used, 9% free)"
                                  " - close to TIC-80's code limit")
        over = self.summary(full + [(5, 0, 65536)], None)          # 512K
        self.assertEqual(over[3], "code limit: 512K / 512K (100% used)"
                                  " - over TIC-80's code limit")
        self.assertTrue(over[-1].startswith("info: code over 64K needs TIC-80 PRO"))
        # no colour unless stdout shows it (here: captured)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.summary(full + [(5, 0, 65536)], None, colour=True), over)

    def test_savings_verbose_and_report_only(self):
        """What minification saved is --verbose detail and -r report content,
        never in the default output; -r names the file it wrote."""
        d = tempfile.mkdtemp(prefix="minify-summary-")
        try:
            tic = os.path.join(d, "game.tic")
            with open(tic, "wb") as f:
                f.write(self.tic([(5, 0, 1000)]))
            groups = {"main.lua": {"source": 3000, "comments": 2000, "final": 1000}}
            for verbose, report_to in ((False, None), (True, None), (False, True)):
                t = bundle.Target(tic, "game", tic, report_to)
                t.savings = (groups, M.Savings(), M.parse_options("comments"))
                out = io.StringIO()
                saved = cli.console.VERBOSE
                cli.console.VERBOSE = verbose
                try:
                    # the hand-made .tic has no header: a violation, exit 1
                    with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
                        report.check_summary(t, 3000)
                finally:
                    cli.console.VERBOSE = saved
                with self.subTest(verbose=verbose, report=report_to):
                    self.assertEqual("bytes saved" in out.getvalue(), verbose)
                    self.assertIn("size: ", out.getvalue())
                    if report_to:
                        self.assertIn("game.bundle.txt", out.getvalue().splitlines()[-1])
                        text = read_text(os.path.join(d, "game.bundle.txt"))
                        self.assertIn("minify: bytes saved", text)
                        self.assertIn("3,000", text)
                        self.assertTrue(text.startswith("check: "))
                    else:
                        self.assertFalse(os.path.exists(os.path.join(d, "game.bundle.txt")))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_unknown_unminified(self):
        lines = self.summary([(5, 0, 1000)], None)
        self.assertEqual(lines, ["cart size: 0.98K",
                                     "code: 0.98K (100%)",
                                     "assets: 0.00K (0%)",
                                     "code limit: 0.98K / 512K (0% used, 100% free)"])

    def test_bundle_over_code_limit_stops(self):
        """A bundle at or over the code limit stops before booting: TIC-80
        would cut it off."""
        tmp = tempfile.mkdtemp(prefix="limit-")
        saved = bundle.CODE_LIMIT
        bundle.CODE_LIMIT = 2048
        try:
            t = bundle.Target(PROJECT_MAIN, "game", os.path.join(tmp, "x.lua"))
            with contextlib.redirect_stdout(io.StringIO()), \
                    self.assertRaises(SystemExit) as e:
                bundle.bundle(t, frozenset())
            self.assertRegex(str(e.exception), r"^bundle: the code is [\d,]+ bytes, over"
                                               r" TIC-80's 2K code limit .*\(-m=max\)")
            self.assertFalse(os.path.exists(t.lua))
        finally:
            bundle.CODE_LIMIT = saved
            shutil.rmtree(tmp, ignore_errors=True)


class TestStructure(unittest.TestCase):
    def test_reparses(self):
        for name, opts in combos():
            with self.subTest(sample=name, opts=label(opts)):
                code = code_of(minified(name, opts).text)
                M.reparse(M.lex_lines(code))            # raises if broken

    def test_header_and_assets_byte_identical(self):
        for name, opts in combos():
            with self.subTest(sample=name, opts=label(opts)):
                h_in, _, c_in = parts(SAMPLES[name])
                h_out, _, c_out = parts(minified(name, opts).text)
                self.assertEqual(h_out, h_in, "metadata header changed")
                self.assertEqual(c_out, c_in, "asset sections changed")

    def test_header_still_complete(self):
        for name, opts in combos():
            with self.subTest(sample=name, opts=label(opts)):
                out = minified(name, opts).text
                m = bundle.CHUNK_RE.search(out)
                self.assertTrue(check.check_header(out[:m.start()] if m else out,
                                                    quiet=True))

    def test_deterministic(self):
        for name, opts in combos():
            with self.subTest(sample=name, opts=label(opts)):
                again = M.minify_cart_ex(SAMPLES[name], mode=opts, meta_keys=META_KEYS)
                self.assertEqual(again.text, minified(name, opts).text)

    def test_report_only_past_comments(self):
        for name, opts in combos():
            with self.subTest(sample=name, opts=label(opts)):
                r = minified(name, opts)
                if opts - {"comments"} and not whole_cart_kept(name):
                    self.assertIsNotNone(r.report)
                    self.assertTrue(r.line_map)
                    n_out = r.text.count("\n") + 1
                    n_in = SAMPLES[name].count("\n") + 1
                    for o, i in r.line_map:
                        self.assertTrue(1 <= o <= n_out and 1 <= i <= n_in, (o, i))
                else:
                    self.assertIsNone(r.report)


class TestOptionEffects(unittest.TestCase):
    def test_none_is_passthrough(self):
        for name in SAMPLES:
            with self.subTest(sample=name):
                self.assertEqual(minified(name, frozenset()).text, SAMPLES[name])

    def test_comments_only_changes_nothing_else(self):
        for name in SAMPLES:
            with self.subTest(sample=name):
                code_in = code_of(SAMPLES[name])
                code_out = code_of(minified(name, frozenset({"comments"})).text)
                keep = M.directives(code_in, top=False).keep()
                if whole_cart_kept(name):
                    self.assertEqual(minified(name, frozenset({"comments"})).text, SAMPLES[name])
                    continue
                self.assertEqual(code_out.strip(), M.strip_comments(code_in, keep).strip())
                self.assertEqual(M.lex(code_out), M.lex(code_in))

    def test_no_comment_left(self):
        for name, opts in combos():
            if not opts:
                continue
            if whole_cart_kept(name):
                continue
            with self.subTest(sample=name, opts=label(opts)):
                code = without_protected(name, code_of(minified(name, opts).text))
                self.assertEqual(M.strip_comments(code), code)

    def test_rename(self):
        for name, opts in combos():
            src = code_of(SAMPLES[name])
            marked = names(r"\brenameme_\w+", src)
            kept = names(r"\bkeepme_\w+", src)
            with self.subTest(sample=name, opts=label(opts)):
                out = code_of(minified(name, opts).text)
                left = names(r"\brenameme_\w+", out)
                if "rename-vars" in opts:
                    self.assertFalse(left, "not renamed")
                elif opts & {"constants", "extra"}:
                    # a renameme_ that is a constant or unused may be removed
                    self.assertLessEqual(left, marked)
                else:
                    self.assertEqual(left, marked)
                self.assertEqual(names(r"\bkeepme_\w+", out), kept, "NOMINIFY name lost")

    def test_rename_functions(self):
        """renamefn_* functions: renamed by rename-functions only, whatever
        else is on; keepfn_* (NOMINIFY) never."""
        seen = False
        for name, opts in combos():
            src = code_of(SAMPLES[name])
            marked = names(r"\brenamefn_\w+", src)
            kept = names(r"\bkeepfn_\w+", src)
            seen |= bool(marked)
            with self.subTest(sample=name, opts=label(opts)):
                out = code_of(minified(name, opts).text)
                left = names(r"\brenamefn_\w+", out)
                if "rename-functions" in opts:
                    self.assertFalse(left, "not renamed")
                else:
                    self.assertEqual(left, marked)
                self.assertEqual(names(r"\bkeepfn_\w+", out), kept, "NOMINIFY function lost")
        self.assertTrue(seen)

    def test_rename_tables(self):
        """renamekey_* keys: renamed by rename-tables only, whatever else is
        on; keepkey_* (also written as a string) never."""
        seen = False
        for name, opts in combos():
            src = code_of(SAMPLES[name])
            marked = names(r"\brenamekey_\w+", src)
            kept = names(r"\bkeepkey_\w+", src)
            seen |= bool(marked)
            with self.subTest(sample=name, opts=label(opts)):
                r = minified(name, opts)
                out = code_of(r.text)
                left = names(r"\brenamekey_\w+", out)
                if "rename-tables" in opts and marked:
                    self.assertIsNone(r.report.keys_off)
                    self.assertFalse(left, "not renamed")
                else:
                    self.assertEqual(left, marked)
                self.assertEqual(names(r"\bkeepkey_\w+", out), kept, "kept key lost")
        self.assertTrue(seen)

    def test_constants(self):
        for name, opts in combos():
            consts = names(r"\bCONST_\w+", code_of(SAMPLES[name]))
            with self.subTest(sample=name, opts=label(opts)):
                out = names(r"\bCONST_\w+", code_of(minified(name, opts).text))
                if "constants" in opts:
                    self.assertFalse(out, "constants left in place")
                elif not opts & {"extra", "rename-vars"}:
                    # (extra's folding may drop them too; rename-vars shortens them)
                    self.assertEqual(out, consts)

    def test_extra(self):
        markers = ["unused_helper_fn", "DEAD_BRANCH", "UNUSED_MODULE", '("sugar_marker")']
        for name, opts in combos():
            src = code_of(SAMPLES[name])
            with self.subTest(sample=name, opts=label(opts)):
                out = code_of(minified(name, opts).text)
                for mk in markers:
                    if mk not in src:
                        continue
                    if "extra" in opts:
                        self.assertNotIn(mk, out)
                    elif mk == "unused_helper_fn" and "rename-functions" in opts:
                        self.assertNotIn(mk, out)       # kept, under a short name
                    else:
                        self.assertIn(mk, out)

    def test_whitespace_line_width(self):
        for name, opts in combos():
            if "whitespace" not in opts:
                continue
            with self.subTest(sample=name, opts=label(opts)):
                for line in code_of(minified(name, opts).text).split("\n"):
                    for text in kept_comments(name):   # a kept comment may run past
                        line = line.replace(text.split("\n")[0], "")
                    if len(line) > 120:              # only one unsplittable token
                        self.assertEqual(len(M.lex(line)), 1, line[:60])

    def test_whitespace_off_keeps_line_breaks(self):
        """Without `whitespace`, no output line holds code from two source
        lines: every line map entry points at a distinct, rising source line."""
        for name, opts in combos():
            if not opts - {"comments"} or "whitespace" in opts:
                continue
            with self.subTest(sample=name, opts=label(opts)):
                src = [i for _, i in minified(name, opts).line_map]
                self.assertEqual(src, sorted(set(src)))


class TestRenameTables(unittest.TestCase):
    """rename-tables (spec R13) on small whole programs: what is renamed,
    what keeps its name and why, each reason the pass turns off, the decode
    map, and the same behaviour under real Lua 5.3. (tests/minify/fixtures.lua
    holds the larger behaviour cases.)"""

    @staticmethod
    def fields(r):
        return {old: new for new, old, kind, _ in r.renames if kind == "field"}

    def test_renamed_and_kept(self):
        src = ("local obj = {long_field_name = 1, insert = 2, n = 3, label_text = 'x'}\n"
               "local mt = {__index = obj}\n"
               "for _, s in ipairs({'label_text'}) do trace(obj[s], s) end\n"
               "trace(obj.long_field_name, obj.insert, obj.n, math.floor(1.5),\n"
               "      setmetatable({}, mt).long_field_name)\n")
        r = M.minify_ex(src, "max")
        ren = self.fields(r)
        self.assertIn("long_field_name", ren)
        for kept in ("insert", "n", "label_text", "floor", "__index"):
            self.assertNotIn(kept, ren)
        self.assertEqual(r.report.keys_kept["also a string literal"], ["label_text"])
        self.assertTrue({"insert", "n", "floor", "__index"}
                        <= set(r.report.keys_kept["library or metamethod"]))
        self.assertIn("table keys renamed: 1", r.report.text())

    def test_key_literals_become_fields(self):
        r = M.minify_ex("local t = {['some_key'] = 1, other_key = 2}\n"
                        "t['other_key'] = t['some_key'] + 1\ntrace(t.some_key, t.other_key)\n",
                        "max")
        self.assertNotIn("some_key", r.text)
        self.assertNotIn("[", r.text)

    def test_function_keys_renamed(self):
        """Methods and functions stored in tables are renamed too (O1: the
        smallest cart); the decode map has their names."""
        r = M.minify_ex("local World = {}\nfunction World.update_world() return 1 end\n"
                        "function World:draw_things() return 2 end\n"
                        "trace(World.update_world(), World:draw_things())\n", "max")
        ren = self.fields(r)
        self.assertEqual(set(ren), {"update_world", "draw_things"})
        self.assertNotIn("update_world", r.text)
        lines = {old: line for new, old, kind, line in r.renames if kind == "field"}
        self.assertEqual(lines, {"update_world": 2, "draw_things": 3})

    def test_built_keys_keep_what_they_could_spell(self):
        """A key built by string.format or `..` keeps every name it could
        spell, and the new names avoid them; other keys are renamed. (The
        event comes from a list: a constant would be folded into the key
        literal "on_click", which is renamed with the key.)"""
        src = ("local sprites = {sprite_01 = 1, sprite_02 = 2, on_click = 3, big_sprite = 4}\n"
               "for i = 1, 2 do trace(sprites[string.format('sprite_%02d', i)]) end\n"
               "for _, ev in ipairs({'click'}) do trace(sprites['on_' .. ev]) end\n"
               "trace(sprites.big_sprite)\n")
        r = M.minify_ex(src, "max")
        self.assertIsNone(r.report.keys_off)
        self.assertEqual(set(self.fields(r)), {"big_sprite"})
        self.assertEqual(r.report.keys_kept["a key built from strings could spell it"],
                         ["on_click", "sprite_01", "sprite_02"])

    def test_off(self):
        """Each reason the pass turns off (spec R13h), named in the report."""
        cases = {
            "fragment": ("local t = {a_key = 1}\ntrace(t.a_key)\n", "fragment mode"),
            "dynamic": ("local t = {a_key = 1}\ntrace(_G.x, t.a_key)\n", "dynamic access"),
            "built": ("local t = {speed = 1}\nlocal p = {'sp', 'eed'}\n"
                      "trace(t[table.concat(p)])\n", "built at runtime"),
            "shown": ("for k in pairs({abc_key = 1}) do trace(k) end\n", "passed to trace"),
            "joined": ("for k in pairs({abc_key = 1}) do trace('k=' .. k) end\n",
                       "joined into a string"),
            "ordered": ("for k in pairs({abc_key = 1}) do trace(k < 'm') end\n",
                        "compared by order"),
            "sorted": ("local ks = {}\nfor k in pairs({abc_key = 1}) do ks[#ks + 1] = k end\n"
                       "table.sort(ks)\ntrace(#ks)\n", "table.sort"),
            "gsub": ("local v = {who_name = 'x'}\ntrace(('$who_name'):gsub('%$(%w+)', v))\n",
                     "gsub"),
            "nominify": ("local function f(t) -- NOMINIFY\n  return t.some_key\nend\n"
                         "trace(f({some_key = 1}))\n", "NOMINIFY"),
        }
        for name, (src, why) in cases.items():
            with self.subTest(case=name):
                r = M.minify_ex(src, "max", whole_program=name != "fragment")
                self.assertIn(why, r.report.keys_off or "")
                self.assertEqual(self.fields(r), {})
                self.assertIn("table keys: not renamed", r.report.text())

    def test_new_names_never_collide(self):
        """80 keys: the new names are distinct and never a key that keeps
        its name (a string literal, a library key) or a name a built key
        could spell."""
        keys = [f"key_number_{i:03d}" for i in range(80)]
        src = ("local t = {" + ", ".join(f"{k} = {i}" for i, k in enumerate(keys)) + "}\n"
               "local u = {a = 1, b = 2, ab = 3, x = 4}\n"
               "trace(u['a'], u.b, 'ab', u.x, math.pi, t[string.char(120)])\n"
               "trace(" + ", ".join(f"t.{k}" for k in keys) + ")\n")
        r = M.minify_ex(src, "max")
        ren = self.fields(r)
        self.assertEqual(set(ren), set(keys))
        new = list(ren.values())
        self.assertEqual(len(new), len(set(new)))
        self.assertFalse(set(new) & (M.LIBRARY_KEYS | {"a", "b", "ab", "x"}))
        self.assertTrue(all(len(n) > 1 for n in new))      # string.char(120): one character

    def test_default_keeps_keys(self):
        src = "local t = {long_field_name = 1}\ntrace(t.long_field_name)\n"
        self.assertIn("long_field_name", M.minify(src, "default"))
        self.assertNotIn("long_field_name", M.minify(src, "default,rename-tables"))
        r = M.minify_ex(src, "default")
        self.assertNotIn("table keys", r.report.text())

    @NEEDS_LUA
    def test_same_behaviour(self):
        programs = [
            "local A = {}\nA.__index = A\nfunction A.new(v) return setmetatable({value_slot = v}, A) end\n"
            "function A:twice() return self.value_slot * 2 end\n"
            "local B = setmetatable({}, {__index = A})\nB.__index = B\n"
            "function B.new(v) local o = A.new(v) o.extra_slot = 1 return setmetatable(o, B) end\n"
            "local b = B.new(4)\ntrace(b:twice(), b.extra_slot, b.value_slot)\n",
            "local src, dst, n = {alpha_k = 1, beta_k = 2}, {}, 0\n"
            "for k, v in pairs(src) do dst[k] = v n = n + v end\n"
            "trace(dst.alpha_k, dst.beta_k, n, dst['beta_k'])\n",
            "local h = {number = function(x) return x + 1 end, string = function(x) return #x end}\n"
            "local t = {sprite_01 = 'a', sprite_02 = 'b', plain_key = 'c'}\n"
            "trace(h[type(1)](1), h[type('ab')]('ab'), t[string.format('sprite_%02d', 2)],"
            " t['sprite_0' .. 1], t.plain_key)\n",
            "local list = {{rank_k = 2, name_k = 'b'}, {rank_k = 1, name_k = 'a'}}\n"
            "table.sort(list, function(x, y) return x.rank_k < y.rank_k end)\n"
            "local ok, v = pcall(function(o) return o.name_k end, list[1])\n"
            "trace(list[1].name_k, list[2].name_k, ok, v)\n",
        ]
        def run(src):
            rt = lua53.LuaRuntime(unpack_returned_tuples=True)
            rt.execute("OUT = {} function trace(...) local p = table.pack(...) "
                       "for i = 1, p.n do p[i] = tostring(p[i]) end "
                       "OUT[#OUT + 1] = table.concat(p, ' ', 1, p.n) end")
            rt.execute(src)
            return list(rt.eval("OUT").values())
        for src in programs:
            with self.subTest(src=src[:40]):
                r = M.minify_ex(src, "max")
                self.assertTrue(self.fields(r), r.report.keys_off)
                self.assertEqual(run(r.text), run(src))


@NEEDS_LUA
class TestBehaviour(unittest.TestCase):
    def test_reference_runs_clean(self):
        for name in SAMPLES:
            with self.subTest(sample=name):
                log = run_lua(SAMPLES[name])
                self.assertNotRegex(log, r"(LOAD|RUN|BOOT|TIC)ERROR", log[-300:])
                self.assertIn("trace", log)

    def test_same_behaviour(self):
        for name, opts in combos():
            with self.subTest(sample=name, opts=label(opts)):
                ref = run_lua(SAMPLES[name]).split("\n")
                got = run_lua(minified(name, opts).text).split("\n")
                if got != ref:
                    diff = next(i for i, (a, b) in enumerate(itertools.zip_longest(ref, got))
                                if a != b)
                    self.fail(f"log differs at entry {diff}: expected {ref[diff:diff + 1]},"
                              f" got {got[diff:diff + 1]}")


class TestSizes(unittest.TestCase):
    def test_adding_an_option_never_grows(self):
        for name in SAMPLES:
            for s in EFFECTIVE:
                for o in OPTIONS:
                    t = M.parse_options(s | {o})
                    if t == s:
                        continue
                    with self.subTest(sample=name, base=label(s), add=o):
                        a = len(code_of(minified(name, s).text))
                        b = len(code_of(minified(name, t).text))
                        self.assertLessEqual(b, a)

    def test_whitespace_never_adds_lines(self):
        for name in SAMPLES:
            for s in EFFECTIVE:
                if "whitespace" in s:
                    continue
                t = M.parse_options(s | {"whitespace"})
                with self.subTest(sample=name, base=label(s)):
                    a = code_of(minified(name, s).text).strip().count("\n")
                    b = code_of(minified(name, t).text).strip().count("\n")
                    self.assertLessEqual(b, a)


class TestNominify(unittest.TestCase):
    KEPT = {"keepme_speed", "keepme_lives", "keepme_later", "keepme_above",
            "keepme_global_above", "keepme_const", "keepme_unused", "keepme_table",
            "keepme_i"}

    def test_directive_names(self):
        """The marked declarations and assignments, and nothing else: not the
        string, not "nominifying"."""
        code = code_of(SAMPLES["nominify"])
        self.assertEqual({n for _, n in M.directives(code).names}, self.KEPT)
        self.assertEqual(M.directives(code).comments, [])

    def test_kept_names_reported(self):
        for opts in (M.parse_options("rename-vars"), M.ALL_OPTIONS):
            with self.subTest(opts=label(opts)):
                r = minified("nominify", opts)
                self.assertEqual({n for n, _ in r.report.nominify}, self.KEPT)
                out = code_of(r.text)
                self.assertNotIn("renameme_marker_in_string", out)
                self.assertNotIn("renameme_longer_word", out)
                self.assertNotRegex(out, re.compile("--.*nominify", re.I))   # no comment kept

    def test_not_inlined_or_removed(self):
        """A kept variable keeps its declaration and value: `constants` does
        not inline keepme_const, `extra` does not remove keepme_unused."""
        for opts in EFFECTIVE:
            if not opts:
                continue
            with self.subTest(opts=label(opts)):
                out = code_of(minified("nominify", opts).text)
                self.assertEqual(len(re.findall(r"\bkeepme_const\b", out)), 2)  # declared, read
                self.assertIn("keepme_unused", out)


class TestNominifyFunctionsAndModules(unittest.TestCase):
    """Function- and module-level NOMINIFY (spec R8h): protected bodies come
    out byte for byte under every option set, and what they use is pinned."""

    def outputs(self, name):
        return [(opts, code_of(minified(name, opts).text)) for opts in EFFECTIVE if opts]

    def test_function_regions(self):
        bodies = protected("nominify_funcs")
        self.assertEqual(len(bodies), 6)       # same line, above, closing line,
        for b in bodies:                       # expression, unused, nested - one each
            self.assertTrue(b.startswith("(") and b.endswith("end"), b[:30])
        joined = "".join(bodies)
        self.assertNotIn("this comment is removed", joined)   # blank line ends the block
        self.assertNotIn("removed with the outer", joined)    # outer function not protected
        self.assertNotIn("KEPT_BELOW", joined)     # a block in the body: not the function

    def test_comment_in_body_kept_alone(self):
        """minfn_below's NOMINIFY block, above its return, keeps itself only."""
        kept = kept_comments("nominify_funcs")
        self.assertEqual(len(kept), 2)             # that one, and the one before a blank
        self.assertIn("KEPT_BELOW", kept[0])
        for opts, out in self.outputs("nominify_funcs"):
            with self.subTest(opts=label(opts)):
                for text in kept:
                    self.assertIn(text, out)

    def test_functions_verbatim(self):
        bodies = protected("nominify_funcs")
        for opts, out in self.outputs("nominify_funcs"):
            with self.subTest(opts=label(opts)):
                for b in bodies:
                    self.assertIn(b, out)
                self.assertNotIn("this comment is removed", out)
                self.assertNotIn("removed with the outer", out)

    def test_pinned_names_survive(self):
        for opts, out in self.outputs("nominify_funcs"):
            with self.subTest(opts=label(opts)):
                for name in ("pinned_count", "PINNED_LIMIT"):
                    self.assertRegex(out, rf"\b{name}\b")
                self.assertIn("UNUSED_BUT_KEPT", out)       # kept even by `extra`

    def test_module_regions(self):
        bodies = protected("nominify_modules")
        self.assertEqual(len(bodies), 3)
        for b in bodies:
            self.assertTrue(b.startswith("(...)"), b[:30])  # the whole preload body
        joined = "".join(bodies)
        self.assertIn("keepmod_top:", joined)
        self.assertNotIn("minmod_plain:", joined)

    def test_module_level_wins(self):
        """keepmod_wins' top block also sits directly above `local function
        helper`: the module is protected, not just helper."""
        wins = [b for b in protected("nominify_modules") if "helper" in b]
        self.assertEqual(len(wins), 1)
        self.assertIn("the whole module is protected", wins[0])
        self.assertIn("function M.inc", wins[0])

    def test_blank_line_after_module_block(self):
        """keepmod_blank: NOMINIFY block, blank line, function - module level."""
        blank = [b for b in protected("nominify_modules") if "negate" in b]
        self.assertEqual(len(blank), 1)
        self.assertTrue(blank[0].startswith("(...)"))

    def test_modules_verbatim(self):
        bodies = protected("nominify_modules")
        for opts, out in self.outputs("nominify_modules"):
            with self.subTest(opts=label(opts)):
                for b in bodies:
                    self.assertIn(b, out)
                self.assertNotIn("-- removed", out)                  # minmod_plain

    def test_whole_cart(self):
        self.assertTrue(whole_cart_kept("nominify_main"))
        for opts in EFFECTIVE:
            with self.subTest(opts=label(opts)):
                self.assertEqual(minified("nominify_main", opts).text, SAMPLES["nominify_main"])

    def test_header_tags_do_not_count(self):
        """The nominify sample's desc says "nominify": not a whole-cart directive."""
        self.assertIn("nominify", parts(SAMPLES["nominify"])[0])
        self.assertFalse(whole_cart_kept("nominify"))

    def test_report_lists_them(self):
        r = minified("nominify_funcs", M.ALL_OPTIONS)
        self.assertEqual(len(r.report.verbatim), 6)
        self.assertIn("kept verbatim by a NOMINIFY comment (6)", r.report.text())

    def test_comments_only_keeps_them(self):
        for name in ("nominify_funcs", "nominify_modules"):
            out = code_of(minified(name, frozenset({"comments"})).text)
            for b in protected(name):
                with self.subTest(sample=name, body=b[:30]):
                    self.assertIn(b, out)


class TestNominifyComments(unittest.TestCase):
    """Comments a NOMINIFY directive keeps (spec R8i): every KEPT_ comment
    comes out under every option set but none; the code around them still
    minifies; one inside a call moves after it; one in removed code goes."""

    def test_found(self):
        kept = kept_comments("nominify_comments")
        self.assertEqual([re.search(r"KEPT_\w+", t).group() for t in kept],
                         ["KEPT_1", "KEPT_2", "KEPT_3", "KEPT_4", "KEPT_5", "KEPT_6",
                          "KEPT_7", "KEPT_UNLESS_EXTRA"])

    def test_kept_under_every_set(self):
        for opts in EFFECTIVE:
            if not opts:
                continue
            with self.subTest(opts=label(opts)):
                out = code_of(minified("nominify_comments", opts).text)
                for text in kept_comments("nominify_comments"):
                    if "UNLESS_EXTRA" in text and "extra" in opts:
                        self.assertNotIn(text, out)
                    else:
                        self.assertIn(text, out)
                self.assertNotIn("GONE_", out)
                if "rename-vars" in opts:
                    self.assertNotRegex(out, r"\brenameme_")
                r = minified("nominify_comments", opts)
                if r.report is not None:
                    self.assertEqual(len(r.report.comments), 7 if "extra" in opts else 8)

    def test_moved_out_of_call(self):
        """KEPT_6 sits between a call's arguments: it goes after the call,
        at the end of that line."""
        for opts in (M.parse_options("rename-vars"), M.ALL_OPTIONS):
            with self.subTest(opts=label(opts)):
                out = code_of(minified("nominify_comments", opts).text)
                self.assertRegex(out, r"2\) -- NOMINIFY KEPT_6")

    def test_tag_line_stops(self):
        """A kept comment line starting `-- <` would cut the code in TIC-80."""
        src = "local a = 1\n-- NOMINIFY\n-- <MAP> notes\n\ntrace(a)\n"
        for opts in ("comments", "comments,rename-vars", "comments,rename-functions"):
            with self.subTest(opts=opts):
                with self.assertRaises(M.NominifyError) as e:
                    M.minify_ex(src, opts)
                self.assertEqual(e.exception.line, 3)

    def test_whole_word(self):
        src = "local a = 1 -- nominifying\nlocal b = 2 -- NOMINIFY_X\ntrace(a, b)\n"
        self.assertEqual(M.directives(src).names, frozenset())
        self.assertEqual(M.directives(src).comments, [])


class TestSavings(unittest.TestCase):
    """What each option saved (Result.savings, savings=True): the bytes
    balance line by line and in total, an option that is off saved nothing,
    and what the output is made of adds up to its size."""

    @staticmethod
    @functools.lru_cache(maxsize=None)
    def measured(name, opts):
        return M.minify_cart_ex(SAMPLES[name], mode=opts, meta_keys=META_KEYS, savings=True)

    def test_off_by_default(self):
        self.assertIsNone(minified("basic", M.ALL_OPTIONS).savings)

    def test_same_output(self):
        for name, opts in combos():
            with self.subTest(sample=name, opts=label(opts)):
                self.assertEqual(self.measured(name, opts).text, minified(name, opts).text)

    def test_balanced(self):
        for name, opts in combos():
            with self.subTest(sample=name, opts=label(opts)):
                r = self.measured(name, opts)
                tot = r.savings.total()
                self.assertEqual(tot.get("source"), len(SAMPLES[name].encode("utf-8")))
                self.assertEqual(tot.get("final"), len(r.text.encode("utf-8")))
                for line, d in r.savings.lines.items():
                    self.assertEqual(d.get("source", 0) - d.get("final", 0),
                                     sum(d.get(k, 0) for k in M.SAVINGS), f"line {line}")

    def test_options_off_save_nothing(self):
        for name, opts in combos():
            with self.subTest(sample=name, opts=label(opts)):
                tot = self.measured(name, opts).savings.total()
                for o in ("constants", "extra", "rename-vars", "rename-functions",
                          "rename-tables"):
                    if o not in opts:
                        self.assertFalse(tot.get(o), o)
                if not opts:
                    self.assertFalse(tot.get("comments") or tot.get("whitespace"))

    def test_made_of(self):
        for name, opts in combos():
            with self.subTest(sample=name, opts=label(opts)):
                sv = self.measured(name, opts).savings
                if opts - {"comments"} and not whole_cart_kept(name):
                    self.assertEqual(sum(n for _, n in sv.left), sv.total()["final"])
                    self.assertTrue(all(n > 0 for _, n in sv.left), sv.left)
                else:
                    self.assertEqual(sv.left, [])

    def test_constants_and_extra_split(self):
        """markers has constants to inline and unused code: with both
        options on, each gets its own share. (Rename then has nothing left:
        every renameme_ there is a constant or unused.)"""
        tot = self.measured("markers", M.ALL_OPTIONS).savings.total()
        for o in ("comments", "whitespace", "constants", "extra"):
            self.assertGreater(tot.get(o, 0), 0, o)
        for o in ("constants", "rename-vars"):
            alone = self.measured("markers", M.parse_options(o)).savings.total()
            self.assertGreater(alone[o], 0, o)

    def test_variables_and_functions_split(self):
        """basic has variables and functions to rename: one rename pass does
        both, and each option gets its own share, alone or together."""
        for opts in (M.ALL_OPTIONS, M.parse_options("rename-vars,rename-functions")):
            tot = self.measured("basic", opts).savings.total()
            for o in ("rename-vars", "rename-functions"):
                with self.subTest(opts=label(opts), option=o):
                    self.assertGreater(tot.get(o, 0), 0)
        for o in ("rename-vars", "rename-functions"):
            alone = self.measured("basic", M.parse_options(o)).savings.total()
            self.assertGreater(alone[o], 0, o)

    def test_tables_share(self):
        """basic has table keys to rename: rename-tables gets its own share,
        alone and with every option."""
        for opts in (M.ALL_OPTIONS, M.parse_options("rename-tables")):
            with self.subTest(opts=label(opts)):
                tot = self.measured("basic", opts).savings.total()
                self.assertGreater(tot.get("rename-tables", 0), 0)

    def test_in_report(self):
        text = minified("markers", M.ALL_OPTIONS).report.text()
        self.assertNotIn("bytes saved by option", text)
        text = self.measured("markers", M.ALL_OPTIONS).report.text()
        self.assertIn("bytes saved by option", text)
        self.assertIn("what the minified code is made of", text)

    def test_bundle_table(self):
        tmp = tempfile.mkdtemp(prefix="savings-")
        try:
            t = bundle.Target(PROJECT_MAIN, "game", os.path.join(tmp, "x.lua"))
            with contextlib.redirect_stdout(io.StringIO()):
                raw = bundle.bundle(t, M.ALL_OPTIONS)
            groups, sv, options = t.savings
            self.assertEqual(list(groups), ["main.lua", "constants.lua", "util.lua",
                                            "game.lua", bundle.ADDED])
            self.assertEqual(sum(g["source"] for g in groups.values()), raw)
            self.assertEqual(sum(g["final"] for g in groups.values()),
                             len(t.code[:bundle.CHUNK_RE.search(t.code).start()]
                                 .encode("utf-8")))
            table = report.savings_table(groups, options)
            self.assertRegex(table[1], r"^file +source +comments +whitespace +constants"
                                       r" +extra +rename-vars +rename-functions"
                                       r" +rename-tables +total +reduction$")
            self.assertRegex(table[-2], rf"^total +{raw:,} .* \d+%$")
            self.assertEqual(table[-1], "")         # a blank line ends it
            self.assertEqual([r.split()[0] for r in table[2:-1]],
                             list(groups)[:-1] + ["(added", "total"])
            # comments only: its column and whitespace's
            t = bundle.Target(PROJECT_MAIN, "game", os.path.join(tmp, "y.lua"))
            with contextlib.redirect_stdout(io.StringIO()):
                bundle.bundle(t, M.parse_options("comments"))
            groups, _, options = t.savings
            table = report.savings_table(groups, options)
            self.assertRegex(table[1], r"^file +source +comments +whitespace +total +reduction$")
            t = bundle.Target(PROJECT_MAIN, "game", os.path.join(tmp, "z.lua"))
            with contextlib.redirect_stdout(io.StringIO()):
                bundle.bundle(t, frozenset())
            self.assertIsNone(t.savings)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_removed_module_marked(self):
        groups = {"main.lua": {"source": 2048, "comments": 1024, "final": 1024},
                  "unused.lua": {"source": 1024, "extra": 1024}}
        table = report.savings_table(groups, M.ALL_OPTIONS)
        self.assertTrue(table[3].endswith("(removed: unused)"))
        self.assertFalse(table[2].endswith("(removed: unused)"))
        self.assertRegex(table[3], r" 100%  \(removed: unused\)$")
        self.assertRegex(table[4], r"^total +3,072 +1,024 +0 +0 +1,024 +0 +0 +0 +1,024 +67%$")


class TestBundle(unittest.TestCase):
    """bundle.bundle() on project/ for every effective set (no TIC-80 run)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="minify-options-")
        cls.main = os.path.join(HERE, "project", "main.lua")
        cls.bundles = {}
        for opts in EFFECTIVE:
            t = bundle.Target(cls.main, "minitest_project",
                                 os.path.join(cls.tmp, label(opts).replace(",", "+")))
            with contextlib.redirect_stdout(io.StringIO()):
                bundle.bundle(t, minify_options=opts)
            # the bundle is written in text mode (CRLF on Windows): read it
            # back the same way so line endings don't count as a difference
            with open(t.lua, encoding="utf-8") as f:
                cls.bundles[opts] = f.read()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_assets_and_header(self):
        chunks = parts(read(self.main))[2]
        for opts, text in self.bundles.items():
            with self.subTest(opts=label(opts)):
                self.assertEqual(parts(text)[2], chunks)
                self.assertTrue(check.check_header(text[:bundle.CHUNK_RE.search(text).start()],
                                                    quiet=True))

    def test_option_signatures(self):
        for opts, text in self.bundles.items():
            code = code_of(text)
            with self.subTest(opts=label(opts)):
                self.assertIn("keepme_frame", code)                 # NOMINIFY
                self.assertIn("{12,9,6}", code.replace(" ", ""))    # a table: never inlined
                self.assertEqual("rename-vars" in opts, "CONST_COLORS" not in code)
                self.assertEqual("rename-vars" in opts, "renameme_ball" not in code)
                self.assertEqual("rename-functions" in opts, "renamefn_land" not in code)
                self.assertEqual("rename-tables" in opts, "renamekey_spin" not in code)
                if "constants" in opts:
                    # inlined at its reads, and its declaration gone from the module
                    module = re.search(r'preload\["constants"\]=function\(\.\.\.\)(.*?)\bend\b',
                                       code, re.S).group(1)
                    self.assertNotIn("CONST_FLOOR", code)
                    self.assertNotIn("120", module)
                elif not opts & {"rename-vars", "extra"}:
                    self.assertIn("CONST_FLOOR", code)
                if opts:
                    self.assertEqual(M.strip_comments(code), code)

    def test_tag_line_guard(self):
        """A comment line starting `-- <` would end the code for TIC-80's
        loader: the unminified bundle must stop and name its source line."""
        bundle.tag_lines("local a = 1\n  -- <MAP> indented is fine\nx = '-- <MAP>'\n")
        origin = [("m.lua", 1), ("m.lua", 2), ("m.lua", 3)]
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            bundle.tag_lines("local a = 1\n-- <MAP> region notes\nend\n", origin)
        self.assertIn("m.lua:2", out.getvalue())

    def test_minify_label(self):
        self.assertEqual(bundle.minify_label(frozenset()), "none")
        self.assertEqual(bundle.minify_label(M.DEFAULT_OPTIONS), "default")
        self.assertEqual(bundle.minify_label(M.ALL_OPTIONS), "max")
        self.assertEqual(bundle.minify_label(M.parse_options("whitespace,rename-vars")),
                         "comments, rename-vars, whitespace")

    def test_minify_flag_round_trip(self):
        """The -m flag a build's `-- ticpak:` line records reads back as the
        same options; an older build's `rename` reads as rename-vars."""
        for opts, flag in ((frozenset(), ""), (M.DEFAULT_OPTIONS, "-m"),
                           (M.ALL_OPTIONS, "-m=max"),
                           (M.parse_options("rename-functions"), "-m=comments,rename-functions"),
                           (M.parse_options("rename-tables"), "-m=comments,rename-tables"),
                           (M.DEFAULT_OPTIONS - {"rename-functions"},
                            "-m=comments,rename-vars,constants,whitespace,extra")):
            with self.subTest(flag=flag):
                self.assertEqual(bundle.minify_flag(opts), flag)
                self.assertEqual(bundle.flag_options(flag), opts)
                self.assertEqual(bundle.flag_options(flag, __version__), opts)
        # a bare -m stamped before 0.4.4 meant default without rename-functions
        for version in ("0.4.3", "0.3.4"):
            self.assertEqual(bundle.flag_options("-m", version),
                             M.DEFAULT_OPTIONS - {"rename-functions"})
        self.assertEqual(bundle.flag_options("-m=comments,rename,whitespace"),
                         {"comments", "rename-vars", "whitespace"})
        self.assertEqual(bundle.flag_options("-m=comments,bogus"), {"comments"})

    @NEEDS_LUA
    def test_same_behaviour(self):
        ref = run_lua(self.bundles[frozenset()])
        self.assertNotRegex(ref, r"(LOAD|RUN|BOOT|TIC)ERROR", ref[-300:])
        for opts, text in self.bundles.items():
            with self.subTest(opts=label(opts)):
                self.assertEqual(run_lua(text), ref)


class TestBundleAssets(unittest.TestCase):
    """bundle.bundle()'s own cart split on every asset layout (TestBundle's
    project has bank 0's only), and asset sections where they don't belong."""

    SETS = (frozenset(), M.parse_options("comments"), M.ALL_OPTIONS)

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="bundle-assets-")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def build(self, main, opts, out="out"):
        t = bundle.Target(main, "assets", os.path.join(os.path.dirname(main), out))
        with contextlib.redirect_stdout(io.StringIO()):
            bundle.bundle(t, minify_options=opts)
        return read_text(t.lua)

    def test_every_layout_kept(self):
        for layout, nl in ASSET_PROJECTS:
            main = asset_project(os.path.join(self.tmp, f"{layout}{len(nl)}"), layout, nl)
            chunks = parts(read_text(main))[2]
            self.assertTrue(chunks)
            for opts in self.SETS:
                with self.subTest(layout=layout, crlf=nl != "\n", opts=label(opts)):
                    self.assertEqual(parts(self.build(main, opts, label(opts)))[2], chunks)

    def test_no_assets_stops(self):
        main = asset_project(os.path.join(self.tmp, "none"), "none")
        with self.assertRaises(SystemExit) as e:
            self.build(main, frozenset())
        self.assertIn("no asset chunks", str(e.exception))

    def test_module_section_stops(self):
        """Unminified, TIC-80 would cut the code at a module's section tag;
        minified, the section is comments and would vanish silently."""
        main = asset_project(os.path.join(self.tmp, "modsec"), "minimal")
        util = os.path.join(os.path.dirname(main), "util.lua")
        line = read_text(util).count("\n") + 2
        with open(util, "a", encoding="utf-8") as f:
            f.write("\n-- <MAP>\n-- 000:0102030405\n-- </MAP>\n")
        for opts in self.SETS:
            with self.subTest(opts=label(opts)), self.assertRaises(SystemExit) as e:
                self.build(main, opts)
            self.assertIn(f"util.lua:{line} starts an asset section (-- <MAP>)",
                          str(e.exception))

    def test_module_prose_tag_minified(self):
        """`-- <MAP> notes` is a comment, not a section: minifying removes it
        (the unminified stop is test_tag_line_guard's)."""
        main = asset_project(os.path.join(self.tmp, "prose"), "minimal")
        with open(os.path.join(os.path.dirname(main), "util.lua"), "a",
                  encoding="utf-8") as f:
            f.write("\n-- <MAP> region notes\n")
        self.assertNotIn("region notes", self.build(main, M.parse_options("comments")))


@unittest.skipUnless(os.environ.get("TICPAK_BOOT"), "set TICPAK_BOOT=1 to boot TIC-80")
class TestBoot(unittest.TestCase):
    """Bundles boot in real TIC-80 and save a .tic that passes check.py and
    holds main.lua's assets byte for byte (slow: one headless TIC-80 run per
    bundle): the project under every effective set, then every asset layout."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="minify-boot-")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def boot(self, main, opts, out):
        t = bundle.Target(main, "minitest_project", os.path.join(self.tmp, out))
        with contextlib.redirect_stdout(io.StringIO()):
            bundle.bundle(t, minify_options=opts)
            tic = run.verify(t)                   # exits on failure
        self.assertTrue(check.check_tic(tic, quiet=True))
        want, got = text_assets(parts(read_text(main))[2]), tic_assets(tic)
        self.assertTrue(want)
        for key, data in want.items():
            self.assertEqual(got.get(key, b""), data, f"{key[0]} bank {key[1]}")

    def test_boots(self):
        for i, opts in enumerate(EFFECTIVE, 1):
            with self.subTest(opts=label(opts)):
                print(f"\nboot {i}/{len(EFFECTIVE)}: {label(opts)}", file=sys.stderr)
                self.boot(PROJECT_MAIN, opts, label(opts).replace(",", "+"))

    def test_asset_layouts(self):
        for layout, nl in ASSET_PROJECTS:
            with self.subTest(layout=layout, crlf=nl != "\n"):
                print(f"\nboot assets: {layout}{' crlf' if nl != chr(10) else ''}",
                      file=sys.stderr)
                main = asset_project(os.path.join(self.tmp, f"src-{layout}{len(nl)}"),
                                     layout, nl)
                self.boot(main, M.ALL_OPTIONS, f"out-{layout}{len(nl)}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
