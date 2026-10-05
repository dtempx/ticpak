# ticpak

**Package a multi-file TIC-80 Lua project into a single cart suitable for publishing.**

TIC-80 carts are a single file, but a game of any size is easier to write as
several Lua modules loaded with `require`. That works while you develop, in
TIC-80 Pro, because `require` reads the modules from disk. It stops working
the moment you share the game: tic80.com, the web player and
`export html`/`export win` have no filesystem. ticpak closes that gap. It
turns your `main.lua` and its modules into one checked `.tic`, ready to
upload.

```
source: main.lua (21 modules)
cart: mygame.tic (up-to-date)
size: 110K
code: 41K (37%)
assets: 69K (63%)
41K / 64K code size limit (64% used, 36% free)
151K unminified (73% reduction)
```

## Quick start

You need [uv](#installing-uv) (or Python 3.9+ with pip) and the **Pro build of
TIC-80** (only Pro reads text `.lua` carts; see
[The TIC-80 binary](#the-tic-80-binary)).

```
uv tool install "ticpak[prompts] @ git+https://github.com/dtempx/ticpak"
cd mygame            # the folder holding main.lua
ticpak
```

Answer a few questions (Enter accepts each default) and you get
`<name>.tic` beside `main.lua`, booted once headless to prove it runs and
checked against TIC-80's limits.

For scripts and CI, skip the questions:

```
ticpak build -m      # build if anything changed, minifying everything
ticpak check         # check the cart already built
```

## Installing

ticpak has no required dependencies. The recommended way to install it is
[uv](https://docs.astral.sh/uv/):

```
uv tool install "ticpak[prompts] @ git+https://github.com/dtempx/ticpak"
```

uv gives ticpak its own private environment, so it can't clash with other
Python packages you have installed, and puts one command, `ticpak`, on your
PATH. Later, `uv tool upgrade ticpak` updates it and `uv tool uninstall ticpak`
removes it. Other ways in:

| How | Command |
|---|---|
| one-off run, nothing installed | `uvx --from git+https://github.com/dtempx/ticpak ticpak build` |
| pipx instead of uv | `pipx install "ticpak[prompts] @ git+https://github.com/dtempx/ticpak"` |
| plain pip | `pip install "ticpak[prompts] @ git+https://github.com/dtempx/ticpak"` |
| from a clone, editable | `pip install -e ".[prompts]"` |
| from a clone, no install | `python -m ticpak` |

The `[prompts]` extra adds [questionary](https://github.com/tmbo/questionary)
for arrow-key menus in interactive mode. Without it you get plain numbered
questions; everything else is the same.

### Installing uv

uv is a single program with no prerequisites. It doesn't even need Python
installed: when no suitable Python is found, it downloads one for ticpak.

**Windows** (PowerShell), either of:

```
winget install --id=astral-sh.uv -e
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**Linux and macOS** (including ARM boards such as a Raspberry Pi):

```
curl -LsSf https://astral.sh/uv/install.sh | sh
```

(Without curl: `wget -qO- https://astral.sh/uv/install.sh | sh`.)

Then **open a new terminal** so the updated PATH takes effect, and check with
`uv --version`. If `ticpak` is not found after `uv tool install`, run
`uv tool update-shell` and open a new terminal again: it adds uv's tool folder
(`~/.local/bin`, or `%USERPROFILE%\.local\bin` on Windows) to your PATH.
Other install methods are in [uv's docs](https://docs.astral.sh/uv/getting-started/installation/).

### One command

Everything is a subcommand of `ticpak`:

| Command | What it does |
|---|---|
| `ticpak` | interactive: status, or asks how to build |
| `ticpak build` | build and check the project's package |
| `ticpak check` | check the project's built package |
| `ticpak check FILE...` | check any `.tic` or `.lua` files you name |
| `ticpak minify FILE` | the Lua 5.3 minifier on its own ([docs/minify.md](docs/minify.md)) |

## What your project looks like

```
mygame/
  main.lua        the cart: metadata header, entry stub, asset sections
  player.lua      modules, beside the cart
  enemies.lua
  ...
  mygame.tic      ticpak's output (by default; see -o)
```

`main.lua` is an ordinary TIC-80 text cart whose code is just the `require`
lines and the `BOOT`/`TIC` callbacks:

```lua
-- title:   My Game
-- author:  you
-- desc:    a short description
-- site:    https://github.com/you/mygame
-- license: MIT License
-- version: 0.1
-- script:  lua

require "player"
require "enemies"

function TIC() game_update() game_draw() end

-- <TILES>
-- 001:...
-- </TILES>
```

ticpak looks for `./main.lua`, then `./src/main.lua`, or takes the path you
give it. Modules are loaded from the cart's own directory, by the names
literally written in `require "..."`.

### Asset sections

The `-- <TILES>` ... `-- </TILES>` block above is an asset section. TIC-80
Pro writes one for each kind of data your game has when it saves a text cart:
`TILES`, `SPRITES`, `MAP`, `FLAGS`, `WAVES`, `SFX`, `PATTERNS`, `TRACKS`,
`PALETTE` and `SCREEN` (the cover image), with a bank number for banks 1-7
(`-- <MAP1>`). Everything from the first such line to the end of the file is
asset data, stored as hex in comment lines.

- **Assets live in `main.lua`.** Edit them in TIC-80 Pro with `main.lua`
  loaded, save (Ctrl+S), and rebuild. Modules hold code only.
- **ticpak copies them unchanged.** It splits `main.lua` at the first asset
  tag and appends everything after it to the bundle byte for byte, after the
  inlined code. The minifier never sees the asset sections, so no
  minification option can change them. TIC-80 then converts them into the
  `.tic`'s binary chunks, and the check reports each section's size against
  its limit and which banks carry data.
- **Asset sections in a module are an error.** Only `main.lua`'s are
  packaged. Left in a module, a section would either cut the code short
  ([why](#a-pitfall-comments-that-look-like-asset-tags)) or, once
  minification strips comments, disappear. So ticpak stops, names the
  module's line, and asks you to move the section into `main.lua`.

## What it does

1. **Reads the metadata header.** The `title`, `author`, `desc`, `site`,
   `license`, `version` and `script` tags are required; tic80.com shows them.
   If any are missing it tells you which and stops, or in interactive mode
   offers to [fill them in](#when-the-header-is-incomplete).
2. **Names the output** after the header's `saveid`, else its `title`,
   lowercased, with anything but letters, digits, `_`, `.` and `-` turned into
   `-` (`My Game` becomes `my-game`). `-n` overrides it, and so does a file
   name given to `-o`.
3. **Bundles.** Every required module is inlined as a `package.preload`
   entry, so `require` still works with no filesystem. The code is minified
   if you asked for it, and the asset sections are copied byte for byte after
   it. The result is the bundle, `<name>.lua`.
4. **Boots the bundle headless** in TIC-80, from a temporary folder holding
   only that file, so a missing module or a syntax error fails now rather
   than after you upload.
5. **Saves `<name>.tic`**, the file you upload, beside `main.lua` (or where
   [`-o`](#output) says).
6. **Checks the `.tic`**: the code budget, every asset section's size, the
   banks, the cover screenshot and the header. Any violation exits with
   status 1.
7. **Prints the summary** shown at the top of this page.

By default only the `.tic` is kept. [`-o`](#output) can keep the bundle
instead, or put the `.tic` and the bundle together in a folder.
[`-r`](#the-full-report--r) also writes the full report to a file.

The bundle is a build artifact: never edit it, and rebuild it for each
release. `main.lua` and the modules stay your sources.

## Usage

```
ticpak [build | check] [SOURCE] [options]
ticpak check FILE... [-q]
ticpak minify [options] FILE
```

| Command | What it does | Asks questions? |
|---|---|---|
| *(none)* | interactive: shows the status, or asks how to build | yes, needs a terminal |
| `build` | builds and checks, or does nothing when the cart is up to date | never |
| `check` | checks the project's existing `.tic` without building | never |
| `check FILE...` | checks exactly the files named ([below](#checking-any-file)) | never |
| `minify FILE` | the minifier on its own ([below](#the-minifier-on-its-own)) | never |

`build` and `check` never wait for input, so they are the forms for scripts,
CI and AI agents. Anything missing is an error message saying what is needed.

| Option | Meaning |
|---|---|
| `SOURCE` | the cart, or a folder searched for `main.lua` then `src/main.lua` (default: the current folder); or [a module on its own](#a-module-on-its-own) |
| `-f`, `--force` | `build` only: build even when the cart is up to date |
| `-m`, `--minify` | minify with every option (see [Minification](#minification)) |
| `-m OPTION,...`, `--minify=OPTION,...` | minify with only the listed options (`-m=a,b` and `-ma,b` work too) |
| *(no `-m`)* | no minification: the inlined source, verbatim |
| `-o`, `--out PATH` | what to write: `NAME.tic`, `NAME.lua`, or a folder (see [Output](#output)); default `<name>.tic` beside `main.lua` |
| `-n`, `--name NAME` | output name without extension (default: saveid, else title); not with `-o NAME.tic`/`NAME.lua`, which name the file themselves |
| `-r`, `--report [PATH]` | also write the full report: `<name>.ticpak.txt` beside the output, or `PATH` (a file, or a folder to put `<name>.ticpak.txt` in); see [The full report](#the-full-report--r) |
| `-q`, `--quiet` | print nothing; the exit status says how it went (0 OK, 1 failed or a violation, 2 a usage error). An error that stops ticpak still prints its one line to stderr. Needs a command; not with `--verbose` |
| `-v`, `--version` | print the version |
| `--verbose` | also show progress, the check's detail and what minification saved (`check --verbose`: the full check report) |

```
ticpak                          # interactive
ticpak build                    # build + check, if anything changed
ticpak build -f                 # build + check, always
ticpak build -f -m              # every minify option: the smallest cart
ticpak build -f -m=comments,whitespace   # only those options
ticpak build --verbose          # with progress, the check's detail, minify savings
ticpak build -q                 # no output: just the exit status
ticpak build -f -r              # also the full report: <name>.ticpak.txt beside the .tic
ticpak build -f --report=r.txt  # the full report to r.txt instead
ticpak check                    # summary of the existing .tic
ticpak check --verbose          # ...and the full check report
ticpak build -n mygame          # mygame.tic beside main.lua
ticpak build -o mygame.tic      # just this .tic (path relative to the current folder)
ticpak build -o mygame.lua      # just the bundle
ticpak build -o dist/           # dist/<name>.tic and .lua
ticpak build path/to/main.lua   # a cart elsewhere (or its folder)
ticpak build enemies.lua -m     # one module, minified, to enemies.min.lua
ticpak check main.lua mygame.tic   # check these two files: full report
ticpak minify --fragment enemies.lua    # one module, minified, to stdout
```

A `SOURCE` that doesn't exist, or a file that isn't a `.lua`, is an error,
and so is a module `main.lua` requires that isn't there.

`ticpak --help` shows the options and these examples; this page is the full
reference.

### Checking any file

`ticpak check` on its own (or given a folder) checks the project's built
`<name>.tic` and prints the summary. With `-o`, it checks that build's output
instead: `ticpak check -o dist/` checks `dist/<name>.tic`, and
`ticpak check -o mygame.lua` gives a bundle the text-cart check below.
`-r` writes the check's full report to a file, as for `build` (with no
savings table: `check` doesn't minify). Give it files instead and it checks
exactly those, printing the checker's full report for each (`-r` doesn't
apply; redirect the output to keep it):

```
ticpak check main.lua                    # the source's header, before a build
ticpak check main.lua mygame.tic         # source and package in one run
ticpak check -q some/other.tic           # nothing printed; just the exit code
```

A `.tic` gets the full check: every section against its size limit, the code
budget, the banks, the cover screenshot and the header. A text-cart `.lua`
gets the header check and the banks its `-- <MAP1>`-style section tags use. No
TIC-80 binary is needed. It exits 1 if any file has a violation.

### The minifier on its own

`ticpak minify FILE` minifies one Lua file or text cart and writes the result
to stdout. Unlike `build`, it applies every option unless `--mode` says
otherwise:

```
ticpak minify --fragment enemies.lua > enemies.min.lua   # one module
ticpak minify --cart --report=report.txt dist/mygame.lua > small.lua
```

`ticpak minify --help` lists its options; [docs/minify.md](docs/minify.md) has
the details.

### A module on its own

Give `build` a `.lua` file that is not `main.lua` and has neither a metadata
header nor asset sections, and ticpak treats it as one module rather than a
cart. There is no game name to read, nothing to inline and no cart to boot, so
it minifies the file on its own (as a fragment: its globals are left alone,
since other modules may use them) and writes `<module>.min.lua` beside it:

```
ticpak build enemies.lua -m              # enemies.min.lua, every option
ticpak build enemies.lua -m -o small.lua # small.lua
ticpak build enemies.lua -m -o out/      # out/enemies.min.lua
```

`-m` works as for a cart, so leave it out and the copy is not minified. A
module can't be saved as a `.tic` (`-o NAME.tic` is an error), and
`ticpak check` has no package to check for it. A `.lua` that does have a
header or asset sections is a cart, whatever its name.

### Up to date or not

Every run opens with two status lines: the source cart with the number of
modules it requires, and the `.tic` with its state.

```
source: main.lua (21 modules)
cart: mygame.tic (up-to-date)
cart: mygame.tic (out-of-date: player.lua, enemies.lua changed)
cart: dist/mygame.tic (out-of-date: dist/mygame.lua missing)
cart: mygame.tic (not built yet)
```

Up to date means the output (the `.tic`, or with `-o NAME.lua` the bundle;
with a folder, the `.tic` and the `.lua` beside it) is newer than `main.lua`
and every module. `build` skips an up-to-date cart, so running it
on every save is cheap; it still prints the summary, then
`hint: ticpak build -f to force rebuild`. Only file timestamps count, so after
changing `-m` or upgrading ticpak, use `build -f`.

### The summary

```
size: 110K
code: 41K (37%)
assets: 69K (63%)
41K / 64K code size limit (64% used, 36% free)
151K unminified (73% reduction)
```

- **size** is the `.tic` file's size.
- **code** and **assets** are its code and its asset sections (tiles,
  sprites, map, sound, palette, cover, ...), each as a share of the file.
  They don't add up to exactly 100%, because each section has a 4-byte header.
- The **code size limit** line measures the code against the free TIC-80
  editor's 64K. Past it the line adds `- over the free editor's limit, fine
  on PRO (up to 512K)`.
- The last line is the code's size before minification and the saving, or
  `not minified`.

By default the summary, the status lines and any error or limit violation are
all ticpak prints. `--verbose` adds the progress lines, every size, anything
at 90% or more of a limit, every warning, and what minification saved
([below](#what-minification-saved)). `-q` prints nothing at all, and the
exit status alone says how the run went. [`-r`](#the-full-report--r) writes
everything `--verbose` shows, plus the check in full, to a file. Console
output is flush left, matching that report.

### What minification saved

With `--verbose` (and in the [`-r` report](#the-full-report--r)), a minified
build shows, just before the summary, how many bytes each option took off
each source file:

```
minify: bytes saved, by file and option (negative: the option added bytes)
file                    source  comments  whitespace  constants  extra  rename   after
main.lua                 3,752     2,924          87         10      0      53     678
constants.lua            9,104     6,216       1,347      1,468      0      27      46
board.lua               12,241     6,357       1,206        478    141     375   3,684
...
(added by ticpak)          974         0          75          0   -153      30   1,022
total                   95,731    44,763      10,326      5,039    866   5,607  29,130
```

- **source** and **after** are each file's code in the bundle, before and
  after minifying, in bytes of UTF-8. Each row's options add up to the
  difference. The total row's `source` is the summary's `unminified` size.
  `main.lua`'s row counts its metadata header but not its asset sections.
- There is a column for each option you chose, plus **whitespace**, because
  every option removes some: `comments` drops the lines that held only a
  comment, and the others re-space every line. Whitespace also gets the
  few bytes of redundant `;` and trailing table commas dropped along the way.
- **constants** and **extra** are optimised together, each enabling more of
  the other. With both on, ticpak measures `constants` alone and gives
  `extra` the rest.
- Options move bytes as well as remove them. An inlined constant's bytes go
  to the file that reads it, so a file's `constants` can be negative. `extra`
  can be negative where its aliases (`local a=spr`) are declared, which is
  usually the `(added by ticpak)` row. That row is the bundle's own lines:
  the `package.preload` wrapper around each module.
- A module that `extra` removed because nothing uses it ends with
  `(removed: unused)`.

After the table comes what the minified code is made of: strings, numbers,
keywords, operators, table field names, TIC-80 and Lua names, names never
renamed (function names, globals), renamed variables, NOMINIFY code, spaces
and line breaks. Then the biggest names that stayed, by total bytes. That
shows where the rest of the code budget goes. A module built on its own gets
a one-row table.

### Interactive mode

Run `ticpak` with no command. If the cart has never been built, it prints
`hint: answer the questions below to build it (Ctrl+C to cancel)` and asks:

```
? Output name (no extension): [mygame]
? Minification:
  1) all      - all minification options (smallest cart)  [default]
  2) comments - remove comments only
  3) none     - no minification (the bundled source verbatim)
  4) choose individual minification options...
? Minify options (space toggles, enter accepts):
   1) [x] comments    remove comments (keeps the metadata header and asset blocks)
   2) [x] rename      rename variables to the shortest free names (1-2 letters)
   3) [x] constants   inline constant values and remove the constants
   4) [x] whitespace  remove extraneous newlines and whitespace
   5) [x] extra       further optimisations
? Output:
  1) mygame.tic - output .tic binary only [default]
  2) output all files to a folder - mygame.tic (binary), mygame.lua (the equivalent source text), etc.
? Output folder: [dist/]
```

`Output folder` is asked only if you choose the folder. Minification
defaults to `all` here, unlike `build`, which minifies only with `-m`.
Options given on the
command line (`-m`, `-n`, `-o`) become the defaults, and `-r` writes the
report as in `build`; `-o NAME.tic` or
`-o NAME.lua` already says what to write, so then only the minification is
asked. Without questionary, type the numbers to toggle (`2,5`) and press
Enter on an empty line to accept.

After the build it prints the `build` command that repeats your answers, for
later rebuilds, scripts, or setting up the same build elsewhere. Answers that
match the defaults are left out:

```
hint: to build with these settings again: ticpak build -m=comments,whitespace -n mygame-lite -o dist/
```

If the default output (`<name>.tic` beside `main.lua`, or `-o`'s) already
exists, it asks nothing. It prints the status lines
and `hint: ticpak build -f to force rebuild`, and exits.

With no terminal (piped input, CI) it doesn't guess. It tells you to use
`build` or `check` and exits with status 2. `-q` needs a command too, since
the questions can't be asked quietly. On Windows, a standalone Git Bash
(mintty) window looks like no terminal to Python: run `winpty ticpak` there,
or use PowerShell, Windows Terminal or VS Code's terminal.

### When the header is incomplete

If tags are missing, empty, or still the placeholder text of TIC-80's `new`
cart, ticpak lists them with the lines to add and does not build (status 1).
In interactive mode it first offers to add them, with a default for each:

| Tag | Default |
|---|---|
| title | the project folder's name (skipping `src/` and `tic80/`) |
| author | `git config user.name`, else your login name |
| desc | `<title> - a TIC-80 game` |
| site | the git `origin` remote as an https URL (credentials stripped), else `https://tic80.com` |
| license | `MIT License` |
| version | `0.1` |

`script` is always `lua`. Placeholders are replaced in place, missing tags are
added after the header's last line, and the file keeps its line endings.

## Minification

The free TIC-80 editor holds 64K of code, so a large game may need its code
shrunk. Without `-m` the bundle is not minified. `-m` on its own applies every
option; `-m=OPTION,...` applies only those.

| Option | What it does |
|---|---|
| `comments` | removes comments (keeps the metadata header and asset sections); nothing else changes |
| `rename` | renames local variables to the shortest free names (1-2 letters); function names are kept so error messages stay readable |
| `constants` | inlines constant values and removes the constants |
| `whitespace` | removes extraneous whitespace and newlines, packing lines to 120 columns |
| `extra` | everything else: folds constant expressions (`2*8` → `16`), removes unreachable code and anything nothing uses, call sugar (`f("x")` → `f"x"`), short local aliases for heavily used API functions (`spr`, `math.floor`, ...), and merges adjacent `local` statements |

On one 21-module game (code characters; the free limit is 65,536):

| Minification | Code |
|---|---|
| none | 154,092 |
| `comments` | 66,262 |
| `comments,whitespace` | 54,981 |
| `-m` (every option) | 42,039 |

With a [folder output](#output), every option past `comments` also writes
two files you need to decode a runtime error in the packaged cart:
`<name>.minify.txt` (what each pass did) and `<name>.minify.json` (each
output line's source `file:line`, and every renamed identifier). See
[The decode maps](#the-decode-maps-nameminifytxt-and-nameminifyjson). A
`.tic` or `.lua` on its own comes without them, so build to a folder
(`-o dist/`) when you need to trace an error.

**Write `-m=a,b` with `=`, or put `SOURCE` first.** In `-m path/main.lua` the
path would be read as the option list; ticpak says so if it happens.

### Opting code out: NOMINIFY

The word `NOMINIFY` (any case) in a comment protects code from the minifier.
It is useful for names that must survive, such as globals another cart or the
debugger reads by name, for code that relies on exact text, and for comments
that should ship with the cart (credits, a licence notice).

A directive is either a **comment block** that holds the word (one or more
comment lines in a row; a blank line or code ends the block), or a comment
**after code** on the same line. What it keeps depends on where it is:

| Where the directive is | What is kept |
|---|---|
| directly above, or after, a variable's `local`, assignment or `for` | that variable: its name, declaration and value |
| directly above a function, or after its first or last line | the whole function, byte for byte |
| a module's top comment block | the whole module, byte for byte |
| `main.lua`'s header block (outside the metadata tags) | the whole cart |
| anywhere else | the comment itself |

```lua
-- NOMINIFY: the high-score cart reads this name
local score_table = {}

-- NOMINIFY: timing-sensitive, keep it exactly as written
function wait_vblank()
  ...
end

-- NOMINIFY: music by A. Composer, CC BY 4.0
```

A directive inside a function body applies only to the statement after it,
not to the function. Where a block could apply to both a module and a
function, the module wins. Details:
[docs/minify.md](docs/minify.md#opting-out-nominify).

### A pitfall: comments that look like asset tags

TIC-80's loader reads any line starting `-- <` as the start of the asset
sections and cuts the code there. An unminified bundle keeps every comment,
so a comment such as `-- <MAP> region ...` in a module would break the cart.
ticpak stops before booting such a bundle and names the line. Reword the
comment, or minify with at least `comments`. A real asset section in a
module (its tag alone on the line) stops the build either way: move it into
`main.lua` (see [Asset sections](#asset-sections)).

## The TIC-80 binary

The boot test and the `.tic` save run TIC-80 **Pro** headless. Pro is a paid
download from [itch.io](https://nesbox.itch.io/tic80), or build it from source
with `-DBUILD_PRO=On`. ticpak looks for it in this order:

1. `$TIC80`, if set;
2. `tools/tic80.exe` (Windows) or `tools/tic80/build/bin/tic80` (Linux), in
   the nearest folder above the current folder that has one;
3. `tic80` on `PATH`.

## Output

`-o` says what a build writes. What it ends in decides which:

| `-o` | Writes | Example |
|---|---|---|
| *(none)* | `<name>.tic` only, in the folder holding `main.lua` | `mygame.tic` |
| `NAME.tic` | that `.tic` only | `-o mygame.tic`, `-o release/v2.tic` |
| `NAME.lua` | the bundle only | `-o mygame.lua` |
| a folder: ends in `/`, or has neither extension | `<name>.tic` and `<name>.lua` in it, plus the decode maps | `-o dist/`, `-o dist` |

A path given to `-o` is relative to the current folder, and a file name there
is the output's name (so `-n` goes only with a folder or the default). Every
kind of build boots the bundle and checks a `.tic` made from it. A file not
kept is never written to your folders: the bundle for a `.tic`-only build is
held in memory and written only into TIC-80's temporary folder, and a
`.lua`-only build checks a temporary `.tic` and deletes it. A build stops
rather than overwrite `main.lua` or one of its modules.

A folder build writes these files, all named after the output name:

| File | What it is | Written |
|---|---|---|
| `<name>.lua` | the bundle: your whole game as one text cart | every build |
| `<name>.tic` | the same cart in TIC-80's binary format: **the file to upload** | every build |
| `<name>.minify.txt` | the minifier's report: what each option saved and each pass did | builds with any minify option past `comments` |
| `<name>.minify.json` | line and rename maps for decoding runtime errors | builds with any minify option past `comments` |

`-r` adds `<name>.ticpak.txt`, [the full report](#the-full-report--r), to
any build: beside the output (in the folder, for a folder build), or where
`-r PATH` says.

Every output is regenerated from your sources, so add it to your
`.gitignore` (`*.tic`, `dist/`) and never edit it. A folder build that writes
no minify files deletes any left over from an earlier minified build, because
they would no longer match the bundle.

### The `.lua` and the `.tic`

Both hold the same game: the same code and the same assets. They differ in
format, and in who writes them.

**`<name>.lua` is written by ticpak.** It is a text cart, the same format as
your `main.lua`: the metadata header, then the code, then the asset sections
(`-- <TILES>`, `-- <MAP>`, ...) as hex text. ticpak builds it from
`main.lua`'s header, then each module wrapped in a
`package.preload["name"] = function(...) ... end` entry, then `main.lua`'s own
code (the `require` lines and callbacks). It minifies that code if you asked,
and copies `main.lua`'s asset sections after it byte for byte. You can open
it in any editor. When TIC-80 reports an error at a line number, the number
refers to a line of this file. Only TIC-80 Pro can load a text cart.

**`<name>.tic` is written by TIC-80.** It is TIC-80's binary cart format:
the code and each asset section stored as binary chunks, with no hex
encoding, so it is smaller than the `.lua`. ticpak doesn't produce it itself.
It writes the bundle into an empty temporary folder and runs TIC-80 Pro
headless there, twice:

1. `load <name>.lua & run` boots the game. Any syntax error, runtime error
   at startup or missing module fails the build here. The folder holds
   nothing else, so the bundle can't quietly fall back on a module file on
   disk.
2. `load <name>.lua & save <name>.tic & exit` has TIC-80 convert the cart.
   ticpak copies the result to its place (beside `main.lua`, or `-o`'s) and
   checks it.

Every TIC-80 can load the `.tic`: the free build, the web player and
tic80.com. Upload it, or send it to anyone with TIC-80. The `.lua` (from a
folder build or `-o NAME.lua`) is for reading and decoding errors, and for
exports: load it in TIC-80 and run `export html <name>` or
`export win <name>` for a web or native build (both need network access).

### The full report: `-r`

`build` and `check` write nothing but the cart unless you ask. `-r` (or
`--report`) also writes the full report, and prints a `report:` line naming
the file:

| Form | Writes |
|---|---|
| `-r` | `<name>.ticpak.txt` beside the output: beside `main.lua` by default, in the folder for `-o dist/`, beside the file for `-o NAME.tic`/`NAME.lua` |
| `-r PATH`, `--report=PATH` | that file |
| `-r DIR/` (or an existing folder) | `DIR/<name>.ticpak.txt` |

A `PATH` is relative to the current folder. One ending in `.lua` or `.tic`
is an error: it is the `SOURCE` or an output read as the report's path. Put
`SOURCE` before `-r`, or write `--report=PATH`.

The report is the check of the `.tic` in full: every asset section's size
against its limit, how the code is stored, which memory banks carry data,
every header tag, whether there is a cover screenshot and any violations.
After a minified build, [what minification saved](#what-minification-saved)
comes next, then the summary. `--verbose` prints the parts that need
attention, and `ticpak check --verbose` prints all of the check.

An up-to-date `build -r` writes the report of the `.tic` already built,
which has no savings table because nothing was minified in that run. Add
`-f` to rebuild. A module built on its own gets a report with its savings
table and sizes.

```
check: dist/mygame.tic
.tic file 137,708 bytes (134.5 KB)
PALETTE                  48 bytes (50%)
SPRITES               8,187 bytes (100%)
MAP                  32,575 bytes (100%)
...
CODE part 1          65,536 bytes (100% of a 64 KB chunk)
CODE part 2           1,564 bytes (2% of a 64 KB chunk)
banks  1 of 8 carry asset data (bank 0 boots; 1-7 load via sync())
...
header complete
title: My Game
...
screenshot (SCREEN) present
all checks OK

minify: bytes saved, by file and option (negative: the option added bytes)
...
size: 134K
...
```

### The decode maps: `<name>.minify.txt` and `<name>.minify.json`

Past `comments`, minification changes line numbers and renames local
variables, so an error from the packaged cart no longer points at your
sources. A folder build (`-o dist/`) writes these two maps beside the bundle
to translate them back. Say TIC-80 reports:

```
[string "-- title: My Game..."]:37: attempt to index a nil value (local 'b')
```

Line 37 is a line of the minified `<name>.lua`, and `b` is a renamed
variable. `<name>.minify.json` translates both:

- `"lines"` maps each bundle line to the source line it came from. Look up
  `"37"` and you get, say, `["enemies.lua", 112]`. Lines that ticpak added
  itself map to `[null, 0]`.
- `"renames"` lists every renamed identifier, such as
  `{"new": "b", "old": "target", "kind": "local", "source": ["enemies.lua", 98]}`.
  A short name can be reused in different scopes, so pick the entry whose
  source is near the line you found.

`<name>.minify.txt` is the minifier's report for people: the code size after
each pass, the bytes each option saved, what the minified code is made of,
the biggest names that stayed, then every constant inlined, every piece of
code or variable
removed, every API function aliased, and everything kept by `NOMINIFY`, each
with its `file:line`. Read it when you want to know what happened to a
particular name, or attach it when reporting a minifier bug. The file
formats are described in [docs/minify.md](docs/minify.md#outputs).

Without minification, or with `comments` only, there are no maps: open
`<name>.lua` at the reported line. The nearest
`package.preload["..."] = function(...)` above it names the module.

## AI agent skills

[`skills/ticpak`](skills/ticpak/SKILL.md) is an
[Agent Skill](https://agentskills.io) that teaches an AI coding agent (Claude
Code, Cursor, Codex, ...) to use ticpak in your game's project. It has three
actions, `/ticpak init`, `/ticpak build` and `/ticpak check`, and agents that
don't take arguments pick the action from what you ask:

| Action | What the agent does |
|---|---|
| `init` | sets up a new project, splits a single-file cart into modules, or reviews a project against ticpak's rules |
| `build` | builds the `.tic`, chooses minify options, fixes failed builds, decodes errors from a packaged cart |
| `check` | checks a cart's limits and explains how much room is left |

Install it into your game's project with the
[skills CLI](https://github.com/vercel-labs/skills), which detects your agents:

```
npx skills add dtempx/ticpak
```

Or copy `skills/ticpak/` into your agent's skills directory yourself
(`.claude/skills/` for Claude Code, `.agents/skills/` for most others).

## Inside ticpak

| Module | What it does |
|---|---|
| `ticpak/cli.py` | the command line, `--help`, the interactive questions, `main()` |
| `ticpak/bundle.py` | finds the cart, resolves `-o` into the outputs to keep, inlines the modules, minifies, writes `<name>.lua` and the decode maps; a module on its own; the up-to-date check; the `-- <` guard |
| `ticpak/run.py` | finds TIC-80 Pro, boots the bundle headless, saves `<name>.tic` |
| `ticpak/report.py` | the summary, the `--verbose` detail (the minify savings table included), the `-r` report file |
| `ticpak/header.py` | the metadata header: the output name, missing tags, filling them in |
| `ticpak/console.py` | console output and the prompts (questionary or plain) |
| `ticpak/check.py` | the `.tic` limit and header checker (`ticpak check FILE...`) |
| `ticpak/minify.py` | the minifier (`ticpak minify`; [docs/minify.md](docs/minify.md), [docs/minify-spec.md](docs/minify-spec.md)) |

`scripts/update_reserved.py` refreshes the minifier's list of TIC-80 API
names (which `rename` must never take) from a TIC-80 binary.

## Testing

```
pip install -e ".[test]"             # lupa: a real Lua 5.3 for the tests
python tests/options/test_options.py # every combination of minify options
python tests/minify/run.py           # the minifier's fixtures and fuzzing
```

`tests/options` builds sample carts with every subset of minify options and
runs the original and minified code side by side in Lua 5.3, comparing what
they draw. It also checks that every asset layout (bank 0, banks 1-7, a
`SCREEN` cover, CRLF line endings) comes through the minifier and the bundle
byte for byte. Set `TICPAK_BOOT=1` to also boot the bundles in TIC-80 and
compare the saved `.tic`'s asset chunks with `main.lua`'s sections (about 4
minutes). `tests/minify` checks the minifier on fixtures and random
expressions; set `TICPAK_GAMES` to a folder of `<game>/tic80/` projects to
also run real games frame by frame against their minified bundles.

## License

MIT; see [LICENSE](LICENSE).
