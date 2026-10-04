#!/usr/bin/env python3
"""TIC-80 distribution packager: bundle, minify, verify, export.

Inlines the modules a TIC-80 cart's entry stub requires into one text cart,
optionally minifies it, boots it headless, saves the .tic and checks it. Full
documentation: README.md. This file is the console front end - the command
line, the interactive questions, and the dispatch to the modules that do the
work:

  bundle.py   find the cart, inline its modules, minify, write <name>.lua
  run.py      find TIC-80, boot the bundle headless, save <name>.tic
  report.py   check the .tic (check.py), write <name>.txt, the summary
  header.py   the metadata header: output name, missing tags, filling in
  console.py  -v, the flush-left console, the prompts
  minify.py   the minifier;  check.py  the .tic checker
"""
import argparse
import os
import sys

from . import __version__, console
from . import minify as minifier
from .bundle import (Target, bundle, find_cart, freshness, stub_requires,
                     unminified_size)
from .check import check_lua, check_tic
from .console import FlatStdout, Prompts, fwd, has_terminal, show
from .header import cart_code, ensure_header, package_name, slug
from .report import check_summary, size_summary
from .run import verify

EXAMPLES = """examples (run from the port's directory, the one holding main.lua):
  ticpak                          interactive: status, or asks to build
  ticpak build                    build + check if out of date
  ticpak build -f                 build + check regardless (--force)
  ticpak build -v                 ...showing progress and the check's detail
  ticpak check                    check the existing .tic: summary only
  ticpak check -v                 ...and the full check report
  ticpak build -f -m              every minify option (smallest cart)
  ticpak build -f -m=comments,whitespace   just those minify options
  ticpak build path/to/main.lua   a cart elsewhere
  ticpak build -n mygame          override the output name
  ticpak build -o out             write to out/ instead of dist/
  ticpak check main.lua dist/x.tic   check exactly these files: full report
  ticpak minify enemies.lua       the minifier on its own (ticpak minify --help)

full documentation: README.md
"""

COMMANDS = ("build", "check")       # `minify` is dispatched before argparse


def minify_arg(text):
    """--minify=OPTION,... / -m OPTION,...: option names only (no presets).
    argparse hands `-m=a,b` over as "=a,b", so a leading = is dropped."""
    text = text[1:] if text.startswith("=") else text
    items = [i.strip() for i in text.split(",") if i.strip()]
    bad = [i for i in items if i not in minifier.OPTIONS]
    if bad and (os.path.sep in text or "/" in text or text.endswith(".lua")
                or os.path.exists(text)):
        raise argparse.ArgumentTypeError(
            f"{text!r} looks like a path, not minify options - put SOURCE before"
            " --minify, or write --minify=OPTION,...")
    if bad or not items:
        raise argparse.ArgumentTypeError(
            f"unknown minify option {', '.join(map(repr, bad)) or repr(text)}"
            f" (expected one or more of {', '.join(minifier.OPTIONS)};"
            " --minify alone means all of them)")
    return minifier.parse_options(items)


def ask_build_settings(ui, minify, name, out_dir):
    """Interactive first build: output name, minification (all options,
    none, or the individual options as checkboxes), output folder. The
    arguments are the defaults; returns (minify, name, out_dir)."""
    while True:
        name = slug(ui.text("Output name (no extension):", name))
        if name:
            break
        print("  the name needs at least one letter or digit")

    presets = {"all": minifier.ALL_OPTIONS, "none": frozenset()}
    current = next((k for k, v in presets.items() if v == minify), "pick")
    choice = ui.select("Minification:", [
        ("all", "all  - every option (smallest cart)"),
        ("none", "none - no minification (the inlined source verbatim)"),
        ("pick", "choose individual options..."),
    ], default=current)
    if choice == "pick":
        picked = ui.checkbox("Minify options (space toggles, enter accepts):",
                             [(o, f"{o:<11} {minifier.OPTION_HELP[o]}")
                              for o in minifier.OPTIONS], checked=minify)
        minify = minifier.parse_options(picked)
    else:
        minify = presets[choice]

    out_dir = ui.text("Output folder:", out_dir) or out_dir
    return minify, name, out_dir


def parse_args(argv):
    """(command or None, argparse namespace, parser) for a command line."""
    ap = argparse.ArgumentParser(
        prog="ticpak",
        usage="%(prog)s [build | check | minify] [SOURCE] [options]",
        description="Package a TIC-80 cart for distribution: inline its modules,"
                    " minify, boot-test headless, save the .tic, and check it."
                    " With no command it asks what to do (at a terminal);"
                    " `build` (skips an up-to-date package unless --force) and"
                    " `check` run without prompts, for automation. `check FILE...`"
                    " checks the named .tic/.lua files instead of the project's"
                    " package; `minify` runs the minifier on its own.",
        epilog=EXAMPLES, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"ticpak {__version__}")
    ap.add_argument("sources", nargs="*", metavar="SOURCE",
                    help="the cart (main.lua) or a directory holding it"
                         " (default: ./main.lua, then ./src/main.lua); with"
                         " `check`, files (.tic/.lua) to check directly")
    ap.add_argument("-f", "--force", action="store_true",
                    help="build: rebuild even if the package is up to date")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="show progress and the check's detail (with `check`:"
                         " the full check report), not just the summary")
    ap.add_argument("-q", "--quiet", action="store_true",
                    help="check FILE...: print only violations (exit code 0/1)")
    ap.add_argument("-o", "--out", metavar="DIR",
                    help="output directory (default: ./dist)")
    ap.add_argument("-n", "--name",
                    help="output file name, without extension (default: the"
                         " header's saveid, else its title)")
    ap.add_argument("-m", "--minify", metavar="OPTION,...", type=minify_arg, nargs="?",
                    const=minifier.ALL_OPTIONS, default=frozenset(),
                    help="minify the bundle: --minify alone applies every"
                         " option; --minify=OPTION,... only those ("
                         + ", ".join(minifier.OPTIONS) + "; see README.md)."
                         " Without it the bundle is not minified")
    # The command is peeled off by hand: argparse cannot tell an optional
    # subcommand from the optional SOURCE positional.
    command = argv[0] if argv and argv[0] in COMMANDS else None
    args = ap.parse_args(argv[1:] if command else argv)
    if command == "check" and args.force:
        ap.error("--force applies to build, not check")
    # `check` given files checks exactly those (a directory, or nothing, means
    # the project's built package); everywhere else SOURCE is one cart.
    args.files = []
    if command == "check" and any(os.path.isfile(s) or s.lower().endswith(".tic")
                                  for s in args.sources):
        args.files = args.sources
        if args.out or args.name or args.minify:
            ap.error("check FILE...: -o, -n and -m apply to the project's package")
    elif len(args.sources) > 1:
        ap.error("give one SOURCE: the cart or the directory holding it")
    elif args.quiet:
        ap.error("--quiet applies to check FILE...")
    args.source = args.sources[0] if args.sources and not args.files else None
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


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "minify":    # its own options: ticpak minify --help
        minifier.main(argv[1:])
        return
    command, args, ap = parse_args(argv)
    console.VERBOSE = args.verbose
    # From here on the console reads like the <name>.txt report: flush left.
    # (After parse_args, so --help keeps its indented layout.)
    if not isinstance(sys.stdout, FlatStdout):
        sys.stdout = FlatStdout(sys.stdout)
    if args.files:
        check_files(args.files, args.quiet)
    interactive = command is None
    if interactive and not has_terminal():
        print("ticpak: no terminal to prompt on. For automated runs, give a command:\n"
              "  ticpak build     # build if out of date, then check\n"
              "  ticpak build -f  # build regardless, then check\n"
              "  ticpak check     # check the existing package\n"
              "Specify --help for more info.")
        sys.exit(2)

    cart = find_cart(args.source)
    if not cart:
        where = f"in {args.source}" if args.source else "at ./main.lua or ./src/main.lua"
        print(f"ticpak: no cart found {where}.\n"
              "Run from the cart's directory, or give its location:"
              " ticpak [build | check] path/to/main.lua\n"
              "Specify --help for more info.")
        sys.exit(2)
    n = len(stub_requires(cart_code(cart))[0])
    print(f"source: {fwd(cart)} ({n} module{'s' if n != 1 else ''})")

    meta = ensure_header(cart, interactive)
    name = slug(args.name) if args.name else package_name(meta)
    if not name and not interactive:
        sys.exit("ticpak: no usable output name - pass --name")
    out_dir = args.out or "dist"
    t = Target(cart, name or "game", out_dir)

    fresh = False
    if os.path.isfile(t.tic):
        fresh, status = freshness(t)
        print(status)
    else:
        print(f"cart: {fwd(t.tic)} (not built yet)")

    if interactive:
        if os.path.isfile(t.tic):
            print("hint: ticpak build -f to force rebuild")
            return
        print("hint: answer the questions below to build it (Ctrl+C to cancel)")
        args.minify, name, out_dir = ask_build_settings(
            Prompts(), args.minify, t.name, out_dir)
        t = Target(cart, name, out_dir)
        command, args.force = "build", True

    if command == "check":
        if not os.path.isfile(t.tic):
            sys.exit(f"ticpak: {show(t.tic)} not found - build it first:"
                     " ticpak build")
        check_summary(t, unminified_size(t), full=True)
        return
    if fresh and not args.force:
        print("\n".join(size_summary(t.tic, unminified_size(t))))
        print("hint: ticpak build -f to force rebuild")
        return
    unminified = bundle(t, minify_options=args.minify)
    verify(t)
    check_summary(t, unminified)


if __name__ == "__main__":
    main()
