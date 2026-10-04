#!/usr/bin/env python3
"""Unit tests for every combination of the minifier's options, on sample carts.

    python tests/options/test_options.py        # all tests
    python tests/options/test_options.py -k Behaviour
    TICPAK_BOOT=1 python tests/options/test_options.py -k Boot

The five options (comments, rename, constants, whitespace, extra) give 32
subsets; since every option but `comments` implies it, they collapse to 17
distinct effective sets, and each runs on each cart in samples/ (built by
make_samples.py) and on the ticpak project in project/. Per combination:

  OptionParsing  empty set, `max` alias, old presets rejected, implied
                 `comments`, raw subset == its effective set
  CommandLine        --minify absent = none, bare = all, =a,b = those only;
                 presets and --no-minify rejected; a path after --minify hinted;
                 -m, -o/--out, -f/--force, -v/--verbose; `rebuild`,
                 `check -f`, --no-check and --output rejected
  Summary        the closing size summary's lines and arithmetic, on a .tic
                 built by hand (no TIC-80 run)
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
  Nominify       NOMINIFY-marked names survive `rename` (spec R8g)
  NominifyFunctionsAndModules  function- and module-level NOMINIFY (R8h):
                 same line / block above / block below a declaration, nested
                 and unused functions, a module's top block, module level
                 winning, a blank line ending a block, the whole cart; bodies
                 byte for byte under every option set, used names pinned
  Bundle         the project bundled by bundle.bundle() for every set behaves
                 like the unminified bundle, keeps its assets and header
  Boot           (TICPAK_BOOT=1 only - runs TIC-80) each bundle boots headless
                 and saves a .tic that passes check.py

Behaviour and Bundle need lupa (pip install lupa); without it they skip.
"""
import argparse
import contextlib
import functools
import io
import itertools
import os
import re
import shutil
import sys
import tempfile
import unittest
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)                    # the ticpak package, installed or not
from ticpak import minify as M  # noqa: E402
from ticpak import bundle, check, cli, report, run  # noqa: E402

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


def whole_cart_kept(name):
    """Does the sample's top comment block turn minification off?"""
    return minified(name, M.ALL_OPTIONS).text == SAMPLES[name]


def without_protected(name, code):
    """code with every protected body cut out (they keep their comments)."""
    for body in protected(name):
        code = code.replace(body, "(...)end")
    return code


def combos():
    """(sample name, effective option set) for every combination."""
    return [(n, o) for n in SAMPLES for o in EFFECTIVE]


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
        # the old presets are gone too
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
    those only; -f/--force and -v/--verbose; `rebuild` gone."""

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
                     ["--no-minify"], ["--minify", "src/main.lua"]):
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
        _, args, _ = self.parse("build", "-f", "-v")
        self.assertTrue(args.force and args.verbose)
        _, args, _ = self.parse("build", "--force", "--verbose")
        self.assertTrue(args.force and args.verbose)
        _, args, _ = self.parse("build")
        self.assertFalse(args.force or args.verbose)
        _, args, _ = self.parse("check", "-v")
        self.assertTrue(args.verbose)

    def test_rebuild_and_check_force_rejected(self):
        for argv in (["check", "-f"], ["build", "--no-check"],
                     ["build", "--output", "x"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                self.parse(*argv)


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
                keep = M.nominify_regions(code_in)
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
    def test_marker_lines(self):
        code = code_of(SAMPLES["nominify"])
        marked = {i + 1 for i, line in enumerate(code.split("\n"))
                  if re.search(r"--.*nominify", line, re.I)}
        self.assertEqual(M.nominify_lines(code), marked)
        self.assertEqual(len(marked), 3)            # the string one is not a marker

    def test_kept_names_reported(self):
        r = minified("nominify", M.parse_options("rename"))
        self.assertEqual({n for n, _ in r.report.nominify},
                         {"keepme_speed", "keepme_lives", "keepme_later"})
        out = code_of(r.text)
        self.assertNotIn("renameme_marker_in_string", out)
        self.assertNotRegex(out, re.compile("nominify --|-- *nominify", re.I))


class TestNominifyFunctionsAndModules(unittest.TestCase):
    """Function- and module-level NOMINIFY (spec R8h): protected bodies come
    out byte for byte under every option set, and what they use is pinned."""

    def outputs(self, name):
        return [(opts, code_of(minified(name, opts).text)) for opts in EFFECTIVE if opts]

    def test_function_regions(self):
        bodies = protected("nominify_funcs")
        self.assertEqual(len(bodies), 6)       # same line, above, below, expression,
        for b in bodies:                       # unused, nested - one each
            self.assertTrue(b.startswith("(") and b.endswith("end"), b[:30])
        joined = "".join(bodies)
        self.assertNotIn("this comment is removed", joined)   # blank line ends the block
        self.assertNotIn("removed with the outer", joined)    # outer function not protected

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


@unittest.skipUnless(os.environ.get("TICPAK_BOOT"), "set TICPAK_BOOT=1 to boot TIC-80")
class TestBoot(unittest.TestCase):
    """Every effective set's project bundle boots in real TIC-80 and saves a
    .tic that passes check.py (slow: one headless TIC-80 run per set)."""

    def test_boots(self):
        tmp = tempfile.mkdtemp(prefix="minify-boot-")
        try:
            main = os.path.join(HERE, "project", "main.lua")
            for i, opts in enumerate(EFFECTIVE, 1):
                with self.subTest(opts=label(opts)):
                    print(f"\nboot {i}/{len(EFFECTIVE)}: {label(opts)}", file=sys.stderr)
                    t = bundle.Target(main, "minitest_project",
                                         os.path.join(tmp, label(opts).replace(",", "+")))
                    with contextlib.redirect_stdout(io.StringIO()):
                        bundle.bundle(t, minify_options=opts)
                        tic = run.verify(t)                   # exits on failure
                    self.assertTrue(check.check_tic(tic, quiet=True))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
