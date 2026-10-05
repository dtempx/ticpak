#!/usr/bin/env python3
"""Console helpers for ticpak: message paths, the --verbose switch, the
flush-left output filter, and the interactive prompts.
"""
import os
import re
import sys

VERBOSE = False       # --verbose: progress and the check's detail on screen


def detail(*args, **kw):
    """print() only with --verbose."""
    if VERBOSE:
        print(*args, **kw)


def show(path):
    """path for messages: relative under the current directory, else absolute."""
    rel = os.path.relpath(path)
    return path if rel.startswith("..") else rel


def fwd(path):
    """show(path) with forward slashes, for the status lines."""
    return show(path).replace(os.sep, "/")


LABEL_PAD_RE = re.compile(r"^(\w+):\s{2,}")


def flat_line(line):
    """A console/report line flush left, one space after a `label:`
    (`check:  banks` -> `check: banks`, `title:   X` -> `title: X`). Spacing
    later in the line - table columns - is kept."""
    return LABEL_PAD_RE.sub(r"\1: ", line.strip())


class FlatStdout:
    """sys.stdout filter that passes every whole line through flat_line(), so
    the console reads like the <name>.txt report (the checker's output included)."""

    def __init__(self, inner):
        self.inner, self.buf = inner, ""

    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            self.inner.write(flat_line(line) + "\n")
        return len(s)

    def flush(self):
        if self.buf:
            self.inner.write(flat_line(self.buf))
            self.buf = ""
        self.inner.flush()

    def __getattr__(self, name):        # encoding, isatty, fileno, ...
        return getattr(self.inner, name)


def highlight(text):
    """text in bright cyan when stdout is a terminal that shows colour (not
    with NO_COLOR set, or when piped or redirected); else text as is."""
    if os.environ.get("NO_COLOR") or not getattr(sys.stdout, "isatty", lambda: False)():
        return text
    if os.name == "nt":                 # turn on the console's ANSI escapes
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            handle, mode = k32.GetStdHandle(-11), ctypes.c_uint()
            if not k32.GetConsoleMode(handle, ctypes.byref(mode)):
                return text
            if not mode.value & 4 and not k32.SetConsoleMode(handle, mode.value | 4):
                return text
        except Exception:
            return text
    return f"\033[96m{text}\033[0m"


def has_terminal():
    """Is someone at a terminal to answer prompts? (Windows) isatty() is also
    true for NUL, so require a real console there."""
    if not sys.stdin.isatty():
        return False
    if os.name != "nt":
        return True
    import ctypes
    import msvcrt
    mode = ctypes.c_uint()
    handle = msvcrt.get_osfhandle(sys.stdin.fileno())
    return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)))


class Prompts:
    """Console prompts: questionary's when it is installed and the terminal
    supports it (Git Bash's mintty does not), else plain input()."""

    def __init__(self):
        try:
            import questionary
            self.q = questionary
        except Exception:
            self.q = None
            print("(tip: `pip install questionary` for nicer prompts)")

    def _ask(self, fancy, plain):
        """Prompts write to the real stdout: FlatStdout would strip the
        menus' alignment (and a prompt has no newline to flush on)."""
        flat = sys.stdout if isinstance(sys.stdout, FlatStdout) else None
        if flat:
            flat.flush()
            sys.stdout = flat.inner
        try:
            return self._ask_raw(fancy, plain)
        finally:
            if flat:
                sys.stdout = flat

    def _ask_raw(self, fancy, plain):
        if self.q is not None:
            try:
                answer = fancy()
            except KeyboardInterrupt:
                answer = None
            except Exception:           # no usable console: fall back for good
                self.q = None
                return self._ask_raw(fancy, plain)
            if answer is None:          # questionary's answer to Ctrl-C
                sys.exit("\nticpak: cancelled")
            return answer
        try:
            return plain()
        except (KeyboardInterrupt, EOFError):
            sys.exit("\nticpak: cancelled")

    def confirm(self, message, default=True):
        def plain():
            hint = "Y/n" if default else "y/N"
            while True:
                a = input(f"? {message} ({hint}) ").strip().lower()
                if not a:
                    return default
                if a in ("y", "yes", "n", "no"):
                    return a.startswith("y")
        return self._ask(lambda: self.q.confirm(message, default=default).ask(), plain)

    def text(self, message, default="", suffix=""):
        """suffix: fixed text shown after the answer as it is typed (e.g.
        ".tic"); not part of the answer. Plain prompts show it in the label."""
        def fancy():
            kw = {}
            if suffix:
                from prompt_toolkit.layout.processors import AfterInput
                kw["input_processors"] = [AfterInput(suffix, style="class:instruction")]
            return self.q.text(message, default=default, **kw).ask()

        def plain():
            label = f"{message.rstrip(':')} ({suffix}):" if suffix else message
            a = input(f"? {label} [{default}] " if default else f"? {label} ").strip()
            return a or default
        return self._ask(fancy, plain).strip()

    def checkbox(self, message, choices, checked):
        """choices: [(value, label)]; checked: the values ticked to start
        with. Returns the ticked values, in choice order."""
        def fancy():
            opts = [self.q.Choice(title=label, value=value, checked=value in checked)
                    for value, label in choices]
            return self.q.checkbox(message, choices=opts).ask()

        def plain():
            ticked = {v for v, _ in choices if v in checked}
            while True:
                print(f"? {message}")
                for i, (value, label) in enumerate(choices, 1):
                    print(f"  {i:>2}) [{'x' if value in ticked else ' '}] {label}")
                a = input("  numbers to toggle (e.g. 2,4), enter to accept: ").strip()
                if not a:
                    return [v for v, _ in choices if v in ticked]
                for part in a.replace(" ", ",").split(","):
                    if part.isdigit() and 1 <= int(part) <= len(choices):
                        ticked ^= {choices[int(part) - 1][0]}
        return self._ask(fancy, plain)

    def select(self, message, choices, default):
        """choices: [(value, label)]; returns the chosen value."""
        def fancy():
            opts = [self.q.Choice(title=label, value=value) for value, label in choices]
            start = next(o for o in opts if o.value == default)
            return self.q.select(message, choices=opts, default=start).ask()

        def plain():
            print(f"? {message}")
            for i, (value, label) in enumerate(choices, 1):
                print(f"  {i}) {label}" + ("  [default]" if value == default else ""))
            while True:
                a = input("  choose: ").strip()
                if not a:
                    return default
                if a.isdigit() and 1 <= int(a) <= len(choices):
                    return choices[int(a) - 1][0]
        return self._ask(fancy, plain)
