# minify.py — Lua 5.3 minifier for TIC-80 carts

`ticpak/minify.py` is the minification stage of [`ticpak`](ticpak). Its
`max` mode is a whole-program optimiser for the bundled cart that `ticpak`
builds. It inlines constants, folds constant expressions, removes dead code and
unused definitions, renames non-function variables, and lays the result out with
one function start per line, wrapped at 120 columns. Header metadata and asset
chunks pass through unchanged. It uses only the Python standard library.

The contract `max` implements is [`minify-spec.md`](minify-spec.md). This page
covers usage, behaviour and testing.

## Options

Since 2026-10-03 minification is a set of options, combined with commas
(`--minify=comments,rename` in `ticpak`, `--mode=comments,rename` here):

| Option | What it does | Pass |
|---|---|---|
| `comments` | Removes comments and nothing else: indentation, blank lines and line breaks stay as written. A line that held only comments is dropped. Header metadata and asset chunks pass through. | (comment stripper) |
| `rename` | Variables get the shortest free names (1–2 letters). A `NOMINIFY` comment keeps a name: see [Keeping a name](#keeping-a-name-nominify). | rename |
| `constants` | Constant values are inlined and the constants' declarations removed. With `extra` off, a restricted removal deletes only constants nothing reads any more; with `rename` off, the size check costs names at their real length. | inline |
| `whitespace` | Extraneous newlines and whitespace removed: one function start per line, packed to 120 columns. **Without it, the source's line breaks are kept**, one space of indent per block level. | layout |
| `extra` | Every further optimisation, together: constant expressions evaluated, unreachable code removed, functions/variables/modules nothing uses removed, call sugar, API aliasing, `local` merging. | fold, dce, shake, sugar, alias, merge |

To run a subset of `extra`'s passes (bisecting a problem), use this tool's
`--passes=` directly; `ticpak` only offers them as one option.

Every option except `comments` works on the token stream, so choosing any of
them removes comments too (`comments` is added automatically).

| `ticpak` | Options | wavynavy code size (2026-10-03) |
|---|---|---|
| no `--minify` | none: passthrough | 154,092 |
| `--minify=comments` | `comments` | 66,262 |
| `--minify=constants` | `comments,constants` (line breaks kept) | 56,769 |
| `--minify=whitespace` | `comments,whitespace` | 54,981 |
| `--minify=rename,constants,extra` | line breaks kept | 47,560 |
| `--minify` | every option: the whole-program pipeline below, output identical to the old `max` mode | 42,039 |

In `ticpak`, no `--minify` means no minification, a bare `--minify` means
every option, and `--minify=OPTION,...` means just those. This module's API
and its `--mode` take the same comma-separated options (empty: passthrough),
plus `max` for every option. The `default`/`all`/`none` presets that existed
briefly on 2026-10-03 are gone.

> **Superseded 2026-10-03.** Until then there were three modes: `none`,
> `default` and `max`. The old `default` removed comments **and** compacted
> whitespace, keeping line breaks but re-indenting to one space per block
> (61,419 on wavynavy). No option set reproduces it exactly. `comments` alone
> keeps the original indentation, so it is larger: 66,262 on wavynavy. `comments,whitespace` packs lines and is smaller (54,981). `max`
> is unchanged: every option, `--minify` in `ticpak`.

## What `max` does

The passes run in a fixed order: fold, inline, dead-code removal and tree
shaking, repeated until nothing changes; then call sugar, aliasing, merging and
tidying; then renaming; then layout. Each pass re-parses the program, so it
always analyses the current code.

| Pass | Effect |
|---|---|
| **inline** | A variable written exactly once, with a constant scalar value (number, string, boolean or `nil`), has its reads replaced by the value. This covers globals such as `constants.lua`'s and ordinary locals alike. The definition is then removed. Tables and functions never qualify. A global qualifies only if it is assigned at the top level of a module and no read can run before that assignment. Inlining happens only when it doesn't grow the code: `len(literal) × reads ≤ declaration + reads × 2`. |
| **fold** | Constant expressions are evaluated with exact Lua 5.3 semantics (integer/float subtypes, wrapping, floor division, `%.14g` concatenation): `60*60` becomes `3600`, `'the answer is: '..1+3*2` becomes `'the answer is: 7'`. A result replaces the expression only when it is no longer than the source: `1/60` stays as written. `false and x` and `true and x` fold too, and a result that could be multiple values is parenthesised so it stays truncated to one. |
| **dce** | Removes `if`/`elseif` arms whose condition is known false. When the first known-true arm is reached, the arms after it are dropped. Also removes `while false` loops, numeric `for` loops that can never run, and code after `break`/`goto`/`return`. An unwrapped body that declares locals keeps its own `do … end` scope. |
| **shake** | Tree shaking by reachability, starting from the main chunk, the TIC-80 callbacks and every `require`d module. Unreachable functions are removed, including recursive ones, along with dead locals and globals whose initialiser is pure, `package.preload` modules that are never required, and trailing parameters that are never read. `local x = f()` with `x` dead becomes `f()`. Table fields are never removed. |
| **sugar** | `f("s")` becomes `f"s"`, and `f({…})` becomes `f{…}`. |
| **alias** | A heavily used API or library name (`spr`, `ipairs`, `math.floor`, …) gets a single local alias at the top of the main chunk. Every module is a closure nested inside the main chunk, so one alias covers all of them. This saves characters, and a local read is faster than a global one. It is skipped for any name the program writes, and reverted if a function would exceed Lua's 255-upvalue limit. |
| **merge** | Merges adjacent `local` statements (`local a=1 local b=2` becomes `local a,b=1,2`) when no initialiser reads an earlier name. |
| **rename** | Locals (including parameters, loop variables and labels) and non-function globals get one- or two-character names, the most-referenced first. Names are reused where scopes don't overlap. **Not renamed:** function names (so tracebacks stay readable), table fields and methods, the implicit `self`, and every TIC-80/Lua global (see [Reserved names](#reserved-names)), and any variable marked with a `NOMINIFY` comment (below). |
| layout | Every function definition starts a new line, at any depth. Otherwise tokens are packed into lines of at most 120 characters, breaking only between tokens. |

Run `ticpak build -f --minify` and read `dist/<name>.minify.txt` to see what each
pass did to a given cart.

### Keeping a name (NOMINIFY)

To stop `rename` shortening a particular variable, put `NOMINIFY` (any case)
anywhere in a comment on the line that **declares or assigns** it:

```lua
local player_speed = 3       -- tuning knob, NOMINIFY
high_score = 0               --[[ read by the debugger: nominify ]]
local enemy_count = 5
function TIC()
  local frame = player_speed + enemy_count + high_score
  frame = frame + 1          -- nominify  (an assignment marks it too)
end
```

With `rename` on, `player_speed`, `high_score` and `frame` keep their names at
every occurrence, and `enemy_count` becomes `a`. The comments are removed as
usual:

```lua
local player_speed=3
high_score=0
local a=5
function TIC()
 local frame=player_speed+a+high_score
 frame=frame+1
end
```

- **What counts:** a `local` declaration, a parameter or `for` variable, or an
  assignment, on the marked line. A line that only *reads* the variable
  marks nothing. Marking any one of a variable's declaration or assignment
  lines keeps it everywhere.
- **What doesn't:** `NOMINIFY` inside a string. A block comment counts for the
  line it starts on.
- **Only renaming is affected.** A marked constant can still be inlined by
  `constants`, and a marked variable nothing uses can still be removed by
  `extra`.
- The report (`dist/<name>.minify.txt`) lists every name kept this way under
  "names kept by a NOMINIFY comment", with the marker's line.

Contract: [`minify-spec.md`](minify-spec.md) R8g.

### Keeping a function or module verbatim (NOMINIFY)

The same marker can keep a whole function, a whole module or the whole cart
out of minification: no option touches it, so it comes out byte for byte,
comments, spacing and names included.

**A function** is kept when a comment containing `NOMINIFY` is on its
declaration line, or in the comment block directly above or below that line:

```lua
local function draw_hud(x, y) -- NOMINIFY: on the declaration line
  ...
end

-- NOMINIFY: the comment block directly above
function debug_overlay()
  ...
end

function tuned_curve(t)
  -- NOMINIFY: the comment block directly below the declaration
  return t * t * (3 - 2 * t)
end

local ease = function(t) -- NOMINIFY: function expressions work too
  ...
end
```

**A module** is kept when the comment block at its top holds a `NOMINIFY`.
In a bundle that is the first comment lines of the module file:

```lua
-- physics: NOMINIFY - ship this module exactly as written
local M = {}
...
```

**The whole cart** is kept when `main.lua`'s top comment block, its metadata
header block, holds a `NOMINIFY` comment line. The header tags' own values,
such as a title that happens to contain the word, don't count.

Rules:

- **A blank line ends a comment block.** A `NOMINIFY` comment, then a blank
  line, then a function does not protect the function. At a module's top it
  is a module-level directive; anywhere else it protects nothing.
- **Module level wins.** A module's top block that runs straight into a
  function declaration could be read either way; the whole module is kept.
  Anything protected inside something else protected is simply part of it.
- **What the kept code uses is left alone everywhere.** Every variable whose
  name appears inside a kept function or module is:
  - never renamed;
  - never inlined as a constant;
  - never aliased;
  - never removed as unused.
  The kept code may read or write any of them. A kept function is never
  removed as unused either, even with `extra`.
- **Exactly what is kept:** the parameter list and body, from `(` to `end`.
  `local function name` and `function name` in front of it are emitted as
  usual. The directive comment itself goes like any other comment, unless it
  is inside the body.
- The report lists every kept function and module under "functions and
  modules kept verbatim by a NOMINIFY comment", with the line each starts on.

Contract: [`minify-spec.md`](minify-spec.md) R8h.

### Whole-program assumptions

`max` treats its input as the **whole program**, which the bundle `ticpak`
builds is. This is what makes global inlining, removal and renaming safe:

- **Dynamic global access** (`_G`, `_ENV`, `load`, `loadstring`, `dofile`,
  `loadfile`, `rawget`, `rawset`, `rawequal`, `debug`, or a `require` whose
  argument isn't a literal) can reach a global through a computed name. If any of
  these appears, every pass that touches globals is turned off, and the report
  says which line triggered it. None of the repo's ports use them (checked
  2026-10-02).
- **Load order.** A global constant read at the top level of a module counts as
  safe only if a module that runs earlier (in the order of literal `require`
  calls) has already assigned it. Reads inside functions are assumed to happen
  after loading. If `require` is used any other way, such as
  `pcall(require, "m")`, every module is kept and only the main chunk's order is
  trusted.
- **A global that is never written** is always `nil`, so conditions on it fold.
  The report lists such globals, because they are often typos.
- **Fragment mode** (`whole_program=False`, CLI `--fragment`) is for minifying
  one module on its own. Globals are then never inlined, removed or renamed.
  beyondcastlewolfenstein's `check.py` uses it for per-module size estimates.

### Why it can't miscompile the way npm luamin did

npm luamin re-prints expressions with Lua 5.1 precedence and silently turned
`(x & y) + z` into `x&y+z`, which Lua 5.3 reads as `x & (y+z)` (wavynavy,
2026-09-13). `max` uses its own parser, which builds a
**lossless concrete tree**: every token, parenthesis and separator is kept.
After every parse, the minifier checks that the tree re-emits exactly the tokens it
was built from. The passes only ever do three things:
- delete statements;
- replace a whole subexpression by a literal, parenthesising it when it is
  negative before `^` or sits in prefix position (`("x"):rep(3)`, `(-1)^2`);
- rename identifiers.

No expression is ever regrouped. The finished text is lexed and parsed again
before it is returned.

## Outputs

`ticpak --minify=` with any option past `comments` writes, next to `dist/<name>.lua`:

- **`dist/<name>.minify.txt`**, the pass report, with sizes after each pass and
  the lists below, each entry naming its `file:line`:
  - the constants inlined, and those kept by the size check;
  - the code, bindings and modules removed;
  - the names aliased;
  - the UPPER_CASE names that are **not** constants, with the reason (for
    example `BANK: value is not a constant scalar (table)`);
  - the globals that are never written.
- **`dist/<name>.minify.json`**, for decoding an error from the packaged cart:
  - `"lines"` maps each output line to the source file and line of its first
    token (TIC-80 reports `[string "…"]:37:`, so look up `"37"`);
  - `"renames"` lists every renamed identifier with its original name and
    source line.

## Running it

From `ticpak` (the normal route):

```
ticpak build -f --minify           # from the folder holding main.lua
```

Standalone, writing to stdout. Whole-program `max` needs the **unminified
bundle**, which `ticpak` without `--minify` writes to `dist/<name>.lua`. A lone
module or `main.lua` must use `--fragment`, or the globals its other modules
define would look as if they were never written.

```
ticpak build -f --minify=comments      # bundle, comments out (see below)
ticpak minify --cart --mode=max --report=wn.txt dist/wavynavy.lua > wn.lua
ticpak minify --mode=max --fragment enemies.lua
ticpak minify --cart --mode=max --passes=fold,inline,dce,shake --width=100 dist/wavynavy.lua
```

| Option | Meaning |
|---|---|
| `--mode=OPTION,…` | Comma-separated options as in [Options](#options), or `max` for all of them. The CLI defaults to `max`. |
| `--cart` | Treat the file as a text cart: header + code + asset chunks, through `minify_cart()`. |
| `--fragment` | Not a whole program (one module): leave globals alone. |
| `--passes=a,b,…` | Run a subset of `fold,inline,dce,shake,rename,sugar,alias,merge` by internal pass name (overrides the passes the options chose), to bisect a problem. Tidying and layout always run. |
| `--width=N` | Line width for the layout (default 120). |
| `--inline=all` | Inline every constant, ignoring the size check. |
| `--report=FILE` | Write the pass report. |

As a module (`ticpak` uses `minify_cart_ex`):

```python
from ticpak import minify
text = minify.minify(src, mode="max")                   # str; "max" = every option
text = minify.minify(src, mode="comments,rename")       # any options
minify.parse_options("comments,rename")                 # -> frozenset({...})
r = minify.minify_cart_ex(cart_text, mode="max", meta_keys=KEYS)
r.text, r.report.text(), r.renames, r.line_map          # Result
minify.minify(module_src, whole_program=False)          # fragment
```

`split_cart()` / `minify_cart()` pass the header and asset chunks through:

- **Header:** the leading `-- key:` metadata lines.
- **Asset chunks:** they start at the first line that is *only* a chunk marker
  (`-- <MAP>`) with nothing but comments after it. Detection is strict because an
  inlined module's prose can begin `-- <MAP> region …`, as wavynavy's
  `a2boot.lua` does.

TIC-80's own loader is less strict. So an unminified wavynavy bundle (no
`--minify`) would fail to boot, because it still contains that comment; any
minify option strips comments, so it is unaffected. Since 2026-10-03
`ticpak` checks for such a line before booting and stops, naming its source
line (`a2boot.lua:14`).

## Reserved names

The globals the minifier never touches are:
- the 82 that TIC-80 1.2.0 Pro exposes at `BOOT` (the standard library plus the
  API);
- the callbacks `TIC BOOT SCN BDR OVR MENU`;
- a few standard names TIC-80 lacks (`utf8`, `os`, `io`, `unpack`, …);
- `_ENV`, `_G`, `self` and `arg`.

The TIC-80 list is generated by probing the real binary, and it is **embedded**
in `minify.py` between `# <reserved>` markers. Regenerate it after a TIC-80
upgrade (this runs one headless boot):

```
python scripts/update_reserved.py            # rewrites the block in ticpak/minify.py
python scripts/update_reserved.py --print    # show it without writing
```

## Testing

The tests need `lupa`, which embeds a real Lua 5.3 (`pip install lupa`; it is a
test dependency only, and packaging never needs it; `pip install -e ".[test]"`
installs it).

```
python tests/minify/run.py             # fold fuzz + bytecode proof + fixtures
python tests/minify/difftest.py --all  # every game under $TICPAK_GAMES, original vs max
python tests/options/test_options.py   # every option combination
```

- **`tests/options/`** runs all 32 subsets of the five options (17 distinct
  sets) on sample carts with assets in several layouts. For each, it checks
  structure, that the metadata header and assets come through byte-identical,
  each option's effect on and off, and identical behaviour under Lua 5.3
  against a logging TIC-80 stand-in. It also covers sizes, NOMINIFY and
  `ticpak.bundle()`. Opt-in, it boots every set's bundle in TIC-80
  (`TICPAK_BOOT=1`, about 3 minutes). Details:
  [tests/options/README.md](../tests/options/README.md).

- **`run.py fold`** generates thousands of random constant expressions. Each one
  the minifier folds must match real Lua exactly (value, integer/float subtype,
  bytes), and the literal it would emit must read back as the same value.
  Result: 2,167 folds, 0 mismatches.
- **`run.py bytecode`** (needs `$TICPAK_GAMES`, a folder of `<game>/tic80/`
  projects) applies local renaming to every game's bundle with each
  token kept on its source line, then requires the stripped bytecode to be
  byte-identical. Lua 5.3's `string.dump(f, true)` still records each
  function's first and last line, so the proof can't use the 120-column layout.
  Result: identical on all 8 ports, 575 KB of bytecode.
- **`run.py fixtures`** runs [`tests/minify/fixtures.lua`](../tests/minify/fixtures.lua):
  19 small programs aimed at the risky transforms (negative literals in every
  operator position, and/or with multiple values, shadowing, multiple
  assignment, varargs, goto, `repeat` scope, string escapes, modules, indirect
  `require`). Each runs before and after minification, and the output must
  match. Add a case with every new rule or bug fix.
- **`difftest.py`** (also on `$TICPAK_GAMES`) bundles a game exactly as `ticpak` does, minifies it, and
  runs both builds in lockstep under a stub of the TIC-80 API:
  - RAM, map banks and flags come from the cart's chunks, and `sync()` swaps
    banks;
  - button input is scripted, and `time()` runs off a frame clock;
  - `pairs` iterates in a stable order, and each build has its own
    `math.random` (5.3's is C `rand()`, one generator shared by every Lua state
    in the process).

  Every output call (drawing, sound, `poke`, `pmem`, `trace`, …) is logged with
  exact arguments, and the logs must match frame for frame. Use `--seed=N` and
  `--frames=N` to vary the input, and `--coverage` to report the share of code
  lines the original executed. Result: all 8 ports identical over 3,600 frames
  for seeds 1–3, executing 15–50% of each game's code lines per run.

