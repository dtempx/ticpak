#!/usr/bin/env python3
"""Unit tests for every combination of the minifier's options, on sample carts.

    python tests/options/test_options.py        # all tests
    python tests/options/test_options.py -k Behaviour
    TICPAK_BOOT=1 python tests/options/test_options.py -k Boot

The five options (comments, rename, constants, whitespace, extra) give 32
subsets; since every option but `comments` implies it, they collapse to 17
distinct effective sets, and each runs on each cart in samples/ (built by
make_samples.py) and on the ticpak project in project/. Per combination:

  OptionParsing  empty set, `max` alias, unknown names rejected, implied
                 `comments`, raw subset == its effective set
  CommandLine        --minify absent = none, bare = all, =a,b = those only;
                 preset names rejected; a path after --minify hinted;
                 -m, -o/--out, -f/--force, --verbose, -v/--version;
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
                 renameme_* shortened, CONST_* inlined and removed, lines
                 packed to 120 columns, unused/dead code and call sugar
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
                 under every option set, used names pinned
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
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)                    # the ticpak package, installed or not
sys.path.insert(0, HERE)                    # make_samples, for its asset layouts
from ticpak import minify as M  # noqa: E402
from ticpak import bundle, check, cli, report, run  # noqa: E402
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
    def test_empty_and_max(self):
        self.assertEqual(M.parse_options(""), frozenset())
        self.assertEqual(M.parse_options([]), frozenset())
        self.assertEqual(M.ALL_OPTIONS, set(OPTIONS))
        self.assertEqual(M.parse_options("max"), M.ALL_OPTIONS)   # API alias

    def test_spelling(self):
        self.assertEqual(M.parse_options(" rename , whitespace "),
                         {"comments", "rename", "whitespace"})
        self.assertEqual(M.parse_options(["constants"]), {"comments", "constants"})

    def test_unknown_rejected(self):
        for bad in ("bogus", "dead", "fold", "comments,unused", "Rename",
                    "default", "all", "none"):
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

    def test_seventeen_effective_sets(self):
        self.assertEqual(len(SUBSETS), 32)
        self.assertEqual(len(EFFECTIVE), 17)


class TestCommandLine(unittest.TestCase):
    """ticpak's command line: --minify absent = none, bare = all, =a,b =
    those only; -f/--force, --verbose and -v/--version."""

    def parse(self, *argv):
        with contextlib.redirect_stderr(io.StringIO()):
            return cli.parse_args(list(argv))

    def test_absent_is_none(self):
        for argv in ([], ["build"], ["build", "-f", "src/main.lua"], ["check"]):
            with self.subTest(argv=argv):
                self.assertEqual(self.parse(*argv)[1].minify, frozenset())

    def test_bare_is_all(self):
        for argv in (["--minify"], ["build", "-f", "--minify"],
                     ["build", "src/main.lua", "--minify"],
                     ["build", "-m"], ["build", "-m", "-f"]):
            with self.subTest(argv=argv):
                self.assertEqual(self.parse(*argv)[1].minify, M.ALL_OPTIONS)

    def test_listed_options(self):
        for argv, want in ((["--minify=rename,extra"], {"comments", "rename", "extra"}),
                           (["-m", "rename,extra"], {"comments", "rename", "extra"}),
                           (["-m=rename"], {"comments", "rename"}),
                           (["-mrename"], {"comments", "rename"}),
                           (["--minify", "whitespace"], {"comments", "whitespace"}),
                           (["--minify=comments"], {"comments"})):
            with self.subTest(argv=argv):
                self.assertEqual(self.parse(*argv)[1].minify, want)

    def test_rejected(self):
        for argv in (["--minify=all"], ["--minify=default"], ["--minify=none"],
                     ["--minify=max"], ["--minify=rename,bogus"], ["--minify="],
                     ["--minify", "src/main.lua"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                self.parse(*argv)

    def test_path_hint(self):
        with self.assertRaises(argparse.ArgumentTypeError) as e:
            cli.minify_arg("src/main.lua")
        self.assertIn("put SOURCE before --minify", str(e.exception))

    def test_out(self):
        self.assertEqual(self.parse("build", "--out", "x")[1].out, "x")
        self.assertEqual(self.parse("build", "-o", "x")[1].out, "x")
        self.assertIsNone(self.parse("build")[1].out)

    def test_force_and_verbose(self):
        _, args, _ = self.parse("build", "-f", "--verbose")
        self.assertTrue(args.force and args.verbose)
        _, args, _ = self.parse("build", "--force", "--verbose")
        self.assertTrue(args.force and args.verbose)
        _, args, _ = self.parse("build")
        self.assertFalse(args.force or args.verbose)
        _, args, _ = self.parse("check", "--verbose")
        self.assertTrue(args.verbose)

    def test_v_is_version(self):
        for flag in ("-v", "--version"):
            out = io.StringIO()
            with self.subTest(flag=flag), contextlib.redirect_stdout(out), \
                    self.assertRaises(SystemExit) as e:
                self.parse("build", flag)
            self.assertEqual(e.exception.code, 0)
            self.assertIn("ticpak ", out.getvalue())

    def test_check_force_rejected(self):
        with self.assertRaises(SystemExit):
            self.parse("check", "-f")

    def test_quiet(self):
        for argv in (["build", "-q"], ["build", "--quiet", "-f"], ["check", "-q"],
                     ["check", "-q", os.path.join(HERE, "README.md")]):
            with self.subTest(argv=argv):
                self.assertTrue(self.parse(*argv)[1].quiet)
        for argv in (["-q"], ["build", "-q", "--verbose"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                self.parse(*argv)

    def test_report(self):
        self.assertIsNone(self.parse("build")[1].report)
        for argv, want in ((["build", "-r"], True), (["build", "-r", "-f"], True),
                           (["build", "--report"], True),
                           (["build", "-r", "out.txt"], "out.txt"),
                           (["build", "-r=out.txt"], "out.txt"),
                           (["build", "--report=logs/"], "logs/"),
                           (["build", "src", "-r"], True)):
            with self.subTest(argv=argv):
                self.assertEqual(self.parse(*argv)[1].report, want)
        for argv in (["build", "-r", "main.lua"], ["build", "--report=x.tic"],
                     ["build", "--report="],
                     ["check", os.path.join(HERE, "README.md"), "-r"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                self.parse(*argv)

    def test_name_with_file_out_rejected(self):
        for out in ("x.tic", "x.lua", "a/X.TIC"):
            with self.subTest(out=out), self.assertRaises(SystemExit):
                self.parse("build", "-n", "y", "-o", out)
        self.assertEqual(self.parse("build", "-n", "y", "-o", "dist")[1].out, "dist")


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
        """-r: <name>.ticpak.txt beside the output; -r PATH: that file, or
        <name>.ticpak.txt in a folder."""
        d = os.path.dirname(self.MAIN)
        self.assertEqual(bundle.Target(self.MAIN, "game", None, True).txt,
                         os.path.join(d, "game.ticpak.txt"))
        self.assertEqual(bundle.Target(self.MAIN, "game", "dist/", True).txt,
                         os.path.join(os.path.abspath("dist"), "game.ticpak.txt"))
        self.assertEqual(bundle.Target(self.MAIN, "game", "x/my.tic", True).txt,
                         os.path.join(os.path.abspath("x"), "my.ticpak.txt"))
        self.assertEqual(bundle.Target(self.MAIN, "game", None, "r.txt").txt,
                         os.path.abspath("r.txt"))
        self.assertEqual(bundle.Target(self.MAIN, "game", None, "logs/").txt,
                         os.path.join(os.path.abspath("logs"), "game.ticpak.txt"))
        self.assertEqual(bundle.Target(self.MAIN, "game", None, HERE).txt,
                         os.path.join(HERE, "game.ticpak.txt"))     # an existing folder

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

        def text(self, message, default=""):
            return self._next(message, default)

        def select(self, message, choices, default):
            return self._next(message, default)

        def checkbox(self, message, choices, checked):
            return self._next(message, checked)

    def test_interactive_tic_default(self):
        ui = self.UI(None, "all", None)
        self.assertEqual(cli.ask_build_settings(ui, frozenset(), "game", None),
                         (M.ALL_OPTIONS, "game", None))
        self.assertEqual(ui.asked[-1], "Output:")

    def test_interactive_folder(self):
        ui = self.UI("Other Name", "none", "dir", None)
        self.assertEqual(cli.ask_build_settings(ui, frozenset(), "game", None),
                         (frozenset(), "other-name", "dist/"))
        ui = self.UI(None, None, None, "x.lua")
        self.assertEqual(cli.ask_build_settings(ui, frozenset(), "game", "out")[2], "x.lua/")

    def test_interactive_file_out_asks_minify_only(self):
        ui = self.UI("all")
        self.assertEqual(cli.ask_build_settings(ui, frozenset(), "game", "a.tic"),
                         (M.ALL_OPTIONS, "game", "a.tic"))
        self.assertEqual(ui.asked, ["Minification:"])

    def test_build_command(self):
        self.assertEqual(cli.build_command(None, M.ALL_OPTIONS, "g", "g", None),
                         "ticpak build -m")
        self.assertEqual(cli.build_command(None, frozenset(), "h", "g", "dist/"),
                         "ticpak build -n h -o dist/")
        self.assertEqual(cli.build_command("src", frozenset(), "a", "g", "a.tic"),
                         "ticpak build src -o a.tic")
        self.assertEqual(cli.build_command(None, frozenset(), "g", "g", None, True),
                         "ticpak build -r")
        self.assertEqual(cli.build_command(None, frozenset(), "g", "g", None, "my r.txt"),
                         'ticpak build "--report=my r.txt"')


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

    def summary(self, chunks, unminified):
        d = tempfile.mkdtemp(prefix="minify-summary-")
        try:
            path = os.path.join(d, "game.tic")
            with open(path, "wb") as f:
                f.write(self.tic(chunks))
            return report.size_summary(path, unminified)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_minified_under_limit(self):
        # CODE 42K (type 5), MAP 30K (4), PALETTE 48 B (12), all bank 0
        # total = 43008 + 30720 + 48 + 3 chunk headers of 4 bytes = 73788
        lines = self.summary([(5, 0, 43008), (4, 0, 30720), (12, 0, 48)], 157696)
        self.assertEqual(lines, ["size: 72K",
                                     "code: 42K (58%)",
                                     "assets: 30K (42%)",
                                     "42K / 64K code size limit (66% used, 34% free)",
                                     "154K unminified (73% reduction)"])

    def test_unminified_over_limit_two_banks(self):
        # code split over two chunks (64K + 6K), maps in banks 0 and 1;
        # total = 65535 + 6145 + 1024 + 1024 + 4 headers = 73744
        lines = self.summary([(5, 1, 65535), (5, 0, 6145), (4, 0, 1024), (4, 1, 1024)],
                             71680)
        self.assertEqual(lines, ["size: 72K",
                                     "code: 70K (97%)",
                                     "assets: 2.0K (3%)",
                                     "70K / 64K code size limit (109% used) - over the"
                                     " free editor's limit, fine on PRO (up to 512K)",
                                     "not minified"])

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
                        self.assertIn("game.ticpak.txt", out.getvalue().splitlines()[-1])
                        text = read_text(os.path.join(d, "game.ticpak.txt"))
                        self.assertIn("minify: bytes saved", text)
                        self.assertIn("3,000", text)
                        self.assertTrue(text.startswith("check: "))
                    else:
                        self.assertFalse(os.path.exists(os.path.join(d, "game.ticpak.txt")))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_unknown_unminified(self):
        lines = self.summary([(5, 0, 1000)], None)
        self.assertEqual(lines, ["size: 0.98K",
                                     "code: 0.98K (100%)",
                                     "assets: 0.00K (0%)",
                                     "0.98K / 64K code size limit (2% used, 98% free)"])


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
                if "rename" in opts:
                    self.assertFalse(left, "not renamed")
                elif opts & {"constants", "extra"}:
                    # a renameme_ that is a constant or unused may be removed
                    self.assertLessEqual(left, marked)
                else:
                    self.assertEqual(left, marked)
                self.assertEqual(names(r"\bkeepme_\w+", out), kept, "NOMINIFY name lost")

    def test_constants(self):
        for name, opts in combos():
            consts = names(r"\bCONST_\w+", code_of(SAMPLES[name]))
            with self.subTest(sample=name, opts=label(opts)):
                out = names(r"\bCONST_\w+", code_of(minified(name, opts).text))
                if "constants" in opts:
                    self.assertFalse(out, "constants left in place")
                elif not opts & {"extra", "rename"}:
                    # (extra's folding may drop them too; rename shortens them)
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
        for opts in (M.parse_options("rename"), M.ALL_OPTIONS):
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
                if "rename" in opts:
                    self.assertNotRegex(out, r"\brenameme_")
                r = minified("nominify_comments", opts)
                if r.report is not None:
                    self.assertEqual(len(r.report.comments), 7 if "extra" in opts else 8)

    def test_moved_out_of_call(self):
        """KEPT_6 sits between a call's arguments: it goes after the call,
        at the end of that line."""
        for opts in (M.parse_options("rename"), M.ALL_OPTIONS):
            with self.subTest(opts=label(opts)):
                out = code_of(minified("nominify_comments", opts).text)
                self.assertRegex(out, r"2\) -- NOMINIFY KEPT_6")

    def test_tag_line_stops(self):
        """A kept comment line starting `-- <` would cut the code in TIC-80."""
        src = "local a = 1\n-- NOMINIFY\n-- <MAP> notes\n\ntrace(a)\n"
        for opts in ("comments", "comments,rename"):
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
                for o in ("constants", "extra", "rename"):
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
        for o in ("constants", "rename"):
            alone = self.measured("markers", M.parse_options(o)).savings.total()
            self.assertGreater(alone[o], 0, o)

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
                                       r" +extra +rename +after$")
            self.assertRegex(table[-1], rf"^total +{raw:,} ")
            self.assertEqual([r.split()[0] for r in table[2:]],
                             list(groups)[:-1] + ["(added", "total"])
            # comments only: its column and whitespace's
            t = bundle.Target(PROJECT_MAIN, "game", os.path.join(tmp, "y.lua"))
            with contextlib.redirect_stdout(io.StringIO()):
                bundle.bundle(t, M.parse_options("comments"))
            groups, _, options = t.savings
            table = report.savings_table(groups, options)
            self.assertRegex(table[1], r"^file +source +comments +whitespace +after$")
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
        self.assertRegex(table[4], r"^total +3,072 +1,024 +0 +0 +1,024 +0 +1,024$")


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
                self.assertEqual("rename" in opts, "CONST_COLORS" not in code)
                self.assertEqual("rename" in opts, "renameme_ball" not in code)
                if "constants" in opts:
                    # inlined at its reads, and its declaration gone from the module
                    module = re.search(r'preload\["constants"\]=function\(\.\.\.\)(.*?)\bend\b',
                                       code, re.S).group(1)
                    self.assertNotIn("CONST_FLOOR", code)
                    self.assertNotIn("120", module)
                elif not opts & {"rename", "extra"}:
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
        self.assertEqual(bundle.minify_label(M.ALL_OPTIONS), "all")
        self.assertEqual(bundle.minify_label(M.parse_options("whitespace,rename")),
                         "comments, rename, whitespace")

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
