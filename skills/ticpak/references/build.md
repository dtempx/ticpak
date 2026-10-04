# ticpak build: package the cart

`ticpak build` writes `dist/<name>.lua` (the bundle) and `dist/<name>.tic`
(the file to upload), then checks the `.tic`. `<name>` is the header's
`saveid`, else its `title`, made filename-safe. `-n NAME` overrides it.

## Steps

1. **Check the header first**: `ticpak check main.lua`. Fill in any field it
   reports as `MISSING` (see the header rule in [SKILL.md](../SKILL.md)).
2. **Build.**

   ```
   ticpak build -f -m=comments
   ```

   - **`-f` forces a build.** Without it, `build` skips a cart whose
     timestamps are up to date, and timestamps don't notice a changed `-m`,
     `-n` or `-o`, or a ticpak upgrade.
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
3. **Report the summary.** It is the last lines of the output, and of
   `dist/<name>.txt`:

   ```
   source: main.lua (21 modules)
   cart: dist/mygame.tic (up-to-date)
   size: 110K
   code: 41K (37%)
   assets: 69K (63%)
   41K / 64K code size limit (64% used, 36% free)
   151K unminified (73% reduction)
   ```

   Exit status 1 means a limit or header violation, printed above the
   summary. Explain it using [check.md](check.md). `--verbose` adds progress and the
   check's detail.
4. **Give the user the path to `dist/<name>.tic`.** That is the file
   tic80.com takes. For a web or native build, load `dist/<name>.lua` in
   TIC-80 and run `export html <name>` or `export win <name>`. Both need
   network access.

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

If minification seems to change behaviour, copy `dist/<name>.minify.txt`
somewhere safe, then rebuild without `-m` (that build deletes the decode maps,
which would no longer match). If the unminified build works, report it as a
ticpak bug, with the copied `.minify.txt` from the failing build.

## Decoding an error from a packaged cart

TIC-80 reports `[string "-- title: ..."]:37: message`. Line 37 is a line of
the **bundle** `dist/<name>.lua`, not of a module.

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
