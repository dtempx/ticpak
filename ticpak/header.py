#!/usr/bin/env python3
"""The cart's metadata header for ticpak: reading the cart's code
section, naming the outputs from the header, and checking and filling in
the `-- title:` / `-- author:` ... tags.
"""
import getpass
import os
import re
import subprocess
import sys

from .check import (check_header, parse_header, META_LINE_RE,
                    REQUIRED_META, OPTIONAL_META, PLACEHOLDER_META)
from .console import Prompts, show

# TIC-80 reads these from the cart's leading comments; minification must keep them.
META_KEYS = REQUIRED_META + OPTIONAL_META

# An asset section's opening tag, `-- <TILES>`: where a cart's code ends.
CHUNK_RE = re.compile(r"^-- <[A-Z]+\d?>", re.M)


def cart_code(cart):
    """The cart's code section (everything above the first asset chunk)."""
    text = open(cart, encoding="utf-8").read()
    m = CHUNK_RE.search(text)
    return text[:m.start()] if m else text


def incomplete_fields(meta):
    """Required header tags that are missing, empty, or TIC-80's placeholder."""
    return [t for t in REQUIRED_META
            if not meta.get(t) or meta[t].lower() in PLACEHOLDER_META.get(t, ())]


def slug(text):
    """A filename that is also safe inside TIC-80's `--cmd "load X & save Y"`."""
    return re.sub(r"[^a-z0-9_.-]+", "-", text.lower()).strip("-.")


def package_name(meta):
    """The output name: the saveid tag, else the title, made filename-safe."""
    for tag in ("saveid", "title"):
        if slug(meta.get(tag) or ""):
            return slug(meta[tag])
    return None


def project_name(cart):
    """The cart's project directory name, skipping layout dirs (src/, tic80/)."""
    d = os.path.dirname(os.path.abspath(cart))
    while os.path.basename(d).lower() in ("src", "tic80") and os.path.dirname(d) != d:
        d = os.path.dirname(d)
    return os.path.basename(d) or "game"


def _git(*args, cwd):
    try:
        out = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                             text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def repo_url(cwd):
    """The origin remote as a public https URL, any embedded credentials dropped."""
    url = _git("remote", "get-url", "origin", cwd=cwd)
    m = re.match(r"^[\w.-]+@([\w.-]+):(.+)$", url)          # git@host:owner/repo
    if m:
        url = f"https://{m.group(1)}/{m.group(2)}"
    url = re.sub(r"^(https?://)[^/@]*@", r"\1", url)         # user:token@host
    url = re.sub(r"\.git$", "", url)
    return url if url.startswith(("http://", "https://")) else ""


def header_defaults(meta, cart):
    """Suggested values for each required tag (the user can change them)."""
    cwd = os.path.dirname(cart)
    title = meta.get("title")
    if not title or title.lower() in PLACEHOLDER_META["title"]:
        title = project_name(cart)
    return {
        "title": title,
        "author": _git("config", "user.name", cwd=cwd) or getpass.getuser(),
        "desc": f"{title} - a TIC-80 game",
        "site": repo_url(cwd) or "https://tic80.com",
        "license": "MIT License",
        "version": "0.1",
        "script": "lua",
    }


def write_header(cart, values):
    """Set header tags in the cart in place: replace a tag's line if the
    header block has one, else add it after the block's last tag (or at the
    top). Keeps the file's line endings."""
    data = open(cart, "rb").read().decode("utf-8")
    nl = "\r\n" if "\r\n" in data else "\n"
    lines = data.split(nl)

    def fmt(tag, value):
        return f"-- {tag + ':':<7} {value}"

    tag_at, last = {}, -1
    for i, line in enumerate(lines):
        s = line.strip()
        if s and not s.startswith("--"):
            break
        m = META_LINE_RE.match(s)
        if m and m.group(1).lower() in META_KEYS:
            tag_at.setdefault(m.group(1).lower(), i)
            last = i
    new = []
    for tag in REQUIRED_META:
        if tag in values:
            if tag in tag_at:
                lines[tag_at[tag]] = fmt(tag, values[tag])
            else:
                new.append(fmt(tag, values[tag]))
    lines[last + 1:last + 1] = new
    open(cart, "wb").write(nl.join(lines).encode("utf-8"))


def fill_header(cart, meta, missing, ui):
    """Ask for the missing header tags and write them into the cart."""
    defaults = header_defaults(meta, cart)
    values = {}
    for tag in missing:
        if tag == "script":             # the only language this packager handles
            values[tag] = "lua"
            continue
        while True:
            value = ui.text(f"{tag}:", defaults[tag])
            if value and value.lower() not in PLACEHOLDER_META.get(tag, ()):
                break
            print(f"  {tag} must be filled in")
        values[tag] = value
        if tag == "title":
            defaults["desc"] = f"{value} - a TIC-80 game"
    write_header(cart, values)
    print(f"header: wrote {', '.join(values)} into {show(cart)}")


def ensure_header(cart, interactive):
    """The cart's header tags, complete. If some are missing, say which and
    (interactive) offer to fill them in, else exit with the lines to add."""
    meta = parse_header(cart_code(cart))
    missing = incomplete_fields(meta)
    if not missing:
        return meta
    if not meta:
        print(f"ticpak: {show(cart)} has no metadata header. TIC-80 and"
              " tic80.com read the cart's title, author, etc. from"
              " `-- title:`-style comments at the top of the code, and"
              " one needs to be added before packaging.")
    else:
        print(f"ticpak: {show(cart)} metadata header is incomplete -"
              f" missing or placeholder: {', '.join(missing)}")
    needed = ("Add these lines at the top of the cart:\n" +
              "\n".join(f"  -- {t + ':':<7} ..." for t in missing))
    if not interactive:
        sys.exit(needed)
    ui = Prompts()
    if not ui.confirm("Add the missing header fields now?", default=True):
        sys.exit(needed)
    fill_header(cart, meta, missing, ui)
    if not check_header(cart_code(cart), quiet=True):
        sys.exit("ticpak: header still incomplete after editing")
    return parse_header(cart_code(cart))
