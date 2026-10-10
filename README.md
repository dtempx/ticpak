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
cart size: 110K
code: 41K (37%)
assets: 69K (63%)
code limit: 41K / 512K (8% used, 92% free)
original code size: 151K (73% reduction with minify: default)
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
ticpak bundle -m      # build if anything changed, with the default minify options
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
PATH. Later, `uv tool upgrade ticpak` [updates it](#updating) and
`uv tool uninstall ticpak` removes it. Other ways in:

| How | Command |
|---|---|
| one-off run, nothing installed | `uvx --from git+https://github.com/dtempx/ticpak ticpak bundle` |
| pipx instead of uv | `pipx install "ticpak[prompts] @ git+https://github.com/dtempx/ticpak"` |
| plain pip | `pip install "ticpak[prompts] @ git+https://github.com/dtempx/ticpak"` |
| from a clone, editable | `pip install -e ".[prompts]"` |
| from a clone, no install | `python -m ticpak` |

The `[prompts]` extra adds [questionary](https://github.com/tmbo/questionary)
for arrow-key menus in interactive mode. Without it you get plain numbered
questions; everything else is the same.

To let an AI coding agent use ticpak, install the agent skill from your game's
project folder (details in [AI agent skills](#ai-agent-skills)):

```
npx skills add dtempx/ticpak
```

### Updating

ticpak installs from git, so updating means fetching the latest commit:

```
ticpak --version       # what you have now
uv tool upgrade ticpak
ticpak --version       # what you have after
```

`uv tool upgrade` keeps the source and the `[prompts]` extra you installed
with. If the version doesn't change and you expected it to, force a fresh
install from git:

```
uv tool install --reinstall "ticpak[prompts] @ git+https://github.com/dtempx/ticpak"
```

With pipx, `pipx upgrade ticpak`; with pip, rerun the `pip install` line
above with `--upgrade`; from a clone, `git pull`.

If your game uses the [agent skill](#ai-agent-skills), refresh it too, since it
describes ticpak's options and messages. From your game's project folder
(details in [Updating the skill](#updating-the-skill)):

```
npx skills update ticpak
```

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
| `ticpak init` | start a new project: `main.lua` and a first module |
| `ticpak bundle` | build and check the project's package |
| `ticpak check` | check the project's built package |
| `ticpak check FILE...` | check any `.tic` or `.lua` files you name |
| `ticpak run` | run `main.lua` (your sources, as they are) in TIC-80 |
| `ticpak test` | run the package in TIC-80, its runtime errors translated back to your files, lines and names |
| `ticpak decode` | translate a runtime error from the package (copied, or in a log) back to your files, lines and names |
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

### Starting a new project

```
ticpak init            # in the current folder
ticpak init mygame     # in mygame/, made if missing
```

`init` writes two files and asks nothing:

- **`main.lua`**, the cart: a metadata header, an entry stub
  (`require "game"` and the `BOOT`/`TIC` callbacks calling `game.init`,
  `game.update` and `game.draw`), and TIC-80's default palette as its one
  asset section. The header has version `0.1` and placeholders for the
  rest (`my game`, `your name or email`, `short description`, ...), which
  packaging won't accept until they are filled in.
- **`game.lua`**, a sample module that defines the global table `game` with
  `init`, `update` and `draw`, drawing a red dot sweeping across the screen.

If the folder already has a `main.lua` (or `src/main.lua`), `init` stops
with a message and exit status 1, and writes nothing; likewise if `game.lua`
is there. Run the new cart with `ticpak run` (or `ticpak run FOLDER`). To
package it, edit the header in `main.lua`, or run `ticpak`, which
[asks for the placeholder tags](#when-the-header-is-incomplete) (offering
the folder's name as the title, your git `user.name` as the author, the git `origin` URL, else
`https://tic80.com`, as the site, and `MIT License`), writes them in and
builds.

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
  its limit and, for each bank that carries data, how full it is.
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
   it. The result is the bundle, `<name>.lua`. ticpak adds one line to the
   header block, `-- ticpak: 0.3.4 -m`: its version and the `-m` it built
   with (none when not minified). It is how a later run knows how the `.tic`
   or `.lua` was built. TIC-80 ignores it, and it costs about 20 bytes of
   code.
4. **Boots the bundle headless** in TIC-80, from a temporary folder holding
   only that file, so a missing module or a syntax error fails now rather
   than after you upload. Code at or over TIC-80's
   [512K limit](#tic-80s-limits) stops before this step, since TIC-80 would
   cut it off.
5. **Saves `<name>.tic`**, the file you upload, beside `main.lua` (or where
   [`-o`](#output) says).
6. **Checks the `.tic`**: the code budget, every asset section's size, the
   banks, the cover screenshot and the header. Any violation exits with
   status 1.
7. **Prints the summary** shown at the top of this page.

By default only the `.tic` is kept. [`-o`](#output) can keep the bundle
instead, or put the `.tic`, the bundle and the full report together in a
folder. For a single-file build, [`-r`](#the-full-report--r) also writes the
full report to a file.

The bundle is a build artifact: never edit it, and rebuild it for each
release. `main.lua` and the modules stay your sources.

## Usage

```
ticpak init [FOLDER] [-q]
ticpak [bundle | check] [SOURCE] [options]
ticpak check FILE... [-q]
ticpak run [SOURCE]
ticpak test [SOURCE] [-o PATH] [-n NAME] [-m...]
ticpak decode [SOURCE] [-o PATH] [-n NAME] [-m...] [-e TEXT | -l FILE]
ticpak minify [options] FILE
```

| Command | What it does | Asks questions? |
|---|---|---|
| *(none)* | interactive: shows the status, or asks how to build | yes, needs a terminal |
| `init` | starts a new project: `main.lua` and `game.lua` ([above](#starting-a-new-project)) | never |
| `bundle` | builds and checks, or does nothing when the cart is up to date | never |
| `check` | checks the project's existing `.tic` without building | never |
| `check FILE...` | checks exactly the files named ([below](#checking-any-file)) | never |
| `run` | runs `main.lua` in TIC-80's window until you close it, from the cart's folder so `require` loads the modules from their files; passes on what TIC-80 prints | never |
| `test` | runs the package in TIC-80's window until you close it, translating its errors as they happen ([below](#errors-from-the-packaged-cart)) | never |
| `decode` | translates an error from the packaged cart back to the sources ([below](#errors-from-the-packaged-cart)) | never; at a terminal, asks you to paste the error when the clipboard holds none |
| `minify FILE` | the minifier on its own ([below](#the-minifier-on-its-own)) | never |

`init`, `bundle`, `check`, `run`, `test` and `decode` never ask questions, so they are the forms for
scripts, CI and AI agents (`run` and `test` wait until TIC-80 is closed). Anything
missing is an error message saying what is needed.

| Option | Meaning |
|---|---|
| `SOURCE` | the cart, or a folder searched for `main.lua` then `src/main.lua` (default: the current folder); or [a module on its own](#a-module-on-its-own) |
| `-f`, `--force` | `bundle` only: build even when the cart is up to date |
| `-m`, `--minify` | minify with the `default` options: every option but `rename-tables` (see [Minification](#minification)) |
| `-m=max`, `--minify=max` | minify with every option, `rename-tables` included: the smallest cart |
| `-m OPTION,...`, `--minify=OPTION,...` | minify with only the listed options (`-m=a,b` and `-ma,b` work too) |
| *(no `-m`)* | no minification: the inlined source, verbatim |
| `-o`, `--output PATH` | what to write: `NAME.tic`, `NAME.lua`, or a folder (see [Output](#output)); default `<name>.tic` beside `main.lua` |
| `-n`, `--name NAME` | output name without extension (default: saveid, else title); not with `-o NAME.tic`/`NAME.lua`, which name the file themselves |
| `-r`, `--report [PATH]` | also write the full report: `<name>.bundle.txt` beside the output, or `PATH` (a file, or a folder to put `<name>.bundle.txt` in); a folder build writes it without `-r`. See [The full report](#the-full-report--r) |
| `-q`, `--quiet` | print nothing; the exit status says how it went (0 OK, 1 failed or a violation, 2 a usage error). An error that stops ticpak still prints its one line to stderr. Needs a command; not with `--verbose` |
| `-v`, `--version` | print the version |
| `--verbose` | also show progress, the check's detail and what minification saved (`check --verbose`: the full check report) |
| `-e`, `--error TEXT` | `decode` only: the error message and traceback to translate (default: stdin when redirected, else the clipboard, else a paste at the terminal) |
| `-l`, `--log FILE` | `decode` only: translate the last error in `FILE`, a log of TIC-80's output |

```
ticpak init mygame               # a new project in mygame/: main.lua and game.lua
ticpak                          # interactive
ticpak bundle                    # build + check, if anything changed
ticpak bundle -f                 # build + check, always
ticpak bundle -f -m              # the default minify options
ticpak bundle -f -m=max          # every minify option: the smallest cart
ticpak bundle -f -m=comments,whitespace   # only those options
ticpak bundle --verbose          # with progress, the check's detail, minify savings
ticpak bundle -q                 # no output: just the exit status
ticpak bundle -f -r              # also the full report: <name>.bundle.txt beside the .tic
ticpak bundle -f --report=r.txt  # the full report to r.txt instead
ticpak check                    # summary of the existing .tic
ticpak check --verbose          # ...and the full check report
ticpak bundle -n mygame          # mygame.tic beside main.lua
ticpak bundle -o mygame.tic      # just this .tic (path relative to the current folder)
ticpak bundle -o mygame.lua      # just the bundle
ticpak bundle -o dist/           # dist/<name>.tic, .lua and .bundle.txt (the report)
ticpak bundle path/to/main.lua   # a cart elsewhere (or its folder)
ticpak bundle enemies.lua -m     # one module, minified, to enemies.min.lua
ticpak check main.lua mygame.tic   # check these two files: full report
ticpak run                      # run main.lua in TIC-80 (the sources, as they are)
ticpak test                     # run the .tic in TIC-80, its errors in your files and names
ticpak decode                   # the error copied from TIC-80's console, translated
ticpak decode --log tic80.log   # the last error in a log of TIC-80's output
ticpak minify enemies.lua        # one module, minified, to stdout
```

A `SOURCE` that doesn't exist, or a file that isn't a `.lua`, is an error,
and so is a module `main.lua` requires that isn't there.

`ticpak --help` shows the options and these examples; this page is the full
reference.

### Checking any file

`ticpak check` on its own (or given a folder) checks the project's built
`<name>.tic` and prints the summary. It looks for it beside `main.lua` and in
`dist/` (the interactive build's default folder), and takes the newer if both
exist; a bare `ticpak` reports on the same one. With `-o`, it checks that
build's output instead: `ticpak check -o out/` checks `out/<name>.tic`, and
`ticpak check -o mygame.lua` gives a bundle the text-cart check below.
`bundle` doesn't look: without `-o` it always writes `<name>.tic` beside
`main.lua`.

Before the `.tic`, `ticpak check` looks at the sources:

```
modules: 3 required by main.lua
OK       player    player.lua
OK       lib.util  lib/util.lua
MISSING  enemies   enemies.lua not found
WARN     helpers   helpers.lua required by player.lua but not main.lua, so not packaged: add it to main.lua's requires
unreferenced: 12 other .lua files not required by main.lua (not packaged)
old/scrap1.lua
...
(+2 more)
header: complete in main.lua
```

- **modules**: each module `main.lua` requires, `OK` or `MISSING`. A module
  that only another module requires gets `WARN`: ticpak packages only what
  `main.lua` requires, so that `require` fails in the `.tic`.
- **unreferenced**: the other `.lua` files under `main.lua`'s folder that
  nothing requires, the first 10 of them. Built bundles (a `-- ticpak:` line)
  and `*.min.lua` files are left out.
- **header**: whether `main.lua`'s metadata header is complete, else what is
  missing. `check` reports it and goes on to the `.tic`, rather than stopping
  as `bundle` does.

A `MISSING` module or an incomplete header makes `check` exit with status 1,
as a violation in the `.tic` does.

`-r` writes the check's full report to a file, as for `bundle` (with no
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

### Errors from the packaged cart

TIC-80 reports a runtime error as a line of the bundle, and once minified
that line can hold a whole function, its names shortened:

```
[string "-- title:  My Game..."]:11: attempt to index a nil value (field 'd')
stack traceback:
	[string "-- title:  My Game..."]:11: in upvalue 'e'
	[string "-- title:  My Game..."]:12: in function 'enemies.a'
	[string "-- title:  My Game..."]:14: in function 'TIC'
```

`ticpak test` and `ticpak decode` translate it back. `ticpak test` runs the
package in TIC-80's window and passes on everything TIC-80 prints (its
console, `trace` included, goes to its standard output too), translating
each error as it happens. Close the window, or press Ctrl+C, to stop it. An
error it can't translate (from another chunk, or with no decode map) is
passed on as it is.

`ticpak decode` translates an error afterwards. Copy it in TIC-80's console:
select the message and its traceback with the mouse, press Ctrl+C, then run
`ticpak decode`. The console copies its 40-column rows with a newline after
each; ticpak joins them back into the lines TIC-80 printed. It takes the
error from the first of:

1. `-e TEXT`: the error itself.
2. `--log FILE`: the last error from the cart in a log of TIC-80's output
   (`tic80 mygame.tic > tic80.log`).
3. Standard input, when it is redirected (`ticpak decode < error.txt`).
4. The clipboard, when it holds an error from a cart. This reads the system
   clipboard (`pbpaste` on macOS; `wl-paste`, `xclip` or `xsel` on Linux).
5. A paste at the terminal: end it with Ctrl+D, or Ctrl+Z then Enter on
   Windows.

```
$ ticpak decode
error: the clipboard
map: the sources rebuilt (-m=max); they match mygame.tic

enemies.lua:13: attempt to index a nil value (field 'target')
stack traceback:
	enemies.lua:13: in upvalue 'chase'
	enemies.lua:23: in function 'enemies.update_all'
	main.lua:16: in function 'TIC'

source: enemies.lua:13
    local dx = enemy.target.x - enemy.x
```

Every location becomes `file:line` and every short name its original. A
minified line holds several source lines, so the name the message quotes
picks out which one: `d` occurs once on line 11, on what was
`enemies.lua:13`. A traceback frame is found the same way, by the call on
its line to the frame above. When nothing picks out one line (two calls to
the same function on one bundle line, say) it gives the range,
`main.lua:15-16`.

Both find the cart as `check` does (`<name>.tic` beside `main.lua` or in
`dist/`; `-o` and `-n` for another), and need its sources. (`test` runs the
cart as built, and says so when the sources have changed since.) The cart's
`-- ticpak:` line says how it was built, and minifying is deterministic, so
ticpak rebuilds the sources the same way in memory and checks that the
result is the cart's code. A folder build's
[`<name>.minify.json`](#the-decode-maps-nameminifytxt-and-nameminifyjson)
is used instead when it is that cart's. If the sources changed since the
build, it says so: the translation is then a best guess, so decode with the
sources as they were (check out the release), or rebuild and reproduce the
error. A change the minifier removes anyway (comments, unused code) still
matches, and the lines then refer to the files as they are now.

`-m` gives the options when the cart has no `-- ticpak:` line (built before
0.3.4) or isn't there at all; it is then decoded against a fresh build.
Locations in other chunks are left as they are. It works for any build,
unminified ones too.

### The minifier on its own

`ticpak minify FILE` minifies one Lua file and writes the result to stdout.
Each minify option is a flag of its own (`--comments`, `--rename-vars`,
`--rename-functions`, `--rename-tables`, `--constants`, `--whitespace`,
`--extra`); with none of them, the `default` options apply (every option but
`--rename-tables`), and `--max` applies every option.

```
ticpak minify enemies.lua > enemies.min.lua         # one module, the default options
ticpak minify --max enemies.lua > enemies.min.lua   # every option
ticpak minify --comments --whitespace enemies.lua   # just those options
ticpak minify dist/mygame.lua > small.lua           # an unminified bundle
```

It works out what the file is. A cart (`main.lua`, or a file with a metadata
header or asset sections) keeps its header and asset sections. A cart that
requires no modules, such as the unminified bundle `ticpak bundle -o
mygame.lua` writes, is the whole program, so `extra` removes anything it doesn't
use. Anything else, including a `main.lua` that requires modules, is minified
as one module: its globals are left alone, since other files may use them.
`ticpak minify --help` lists the flags; [docs/minify.md](docs/minify.md) has
the details.

### A module on its own

Give `bundle` a `.lua` file that is not `main.lua` and has neither a metadata
header nor asset sections, and ticpak treats it as one module rather than a
cart. There is no game name to read, nothing to inline and no cart to boot, so
it minifies the file on its own (as a fragment: its globals are left alone,
since other modules may use them) and writes `<module>.min.lua` beside it:

```
ticpak bundle enemies.lua -m              # enemies.min.lua, the default options
ticpak bundle enemies.lua -m -o small.lua # small.lua
ticpak bundle enemies.lua -m -o out/      # out/enemies.min.lua
```

`-m` works as for a cart, so leave it out and the copy is not minified. A
module can't be saved as a `.tic` (`-o NAME.tic` is an error), and
`ticpak check` has no package to check for it. A `.lua` that does have a
header or asset sections is a cart, whatever its name. A header here means at
least two metadata tags at the top, so a module whose opening comment happens
to begin `-- title: ...` stays a module; and asset sections run to the end of
the file, so a `-- <MAP> ...` comment in the middle of code doesn't count.

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
with a folder, the `.tic`, with the `.lua` and the report beside it) is newer
than `main.lua` and every module. `bundle` skips an up-to-date cart, so running it
on every save is cheap; it still prints the summary, then a hint that repeats
your command with `-f`, such as `hint: ticpak bundle -f -m -o dist/ to force
rebuild`, and one with the matching `ticpak check`. `check` and `test` on a
cart not built yet stop (status 1) with the command that builds it, such as
`hint: ticpak bundle -m to build`. Only file timestamps count, so after changing `-m` or upgrading
ticpak, use `bundle -f`. When your `-m` differs from the one the output was
built with (read from its `-- ticpak:` line), `bundle` says so, whether it
rebuilds or not:

```
note: it was built with -m; this command asks for no minification
note: the last build used -m; this command asks for -m=comments
```

### The summary

```
cart size: 110K
code: 41K (37%)
assets: 69K (63%)
code limit: 41K / 512K (8% used, 92% free)
original code size: 151K (73% reduction with minify: default)
```

- **cart size** is the `.tic` file's size.
- **code** and **assets** are its code and its asset sections (tiles,
  sprites, map, sound, palette, cover, ...), each as a share of the file.
  They don't add up to exactly 100%, because each section has a 4-byte header.
- The **code limit** line measures the code against TIC-80's 512K code
  limit ([TIC-80's limits](#tic-80s-limits)). From 90% it turns yellow and
  adds `- close to TIC-80's code limit`. At the limit it turns red and says
  `- over TIC-80's code limit`, and the check fails. A build never gets
  that far, because `bundle` stops first. The colours show only in a
  terminal.
- **original code size** is the code's size before minification and the
  saving, with the options used (`(73% reduction with minify: default)`), or `not
  minified`. The options come from the cart's `-- ticpak:` line, so `check`
  shows them too. A cart built before ticpak 0.3.4 has no such line, and
  then only the size and the saving show.
- With more than 64K of code, a last line says that editing it in TIC-80
  needs Pro. The cart still plays in every TIC-80:

  ```
  info: code over 64K needs TIC-80 PRO to edit it in TIC-80 (the cart plays in every TIC-80)
  ```

By default the summary, the status lines and any error or limit violation are
all ticpak prints. `--verbose` adds the progress lines, every size, anything
at 90% or more of a limit, every warning, and what minification saved
([below](#what-minification-saved)). `-q` prints nothing at all, and the
exit status alone says how the run went. [`-r`](#the-full-report--r) writes
everything `--verbose` shows, plus the check in full, to a file. Console
output is flush left, matching that report.

While a build runs, a gray progress bar on the line below the output says
what it is doing (`inlining modules`, `minifying`, `booting the bundle
headless in TIC-80`, `saving <name>.tic`) and is erased when the build ends,
so it leaves nothing behind. The boot takes about 10 seconds whatever the
cart's size, so most of the bar is that step. The bar shows only on a
terminal: never with `-q`, and never when the output is piped or redirected
(CI logs, `> log.txt`). Without colour (`NO_COLOR`) it is not gray, and on a
console that can't show block characters it is drawn with `#` and `-`.

### What minification saved

With `--verbose` (and in the [`-r` report](#the-full-report--r)), a minified
build shows, just before the summary, how many bytes each option took off
each source file:

```
minify: bytes saved, by file and option (negative: the option added bytes)
file                    source  comments  whitespace  constants  extra  rename-vars   total  reduction
main.lua                 3,752     2,924          87         10      3           56     672        82%
constants.lua            9,104     6,216       1,347      1,468      0           27      46        99%
helpers.lua              1,847     1,212         126         15     58          127     309        83%
...
(added by ticpak)          994         0          75          0   -241           51   1,109       -12%
total                   95,751    44,763      10,323      5,039    826        5,727  29,073        70%
```

- **source** and **total** are each file's code in the bundle, before and
  after minifying, in bytes of UTF-8, and **reduction** is the share
  minifying took off. Each row's options add up to the difference. The
  total row's `source` is the summary's original code size.
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
  can be negative where its aliases and shared literals (`local a,b=spr,"left"`) are declared, which is
  usually the `(added by ticpak)` row. That row is the bundle's own lines:
  the `package.preload` wrapper around each module.
- **rename-vars** and **rename-functions** run as one pass, so the names
  used most get the shortest, whatever they are. Each column counts what
  shortening its own names saved. **rename-tables** is a pass of its own: its
  column is what shortening table keys saved.
- A module that `extra` removed because nothing uses it ends with
  `(removed: unused)`.

After the table comes what the minified code is made of: strings, numbers,
keywords, operators, table field names, TIC-80 and Lua names, names never
renamed (globals the minifier can't safely rename, NOMINIFY names), variable
names and function names (renamed, or what renaming them would shorten),
NOMINIFY code, spaces and line breaks. Then the biggest names that stayed, by total bytes. That
shows where the rest of the code budget goes. A module built on its own gets
a one-row table.

### Interactive mode

Run `ticpak` with no command. If the cart has never been built, it prints
`hint: answer the questions below to build it (Ctrl+C to cancel)` and asks:

```
? Cart name (.tic): [mygame]
? Minification:
  1) default  - everything except rename-tables  [default]
  2) comments - remove comments only
  3) max      - all minification options
  4) none     - no minification (the bundled source verbatim)
  5) choose individual minification options...
? Minify options (space toggles, enter accepts):
   1) [x] comments          remove comments (keeps the metadata header and asset blocks)
   2) [x] rename-vars       rename variables to the shortest free names (1-2 letters)
   3) [x] rename-functions  rename functions to the shortest free names too (error messages then show the short names)
   4) [ ] rename-tables     rename table fields and methods too, where an analysis proves it safe (error messages then show the short names)
   5) [x] constants         inline constant values and remove the constants
   6) [x] whitespace        remove extraneous newlines and whitespace
   7) [x] extra             further optimisations
? Output:
  1) output mygame.tic only [default]
  2) output all files to a folder - mygame.tic (binary), mygame.lua (source), etc.
? Output folder: [dist/]
```

`Output folder` is asked only if you choose the folder. Minification
defaults to `default` here, unlike `bundle`, which minifies only with `-m`.
Options given on the
command line (`-m`, `-n`, `-o`) become the defaults, and the report is
written as in `bundle` (always for a folder, else with `-r`); `-o NAME.tic` or
`-o NAME.lua` already says what to write, so then only the minification is
asked. Without questionary, type the numbers to toggle (`2,5`) and press
Enter on an empty line to accept.

After the build it prints the `bundle` command that repeats your answers, for
later rebuilds, scripts, or setting up the same build elsewhere. Answers that
match the defaults are left out. Commands in hints are highlighted when the
terminal shows colour (not with `NO_COLOR` set):

```
hint: ticpak bundle -m=comments,whitespace -n mygame-lite -o dist/ to build with these settings again
```

If the default output (`<name>.tic` beside `main.lua`, or `-o`'s) already
exists, it asks nothing. It prints the status lines and a hint with the
command that rebuilds it as it was built, `-m` included (from its
`-- ticpak:` line), and the one that checks it, and exits:

```
hint: ticpak bundle -f -m -o dist/ to force rebuild
hint: ticpak check to check bundle info
```

With no terminal (piped input, CI) it doesn't guess. It tells you to use
`bundle` or `check` and exits with status 2. `-q` needs a command too, since
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

## TIC-80's limits

| | Limit | What ticpak does |
|---|---|---|
| Code | 512K: 524,287 bytes, in every TIC-80 build | `bundle` stops on code at or over it, before booting. `check` fails a `.tic` over it. The summary turns yellow from 90%. |
| Code over 64K | Plays everywhere. Only editing it in TIC-80 needs Pro. | The summary ends with an `info:` line, and the full report has an `INFO (non-PRO)` line. |
| Asset sections | Their own sizes (`MAP` 32,640 bytes, `SPRITES` 8,192, ...) in each of 8 banks | `check` fails any section over its limit. |
| Asset banks 1-7 | Load with `sync()`. Every build reads them; only editing them needs Pro. | An `INFO (non-PRO)` line, plus a warning when the code never calls `sync()` |
| `.tic` file | None | Nothing |

**Code over 64K plays everywhere.** That includes the free build, the web
player, tic80.com and the `export html`/`export win` builds. The free
TIC-80's code editor stops at 64K, so editing more than that in TIC-80
needs Pro. Players don't need it. tic80.com bears this out: in October 2026,
108 of its 4,630 carts had more than 64K of code, up to 511K, and 67 were
`.tic` files over 256K, up to 1 MB.

**How TIC-80 splits the code into banks.** A `.tic` stores code in chunks of
64K at most. When TIC-80 saves a cart (ticpak runs TIC-80 Pro's `save`), it
splits code longer than that into as many 64K `CODE` chunks as it needs, up
to 8. The start of the code goes in the highest-numbered chunk and the end
in chunk 0. When it loads a cart, TIC-80 joins them back into one program.
These code banks are only storage. Unlike asset banks, `sync()` never swaps
them, and your code doesn't change to use them. The full report lists them
as `CODE part 1`, `CODE part 2`, ... in program order. The 512K limit is
those 8 chunks of 64K, less one byte for the end of the text.

## Minification

Minification makes the code smaller: it keeps a large game inside the 512K
limit, under 64K if you want to edit it in the free TIC-80, or just
downloading faster. Without `-m` the bundle is not minified. `-m` on its own applies the
`default` options, every option but `rename-tables`;
`-m=max` applies every option; `-m=OPTION,...` applies only those (`default`
and `max` can be listed too: `-m=default,rename-tables` is `-m=max`).

| Option | What it does |
|---|---|
| `comments` | removes comments (keeps the metadata header and asset sections); nothing else changes |
| `rename-vars` | renames variables to the shortest free names (1-2 letters) |
| `rename-functions` | renames functions to the shortest free names too. Error messages then show the short names, so you need [`ticpak decode`](#errors-from-the-packaged-cart) to read them. Table fields and methods (`M.update`, `obj:draw`) are `rename-tables`' |
| `rename-tables` | renames table keys, fields and methods alike (`obj.speed`, `M.update`, `{hp=3}`), to the shortest free names too: one new name per key, everywhere. Library keys (`math.floor`, `s:sub`), metamethods, keys also written as a string, and keys a string built at runtime could spell keep their names. It renames only when an analysis of the whole program proves that safe; when it can't (say a `pairs` loop prints its keys), no key is renamed and the report says why ([details](docs/minify.md#table-keys-rename-tables)). Not in `default`: error messages then show short field and method names |
| `constants` | inlines constant values and removes the constants |
| `whitespace` | removes extraneous whitespace and newlines, packing lines to 120 columns |
| `extra` | everything else: folds constant expressions (`2*8` → `16`), removes unreachable code and anything nothing uses, call sugar (`f("x")` → `f"x"`), short local aliases for heavily used API functions (`spr`, `math.floor`, ...), shares strings and numbers written several times through one local each (only where that saves space), and merges adjacent `local` statements |

On one 20-module game (code characters):

| Minification | Code |
|---|---|
| none | 95,731 |
| `comments` | 47,773 |
| `comments,whitespace` | 40,964 |
| `-m=comments,rename-vars,constants,whitespace,extra` | 29,053 |
| `-m` (`default`: `rename-functions` too) | 27,346 |
| `-m=max` (`rename-tables` too) | 24,324 |

How much `rename-functions` adds depends on the code: about 2% for a game
whose functions live in module tables (`M.update`), and up to 12% for one
written as many global functions with long names. `rename-tables` took
another 2.3–11.4% off seven games (7.1% overall); it renamed nothing in an
eighth, which reads `load`.

With a [folder output](#output), every option past `comments` also writes
two maps of what minification did: `<name>.minify.txt` (what each pass did)
and `<name>.minify.json` (where each output line's tokens came from, and
every renamed identifier). See
[The decode maps](#the-decode-maps-nameminifytxt-and-nameminifyjson).
[`ticpak decode`](#errors-from-the-packaged-cart) translates a runtime error
from any build, with or without them: it needs only the cart and its
sources.

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
| directly above a function, or after its first or last line | the whole function, byte for byte, and its name (`rename-functions` leaves it alone, and `rename-tables` renames no key while kept code is in the cart) |
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
with `-DBUILD_PRO=On`. ticpak looks for it in this order, and uses the
first it finds:

1. `$TIC80`, if set to the binary's path;
2. `tic80` on `PATH`;
3. where TIC-80's own download puts it:
   - **Windows**: your `Downloads` folder, for a file named
     `tic80-v<version>-win.exe` (`tic80-v1.3-win.exe`, say), the highest
     version if there are several. ticpak works out which `Downloads` folder
     from the current folder: when you run it somewhere under
     `C:\Users\<you>\`, it looks in `C:\Users\<you>\Downloads`. Run from
     anywhere else, it skips this step;
   - **macOS**: the app dragged from the `.dmg`, `tic80.app` (or `TIC-80.app`)
     in `/Applications` or `~/Applications`;
   - **Linux**: `/usr/bin/tic80`, where the `.deb` package installs it, or
     `/usr/local/bin/tic80`.

ticpak doesn't search the disk beyond these. If none has it, ticpak stops with
`ticpak: no TIC-80 Pro binary found - install TIC-80 Pro
(https://nesbox.itch.io/tic80), or add tic80 to your PATH (or set $TIC80 to
its path)`. ticpak doesn't check that the binary it finds is Pro: a free
build fails the boot test.

## Output

`-o` says what a build writes. What it ends in decides which:

| `-o` | Writes | Example |
|---|---|---|
| *(none)* | `<name>.tic` only, in the folder holding `main.lua` | `mygame.tic` |
| `NAME.tic` | that `.tic` only | `-o mygame.tic`, `-o release/v2.tic` |
| `NAME.lua` | the bundle only | `-o mygame.lua` |
| a folder: ends in `/`, or has neither extension | `<name>.tic`, `<name>.lua` and the full report in it, plus the decode maps | `-o dist/`, `-o dist` |

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
| `<name>.bundle.txt` | [the full report](#the-full-report--r): the check in full, what minification saved, the summary | every build (`-r PATH` puts it elsewhere) |
| `<name>.minify.txt` | the minifier's report: what each option saved and each pass did | builds with any minify option past `comments` |
| `<name>.minify.json` | line and rename maps for decoding runtime errors | builds with any minify option past `comments` |

A single-file build writes the report only with `-r`. A folder build whose
report is missing is out of date, so `bundle` rebuilds it.

Every output is regenerated from your sources, so add it to your
`.gitignore` (`*.tic`, `dist/`) and never edit it. A folder build that writes
no minify files deletes any left over from an earlier minified build, because
they would no longer match the bundle.

### The `.lua` and the `.tic`

Both hold the same game: the same code and the same assets. They differ in
format, and in who writes them.

**`<name>.lua` is written by ticpak.** It is a text cart, the same format as
your `main.lua`: the metadata header, then the code, then the asset sections
(`-- <TILES>`, `-- <MAP>`, ...) as hex text. ticpak bundles it from
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
folder build or `-o NAME.lua`) is for reading, and for
exports: load it in TIC-80 and run `export html <name>` or
`export win <name>` for a web or native build (both need network access).

### The full report: `-r`

A folder build (`-o dist/`) always writes the full report,
`<name>.bundle.txt`, in the folder. Otherwise `bundle` and `check` write
nothing but the cart unless you ask: `-r` (or `--report`) also writes the
full report. Either way a `report:` line names the file. A `check` without
`-r` that finds a report a build left beside the output points at it
(`hint: see dist/<name>.bundle.txt for more info`).

| Form | Writes |
|---|---|
| `-r` | `<name>.bundle.txt` beside the output: beside `main.lua` by default, beside the file for `-o NAME.tic`/`NAME.lua` (in the folder for `-o dist/`, as without `-r`) |
| `-r PATH`, `--report=PATH` | that file |
| `-r DIR/` (or an existing folder) | `DIR/<name>.bundle.txt` |

A `PATH` is relative to the current folder. One ending in `.lua` or `.tic`
is an error: it is the `SOURCE` or an output read as the report's path. Put
`SOURCE` before `-r`, or write `--report=PATH`.

The report is the check of the `.tic` in full: every asset section's size
against its limit, how the code is stored, each memory bank that carries
data (every section in it and the bank's total, in bytes used of what it
holds, with the percentage; a bank holds 82,360 bytes), every header tag, whether there is a cover screenshot and any violations.
After a minified build, [what minification saved](#what-minification-saved)
comes next, then the summary. `--verbose` prints the parts that need
attention, and `ticpak check --verbose` prints all of the check.

An up-to-date single-file `bundle -r` writes the report of the `.tic` already
built, which has no savings table because nothing was minified in that run.
Add `-f` to rebuild. An up-to-date folder build leaves its report as the last
build wrote it. `check` writes a report only with `-r`, even for a folder
build. A module built on its own gets a report with its savings table and
sizes: with `-r`, or always when `-o` is a folder.

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
bank 0 SPRITES        8,187 /  8,192 bytes (100%)
bank 0 MAP           32,575 / 32,640 bytes (100%)
...
bank 0 total         56,210 / 82,360 bytes (68%)
unused   banks 1-7
...
header complete
title: My Game
...
screenshot (SCREEN) present
all checks OK

minify: bytes saved, by file and option (negative: the option added bytes)
...
cart size: 134K
...
```

### The decode maps: `<name>.minify.txt` and `<name>.minify.json`

Past `comments`, minification changes line numbers and renames variables
(and functions, with `rename-functions`, and table keys, with
`rename-tables`), so an error from the packaged cart
no longer points at your sources. A folder build (`-o dist/`) writes these two maps beside the bundle
to translate them back. [`ticpak decode`](#errors-from-the-packaged-cart)
reads `<name>.minify.json` (or makes the same map in memory), so you need
the file itself only to decode by hand or with your own tools. It holds:

- `"format"`: 2. `"build"`: the cart's `-- ticpak:` line (`"0.4.1 -m=max"`).
  `"code"`: a hash of the cart's code, which tells whether the map is that
  cart's.
- `"lines"` maps each bundle line to the source line of its first token:
  `"37"` gives, say, `["enemies.lua", 112]`. Lines that ticpak added itself
  map to `[null, 0]`.
- `"segments"` maps each bundle line to every place its tokens change source
  line, `[column, file, line]` with 0-based columns: `"37": [[0,
  "enemies.lua", 110], [24, "enemies.lua", 112], ...]`. The column of a name
  in the error message gives its source line.
- `"renames"` lists every renamed identifier, such as `{"new": "b", "old":
  "target", "kind": "local", "source": ["enemies.lua", 98], "uses": [[37,
  14], [41, 3]]}`. `source` is where it is declared; `uses`, for a variable,
  its first and last use in the bundle as `[line, column]`. A short name is
  reused, but only in places that never overlap, so the entry whose uses
  hold the error's position is the one. With `rename-tables`, a key in a
  message (`(field 'q')`, `in method 'q'`) has an entry of kind `"field"`:
  a key has the same new name everywhere, so there is only one.

`<name>.minify.txt` is the minifier's report for people: the code size after
each pass, the bytes each option saved, what the minified code is made of,
the biggest names that stayed, then every constant inlined, every piece of
code or variable
removed, every API function aliased, every literal shared, the table keys
renamed (or why none was), and everything kept by `NOMINIFY`, each
with its `file:line`. Read it when you want to know what happened to a
particular name, or attach it when reporting a minifier bug. The file
formats are described in [docs/minify.md](docs/minify.md#outputs).

Without minification, or with `comments` only, there are no map files, but
`ticpak decode` decodes those builds' errors all the same.

## AI agent skills

[`skills/ticpak`](skills/ticpak/SKILL.md) is an
[Agent Skill](https://agentskills.io) that teaches an AI coding agent (Claude
Code, Cursor, Codex, ...) to use ticpak in your game's project. It has three
actions, `/ticpak init`, `/ticpak bundle` and `/ticpak check`, and agents that
don't take arguments pick the action from what you ask:

| Action | What the agent does |
|---|---|
| `init` | sets up a new project, splits a single-file cart into modules, or reviews a project against ticpak's rules |
| `bundle` | builds the `.tic`, chooses minify options, fixes failed builds, decodes errors from a packaged cart |
| `check` | checks a cart's limits and explains how much room is left |

Install it into your game's project with the
[skills CLI](https://github.com/vercel-labs/skills), which detects your agents:

```
npx skills add dtempx/ticpak
```

Or copy `skills/ticpak/` into your agent's skills directory yourself
(`.claude/skills/` for Claude Code, `.agents/skills/` for most others).

### Updating the skill

The skill is a copy, so it doesn't change when you [update ticpak](#updating).
When the skill changes (new options, renamed actions, new error messages),
refresh it from your game's project folder:

```
npx skills update ticpak
```

Add `-g` if you installed it globally (`npx skills add -g ...`). If you copied
the folder by hand, delete your copy and copy `skills/ticpak/` in again, so
files that were removed or renamed don't linger. Restart your agent, or start a
new session, so it reads the new version.

## Inside ticpak

| Module | What it does |
|---|---|
| `ticpak/cli.py` | the command line, `--help`, the interactive questions, `main()` |
| `ticpak/bundle.py` | finds the cart, resolves `-o` into the outputs to keep, inlines the modules, minifies, writes `<name>.lua` and the decode maps; a module on its own; the up-to-date check; the `-- <` guard |
| `ticpak/run.py` | finds TIC-80 Pro, boots the bundle headless, saves `<name>.tic`; runs a cart in its window for `ticpak run` and `ticpak test` |
| `ticpak/report.py` | the summary, the `--verbose` detail (the minify savings table included), the `-r` report file |
| `ticpak/header.py` | the metadata header: the output name, missing tags, filling them in |
| `ticpak/scaffold.py` | `ticpak init`: a new project's `main.lua` and `game.lua` |
| `ticpak/console.py` | console output and the prompts (questionary or plain) |
| `ticpak/check.py` | the `.tic` limit and header checker (`ticpak check FILE...`) |
| `ticpak/errors.py` | `ticpak decode` and `test`: finds the decode map for a cart (its map file, or a rebuild checked against it) and translates an error with it; reads the clipboard, rejoins text copied from TIC-80's console, finds a log's last error, and translates TIC-80's output as it runs |
| `ticpak/minify.py` | the minifier (`ticpak minify`; [docs/minify.md](docs/minify.md), [docs/minify-spec.md](docs/minify-spec.md)) |

`scripts/update_reserved.py` refreshes the minifier's list of TIC-80 API
names and library keys (which renaming must never take) from a TIC-80 binary.

## Testing

```
pip install -e ".[test]"             # lupa: a real Lua 5.3 for the tests
python tests/options/test_options.py # every combination of minify options
python tests/minify/run.py           # the minifier's fixtures and fuzzing
python tests/error/test_error.py     # ticpak decode on real Lua 5.3 errors
```

`tests/error` gives small projects one bug each, makes each error both from
the sources as written and from the packaged cart (loaded as TIC-80 loads
it), and checks that `ticpak decode` turns the second into the first under
every minify preset. It also checks where the error text comes from: text
copied from TIC-80's console (laid out as `console.c` lays it out) rejoined,
a log's last error, and TIC-80's output as `ticpak test` reads it.

`tests/options` builds sample carts with every subset of minify options and
runs the original and minified code side by side in Lua 5.3, comparing what
they draw. It also checks that every asset layout (bank 0, banks 1-7, a
`SCREEN` cover, CRLF line endings) comes through the minifier and the bundle
byte for byte. Set `TICPAK_BOOT=1` to also boot the bundles in TIC-80 and
compare the saved `.tic`'s asset chunks with `main.lua`'s sections (about 12
minutes). `tests/minify` checks the minifier on fixtures and random
expressions; set `TICPAK_GAMES` to a folder of `<game>/tic80/` projects to
also run real games frame by frame against their minified bundles.

## License

MIT; see [LICENSE](LICENSE).

> **AI disclosure:** ticpak was developed with the help of AI coding assistants.
