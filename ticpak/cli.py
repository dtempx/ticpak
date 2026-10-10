#!/usr/bin/env python3
"""TIC-80 distribution packager: bundle, minify, verify, export.

Inlines the modules a TIC-80 cart's entry stub requires into one text cart,
optionally minifies it, boots it headless, saves the .tic and checks it. Full
documentation: README.md. This file is the console front end - the command
line, the interactive questions, and the dispatch to the modules that do the
work:

  bundle.py   find the cart, the outputs (-o), inline its modules, minify,
              write <name>.lua
  run.py      find TIC-80, boot the bundle headless, save <name>.tic;
              `ticpak run`, `test`: the cart in TIC-80's window
  report.py   check the .tic (check.py), the summary, the -r report file
  header.py   the metadata header: output name, missing tags, filling in
  console.py  --verbose, the flush-left console, the prompts
  errors.py   `ticpak decode` and `test`: a packaged cart's runtime error, decoded
  scaffold.py `ticpak init`: a new project's main.lua and first module
  minify.py   the minifier;  check.py  the .tic checker
"""
import argparse
import contextlib
import io
import os
import shutil
import sys
import tempfile

from . import __version__, console, errors
from . import minify as minifier
from .scaffold import init_project
from .bundle import (DEFAULT_DIR, Target, built_options, built_target, bundle,
                     check_sources, find_cart, freshness, is_cart, minify_flag, minify_module, options_label,
                     out_kind, save_bundle, stub_requires, unminified_size)
from .check import check_lua, check_tic, parse_header
from .console import FlatStdout, Progress, Prompts, fwd, has_terminal, highlight, show
from .header import META_KEYS, cart_code, ensure_header, package_name, slug
from .report import (check_summary, kb, made_of_lines, savings_table, size_summary,
                     write_report)
from .run import BOOT_SECONDS, play, verify

EXAMPLES = """examples (run from the port's directory, the one holding main.lua):
  ticpak init                     a new project here: main.lua and game.lua
  ticpak init mygame              ...in mygame/ (made if missing)
  ticpak                          interactive: status, or asks to build
  ticpak bundle                    build + check if out of date: <name>.tic beside main.lua
  ticpak bundle -f                 build + check regardless (--force)
  ticpak bundle --verbose          ...showing progress, the check's detail, minify savings
  ticpak check                    check the existing .tic: summary only
  ticpak check --verbose          ...and the full check report
  ticpak bundle -f -m              the default minify options (all but rename-tables)
  ticpak bundle -f -m=max          every minify option (smallest cart)
  ticpak bundle -f -m=comments,whitespace   just those minify options
  ticpak bundle path/to/main.lua   a cart elsewhere
  ticpak bundle -n mygame          override the output name: mygame.tic
  ticpak bundle -o mygame.tic      just this .tic
  ticpak bundle -o mygame.lua      just the bundle (still boot-tested and checked)
  ticpak bundle -o dist/           dist/<name>.tic and .lua (the bundle)
  ticpak bundle -f -r              also the full report: <name>.bundle.txt beside the .tic
  ticpak bundle -f --report=r.txt  the full report to r.txt instead
  ticpak bundle -q                 no output: just the exit status
  ticpak bundle enemies.lua -m     one module on its own -> enemies.min.lua
  ticpak check main.lua dist/x.tic   check exactly these files: full report
  ticpak run                      run main.lua (the sources) in TIC-80
  ticpak test                     run the package in TIC-80, its errors in the
                                   sources' files, lines and names
  ticpak decode                   the error copied from TIC-80's console (select it,
                                   Ctrl+C), in the sources' files, lines and names
  ticpak decode --log tic80.log   the last error in a log of TIC-80's output
  ticpak decode -e "[string ...]:37: attempt to ..."   the error given inline
  ticpak minify enemies.lua       the minifier on its own (ticpak minify --help)

full documentation: https://github.com/dtempx/ticpak#readme
"""

COMMANDS = ("init", "bundle", "check", "run", "test", "decode")  # `minify`: dispatched before argparse


def minify_arg(text):
    """--minify=OPTION,... / -m OPTION,...: option names, or a preset
    (default, max). argparse hands `-m=a,b` over as "=a,b", so a leading =
    is dropped."""
    text = text[1:] if text.startswith("=") else text
    items = [i.strip() for i in text.split(",") if i.strip()]
    bad = [i for i in items if i not in minifier.OPTIONS and i not in minifier.PRESETS]
    if bad and (os.path.sep in text or "/" in text or text.endswith(".lua")
                or os.path.exists(text)):
        raise argparse.ArgumentTypeError(
            f"{text!r} looks like a path, not minify options - put SOURCE before"
            " --minify, or write --minify=OPTION,...")
    if bad or not items:
        raise argparse.ArgumentTypeError(
            f"unknown minify option {', '.join(map(repr, bad)) or repr(text)}"
            f" (expected one or more of {', '.join(minifier.OPTIONS)}, or default"
            " or max; --minify alone means default: every option but"
            " rename-tables)")
    return minifier.parse_options(items)


def report_arg(text):
    """-r PATH / --report=PATH: where to write the full report. argparse
    hands `-r=x` over as "=x", so a leading = is dropped. A .lua or .tic is
    refused: it is the SOURCE or an output, read as the report's path."""
    text = text[1:] if text.startswith("=") else text
    if not text:
        raise argparse.ArgumentTypeError("--report= needs a path (or give -r alone)")
    if text.lower().endswith((".lua", ".tic")):
        raise argparse.ArgumentTypeError(
            f"{text!r} is not a report file - put SOURCE before -r, or write"
            " --report=PATH (a .txt file or a folder)")
    return text


def ask_minify(ui, minify):
    """Minification: the default options, comments only, max (every
    option), none, or the individual options as checkboxes. minify is the
    default; returns the chosen options."""
    presets = {"default": minifier.DEFAULT_OPTIONS,
               "comments": minifier.parse_options(["comments"]),
               "max": minifier.ALL_OPTIONS,
               "none": frozenset()}
    current = next((k for k, v in presets.items() if v == minify), "pick")
    choice = ui.select("Minification:", [
        ("default", "default  - everything except rename-tables"),
        ("comments", "comments - remove comments only"),
        ("max", "max      - all minification options"),
        ("none", "none     - no minification (the bundled source verbatim)"),
        ("pick", "choose individual minification options..."),
    ], default=current)
    if choice == "pick":
        picked = ui.checkbox("Minify options (space toggles, enter accepts):",
                             [(o, f"{o:<16} {minifier.OPTION_HELP[o]}")
                              for o in minifier.OPTIONS], checked=minify)
        return minifier.parse_options(picked)
    return presets[choice]


def ask_build_settings(ui, minify, name, out):
    """Interactive first build: output name, minification, and the output:
    the .tic alone beside main.lua, or a folder (asked for, default dist/)
    holding the .tic and the .lua bundle. The arguments are
    the defaults (out: None, a folder, or a file -o, which leaves only the
    minification to ask); returns (minify, name, out)."""
    if out is not None and out_kind(out) != "dir":
        return ask_minify(ui, minify), name, out
    while True:
        name = ui.text("cart name:", name, suffix=".tic")
        if name.lower().endswith(".tic"):   # typed the extension anyway
            name = name[:-4]
        name = slug(name)
        if name:
            break
        print("  the name needs at least one letter or digit")
    minify = ask_minify(ui, minify)
    where = ui.select("Output:", [
        ("tic", f"output {name}.tic only"),
        ("dir", f"output all files to a folder - {name}.tic (binary), {name}.lua (source), etc."),
    ], default="tic" if out is None else "dir")
    if where == "tic":
        return minify, name, None
    out = ui.text("Output folder:", out or DEFAULT_DIR) or out or DEFAULT_DIR
    if out_kind(out) != "dir":          # `x.lua` typed as a folder name
        out += "/"
    return minify, name, out


def build_report(report, out):
    """The report a build writes: -r's, else for a folder output
    <name>.bundle.txt in that folder all the same (None: no report file)."""
    return report or (True if out is not None and out_kind(out) == "dir" else None)


def build_command(source, minify, name, default_name, out, report=None, force=False):
    """The `ticpak bundle` command line that repeats an interactive build's
    answers (and -r), leaving out anything that is already the default;
    force: with -f, to rebuild an output that is up to date."""
    parts = ["ticpak", "bundle"] + (["-f"] if force else [])
    if source:
        parts.append(source)
    if minify:
        parts.append(minify_flag(minify))
    if name != default_name and (out is None or out_kind(out) == "dir"):
        parts += ["-n", name]
    if out is not None:
        parts += ["-o", out]
    if report is True:
        parts.append("-r")
    elif report:
        parts.append("--report=" + report)
    return join_command(parts)


def check_command(source, name, default_name, out):
    """The `ticpak check` command line for what build_command builds. A
    check finds DEFAULT_DIR's build by itself, so -o only for another."""
    parts = ["ticpak", "check"]
    if source:
        parts.append(source)
    if name != default_name and (out is None or out_kind(out) == "dir"):
        parts += ["-n", name]
    if out is not None and out != DEFAULT_DIR:
        parts += ["-o", out]
    return join_command(parts)


def join_command(parts):
    return " ".join(f'"{p}"' if any(c.isspace() for c in p) else p for p in parts)


def parse_args(argv):
    """(command or None, argparse namespace, parser) for a command line."""
    ap = argparse.ArgumentParser(
        prog="ticpak",
        usage="%(prog)s [init | bundle | check | run | test | decode | minify] [SOURCE] [options]",
        description="Package a TIC-80 cart for distribution: inline its modules,"
                    " minify, boot-test headless, save the .tic, and check it."
                    " `init [FOLDER]` starts a new project (main.lua and a"
                    " module, game.lua) and stops if there is a main.lua already."
                    " With no command it asks what to do (at a terminal);"
                    " `bundle` (skips an up-to-date package unless --force) and"
                    " `check` run without prompts, for automation. `check FILE...`"
                    " checks the named .tic/.lua files instead of the project's"
                    " package; `run` runs main.lua in TIC-80 as it is; `test`"
                    " runs the package in TIC-80, translating"
                    " its errors back to the sources as they happen; `decode`"
                    " translates one afterwards (from the clipboard, a log,"
                    " or -e); `minify` runs the minifier on its own.",
        epilog=EXAMPLES, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-v", "--version", action="version", version=f"ticpak {__version__}")
    ap.add_argument("sources", nargs="*", metavar="SOURCE",
                    help="the cart (main.lua) or a directory holding it"
                         " (default: ./main.lua, then ./src/main.lua), or a"
                         " module .lua to minify on its own; with `check`,"
                         " files (.tic/.lua) to check directly")
    ap.add_argument("-f", "--force", action="store_true",
                    help="bundle: rebuild even if the package is up to date")
    ap.add_argument("-q", "--quiet", action="store_true",
                    help="bundle, check: print nothing; the exit status says how it"
                         " went (0 OK, 1 failed or a violation, 2 a usage error)."
                         " An error that stops ticpak still prints its line to"
                         " stderr")
    ap.add_argument("-r", "--report", metavar="PATH", nargs="?", const=True,
                    type=report_arg,
                    help="bundle, check: also write the full report (the check in"
                         " full, what minification saved, the summary) to"
                         " <name>.bundle.txt beside the output, or to PATH (a"
                         " file, or a folder to put <name>.bundle.txt in). A"
                         " build to a folder writes it there without -r")
    # --out still works: argparse takes any unambiguous prefix of --output.
    ap.add_argument("-o", "--output", dest="out", metavar="PATH",
                    help="what to write: NAME.tic (just the cart), NAME.lua (just"
                         " the bundle), or a folder (DIR/, or any name without"
                         " those extensions: the .tic, the .lua bundle and the"
                         " full report)."
                         " Default: <name>.tic beside"
                         " main.lua; for a module on its own, <module>.min.lua"
                         " beside it")
    ap.add_argument("-n", "--name",
                    help="output file name, without extension (default: the"
                         " header's saveid, else its title); not with -o FILE,"
                         " which names the file itself")
    ap.add_argument("-m", "--minify", metavar="OPTION,...", type=minify_arg, nargs="?",
                    const=minifier.DEFAULT_OPTIONS, default=None,
                    help="minify the bundle: --minify alone applies the default"
                         " options (every option but rename-tables);"
                         " --minify=max every option; --minify=OPTION,... only"
                         " those (" + ", ".join(minifier.OPTIONS) + "; see the"
                         " documentation below)."
                         " Without it the bundle is not minified")
    ap.add_argument("--verbose", action="store_true",
                    help="show progress, the check's detail and what minification"
                         " saved (with `check`: the full check report), not just"
                         " the summary")
    ap.add_argument("-e", "--error", dest="error_text", metavar="TEXT",
                    help="decode: the error message (and traceback) to translate."
                         " Without it or --log: stdin when redirected, else the"
                         " clipboard, else a paste at the terminal. -o and -n"
                         " pick the cart it came from as they do for check"
                         " (and test); -m gives the options it was built with"
                         " when it has no `-- ticpak:` line, or is not there")
    ap.add_argument("-l", "--log", metavar="FILE",
                    help="decode: translate the last error in FILE, a log of"
                         " TIC-80's output")
    # The command is peeled off by hand: argparse cannot tell an optional
    # subcommand from the optional SOURCE positional.
    command = argv[0] if argv and argv[0] in COMMANDS else None
    args = ap.parse_args(argv[1:] if command else argv)
    if command == "init":
        if (args.force or args.report or args.out or args.name or args.minify
                or args.error_text is not None or args.log or args.verbose):
            ap.error("init takes only a folder (and -q)")
        if len(args.sources) > 1:
            ap.error("init: give one folder")
    if command == "run" and (args.force or args.report or args.quiet or args.out
                             or args.name or args.minify is not None or args.verbose):
        ap.error("run takes only the cart (SOURCE): it runs main.lua as it is")
    if command in ("check", "test", "decode") and args.force:
        ap.error(f"--force applies to bundle, not {command}")
    if command in ("test", "decode") and (args.report or args.quiet):
        ap.error(f"{command}: -r and -q apply to bundle and check")
    if args.error_text is not None and command != "decode":
        ap.error("--error applies to the decode command: ticpak decode -e TEXT")
    if args.log is not None and command != "decode":
        ap.error("--log applies to the decode command: ticpak decode --log FILE")
    if args.log is not None and args.error_text is not None:
        ap.error("decode: give -e TEXT or --log FILE, not both")
    if args.quiet and args.verbose:
        ap.error("--quiet and --verbose: choose one")
    if args.quiet and command is None:
        ap.error("--quiet needs a command (bundle or check): without one, ticpak"
                 " asks questions")
    # `check` given files checks exactly those (a directory, or nothing, means
    # the project's built package); everywhere else SOURCE is one cart.
    args.files = []
    if command == "check" and any(os.path.isfile(s) or s.lower().endswith(".tic")
                                  for s in args.sources):
        args.files = args.sources
        if args.out or args.name or args.minify or args.report:
            ap.error("check FILE...: -o, -n, -m and -r apply to the project's package"
                     " (check FILE... prints each file's full report)")
    elif len(args.sources) > 1:
        ap.error("give one SOURCE: the cart or the directory holding it")
    if args.name and args.out and out_kind(args.out) != "dir":
        ap.error(f"-o {args.out} names the output file itself - drop -n,"
                 " or give -o a folder")
    args.source = args.sources[0] if args.sources and not args.files else None
    # Without -m, build and check don't minify; the interactive question
    # offers the default options as its default. (decode, test: the cart says.)
    args.minify_given = args.minify is not None
    if args.minify is None:
        args.minify = frozenset() if command else minifier.DEFAULT_OPTIONS
    return command, args, ap


def check_files(paths, quiet):
    """`check FILE...`: the checker's report on each .tic / .lua; exits 1 on
    any violation."""
    ok = True
    for path in paths:
        if not os.path.isfile(path):
            sys.exit(f"ticpak: {path} not found")
        check = check_lua if path.lower().endswith(".lua") else check_tic
        ok = check(path, quiet=quiet) and ok
    sys.exit(0 if ok else 1)


def minify_command(argv):
    """`ticpak minify FILE`: the minifier on its own, to stdout. A cart (see
    is_cart) keeps its header and asset sections, and is minified as a whole
    program unless it requires modules; anything else is minified as one
    module, leaving its globals alone."""
    ap = argparse.ArgumentParser(
        prog="ticpak minify", usage="%(prog)s [options] FILE.lua    (writes to stdout)",
        description="Minify one Lua file; with no option given, the default options\n"
                    "apply (every option but --rename-tables; --max adds it).\n\n"
                    "A cart (main.lua, or a file with a metadata header or asset\n"
                    "sections) keeps its header and asset sections. A cart that\n"
                    "requires no modules is the whole program, so anything it doesn't\n"
                    "use is removed; any other file is minified as one module,\n"
                    "leaving its globals alone.",
        epilog="extra does:\n" + "\n".join(f"  {k:<8} {v}" for k, v in
                                           minifier.EXTRA_HELP.items())
               + "\n\nfull documentation:"
                 " https://github.com/dtempx/ticpak/blob/main/docs/minify.md",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", metavar="FILE.lua")
    for o in minifier.OPTIONS:
        ap.add_argument("--" + o, dest="options", action="append_const", const=o,
                        help="further optimisations (listed below)" if o == "extra"
                        else minifier.OPTION_HELP[o])
    ap.add_argument("--max", dest="options", action="append_const", const="max",
                    help="every option, rename-tables included")
    args = ap.parse_args(argv)
    if not os.path.isfile(args.file):
        sys.exit(f"minify: {args.file} not found")
    options = minifier.parse_options(args.options or minifier.DEFAULT_OPTIONS)
    src = open(args.file, encoding="utf-8").read()
    cart = is_cart(args.file)
    header, code, chunks = minifier.split_cart(src, META_KEYS)
    whole = cart and not stub_requires(code)[0]
    try:
        if cart and (header or chunks):     # chunks without a header: refused
            r = minifier.minify_cart_ex(src, mode=options, meta_keys=META_KEYS,
                                        whole_program=whole)
        else:
            r = minifier.minify_ex(src, mode=options, whole_program=whole)
    except (ValueError, minifier.LuaSyntaxError) as e:
        sys.exit(f"minify: {args.file}: {e}")
    # bytes, so a non-ASCII character can't fail on a legacy console encoding
    sys.stdout.buffer.write(r.text.encode("utf-8"))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "minify":    # its own options: ticpak minify --help
        minify_command(argv[1:])
        return
    command, args, ap = parse_args(argv)
    console.VERBOSE = args.verbose
    if args.quiet:                      # nothing on stdout; errors still reach stderr
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    # From here on the console reads like the report file: flush left.
    # (After parse_args, so --help keeps its indented layout.)
    if not isinstance(sys.stdout, FlatStdout):
        sys.stdout = FlatStdout(sys.stdout)
    if command == "init":
        init_project(args.sources[0] if args.sources else None)
        return
    if args.files:
        check_files(args.files, args.quiet)
    if command == "decode":
        decode_command(args)
        return
    if command == "run":
        run_command(args)
        return
    if command == "test":
        test_command(args)
        return
    interactive = command is None
    if interactive and not has_terminal():
        print("ticpak: no terminal to prompt on. For automated runs, give a command:\n"
              "  ticpak bundle     # build if out of date, then check\n"
              "  ticpak bundle -f  # build regardless, then check\n"
              "  ticpak check     # check the existing package\n"
              "Specify --help for more info.")
        sys.exit(2)

    cart = find_cart(args.source)
    if not cart:
        where = f"in {args.source}" if args.source else "at ./main.lua or ./src/main.lua"
        print(f"ticpak: no cart found {where}.\n"
              "Run from the cart's directory, or give its location:"
              " ticpak [bundle | check] path/to/main.lua")
        if interactive:
            init = "ticpak init" + (f" {args.source}" if args.source
                                    and os.path.isdir(args.source) else "")
            print("hint: " + highlight(init) + " to start a new project"
                  + (" here" if init == "ticpak init" else " there"))
        else:
            print("To start a new project here: ticpak init")
        sys.exit(2)
    if not is_cart(cart):
        build_module(command, args, cart, interactive)
        return
    n = len(stub_requires(cart_code(cart))[0])
    print(f"source: {fwd(cart)} ({n} module{'s' if n != 1 else ''})")

    sources_ok = True
    if command == "check":              # reports the header rather than stopping on it
        sources_ok = check_sources(cart)
        meta = parse_header(cart_code(cart))
    else:
        meta = ensure_header(cart, interactive)
    name = slug(args.name) if args.name else package_name(meta)
    if not name and not interactive and (args.out is None or out_kind(args.out) == "dir"):
        sys.exit("ticpak: no usable output name - pass --name, or -o NAME.tic")
    out = args.out
    if out is None and command != "bundle":     # look where it was built: here or dist/
        t = built_target(cart, name or "game", args.report)
        out = DEFAULT_DIR if t.kind == "dir" else None
    else:
        report = build_report(args.report, out) if command == "bundle" else args.report
        t = Target(cart, name or "game", out, report)
    guard_sources(t)

    fresh, rerun, last = False, None, None
    if os.path.isfile(t.output):
        fresh, status = freshness(t)
        print(status)
        last = built_options(t.output)
    else:
        print(f"cart: {fwd(t.output)} (not built yet)")

    if interactive:
        if os.path.isfile(t.output):    # rebuild it as it was built
            force_hint(build_command(args.source, last, t.name, package_name(meta), out,
                                     force=True),
                       check_command(args.source, t.name, package_name(meta), out))
            return
        print("hint: answer the questions below to build it (Ctrl+C to cancel)")
        args.minify, name, out = ask_build_settings(Prompts(), args.minify, t.name, out)
        t = Target(cart, name, out, build_report(args.report, out))
        guard_sources(t)
        command, args.force = "bundle", True
        rerun = build_command(args.source, args.minify, name, package_name(meta), out,
                              args.report)

    if command == "check":
        if not os.path.isfile(t.output):
            build_hint(args, t, package_name(meta))
            sys.exit(1)
        try:                            # the hint after violations (exit 1) too
            if t.tic:
                check_summary(t, unminified_size(t), full=True)
            else:                       # a lone bundle: the text-cart check
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    ok = check_lua(t.lua)
                print(buf.getvalue(), end="")
                write_report(t, buf.getvalue())
                sys.exit(0 if ok and sources_ok else 1)
        finally:
            report_hint(t)
        if not sources_ok:
            sys.exit(1)
        return
    if not rerun:
        options_note(last, args.minify, fresh and not args.force)
    if fresh and not args.force:
        # -r: the report of the .tic already built. A folder's report is one
        # of its outputs, so it exists and holds the savings: leave it be.
        if t.tic and t.txt and t.kind != "dir":
            check_summary(t, unminified_size(t))
        elif t.tic:
            print("\n".join(size_summary(t.tic, unminified_size(t), colour=True)))
        force_hint(build_command(args.source, args.minify, t.name, package_name(meta),
                                 args.out, args.report, force=True),
                   check_command(args.source, t.name, package_name(meta), args.out))
        return
    # Just the .lua: boot it and check a .tic made from it all the same in
    # tmp, then drop the .tic.
    tmp = None if t.tic else tempfile.mkdtemp(prefix="ticpak-check-")
    try:
        with Progress(build_plan(args.minify)):
            unminified = bundle(t, minify_options=args.minify)
            tic = verify(t, tmp and os.path.join(tmp, "check.tic"))
            if tmp:
                save_bundle(t)
        check_summary(t, unminified, tic=tic)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
        # Also after a failed boot or a limit violation: the fix is usually
        # in the code, and the rebuild wants the same settings.
        if rerun:
            rerun_hint(rerun)


def package_target(args, command):
    """The Target for the package `test` and `decode` read: -o's, else the one
    built (beside the cart, or in dist/)."""
    cart = find_cart(args.source)
    if not cart or not is_cart(cart):
        sys.exit(f"ticpak: {command} needs the cart (main.lua) the package was built"
                 " from: run from its directory, or give its location")
    name = slug(args.name) if args.name else package_name(parse_header(cart_code(cart)))
    return (Target(cart, name or "game", args.out) if args.out
            else built_target(cart, name or "game"))


def raw_write(text):
    """Text as TIC-80 wrote it, indents and all: not through the flush-left
    console, and never failing on a character the console can't show."""
    sys.stdout.flush()
    raw = getattr(sys.stdout, "inner", sys.stdout)
    try:
        raw.write(text)
    except UnicodeEncodeError:
        enc = getattr(raw, "encoding", None) or "ascii"
        raw.write(text.encode(enc, errors="replace").decode(enc))
    raw.flush()


def error_input(args):
    """(The error text, where it came from or None, from a log) for `ticpak
    error`: -e; --log FILE; stdin when redirected; the clipboard when it
    holds a location in a cart; else a paste at the terminal. Text that may
    have been copied from TIC-80's console is unwrapped."""
    if args.error_text is not None:
        return errors.unwrap(args.error_text), None, False
    if args.log is not None:
        try:
            with open(args.log, encoding="utf-8", errors="replace") as f:
                return f.read(), f"the last error in {fwd(args.log)}", True
        except OSError as e:
            sys.exit(f"ticpak: can't read {args.log}: {e.strerror or e}")
    tty = sys.stdin is not None and sys.stdin.isatty()
    if sys.stdin is not None and not tty:
        text = sys.stdin.read()
        if text.strip():
            return errors.unwrap(text), None, False
    clip = errors.clipboard_text()
    if clip and errors.LOC_RE.search(errors.unwrap(clip)):
        return errors.unwrap(clip), "the clipboard", False
    if not tty:
        sys.exit("ticpak: no error to translate: the clipboard holds none - copy it"
                 " from TIC-80's console (select it with the mouse, Ctrl+C), or give"
                 " -e TEXT or --log FILE")
    eof = "Ctrl+Z then Enter" if os.name == "nt" else "Ctrl+D"
    print(f"the clipboard holds no error from a cart: paste the error message and"
          f" its traceback, then {eof}:", file=sys.stderr)
    return errors.unwrap(sys.stdin.read()), None, False


def decode_command(args):
    """`ticpak decode`: the error text (see error_input) with each location in
    the packaged cart and each short name translated back to the sources,
    then the error's source line. Exits 1 when the text holds no location in
    the cart."""
    t = package_target(args, "decode")
    text, origin, log = error_input(args)
    if not errors.LOC_RE.search(text):
        sys.exit(f"ticpak: no location in the cart found in {origin or 'the error text'}"
                 ' - TIC-80 writes one as [string "-- title: ..."]:37:')
    if origin:
        print(f"error: {origin}")
    dec, notes = errors.find_map(t, args.minify if args.minify_given else None)
    for note in notes:
        print(note)
    if log:
        text = errors.last_error(text, dec.ours) or text
    out, first, missing = errors.decode(text, dec)
    out = out.rstrip("\n") + errors.source_note(t.cart_dir, first)
    raw_write("\n" + out.rstrip("\n") + "\n")
    if missing:
        print(f"  WARN  line{'s' if len(missing) > 1 else ''}"
              f" {', '.join(map(str, missing))} not in the cart - is the error from"
              " another build?")


def run_command(args):
    """`ticpak run`: the cart's sources (main.lua, its modules loaded from
    their files) in TIC-80's window until it is closed, from the cart's
    folder, where `require` finds them. Its output passes through as it is:
    errors already name the sources. Exits with TIC-80's status."""
    cart = find_cart(args.source)
    if not cart or not is_cart(cart):
        sys.exit("ticpak: run needs the cart (main.lua): run from its directory,"
                 " or give its location")

    class Passthrough:
        feed = staticmethod(raw_write)

        def idle(self):
            pass

        def close(self):
            pass
    print(f"running {fwd(cart)} in TIC-80 (close it, or Ctrl+C here, to stop)")
    sys.exit(play(cart, Passthrough(), cwd=os.path.dirname(os.path.abspath(cart))))


def test_command(args):
    """`ticpak test`: the package in TIC-80's window until it is closed, all
    it prints passed through, each error in the cart translated back to the
    sources as it happens (errors.Stream). Exits with TIC-80's status."""
    t = package_target(args, "test")
    if not os.path.isfile(t.output):
        print(f"cart: {fwd(t.output)} (not built yet)")
        build_hint(args, t, package_name(parse_header(cart_code(t.cart))))
        sys.exit(1)
    fresh, status = freshness(t)
    print(status)
    if not fresh:
        print("note: running the cart as built; ticpak bundle rebuilds it")

    def decoder():
        try:
            dec, notes = errors.find_map(t, args.minify if args.minify_given else None)
        except SystemExit as e:         # no `-- ticpak:` line: the error as it is
            raw_write(f"ticpak: can't translate errors - {str(e.code).split(': ', 1)[-1]}\n")
            return None
        for note in notes:
            if "WARN" in note:
                raw_write(note.strip() + "\n")
        return dec
    print(f"running {fwd(t.output)} in TIC-80 (close it, or Ctrl+C here, to stop);"
          " errors are translated to the sources")
    sys.exit(play(t.output, errors.Stream(decoder, t.cart_dir, raw_write)))


def build_plan(minify):
    """The progress bar's steps for a build, with rough seconds for each
    (bundle() puts a figure on minify once it knows the code's size)."""
    return ([("inline", 0.05)] + ([("minify", 1.0)] if minify else [])
            + [("boot", BOOT_SECONDS), ("save", 1.0)])


def force_hint(command, check=None):
    """The command that rebuilds an up-to-date output, and for a cart the
    one that checks it (check), highlighted."""
    print("hint: " + highlight(command) + " to force rebuild")
    if check:
        print("hint: " + highlight(check) + " to check bundle info")


def build_hint(args, t, default_name):
    """The command that builds a package not built yet (check, test),
    highlighted."""
    command = build_command(args.source, minifier.DEFAULT_OPTIONS, t.name, default_name,
                            args.out)
    print("hint: " + highlight(command) + " to build")


def report_hint(t):
    """After a check that wrote no report: point at the one a build left
    beside the output (<name>.bundle.txt), if there is one."""
    path = os.path.join(t.dist_dir, t.name + ".bundle.txt")
    if t.txt is None and os.path.isfile(path):
        print("hint: see " + highlight(fwd(path)) + " for more info")


def options_note(last, minify, skipped):
    """A `ticpak bundle` whose -m differs from the one the existing output was
    built with (last; None: unknown) says so: it rebuilds with the options
    asked for, or (skipped, up to date) did not rebuild at all."""
    if last is None or last == minify:
        return
    print(f"note: {'it was built with' if skipped else 'the last build used'}"
          f" {options_label(last)}; this command asks for {options_label(minify)}")


def rerun_hint(rerun):
    """The command that repeats an interactive build, highlighted."""
    print("hint: " + highlight(rerun) + " to build with these settings again")


def guard_sources(t):
    """Stop before an output would overwrite the cart or one of its modules."""
    outputs = {os.path.normcase(p) for p in (t.lua, t.tic, t.txt) if p}
    names = stub_requires(cart_code(t.cart))[0] if t.kind != "module" else []
    for src in [t.cart] + [t.module_path(n) for n in names]:
        if os.path.normcase(os.path.abspath(src)) in outputs:
            sys.exit(f"ticpak: the output would overwrite {show(src)} - choose"
                     " another -o")


def build_module(command, args, path, interactive):
    """A .lua with no metadata header or asset sections is a module on its
    own: minified as a fragment (globals left alone) to <module>.min.lua
    beside it, or to -o's .lua or folder. No .tic: it is not a cart."""
    print(f"source: {fwd(path)} (a module on its own: no metadata header)")
    if command == "check":
        sys.exit(f"ticpak: {show(path)} is a module, not a cart: there is"
                 " no package to check (ticpak check FILE checks a file itself)")
    if args.out and out_kind(args.out) == "tic":
        sys.exit(f"ticpak: {show(path)} is a module, not a cart, so it can't be"
                 " saved as a .tic - give -o NAME.lua or a folder")
    default_name = os.path.splitext(os.path.basename(path))[0] + ".min"
    name = slug(args.name) if args.name else default_name
    if args.out and out_kind(args.out) == "lua":
        lua = args.out
    else:
        lua = os.path.join(args.out or os.path.dirname(path), name + ".lua")
    t = Target(path, name, lua, build_report(args.report, args.out))
    t.kind = "module"
    guard_sources(t)

    fresh, rerun, last = False, None, None
    if os.path.isfile(t.lua):
        fresh, status = freshness(t, module=True)
        print(status)
        last = built_options(t.lua)
    else:
        print(f"output: {fwd(t.lua)} (not built yet)")
    if interactive:
        if os.path.isfile(t.lua):       # rebuild it as it was built
            force_hint(build_command(args.source, last, name, default_name, args.out,
                                     force=True))
            return
        print("hint: answer the question below to build it (Ctrl+C to cancel)")
        args.minify = ask_minify(Prompts(), args.minify)
        args.force = True
        rerun = build_command(args.source, args.minify, name, default_name, args.out,
                              args.report)
    else:
        options_note(last, args.minify, fresh and not args.force)
    if fresh and not args.force:
        force_hint(build_command(args.source, args.minify, name, default_name, args.out,
                                 args.report, force=True))
        return
    with Progress([("minify", 1.0)]):
        before, after = minify_module(t, args.minify)
    saved = []
    if t.savings is not None:
        groups, sv, options = t.savings
        saved = savings_table(groups, options) + made_of_lines(sv)
    for line in saved:
        console.detail(line)
    summary = [f"size: {kb(after)}",
               f"original code size: {kb(before)} ({100 * (1 - after / before):.0f}% reduction)"
               if args.minify and before else "not minified"]
    print("\n".join(summary))
    write_report(t, "".join(line + "\n" for line in [f"source: {fwd(path)}"] + saved
                            + summary))
    if rerun:
        rerun_hint(rerun)


if __name__ == "__main__":
    main()
