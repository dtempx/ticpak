# ticpak

**Package a multi-file TIC-80 Lua project into one cart you can upload.**

TIC-80 carts are a single file, but a game of any size is easier to write as
several Lua modules loaded with `require`. That works while you develop, in
TIC-80 Pro, because `require` reads the modules from disk. It stops working
the moment you share the game: tic80.com, the web player and
`export html`/`export win` have no filesystem. ticpak closes that gap. It
turns your `main.lua` and its modules into one checked `.tic`, ready to
upload.

```
source: main.lua (21 modules)
cart: dist/wavynavy.tic (up-to-date)
size: 110K
code: 41K (37%)
assets: 69K (63%)
41K / 64K code size limit (64% used, 36% free)
151K unminified (73% reduction)
```

## Quick start

You need **Python 3.9+** and the **Pro build of TIC-80** (only Pro reads text
`.lua` carts; see [The TIC-80 binary](#the-tic-80-binary)).

```
uv tool install "ticpak[prompts] @ git+https://github.com/dtempx/ticpak"
cd mygame            # the folder holding main.lua
ticpak
```

Answer three questions (Enter accepts each default) and you get
`dist/<name>.tic`, booted once headless to prove it runs and checked against
TIC-80's limits.

For scripts and CI, skip the questions:

```
ticpak build -m      # build if anything changed, minifying everything
ticpak check         # check the cart already built
```

## Installing

ticpak has no required dependencies. Pick whichever installer you already use:

| How | Command |
|---|---|
| [uv](https://docs.astral.sh/uv/) (recommended) | `uv tool install "ticpak[prompts] @ git+https://github.com/dtempx/ticpak"` |
| uv, one-off run without installing | `uvx --from git+https://github.com/dtempx/ticpak ticpak build` |
| pipx | `pipx install "ticpak[prompts] @ git+https://github.com/dtempx/ticpak"` |
| from a clone, editable | `pip install -e ".[prompts]"` |
| from a clone, no install | `python -m ticpak` |

The `[prompts]` extra adds [questionary](https://github.com/tmbo/questionary)
for arrow-key menus in interactive mode. Without it you get plain numbered
questions; everything else is the same.

Installing gives you three commands:

| Command | What it is |
|---|---|
| `ticpak` | the packager: everything on this page |
| `ticpak-minify` | the Lua 5.3 minifier on its own ([docs/minify.md](docs/minify.md)) |
| `ticpak-check` | the `.tic` limit and header checker on its own |

## What your project looks like

```
mygame/
  main.lua        the cart: metadata header, entry stub, asset sections
  player.lua      modules, beside the cart
  enemies.lua
  ...
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

## What it does

1. **Reads the metadata header.** The `title`, `author`, `desc`, `site`,
   `license`, `version` and `script` tags are required; tic80.com shows them.
   If any are missing it tells you which and stops, or in interactive mode
   offers to [fill them in](#when-the-header-is-incomplete).
2. **Names the output** after the header's `saveid`, else its `title`,
   lowercased, with anything but letters, digits, `_`, `.` and `-` turned into
   `-` (`Wavy Navy` becomes `wavy-navy`). `-n` overrides it.
3. **Bundles.** Every required module is inlined as a `package.preload`
   entry, so `require` still works with no filesystem. The code is minified
   if you asked for it, and the asset sections are copied byte for byte into
   `dist/<name>.lua`.
4. **Boots the bundle headless** in TIC-80, from a folder holding only that
   file, so a missing module or a syntax error fails now rather than after
   you upload.
5. **Saves `dist/<name>.tic`**, the file you upload.
6. **Checks the `.tic`**: the code budget, every asset section's size, the
   banks, the cover screenshot and the header. The full report goes to
   `dist/<name>.txt`. Any violation exits with status 1.
7. **Prints the summary** shown at the top of this page, and appends it to
   the `.txt`.

The bundle is a build artifact: never edit it, and rebuild it for each
release. `main.lua` and the modules stay your sources.

## Usage

```
ticpak [build | check] [SOURCE] [options]
```

| Command | What it does | Asks questions? |
|---|---|---|
| *(none)* | interactive: shows the status, or asks how to build | yes, needs a terminal |
| `build` | builds and checks, or does nothing when the cart is up to date | never |
| `check` | checks the existing `.tic` without building | never |

`build` and `check` never wait for input, so they are the forms for scripts,
CI and AI agents. Anything missing is an error message saying what is needed.

| Option | Meaning |
|---|---|
| `SOURCE` | the cart, or a folder searched for `main.lua` then `src/main.lua` (default: the current folder) |
| `-f`, `--force` | `build` only: build even when the cart is up to date |
| `-m`, `--minify` | minify with every option (see [Minification](#minification)) |
| `-m OPTION,...`, `--minify=OPTION,...` | minify with only the listed options (`-m=a,b` and `-ma,b` work too) |
| *(no `-m`)* | no minification: the inlined source, verbatim |
| `-o`, `--out DIR` | output folder, relative to the current folder (default `dist`) |
| `-n`, `--name NAME` | output name without extension (default: saveid, else title) |
| `-v`, `--verbose` | also show progress and the check's detail (`check -v`: the full report) |
| `--version` | print the version |

```
ticpak                          # interactive
ticpak build                    # build + check, if anything changed
ticpak build -f                 # build + check, always
ticpak build -f -m              # every minify option: the smallest cart
ticpak build -f -m=comments,whitespace   # only those options
ticpak build -v                 # with progress and the check's detail
ticpak check                    # summary of the existing .tic
ticpak check -v                 # ...and the full check report
ticpak build -n mygame          # dist/mygame.lua + dist/mygame.tic
ticpak build -o out             # write to ./out instead of ./dist
ticpak build path/to/main.lua   # a cart elsewhere (or its folder)
```

`ticpak --help` shows the options and these examples; this page is the full
reference.

### Up to date or not

Every run opens with two status lines: the source cart with the number of
modules it requires, and the `.tic` with its state.

```
source: main.lua (21 modules)
cart: dist/wavynavy.tic (up-to-date)
cart: dist/wavynavy.tic (out-of-date: state_play.lua, grid.lua changed)
cart: dist/wavynavy.tic (out-of-date: dist/wavynavy.lua missing)
cart: dist/wavynavy.tic (not built yet)
```

Up to date means the `.tic`, and the `.lua` bundle beside it, are newer than
`main.lua` and every module. `build` skips an up-to-date cart, so running it
on every save is cheap; it still prints the summary, then
`hint: ticpak build -f to force rebuild`. Only file timestamps count, so after
changing `-m`, `-n` or `-o`, or upgrading ticpak, use `build -f`.

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
all ticpak prints. `-v` adds the progress lines, every size, anything at 90%
or more of a limit, and every warning. Console output is flush left, matching
the `.txt` report.

### Interactive mode

Run `ticpak` with no command. If the cart has never been built, it prints
`hint: answer the questions below to build it (Ctrl+C to cancel)` and asks:

```
? Output name (no extension): [wavynavy]
? Minification:
  1) all  - every option (smallest cart)
  2) none - no minification (the inlined source verbatim)  [default]
  3) choose individual options...
? Minify options (space toggles, enter accepts):
   1) [ ] comments    remove comments (keeps the metadata header and asset blocks)
   2) [ ] rename      rename variables to the shortest free names (1-2 letters)
   3) [ ] constants   inline constant values and remove the constants
   4) [ ] whitespace  remove extraneous newlines and whitespace
   5) [ ] extra       further optimisations
? Output folder: [dist]
```

Options given on the command line (`-m`, `-n`, `-o`) become the defaults.
Without questionary, type the numbers to toggle (`2,5`) and press Enter on an
empty line to accept.

If the `.tic` already exists, it asks nothing. It prints the status lines
and `hint: ticpak build -f to force rebuild`, and exits.

With no terminal (piped input, CI) it doesn't guess. It tells you to use
`build` or `check` and exits with status 2. On Windows, a standalone Git Bash
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

Every option past `comments` also writes two files you need to decode a
runtime error in the packaged cart: `<name>.minify.txt` (what each pass did)
and `<name>.minify.json` (each output line's source `file:line`, and every
renamed identifier).

**Write `-m=a,b` with `=`, or put `SOURCE` first.** In `-m path/main.lua` the
path would be read as the option list; ticpak says so if it happens.

### Opting code out: NOMINIFY

A comment containing `NOMINIFY` (any case) protects code from the minifier.
It is useful for names that must survive, such as globals another cart or the
debugger reads by name, and for code that relies on exact text.

| Where the comment is | What is kept |
|---|---|
| the line that declares or assigns a variable | that variable's name, through `rename` |
| a function's declaration line, or the comment block directly above or below it | the whole function, byte for byte |
| a module's top comment block | the whole module, byte for byte |
| `main.lua`'s header block (outside the metadata tags) | the whole cart |

```lua
local score_table = {}  -- NOMINIFY: the high-score cart reads this name

-- NOMINIFY: timing-sensitive, keep it exactly as written
function wait_vblank()
  ...
end
```

A blank line ends a comment block. Where a comment could apply to both a
module and a function, the module wins. Details:
[docs/minify.md](docs/minify.md).

### A pitfall: comments that look like asset tags

TIC-80's loader reads any line starting `-- <` as the start of the asset
sections and cuts the code there. An unminified bundle keeps every comment,
so a comment such as `-- <MAP> region ...` in a module would break the cart.
ticpak stops before booting such a bundle and names the line. Reword the
comment, or minify with at least `comments`.

## The TIC-80 binary

The boot test and the `.tic` save run TIC-80 **Pro** headless. Pro is a paid
download from [itch.io](https://nesbox.itch.io/tic80), or build it from source
with `-DBUILD_PRO=On`. ticpak looks for it in this order:

1. `$TIC80`, if set;
2. `tools/tic80.exe` (Windows) or `tools/tic80/build/bin/tic80` (Linux), in
   the nearest folder above the current folder that has one;
3. `tic80` on `PATH`.

## Output

```
dist/<name>.lua           the bundled text cart (export html / export win from this)
dist/<name>.tic           the binary cart: the file to upload
dist/<name>.txt           the check's full report, then the summary
dist/<name>.minify.txt    any option past comments: what each pass did
dist/<name>.minify.json   any option past comments: line and rename maps
```

Add `dist/` to your `.gitignore`. For a web or native build, load
`dist/<name>.lua` in TIC-80 and run `export html <name>` or
`export win <name>` (both need network access).

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
| `ticpak/bundle.py` | finds the cart, inlines the modules, minifies, writes `<name>.lua` and the decode maps; the up-to-date check; the `-- <` guard |
| `ticpak/run.py` | finds TIC-80 Pro, boots the bundle headless, saves `<name>.tic` |
| `ticpak/report.py` | the check report in `<name>.txt`, the summary, the `-v` detail |
| `ticpak/header.py` | the metadata header: the output name, missing tags, filling them in |
| `ticpak/console.py` | console output and the prompts (questionary or plain) |
| `ticpak/check.py` | the `.tic` limit and header checker (`ticpak-check`) |
| `ticpak/minify.py` | the minifier (`ticpak-minify`; [docs/minify.md](docs/minify.md), [docs/minify-spec.md](docs/minify-spec.md)) |

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
they draw. Set `TICPAK_BOOT=1` to also boot each one in TIC-80 (about 3
minutes). `tests/minify` checks the minifier on fixtures and random
expressions; set `TICPAK_GAMES` to a folder of `<game>/tic80/` projects to
also run real games frame by frame against their minified bundles.

## License

MIT; see [LICENSE](LICENSE).
