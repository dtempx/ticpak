#!/usr/bin/env python3
"""Running TIC-80 for ticpak: find the Pro binary, capture a headless
run's output, boot the bundle alone then save the .tic, and run a cart in
its window passing its output on (`ticpak debug`).
"""
import codecs
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

if os.name != "nt":                 # the pty route below is POSIX-only
    import pty
    import select

from .console import detail, show, step
from .header import slug

HERE = os.path.dirname(os.path.abspath(__file__))
BOOT_SECONDS = 10       # the boot run's length: TIC-80's --cli loop never exits


def tic80_exe():
    """The Pro binary: $TIC80, else tools/tic80.exe (Windows) or
    tools/tic80/build/bin/tic80 (Linux) in the nearest enclosing directory of
    this script or the cwd that has one, else `tic80` on PATH."""
    env = os.environ.get("TIC80")
    if env and os.path.isfile(env):
        return env
    for start in (HERE, os.getcwd()):
        d = os.path.abspath(start)
        while True:
            for rel in (("tools", "tic80.exe"), ("tools", "tic80", "build", "bin", "tic80")):
                p = os.path.join(d, *rel)
                if os.path.isfile(p):
                    return p
            if os.path.dirname(d) == d:
                break
            d = os.path.dirname(d)
    for name in ("tic80", "tic80.exe"):
        if shutil.which(name):
            return shutil.which(name)
    sys.exit("ticpak: no TIC-80 Pro binary found - set $TIC80 to its path, or put tic80 on PATH")


IDLE_SECONDS = 0.3      # `debug`: output this long quiet ends an error's traceback


def play(cart, stream):
    """`ticpak debug`: TIC-80 in its window, running cart (a .tic or .lua) until
    it is closed. Everything it prints (its console mirrors to stdout: an
    error and its traceback too) goes to stream.feed as it comes, and
    stream.idle() when it pauses. Returns TIC-80's exit status (130 for
    Ctrl+C, which stops it too)."""
    cmd = [tic80_exe(), "--skip", os.path.abspath(cart)]
    if os.name == "nt":                 # TIC-80 does not buffer its stdout
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL)
        fd, close = p.stdout.fileno(), p.stdout.close
    else:                               # a pty, as _run_tty: never block-buffered
        fd, slave = pty.openpty()
        p = subprocess.Popen(cmd, stdout=slave, stderr=slave, stdin=subprocess.DEVNULL,
                             close_fds=True)
        os.close(slave)
        close = lambda: os.close(fd)    # noqa: E731
    chunks = queue.Queue()

    def reader():
        while True:
            try:
                data = os.read(fd, 65536)
            except OSError:             # a pty reports its end so
                data = b""
            chunks.put(data)
            if not data:
                return
    threading.Thread(target=reader, daemon=True).start()
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    status = None
    try:
        while True:
            try:
                data = chunks.get(timeout=IDLE_SECONDS)
            except queue.Empty:
                stream.idle()
                continue
            if not data:
                break
            stream.feed(decoder.decode(data))
    except KeyboardInterrupt:
        p.terminate()
        status = 130
    stream.feed(decoder.decode(b"", final=True))
    stream.close()
    rc = p.wait()
    close()
    return rc if status is None else status


def _run_tty(cmd, cwd, timeout):
    """Run cmd capturing output through a pty.

    TIC-80's --cli loop never exits on its own and ignores SIGTERM, so the run
    has to be killed - and on a pipe its stdio is block-buffered, which loses
    the unflushed tail (an error message) on the kill. A pty makes it line
    buffered, so what it printed is what we see.

    (Windows) There is no pty, and none is needed: the Windows build flushes
    its console output as it goes, so a plain pipe with a timeout catches the
    boot message and any error line (the same capture the port's check.py
    smoke test relies on). subprocess.run kills the child on TimeoutExpired
    and hands back what it had read.
    """
    if os.name == "nt":
        try:
            done = subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=timeout,
                                  stdin=subprocess.DEVNULL)
            raw = (done.stdout or b"") + (done.stderr or b"")
        except subprocess.TimeoutExpired as exc:
            raw = (exc.stdout or b"") + (exc.stderr or b"")
        return raw.decode(errors="replace").replace("\r", "")
    master, slave = pty.openpty()
    p = subprocess.Popen(cmd, cwd=cwd, stdout=slave, stderr=slave,
                         stdin=subprocess.DEVNULL, close_fds=True)
    os.close(slave)
    chunks, deadline = [], time.time() + timeout
    while time.time() < deadline:
        if select.select([master], [], [], 0.2)[0]:
            try:
                data = os.read(master, 65536)
            except OSError:
                break
            if not data:
                break
            chunks.append(data)
        if p.poll() is not None:
            break
    if p.poll() is None:
        p.kill()
        p.wait()
    while select.select([master], [], [], 0.1)[0]:
        try:
            data = os.read(master, 65536)
        except OSError:
            break
        if not data:
            break
        chunks.append(data)
    os.close(master)
    return b"".join(chunks).decode(errors="replace").replace("\r", "")


def verify(t, tic=None):
    """Boot the bundle (t.code, else the file t.lua) headless on its own, then
    save it as a .tic to tic (default t.tic). Only that file is kept: the
    bundle is written into a temporary folder for TIC-80 to load. Returns the
    .tic's path; exits with TIC-80's output if either step fails."""
    exe = tic80_exe()
    tic = tic or t.tic
    # The name goes inside `--cmd "load X & save Y"`: keep it plain.
    base = slug(t.name) or "cart"
    lua = base + ".lua"
    tmp = tempfile.mkdtemp(prefix=f"{base}-bundle-")
    if t.code is not None:
        with open(os.path.join(tmp, lua), "w", encoding="utf-8") as f:
            f.write(t.code)
    else:
        shutil.copy(t.lua, os.path.join(tmp, lua))
    try:
        step("boot", "booting the bundle headless in TIC-80")
        cmd = f"load {lua} & run"
        out = _run_tty([exe, "--fs=.", "--cli", "--skip", "--cmd", cmd], tmp, BOOT_SECONDS)
        bad = ('[string "' in out or "stack traceback" in out
               or "not found" in out or re.search(r"\berror\b", out, re.I))
        if bad or "loaded!" not in out:
            for line in out.splitlines():
                if line.strip():
                    print("   |", line[:120])
            print("bundle: FAILED to boot alone")
            sys.exit(1)
        detail(f"bundle: boots headless from a directory containing only {lua}")
        name = base + ".tic"
        step("save", f"saving {os.path.basename(tic)}" if tic == t.tic
             else "saving a .tic to check")
        # This run ends itself (`& exit`), so the ceiling only has to be
        # above the worst case - saving a big cart on a thermally
        # throttled SBC has been seen to take >20 s.
        out = _run_tty([exe, "--fs=.", "--cli", "--skip", "--cmd",
                        f"load {lua} & save {name} & exit"], tmp, 90)
        src = os.path.join(tmp, name)
        if not os.path.exists(src):
            for line in out.splitlines():
                if line.strip():
                    print("   |", line[:120])
            sys.exit("bundle: TIC-80 did not write the .tic")
        os.makedirs(os.path.dirname(os.path.abspath(tic)), exist_ok=True)
        shutil.copy(src, tic)
        if tic == t.tic:
            detail(f"bundle: {show(tic)}"
                   f" ({os.path.getsize(src)} bytes) - this is the file to upload")
        return tic
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
