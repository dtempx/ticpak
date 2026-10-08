#!/usr/bin/env python3
"""Console helpers for ticpak: message paths, the --verbose switch, the
flush-left output filter, the progress bar, and the interactive prompts.
"""
import os
import re
import shutil
import sys
import threading
import time

VERBOSE = False       # --verbose: progress and the check's detail on screen
_bar = None           # the Progress on screen, if any


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
        if "\n" not in self.buf:
            return len(s)
        bar = _bar if _bar is not None and _bar.stream is self.inner else None
        if bar:                         # print the lines above the progress bar
            bar.lock.acquire()
            bar.clear()
        try:
            while "\n" in self.buf:
                line, self.buf = self.buf.split("\n", 1)
                self.inner.write(flat_line(line) + "\n")
        finally:
            if bar:
                bar.draw()
                bar.lock.release()
        return len(s)

    def flush(self):
        if self.buf:
            self.inner.write(flat_line(self.buf))
            self.buf = ""
        self.inner.flush()

    def __getattr__(self, name):        # encoding, isatty, fileno, ...
        return getattr(self.inner, name)


def colour(stream):
    """Does stream show ANSI colour? A terminal, without NO_COLOR set (not
    when piped or redirected). (Windows) turns on the console's escapes."""
    if os.environ.get("NO_COLOR") or not getattr(stream, "isatty", lambda: False)():
        return False
    if os.name == "nt":
        try:
            import ctypes
            import msvcrt
            k32 = ctypes.windll.kernel32
            handle, mode = msvcrt.get_osfhandle(stream.fileno()), ctypes.c_uint()
            if not k32.GetConsoleMode(handle, ctypes.byref(mode)):
                return False
            if not mode.value & 4 and not k32.SetConsoleMode(handle, mode.value | 4):
                return False
        except Exception:
            return False
    return True


TINTS = {"highlight": 96, "warn": 93, "error": 91}   # bright cyan, yellow, red


def tint(text, kind):
    """text in kind's colour (TINTS; None: none) when stdout shows colour;
    else text as is."""
    return f"\033[{TINTS[kind]}m{text}\033[0m" if kind and colour(sys.stdout) else text


def highlight(text):
    """text in bright cyan when stdout shows colour; else text as is."""
    return tint(text, "highlight")


def is_console(stream):
    """Is stream a terminal? (Windows) isatty() is also true for NUL, so
    require a real console there."""
    try:
        if not stream.isatty():
            return False
        if os.name != "nt":
            return True
        import ctypes
        import msvcrt
        mode = ctypes.c_uint()
        handle = msvcrt.get_osfhandle(stream.fileno())
        return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)))
    except (AttributeError, OSError, ValueError):
        return False


def has_terminal():
    """Is someone at a terminal to answer prompts?"""
    return is_console(sys.stdin)


class Progress:
    """A progress bar and status line, in gray, redrawn in place below the
    output while a build runs, and gone when it ends. Only on a terminal:
    it draws on the stream behind sys.stdout, so -q (devnull) and a pipe or
    file get none. FlatStdout prints lines above it.

    plan: [(step, expected seconds)] in order. The bar fills by time within
    each step (never quite to its end), so a 10 s TIC-80 boot still moves.
    Use as a context manager; step() moves it on."""

    def __init__(self, plan):
        out = sys.stdout
        self.stream = out.inner if isinstance(out, FlatStdout) else out
        self.on = is_console(self.stream)
        self.plan = dict(plan)
        self.done, self.key, self.message, self.start = 0.0, None, "", 0.0
        self.shown = 0                  # length of the line on screen
        self.lock = threading.RLock()
        self.stop = threading.Event()
        if self.on:
            self.gray = colour(self.stream)
            try:
                "█░".encode(self.stream.encoding or "ascii")
                self.chars = "█░"
            except (LookupError, UnicodeError):
                self.chars = "#-"

    def __enter__(self):
        global _bar
        if self.on:
            _bar = self
            threading.Thread(target=self._tick, daemon=True).start()
        return self

    def __exit__(self, *exc):
        global _bar
        if self.on:
            self.stop.set()
            with self.lock:
                self.clear()
                _bar = None

    def _tick(self):
        while not self.stop.wait(0.1):
            with self.lock:
                if not self.stop.is_set():
                    self.draw()

    def step(self, key, message, seconds=None):
        """Start step key (seconds: a better estimate than the plan's)."""
        if not self.on:
            return
        with self.lock:
            if self.key is not None:
                self.done += self.plan[self.key]
            if seconds is not None or key not in self.plan:
                self.plan[key] = max(seconds or 0.0, 0.05)
            self.key, self.message, self.start = key, message, time.monotonic()
            self.draw()

    def fraction(self):
        part = 0.0
        if self.key is not None:
            expect = self.plan[self.key]
            part = expect * min((time.monotonic() - self.start) / expect, 0.97)
        return min((self.done + part) / (sum(self.plan.values()) or 1), 1.0)

    def draw(self):
        if not self.on or self.key is None:
            return
        f = self.fraction()
        width = 24
        fill = int(f * width)
        line = (f"[{self.chars[0] * fill}{self.chars[1] * (width - fill)}]"
                f" {int(f * 100):3d}%  {self.message}")
        line = line[:max(shutil.get_terminal_size().columns - 1, 10)]
        pad = " " * max(self.shown - len(line), 0)
        text = f"\033[90m{line}\033[0m" if self.gray else line
        self._write("\r" + text + pad + "\r")
        self.shown = len(line)

    def clear(self):
        if self.shown:
            self._write("\r" + " " * self.shown + "\r")
            self.shown = 0

    def _write(self, s):
        try:
            self.stream.write(s)
            self.stream.flush()
        except (OSError, ValueError):
            self.on = False


def step(key, message, seconds=None):
    """Move the progress bar on screen, if any, to step key (see Progress)."""
    if _bar is not None:
        _bar.step(key, message, seconds)


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
