# ticpak build: package the cart

`ticpak build` writes `<name>.tic` (the file to upload) beside `main.lua`,
after booting the bundle headless, and checks it. `<name>` is the header's
`saveid`, else its `title`, made filename-safe. `-n NAME` overrides it.

`-o` picks the output, by how it ends (paths relative to the current folder):

| `-o` | Writes |
|---|---|
| *(none)* | `<name>.tic` beside `main.lua`, nothing else |
| `NAME.tic` | that `.tic` only |
| `NAME.lua` | the bundle only (still boot-tested and checked) |
| `DIR/`, or a name with neither extension | `DIR/<name>.tic`, `<name>.lua` (bundle), `<name>.txt` (check report), and with `-m` past `comments` the decode maps `<name>.minify.txt`/`.json` |

Use a folder (`-o dist/`) whenever you need the bundle or the decode maps:
to decode an error, or for `export html`/`export win`. `-n` with
`-o NAME.tic`/`NAME.lua` is an error: the file names itself.

A `.lua` other than `main.lua` with no metadata header or asset sections is a
module on its own: `ticpak build enemies.lua -m` minifies it (globals left
alone) to `enemies.min.lua` beside it, or to `-o`'s `.lua` or folder. It
can't be a `.tic`.

## Steps

1. **Check the header first**: `ticpak check main.lua`. Fill in any field it
   reports as `MISSING` (see the header rule in [SKILL.md](../SKILL.md)).
2. **Build.**

   ```
   ticpak build -f -m=comments
   ```

   - **`-f` forces a build.** Without it, `build` skips a cart whose
     timestamps are up to date, and timestamps don't notice a changed `-m`
     or a ticpak upgrade.
   - **Write `-m=a,b` with `=`.** In `-m path/to/main.lua`, the path is read
     as the option list.

   Pick the minification from what the user asked for:

   | Flag | Result |
   |---|---|
   | *(none)* | the source inlined verbatim; fails if a module has a column-0 `-- <` comment |
   | `-m=comments` | comments removed, line structure kept: a readable cart and a safe default |
   | `-m=comments,whitespace` | lines packed to 120 columns |
   | `-m` | every option (`comments,rename,constants,whitespace,extra`): the smallest cart |

   On a 21-module game these gave 154K, 66K, 55K and 42K characters of code.
   Go further than `comments` only if the user wants the code under the free
   editor's 64K, or as small as possible. Code past 64K is fine on Pro, and
   every player loads it.
3. **Report the summary.** It is the last lines of the output (and, for a
   folder build, of `<dir>/<name>.txt`):

   ```
   source: main.lua (21 modules)
   cart: mygame.tic (up-to-date)
   size: 110K
   code: 41K (37%)
   assets: 69K (63%)
   41K / 64K code size limit (64% used, 36% free)
   151K unminified (73% reduction)
   ```

   Exit status 1 means a limit or header violation, printed above the
   summary. Explain it using [check.md](check.md). `--verbose` adds progress and the
   check's detail.
4. **Give the user the path to the `.tic`** (the `cart:` status line). That
   is the file tic80.com takes. For a web or native build, build with
   `-o dist/`, load `dist/<name>.lua` in TIC-80 and run `export html <name>`
   or `export win <name>`. Both need network access.

## When the build fails

| Message | Cause and fix |
|---|---|
| `metadata header is incomplete` | Fill in the listed tags in `main.lua`. |
| `module 'x' not found at ...` | `main.lua` requires a module that isn't at that path. Names are paths from the cart's folder (`a.b` is `a/b.lua`). |
| boot output with `module 'x' not found`, then `FAILED to boot alone` | A module that only another module requires. Add `require "x"` to `main.lua`: ticpak inlines only the modules named there. |
| boot output with `[string "..."]:N:` or `stack traceback` | A syntax or runtime error during boot. Decode `N` as below and fix the source. |
| `TIC-80 reads a line starting -- < ...` | A module comment starts `-- <` in column 0. Reword or indent it, or build with at least `-m=comments`. |
| `x.lua:N starts an asset section (-- <MAP>), but only main.lua's asset sections are packaged` | A module holds asset data, which would be cut off or silently stripped. Move the whole section into `main.lua`'s asset sections, merging with any existing section of the same name. |
| `no asset chunks found` | `main.lua` has no `-- <TILES>`-style section. Save the cart once from TIC-80 Pro, or add the `PALETTE` section from [init.md](init.md). |
| `entry stub requires no modules` | `main.lua` has no `require` lines. A single-file cart doesn't need ticpak. |
| `no TIC-80 Pro binary found` | Set `$TIC80` to the binary, or put `tic80` on PATH. ticpak also checks `tools/tic80.exe` and `tools/tic80/build/bin/tic80` in the nearest folder above. Only Pro reads `.lua` carts, and it is a paid download from itch.io or a source build with `-DBUILD_PRO=On`. |
| `-m` option list error naming a path | Write `-m=OPTION,...` with `=`, or put the cart path first. |
| `X not found` / `X is not a .lua file` | `SOURCE` must be an existing `.lua` file or a folder holding `main.lua`. |
| `-o X names the output file itself - drop -n` | `-n` goes only with a folder `-o` or none. |
| `is a module, not a cart, so it can't be saved as a .tic` | The source has no header or asset sections. Build `main.lua` instead, or give `-o NAME.lua`. |
| `the output would overwrite X` | `-o` points at `main.lua` or a module. Choose another name. |

If minification seems to change behaviour, rebuild with `-o dist/` to get
the decode maps, copy `dist/<name>.minify.txt` somewhere safe, then rebuild
without `-m` (that build deletes the decode maps, which would no longer
match). If the unminified build works, report it as a ticpak bug, with the
copied `.minify.txt` from the failing build.

## Decoding an error from a packaged cart

TIC-80 reports `[string "-- title: ..."]:37: message`. Line 37 is a line of
the **bundle**, not of a module. A default build keeps only the `.tic`, so
first rebuild the same way (same `-m`) with `-f -o dist/` to get
`dist/<name>.lua` and, past `comments`, its decode maps. The line numbers
match: the bundle is the same.

- **Built with any option past `comments`:** look up `"37"` under `"lines"` in
  `dist/<name>.minify.json`. It gives `[file, line]` in your sources. The
  file's `"renames"` list maps a short name in the message (`attempt to call
  a nil value (global 'q')`) back to the original name.
  `dist/<name>.minify.txt` lists what each pass removed, inlined or renamed.
- **Built with no `-m` or `-m=comments`:** open `dist/<name>.lua` at line 37.
  The nearest `package.preload["mod"] = function(...)` above it names the
  module. Without `-m`, the module's line is the bundle line minus that
  wrapper's line. With `-m=comments`, removed comment lines shift the
  numbering, so match the code text instead.
