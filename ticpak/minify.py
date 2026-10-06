#!/usr/bin/env python3
"""Lua 5.3 minifier for TIC-80 carts -- the minification stage of ticpak.

ticpak's bundle imports it to shrink the amalgamated cart; `ticpak minify`
runs it on its own.

Options (docs/minify.md has usage, docs/minify-spec.md the contract), combined as
a set - `comments,rename-vars`; an empty set is a passthrough:
  comments          remove comments; every other character stays where it was
  whitespace        remove extraneous whitespace and newlines: one function
                    start per line, wrapped at 120 columns (without it, the
                    source's line breaks are kept, single-space indented)
  rename-vars       rename non-function variables to the shortest free names
  rename-functions  rename functions too (error messages then show the short
                    names; the decode map has the originals)
  rename-tables     rename table keys (fields and methods) consistently across
                    the program, when an analysis of how it uses strings proves
                    that safe; off otherwise (the report says why)
  constants         inline constant values and remove the constants
  extra             the remaining optimisations: evaluate constant expressions,
                    remove unreachable code and anything nothing uses, call
                    sugar, alias heavily used API functions, share repeated
                    strings and numbers through locals, merge local statements
Two presets: `default`, every option but rename-functions and rename-tables,
and `max`, every option. Every option but `comments` works on the token stream,
so it removes comments too.

Why no AST printer: luamin 1.0.4 (npm) re-prints expressions with Lua 5.1
precedence and silently turned (x & y) + z into x&y+z (verified 2026-09-13 on
wavynavy). Max mode parses into a *lossless* concrete tree -- every token,
parenthesis and separator of the source is kept -- and every parse is checked to
re-emit exactly the token stream it was built from. Passes only delete
statements, substitute a whole subexpression by a literal (parenthesised where
precedence could change) or by a local holding the same value, or rename
identifiers, so no expression is ever regrouped. The final text is re-lexed and re-parsed before it is returned.
"""
import bisect, math, re
from decimal import Decimal

OPTIONS = ("comments", "rename-vars", "rename-functions", "rename-tables", "constants",
           "whitespace", "extra")
OPTION_HELP = {
    "comments": "remove comments (keeps the metadata header and asset blocks)",
    "rename-vars": "rename variables to the shortest free names (1-2 letters)",
    "rename-functions": "rename functions to the shortest free names too"
                        " (error messages then show the short names)",
    "rename-tables": "rename table fields and methods too, where an analysis proves"
                     " it safe (error messages then show the short names)",
    "constants": "inline constant values and remove the constants",
    "whitespace": "remove extraneous newlines and whitespace",
    "extra": "further optimisations (see --help for more info)",
}
# What `extra` does, for --help and the docs: one pass of the max pipeline each.
EXTRA_HELP = {
    "dce": "remove unreachable code (if false ... end, code after return)",
    "fold": "evaluate constant expressions (2*8 -> 16)",
    "shake": "remove functions, variables and modules nothing uses",
    "sugar": 'call sugar: f("x") -> f"x", f({...}) -> f{...}',
    "alias": "alias heavily used API functions to short locals",
    "literals": "share strings and numbers written several times through one local",
    "merge":"merge adjacent local statements",
}
# The passes of the max pipeline (ALL_PASSES) each option runs.
OPTION_PASSES = {"constants": ("inline",), "rename-vars": ("rename-vars",),
                 "rename-functions": ("rename-functions",),
                 "rename-tables": ("rename-tables",), "extra": tuple(EXTRA_HELP)}
ALL_OPTIONS = frozenset(OPTIONS)
# `default`: every option but the opt-in ones: rename-functions costs readable
# error messages (spec D11), and rename-tables both those and a guarantee that
# rests on an analysis rather than Lua's semantics alone (spec R13). `max`:
# every option.
DEFAULT_OPTIONS = ALL_OPTIONS - {"rename-functions", "rename-tables"}
PRESETS = {"default": DEFAULT_OPTIONS, "max": ALL_OPTIONS}


def parse_options(spec):
    """'comments,rename-vars' | 'default' | 'max' | an iterable of any of
    them -> frozenset of OPTIONS ('' or an empty iterable: no minification).
    Any option but comments implies comments: it relexes the code."""
    items = spec.split(",") if isinstance(spec, str) else list(spec)
    out = set()
    for it in (i.strip() for i in items):
        if not it:
            continue
        if it in PRESETS:
            out |= set(PRESETS[it])
        elif it in OPTIONS:
            out.add(it)
        else:
            raise ValueError(f"unknown minify option {it!r} (expected one or"
                             f" more of {', '.join(OPTIONS)}, or a preset:"
                             f" {', '.join(PRESETS)})")
    if out:
        out.add("comments")
    return frozenset(out)

KEYWORDS = set("and break do else elseif end false for function goto if in local nil not or repeat return then true until while".split())
OPS = ["...", "..", "::", "==", "~=", "<=", ">=", "//", "<<", ">>",
       "+", "-", "*", "/", "%", "^", "#", "&", "~", "|", "<", ">", "=",
       "(", ")", "{", "}", "[", "]", ";", ":", ",", "."]
NUM = re.compile(r"0[xX][0-9a-fA-F]*(?:\.[0-9a-fA-F]*)?(?:[pP][+-]?[0-9]+)?|(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# A text cart's asset sections (-- <TILES> ... -- </TILES>) run from the first
# chunk marker to the end of the file and are passed through verbatim. The
# marker must be alone on its line AND everything after it must be comment
# lines: an inlined module's prose comment can begin "-- <MAP> region ..."
# (wavynavy's a2boot.lua does), and a looser match cut the code there.
CHUNK_RE = re.compile(r"^-- <[A-Z]+\d?>[ \t]*\r?$", re.M)

# <reserved> -- generated by scripts/update_reserved.py; do not edit by hand
TIC80_VERSION = "1.2.0 Pro (f98470a)"
TIC80_GLOBALS = """
BOOT TIC _G _VERSION assert btn btnp circ circb clip cls collectgarbage coroutine debug dofile elli
ellib error exit fft ffts fget font fset getmetatable ipairs key keyp line load loadfile map math
memcpy memset mget mouse mset music next package paint pairs pcall peek peek1 peek2 peek4 pix pmem
poke poke1 poke2 poke4 print rawequal rawget rawlen rawset rect rectb require reset select
setmetatable sfx spr string sync table textri time tonumber tostring trace tri trib tstamp ttri type
vbank xpcall
""".split()
# every key of the library tables, two levels deep (<string>: the
# string metatable)
TIC80_LIBRARY = """
<string>.__index coroutine.create coroutine.isyieldable coroutine.resume coroutine.running
coroutine.status coroutine.wrap coroutine.yield debug.debug debug.gethook debug.getinfo
debug.getlocal debug.getmetatable debug.getregistry debug.getupvalue debug.getuservalue
debug.sethook debug.setlocal debug.setmetatable debug.setupvalue debug.setuservalue debug.traceback
debug.upvalueid debug.upvaluejoin math.abs math.acos math.asin math.atan math.atan2 math.ceil
math.cos math.cosh math.deg math.exp math.floor math.fmod math.frexp math.huge math.ldexp math.log
math.log10 math.max math.maxinteger math.min math.mininteger math.modf math.pi math.pow math.rad
math.random math.randomseed math.sin math.sinh math.sqrt math.tan math.tanh math.tointeger math.type
math.ult package.config package.cpath package.loaded package.loaded._G package.loaded.coroutine
package.loaded.debug package.loaded.math package.loaded.package package.loaded.string
package.loaded.table package.loadlib package.path package.preload package.searchers
package.searchpath string.byte string.char string.dump string.find string.format string.gmatch
string.gsub string.len string.lower string.match string.pack string.packsize string.rep
string.reverse string.sub string.unpack string.upper table.concat table.insert table.move table.pack
table.remove table.sort table.unpack
""".split()
# </reserved>

CALLBACKS = {"TIC", "BOOT", "SCN", "BDR", "OVR", "MENU"}
# Standard 5.3 / 5.1 names TIC-80 1.2 does not expose, reserved anyway so a
# cart written against a different build can never have them renamed.
EXTRA_RESERVED = {"_ENV", "_G", "self", "arg", "utf8", "os", "io", "bit32",
                  "unpack", "loadstring", "module", "setfenv", "getfenv", "jit"}
RESERVED = set(TIC80_GLOBALS) | CALLBACKS | EXTRA_RESERVED
# Reading any of these makes global analysis unsound (spec D6).
DYNAMIC_NAMES = {"_G", "_ENV", "load", "loadstring", "dofile", "loadfile", "debug",
                 "rawget", "rawset", "rawequal", "getfenv", "setfenv"}
NAME_EST = 2          # assumed length of a renamed identifier in size decisions
ALL_PASSES = ("fold", "inline", "dce", "shake", "rename-vars", "rename-functions",
              "rename-tables", "sugar", "alias", "literals", "merge")
UPPER_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class LuaSyntaxError(SyntaxError):
    pass


# =============================================================================
# Lexer (shared by every mode)
# =============================================================================

def long_bracket(s, i):
    """If s[i:] opens a long bracket [=*[, return (level, content_start)."""
    if i >= len(s) or s[i] != "[": return None
    j = i + 1
    while j < len(s) and s[j] == "=": j += 1
    return (j - i - 1, j + 1) if j < len(s) and s[j] == "[" else None

def lex(s, track_newlines=False, offsets=None):
    """Lex Lua source into (kind, text) tokens.

    With track_newlines=True, each token also records whether a newline appeared
    in the skipped whitespace/comments before it: (kind, text, had_newline).
    If offsets is a list, each token's start offset in s is appended to it.
    """
    toks, i, n = [], 0, len(s)
    saw_nl = False
    while i < n:
        c = s[i]
        if offsets is not None and len(offsets) < len(toks) + 1 and c not in " \t\r\n\f\v" \
                and not s.startswith("--", i):
            offsets.append(i)
        if c in " \t\r\n\f\v":
            if track_newlines and c == "\n":
                saw_nl = True
            i += 1; continue
        if s.startswith("--", i):                                  # comment
            lb = long_bracket(s, i + 2)
            if lb:
                lvl, st = lb
                end = s.index("]" + "=" * lvl + "]", st)
                if track_newlines and "\n" in s[i:end + lvl + 2]:
                    saw_nl = True
                i = end + lvl + 2
            else:
                nl = s.find("\n", i)
                if track_newlines:
                    saw_nl = True
                i = n if nl < 0 else nl + 1
            continue
        if track_newlines:
            nl_flag = saw_nl
            saw_nl = False
        lb = long_bracket(s, i)                                    # long string
        if lb:
            lvl, st = lb
            end = s.index("]" + "=" * lvl + "]", st)
            tok = ("string", s[i:end + lvl + 2])
            toks.append(tok + (nl_flag,) if track_newlines else tok)
            i = end + lvl + 2; continue
        if c in "\"'":                                             # short string
            j = i + 1
            while s[j] != c:
                j += 2 if s[j] == "\\" else 1
            tok = ("string", s[i:j + 1])
            toks.append(tok + (nl_flag,) if track_newlines else tok)
            i = j + 1; continue
        m = NUM.match(s, i)
        if m and (c.isdigit() or (c == "." and i + 1 < n and s[i + 1].isdigit())):
            tok = ("number", m.group())
            toks.append(tok + (nl_flag,) if track_newlines else tok)
            i = m.end(); continue
        m = NAME.match(s, i)
        if m:
            t = m.group()
            tok = ("keyword" if t in KEYWORDS else "name", t)
            toks.append(tok + (nl_flag,) if track_newlines else tok)
            i = m.end(); continue
        for op in OPS:
            if s.startswith(op, i):
                tok = ("op", op)
                toks.append(tok + (nl_flag,) if track_newlines else tok)
                i += len(op); break
        else:
            raise SyntaxError(f"unexpected {c!r} at offset {i}")
    return toks

def lex_lines(s, offsets=None):
    """lex() plus the 1-based source line of each token: (kind, text, line).
    If offsets is a list, each token's start offset in s is appended to it."""
    offs = [] if offsets is None else offsets
    toks = lex(s, offsets=offs)
    out, line, pos = [], 1, 0
    for (kind, text), j in zip(toks, offs):
        line += s.count("\n", pos, j)
        out.append((kind, text, line))
        pos = j
    return out

def _needs_space(pk, pt, kind, text):
    """True when omitting whitespace between two tokens would re-lex differently."""
    if kind == "comment":             # a kept comment: kept apart from the code before it
        return True
    if kind == "raw":                 # a protected body starts with "(": never needs one
        return False
    if pk == "raw":                   # ... and ends with `end`
        pk, pt = "keyword", "end"
    WORD = ("name", "keyword", "number")
    if (pk in WORD and kind in WORD) or (pk == "number" and text[0] == "."):
        return True
    try:
        merged = lex(pt + text)
    except (SyntaxError, ValueError, IndexError):
        merged = None
    return merged != [(pk, pt), (kind, text)]

BLOCK_OPEN = {"do", "then", "repeat", "function"}
BLOCK_CLOSE = {"end", "until"}

def emit_readable(toks3):
    """Join tokens with newlines where the original source had them, single-space indent.

    toks3 is a list of (kind, text, had_newline) from lex(..., track_newlines=True).
    Preserves the original line structure (wherever the source had a newline between
    tokens, the output does too) while stripping comments and compacting each line.
    Indentation is computed from block-keyword depth.
    """
    depth = 0
    lines = []
    cur = []
    line_depth = 0

    def flush():
        if cur:
            line = "".join(t for _, t in cur)
            lines.append(" " * line_depth + line)
            cur.clear()

    for kind, text, had_nl in toks3:
        if had_nl and cur:
            flush()
            line_depth = depth

        is_close = kind == "keyword" and text in BLOCK_CLOSE
        is_else = kind == "keyword" and text == "else"
        is_elseif = kind == "keyword" and text == "elseif"
        if is_close or is_else or is_elseif:
            depth = max(0, depth - 1)
            if not cur:
                line_depth = depth

        if cur:
            pk, pt = cur[-1]
            if _needs_space(pk, pt, kind, text):
                cur.append((None, " "))
        cur.append((kind, text))

        if kind == "keyword" and text in BLOCK_OPEN:
            depth += 1
        elif is_else:
            depth += 1
        elif kind == "raw":           # a protected body ends with the `end` of its function
            depth = max(0, depth - 1)

    flush()
    return "\n".join(lines)


def strip_comments(s, keep=(), gone=None):
    """Remove every comment and nothing else. A line that held only comments
    is dropped, whitespace before a comment that ends its line goes with it,
    and a block comment between two tokens becomes one space. Strings - long
    ones included - are copied byte for byte, and so is every (start, end)
    span in keep (NOMINIFY-protected function bodies and kept comments,
    sorted: Directives.keep()). gone: a list to append (offset, comment
    bytes, whitespace bytes) to for each comment removed (the whitespace
    that went with it; -1 for the space that replaced it)."""
    out, i, n = [], 0, len(s)
    keep, k = list(keep), 0

    def line_blank():
        """Is the output since the last newline only spaces/tabs? (Then that
        newline was code, not inside a long string: a string closing on this
        line would have left its quote or bracket here.)"""
        j = len(out)
        while j and out[j - 1] in " \t":
            j -= 1
        return j == 0 or out[j - 1] == "\n"

    def trim_trailing():
        k = len(out)
        while out and out[-1] in " \t":
            out.pop()
        return k - len(out)

    while i < n:
        c = s[i]
        if k < len(keep) and i == keep[k][0]:
            out.extend(s[i:keep[k][1]]); i = keep[k][1]; k += 1; continue
        if s.startswith("--", i):
            lb = long_bracket(s, i + 2)
            if lb:
                lvl, st = lb
                end = s.index("]" + "=" * lvl + "]", st) + lvl + 2
            else:
                nl = s.find("\n", i)
                end = n if nl < 0 else nl
            text = s[i:end].rstrip("\r")
            rest_end = s.find("\n", end)
            rest_end = n if rest_end < 0 else rest_end
            ends_line = not s[end:rest_end].strip(" \t\r")
            if ends_line:
                blank = line_blank()
                trimmed = trim_trailing()
                # a line that was only comment loses its newline too
                j = min(n, rest_end + 1) if blank else rest_end
                if gone is not None:
                    gone.append((i, len(text.encode("utf-8")), trimmed + j - i - len(text)))
                i = j
                continue
            space = bool(out) and out[-1] not in " \t\n" and s[end] not in " \t"
            if space:
                out.append(" ")                # keep the tokens apart
            if gone is not None:
                gone.append((i, len(text.encode("utf-8")), end - i - len(text) - space))
            i = end
            continue
        lb = long_bracket(s, i)
        if lb:
            lvl, st = lb
            end = s.index("]" + "=" * lvl + "]", st) + lvl + 2
            out.extend(s[i:end]); i = end; continue
        if c in "\"'":
            j = i + 1
            while s[j] != c:
                j += 2 if s[j] == "\\" else 1
            out.extend(s[i:j + 1]); i = j + 1; continue
        out.append(c); i += 1
    return "".join(out)


def layout_lines(toks):
    """Keep the source's line breaks: an output line starts wherever a token
    comes from a later source line than the one before it, indented one space
    per block level. Returns (text, first source line of each output line).
    A kept comment that had its own line(s) gets them again; one that
    followed code stays at the end of that line; code after it starts a new
    line."""
    toks3, firsts, prev, after_comment = [], [], None, False
    for kind, text, line in toks:
        if kind == "nl":
            continue
        brk = prev is not None and (line > prev or after_comment
                                    or (kind == "comment" and text.own_line))
        if prev is None or brk:
            # (a token's line can be its statement's - an `if`'s `end` - so
            # the line after a comment maps to a line after the comment)
            firsts.append(max(line, prev + 1) if after_comment else line)
        toks3.append((kind, text, brk))
        prev = line if prev is None else max(prev, line)
        if kind in ("raw", "comment"):    # verbatim text: its own lines too
            nl = text.count("\n")
            firsts.extend(range(line + 1, line + nl + 1))
            prev = max(prev, line + nl)
        after_comment = kind == "comment"
    return emit_readable(toks3), firsts


class RawText(str):
    """A NOMINIFY-protected function body - from its "(" to its "end" - as the
    text of one "raw" token. refs: the names it uses (their bindings are
    pinned); line: the source line it starts on."""

    def __new__(cls, text, refs, line):
        s = super().__new__(cls, text)
        s.refs, s.line = refs, line
        return s


class CommentText(str):
    """A comment block a NOMINIFY directive keeps (spec R8i), as the text of
    one "comment" token: the source from its first comment's `--` to the end
    of its last comment. own_line: it had its own line(s) in the source (a
    comment block), rather than following code."""

    def __new__(cls, text, own_line):
        s = super().__new__(cls, text)
        s.own_line = own_line
        return s


class NominifyError(ValueError):
    """A NOMINIFY directive that cannot be honoured; line is a source line."""

    def __init__(self, line, msg):
        super().__init__(f"line {line}: {msg}")
        self.line, self.msg = line, msg


NOMINIFY_RE = re.compile(r"\bnominify\b", re.I)
TAG_LINE_RE = re.compile(r"-- <[A-Za-z]")     # TIC-80 reads it as an asset section


def _scan_comments(src):
    """([(start line, end line, text, start, end)] of every comment, {lines
    holding code}). Strings count as code on every line they span."""
    comments, code = [], set()
    i, n, line = 0, len(src), 1
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1; i += 1; continue
        if c in " \t\r\f\v":
            i += 1; continue
        if src.startswith("--", i):
            lb = long_bracket(src, i + 2)
            if lb:
                lvl, st = lb
                end = src.index("]" + "=" * lvl + "]", st) + lvl + 2
            else:
                nl = src.find("\n", i)
                end = n if nl < 0 else nl
            text = src[i:end].rstrip("\r")
            comments.append((line, line + text.count("\n"), text, i, i + len(text)))
            line += text.count("\n"); i = end; continue
        lb = long_bracket(src, i)
        if lb:
            lvl, st = lb
            end = src.index("]" + "=" * lvl + "]", st) + lvl + 2
        elif c in "\"'":
            j = i + 1
            while src[j] != c:
                j += 2 if src[j] == "\\" else 1
            end = j + 1
        else:
            end = i + 1
        nls = src.count("\n", i, end)
        code.update(range(line, line + nls + 1))
        line += nls; i = end
    return comments, code


def _comment_blocks(src):
    """(blocks, trailing, code lines, blank(l)). A block is a run of comments
    each starting on its own line, ended by a blank line or code: [comment,
    ...] with comments as _scan_comments gives them. trailing: the comments
    that follow code on their line."""
    comments, code = _scan_comments(src)
    text = src.split("\n")

    def blank(l):
        return 1 <= l <= len(text) and l not in code and not text[l - 1].strip()

    blocks, trailing = [], []
    for c in comments:
        if c[0] in code:
            trailing.append(c)
        elif (blocks and blocks[-1][-1][1] not in code
              and c[0] <= blocks[-1][-1][1] + 1):
            blocks[-1].append(c)
        else:
            blocks.append([c])
    return blocks, trailing, code, blank


def _has_nomi(comments):
    return any(NOMINIFY_RE.search(c[2]) for c in comments)


def top_block_nominify(src):
    """Is there a NOMINIFY in the source's top comment block (after any
    leading blank lines)? Then the whole module is left alone (spec R8h)."""
    if not NOMINIFY_RE.search(src):
        return False
    blocks, _, code, blank = _comment_blocks(src)
    l = 1
    while blank(l):
        l += 1
    return bool(blocks) and blocks[0][0][0] == l and _has_nomi(blocks[0])


def _is_preload(toks, i):
    """Is toks[i] the `function` of `package.preload["m"] = function(...)`?"""
    return (i >= 7 and [t[1] for t in toks[i - 7:i - 3]] == ["package", ".", "preload", "["]
            and toks[i - 3][0] == "string" and [t[1] for t in toks[i - 2:i]] == ["]", "="])


class Directives:
    """What a source's NOMINIFY comments ask for (spec R8g-R8i).

    regions:  (start, end) offsets of the protected function bodies, from
              "(" to the end of "end", outermost only
    names:    {(line, name)}: the variables declared or assigned there keep
              their names, declarations and values
    comments: [(start, end, at, text)]: the comment blocks kept in the
              output; at is the index of the token they go before
    """

    def __init__(self, regions=(), names=frozenset(), comments=()):
        self.regions, self.names, self.comments = list(regions), names, list(comments)

    def keep(self):
        """Every span copied verbatim: the regions and the kept comments."""
        return sorted(self.regions + [c[:2] for c in self.comments])


def _targets(stmts, funcs, modules):
    """What a directive on these statements does: (functions to protect,
    {(line, name)} to keep). A module (in modules, by id) is protected only
    by its own top block, never by a directive above its preload line."""
    prot, names = [f for f in funcs if id(f) not in modules], set()
    for s in stmts:
        t = type(s)
        if t in (LocalFunc, FuncStat):
            prot.append(s.func)
            # the function's name too, as `local f = function` keeps f
            if t is LocalFunc:
                names.add((s.name.line, s.name.name))
            elif not s.path and not s.method:
                names.add((s.base.line, s.base.name))
        elif t in (Local, Assign):
            prot.extend(e for e in s.exprs if type(e) is Func and id(e) not in modules)
            ns = s.names if t is Local else [tg for tg in s.targets if type(tg) is Name]
            names.update((n.line, n.name) for n in ns)
        elif t is NumFor:
            names.add((s.var.line, s.var.name))
        elif t is GenFor:
            names.update((n.line, n.name) for n in s.names)
    return prot, names


def directives(src, top=True):
    """Find the source's NOMINIFY directives (spec R8g-R8i). A directive is a
    comment block holding NOMINIFY (any case, as a word), or a comment
    containing it that follows code on its line.

    - A block at the top of a `package.preload` module protects the module.
      With top, one at the top of the source is the caller's to act on (it
      leaves it all alone: top_block_nominify) and is skipped here.
    - A block applies to the statements that start on the line after it (or
      on its last line, when code follows the block there); a comment after
      code to the statements that start or end on its line. Each function
      among them (a function statement, `local function`, or a function value
      of `local`/assignment), and each function whose `function` keyword is
      on that line, is protected: kept byte for byte. Each variable a `local`,
      assignment or `for` among them declares or assigns is kept: its name,
      declaration and value (Info pins it).
    - A directive that keeps nothing that way keeps its own comment, placed
      between statements or table fields (else after the statement around it).
    - Raises NominifyError for a kept comment line TIC-80 would read as an
      asset section tag.
    """
    if not NOMINIFY_RE.search(src):
        return Directives()
    blocks, trailing, code, blank = _comment_blocks(src)
    offs = []
    toks = lex_lines(src, offs)
    p = Parser(toks)
    p.marks, p.seen, p.funcs = set(), [], []
    p.chunk()
    line_of = lambda i: toks[i][2] if i < len(toks) else (toks[-1][2] if toks else 1)
    starts, ends, kw_on = {}, {}, {}
    for a, b, s in p.seen:
        starts.setdefault(line_of(a), []).append(s)
        ends.setdefault(line_of(b - 1), []).append(s)
    for f in p.funcs:
        kw_on.setdefault(line_of(f.kw), []).append(f)

    protect_f, names, kept = [], set(), []
    used = set()                                # blocks consumed as module directives
    modules = {id(f) for f in p.funcs if _is_preload(toks, f.kw)}
    for f in p.funcs:
        if id(f) in modules:
            l = line_of(f.kw) + 1
            while blank(l):
                l += 1
            for k, blk in enumerate(blocks):
                if blk[0][0] == l:
                    if _has_nomi(blk):
                        protect_f.append(f); used.add(k)
                    break
    l = 1
    while blank(l):
        l += 1
    if top and blocks and blocks[0][0][0] == l:
        used.add(0)                             # the top block: top_block_nominify's
    for k, blk in enumerate(blocks):
        if k in used or not _has_nomi(blk):
            continue
        last = blk[-1][1]
        tl = last if last in code else last + 1 if last + 1 in code else None
        prot, nm = (_targets(starts.get(tl, ()), kw_on.get(tl, ()), modules) if tl
                    else ([], set()))
        protect_f += prot; names |= nm
        if not prot and not nm:
            kept.append((blk[0][3], blk[-1][4], blk[0][0], True))
    for c in trailing:
        if not NOMINIFY_RE.search(c[2]):
            continue
        l = c[0]
        stmts = starts.get(l, []) + [s for s in ends.get(l, ()) if s not in starts.get(l, ())]
        prot, nm = _targets(stmts, kw_on.get(l, ()), modules)
        protect_f += prot; names |= nm
        if not prot and not nm:
            kept.append((c[3], c[4], c[0], False))

    regions = []
    for a, b in sorted({(offs[f.toks[0]], offs[f.toks[1]] + len("end")) for f in protect_f}):
        if not regions or a >= regions[-1][1]:   # outermost only: module level wins
            regions.append((a, b))
    comments = []
    for a, b, line, own in sorted(kept):
        if any(ra <= a < rb for ra, rb in regions):
            continue                            # inside protected code: verbatim already
        text = src[a:b]
        for i, ln in enumerate(text.split("\n")):
            if TAG_LINE_RE.match(ln.lstrip() if i == 0 else ln):
                raise NominifyError(line + i, "a comment kept by NOMINIFY has a line starting"
                                    " `-- <`, which TIC-80 reads as the start of the asset"
                                    " sections - reword that line")
        at = bisect.bisect_left(offs, b)
        if at not in p.marks:
            # not between statements or table fields: after the innermost
            # statement around it instead, at the end of that line
            around = [(sa, sb) for sa, sb, _ in p.seen if sa < at < sb]
            at, own = max(around)[1], False
        comments.append((a, b, at, CommentText(text, own)))
    return Directives(regions, frozenset(names), comments)


def nominify_regions(src):
    """(start, end) offsets of every NOMINIFY-protected function body, from
    its "(" to the end of its "end", outermost only (spec R8h)."""
    return directives(src).regions


def protect(src, toks, offs, nomi):
    """Put each kept comment in the token stream as ("comment", CommentText,
    line), and collapse each protected body's tokens into one ("raw",
    RawText, line)."""
    if nomi.comments:
        at = {}
        for c in nomi.comments:
            at.setdefault(c[2], []).append(c)
        t2, o2 = [], []
        for i in range(len(toks) + 1):
            for a, b, _, text in at.get(i, ()):
                t2.append(("comment", text, src.count("\n", 0, a) + 1)); o2.append(a)
            if i < len(toks):
                t2.append(toks[i]); o2.append(offs[i])
        toks, offs = t2, o2
    spans = nomi.regions
    if not spans:
        return toks
    out, i, k = [], 0, 0
    while i < len(toks):
        if k < len(spans) and offs[i] == spans[k][0]:
            a, b = spans[k]
            j, refs = i, set()
            while j < len(toks) and offs[j] < b:
                if toks[j][0] == "name" and not (j and toks[j - 1][:2] in (("op", "."), ("op", ":"))):
                    refs.add(toks[j][1])
                j += 1
            line = toks[i][2]
            out.append(("raw", RawText(src[a:b], frozenset(refs), line), line))
            i, k = j, k + 1
        else:
            out.append(toks[i]); i += 1
    return out


# =============================================================================
# Lossless concrete syntax tree
# =============================================================================

class Lit:            # kind: number string nil true false vararg
    def __init__(s, kind, text, line): s.kind, s.text, s.line = kind, text, line
class Name:
    def __init__(s, name, line, pos=-1): s.name, s.line, s.pos, s.b = name, line, pos, None
class Paren:
    def __init__(s, e, line): s.e, s.line = e, line
class Un:
    def __init__(s, op, a, line): s.op, s.a, s.line = op, a, line
class Bin:
    def __init__(s, op, a, b, line): s.op, s.a, s.b, s.line = op, a, b, line
class Index:
    def __init__(s, obj, key, line): s.obj, s.key, s.line = obj, key, line
class Field:
    def __init__(s, obj, name, line): s.obj, s.name, s.line = obj, name, line
class Call:           # form: "(" args list, "str" one string Lit, "tbl" one Table
    def __init__(s, fn, args, form, line): s.fn, s.args, s.form, s.line = fn, args, form, line
class Method:
    def __init__(s, obj, name, args, form, line):
        s.obj, s.name, s.args, s.form, s.line = obj, name, args, form, line
class Func:
    def __init__(s, params, vararg, body, line, end_line, is_method=False):
        s.params, s.vararg, s.body, s.line, s.end_line = params, vararg, body, line, end_line
        s.is_method, s.chunk, s.upvals, s.self_b = is_method, None, set(), None
        s.raw, s.raw_bindings = None, []      # NOMINIFY: the body's exact source (RawText)
        s.kw = s.toks = None                  # token indices: `function`, ("(", "end")
class Table:          # fields: [kind, key, value, sep]; kind pos|named|index
    def __init__(s, fields, line): s.fields, s.line = fields, line

class Block:
    def __init__(s, stmts, end_pos): s.stmts, s.end_pos = stmts, end_pos
class Local:
    def __init__(s, names, exprs, line): s.names, s.exprs, s.line = names, exprs, line
class LocalFunc:
    def __init__(s, name, func, line): s.name, s.func, s.line = name, func, line
class FuncStat:       # path: [(field, line)], method: (name, line) | None
    def __init__(s, base, path, method, func, line):
        s.base, s.path, s.method, s.func, s.line = base, path, method, func, line
class Assign:
    def __init__(s, targets, exprs, line): s.targets, s.exprs, s.line = targets, exprs, line
class CallStat:
    def __init__(s, call, line): s.call, s.line = call, line
class Do:
    def __init__(s, body, line): s.body, s.line = body, line
class While:
    def __init__(s, cond, body, line): s.cond, s.body, s.line = cond, body, line
class Repeat:
    def __init__(s, body, cond, line, end_pos): s.body, s.cond, s.line, s.end_pos = body, cond, line, end_pos
class If:
    def __init__(s, conds, blocks, orelse, line): s.conds, s.blocks, s.orelse, s.line = conds, blocks, orelse, line
class NumFor:
    def __init__(s, var, start, stop, step, body, line):
        s.var, s.start, s.stop, s.step, s.body, s.line = var, start, stop, step, body, line
class GenFor:
    def __init__(s, names, exprs, body, line): s.names, s.exprs, s.body, s.line = names, exprs, body, line
class Return:
    def __init__(s, exprs, semi, line): s.exprs, s.semi, s.line = exprs, semi, line
class Break:
    def __init__(s, line): s.line = line
class Goto:
    def __init__(s, name, line): s.name, s.line, s.label = name, line, None
class Label:
    def __init__(s, name, line): s.name, s.line = name, line
class Semi:
    def __init__(s, line): s.line = line
class Comment:        # a comment kept by NOMINIFY (CommentText); also a table field's key
    def __init__(s, text, line): s.text, s.line = text, line

EOF_TOK = ("eof", "<eof>", 0)
BINPRI = {"or": (1, 1), "and": (2, 2),
          "<": (3, 3), ">": (3, 3), "<=": (3, 3), ">=": (3, 3), "~=": (3, 3), "==": (3, 3),
          "|": (4, 4), "~": (5, 5), "&": (6, 6), "<<": (7, 7), ">>": (7, 7),
          "..": (9, 8), "+": (10, 10), "-": (10, 10),
          "*": (11, 11), "/": (11, 11), "//": (11, 11), "%": (11, 11), "^": (14, 13)}
UNARY_PRI = 12
BLOCK_END = {"end", "else", "elseif", "until"}


class Parser:
    """Recursive-descent Lua 5.3 parser (same priorities as lparser.c)."""

    def __init__(self, toks):
        self.t, self.i, self.n = toks, 0, len(toks)
        # directives() sets these to record where a kept comment may go
        # (marks: token indices between statements or table fields), every
        # statement's (start, end) token span (seen) and every function (funcs)
        self.marks = self.seen = self.funcs = None

    def tok(self):
        return self.t[self.i] if self.i < self.n else EOF_TOK

    def is_(self, text):
        t = self.tok()
        return t[1] == text and t[0] in ("op", "keyword")

    def take(self):
        t = self.tok(); self.i += 1; return t

    def err(self, msg):
        t = self.tok()
        if t[0] == "comment":                  # directives() places them where they parse
            raise AssertionError(f"minify: kept NOMINIFY comment misplaced at line {t[2]}")
        raise LuaSyntaxError(f"line {t[2]}: {msg} near {t[1]!r}")

    def expect(self, text):
        if not self.is_(text):
            self.err(f"'{text}' expected")
        return self.take()

    def name(self):
        t = self.tok()
        if t[0] != "name":
            self.err("<name> expected")
        self.i += 1
        return Name(t[1], t[2], self.i - 1)

    def chunk(self):
        b = self.block()
        if self.tok()[0] != "eof":
            self.err("'<eof>' expected")
        return b

    def comments(self, out):
        """Take the kept-comment tokens here, appending a Comment for each."""
        while self.tok()[0] == "comment":
            t = self.take()
            out.append(Comment(t[1], t[2]))

    def block(self):
        stmts = []
        while True:
            if self.marks is not None: self.marks.add(self.i)
            self.comments(stmts)
            t = self.tok()
            if t[0] == "eof" or (t[0] == "keyword" and t[1] in BLOCK_END):
                break
            start = self.i
            if t[0] == "keyword" and t[1] == "return":
                stmts.append(self.retstat())
            else:
                stmts.append(self.statement())
            if self.seen is not None: self.seen.append((start, self.i, stmts[-1]))
            if type(stmts[-1]) is Return:
                self.comments(stmts)
                break
        if self.marks is not None: self.marks.add(self.i)
        return Block(stmts, self.i)

    def retstat(self):
        line = self.take()[2]
        exprs = []
        t = self.tok()
        if not (t[0] in ("eof", "comment") or (t[0] == "keyword" and t[1] in BLOCK_END)
                or self.is_(";")):
            exprs = self.explist()
        semi = False
        if self.is_(";"):
            self.take(); semi = True
        return Return(exprs, semi, line)

    def statement(self):
        t = self.tok()
        k = t[1] if t[0] in ("op", "keyword") else None
        line = t[2]
        if k == ";":
            self.take(); return Semi(line)
        if k == "if":
            self.take()
            conds, blocks, orelse = [self.expr()], [], None
            self.expect("then"); blocks.append(self.block())
            while self.is_("elseif"):
                self.take(); conds.append(self.expr()); self.expect("then"); blocks.append(self.block())
            if self.is_("else"):
                self.take(); orelse = self.block()
            self.expect("end")
            return If(conds, blocks, orelse, line)
        if k == "while":
            self.take(); cond = self.expr(); self.expect("do")
            body = self.block(); self.expect("end")
            return While(cond, body, line)
        if k == "do":
            self.take(); body = self.block(); self.expect("end")
            return Do(body, line)
        if k == "for":
            self.take()
            n1 = self.name()
            if self.is_("="):
                self.take()
                start = self.expr(); self.expect(","); stop = self.expr(); step = None
                if self.is_(","):
                    self.take(); step = self.expr()
                self.expect("do"); body = self.block(); self.expect("end")
                return NumFor(n1, start, stop, step, body, line)
            names = [n1]
            while self.is_(","):
                self.take(); names.append(self.name())
            self.expect("in"); exprs = self.explist(); self.expect("do")
            body = self.block(); self.expect("end")
            return GenFor(names, exprs, body, line)
        if k == "repeat":
            self.take(); body = self.block(); self.expect("until"); cond = self.expr()
            return Repeat(body, cond, line, self.i)
        if k == "function":
            kw = self.i; self.take()
            base = self.name(); path = []; method = None
            while self.is_("."):
                self.take(); n = self.name(); path.append((n.name, n.line))
            if self.is_(":"):
                self.take(); n = self.name(); method = (n.name, n.line)
            func = self.funcbody(line, method is not None, kw)
            return FuncStat(base, path, method, func, line)
        if k == "local":
            self.take()
            if self.is_("function"):
                kw = self.i; self.take(); n = self.name(); func = self.funcbody(line, False, kw)
                return LocalFunc(n, func, line)
            names = [self.name()]
            while self.is_(","):
                self.take(); names.append(self.name())
            exprs = []
            if self.is_("="):
                self.take(); exprs = self.explist()
            return Local(names, exprs, line)
        if k == "::":
            self.take(); n = self.name(); self.expect("::")
            return Label(n.name, line)
        if k == "break":
            self.take(); return Break(line)
        if k == "goto":
            self.take(); n = self.name(); return Goto(n.name, line)
        e = self.suffixedexp()
        if self.is_("=") or self.is_(","):
            targets = [e]
            while self.is_(","):
                self.take(); targets.append(self.suffixedexp())
            self.expect("=")
            exprs = self.explist()
            for tg in targets:
                if not isinstance(tg, (Name, Index, Field)):
                    self.err("syntax error (cannot assign)")
            return Assign(targets, exprs, line)
        if not isinstance(e, (Call, Method)):
            self.err("syntax error")
        return CallStat(e, line)

    def funcbody(self, line, is_method=False, kw=None):
        t = self.tok()
        if t[0] == "raw":                     # a NOMINIFY-protected body, kept verbatim
            self.i += 1
            f = Func([], False, Block([], self.i), line, t[2] + t[1].count("\n"), is_method)
            f.raw = t[1]
            return f
        paren = self.i
        self.expect("(")
        params, vararg = [], False
        if not self.is_(")"):
            while True:
                if self.is_("..."):
                    self.take(); vararg = True; break
                params.append(self.name())
                if not self.is_(","):
                    break
                self.take()
        self.expect(")")
        body = self.block()
        end_line = self.expect("end")[2]
        f = Func(params, vararg, body, line, end_line, is_method)
        f.kw, f.toks = kw, (paren, self.i - 1)
        if self.funcs is not None: self.funcs.append(f)
        return f

    def explist(self):
        es = [self.expr()]
        while self.is_(","):
            self.take(); es.append(self.expr())
        return es

    def expr(self):
        return self.subexpr(0)

    def subexpr(self, limit):
        t = self.tok()
        if t[0] in ("keyword", "op") and t[1] in ("not", "-", "#", "~"):
            self.i += 1
            e = Un(t[1], self.subexpr(UNARY_PRI), t[2])
        else:
            e = self.simpleexp()
        while True:
            t = self.tok()
            if t[0] in ("keyword", "op") and t[1] in BINPRI and BINPRI[t[1]][0] > limit:
                self.i += 1
                e = Bin(t[1], e, self.subexpr(BINPRI[t[1]][1]), t[2])
            else:
                return e

    def simpleexp(self):
        t = self.tok()
        if t[0] == "number":
            self.i += 1; return Lit("number", t[1], t[2])
        if t[0] == "string":
            self.i += 1; return Lit("string", t[1], t[2])
        if t[0] == "keyword" and t[1] in ("nil", "true", "false"):
            self.i += 1; return Lit(t[1], t[1], t[2])
        if t[0] == "op" and t[1] == "...":
            self.i += 1; return Lit("vararg", "...", t[2])
        if t[0] == "op" and t[1] == "{":
            return self.table()
        if t[0] == "keyword" and t[1] == "function":
            self.i += 1; return self.funcbody(t[2], False, self.i - 1)
        return self.suffixedexp()

    def primaryexp(self):
        t = self.tok()
        if t[0] == "name":
            return self.name()
        if self.is_("("):
            self.take(); e = self.expr(); self.expect(")")
            return Paren(e, t[2])
        self.err("unexpected symbol")

    def suffixedexp(self):
        e = self.primaryexp()
        while True:
            t = self.tok()
            if self.is_("."):
                self.take(); n = self.name(); e = Field(e, n.name, n.line)
            elif self.is_("["):
                self.take(); k = self.expr(); self.expect("]"); e = Index(e, k, t[2])
            elif self.is_(":"):
                self.take(); n = self.name(); args, form = self.callargs()
                e = Method(e, n.name, args, form, n.line)
            elif self.is_("(") or self.is_("{") or t[0] == "string":
                args, form = self.callargs()
                e = Call(e, args, form, t[2])
            else:
                return e

    def callargs(self):
        t = self.tok()
        if t[0] == "string":
            self.i += 1; return [Lit("string", t[1], t[2])], "str"
        if self.is_("{"):
            return [self.table()], "tbl"
        self.expect("(")
        args = [] if self.is_(")") else self.explist()
        self.expect(")")
        return args, "("

    def table(self):
        line = self.expect("{")[2]
        fields = []
        while True:
            if self.marks is not None: self.marks.add(self.i)
            while self.tok()[0] == "comment":
                t = self.take()
                fields.append(["comment", Comment(t[1], t[2]), None, None])
            if self.is_("}"):
                break
            if self.is_("["):
                self.take(); k = self.expr(); self.expect("]"); self.expect("=")
                f = ["index", k, self.expr(), None]
            elif self.tok()[0] == "name" and self.i + 1 < self.n and self.t[self.i + 1][:2] == ("op", "="):
                n = self.name(); self.take()
                f = ["named", (n.name, n.line), self.expr(), None]
            else:
                f = ["pos", None, self.expr(), None]
            fields.append(f)
            if self.is_(",") or self.is_(";"):
                f[3] = self.take()[1]
            else:
                if self.marks is not None: self.marks.add(self.i)
                while self.tok()[0] == "comment":
                    t = self.take()
                    fields.append(["comment", Comment(t[1], t[2]), None, None])
                break
        self.expect("}")
        return Table(fields, line)


def parse(toks):
    return Parser(toks).chunk()


# ------------------------------------------------------------------ emission

NL = ("nl", "", 0)   # layout marker: a function-start statement begins here

class Emitter:
    def __init__(self):
        self.out = []

    def kw(self, text, line): self.out.append(("keyword", text, line))
    def op(self, text, line): self.out.append(("op", text, line))

    def block(self, b):
        for s in b.stmts:
            self.stmt(s)

    def names(self, ns, line):
        for i, n in enumerate(ns):
            if i: self.op(",", line)
            self.out.append(("name", n.name, n.line))

    def exprs(self, es, line):
        for i, e in enumerate(es):
            if i: self.op(",", line)
            self.expr(e)

    def stmt(self, s):
        t = type(s); L = s.line
        if t is Local:
            if s.exprs and type(s.exprs[0]) is Func: self.out.append(NL)
            self.kw("local", L); self.names(s.names, L)
            if s.exprs:
                self.op("=", L); self.exprs(s.exprs, L)
        elif t is Assign:
            if type(s.exprs[0]) is Func: self.out.append(NL)
            self.exprs(s.targets, L); self.op("=", L); self.exprs(s.exprs, L)
        elif t is CallStat:
            self.expr(s.call)
        elif t is LocalFunc:
            self.out.append(NL); self.kw("local", L); self.kw("function", L)
            self.out.append(("name", s.name.name, s.name.line)); self.funcbody(s.func)
        elif t is FuncStat:
            self.out.append(NL); self.kw("function", L)
            self.out.append(("name", s.base.name, s.base.line))
            for f, fl in s.path:
                self.op(".", fl); self.out.append(("name", f, fl))
            if s.method:
                self.op(":", s.method[1]); self.out.append(("name", s.method[0], s.method[1]))
            self.funcbody(s.func)
        elif t is If:
            for i, (c, b) in enumerate(zip(s.conds, s.blocks)):
                self.kw("if" if i == 0 else "elseif", L); self.expr(c); self.kw("then", L); self.block(b)
            if s.orelse is not None:
                self.kw("else", L); self.block(s.orelse)
            self.kw("end", L)
        elif t is While:
            self.kw("while", L); self.expr(s.cond); self.kw("do", L); self.block(s.body); self.kw("end", L)
        elif t is Do:
            self.kw("do", L); self.block(s.body); self.kw("end", L)
        elif t is NumFor:
            self.kw("for", L); self.out.append(("name", s.var.name, s.var.line)); self.op("=", L)
            self.expr(s.start); self.op(",", L); self.expr(s.stop)
            if s.step is not None:
                self.op(",", L); self.expr(s.step)
            self.kw("do", L); self.block(s.body); self.kw("end", L)
        elif t is GenFor:
            self.kw("for", L); self.names(s.names, L); self.kw("in", L); self.exprs(s.exprs, L)
            self.kw("do", L); self.block(s.body); self.kw("end", L)
        elif t is Repeat:
            self.kw("repeat", L); self.block(s.body); self.kw("until", L); self.expr(s.cond)
        elif t is Return:
            self.kw("return", L); self.exprs(s.exprs, L)
            if s.semi: self.op(";", L)
        elif t is Break:
            self.kw("break", L)
        elif t is Goto:
            self.kw("goto", L); self.out.append(("name", s.name, L))
        elif t is Label:
            self.op("::", L); self.out.append(("name", s.name, L)); self.op("::", L)
        elif t is Semi:
            self.op(";", L)
        elif t is Comment:
            self.out.append(("comment", s.text, L))
        else:
            raise TypeError(t)

    def funcbody(self, f):
        if f.raw is not None:
            self.out.append(("raw", f.raw, f.raw.line)); return
        L = f.line
        self.op("(", L)
        self.names(f.params, L)
        if f.vararg:
            if f.params: self.op(",", L)
            self.op("...", L)
        self.op(")", L)
        self.block(f.body)
        self.kw("end", f.end_line)

    def args(self, e):
        if e.form == "(":
            self.op("(", e.line); self.exprs(e.args, e.line); self.op(")", e.line)
        else:
            self.expr(e.args[0])

    def expr(self, e):
        t = type(e)
        if t is Name:
            self.out.append(("name", e.name, e.line))
        elif t is Lit:
            k = e.kind
            if k == "number" or k == "string": self.out.append((k, e.text, e.line))
            elif k == "vararg": self.op("...", e.line)
            else: self.kw(e.text, e.line)
        elif t is Bin:
            self.expr(e.a)
            (self.kw if e.op in ("and", "or") else self.op)(e.op, e.line)
            self.expr(e.b)
        elif t is Un:
            (self.kw if e.op == "not" else self.op)(e.op, e.line); self.expr(e.a)
        elif t is Paren:
            self.op("(", e.line); self.expr(e.e); self.op(")", e.line)
        elif t is Field:
            self.expr(e.obj); self.op(".", e.line); self.out.append(("name", e.name, e.line))
        elif t is Index:
            self.expr(e.obj); self.op("[", e.line); self.expr(e.key); self.op("]", e.line)
        elif t is Call:
            self.expr(e.fn); self.args(e)
        elif t is Method:
            self.expr(e.obj); self.op(":", e.line); self.out.append(("name", e.name, e.line)); self.args(e)
        elif t is Func:
            self.kw("function", e.line); self.funcbody(e)
        elif t is Table:
            self.op("{", e.line)
            for kind, key, val, sep in e.fields:
                if kind == "comment":
                    self.out.append(("comment", key.text, key.line)); continue
                if kind == "index":
                    self.op("[", e.line); self.expr(key); self.op("]", e.line); self.op("=", e.line)
                elif kind == "named":
                    self.out.append(("name", key[0], key[1])); self.op("=", key[1])
                self.expr(val)
                if sep: self.op(sep, e.line)
            self.op("}", e.line)
        else:
            raise TypeError(t)

def emit_tree(node):
    em = Emitter()
    if isinstance(node, Block): em.block(node)
    else: em.expr(node)
    return em.out

def strip_nl(toks):
    return [t for t in toks if t[0] != "nl"]

def reparse(toks, check=True):
    """Parse a token list and prove the tree re-emits exactly those tokens."""
    prog = parse(toks)
    if check:
        back = strip_nl(emit_tree(prog))
        if [t[:2] for t in back] != [t[:2] for t in toks]:
            for k, (a, b) in enumerate(zip(back, toks)):
                if a[:2] != b[:2]:
                    raise AssertionError(f"minify: parser is not lossless at token {k} "
                                         f"(line {b[2]}): {b[1]!r} re-emitted as {a[1]!r}")
            raise AssertionError("minify: parser is not lossless (token count differs)")
    return prog


# =============================================================================
# Lua 5.3 values and constant evaluation (spec D7)
# =============================================================================

MASK64 = (1 << 64) - 1
MAXINT, MININT = (1 << 63) - 1, -(1 << 63)

class NoFold(Exception):
    pass

FALSY = ("falsy", None)   # truthiness known to be false, value unknown

def wrap(i):
    i &= MASK64
    return i - (1 << 64) if i >> 63 else i

def num_value(text):
    t = text.lower()
    if t.startswith("0x"):
        if "." in t or "p" in t:
            if t.endswith("."): t += "0"
            return ("float", float.fromhex(t))
        return ("int", wrap(int(t, 16)))
    if "." in t or "e" in t:
        return ("float", float(t))
    v = int(t)
    return ("int", v) if v <= MAXINT else ("float", float(t))

_ESC = {"a": 7, "b": 8, "f": 12, "n": 10, "r": 13, "t": 9, "v": 11, "\\": 92, '"': 34, "'": 39}

def str_value(text):
    """Bytes of a Lua string literal, or None for an escape we do not model."""
    if text[0] == "[":
        lvl = text.index("[", 1) - 1
        body = text[lvl + 2: len(text) - lvl - 2]
        body = re.sub(r"\r\n|\n\r|\r", "\n", body)
        if body.startswith("\n"): body = body[1:]
        return body.encode("utf-8")
    raw, out, i = text[1:-1], bytearray(), 0
    while i < len(raw):
        c = raw[i]
        if c != "\\":
            out += c.encode("utf-8"); i += 1; continue
        i += 1
        c = raw[i]
        if c in _ESC:
            out.append(_ESC[c]); i += 1
        elif c == "\n" or c == "\r":
            out.append(10); i += 1
            if i < len(raw) and raw[i] in "\r\n" and raw[i] != c: i += 1
        elif c == "x":
            out.append(int(raw[i + 1:i + 3], 16)); i += 3
        elif c == "z":
            i += 1
            while i < len(raw) and raw[i] in " \t\r\n\f\v": i += 1
        elif c.isdigit():
            m = re.match(r"[0-9]{1,3}", raw[i:]).group()
            if int(m) > 255: return None
            out.append(int(m)); i += len(m)
        elif c == "u":
            m = re.match(r"\{([0-9a-fA-F]+)\}", raw[i + 1:])
            if not m or int(m.group(1), 16) > 0x10FFFF: return None
            out += chr(int(m.group(1), 16)).encode("utf-8", "surrogatepass"); i += 1 + len(m.group())
        else:
            return None
    return bytes(out)

def lit_value(e):
    k = e.kind
    if k == "number": return num_value(e.text)
    if k == "string":
        b = str_value(e.text)
        return ("str", b) if b is not None else None
    if k == "nil": return ("nil", None)
    if k == "true": return ("bool", True)
    if k == "false": return ("bool", False)
    return None

def truthy(v):
    return not (v is FALSY or v[0] == "nil" or (v[0] == "bool" and not v[1]))

def _num(v):
    if v[0] not in ("int", "float"): raise NoFold()
    return v

def _toint(v):
    if v[0] == "int": return v[1]
    if v[0] == "float" and v[1].is_integer() and -2.0 ** 63 <= v[1] < 2.0 ** 63:
        return int(v[1])
    raise NoFold()

def _fl(x):
    if math.isinf(x) or math.isnan(x): raise NoFold()
    return ("float", x)

def _shl(a, b):
    if b <= -64 or b >= 64: return 0
    if b >= 0: return wrap((a & MASK64) << b)
    return wrap((a & MASK64) >> -b)

def lua_tostring_num(v):
    if v[0] == "int": return str(v[1]).encode()
    s = "%.14g" % v[1]
    if all(ch in "-0123456789" for ch in s): s += ".0"
    return s.encode()

def binop(op, a, b):
    if a is FALSY or b is FALSY: raise NoFold()
    if op == "..":
        def cs(v):
            if v[0] == "str": return v[1]
            if v[0] in ("int", "float"): return lua_tostring_num(v)
            raise NoFold()
        return ("str", cs(a) + cs(b))
    if op in ("==", "~="):
        if a[0] in ("int", "float") and b[0] in ("int", "float"): eq = a[1] == b[1]
        else: eq = a[0] == b[0] and a[1] == b[1]
        return ("bool", eq if op == "==" else not eq)
    if op in ("<", "<=", ">", ">="):
        _num(a); _num(b)
        x, y = a[1], b[1]
        return ("bool", {"<": x < y, "<=": x <= y, ">": x > y, ">=": x >= y}[op])
    if op in ("&", "|", "~", "<<", ">>"):
        x, y = _toint(a), _toint(b)
        if op == "&": return ("int", wrap(x & y))
        if op == "|": return ("int", wrap(x | y))
        if op == "~": return ("int", wrap(x ^ y))
        if op == "<<": return ("int", _shl(x, y))
        return ("int", _shl(x, -y))
    _num(a); _num(b)
    if op in ("+", "-", "*") and a[0] == "int" and b[0] == "int":
        x, y = a[1], b[1]
        return ("int", wrap(x + y if op == "+" else x - y if op == "-" else x * y))
    if op in ("//", "%") and a[0] == "int" and b[0] == "int":
        if b[1] == 0: raise NoFold()
        return ("int", wrap(a[1] // b[1] if op == "//" else a[1] % b[1]))
    x, y = float(a[1]), float(b[1])
    try:
        if op == "+": return _fl(x + y)
        if op == "-": return _fl(x - y)
        if op == "*": return _fl(x * y)
        if op == "/":
            if y == 0: raise NoFold()
            return _fl(x / y)
        if op == "//":
            if y == 0: raise NoFold()
            return _fl(float(math.floor(x / y)))
        if op == "%":
            if y == 0 or math.isinf(x) or math.isinf(y): raise NoFold()
            m = math.fmod(x, y)
            if m * y < 0: m += y
            return _fl(m)
        if op == "^": return _fl(math.pow(x, y))
    except (OverflowError, ValueError, ZeroDivisionError):
        raise NoFold()
    raise NoFold()

def unop(op, a):
    if op == "not":
        return ("bool", not truthy(a))
    if a is FALSY: raise NoFold()
    if op == "-":
        if a[0] == "int": return ("int", wrap(-a[1]))
        if a[0] == "float": return ("float", -a[1])
        raise NoFold()
    if op == "~": return ("int", wrap(~_toint(a)))
    if op == "#":
        if a[0] == "str": return ("int", len(a[1]))
        raise NoFold()
    raise NoFold()

# ------------------------------------------------------------ literal output

def int_text(v):
    d, h = str(v), "0x%x" % v
    return h if len(h) < len(d) else d

def float_text(v):
    """Shortest Lua numeral that reads back as exactly this (non-negative) double."""
    sign, digits, exp = Decimal(repr(v)).normalize().as_tuple() if v else (0, (0,), 0)
    D = "".join(map(str, digits))
    cands = []
    if exp >= 0:
        cands.append(D + "0" * exp + ".")
    else:
        k = len(D) + exp
        cands.append((D[:k] + "." + D[k:]) if k > 0 else ("." + "0" * -k + D))
    cands.append(f"{D}e{exp}")
    if len(D) > 1:
        cands.append(f"{D[0]}.{D[1:]}e{exp + len(D) - 1}")
    best = None
    for c in cands:
        try:
            ok = float(c) == v
        except ValueError:
            ok = False
        if ok and ("." in c or "e" in c) and (best is None or len(c) < len(best)):
            best = c
    return best

_NAMED_ESC = {7: "\\a", 8: "\\b", 12: "\\f", 10: "\\n", 13: "\\r", 9: "\\t", 11: "\\v", 92: "\\\\"}

def str_text(b):
    """Shortest quoted Lua literal for the bytes b (raw UTF-8 kept when valid)."""
    try:
        units = list(b.decode("utf-8"))              # characters
    except UnicodeDecodeError:
        units = [x if x >= 128 else chr(x) for x in b]   # ints = raw high bytes
    best = None
    for q in ('"', "'"):
        pieces = []                                  # (text, is_decimal_escape)
        for u in units:
            if isinstance(u, int):
                pieces.append(("\\%d" % u, True)); continue
            c = ord(u)
            if c in _NAMED_ESC: pieces.append((_NAMED_ESC[c], False))
            elif u == q: pieces.append(("\\" + q, False))
            elif c < 32 or c == 127: pieces.append(("\\%d" % c, True))
            else: pieces.append((u, False))
        out = []
        for i, (p, dec) in enumerate(pieces):
            if dec and i + 1 < len(pieces) and pieces[i + 1][0][:1].isdigit():
                p = "\\%03d" % int(p[1:])            # keep a following digit out of the escape
            out.append(p)
        t = q + "".join(out) + q
        if best is None or len(t) < len(best):
            best = t
    return best

def value_lit(v, line):
    """Literal node(s) for a value: (node, negative) or None when unwritable."""
    k = v[0]
    if k == "nil": return Lit("nil", "nil", line), False
    if k == "bool": return (Lit("true", "true", line) if v[1] else Lit("false", "false", line)), False
    if k == "str": return Lit("string", str_text(v[1]), line), False
    if k == "int":
        if v[1] == MININT: return None
        if v[1] < 0: return Un("-", Lit("number", int_text(-v[1]), line), line), True
        return Lit("number", int_text(v[1]), line), False
    if k == "float":
        x = v[1]
        if math.isinf(x) or math.isnan(x): return None
        if x < 0 or (x == 0 and math.copysign(1, x) < 0):
            t = float_text(-x)
            return (Un("-", Lit("number", t, line), line), True) if t else None
        t = float_text(x)
        return (Lit("number", t, line), False) if t else None
    return None

def value_text_len(v):
    r = value_lit(v, 0)
    if r is None: return None
    return sum(len(t[1]) for t in emit_tree(r[0]))


# =============================================================================
# Scope resolution and whole-program facts
# =============================================================================

MULTI, NILV, PARAM, FORV = "MULTI", "NILV", "PARAM", "FORV"

class W:
    __slots__ = ("kind", "value", "chunk", "idx", "top", "stmt", "name")
    def __init__(s, kind, value, chunk, idx, top, stmt, name=None):
        s.kind, s.value, s.chunk, s.idx, s.top, s.stmt, s.name = kind, value, chunk, idx, top, stmt, name

class Binding:
    def __init__(s, name, kind):
        s.name, s.kind = name, kind              # kind: local | global
        s.occ, s.reads, s.writes = [], [], []
        s.top_reads = []                          # globals: (chunk, idx, line)
        s.fctx = None; s.start = s.end = -1
        s.reserved = False; s.is_function = False; s.renamable = False
        s.can_rename = False                      # renamable once functions are (rename-functions)
        s.implicit = False                        # method's implicit self
        s.cval = None; s.truth = None; s.inline = False
        s.live = False; s.deferred = []; s.newname = None
        s.wlines = []                             # lines it is declared/assigned on
        s.pinned = False                          # used inside a NOMINIFY-protected body
        s.nomi = None                             # line of the NOMINIFY that keeps it

class FCtx:
    def __init__(s, node, chunk, is_chunk, parent):
        s.node, s.chunk, s.is_chunk, s.parent = node, chunk, is_chunk, parent
        s.labels, s.gotos = [], []

class Scope:
    def __init__(s, parent, fctx, depth, end):
        s.parent, s.fctx, s.depth, s.end = parent, fctx, depth, end
        s.vars, s.labels = {}, {}

def is_multi(e):
    return type(e) in (Call, Method) or (type(e) is Lit and e.kind == "vararg")

def pair_values(nt, exprs):
    ne, vals = len(exprs), []
    for i in range(nt):
        if i < ne: vals.append(exprs[i])
        elif ne and is_multi(exprs[-1]): vals.append(MULTI)
        else: vals.append(NILV)
    return vals

def preload_name(s):
    """Module name if s is `package.preload["m"] = function(...) ... end`."""
    if (type(s) is Assign and len(s.targets) == 1 and len(s.exprs) == 1
            and type(s.exprs[0]) is Func):
        t = s.targets[0]
        if (type(t) is Index and type(t.key) is Lit and t.key.kind == "string"
                and type(t.obj) is Field and t.obj.name == "preload"
                and type(t.obj.obj) is Name and t.obj.obj.name == "package"):
            v = str_value(t.key.text)
            return v.decode("utf-8", "replace") if v is not None else None
    return None

def require_target(e):
    """Module name for a literal require call, '' for a non-literal one, else None."""
    if type(e) is Call and type(e.fn) is Name and e.fn.name == "require" \
            and e.fn.b is not None and e.fn.b.kind == "global":
        if len(e.args) == 1 and type(e.args[0]) is Lit and e.args[0].kind == "string":
            v = str_value(e.args[0].text)
            return v.decode("utf-8", "replace") if v is not None else ""
        return ""
    return None


class Info:
    """Everything one resolution pass learns about the program."""

    def __init__(self, prog, whole, keep=frozenset(), rename_functions=False):
        """keep: {(line, name)} of the variables a NOMINIFY directive keeps
        (Directives.names); each binding declared or assigned there is
        pinned, and listed in self.kept as (name, line). rename_functions:
        function bindings (D11) are renamable too."""
        self.prog, self.whole = prog, whole
        self.rename_functions = rename_functions
        self.globals, self.locals = {}, []
        self.dynamic = None
        self.chunks = {"<main>": prog.stmts}
        self.preloads = {}                         # module -> (stmt, func)
        self.requires = {}                         # (chunk, idx) -> [module]
        self.funcs = []
        self.fctxs = []
        self.require_calls = 0                     # literal require "m" calls seen
        r = _Resolver(self)
        r.run()
        self.kept = []
        if keep:
            for b in list(self.globals.values()) + self.locals:
                hit = next((l for l in b.wlines if (l, b.name) in keep), None)
                if hit is not None:
                    b.pinned, b.nomi = True, hit
                    self.kept.append((b.name, hit))
        # `require` used any other way (pcall(require, m), local r = require, ...)
        # can load a module the literal scan never sees: keep every module and
        # trust no cross-module load order
        rq = self.globals.get("require")
        self.require_escapes = rq is not None and len(rq.reads) > self.require_calls
        self.stamps = self._timeline()
        if self.require_escapes:
            self.stamps = {k: v for k, v in self.stamps.items() if k[0] == "<main>"}
        self._classify()

    def global_(self, name):
        b = self.globals.get(name)
        if b is None:
            b = self.globals[name] = Binding(name, "global")
            b.reserved = name in RESERVED
        return b

    def _timeline(self):
        stamps, t, seen = {}, [0], {"<main>"}
        def run(chunk):
            for idx in range(len(self.chunks[chunk])):
                ts = t[0]; t[0] += 1
                for m in self.requires.get((chunk, idx), ()):
                    if m not in seen and m in self.chunks:
                        seen.add(m); run(m)
                stamps[(chunk, idx)] = (ts, t[0]); t[0] += 1
        run("<main>")
        return stamps

    def read_safe(self, w, r):
        """Can a top-level read r=(chunk, idx, line) see write w?"""
        a, b = self.stamps.get((w.chunk, w.idx)), self.stamps.get((r[0], r[1]))
        if a and b:
            return a[1] < b[0]
        return r[0] == w.chunk and r[1] > w.idx

    def _classify(self):
        for b in list(self.globals.values()) + self.locals:
            b.is_function = any(type(w.value) is Func for w in b.writes)
            if b.kind == "local":
                b.can_rename = not b.implicit and not b.pinned
            else:
                b.can_rename = (self.whole and self.dynamic is None and not b.reserved
                                and not b.pinned)
            b.renamable = b.can_rename and (self.rename_functions or not b.is_function)


class _Resolver:
    def __init__(self, info):
        self.info = info
        self.scope = None
        self.fctx = None
        self.top_idx = 0

    def run(self):
        prog = self.info.prog
        self.fctx = FCtx(None, "<main>", True, None)
        self.info.fctxs.append(self.fctx)
        self.block(prog, prog.end_pos, func_body=True)

    # ---- scopes
    def push(self, end, func_body=False):
        depth = 0 if func_body else self.scope.depth + 1
        self.scope = Scope(self.scope, self.fctx, depth, end)

    def pop(self):
        self.scope = self.scope.parent

    def lookup(self, name):
        s = self.scope
        while s is not None:
            b = s.vars.get(name)
            if b is not None: return b
            s = s.parent
        return None

    def declare(self, n, w):
        b = Binding(n.name, "local")
        b.fctx, b.start, b.end = self.fctx, n.pos, self.scope.end
        b.occ.append(n); n.b = b
        b.wlines.append(n.line)
        if w is not None: b.writes.append(w)
        self.scope.vars[n.name] = b
        self.info.locals.append(b)
        if n.name == "_ENV" and self.info.dynamic is None:
            self.info.dynamic = f"line {n.line}: local _ENV"
        return b

    def W(self, kind, value, stmt, name=None):
        f = self.fctx
        return W(kind, value, f.chunk, self.top_idx, f.is_chunk and self.scope.depth == 0, stmt, name)

    def ref(self, n, w=None):
        b = self.lookup(n.name)
        if b is None:
            b = self.info.global_(n.name)
            if n.name in DYNAMIC_NAMES and self.info.dynamic is None:
                self.info.dynamic = f"line {n.line}: {n.name}"
        n.b = b
        b.occ.append(n)
        if w is None:
            b.reads.append(n)
            if b.kind == "global" and self.fctx.is_chunk:
                b.top_reads.append((self.fctx.chunk, self.top_idx, n.line))
        else:
            b.writes.append(w)
            b.wlines.append(n.line)
        if b.kind == "local" and b.fctx is not self.fctx:
            f = self.fctx
            while f is not None and f is not b.fctx:
                if f.node is not None: f.node.upvals.add(b)
                f = f.parent
        return b

    # ---- statements
    def block(self, blk, end, func_body=False, tail=None):
        self.push(end, func_body)
        for s in blk.stmts:
            if type(s) is Label:
                self.scope.labels[s.name] = s
                self.fctx.labels.append(s)
        chunk_top = func_body and self.fctx.is_chunk
        for i, s in enumerate(blk.stmts):
            if chunk_top: self.top_idx = i
            self.stmt(s)
        if tail is not None:
            self.expr(tail)
        self.pop()

    def stmt(self, s):
        t = type(s)
        if t is Local:
            for e in s.exprs: self.expr(e)
            for n, v in zip(s.names, pair_values(len(s.names), s.exprs)):
                self.declare(n, self.W("local", v, s))
        elif t is Assign:
            m = preload_name(s) if self.fctx.node is None and self.scope.depth == 0 else None
            if m is not None:
                s.exprs[0].chunk = m
                self.info.preloads[m] = (s, s.exprs[0])
                self.info.chunks[m] = s.exprs[0].body.stmts
            for e in s.exprs: self.expr(e)
            for tg, v in zip(s.targets, pair_values(len(s.targets), s.exprs)):
                if type(tg) is Name: self.ref(tg, self.W("assign", v, s))
                else: self.expr(tg)
        elif t is CallStat:
            self.expr(s.call)
        elif t is LocalFunc:
            self.declare(s.name, self.W("localfunc", s.func, s))
            self.func(s.func)
        elif t is FuncStat:
            if not s.path and not s.method:
                self.ref(s.base, self.W("func", s.func, s))
            else:
                self.ref(s.base)
            self.func(s.func)
        elif t is If:
            for c, b in zip(s.conds, s.blocks):
                self.expr(c); self.block(b, b.end_pos)
            if s.orelse is not None: self.block(s.orelse, s.orelse.end_pos)
        elif t is While:
            self.expr(s.cond); self.block(s.body, s.body.end_pos)
        elif t is Do:
            self.block(s.body, s.body.end_pos)
        elif t is Repeat:
            self.block(s.body, s.end_pos, tail=s.cond)
        elif t is NumFor:
            self.expr(s.start); self.expr(s.stop)
            if s.step is not None: self.expr(s.step)
            self.push(s.body.end_pos)
            self.declare(s.var, self.W("for", FORV, s))
            self.block(s.body, s.body.end_pos)
            self.pop()
        elif t is GenFor:
            for e in s.exprs: self.expr(e)
            self.push(s.body.end_pos)
            for n in s.names: self.declare(n, self.W("for", FORV, s))
            self.block(s.body, s.body.end_pos)
            self.pop()
        elif t is Return:
            for e in s.exprs: self.expr(e)
        elif t is Goto:
            sc = self.scope
            while sc is not None and sc.fctx is self.fctx:
                if s.name in sc.labels:
                    s.label = sc.labels[s.name]; break
                sc = sc.parent
            self.fctx.gotos.append(s)

    def func(self, f):
        if f.raw is not None:
            # A protected body is opaque: every name it uses is a reference
            # from here, and those bindings are pinned (never renamed, inlined,
            # aliased or removed) - it may read or write any of them.
            f.raw_bindings = []
            for name in sorted(f.raw.refs):
                n = Name(name, f.raw.line, -1)
                self.ref(n)
                n.b.pinned = True
                f.raw_bindings.append(n.b)
            return
        saved = (self.fctx, self.top_idx)
        self.fctx = FCtx(f, f.chunk or self.fctx.chunk, f.chunk is not None, self.fctx)
        self.info.fctxs.append(self.fctx)
        self.info.funcs.append(f)
        self.push(f.body.end_pos, func_body=True)
        self.scope.depth = -1                       # parameter scope; body is depth 0
        if f.is_method:
            b = Binding("self", "local")
            b.fctx, b.implicit = self.fctx, True
            self.scope.vars["self"] = b
            self.info.locals.append(b)
            f.self_b = b
        for p in f.params:
            self.declare(p, self.W("param", PARAM, None))
        self.block(f.body, f.body.end_pos, func_body=True)
        self.pop()
        self.fctx, self.top_idx = saved

    # ---- expressions
    def expr(self, e):
        t = type(e)
        if t is Name:
            self.ref(e)
        elif t is Bin:
            self.expr(e.a); self.expr(e.b)
        elif t is Un:
            self.expr(e.a)
        elif t is Paren:
            self.expr(e.e)
        elif t is Field:
            self.expr(e.obj)
        elif t is Index:
            self.expr(e.obj); self.expr(e.key)
        elif t is Call:
            self.expr(e.fn)
            for a in e.args: self.expr(a)
            m = require_target(e)
            if m == "":
                if self.info.dynamic is None:
                    self.info.dynamic = f"line {e.line}: non-literal require"
            elif m is not None:
                self.info.require_calls += 1
                if self.fctx.is_chunk:
                    self.info.requires.setdefault((self.fctx.chunk, self.top_idx), []).append(m)
        elif t is Method:
            self.expr(e.obj)
            for a in e.args: self.expr(a)
        elif t is Func:
            self.func(e)
        elif t is Table:
            for kind, key, val, sep in e.fields:
                if kind == "index": self.expr(key)
                if kind != "comment": self.expr(val)


# =============================================================================
# Constant analysis (spec D8, D9)
# =============================================================================

def const_eval(e, depth=0):
    t = type(e)
    if t is Lit:
        return lit_value(e)
    if t is Name:
        b = e.b
        if b is None: return None
        if b.cval is not None: return b.cval
        if b.truth is False: return FALSY
        return None
    if t is Paren:
        return const_eval(e.e, depth)
    try:
        if t is Un:
            a = const_eval(e.a, depth)
            return None if a is None else unop(e.op, a)
        if t is Bin:
            a = const_eval(e.a, depth)
            if e.op in ("and", "or"):
                if a is None: return None
                if (e.op == "and") != truthy(a): return a
                return const_eval(e.b, depth)
            if a is None: return None
            b = const_eval(e.b, depth)
            return None if b is None else binop(e.op, a, b)
    except NoFold:
        return None
    return None

def analyze_constants(info, report=None):
    """Set cval / truth on bindings. Returns {name: reason} for failed UPPER_CASE names."""
    whole_g = info.whole and info.dynamic is None
    reasons, cands = {}, []
    for b in list(info.globals.values()) + info.locals:
        b.cval = b.truth = None
        b.inline = False
    for b in list(info.globals.values()) + info.locals:
        if b.reserved or b.implicit or b.is_function or b.pinned:
            continue
        if b.kind == "global" and not whole_g:
            continue
        if b.kind == "global" and not b.writes:
            b.cval = ("nil", None)                 # never written anywhere: always nil
            continue
        why = None
        if len(b.writes) != 1:
            why = f"{len(b.writes)} writes"
        else:
            w = b.writes[0]
            if b.kind == "local" and w.kind != "local":
                why = f"bound by {w.kind}"
            elif b.kind == "global" and not (w.kind == "assign" and w.top):
                why = "not a top-level assignment"
            elif w.value in (MULTI, PARAM, FORV):
                why = "value from a multiple-value expression"
            elif b.kind == "global":
                for r in b.top_reads:
                    if not info.read_safe(w, r):
                        why = f"read at line {r[2]} may run before the write"
                        break
        if why is None:
            cands.append(b)
        elif UPPER_RE.match(b.name):
            reasons.setdefault(b.name, why)
    changed = True
    while changed:
        changed = False
        for b in cands:
            if b.cval is not None: continue
            v = b.writes[0].value
            val = ("nil", None) if v is NILV else const_eval(v)
            if val is not None and val is not FALSY:
                b.cval = val; changed = True
        # always-falsy (D9) bindings, for conditions
        for b in list(info.globals.values()) + info.locals:
            if b.cval is not None or b.truth is not None or b.reserved or b.implicit \
                    or b.pinned:
                continue
            if b.kind == "global" and not whole_g: continue
            if not b.writes or b.is_function: continue
            ok = True
            for w in b.writes:
                v = w.value
                if v is NILV: continue
                if v in (MULTI, PARAM, FORV) or v is None: ok = False; break
                cv = const_eval(v)
                if cv is None or (cv is not FALSY and truthy(cv)): ok = False; break
            if ok:
                b.truth = False; changed = True
    for b in cands:
        if b.cval is None and UPPER_RE.match(b.name):
            v = b.writes[0].value
            reasons.setdefault(b.name, "value is not a constant scalar"
                               + (" (table)" if type(v) is Table else
                                  " (call)" if type(v) in (Call, Method) else ""))
    return reasons


# =============================================================================
# Pass: fold + inline + dead-code removal (spec R4, R5, R6)
# =============================================================================

def cost(node):
    n = 0
    for k, t, _ in emit_tree(node):
        n += len(t)
    return n

def cost_est(node, info):
    """Emitted length with renamable names counted at their expected new length."""
    n = 0
    stack = [node]
    for k, t, _ in emit_tree(node):
        n += len(t)
    # Names: subtract the difference for renamable bindings
    def walk(e):
        nonlocal n
        if type(e) is Name:
            if e.b is not None and e.b.renamable and len(e.name) > NAME_EST:
                n -= len(e.name) - NAME_EST
            return
        for c in children_expr(e): walk(c)
    walk(node)
    return n

def children_expr(e):
    t = type(e)
    if t is Bin: return (e.a, e.b)
    if t in (Un,): return (e.a,)
    if t is Paren: return (e.e,)
    if t is Field: return (e.obj,)
    if t is Index: return (e.obj, e.key)
    if t is Call: return (e.fn,) + tuple(e.args)
    if t is Method: return (e.obj,) + tuple(e.args)
    if t is Table:
        out = []
        for kind, key, val, sep in e.fields:
            if kind == "index": out.append(key)
            if kind != "comment": out.append(val)
        return out
    return ()

def is_atom_lit(e):
    return type(e) is Lit and e.kind in ("number", "string", "nil", "true", "false")


class Folder:
    def __init__(self, info, enable, report, inline_all, renaming=True):
        self.info, self.report = info, report
        self.do_fold, self.do_inline, self.do_dce = enable
        self.changes = 0
        if self.do_inline:
            for b in list(info.globals.values()) + info.locals:
                if b.cval is None or not b.reads: continue
                L = value_text_len(b.cval)
                if L is None: continue
                R = len(b.reads)
                # a read costs the name's length after renaming - its own
                # length when the rename-vars option is off
                N = NAME_EST if renaming else len(b.name)
                decl = 0 if (b.kind == "global" and not b.writes) else N + 1 + L + 1
                b.inline = inline_all or L * R <= decl + R * N
                if b.inline and not (b.kind == "global" and not b.writes):
                    report.inlined[(b.name, b.occ[0].line)] = (b.kind, value_repr(b.cval), R)
                    report.kept.pop((b.name, b.occ[0].line), None)
                elif not b.inline and b.cval[0] in ("str", "float", "int"):
                    report.kept[(b.name, b.occ[0].line)] = (value_repr(b.cval), R)

    def lit_for(self, v, line, ctx):
        r = value_lit(v, line)
        if r is None: return None
        node, neg = r
        if ctx == "prefix" or (neg and ctx == "powleft"):
            node = Paren(node, line)
        return node

    def expr(self, e, ctx=None):
        t = type(e)
        if t is Lit:
            return e, lit_value(e)
        if t is Name:
            b = e.b
            if b is not None and b.cval is not None:
                if self.do_inline and b.inline:
                    n = self.lit_for(b.cval, e.line, ctx)
                    if n is not None:
                        self.changes += 1
                        return n, b.cval
                return e, b.cval
            if b is not None and b.truth is False:
                return e, FALSY
            return e, None
        if t is Paren:
            inner, v = self.expr(e.e, None)
            e.e = inner
            if (ctx != "prefix" and is_atom_lit(inner)) or type(inner) is Paren:
                self.changes += 1                  # (5) -> 5, ((x)) -> (x)
                return inner, v
            return e, v
        if t is Un:
            a, va = self.expr(e.a, "unary")
            e.a = a
            if va is None: return e, None
            try:
                v = unop(e.op, va)
            except NoFold:
                return e, None
            return self.replace(e, v, ctx)
        if t is Bin:
            if e.op in ("and", "or"):
                a, va = self.expr(e.a, None)
                e.a = a
                if va is not None and self.do_fold:
                    keep_left = (e.op == "and") != truthy(va)
                    self.changes += 1
                    if keep_left:
                        return a, va
                    b, vb = self.expr(e.b, ctx)
                    if is_multi(b): b = Paren(b, e.line)
                    return b, vb
                b, vb = self.expr(e.b, None)
                e.b = b
                return e, None
            a, va = self.expr(e.a, "powleft" if e.op == "^" else None)
            b, vb = self.expr(e.b, None)
            e.a, e.b = a, b
            if va is None or vb is None: return e, None
            try:
                v = binop(e.op, va, vb)
            except NoFold:
                return e, None
            return self.replace(e, v, ctx)
        if t is Field:
            e.obj = self.expr(e.obj, "prefix")[0]; return e, None
        if t is Index:
            e.obj = self.expr(e.obj, "prefix")[0]; e.key = self.expr(e.key)[0]; return e, None
        if t is Call:
            e.fn = self.expr(e.fn, "prefix")[0]
            if e.form == "(": e.args = [self.expr(a)[0] for a in e.args]
            elif e.form == "tbl": self.expr(e.args[0])
            return e, None
        if t is Method:
            e.obj = self.expr(e.obj, "prefix")[0]
            if e.form == "(": e.args = [self.expr(a)[0] for a in e.args]
            elif e.form == "tbl": self.expr(e.args[0])
            return e, None
        if t is Func:
            self.block(e.body); return e, None
        if t is Table:
            for f in e.fields:
                if f[0] == "comment": continue
                if f[0] == "index": f[1] = self.expr(f[1])[0]
                f[2] = self.expr(f[2])[0]
            return e, None
        return e, None

    def replace(self, e, v, ctx):
        if not self.do_fold:
            return e, v
        n = self.lit_for(v, e.line, ctx)
        if n is not None and cost(n) <= cost_est(e, self.info):
            self.changes += 1
            self.report.folded += 1
            return n, v
        return e, v

    # ---- statements
    def block(self, blk):
        out = []
        for s in blk.stmts:
            out.extend(self.stmt(s))
        if self.do_dce:
            kept, dead = [], False
            for s in out:
                if dead and type(s) not in (Label, Comment):
                    self.changes += 1; self.report.removed_code.append(("unreachable", s.line))
                    continue
                dead = False if type(s) is Label else dead
                kept.append(s)
                if type(s) in (Break, Goto, Return):
                    dead = True
            out = kept
        blk.stmts = out

    def unwrap(self, blk, line):
        if any(type(s) in (Local, LocalFunc, Label, Return) for s in blk.stmts):
            return [Do(blk, line)]
        return blk.stmts

    def stmt(self, s):
        t = type(s)
        ex = lambda e: self.expr(e)[0]
        if t is Local:
            s.exprs = [ex(e) for e in s.exprs]
        elif t is Assign:
            for tg in s.targets:
                if type(tg) is Index: tg.obj = self.expr(tg.obj, "prefix")[0]; tg.key = ex(tg.key)
                elif type(tg) is Field: tg.obj = self.expr(tg.obj, "prefix")[0]
            s.exprs = [ex(e) for e in s.exprs]
        elif t is CallStat:
            s.call = ex(s.call)
            if type(s.call) not in (Call, Method):    # cannot happen: calls never fold
                raise AssertionError("call statement folded away")
        elif t in (LocalFunc, FuncStat):
            self.block(s.func.body)
        elif t is Do:
            self.block(s.body)
        elif t is While:
            c, v = self.expr(s.cond)
            s.cond = c
            if self.do_dce and v is not None and not truthy(v):
                self.changes += 1; self.report.removed_code.append(("while false", s.line))
                return []
            self.block(s.body)
        elif t is Repeat:
            self.block(s.body); s.cond = ex(s.cond)
        elif t is If:
            conds, blocks, orelse = [], [], s.orelse
            for c, b in zip(s.conds, s.blocks):
                c, v = self.expr(c)
                if self.do_dce and v is not None:
                    self.changes += 1
                    if not truthy(v):
                        self.report.removed_code.append(("if-arm false", s.line))
                        continue
                    self.report.removed_code.append(("if-arm true: rest dropped", s.line))
                    orelse = b
                    break
                conds.append(c); blocks.append(b)
            for b in blocks: self.block(b)
            if orelse is not None: self.block(orelse)
            if not conds:
                return [] if orelse is None else self.unwrap(orelse, s.line)
            s.conds, s.blocks, s.orelse = conds, blocks, orelse
        elif t is NumFor:
            a, va = self.expr(s.start); s.start = a
            b, vb = self.expr(s.stop); s.stop = b
            vs = ("int", 1)
            if s.step is not None:
                c, vs = self.expr(s.step); s.step = c
            if (self.do_dce and va and vb and vs and all(x is not FALSY and x[0] in ("int", "float")
                                                         for x in (va, vb, vs))):
                st = vs[1]
                if (st > 0 and va[1] > vb[1]) or (st < 0 and va[1] < vb[1]):
                    self.changes += 1; self.report.removed_code.append(("empty for", s.line))
                    return []
            self.block(s.body)
        elif t is GenFor:
            s.exprs = [ex(e) for e in s.exprs]
            self.block(s.body)
        elif t is Return:
            s.exprs = [ex(e) for e in s.exprs]
        return [s]

def value_repr(v):
    r = value_lit(v, 0)
    return "".join(t[1] for t in emit_tree(r[0])) if r else "?"


# =============================================================================
# Pass: tree shaking (spec R7)
# =============================================================================

def is_pure(e):
    t = type(e)
    if t is Lit: return e.kind != "vararg"
    if t in (Name, Func): return True
    if t is Paren: return is_pure(e.e)
    if t is Table:
        return all(kind == "comment" or ((kind != "index" or is_pure(key)) and is_pure(val))
                   for kind, key, val, sep in e.fields)
    if t is Bin and e.op in ("and", "or"): return is_pure(e.a) and is_pure(e.b)
    if t is Un and e.op == "not": return is_pure(e.a)
    if t in (Bin, Un): return all(type(c) is Lit and c.kind in ("number", "string")
                                  for c in leaves(e))
    return False

def leaves(e):
    if type(e) in (Bin, Un, Paren):
        for c in children_expr(e): yield from leaves(c)
    else:
        yield e

class Shaker:
    def __init__(self, info, report):
        self.info, self.report = info, report
        self.work = []
        self.mod_live, self.mod_deferred = set(), {}
        self.changes = 0
        self.top_ids = {id(s) for s in info.prog.stmts}
        for b in info.globals.values():
            b.live = b.reserved or not (info.whole and info.dynamic is None)
        for b in list(info.globals.values()) + info.locals:
            if b.nomi is not None:
                b.live = True                       # kept by NOMINIFY: never removed
        if info.dynamic is not None or not info.whole or info.require_escapes:
            self.mod_live = set(info.preloads)

    def mark(self, b):
        if b is None or b.live: return
        b.live = True
        self.work.extend(b.deferred)
        b.deferred = []

    def defer(self, b, node):
        if type(node) is Func and node.raw is not None:
            self.mark(b)                    # a NOMINIFY function is never removed
        if b.live: self.work.append(node)
        else: b.deferred.append(node)

    def run(self):
        self.work.append(self.info.prog)
        while self.work:
            n = self.work.pop()
            if type(n) is Block: self.block(n)
            elif type(n) is tuple and n[0] == "module": self.block(n[1].body)
            else: self.expr(n)

    def module(self, m):
        if m in self.mod_live and m not in self.mod_deferred: return
        self.mod_live.add(m)
        if m in self.mod_deferred:
            self.work.append(("module", self.mod_deferred.pop(m)))

    def block(self, blk):
        for s in blk.stmts: self.stmt(s)

    def pairs(self, targets, exprs, binding_of):
        ne = len(exprs)
        for i, e in enumerate(exprs):
            b = binding_of(targets[i]) if i < len(targets) else None
            feeds_many = i == ne - 1 and len(targets) > ne and is_multi(e)
            if b is not None and not feeds_many and is_pure(e):
                self.defer(b, e)
            else:
                self.expr(e)

    def stmt(self, s):
        t = type(s)
        if t is Local:
            self.pairs(s.names, s.exprs, lambda n: n.b)
        elif t is Assign:
            m = preload_name(s) if id(s) in self.top_ids else None
            if m is not None:
                self.expr(s.targets[0].obj)
                if m in self.mod_live: self.work.append(("module", s.exprs[0]))
                else: self.mod_deferred[m] = s.exprs[0]
                return
            for tg in s.targets:
                if type(tg) is Index: self.expr(tg.obj); self.expr(tg.key)
                elif type(tg) is Field: self.expr(tg.obj)
            self.pairs(s.targets, s.exprs, lambda tg: tg.b if type(tg) is Name else None)
        elif t is CallStat:
            self.expr(s.call)
        elif t is LocalFunc:
            self.defer(s.name.b, s.func)
        elif t is FuncStat:
            if not s.path and not s.method:
                self.defer(s.base.b, s.func)
            else:
                self.mark(s.base.b); self.expr(s.func)
        elif t is If:
            for c, b in zip(s.conds, s.blocks): self.expr(c); self.block(b)
            if s.orelse is not None: self.block(s.orelse)
        elif t is While:
            self.expr(s.cond); self.block(s.body)
        elif t is Do:
            self.block(s.body)
        elif t is Repeat:
            self.block(s.body); self.expr(s.cond)
        elif t is NumFor:
            self.expr(s.start); self.expr(s.stop)
            if s.step is not None: self.expr(s.step)
            self.block(s.body)
        elif t is GenFor:
            for e in s.exprs: self.expr(e)
            self.block(s.body)
        elif t is Return:
            for e in s.exprs: self.expr(e)

    def expr(self, e):
        t = type(e)
        if t is Name:
            self.mark(e.b)
        elif t is Func:
            for b in e.raw_bindings:        # what a protected body uses stays live
                self.mark(b)
            self.block(e.body)
        elif t is Call:
            self.expr(e.fn)
            for a in e.args: self.expr(a)
            m = require_target(e)
            if m == "":
                for mm in list(self.mod_deferred): self.module(mm)
            elif m is not None:
                self.module(m)
        else:
            for c in children_expr(e): self.expr(c)

    # ---- removal
    def dead(self, b):
        return b is not None and not b.live and not b.reserved and not b.implicit

    def prune_pairs(self, targets, exprs, tb):
        """Drop (target, value) pairs whose target is dead and value pure."""
        ne, nt = len(exprs), len(targets)
        last_multi = ne > 0 and is_multi(exprs[-1])
        keep_t = [True] * nt
        keep_e = [True] * ne
        for i in range(nt):
            b = tb(targets[i])
            if not self.dead(b): continue
            if i < ne:
                e = exprs[i]
                if i == ne - 1 and (last_multi or nt > ne):
                    continue          # last value feeds later targets / is multi
                if is_pure(e):
                    keep_t[i] = keep_e[i] = False
            else:
                if not last_multi:
                    keep_t[i] = False
        if last_multi:                # trailing dead targets fed by the multi value
            for i in range(nt - 1, ne - 1, -1):
                if keep_t[i] and self.dead(tb(targets[i])) and i > ne - 1:
                    keep_t[i] = False
                else:
                    break
        nt2 = [x for x, k in zip(targets, keep_t) if k]
        ne2 = [x for x, k in zip(exprs, keep_e) if k]
        return nt2, ne2

    def prune_block(self, blk):
        out = []
        for s in blk.stmts:
            t = type(s)
            if t is Local:
                names, exprs = self.prune_pairs(s.names, s.exprs, lambda n: n.b)
                if not names:
                    self.note(s)
                    if exprs and all(type(e) in (Call, Method) or is_pure(e) for e in exprs):
                        out.extend(CallStat(e, s.line) for e in exprs if type(e) in (Call, Method))
                        continue
                    if not exprs:
                        continue
                    names, exprs = s.names, s.exprs          # keep as written
                elif len(names) != len(s.names):
                    self.note(s)
                s.names, s.exprs = names, exprs
                for e in s.exprs: self.prune_expr(e)
                out.append(s)
            elif t is Assign:
                if preload_name(s) is not None and blk is self.info.prog:
                    m = preload_name(s)
                    if m not in self.mod_live:
                        self.changes += 1; self.report.removed_modules.append(m)
                        continue
                    self.prune_block(s.exprs[0].body)
                    out.append(s); continue
                tb = lambda tg: tg.b if type(tg) is Name else None
                targets, exprs = self.prune_pairs(s.targets, s.exprs, tb)
                if not targets:
                    self.note(s)
                    if all(type(e) in (Call, Method) or is_pure(e) for e in exprs):
                        out.extend(CallStat(e, s.line) for e in exprs if type(e) in (Call, Method))
                        continue
                    targets, exprs = s.targets, s.exprs
                elif not exprs:
                    targets, exprs = s.targets, s.exprs
                elif len(targets) != len(s.targets):
                    self.note(s)
                s.targets, s.exprs = targets, exprs
                for e in s.exprs: self.prune_expr(e)
                out.append(s)
            elif t is LocalFunc:
                if self.dead(s.name.b):
                    self.note(s); continue
                self.prune_func(s.func); out.append(s)
            elif t is FuncStat:
                if not s.path and not s.method and self.dead(s.base.b):
                    self.note(s); continue
                self.prune_func(s.func); out.append(s)
            else:
                for sub in sub_blocks(s): self.prune_block(sub)
                for e in stmt_exprs(s): self.prune_expr(e)
                out.append(s)
        blk.stmts = out

    def note(self, s):
        self.changes += 1
        names = [n.name for n in getattr(s, "names", [])] or \
                [tg.name for tg in getattr(s, "targets", []) if type(tg) is Name]
        if type(s) is LocalFunc: names = [s.name.name]
        if type(s) is FuncStat: names = [s.base.name]
        self.report.removed_bindings.append((", ".join(names), s.line))

    def prune_func(self, f):
        while f.params and not f.vararg:
            b = f.params[-1].b
            if b.reads or len(b.writes) > 1: break
            f.params.pop(); self.changes += 1; self.report.dropped_params += 1
        self.prune_block(f.body)

    def prune_expr(self, e):
        if type(e) is Func:
            self.prune_func(e); return
        for c in children_expr(e): self.prune_expr(c)


class ConstDropper(Shaker):
    """The removal half of `constants` without `unused` (shake): delete the
    declaration of every constant (a binding analyze_constants gave a cval)
    that nothing reads any more - usually because inline replaced its reads.
    Nothing else is removed: no functions, modules or parameters. Call
    analyze_constants(info) first; then prune_block(prog)."""

    def __init__(self, info, report):
        super().__init__(info, report)
        self.mod_live = set(info.preloads)        # never drop a module here

    def dead(self, b):
        return (b is not None and b.cval is not None and b.writes and not b.reads
                and not b.reserved and not b.implicit)

    def prune_func(self, f):                      # keep unused parameters
        self.prune_block(f.body)

def sub_blocks(s):
    t = type(s)
    if t is If: return list(s.blocks) + ([s.orelse] if s.orelse is not None else [])
    if t in (While, Do, Repeat, NumFor, GenFor): return [s.body]
    if t in (LocalFunc, FuncStat): return [s.func.body]
    return []

def stmt_exprs(s):
    t = type(s)
    if t is Local: return list(s.exprs)
    if t is Assign: return list(s.targets) + list(s.exprs)
    if t is CallStat: return [s.call]
    if t is If: return list(s.conds)
    if t is While: return [s.cond]
    if t is Repeat: return [s.cond]
    if t is NumFor: return [x for x in (s.start, s.stop, s.step) if x is not None]
    if t is GenFor: return list(s.exprs)
    if t is Return: return list(s.exprs)
    return []

def walk_exprs(node, fn):
    """Call fn on every expression node in a block or expression, depth first."""
    if type(node) is Block:
        for s in node.stmts:
            for e in stmt_exprs(s): walk_exprs(e, fn)
            if type(s) in (LocalFunc, FuncStat): walk_exprs(s.func, fn)
            for sub in sub_blocks(s):
                if type(s) not in (LocalFunc, FuncStat): walk_exprs(sub, fn)
        return
    fn(node)
    if type(node) is Func:
        walk_exprs(node.body, fn)
    else:
        for c in children_expr(node): walk_exprs(c, fn)


# =============================================================================
# Small passes: sugar, alias, merge, tidy (spec R11)
# =============================================================================

def pass_sugar(prog, report):
    n = [0]
    def fn(e):
        if type(e) in (Call, Method) and e.form == "(" and len(e.args) == 1:
            a = e.args[0]
            if type(a) is Lit and a.kind == "string": e.form = "str"; n[0] += 1
            elif type(a) is Table: e.form = "tbl"; n[0] += 1
    walk_exprs(prog, fn)
    report.sugar += n[0]
    return n[0]

def slot_walk(prog, visit):
    """Call visit(e, setter) for every expression in prog, outermost first,
    where setter(x) puts x in e's place; visit returns True to skip e's
    insides. Function bodies are walked too, and an assignment's targets'
    objects and keys (not the targets themselves)."""
    def visit_slot(obj, attr):
        v = getattr(obj, attr)
        if type(v) is list:
            for i in range(len(v)):
                def s2(x, lst=v, k=i): lst[k] = x
                visit_expr(v[i], s2)
        elif v is not None:
            def setter(x, o=obj, a=attr): setattr(o, a, x)
            visit_expr(v, setter)
    def visit_expr(e, setter):
        if visit(e, setter):
            return
        for attr in expr_slots(e):
            visit_slot(e, attr)
    def visit_block(blk):
        for s in blk.stmts:
            for attr in stmt_slots(s):
                visit_slot(s, attr)
            if type(s) in (LocalFunc, FuncStat): visit_block(s.func.body)
            for sub in sub_blocks(s):
                if type(s) not in (LocalFunc, FuncStat): visit_block(sub)
    def expr_slots(e):
        t = type(e)
        if t is Bin: return ("a", "b")
        if t is Un: return ("a",)
        if t is Paren: return ("e",)
        if t is Field: return ("obj",)
        if t is Index: return ("obj", "key")
        if t is Call: return ("fn", "args")
        if t is Method: return ("obj", "args")
        if t is Func:
            visit_block(e.body); return ()
        if t is Table:
            out = []
            for f in e.fields:
                if f[0] == "index": out.append((1, f))
                if f[0] != "comment": out.append((2, f))
            for i, f in out:
                def s3(x, f=f, i=i): f[i] = x
                visit_expr(f[i], s3)
            return ()
        return ()
    def stmt_slots(s):
        t = type(s)
        if t is Local: return ("exprs",)
        if t is Assign:
            for tg in s.targets:
                if type(tg) is Index: visit_slot(tg, "obj"); visit_slot(tg, "key")
                elif type(tg) is Field: visit_slot(tg, "obj")
            return ("exprs",)
        if t is CallStat: return ("call",)
        if t is If: return ("conds",)
        if t in (While, Repeat): return ("cond",)
        if t is NumFor: return ("start", "stop", "step")
        if t is GenFor: return ("exprs",)
        if t is Return: return ("exprs",)
        return ()
    visit_block(prog)

def top_local_count(prog):
    """The main chunk's top-level locals (Lua allows 200 per function)."""
    return sum(len(s.names) for s in prog.stmts if type(s) is Local) + \
           sum(1 for s in prog.stmts if type(s) is LocalFunc)

TOP_LOCALS_CAP = 180      # the main chunk's top-level locals once alias/literals add theirs

ALIAS_SKIP = {"package", "require", "_G", "_ENV", "self", "arg"} | CALLBACKS

def pass_alias(info, report):
    """Alias heavily used reserved globals / library fields with one top-level local."""
    prog = info.prog
    if not info.whole or info.dynamic is not None:
        return 0
    field_writes = set()
    def collect_field_writes(blk):
        for s in blk.stmts:
            if type(s) is Assign:
                for tg in s.targets:
                    if type(tg) is Field and type(tg.obj) is Name and tg.obj.b.kind == "global":
                        field_writes.add((tg.obj.name, tg.name))
            if type(s) is FuncStat and s.path and s.base.b.kind == "global":
                field_writes.add((s.base.name, s.path[0][0]))
            for sub in sub_blocks(s): collect_field_writes(sub)
            for e in stmt_exprs(s):
                walk_exprs(e, lambda x: collect_field_writes(x.body) if type(x) is Func else None)
    collect_field_writes(prog)
    uses = {}                                       # key -> list of (parent setter)
    def visit(e, setter):
        t = type(e)
        if t is Field and type(e.obj) is Name and e.obj.b is not None and e.obj.b.kind == "global" \
                and e.obj.b.reserved and not e.obj.b.writes and not e.obj.b.pinned \
                and e.obj.name not in ALIAS_SKIP \
                and (e.obj.name, e.name) not in field_writes:
            uses.setdefault(f"{e.obj.name}.{e.name}", []).append((setter, e))
            return True
        if t is Name:
            b = e.b
            if b is not None and b.kind == "global" and b.reserved and not b.writes \
                    and not b.pinned and e.name not in ALIAS_SKIP and b.name in TIC80_GLOBALS:
                uses.setdefault(e.name, []).append((setter, e))
            return True
        return False
    slot_walk(prog, visit)
    top_locals = top_local_count(prog)
    chosen = []
    for key, sites in sorted(uses.items(), key=lambda kv: -len(kv[1])):
        L = len(key)
        if len(sites) * (L - NAME_EST) <= NAME_EST + 1 + L + 1:
            continue
        if top_locals + len(chosen) >= TOP_LOCALS_CAP:
            break
        chosen.append((key, sites))
    if not chosen:
        return 0
    used = {b.name for b in info.locals} | set(info.globals)
    names, exprs = [], []
    line = prog.stmts[0].line if prog.stmts else 1
    for i, (key, sites) in enumerate(chosen):
        nm = f"__a{i}"
        while nm in used: nm += "_"
        used.add(nm)
        names.append(Name(nm, line))
        if "." in key:
            g, f = key.split(".")
            exprs.append(Field(Name(g, line), f, line))
        else:
            exprs.append(Name(key, line))
        for setter, node in sites:
            setter(Name(nm, node.line))
        report.aliased.append((key, len(sites)))
    prog.stmts.insert(0, Local(names, exprs, line))
    return len(chosen)

def pass_literals(info, report, renaming=True, limit=None):
    """Share a string or number literal written several times through one
    top-level local, when that saves size (spec R11e). limit: share at most
    that many (the caller's retry when a function would need too many
    upvalues). Returns how many were shared."""
    prog = info.prog
    skip = set()     # what other passes read as literals: require "m", package.preload["m"]
    sugar = set()    # f"s" arguments: f(a) is two characters longer than f"s"
    def mark(e):
        t = type(e)
        if t in (Call, Method) and e.form == "str":
            sugar.add(id(e.args[0]))
        if t is Call and require_target(e) is not None:
            skip.update(id(a) for a in e.args)
        if t is Index and type(e.obj) is Field and type(e.obj.obj) is Name \
                and e.obj.obj.name == "package":
            skip.add(id(e.key))
    walk_exprs(prog, mark)
    groups = {}                                     # value -> [(setter, Lit)]
    def visit(e, setter):
        if type(e) is Lit and e.kind in ("string", "number") and id(e) not in skip:
            v = lit_value(e)                        # ("int", 1) and ("float", 1.0) differ
            if v is not None:
                groups.setdefault(v, []).append((setter, e))
            return True
        return False
    slot_walk(prog, visit)
    est = NAME_EST if renaming else 5               # `__l12` stays that long unrenamed
    shared = []
    for sites in groups.values():
        if len(sites) < 2:
            continue
        text = min((e.text for _, e in sites), key=len)
        gain = sum(len(e.text) - est - 2 * (id(e) in sugar) for _, e in sites) \
            - (est + 1 + len(text) + 1)             # `a,` and `"text",` in the declaration
        if gain > 0:
            shared.append((gain, text, sites))
    shared.sort(key=lambda s: -s[0])
    room = max(0, TOP_LOCALS_CAP - top_local_count(prog))
    shared = shared[:room if limit is None else min(room, limit)]
    if not shared:
        return 0
    used = {b.name for b in info.locals} | set(info.globals)
    names, exprs = [], []
    line = prog.stmts[0].line if prog.stmts else 1
    for i, (_, text, sites) in enumerate(shared):
        nm = f"__l{i}"
        while nm in used: nm += "_"
        used.add(nm)
        names.append(Name(nm, line))
        exprs.append(Lit(sites[0][1].kind, text, line))
        for setter, node in sites:
            setter(Name(nm, node.line))
        report.shared.append((text, len(sites)))
    prog.stmts.insert(0, Local(names, exprs, line))
    def unsugar(e):                                 # f"s" whose s is now a local: f(a)
        if type(e) in (Call, Method) and e.form == "str" and type(e.args[0]) is not Lit:
            e.form = "("
    walk_exprs(prog, unsugar)
    return len(shared)

def pass_merge(info, report):
    n = [0]
    def block(blk):
        out = []
        for s in blk.stmts:
            prev = out[-1] if out else None
            if (type(s) is Local and type(prev) is Local
                    and len(prev.exprs) in (0, len(prev.names)) and len(s.exprs) in (0, len(s.names))
                    and bool(prev.exprs) == bool(s.exprs)
                    and not any(type(e) is Func for e in prev.exprs + s.exprs)):
                declared = {nm.b for nm in prev.names}
                hit = [False]
                def fn(e):
                    if type(e) is Name and e.b in declared: hit[0] = True
                for e in s.exprs: walk_exprs(e, fn)
                if not hit[0]:
                    prev.names = prev.names + s.names
                    prev.exprs = prev.exprs + s.exprs
                    n[0] += 1
                    continue
            out.append(s)
            for sub in sub_blocks(s): block(sub)
            for e in stmt_exprs(s):
                walk_exprs(e, lambda x: block(x.body) if type(x) is Func else None)
        blk.stmts = out
    block(info.prog)
    report.merged += n[0]
    return n[0]

def pass_tidy(prog):
    n = [0]
    def block(blk):
        out = []
        for s in blk.stmts:
            t = type(s)
            if t is Semi:
                n[0] += 1; continue
            if t is Return and s.semi:
                s.semi = False; n[0] += 1
            if t is If and s.orelse is not None and not s.orelse.stmts:
                s.orelse = None; n[0] += 1
            if t is Do and not s.body.stmts:
                n[0] += 1; continue
            out.append(s)
            for sub in sub_blocks(s): block(sub)
            for e in stmt_exprs(s):
                walk_exprs(e, tidy_expr)
        blk.stmts = out
    def tidy_expr(e):
        if type(e) is Func:
            block(e.body)
        elif type(e) is Table and e.fields and e.fields[-1][3] is not None:
            e.fields[-1][3] = None; n[0] += 1
    block(prog)
    return n[0]


# =============================================================================
# Pass: renaming (spec R8)
# =============================================================================

_C1 = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_"
_C2 = _C1 + "0123456789"

def name_pool(excluded):
    def gen():
        for a in _C1: yield a
        for a in _C1:
            for b in _C2: yield a + b
        for a in _C1:
            for b in _C2:
                for c in _C2: yield a + b + c
    for n in gen():
        if n in KEYWORDS or n in excluded or (len(n) > 1 and n[0] == "_" and n[1].isupper()):
            continue
        yield n

def pass_rename(info, report, variables=True):
    """Rename the renamable bindings (spec R8): variables (and goto labels)
    unless variables is False, and functions when info says they are
    renamable (rename-functions). Returns how many were renamed, and
    {source line: bytes} that renaming functions saved."""
    # a variable a NOMINIFY directive keeps is pinned (Info), so not renamable
    def wanted(b):
        return b.renamable and (variables or b.is_function)
    gl = [b for b in info.globals.values() if wanted(b) and b.occ]
    lo = [b for b in info.locals if wanted(b) and b.occ]
    fixed = set(RESERVED)
    for b in list(info.globals.values()) + info.locals:
        if not wanted(b): fixed.add(b.name)
    pool = list(_take(name_pool(fixed), len(gl) + len(lo) + 200))
    # local intervals and the renamable globals referenced inside each local's scope
    gocc = sorted((n.pos, i) for i, b in enumerate(gl) for n in b.occ if n.pos >= 0)
    gpos = [p for p, _ in gocc]
    for b in lo:
        ps = [n.pos for n in b.occ if n.pos >= 0]
        b.ival = (min(ps), max(ps)) if ps else (b.start, b.start)
        lo_i = bisect.bisect_left(gpos, b.start if b.start >= 0 else b.ival[0])
        hi_i = bisect.bisect_right(gpos, b.end)
        b.gin = {gocc[k][1] for k in range(lo_i, hi_i)}
    gid = {id(b): i for i, b in enumerate(gl)}
    order = sorted(gl + lo, key=lambda b: (-len(b.occ), b.occ[0].pos if b.occ else 0))
    by_name_g = {}                 # name -> global index
    by_name_l = {}                 # name -> [local bindings]
    for b in order:
        isg = b.kind == "global"
        for nm in pool:
            if isg:
                if nm in by_name_g: continue
                me = gid[id(b)]
                if any(me in L.gin for L in by_name_l.get(nm, ())): continue
                by_name_g[nm] = me
            else:
                g = by_name_g.get(nm)
                if g is not None and g in b.gin: continue
                a0, a1 = b.ival
                if any(not (a1 < L.ival[0] or L.ival[1] < a0) for L in by_name_l.get(nm, ())):
                    continue
                by_name_l.setdefault(nm, []).append(b)
            b.newname = nm
            break
        else:
            raise AssertionError(f"minify: name pool exhausted renaming {b.name}")
    fn_saved = {}
    for b in gl + lo:
        if b.newname != b.name:
            report.renames.append((b.newname, b.name, b.kind, b.occ[0].line))
        for n in b.occ:
            if b.is_function:
                fn_saved[n.line] = fn_saved.get(n.line, 0) + len(b.name) - len(b.newname)
            n.name = b.newname
    # labels: one namespace per function
    nl = 0
    for f in info.fctxs if variables else ():
        if not f.labels: continue
        if any(g.label is None for g in f.gotos): continue
        names = {}
        lp = name_pool(set())
        for lab in f.labels:
            names[id(lab)] = next(lp)
        for g in f.gotos: g.name = names[id(g.label)]
        for lab in f.labels:
            lab.name = names[id(lab)]; nl += 1
    return len(gl) + len(lo) + nl, fn_saved

def _take(it, n):
    for i, x in enumerate(it):
        if i >= n: break
        yield x


# =============================================================================
# Pass: table key renaming (spec R13, D13, D14)
# =============================================================================
#
# Keys are renamed by spelling, not by table: every `.speed`, `:speed()`,
# `{speed=}` and `["speed"]` becomes the same short name, so whatever the
# program does with its own keys still lines up. What can break that is a
# string the platform reads or hands back as a key (library members,
# metamethods: kept by name), and a string built at runtime that meets a key
# (`t["sp".."eed"]`) or a key that is looked at as a string (`print(k)` in a
# pairs loop). _KeyFlow works out, for the whole program, which strings can
# reach each key position and where the runtime's keys go; anything it can't
# prove harmless keeps its name or turns the pass off.

# The 5.3 library members TIC-80 1.2 lacks (utf8, os, io; bit32 from 5.2),
# kept all the same so a cart written for another build never loses one.
EXTRA_LIBRARY_KEYS = set("""char charpattern codepoint codes len offset clock date difftime
execute exit getenv remove rename setlocale time tmpname close flush input lines open output
popen read stderr stdin stdout tmpfile type write arshift band bnot bor btest bxor extract
lrotate lshift replace rrotate rshift""".split())
# spec R13b: never renamed. `n` is table.pack's; names starting `__` too.
LIBRARY_KEYS = ({q.rsplit(".", 1)[1] for q in TIC80_LIBRARY} | EXTRA_LIBRARY_KEYS | {"n"})
STRING_LIB = {q.split(".", 1)[1] for q in TIC80_LIBRARY if q.startswith("string.")}
# the library tables: `string.format` is a library function, `M.format` not
LIB_TABLES = {q.split(".", 1)[0] for q in TIC80_LIBRARY if not q.startswith("<")} \
    | {"utf8", "os", "io", "bit32"}
# The TIC-80 API: every function takes and returns numbers, booleans or nil,
# except that these show (or play) a string argument.
LUA_GLOBALS = set("""_G _VERSION assert collectgarbage coroutine debug dofile error
getmetatable ipairs load loadfile math next package pairs pcall rawequal rawget rawlen rawset
require select setmetatable string table tonumber tostring type xpcall""".split())
TIC80_API = set(TIC80_GLOBALS) - LUA_GLOBALS - CALLBACKS
TIC80_SHOWS = {"print", "trace", "font", "sfx"}
# Library functions that never look at a string argument's spelling (they pass
# it on, store it, or would fail the same on any identifier). Any other
# library function is a sink: a key reaching it disables the pass (R13f).
KEY_BLIND = (TIC80_API - TIC80_SHOWS) | {
    "type", "select", "pcall", "xpcall", "setmetatable", "getmetatable", "next", "pairs",
    "ipairs", "<ipairs>", "rawequal", "tostring", "tonumber", "require", "collectgarbage",
    "table.insert", "table.remove", "table.unpack", "table.pack", "table.move",
    "coroutine.create", "coroutine.wrap", "coroutine.resume", "coroutine.yield",
    "coroutine.running", "coroutine.status", "coroutine.isyieldable"}
LIT_RESULTS = {"type": ("nil", "number", "string", "boolean", "table", "function", "thread",
                        "userdata"),
               "math.type": ("integer", "float"),
               "coroutine.status": ("suspended", "running", "normal", "dead")}
# metamethods the runtime calls with operands, and what reads their result
ARITH_MM = {"__add", "__sub", "__mul", "__div", "__mod", "__pow", "__unm", "__idiv", "__band",
            "__bor", "__bxor", "__shl", "__shr", "__bnot", "__concat", "__len"}
NOT_CALLED_MM = {"__index", "__newindex", "__mode", "__name", "__metatable"}

# The analysis' values (spec D14): a shape is a set of these alternatives,
# and ("lit", s) the string s (made of identifier characters; a literal, or
# built), ("re", r) a string built at runtime that fully matches the regular
# expression r, ("len", n) one of at most n characters; ("fn", id) a program
# function, ("tbl", id) a program table (by the constructor that made it);
# ("lib", name) a library value (`string.format`).
ANY = ("any",)          # any string the program builds at runtime
NONID = ("nonid",)      # a string holding a character no identifier has: never a key name
KEY = ("key",)          # a key the runtime hands back (pairs, next, __index's argument)
FNQ = ("fn?",)          # a function the analysis does not track (from the library)
TBLQ = ("tbl?",)        # a table the analysis does not track: any table at all
TOP = frozenset({ANY, KEY, FNQ, TBLQ})
EMPTY = frozenset()
STRINGISH = {"any", "lit", "re", "len", "nonid", "key"}
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
IDCHARS = re.compile(r"[A-Za-z0-9_]*\Z")
# what tostring makes of anything but a string: a number, nil, a boolean, or
# "table: 0x..." (only "inf" and "nan" could ever be key names)
NUMBER_RX = r"-?(?:\d[\w.+-]*|inf|nan)"
NUMBER_TEXT = ("re", NUMBER_RX + r"|nil|true|false|\w+: .*")
# string.format's conversions, and what each can write
FORMAT_SPEC = re.compile(r"%([-+ #0]*)\d*(?:\.\d*)?([diouxXeEfgGaAcsq%])")
FORMAT_TEXT = {"d": r"-?\d*", "i": r"-?\d*", "u": r"\d*", "o": r"[0-7]*", "x": r"[0-9a-f]*",
               "X": r"[0-9A-F]*", "c": r"(?s:.)", "%": "%"}


def _str_shape(s):
    """The value a literal string s is."""
    return ("lit", s) if IDCHARS.match(s) else NONID


def _format_shape(fmt):
    """What string.format(fmt, ...) can make: NONID when its fixed text has
    a character no identifier has, else a pattern; None if fmt is only
    conversions."""
    out, pos, fixed = [], 0, ""
    for m in FORMAT_SPEC.finditer(fmt):
        flags, conv = m.groups()
        fixed += fmt[pos:m.start()] + ("%" if conv == "%" else "")
        out.append(re.escape(fmt[pos:m.start()]))
        # `#` adds a 0x prefix (or a point): anything, to be safe
        out.append(".*" if "#" in flags else FORMAT_TEXT.get(conv, ".*"))
        pos = m.end()
    fixed += fmt[pos:]
    out.append(re.escape(fmt[pos:]))
    if not IDCHARS.match(fixed):
        return NONID
    return ("re", "".join(out)) if fixed else None


def _ident(lit):
    """The identifier a string literal spells (not a keyword), else None."""
    if type(lit) is not Lit or lit.kind != "string":
        return None
    v = str_value(lit.text)
    if v is None:
        return None
    s = v.decode("latin-1")
    return s if IDENT.match(s) and s not in KEYWORDS else None


def _stringish(shape):
    return any(a[0] in STRINGISH for a in shape)


SAME_TWICE = {"name", "number"}            # token kinds an index may be made of ...
SAME_OPS = {"+", "-", "*", "//", "%", "(", ")"}   # ... with these: no call, no __index


def _sub_span(args):
    """For s:sub(i, j) (args: s, i, j), the most characters it can return
    when j is i or i plus a small integer literal, and i is made of
    variables, numbers and arithmetic only (so both evaluate the same);
    else None."""
    if len(args) != 3:
        return None
    i, j = [t[:2] for t in emit_tree(args[1])], [t[:2] for t in emit_tree(args[2])]
    if not all(k in SAME_TWICE or (k == "op" and t in SAME_OPS) for k, t in i):
        return None
    if i == j:
        return 1
    if len(j) == len(i) + 2 and j[:len(i)] == i and j[len(i)] == ("op", "+") \
            and j[-1][0] == "number" and j[-1][1].isdigit() and int(j[-1][1]) < 8:
        return int(j[-1][1]) + 1
    return None


def _is_package(e, fields=("preload", "loaded")):
    """Is e `package.preload` (or `package.loaded`)?"""
    return (type(e) is Field and e.name in fields and type(e.obj) is Name
            and e.obj.name == "package" and e.obj.b is not None and e.obj.b.kind == "global")


def _key_literal(e):
    """The key name of `t["k"]` (spec D13), except package.preload/loaded's
    module names, which other passes read as literals."""
    return None if _is_package(e.obj) else _ident(e.key)


class _KeyFlow:
    """The key-shape analysis (spec D14) of one whole program: what each
    variable, parameter, return value and table slot can hold, as a set of
    alternatives, worked out to a fixpoint ignoring statement order.

    Functions and tables are values like any other: ("fn", id) follows a
    function wherever it goes, so a call reaches exactly the functions its
    callee can hold, and ("tbl", id) a table built at one constructor, so
    what is stored in one table never leaks into another. A table's slots
    are ("t", id, key) per key name, ("tn", id) for number (or other
    non-string) keys and ("ts", id) for any other string key; a table the
    analysis doesn't know (TBLQ: from the library, or a value it lost track
    of) stores into the global slots ("k", key), DYN_N and DYN_S, which every
    read sees too, and reads every table at once (the ("kall", key), ALLN,
    ALLS and ALL aggregates). Metatables are followed: ("mt", id) holds what
    setmetatable gave a table, and a read misses into `__index`."""

    def __init__(self, info):
        self.info = info
        self.val = {}
        self.funcs, self.va_of = {}, {}
        self.calls, self.returns, self.assigns, self.tables = [], [], [], []
        self.genfors, self.fstats, self.raws = [], [], []
        self.bindings = [b for b in list(info.globals.values()) + info.locals if b.writes]
        self.visit_block(info.prog, None)
        self.dyn_mm = False             # a string key could spell a metamethod
        self.key_escaped = False        # a key went where the analysis can't follow
        self.changed = False
        self.memo = {}

    # ---- collecting the program
    def visit_block(self, blk, F):
        for s in blk.stmts:
            t = type(s)
            if t is Return and F is not None:
                self.returns.append((F, s.exprs))
            elif t is Assign:
                self.assigns.append(s)
            elif t is GenFor:
                self.genfors.append(s)
            elif t is FuncStat and (s.path or s.method):
                self.fstats.append(s)
            for e in stmt_exprs(s):
                self.visit_expr(e, F)
            if t in (LocalFunc, FuncStat):
                self.visit_func(s.func)
            else:
                for sub in sub_blocks(s):
                    self.visit_block(sub, F)

    def visit_expr(self, e, F):
        t = type(e)
        if t is Func:
            self.visit_func(e)
            return
        if t is Lit and e.kind == "vararg":
            self.va_of[id(e)] = F
        elif t in (Call, Method):
            self.calls.append(e)
        elif t is Table:
            self.tables.append(e)
        for c in children_expr(e):
            self.visit_expr(c, F)

    def visit_func(self, f):
        self.funcs[id(f)] = f
        if f.raw is not None:
            self.raws.append(f)
        else:
            self.visit_block(f.body, f)

    # ---- nodes
    def get(self, node):
        return self.val.get(node, EMPTY)

    def add(self, node, shape):
        if not shape:
            return
        cur = self.val.get(node)
        if cur is None:
            cur = self.val[node] = set()
        if shape <= cur:
            return
        cur |= shape
        self.changed = True
        k = node[0] if type(node) is tuple else node
        aggs = {"t": (("tall", node[1]), ("kall", node[-1]), "ALL"),
                "tn": (("tall", node[1]), "ALLN", "ALL"),
                "ts": (("tall", node[1]), "ALLS", "ALL"),
                "k": (("kall", node[-1]), "GALL", "ALL"),
                "DYN_N": ("ALLN", "GALL", "ALL"),
                "DYN_S": ("ALLS", "GALL", "ALL")}.get(k, ())
        for a in aggs:
            self.val.setdefault(a, set()).update(shape)

    def params(self, F):
        return ([F.self_b] if F.is_method else []) + [p.b for p in F.params]

    def fns(self, shape):
        return [self.funcs[a[1]] for a in shape if a[0] == "fn"]

    def ret(self, fid):
        F = self.funcs[fid]
        return self.top if F.raw is not None else self.get(("ret", fid))

    # ---- table slots
    @staticmethod
    def kind(key_shape):
        """How a non-literal key reads or writes a table: "s" for a string
        (which could be any key name), else "n"."""
        return "s" if _stringish(key_shape) else "n"

    def read(self, obj, kind, k=None):
        """What reading key k ("k"), a number key ("n") or any string key
        ("s") of the tables obj can be gives."""
        out = set()
        for a in obj:
            if a[0] == "tbl":
                out |= self.read_t(a[1], kind, k, set())
            elif a is TBLQ:
                out |= self.read_q(kind, k)
            elif (a[0] == "lib" and a[1] in LIB_TABLES) or (a[0] in STRINGISH and kind == "k"):
                out |= self.read_g(kind, k)     # what the program put in a library table
        return frozenset(out)

    def read_g(self, kind, k):
        if kind == "k":
            return self.get(("k", k)) | self.get("DYN_S")
        return self.get("DYN_N") if kind == "n" else self.get("GALL")

    def read_q(self, kind, k):
        if kind == "k":
            return self.get(("kall", k)) | self.get("ALLS") | self.get("IDXRET")
        return (self.get("ALLN") if kind == "n" else self.get("ALL")) | self.get("IDXRET")

    def read_t(self, tid, kind, k, seen):
        if tid in seen:
            return EMPTY
        seen.add(tid)
        if kind == "k":
            out = self.get(("t", tid, k)) | self.get(("ts", tid))
        else:
            out = self.get(("tn", tid) if kind == "n" else ("tall", tid))
        out = out | self.read_g(kind, k)
        for m in self.get(("mt", tid)):
            if m[0] == "tbl":
                for x in self.meta(m[1], "__index"):
                    if x[0] == "tbl":
                        out = out | self.read_t(x[1], kind, k, seen)
                    elif x[0] == "fn":
                        out = out | self.ret(x[1])
                    elif x is TBLQ:
                        out = out | self.read_q(kind, k)
                    elif x is FNQ:
                        out = out | self.top
            elif m is TBLQ:
                out = out | self.read_q(kind, k)
        return out

    def meta(self, mid, name):
        """A metatable's field, as the runtime reads it (raw)."""
        return self.get(("t", mid, name)) | self.get(("ts", mid)) | self.read_g("k", name)

    def store(self, obj, kind, k, shape):
        for a in obj:
            if a[0] == "tbl":
                self.store_t(a[1], kind, k, shape, set())
            elif a is TBLQ or (a[0] == "lib" and a[1] in LIB_TABLES):
                self.add(("k", k) if kind == "k" else "DYN_N" if kind == "n" else "DYN_S",
                         shape)

    def store_t(self, tid, kind, k, shape, seen):
        if tid in seen:
            return
        seen.add(tid)
        self.add(("t", tid, k) if kind == "k" else ("tn", tid) if kind == "n" else ("ts", tid),
                 shape)
        for m in self.get(("mt", tid)):         # a new key may go to __newindex
            if m[0] == "tbl":
                for x in self.meta(m[1], "__newindex"):
                    if x[0] == "tbl":
                        self.store_t(x[1], kind, k, shape, seen)
                    elif x[0] == "fn" and self.funcs[x[1]].raw is None:
                        ps = self.params(self.funcs[x[1]])
                        if len(ps) > 2:
                            self.add(("b", id(ps[2])), shape)
                    elif x is TBLQ:
                        self.store([TBLQ], kind, k, shape)

    # ---- the shape of an expression
    def S(self, e):
        r = self.memo.get(id(e))
        if r is None:
            r = self.memo[id(e)] = self._S(e)
        return r

    def _S(self, e):
        t = type(e)
        if t is Lit:
            if e.kind == "string":
                v = str_value(e.text)
                return frozenset({NONID if v is None else _str_shape(v.decode("latin-1"))})
            if e.kind == "vararg":
                F = self.va_of.get(id(e))
                return self.get(("va", id(F))) if F is not None else EMPTY
            return EMPTY
        if t is Name:
            b = e.b
            if b is None:
                return self.top
            s = self.get(("b", id(b)))
            if b.kind == "global" and b.reserved and b.name not in CALLBACKS:
                s = s | {("lib", b.name)}
            return s
        if t is Paren:
            return self.S(e.e)
        if t is Func:
            return frozenset({("fn", id(e))})
        if t is Table:
            return frozenset({("tbl", id(e))})
        if t is Un:
            return EMPTY if e.op == "not" else self.get("OPS")
        if t is Bin:
            if e.op in ("and", "or"):
                return self.S(e.a) | self.S(e.b)
            if e.op in ("==", "~=", "<", "<=", ">", ">="):
                return EMPTY
            if e.op == "..":
                return self.concat(e) | self.get("OPS")
            return self.get("OPS")
        if t is Field:
            o = self.S(e.obj)
            return self.member(o, e.name) | self.read(o, "k", e.name)
        if t is Index:
            o, k = self.S(e.obj), _key_literal(e)
            if k is not None:
                return self.member(o, k) | self.read(o, "k", k)
            return self.read(o, self.kind(self.S(e.key)))
        if t in (Call, Method):
            return self.call_result(e)
        return self.top

    def member(self, obj, k):
        """Library members a read of key k on obj can give: `string.format`,
        or a string's method through the string metatable."""
        out = {("lib", f"{a[1]}.{k}") for a in obj if a[0] == "lib" and a[1] in LIB_TABLES}
        if k in STRING_LIB and _stringish(obj):
            out.add(("lib", "string." + k))
        return frozenset(out)

    def lit_alts(self, e):
        """The literal strings e can be, when it is one (or a variable only
        ever set to one); else None."""
        if type(e) is Paren:
            return self.lit_alts(e.e)
        if type(e) is Lit and e.kind == "string":
            v = str_value(e.text)
            return None if v is None else {v.decode("latin-1")}
        if type(e) is Lit and e.kind == "number":
            v = lit_value(e)
            return {str(v[1])} if v and v[0] == "int" and v[1] >= 0 else None
        if type(e) is Name and e.b is not None and e.b.writes and not e.b.pinned:
            out = set()
            for w in e.b.writes:
                if w.kind not in ("local", "assign") or type(w.value) is not Lit \
                        or w.value.kind != "string":
                    return None
                out |= self.lit_alts(w.value)
            return out
        return None

    def concat(self, e):
        """`a .. b .. c`: a pattern made of what each piece can be (D14);
        NONID when a piece always holds a non-identifier character; ANY when
        no piece is known at all."""
        pieces, todo = [], [e]
        while todo:
            x = todo.pop()
            while type(x) is Paren:
                x = x.e
            if type(x) is Bin and x.op == "..":
                todo += [x.b, x.a]
            else:
                pieces.append(x)
        parts = []
        for p in pieces:
            sh = self.S(p)
            strs = [a for a in sh if a[0] in STRINGISH]
            if strs and all(a is NONID for a in strs) and len(strs) == len(sh):
                return frozenset({NONID})
            alts = set()
            for a in strs:
                alts.add(re.escape(a[1]) if a[0] == "lit" else a[1] if a[0] == "re" else
                         ".{0,%d}" % a[1] if a[0] == "len" else ".*")
            if len(strs) < len(sh) or not sh:
                # a number, as `..` writes it (not ".*": a piece knows nothing
                # yet in the first rounds, and ANY then would stick)
                alts.add(NUMBER_RX)
            parts.append(".*" if ".*" in alts or len(alts) > 16 else
                         "(?:" + "|".join(sorted(alts)) + ")")
        rx = "".join(parts)
        if all(x in (".*", "(?:)") for x in parts) or len(rx) > 400:
            return frozenset({ANY})
        return frozenset({("re", rx)})

    def callee(self, e):
        """(the values a call's callee can be, its arguments as a list)."""
        if type(e) is Method:
            o = self.S(e.obj)
            return self.member(o, e.name) | self.read(o, "k", e.name), [e.obj] + list(e.args)
        return self.S(e.fn), list(e.args)

    def arg(self, args, i):
        if i < len(args):
            return self.S(args[i])
        if args and is_multi(args[-1]):
            return self.S(args[-1])
        return EMPTY

    def args_from(self, args, i):
        out = set()
        for j in range(i, max(len(args), i + 1)):
            out |= self.arg(args, j)
        return frozenset(out)

    def call_result(self, e):
        c, args = self.callee(e)
        out = set(self.get("CALLRET"))
        for a in c:
            if a[0] == "fn":
                out |= self.ret(a[1])
            elif a[0] == "lib":
                out |= self.lib_result(a[1], e, args)
            elif a is FNQ:
                out |= self.top
        return frozenset(out)

    @property
    def top(self):
        """Any value at all: a key only once one has gone where the analysis
        can't follow it (key_escaped)."""
        return TOP if self.key_escaped else TOP - {KEY}

    def lib_result(self, name, e, args):
        """What calling library function name returns (any value when the
        analysis doesn't know it)."""
        r = self._lib(name, e, args)
        return self.top if r is None else r

    def module(self, args):
        """The preload function a literal `require "m"` runs, else None."""
        m = self.lit_alts(args[0]) if args else None
        if m and len(m) == 1 and next(iter(m)) in self.info.preloads:
            return self.info.preloads[next(iter(m))][1]
        return None

    def _lib(self, name, e, args):
        A = lambda i: self.arg(args, i)
        if name in TIC80_API or (name.startswith("math.") and name != "math.type"):
            return EMPTY
        if name in LIT_RESULTS:
            return frozenset(("lit", s) for s in LIT_RESULTS[name])
        if name == "tostring":
            a0 = A(0)
            strs = frozenset(a for a in a0 if a[0] in STRINGISH)
            return strs | self.get("TSRET") | ({NUMBER_TEXT} if len(strs) < len(a0) or not a0
                                               else EMPTY)
        if name == "string.format":
            fmts = self.lit_alts(args[0]) if args else None
            if not fmts:
                return frozenset({ANY})
            out = {_format_shape(f) for f in fmts}
            return frozenset({ANY}) if None in out else frozenset(out)
        if name in ("tonumber", "rawlen", "rawequal", "collectgarbage", "error",
                    "coroutine.create", "coroutine.running", "coroutine.isyieldable",
                    "table.insert", "table.sort", "string.byte", "string.len",
                    "string.packsize"):
            return EMPTY
        if name in ("select", "assert"):
            return self.args_from(args, 1 if name == "select" else 0)
        if name == "setmetatable":
            return A(0)
        if name == "getmetatable":
            mts = set()
            for a in A(0):
                if a[0] == "tbl":
                    mts |= self.get(("mt", a[1]))
                elif a[0] in STRINGISH or a is TBLQ:
                    mts.add(TBLQ)
            return frozenset(mts) | self.read(mts, "k", "__metatable")
        if name == "next":
            return frozenset({KEY}) | self.read(A(0), "s")
        if name == "pairs":
            return frozenset({("lib", "next")}) | A(0)
        if name == "ipairs":
            return frozenset({("lib", "<ipairs>")}) | A(0)
        if name in ("table.unpack", "table.remove", "<ipairs>"):
            return self.read(A(0), "n")
        if name == "table.pack":
            return frozenset({("tbl", id(e)) if e is not None else TBLQ})
        if name == "table.move":
            return A(4) if len(args) > 4 else A(0)
        if name == "require":
            F = self.module(args)
            return None if F is None else self.ret(id(F))
        if name in ("pcall", "xpcall"):
            out = {ANY}                             # false and the error message
            rest = args[1:] if name == "pcall" else args[2:]
            for a in A(0):
                if a[0] == "fn":
                    out |= self.ret(a[1])
                elif a[0] == "lib":
                    out |= self.lib_result(a[1], None, rest)
                elif a is FNQ:
                    out |= self.top
            return frozenset(out)
        if name == "string.sub":
            return self.substrings(args)
        if name == "string.gmatch":
            return frozenset({("lib", "<gmatch>")})
        if name == "<gmatch>":
            return frozenset({ANY})
        if name == "coroutine.wrap":
            return frozenset({FNQ})
        if name == "string.char" and args and not is_multi(args[-1]):
            return frozenset({("len", len(args))})
        if name.startswith("string.") or name == "table.concat":
            return frozenset({ANY})
        return None

    def substrings(self, args):
        """s:sub(i, j) with s a literal: its characters when i and j are the
        same expression, else every piece of it; with s any other string, a
        string of at most j - i + 1 characters when that is a constant
        (`s:sub(i, i)`, `s:sub(i, i + 2)`), else any string (D14)."""
        span = _sub_span(args)
        alts = self.lit_alts(args[0]) if args else None
        if not alts or sum(len(a) for a in alts) > 64:
            return frozenset({("len", span) if span else ANY})
        out = set()
        for s in alts:
            if span == 1:
                out.update(s)
            else:
                out.update(s[i:j] for i in range(len(s)) for j in range(i + 1, len(s) + 1))
        return frozenset(_str_shape(x) for x in out)

    # ---- the constraints, one round
    def flow(self, F, args):
        """A call reaching F passes args to its parameters."""
        if F.raw is not None:
            return
        ps = self.params(F)
        for i, b in enumerate(ps):
            self.add(("b", id(b)), self.arg(args, i))
        if F.vararg:
            self.add(("va", id(F)), self.args_from(args, len(ps)))

    def top_params(self, F, shape=None):
        if F.raw is not None:
            return
        shape = self.top if shape is None else shape
        for b in self.params(F):
            self.add(("b", id(b)), shape)
        if F.vararg:
            self.add(("va", id(F)), shape)

    def write(self, w):
        if w.kind in ("localfunc", "func"):
            return frozenset({("fn", id(w.value))})
        if w.kind in ("param", "for") or w.value is NILV:
            return EMPTY
        if w.value is MULTI:
            return self.S(w.stmt.exprs[-1])
        return self.S(w.value)

    def assign_target(self, tg, shape):
        if type(tg) is Field:
            self.store(self.S(tg.obj), "k", tg.name, shape)
        elif type(tg) is Index and not _is_package(tg.obj):
            k = _key_literal(tg)
            if k is not None:
                self.store(self.S(tg.obj), "k", k, shape)
            else:
                self.store(self.S(tg.obj), self.kind(self.S(tg.key)), None, shape)

    def round(self):
        self.memo = {}
        for b in self.bindings:
            for w in b.writes:
                self.add(("b", id(b)), self.write(w))
        for F, exprs in self.returns:
            for x in exprs:
                self.add(("ret", id(F)), self.S(x))
        for s in self.assigns:
            vals = pair_values(len(s.targets), s.exprs)
            for tg, v in zip(s.targets, vals):
                if type(tg) is not Name:
                    self.assign_target(tg, EMPTY if v is NILV else
                                       self.S(s.exprs[-1]) if v is MULTI else self.S(v))
        for s in self.fstats:
            o = self.S(s.base)
            names = [p[0] for p in s.path] + ([s.method[0]] if s.method else [])
            for n in names[:-1]:
                o = self.member(o, n) | self.read(o, "k", n)
            self.store(o, "k", names[-1], frozenset({("fn", id(s.func))}))
        for e in self.tables:
            tid = id(e)
            for kind, key, val, _ in e.fields:
                if kind == "named":
                    self.store_t(tid, "k", key[0], self.S(val), set())
                elif kind == "index":
                    k = _ident(key)
                    if k:
                        self.store_t(tid, "k", k, self.S(val), set())
                    else:
                        self.store_t(tid, self.kind(self.S(key)), None, self.S(val), set())
                elif kind == "pos":
                    self.store_t(tid, "n", None, self.S(val), set())
        for e in self.calls:
            c, args = self.callee(e)
            for a in c:
                if a[0] == "fn":
                    self.flow(self.funcs[a[1]], args)
                elif a[0] == "lib":
                    self.lib_effects(a[1], e, args)
                elif a is FNQ:
                    for F in self.fns(self.get("UNK")):
                        self.top_params(F)
            if not self.key_escaped and self.opaque(c, e, args) and \
                    any(KEY in self.arg(args, i) for i in range(len(args))):
                self.escape()
        if not self.key_escaped and any(KEY in self.ret(id(F))
                                        for F in self.fns(self.get("UNK"))):
            self.escape()
        for s in self.genfors:
            self.loop(s)
        self.metamethods()

    def opaque(self, c, e, args):
        """Can a call with callee values c hand its arguments to code the
        analysis doesn't follow: a coroutine, a library function it doesn't
        know, a function from the library, or a table's __call?"""
        return any(a is FNQ or a is TBLQ or a[0] == "tbl" or
                   (a[0] == "lib" and (a[1].startswith("coroutine.")
                                       or self._lib(a[1], e, args) is None))
                   for a in c)

    def escape(self):
        """A key reached code the analysis doesn't follow: from now on any
        value that comes back from there may be a key."""
        self.key_escaped = True
        self.changed = True

    def lib_effects(self, name, e, args):
        A = lambda i: self.arg(args, i)
        if name == "table.insert" and args:
            self.store(A(0), "n", None, self.S(args[-1]))
        elif name == "table.pack":
            self.store_t(id(e), "n", None, self.args_from(args, 0), set())
        elif name == "table.move" and len(args) >= 4:
            self.store(A(4) if len(args) > 4 else A(0), "n", None, self.read(A(0), "n"))
        elif name == "table.sort":
            for F in self.fns(A(1)):
                self.top_params(F, self.read(A(0), "n"))
        elif name == "setmetatable":
            mt = frozenset(a for a in A(1) if a[0] == "tbl")
            if any(a[0] != "tbl" for a in A(1)):
                mt = mt | {TBLQ}
            for a in A(0):
                if a[0] == "tbl":
                    self.add(("mt", a[1]), mt)
        elif name == "pcall":
            for F in self.fns(A(0)):
                self.flow(F, args[1:])
        elif name == "xpcall":
            for F in self.fns(A(0)):
                self.flow(F, args[2:])
            for F in self.fns(A(1)):
                self.top_params(F)
        elif name == "require":
            F = self.module(args)
            if F is not None:                   # a module's `...`: its name
                self.top_params(F, frozenset(_str_shape(m) for m in self.lit_alts(args[0])))
        elif name in ("coroutine.create", "coroutine.wrap") or \
                self._lib(name, e, args) is None:
            # coroutines, and library functions the analysis doesn't know,
            # may call a program function they hold with anything, or hand it
            # back (coroutine.wrap): it escapes. (map's remap callback gets
            # numbers; the rest of the library calls nothing.)
            for i in range(len(args)):
                fs = self.fns(A(i))
                for F in fs:
                    self.top_params(F)
                self.add("UNK", frozenset(("fn", id(F)) for F in fs))

    def loop(self, s):
        names = [n.b for n in s.names]
        e0 = s.exprs[0]
        it = self.S(e0)
        # the table pairs/ipairs/next walks: pairs(t), ipairs(t), or `next, t`
        if type(e0) in (Call, Method):
            c, args = self.callee(e0)
            walked = self.arg(args, 0) if any(a[0] == "lib" and a[1] in ("pairs", "ipairs")
                                              for a in c) else frozenset({TBLQ})
        else:
            walked = self.S(s.exprs[1]) if len(s.exprs) > 1 else frozenset({TBLQ})
        for a in it:
            if a == ("lib", "next"):
                self.add(("b", id(names[0])), frozenset({KEY}) | self.get("PAIRS"))
                for b in names[1:]:
                    self.add(("b", id(b)), self.read(walked, "s") | self.get("PAIRS"))
            elif a == ("lib", "<ipairs>"):
                for b in names[1:]:
                    self.add(("b", id(b)), self.read(walked, "n"))
            elif a == ("lib", "<gmatch>"):
                for b in names:
                    self.add(("b", id(b)), frozenset({ANY}))
            elif a[0] == "fn":
                ret = self.ret(a[1])
                for b in names:
                    self.add(("b", id(b)), ret)
                state = set(it) | self.get(("b", id(names[0])))
                for x in s.exprs[1:]:
                    state |= self.S(x)
                self.top_params(self.funcs[a[1]], frozenset(state))
            elif (a[0] == "lib" and a[1] not in LIB_TABLES) or a is FNQ:
                for b in names:
                    self.add(("b", id(b)), self.top)

    def metamethods(self):
        """Functions the runtime calls (spec D14): stored under a `__` key in
        any table, or under any string key when one could spell a
        metamethod (<dyn>)."""
        dyn = self.fns(self.get("ALLS")) if self.dyn_mm else []
        keys = [k[1] for k in list(self.val) if type(k) is tuple and k[0] == "kall"
                and k[1].startswith("__")]
        for name in keys + (["<dyn>"] if dyn else []):
            fs = dyn if name == "<dyn>" else self.fns(self.get(("kall", name)))
            for F in fs:
                rets = self.ret(id(F))
                if name in ("__index", "__newindex", "<dyn>"):
                    ps = self.params(F) if F.raw is None else []
                    if ps:
                        self.add(("b", id(ps[0])), frozenset({TBLQ}))
                    if len(ps) > 1:
                        self.add(("b", id(ps[1])), frozenset({KEY}))
                    for b in ps[2:]:
                        self.add(("b", id(b)), self.get("GALL"))
                    if F.vararg:
                        self.add(("va", id(F)), self.get("GALL"))
                    if name != "__newindex":
                        self.add("IDXRET", rets)
                if name not in NOT_CALLED_MM:
                    self.top_params(F, TOP)     # an operand may be a key
                    if name in ARITH_MM or name == "<dyn>":
                        self.add("OPS", rets)
                    if name in ("__call", "<dyn>"):
                        self.add("CALLRET", rets)
                    if name in ("__tostring", "<dyn>"):
                        self.add("TSRET", rets)
                    if name in ("__pairs", "<dyn>"):
                        self.add("PAIRS", self.top)

    def solve(self, rounds=200):
        for _ in range(rounds):
            self.changed = False
            self.round()
            if not self.changed:
                self.memo = {}
                return True
        return False


class KeyOff(Exception):
    """Key renaming can't be proven safe: the reason, with its code line."""


def pass_keys(info, report):
    """Rename table keys (spec R13). Returns how many keys were renamed (0
    when the pass is off; report.keys_off says why)."""
    report.keys_renamed, report.keys_kept, report.keys_off = 0, {}, None
    try:
        return _pass_keys(info, report)
    except KeyOff as e:
        report.keys_off = str(e)
        return 0


def _pass_keys(info, report):
    prog = info.prog
    if not info.whole:
        raise KeyOff("a module on its own (fragment mode): its keys are its interface")
    if info.dynamic is not None:
        raise KeyOff(f"dynamic access ({info.dynamic})")
    fl = _KeyFlow(info)
    if fl.raws:
        raise KeyOff(f"line {fl.raws[0].raw.line}: code kept by NOMINIFY is not analysed,"
                     " and may use any key")

    # every key position (D13) and every value literal
    sites, lits = [], set()
    def note(name, node, how):
        sites.append((name, node, how))
    for s in fl.fstats:
        for i, (name, _) in enumerate(s.path):
            note(name, s, ("path", i))
        if s.method:
            note(s.method[0], s, "method")
    def visit(e):
        t = type(e)
        if t in (Field, Method):
            note(e.name, e, "attr")
        elif t is Index:
            k = _key_literal(e)
            if k is not None:
                note(k, e, "index")
        elif t is Table:
            for f in e.fields:
                if f[0] == "named":
                    note(f[1][0], f, "named")
                elif f[0] == "index" and _ident(f[1]) is not None:
                    note(_ident(f[1]), f, "ctor")
    keylits = set()
    def mark(e):
        if type(e) is Index and _key_literal(e) is not None:
            keylits.add(id(e.key))
        elif type(e) is Table:
            keylits.update(id(f[1]) for f in e.fields if f[0] == "index" and _ident(f[1]))
    walk_exprs(prog, mark)
    def literal(e):
        if type(e) is Lit and e.kind == "string" and id(e) not in keylits:
            v = str_value(e.text)
            if v is not None:
                lits.add(v.decode("latin-1"))
    walk_exprs(prog, literal)
    walk_exprs(prog, visit)

    fl.dyn_mm = any(s.startswith("__") for s in lits)
    if not fl.solve():
        raise KeyOff("the analysis did not settle")

    # what reaches each key position and each place a key is looked at (R13d-f)
    keep_lit, keep_re, keep_len = set(), set(), [0]
    def key_check(shape, line, what):
        for a in shape:
            if a is ANY:
                raise KeyOff(f"line {line}: {what} can be a string built at runtime")
            if a[0] == "lit":
                keep_lit.add(a[1])
            elif a[0] == "re":
                keep_re.add(a[1])
            elif a[0] == "len":
                keep_len[0] = max(keep_len[0], a[1])
    def seen(shape, line, what):
        if KEY in shape:
            raise KeyOff(f"line {line}: a table key {what}, so its spelling would show")
    S = fl.S
    def builds_string(r):
        """gsub's replacement is a string: a literal, a concatenation, or a
        call that can only be tostring or a string function."""
        while type(r) is Paren:
            r = r.e
        if (type(r) is Lit and r.kind == "string") or type(r) is Func or \
                (type(r) is Bin and r.op == ".."):
            return True
        if type(r) in (Call, Method):
            c = fl.callee(r)[0]
            return bool(c) and all(a[0] == "lib" and (a[1] == "tostring"
                                                      or a[1].startswith("string."))
                                   for a in c)
        return False
    def check(e):
        t = type(e)
        if t is Index and _key_literal(e) is None and not _is_package(e.obj):
            key_check(S(e.key), e.line, "a table key")
        elif t is Table:
            for f in e.fields:
                if f[0] == "index" and _ident(f[1]) is None:
                    key_check(S(f[1]), e.line, "a table key")
        elif t is Bin:
            a, b = S(e.a), S(e.b)
            if e.op in ("==", "~="):
                if KEY in a:
                    key_check(b, e.line, "a string compared with a key")
                if KEY in b:
                    key_check(a, e.line, "a string compared with a key")
            elif e.op == "..":
                seen(a | b, e.line, "is joined into a string")
            elif e.op in ("<", "<=", ">", ">="):
                seen(a | b, e.line, "is compared by order")
        elif t is Un and e.op == "#":
            seen(S(e.a), e.line, "is measured with #")
        elif t in (Call, Method):
            c, args = fl.callee(e)
            for a in c:
                if a[0] == "lib":
                    name = a[1]
                    if name == "string.gsub" and len(args) > 2 and not builds_string(args[2]):
                        raise KeyOff(f"line {e.line}: gsub's replacement may be a table,"
                                     " whose keys gsub looks up by the captured text")
                    if name in ("table.concat", "table.sort") and \
                            (name == "table.concat" or len(args) < 2):
                        seen(fl.read(fl.arg(args, 0), "n"), e.line,
                             f"may be in a list given to {name}")
                    if name not in KEY_BLIND and not name.startswith("math."):
                        for x in (args[1:] if name == "assert" else args):
                            seen(S(x), e.line, f"is passed to {name}")
                elif a is FNQ:
                    for x in args:
                        seen(S(x), e.line, "is passed to a function from the library")
    walk_exprs(prog, check)

    # what keeps its name (R13b-d)
    patterns = [re.compile(r, re.S) for r in sorted(keep_re)]
    def spelled(name):
        """Could a string built at runtime that reaches a key be name?"""
        return name in keep_lit or len(name) <= keep_len[0] or \
            any(p.fullmatch(name) for p in patterns)
    reasons = {}
    def why(name):
        if name in LIBRARY_KEYS or name.startswith("__"):
            return "library or metamethod"
        if name in lits:
            return "also a string literal"
        if spelled(name):
            return "a key built from strings could spell it"
        return None
    count, first = {}, {}
    for i, (name, _, _) in enumerate(sites):
        count[name] = count.get(name, 0) + 1
        first.setdefault(name, i)
    fixed = set(LIBRARY_KEYS) | lits | keep_lit
    cands = []
    for name in count:
        r = why(name)
        if r:
            reasons.setdefault(r, set()).add(name)
            fixed.add(name)
        else:
            cands.append(name)
    cands.sort(key=lambda n: (-count[n], first[n]))

    def usable(n):
        return n[0] != "_" and not spelled(n)
    # a key the pool can't shorten keeps its name, and so leaves the pool:
    # repeat until that settles
    stay = {n for n in cands if len(n) == 1}
    while True:
        pool = (n for n in name_pool(fixed | stay) if usable(n))
        new, more = {}, set()
        for n in cands:
            if n in stay:
                continue
            p = next(pool)
            if len(p) < len(n):
                new[n] = p
            else:
                more.add(n)
        if not more:
            break
        stay |= more
    if not new:
        report.keys_kept = {r: sorted(v) for r, v in reasons.items()}
        return 0

    # rename every site; a key literal becomes a field (t.k, {k=})
    for name, node, how in sites:
        n = new.get(name, name)
        if how == "attr":
            node.name = n
        elif how == "index":
            node.__class__ = Field
            node.name = n
            del node.key
        elif how == "named":
            node[1] = (n, node[1][1])
        elif how == "ctor":
            node[0], node[1] = "named", (n, node[1].line)
        elif how == "method":
            node.method = (n, node.method[1])
        else:
            i = how[1]
            node.path[i] = (n, node.path[i][1])
    lines = {}
    for name, node, how in sites:
        if name in new and name not in lines:
            lines[name] = node[1][1] if type(node) is list else node.line
    for name in cands:
        if name in new:
            report.renames.append((new[name], name, "field", lines[name]))
    report.keys_renamed = len(new)
    report.keys_kept = {r: sorted(v) for r, v in reasons.items()}
    return len(new)


# =============================================================================
# Layout (spec R3) and the max pipeline
# =============================================================================

def layout(toks, width=120):
    """Pack tokens into lines <= width; a new line at every function start.
    A kept comment ends its line; one that had its own line(s) in the source
    starts one too."""
    lines, first = [], []
    cur, cur_len, prev, floor = [], 0, None, 0
    for kind, text, line in toks:
        if kind == "nl":
            if cur:
                lines.append("".join(cur)); cur, cur_len = [], 0
            prev = None
            continue
        line = max(line, floor)       # the line after a kept comment: after it
        if kind == "comment":
            if cur and text.own_line:
                lines.append("".join(cur)); cur = []
            if cur:
                cur.append(" " + text)
            else:
                cur = [text]; first.append(line)
            floor = line + text.count("\n") + 1
            first.extend(range(line + 1, floor))
            lines.append("".join(cur)); cur, cur_len, prev = [], 0, None
            continue
        floor = 0
        # a protected body is verbatim, newlines and all: only its first line
        # counts toward this line's width, and its later lines are lines too
        tlen = len(text.split("\n", 1)[0]) if kind == "raw" else len(text)
        if not cur:
            cur, cur_len = [text], tlen; first.append(line)
        else:
            sep = " " if _needs_space(prev[0], prev[1], kind, text) else ""
            if cur_len + len(sep) + tlen > width:
                lines.append("".join(cur))
                cur, cur_len = [text], tlen; first.append(line)
            else:
                cur.append(sep + text); cur_len += len(sep) + tlen
        if kind == "raw" and "\n" in text:
            nl = text.count("\n")
            first.extend(range(line + 1, line + nl + 1))
            cur_len = len(text) - text.rfind("\n") - 1
        prev = (kind, text)
    if cur:
        lines.append("".join(cur))
    return "\n".join(lines), first


# What each option saved, by source line: measured only (savings=True), so
# no pass depends on it.
SAVINGS = ("comments", "whitespace", "constants", "extra", "rename-vars", "rename-functions",
           "rename-tables")


class Savings:
    """What minification did to each source line, in UTF-8 bytes: lines
    maps line -> {"source": bytes before, "final": bytes after, and an entry
    per SAVINGS option for what it removed}. An option's entry is negative
    where it added bytes (a constant longer than its name, an alias's
    declaration), and for a whole module it can land on other lines than the
    ones it came from: an inlined constant's bytes move to where it is read.
    source - final is the sum of the options' entries.

    left:  what the output is made of, [(label, bytes)], summing to its size
    names: the names that stayed, longest total first, [(name, bytes)]
    (left and names: past comments only; empty otherwise)"""

    def __init__(self):
        self.lines, self.left, self.names = {}, [], []

    def add(self, key, counts):
        """Add {line: bytes} to key."""
        for line, n in counts.items():
            if n:
                d = self.lines.setdefault(line, {})
                d[key] = d.get(key, 0) + n

    def shift(self, by):
        self.lines = {line + by: d for line, d in self.lines.items()}

    def group(self, key_of):
        """{key_of(line): {key: bytes}}, in order of each group's first line."""
        out = {}
        for line in sorted(self.lines):
            g = out.setdefault(key_of(line), {})
            for k, n in self.lines[line].items():
                g[k] = g.get(k, 0) + n
        return out

    def total(self):
        return self.group(lambda line: None).get(None, {})

    @classmethod
    def unchanged(cls, src):
        sv = cls()
        sv.add("source", _src_lines(src)); sv.add("final", _src_lines(src))
        return sv


def _nbytes(s):
    return len(s.encode("utf-8"))


def _src_lines(src):
    """{line: bytes} of src, each line with its newline."""
    rows = src.split("\n")
    out = {i: _nbytes(r) + 1 for i, r in enumerate(rows, 1)}
    out[len(rows)] -= 1
    return out


def _tok_lines(toks):
    """{line: bytes} of the tokens' text, by the source line each came from."""
    out = {}
    for kind, text, line in toks:
        if kind != "nl":
            out[line] = out.get(line, 0) + _nbytes(text)
    return out


def _lin(*terms):
    """The sum of (sign, {line: bytes}) terms, line by line."""
    out = {}
    for sign, d in terms:
        for line, n in d.items():
            out[line] = out.get(line, 0) + sign * n
    return out


def _comment_lines(src, keep):
    """{line: bytes} of the comments the max pipeline drops (all but those
    in keep's spans), by the line each starts on."""
    starts, out = [a for a, _ in keep], {}
    for line, _, text, a, _ in _scan_comments(src)[0]:
        k = bisect.bisect_right(starts, a) - 1
        if k < 0 or a >= keep[k][1]:
            out[line] = out.get(line, 0) + _nbytes(text)
    return out


def _gone_lines(src, gone):
    """strip_comments' gone list as ({line: comment bytes}, {line: whitespace bytes})."""
    nls = [i for i, c in enumerate(src) if c == "\n"]
    com, ws = {}, {}
    for at, c, w in gone:
        line = bisect.bisect_left(nls, at) + 1
        com[line] = com.get(line, 0) + c
        ws[line] = ws.get(line, 0) + w
    return com, ws


def _final_lines(text, toks):
    """{source line: bytes} of the laid-out text: each token's bytes and the
    whitespace (or kept comment) before the next go to the token's line."""
    lines = []
    for kind, t, line in strip_nl(toks):
        if kind == "raw":
            lines.extend([line] * len(lex(t)))
        elif kind != "comment":
            lines.append(line)
    offs = []
    lex(text, offsets=offs)
    if not lines:
        return {1: _nbytes(text)} if text else {}
    bounds = [0] + offs[1:] + [len(text)]
    out = {}
    for k, line in enumerate(lines):
        out[line] = out.get(line, 0) + _nbytes(text[bounds[k]:bounds[k + 1]])
    return out


def _made_of(prog, toks, size, whole, keep_names, passes):
    """(left, names) for Savings: the output's bytes by what they are, and
    the names that stayed with their total bytes. passes: the ones that ran
    (which of the rename passes did)."""
    info = Info(prog, whole, keep_names)
    fields, opaque = [0], {}       # opaque: id(binding) -> uses inside protected bodies

    def stmts(blk):
        for s in blk.stmts:
            if type(s) is FuncStat:
                fields[0] += sum(_nbytes(f) for f, _ in s.path)
                fields[0] += _nbytes(s.method[0]) if s.method else 0
            if type(s) not in (LocalFunc, FuncStat):
                for sub in sub_blocks(s):
                    stmts(sub)

    def expr(e):
        t = type(e)
        if t in (Field, Method):
            fields[0] += _nbytes(e.name)
        elif t is Table:
            fields[0] += sum(_nbytes(k[0]) for kind, k, _, _ in e.fields if kind == "named")
        elif t is Func:
            stmts(e.body)
            # a protected body's names are in its raw text, not name tokens
            for b in getattr(e, "raw_bindings", ()):
                opaque[id(b)] = opaque.get(id(b), 0) + 1
    stmts(prog)
    walk_exprs(prog, expr)
    api = variables = functions = 0
    names = {}
    for b in list(info.globals.values()) + info.locals:
        n = _nbytes(b.name) * (len(b.occ) - opaque.get(id(b), 0))
        if b.reserved:
            api += n
        elif b.can_rename and b.is_function:
            functions += n
        elif b.can_rename:
            variables += n
        elif n:
            names[b.name] = names.get(b.name, 0) + n
    kinds = {}
    for t in toks:
        if t[0] != "nl":
            kinds[t[0]] = kinds.get(t[0], 0) + _nbytes(t[1])
    kept = sum(names.values())
    left = [("strings", kinds.get("string", 0)),
            ("numbers", kinds.get("number", 0)),
            ("keywords", kinds.get("keyword", 0)),
            ("operators and punctuation", kinds.get("op", 0)),
            ("table field and method names", fields[0]),
            ("TIC-80 and Lua names (spr, math, ...)", api),
            ("names never renamed (globals, NOMINIFY)", kept),
            ("renamed variable names" if "rename-vars" in passes
             else "variable names rename-vars would shorten", variables),
            ("renamed function names" if "rename-functions" in passes
             else "function names rename-functions would shorten", functions),
            ("goto labels", kinds.get("name", 0) - fields[0] - api - kept - variables
             - functions),
            ("kept verbatim by NOMINIFY", kinds.get("raw", 0) + kinds.get("comment", 0)),
            ("spaces and line breaks", size - sum(kinds.values()))]
    return [x for x in left if x[1]], sorted(names.items(), key=lambda x: (-x[1], x[0]))


class Report:
    def __init__(self):
        self.inlined, self.kept = {}, {}          # (name, line) -> details
        self.removed_code, self.removed_bindings = [], []
        self.removed_modules, self.renames, self.aliased = [], [], []
        self.shared = []                          # (literal, uses) shared by `literals`
        self.verbatim = []                        # lines of NOMINIFY-protected bodies
        self.nominify = []                        # (name, line) kept by NOMINIFY
        self.comments = []                        # lines of comments kept by NOMINIFY
        self.folded = self.sugar = self.merged = self.dropped_params = 0
        self.disqualified, self.zero_write, self.dynamic = {}, [], None
        self.keys_ran = False                     # rename-tables (spec R13)
        self.keys_renamed, self.keys_kept, self.keys_off = 0, {}, None
        self.sizes = []          # (pass, chars)
        self.rounds = 0
        self.savings = None      # Savings, when asked for

    off = 0                      # code line -> cart line offset (set by minify_cart_ex)

    def text(self, where=None):
        out = ["ticpak minify report", ""]
        out.append("size by pass (characters of token text):")
        for p, n in self.sizes: out.append(f"  {p:<10} {n:>8,}")
        out.append(f"fixpoint rounds: {self.rounds}")
        if self.savings is not None:
            out.extend([""] + savings_text(self.savings))
        if self.dynamic:
            out.append(f"DYNAMIC ACCESS ({self.dynamic}): global passes disabled")
        def sect(title, rows):
            out.append(""); out.append(f"{title} ({len(rows)})")
            out.extend("  " + r for r in rows)
        sect("constants inlined", [f"line {l}: {n} = {v}  ({k}, {r} reads)"
                                   for (n, l), (k, v, r) in sorted(self.inlined.items(), key=lambda x: x[0][1])])
        sect("constants kept by the size check", [f"line {l}: {n} = {v}  ({r} reads)"
                                                  for (n, l), (v, r) in sorted(self.kept.items(), key=lambda x: x[0][1])])
        out.append(""); out.append(f"expressions folded: {self.folded}")
        sect("code removed", [f"line {l}: {k}" for k, l in self.removed_code])
        sect("bindings removed", [f"line {l}: {n}" for n, l in self.removed_bindings])
        sect("modules removed", self.removed_modules)
        out.append(f"trailing unused parameters dropped: {self.dropped_params}")
        sect("aliased globals", [f"{k}  ({n} uses)" for k, n in self.aliased])
        sect("literals shared", [f"{k}  ({n} uses)" if n else k for k, n in self.shared])
        out.append(f"call sugar applied: {self.sugar}   local statements merged: {self.merged}")
        sect("UPPER_CASE names that are not constants",
             [f"{n}: {w}" for n, w in sorted(self.disqualified.items())])
        sect("globals never written (always nil)", self.zero_write)
        out.append(""); out.append(f"identifiers renamed: {len(self.renames)}")
        if self.keys_ran:
            if self.keys_off:
                out.append(f"table keys: not renamed - {self.keys_off}")
            else:
                out.append(f"table keys renamed: {self.keys_renamed}")
                for why, names in sorted(self.keys_kept.items()):
                    if why != "library or metamethod":
                        sect(f"table keys kept: {why}", names)
        sect("functions and modules kept verbatim by a NOMINIFY comment",
             [f"line {l}" for l in sorted(self.verbatim)])
        sect("names kept by a NOMINIFY comment",
             [f"line {l}: {n}" for n, l in sorted(self.nominify, key=lambda x: x[1])])
        sect("comments kept by NOMINIFY", [f"line {l}" for l in sorted(self.comments)])
        # every "line N" above is a code-section line; shift to cart lines and
        # let the caller name the source file (ticpak passes its origin map)
        def fix(m):
            n = int(m.group(1)) + self.off
            return where(n) if where else f"line {n}"
        return re.sub(r"\bline (\d+)", fix, "\n".join(out)) + "\n"


def savings_text(sv, names=8):
    """Savings totals as report lines: bytes saved per option, what the
    output is made of, and the biggest names that stayed (no `line N`
    text: Report.text rewrites those)."""
    tot = sv.total()
    out = ["bytes saved by option (UTF-8; negative: it added bytes):"]
    out.append(f"  {'source':<16} {tot.get('source', 0):>8,}")
    for k in SAVINGS:
        out.append(f"  {k:<16} {tot.get(k, 0):>8,}")
    out.append(f"  {'after':<16} {tot.get('final', 0):>8,}")
    if sv.left:
        out += ["", "what the minified code is made of (bytes):"]
        out += [f"  {n:>8,}  {what}" for what, n in sv.left]
    if sv.names[:names]:
        out += ["", "biggest names that stayed (bytes, all uses):"]
        out += [f"  {n:>8,}  {name}" for name, n in sv.names[:names]]
    return out


class Result:
    def __init__(self, text, report, renames, line_map, savings=None):
        self.text, self.report, self.renames, self.line_map = text, report, renames, line_map
        self.savings = savings


def toklen(toks):
    return sum(len(t[1]) for t in toks if t[0] != "nl")

def minify_max(src, whole_program=True, passes=None, width=120, inline_all=False,
               reflow=True, nomi=None, savings=False, fixpoint_only=False):
    """The max pipeline. Returns a Result (text, report, renames, line_map,
    savings). reflow: pack lines to `width` (the whitespace option); False
    keeps the source's line breaks. nomi: the source's NOMINIFY Directives
    (found here when None). savings: also measure what each option saved
    (Result.savings, Report.savings). fixpoint_only: stop after the
    optimisation fixpoint and return its tokens' {line: bytes} (savings'
    constants-alone run)."""
    passes = set(ALL_PASSES if passes is None else passes)
    unknown = passes - set(ALL_PASSES)
    if unknown:
        raise ValueError(f"unknown pass(es): {', '.join(sorted(unknown))}")
    if nomi is None:
        nomi = directives(src)
    rep = Report()
    offs = []
    toks = lex_lines(src, offs)
    rep.sizes.append(("input", toklen(toks)))
    toks = protect(src, toks, offs, nomi)
    rep.verbatim = [t[2] for t in toks if t[0] == "raw"]
    prog = reparse(toks)
    stage = {"input": _tok_lines(toks)} if savings else None

    def info_of(prog):
        info = Info(prog, whole_program, nomi.names, "rename-functions" in passes)
        rep.nominify = info.kept
        return info

    first = True
    for rnd in range(1, 21):
        before = [t[:2] for t in strip_nl(toks)]
        if passes & {"fold", "inline", "dce"}:
            info = info_of(prog)
            reasons = analyze_constants(info)
            if first:
                rep.disqualified = reasons
                rep.dynamic = info.dynamic
                rep.zero_write = sorted(b.name for b in info.globals.values()
                                        if not b.reserved and not b.pinned and not b.writes and b.reads
                                        and whole_program and info.dynamic is None)
            Folder(info, ("fold" in passes, "inline" in passes, "dce" in passes), rep,
                   inline_all, renaming="rename-vars" in passes).block(prog)
            pass_tidy(prog)
            toks = emit_tree(prog); prog = reparse(strip_nl(toks))
        if "shake" in passes:
            info = info_of(prog)
            sh = Shaker(info, rep); sh.run(); sh.prune_block(prog)
            toks = emit_tree(prog); prog = reparse(strip_nl(toks))
        elif "inline" in passes:
            # constants without unused: still delete the inlined definitions
            info = info_of(prog)
            analyze_constants(info)
            ConstDropper(info, rep).prune_block(prog)
            toks = emit_tree(prog); prog = reparse(strip_nl(toks))
        first = False
        rep.rounds = rnd
        if [t[:2] for t in strip_nl(toks)] == before:
            break
    else:
        raise AssertionError("minify: optimisation passes did not reach a fixpoint")
    if fixpoint_only:
        return _tok_lines(toks)
    rep.sizes.append(("optimised", toklen(toks)))
    if savings:
        stage["optimised"] = _tok_lines(toks)

    if "rename-tables" in passes:
        rep.keys_ran = True
        if pass_keys(info_of(prog), rep):
            toks = emit_tree(prog); prog = reparse(strip_nl(toks))
        rep.sizes.append(("keys", toklen(toks)))
    if savings:
        stage["keys"] = _tok_lines(toks)

    if "sugar" in passes:
        pass_sugar(prog, rep)
    def worst_upvals(prog):                       # Lua 5.3 allows 255 upvalues per function
        return max((len(f.upvals) for f in info_of(prog).funcs), default=0)
    if "alias" in passes:
        saved, saved_alias = emit_tree(prog), list(rep.aliased)   # sugar's edits included
        info = info_of(prog)
        if pass_alias(info, rep):
            toks = emit_tree(prog); prog = reparse(strip_nl(toks))
            worst = worst_upvals(prog)
            if worst > 250:
                toks, rep.aliased = saved, saved_alias
                rep.aliased.append(("(alias pass reverted: a function would need "
                                    f"{worst} upvalues)", 0))
                prog = reparse(strip_nl(toks))
    if "literals" in passes:
        saved, noted, limit = emit_tree(prog), len(rep.shared), None
        while pass_literals(info_of(prog), rep, "rename-vars" in passes, limit):
            toks = emit_tree(prog); prog = reparse(strip_nl(toks))
            worst = worst_upvals(prog)
            if worst <= 250:
                break
            # every shared literal a function reads is one more upvalue for it
            # and every function around it: share half as many and try again
            limit = (len(rep.shared) - noted) // 2
            del rep.shared[noted:]
            toks = saved; prog = reparse(strip_nl(toks))
            rep.shared.append((f"(sharing cut to {limit}: a function would need "
                               f"{worst} upvalues)", 0))
            noted = len(rep.shared)
    if "merge" in passes:
        info = info_of(prog)
        pass_merge(info, rep)
    pass_tidy(prog)
    toks = emit_tree(prog); prog = reparse(strip_nl(toks))
    rep.sizes.append(("small", toklen(toks)))
    if savings:
        stage["small"] = _tok_lines(toks)
    fn_saved = {}
    if passes & {"rename-vars", "rename-functions"}:
        info = info_of(prog)
        _, fn_saved = pass_rename(info, rep, variables="rename-vars" in passes)
        toks = emit_tree(prog)
        prog = reparse(strip_nl(toks))
    rep.sizes.append(("renamed", toklen(toks)))
    if savings:
        stage["renamed"] = _tok_lines(toks)
        stage["functions renamed"] = fn_saved
    rep.comments = [t[2] for t in toks if t[0] == "comment"]

    text, first_lines = layout(toks, width) if reflow else layout_lines(toks)
    # final proof: the text lexes back to exactly the emitted tokens (kept
    # comments lex to nothing) and parses
    final = []
    for t in strip_nl(toks):
        if t[0] != "comment":
            final.extend(lex(t[1]) if t[0] == "raw" else [t[:2]])
    if [tuple(t) for t in lex(text)] != final:
        raise AssertionError("minify: layout changed the token stream - refusing to emit")
    reparse(lex_lines(text))
    for i, ln in enumerate(text.split("\n")):
        if re.match(r"-- <[A-Z]", ln):
            raise AssertionError(f"minify: output line {i + 1} would read as an asset chunk marker")
    rep.sizes.append(("laid out", len(text)))
    line_map = list(enumerate(first_lines, 1))
    if savings:
        rep.savings = _max_savings(src, text, toks, prog, stage, passes, nomi,
                                   dict(whole_program=whole_program, width=width,
                                        inline_all=inline_all, reflow=reflow))
    return Result(text, rep, rep.renames, line_map, rep.savings)


def _max_savings(src, text, toks, prog, stage, passes, nomi, run):
    """The max pipeline's Savings, from its stages' {line: bytes}: the
    source, the tokens after protect() (input), after the fixpoint loop
    (optimised), after sugar/alias/merge (small), after rename (renamed),
    and the laid-out text. The fixpoint loop runs constants' pass (inline)
    together with extra's fold/dce/shake, so with both on, a second run
    with inline alone measures constants' share and extra gets the rest.
    One rename pass renames variables and functions together; what the
    functions' names saved is counted as it renames them."""
    sv = Savings()
    source, com = _src_lines(src), _comment_lines(src, nomi.keep())
    inp, opt, keys, small, ren, fn = (stage[k] for k in ("input", "optimised", "keys", "small",
                                                         "renamed", "functions renamed"))
    final = _final_lines(text, toks)
    fix = _lin((1, inp), (-1, opt))
    if "inline" in passes and passes & {"fold", "dce", "shake"}:
        renames = passes & {"rename-vars", "rename-functions"}
        alone = minify_max(src, passes={"inline"} | renames, nomi=nomi,
                           fixpoint_only=True, **run)
        const = _lin((1, inp), (-1, alone))
    else:
        const = fix if "inline" in passes else {}
    # pass_tidy (redundant `;`, trailing table separators, empty else/do)
    # runs with any option past comments: without extra's small passes, its
    # few bytes count as whitespace, the layout's clean-up
    tidy = "extra" if passes & {"sugar", "alias", "literals", "merge"} else "whitespace"
    sv.add("source", source)
    sv.add("comments", com)
    sv.add("whitespace", _lin((1, source), (-1, com), (-1, inp), (1, ren), (-1, final)))
    sv.add("constants", const)
    sv.add("extra", _lin((1, fix), (-1, const)))
    sv.add("rename-tables", _lin((1, opt), (-1, keys)))
    sv.add(tidy, _lin((1, keys), (-1, small)))
    sv.add("rename-vars", _lin((1, small), (-1, ren), (-1, fn)))
    sv.add("rename-functions", fn)
    sv.add("final", final)
    sv.left, sv.names = _made_of(prog, toks, _nbytes(text), run["whole_program"],
                                 nomi.names, passes)
    return sv


# =============================================================================
# Public API
# =============================================================================

def minify_ex(src, mode="max", whole_program=True, top_directive=True, savings=False,
              **opts):
    """mode: anything parse_options() takes - 'comments,rename-vars',
    'default', 'max', or a set of OPTIONS (empty: passthrough). top_directive: a NOMINIFY in
    the source's top comment block leaves it all alone (minify_cart_ex says
    False: a cart's top block is its header, checked there). savings: also
    measure what each option saved, by source line (Result.savings)."""
    o = parse_options(mode)
    if not o or (top_directive and top_block_nominify(src)):   # leave it alone
        return Result(src, None, [], [], Savings.unchanged(src) if savings else None)
    nomi = directives(src, top_directive)
    if o == {"comments"}:
        gone = [] if savings else None
        out = strip_comments(src, nomi.keep(), gone)
        if lex(out) != lex(src):                                   # safety net
            raise AssertionError("token stream changed - refusing to emit")
        sv = None
        if savings:
            sv, source = Savings(), _src_lines(src)
            com, ws = _gone_lines(src, gone)
            sv.add("source", source); sv.add("comments", com); sv.add("whitespace", ws)
            sv.add("final", _lin((1, source), (-1, com), (-1, ws)))
        return Result(out, None, [], [], sv)
    opts.setdefault("passes", [p for x in OPTIONS if x in o
                               for p in OPTION_PASSES.get(x, ())])
    return minify_max(src, whole_program=whole_program,
                      reflow="whitespace" in o, nomi=nomi, savings=savings, **opts)

def minify(src, mode="max", whole_program=True, **opts):
    """Minify Lua source; returns the text.

    mode: option names, e.g. 'comments,rename-vars' (see the module
    docstring), 'default' for every option but rename-functions and
    rename-tables, 'max' for every option (whole-program optimisation,
    minify-spec.md), or '' for none (passthrough).
    whole_program=False treats src as a fragment (one module on its own):
    globals are then never inlined, removed or renamed.
    """
    return minify_ex(src, mode, whole_program, **opts).text

def split_cart(text, meta_keys=None):
    """Split a text cart into (header, code, chunks).

    header -- the metadata lines (`-- title: ...`) found in the leading run of
              comment and blank lines, joined by newlines; other leading
              comments are dropped, except that a comment block holding
              NOMINIFY after the header block starts the code (spec R8i).
              meta_keys limits which keys count (ticpak
              passes the checker's REQUIRED_META + OPTIONAL_META); None accepts any
              `-- <word>:` line.
    code   -- everything after that leading run, up to the first asset chunk.
    chunks -- the asset sections from the first `-- <NAME>` marker to the end
              of the file, verbatim ("" when the text has none).
    """
    return _split_cart(text, meta_keys)[:3]

def _split_cart(text, meta_keys):
    body, chunks = text, ""
    for m in CHUNK_RE.finditer(text):
        rest = text[m.start():].split("\n")
        if all(l.lstrip().startswith("--") or not l.strip() for l in rest):
            body, chunks = text[:m.start()], text[m.start():]
            break
    keys = r"\w+" if meta_keys is None else "|".join(map(re.escape, meta_keys))
    meta_re = re.compile(r"^--\s*(%s)\s*:" % keys, re.I)
    lines = body.split("\n")
    h = 0
    while h < len(lines) and (lines[h].lstrip().startswith("--") or not lines[h].strip()):
        h += 1
    # The code starts early at a comment block holding NOMINIFY after the
    # header block (unless metadata tags follow it): the minifier keeps it
    # (spec R8i). A NOMINIFY in the header block itself is a whole-cart one.
    l = 0
    while l < h and not lines[l].strip():
        l += 1
    while l < h and lines[l].strip():
        l += 1
    while l < h:
        if not lines[l].strip():
            l += 1; continue
        b = l
        while l < h and lines[l].strip():
            l += 1
        if any(NOMINIFY_RE.search(x) for x in lines[b:l]) \
                and not any(meta_re.match(x) for x in lines[b:h]):
            h = b
            break
    header = "\n".join(l for l in lines[:h] if meta_re.match(l))
    return header, "\n".join(lines[h:]), chunks, h

def minify_cart_ex(text, mode=("comments",), meta_keys=None, savings=False, **opts):
    """minify_cart() returning a Result whose line_map is in cart lines:
    [(output cart line, input cart line)]. A NOMINIFY in the cart's top
    comment block (its metadata header block) leaves the whole cart alone;
    the metadata tags' own values (a title or desc that says "nominify")
    don't count. savings: Result.savings by cart line; the header block,
    its dropped comments and the asset sections count as line 1's."""
    unchanged = Savings.unchanged(text) if savings else None
    if not parse_options(mode):
        return Result(text, None, [], [], unchanged)
    keys = r"\w+" if meta_keys is None else "|".join(map(re.escape, meta_keys))
    meta_re = re.compile(r"^\s*--\s*(%s)\s*:" % keys, re.I)
    if top_block_nominify("\n".join("--" if meta_re.match(l) else l
                                    for l in text.split("\n"))):
        return Result(text, None, [], [], unchanged)
    header, code, chunks, h = _split_cart(text, meta_keys)
    if not header:
        raise ValueError("no metadata header comments found - refusing to minify")
    try:
        # the cart's top block was the header: the code's first comment
        # block, if any, is not a whole-module directive
        r = minify_ex(code, mode=mode, top_directive=False, savings=savings, **opts)
    except NominifyError as e:                  # code lines -> cart lines
        raise NominifyError(e.line + h, e.msg) from None
    # code that starts with a kept comment stays apart from the header block,
    # where it would read as part of the header (or a whole-cart directive)
    sep = "\n\n" if r.text.lstrip().startswith("--") else "\n"
    hl = header.count("\n") + len(sep)
    r.line_map = [(o + hl, i + h) for o, i in r.line_map]
    r.renames = [(n, o, k, l + h) for n, o, k, l in r.renames]
    if r.report is not None:
        r.report.off = h
    if savings:
        _header_savings(r.savings, text, h, header + sep, chunks)
    r.text = header + sep + r.text + "\n" + chunks
    return r


def _header_savings(sv, text, h, kept, chunks):
    """Shift a cart's code Savings to cart lines and add the header block
    (h lines, `kept` of it left), the newline after the code and the asset
    sections, all as line 1's."""
    sv.shift(h)
    rows = text[:len(text) - len(chunks)].split("\n")[:h]
    source = sum(_nbytes(r) + 1 for r in rows) + _nbytes(chunks)
    com = sum(_nbytes(r.strip()) for r in rows if r.strip() and r not in kept.split("\n"))
    final = _nbytes(kept) + 1 + _nbytes(chunks)
    sv.add("source", {1: source})
    sv.add("comments", {1: com})
    sv.add("whitespace", {1: source - com - final})
    sv.add("final", {1: final})
    if sv.left:
        sv.left.insert(0, ("metadata header and asset sections", final))

def minify_cart(text, mode=("comments",), meta_keys=None, **opts):
    """Minify a cart's code, passing its metadata header and asset chunks through.

    Returns header + "\\n" + minified code + "\\n" + chunks. An empty mode returns
    text unchanged. Raises ValueError when there is no metadata header, since a
    cart without one would lose its title/script fields.
    """
    return minify_cart_ex(text, mode, meta_keys, **opts).text
