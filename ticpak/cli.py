#!/usr/bin/env python3
"""TIC-80 distribution packager: bundle, minify, verify, export.

Inlines the modules a TIC-80 cart's entry stub requires into one text cart,
optionally minifies it, boots it headless, saves the .tic and checks it. Full
documentation: README.md. This file is the console front end - the command
line, the interactive questions, and the dispatch to the modules that do the
work:

  bundle.py   find the cart, the outputs (-o), inline its modules, minify,
              write <name>.lua
  run.py      find TIC-80, boot the bundle headless, save <name>.tic
  report.py   check the .tic (check.py), the summary, the -r report file
  header.py   the metadata header: output name, missing tags, filling in
  console.py  --verbose, the flush-left console, the prompts
  minify.py   the minifier;  check.py  the .tic checker
"""
import argparse
import contextlib
import io
import os
import shutil
import sys
import tempfile

from . import __version__, console
from . import minify as minifier
from .bundle import (DEFAULT_DIR, Target, built_target, bundle, find_cart, freshness,
                     is_cart, minify_module, out_kind, save_bundle, stub_requires,
                     unminified_size)
from .check import check_lua, check_tic
from .console import FlatStdout, Prompts, fwd, has_terminal, highlight, show
from .header import cart_code, ensure_header, package_name, slug
from .report import (check_summary, kb, made_of_lines, savings_table, size_summary,
                     write_report)
from .run import verify

EXAMPLES = """examples (run from the port's directory, the one holding main.lua):
  ticpak                          interactive: status, or asks to build
  ticpak bundle                    build + check if out of date: <name>.tic beside main.lua
  ticpak bundle -f                 build + check regardless (--force)
  ticpak bundle --verbose          ...showing progress, the check's detail, minify savings
  ticpak check                    check the existing .tic: summary only
  ticpak check --verbose          ...and the full check report
  ticpak bundle -f -m              every minify option (smallest cart)
  ticpak bundle -f -m=comments,whitespace   just those minify options
  ticpak bundle path/to/main.lua   a cart elsewhere
  ticpak bundle -n mygame          override the output name: mygame.tic
  ticpak bundle -o mygame.tic      just this .tic
  ticpak bundle -o mygame.lua      just the bundle (still boot-tested and checked)
  ticpak bundle -o dist/           dist/<name>.tic and .lua (the bundle)
  ticpak bundle -f -r              also the full report: <name>.ticpak.txt beside the .tic
  ticpak bundle -f --report=r.txt  the full report to r.txt instead
  ticpak bundle -q                 no output: just the exit status
  ticpak bundle enemies.lua -m     one module on its own -> enemies.min.lua
  ticpak check main.lua dist/x.tic   check exactly these files: full report
  ticpak minify enemies.lua       the minifier on its own (ticpak minify --help)

full documentation: https://github.com/dtempx/ticpak#readme
"""

COMMANDS = ("bundle", "check")       # `minify` is dispatched before argparse


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
    """Minification: all options, comments only, none, or the individual
    options as checkboxes. minify is the default; returns the chosen options."""
    presets = {"all": minifier.ALL_OPTIONS,
               "comments": minifier.parse_options(["comments"]),
               "none": frozenset()}
    current = next((k for k, v in presets.items() if v == minify), "pick")
    choice = ui.select("Minification:", [
        ("all", "all      - all minification options (smallest cart)"),
        ("comments", "comments - remove comments only"),
        ("none", "none     - no minification (the bundled source verbatim)"),
        ("pick", "choose individual minification options..."),
    ], default=current)
    if choice == "pick":
        picked = ui.checkbox("Minify options (space toggles, enter accepts):",
                             [(o, f"{o:<11} {minifier.OPTION_HELP[o]}")
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
        name = ui.text("Cart name:", name, suffix=".tic")
        if name.lower().endswith(".tic"):   # typed the extension anyway
            name = name[:-4]
        name = slug(name)
        if name:
            break
        print("  the name needs at least one letter or digit")
    minify = ask_minify(ui, minify)
    where = ui.select("Output:", [
        ("tic", f"{name}.tic - output .tic binary only"),
        ("dir", f"output all files to a folder - {name}.tic (binary), {name}.lua (the equivalent source text), etc."),
    ], default="tic" if out is None else "dir")
    if where == "tic":
        return minify, name, None
    out = ui.text("Output folder:", out or DEFAULT_DIR) or out or DEFAULT_DIR
    if out_kind(out) != "dir":          # `x.lua` typed as a folder name
        out += "/"
    return minify, name, out


def build_report(report, out):
    """The report a build writes: -r's, else for a folder output
    <name>.ticpak.txt in that folder all the same (None: no report file)."""
    return report or (True if out is not None and out_kind(out) == "dir" else None)


def build_command(source, minify, name, default_name, out, report=None):
    """The `ticpak bundle` command line that repeats an interactive build's
    answers (and -r), leaving out anything that is already the default."""
    parts = ["ticpak", "bundle"]
    if source:
        parts.append(source)
    if minify == minifier.ALL_OPTIONS:
        parts.append("-m")
    elif minify:
        parts.append("-m=" + ",".join(o for o in minifier.OPTIONS if o in minify))
    if name != default_name and (out is None or out_kind(out) == "dir"):
        parts += ["-n", name]
    if out is not None:
        parts += ["-o", out]
    if report is True:
        parts.append("-r")
    elif report:
        parts.append("--report=" + report)
    return " ".join(f'"{p}"' if any(c.isspace() for c in p) else p for p in parts)


def parse_args(argv):
    """(command or None, argparse namespace, parser) for a command line."""
    ap = argparse.ArgumentParser(
        prog="ticpak",
        usage="%(prog)s [bundle | check | minify] [SOURCE] [options]",
        description="Package a TIC-80 cart for distribution: inline its modules,"
                    " minify, boot-test headless, save the .tic, and check it."
                    " With no command it asks what to do (at a terminal);"
                    " `bundle` (skips an up-to-date package unless --force) and"
                    " `check` run without prompts, for automation. `check FILE...`"
                    " checks the named .tic/.lua files instead of the project's"
                    " package; `minify` runs the minifier on its own.",
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
                         " <name>.ticpak.txt beside the output, or to PATH (a"
                         " file, or a folder to put <name>.ticpak.txt in). A"
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
                    const=minifier.ALL_OPTIONS, default=None,
                    help="minify the bundle: --minify alone applies every"
                         " option; --minify=OPTION,... only those ("
                         + ", ".join(minifier.OPTIONS) + "; see the documentation"
                         " below)."
                         " Without it the bundle is not minified")
    ap.add_argument("--verbose", action="store_true",
                    help="show progress, the check's detail and what minification"
                         " saved (with `check`: the full check report), not just"
                         " the summary")
    # The command is peeled off by hand: argparse cannot tell an optional
    # subcommand from the optional SOURCE positional.
    command = argv[0] if argv and argv[0] in COMMANDS else None
    args = ap.parse_args(argv[1:] if command else argv)
    if command == "check" and args.force:
        ap.error("--force applies to bundle, not check")
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
    # offers every option as its default.
    if args.minify is None:
        args.minify = frozenset() if command else minifier.ALL_OPTIONS
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
    if args.quiet:                      # nothing on stdout; errors still reach stderr
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    # From here on the console reads like the report file: flush left.
    # (After parse_args, so --help keeps its indented layout.)
    if not isinstance(sys.stdout, FlatStdout):
        sys.stdout = FlatStdout(sys.stdout)
    if args.files:
        check_files(args.files, args.quiet)
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
              " ticpak [bundle | check] path/to/main.lua\n"
              "Specify --help for more info.")
        sys.exit(2)
    if not is_cart(cart):
        build_module(command, args, cart, interactive)
        return
    n = len(stub_requires(cart_code(cart))[0])
    print(f"source: {fwd(cart)} ({n} module{'s' if n != 1 else ''})")

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

    fresh, rerun = False, None
    if os.path.isfile(t.output):
        fresh, status = freshness(t)
        print(status)
    else:
        print(f"cart: {fwd(t.output)} (not built yet)")

    if interactive:
        if os.path.isfile(t.output):
            print("hint: ticpak bundle -f" + (f" -o {out}" if out else "")
                  + " to force rebuild")
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
            sys.exit(f"ticpak: {show(t.output)} not found - build it first:"
                     " ticpak bundle" + (f" -o {args.out}" if args.out else ""))
        if t.tic:
            check_summary(t, unminified_size(t), full=True)
        else:                           # a lone bundle: the text-cart check
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                ok = check_lua(t.lua)
            print(buf.getvalue(), end="")
            write_report(t, buf.getvalue())
            sys.exit(0 if ok else 1)
        return
    if fresh and not args.force:
        # -r: the report of the .tic already built. A folder's report is one
        # of its outputs, so it exists and holds the savings: leave it be.
        if t.tic and t.txt and t.kind != "dir":
            check_summary(t, unminified_size(t))
        elif t.tic:
            print("\n".join(size_summary(t.tic, unminified_size(t))))
        print("hint: ticpak bundle -f to force rebuild")
        return
    try:
        unminified = bundle(t, minify_options=args.minify)
        if t.tic:
            verify(t)
            check_summary(t, unminified)
        else:
            # Just the .lua: boot it and check a .tic made from it all the
            # same, then drop the .tic.
            tmp = tempfile.mkdtemp(prefix="ticpak-check-")
            try:
                tic = verify(t, os.path.join(tmp, "check.tic"))
                save_bundle(t)
                check_summary(t, unminified, tic=tic)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
    finally:
        # Also after a failed boot or a limit violation: the fix is usually
        # in the code, and the rebuild wants the same settings.
        if rerun:
            rerun_hint(rerun)


def rerun_hint(rerun):
    """The command that repeats an interactive build, highlighted on its own line."""
    print("hint: use the following command to build with these settings again")
    print(highlight(rerun))


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

    fresh, rerun = False, None
    if os.path.isfile(t.lua):
        fresh, status = freshness(t, module=True)
        print(status)
    else:
        print(f"output: {fwd(t.lua)} (not built yet)")
    if interactive:
        if os.path.isfile(t.lua):
            print("hint: ticpak bundle -f to force rebuild")
            return
        print("hint: answer the question below to build it (Ctrl+C to cancel)")
        args.minify = ask_minify(Prompts(), args.minify)
        args.force = True
        rerun = build_command(args.source, args.minify, name, default_name, args.out,
                              args.report)
    if fresh and not args.force:
        print("hint: ticpak bundle -f to force rebuild")
        return
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
