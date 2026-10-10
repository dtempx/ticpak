# ticpak init: set up a multi-file project

`ticpak init` starts a new project; splitting or reviewing an existing one
is done by hand. Either way, prove the result with `ticpak bundle`. First
look at the folder:

| The folder has | Do |
|---|---|
| no `main.lua` | [New project](#new-project) |
| a `main.lua` with all the code in it | [Split a single-file cart](#split-a-single-file-cart) |
| a `main.lua` that already `require`s modules | [Review an existing project](#review-an-existing-project) |

## The layout ticpak expects

```
mygame/
  main.lua        the cart: metadata header, entry stub, asset sections
  game.lua        modules, beside the cart...
  state/play.lua  ...or in subfolders: require "state.play"
  <name>.tic      ticpak's output (dist/ with -o dist/): add both to .gitignore
```

`main.lua` has three parts, in this order:

```lua
-- title:   My Game
-- author:  your name
-- desc:    one line about the game
-- site:    https://github.com/you/mygame
-- license: MIT License
-- version: 0.1
-- script:  lua

require "game"

function BOOT() game_init() end
function TIC() game_update() game_draw() end

-- <PALETTE>
-- 000:1a1c2c5d275db13e53ef7d57ffcd75a7f07038b76425717929366f3b5dc941a6f673eff7f4f4f494b0c2566c86333c57
-- </PALETTE>
```

1. **The metadata header.** See the header rule in [SKILL.md](../SKILL.md).
   Add `-- saveid: <author>_<game>` if the game uses `pmem`; see
   [Saves](#saves-need-a-saveid).
2. **The entry stub.** The `require` lines and the callbacks, and nothing
   else.
3. **The asset sections** (`-- <TILES>`, `-- <MAP>`, `-- <SFX>`, ...). TIC-80
   writes these when you save from its editors, and ticpak needs at least
   one. The `PALETTE` section above is TIC-80's default palette, so a new
   cart has one before anything has been drawn.

## The rules ticpak relies on

- **List every module in `main.lua`, with a literal name.** ticpak inlines
  exactly the modules named by `require "name"` or `require("name")` in
  `main.lua`'s code. A module that only another module requires is **not**
  bundled, and the build fails its boot test with `module 'x' not found`.
  Modules may also require each other (Lua caches each one), but every one
  must appear in `main.lua`'s list too.
- **The `require` order is the execution order.** A module's top-level code
  runs at its first `require`, so put modules that define constants and
  helpers first. Keep top-level code to definitions and do runtime setup in
  `BOOT()`.
- **Names are paths from the cart's folder.** `require "player"` is
  `player.lua` beside `main.lua`, and `require "state.play"` is
  `state/play.lua`. Don't name a module `main`.
- **No line may start `-- <` in column 0** in any module, e.g.
  `-- <MAP> layout notes`. TIC-80's loader reads such a line as the start of
  the asset sections and cuts the code there. Indent such comments, or reword
  them. An unminified build stops on one and names the line.
- **Asset sections belong in `main.lua` only.** ticpak copies `main.lua`'s
  sections into the package unchanged and packages no others. A section in a
  module (a tag such as `-- <MAP>` alone on its line) stops every build,
  minified or not. Move it into `main.lua`.

## New project

1. Run `ticpak init` in the project folder (or `ticpak init FOLDER`, which
   makes the folder if missing). It never prompts. It writes `main.lua` (a
   header, the stub `require "game"` with `BOOT` and `TIC` calling
   `game.init`, `game.update` and `game.draw`, and the default `PALETTE`
   section) and `game.lua`, a module defining the global table `game`,
   which draws the title. If a `main.lua`, `src/main.lua` or `game.lua` is
   there already it stops with `ticpak: <path> already exists - ...`, exit
   status 1, and writes nothing: use the other rows of the table above
   instead.
2. The header has the folder's name as `title`, `0.1` as `version`, and
   TIC-80's placeholders for `author`, `desc`, `site` and `license`, which
   `ticpak bundle` rejects (`header: INCOMPLETE`). Ask the user for the
   author, title, a one-line description, `site`, `license` and `version`,
   and edit those lines in `main.lua`.
3. Add `*.tic` and `dist/` to `.gitignore`.
4. Run `ticpak bundle -f` to prove the bundle boots on its own (see
   [bundle.md](bundle.md)), and tell the user how to run it while developing.

## Split a single-file cart

1. Keep the header and the asset sections in `main.lua`. Fill in any missing
   header tags.
2. Move the code into modules by concern: constants, helpers, one module per
   entity or system, one per game state. Keep each module roughly under 150
   lines.
3. Replace the moved code in `main.lua` with the `require` lines, in an order
   where each module's top-level code finds what it needs, followed by `BOOT`
   and `TIC`.
4. Run `ticpak bundle -f`. If the original cart had a known-good behaviour,
   compare it against the built cart in TIC-80.

Shared state that many modules use (the score, the current state's update and
draw functions) can stay global. A module that owns its data can return a
table (`local M = {} ... return M`), and callers bind it with
`local player = require "player"`.

## Review an existing project

Check it against the rules above, in this order:

1. `ticpak check main.lua`: the header is complete.
2. Every `require` anywhere in the modules names a module that `main.lua`
   also requires.
3. No module has a column-0 `-- <` line (`grep -n "^-- <" *.lua`, apart from
   `main.lua`'s asset sections).
4. Nothing blocks the minifier (see [below](#writing-code-that-minifies-well)).
5. `pmem` without a `saveid`.

Report what you find, fix it if the user agrees, then run `ticpak bundle -f`.

## The dev loop

- **Launch TIC-80 Pro with the cart's folder as the working directory.**
  `require` searches `.\?.lua` relative to the process's current directory,
  not the cart's folder:

  ```
  cd mygame
  tic80 main.lua
  ```

  Launched from anywhere else, it fails with `module '...' not found`.
- **Edit modules, then press Ctrl+R** (or type `run` in the console). Each run
  starts a fresh Lua VM, so it reloads every module. TIC-80's auto-reload
  watches only `main.lua`.
- **Edit art, map and sound in TIC-80's editors, and save.** Never write game
  code in TIC-80's code editor, which shows only the stub. Don't rewrite
  `main.lua` in another program while TIC-80 holds unsaved changes to it,
  because the last save wins.
- Press **F7** in the running game to capture the cover screenshot, then
  save. This writes a `-- <SCREEN>` section, which is the thumbnail tic80.com
  shows.

## Writing code that minifies well

ticpak's minifier is opt-in (`-m`). It is verified against real Lua 5.3 and
never changes behaviour. Its whole-program options do assume that the bundle
is the whole program. Write the game this way and every option stays
available:

- **Write for the reader, not for size.** Comments, indentation and long names
  cost nothing in a minified cart. TIC-80's 512 KB code limit (64 KB to
  edit without Pro) applies to the *packaged* code, which is often less than
  half the source. Don't golf the modules.
- **Avoid dynamic global access**: `_G`, `_ENV`, `load`, `loadstring`,
  `dofile`, `loadfile`, `rawget`, `rawset`, `rawequal`, `debug`, a
  `require` with a computed name, or `pcall(require, "m")`. Any of these
  switches off every pass that touches globals. The `.minify.txt` report names
  the line that caused it.
- **Mark names something reads as strings.** If a debugger, another cart or a
  string lookup needs a variable's real name, put a `NOMINIFY` comment
  directly above its `local` or assignment, or after it on the same line. The
  variable then keeps its name, declaration and value. A `NOMINIFY` comment
  directly above a function, or after its first or last line, keeps the whole
  function byte for byte. In a module's top comment block it keeps the whole
  module. A `NOMINIFY` comment anywhere else (followed by a blank line, or
  above a call) keeps just itself, for credits or licence lines. A blank
  line ends a comment block, and the word must stand alone (`NOMINIFY_X`
  doesn't count). A kept comment line must not start `-- <`.
- Every TIC-80/Lua global is never renamed. Function names are renamed by
  `-m` (the `rename-functions` option; `ticpak decode` turns tracebacks back
  into source names), and table fields and methods only by the opt-in
  `rename-tables` (in `-m=max`), so a plain `-m`'s tracebacks still name
  fields and methods. A `NOMINIFY` comment on a function keeps its name too.
- `rename-tables` gives a key the same new name everywhere and checks the
  whole program first: it keeps library keys, metamethods, keys also written
  as strings and keys a built string could spell (`t["sprite_" .. i]`). It
  renames nothing if a `pairs` loop shows its keys (prints, concatenates,
  sorts them), if a key is built from data it can't pin down, or if any code
  is kept by `NOMINIFY`. To let it run, show a label looked up by the key
  (`LABELS[k]`, with `LABELS = {speed = "Speed"}`) rather than the key
  itself.

Details: [docs/minify.md](https://github.com/dtempx/ticpak/blob/main/docs/minify.md).

## Saves need a saveid

Without a `-- saveid:` tag, TIC-80 keys a cart's `pmem` save data by the
cart's hash. Every rebuild then changes the hash and orphans the player's
saves. If the game calls `pmem`, add `-- saveid: <author>_<game>`. ticpak also
uses `saveid` to name its output files.
