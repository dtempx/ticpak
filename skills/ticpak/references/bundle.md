# ticpak bundle: package the cart

`ticpak bundle` writes `<name>.tic` (the file to upload) beside `main.lua`,
after booting the bundle headless, and checks it. `<name>` is the header's
`saveid`, else its `title`, made filename-safe. `-n NAME` overrides it.

`-o` picks the output, by how it ends (paths relative to the current folder):

| `-o` | Writes |
|---|---|
| *(none)* | `<name>.tic` beside `main.lua`, nothing else |
| `NAME.tic` | that `.tic` only |
| `NAME.lua` | the bundle only (still boot-tested and checked) |
| `DIR/`, or a name with neither extension | `DIR/<name>.tic`, `<name>.lua` (bundle), `<name>.bundle.txt` (the full report), and with `-m` past `comments` the decode maps `<name>.minify.txt`/`.json` |

Use a folder (`-o dist/`) whenever you need the bundle or the decode maps:
to read the bundle or the minify report, or for `export html`/`export win`.
Decoding an error needs neither: `ticpak decode` works from the `.tic` alone
(see the end of this file). `-n` with
`-o NAME.tic`/`NAME.lua` is an error: the file names itself.

A folder build always writes the full report (the check in full, what
minification saved, the summary) as `<name>.bundle.txt` in the folder. For a
single-file output, `-r` writes it beside the output. `-r PATH` or
`--report=PATH` writes it to that file, or into that folder. Put the cart's
path before `-r`, or `-r` takes it as the report's path; a `.lua` or `.tic`
there is refused.

A `.lua` other than `main.lua` with no metadata header (two tags or more at
the top) or asset sections (running to the end of the file) is a module on its
own: `ticpak bundle enemies.lua -m` minifies it (globals left
alone) to `enemies.min.lua` beside it, or to `-o`'s `.lua` or folder. It
can't be a `.tic`.

## Steps

1. **Check the header first**: `ticpak check main.lua`. Fill in any field it
   reports as `MISSING` (see the header rule in [SKILL.md](../SKILL.md)).
2. **Build.**

   ```
   ticpak bundle -f -m=comments
   ```

   - **`-f` forces a build.** Without it, `bundle` skips a cart whose
     timestamps are up to date, and timestamps don't notice a changed `-m`
     or a ticpak upgrade. A `note: it was built with -m; this command asks
     for ...` line means the existing output used a different `-m` from the
     one given.
   - **Write `-m=a,b` with `=`.** In `-m path/to/main.lua`, the path is read
     as the option list.

   Pick the minification from what the user asked for:

   | Flag | Result |
   |---|---|
   | *(none)* | the source inlined verbatim; fails if a module has a column-0 `-- <` comment |
   | `-m=comments` | comments removed, line structure kept: a readable cart and a safe default |
   | `-m=comments,whitespace` | lines packed to 120 columns |
   | `-m` | the `default` preset, every option but `rename-tables` (`comments,rename-vars,rename-functions,constants,whitespace,extra`): small; error messages show short function names (`ticpak decode` turns them back, as below) but still name fields and methods |
   | `-m=max` | every option, `rename-tables` too: the smallest cart, but error messages show short field and method names as well |

   On a 20-module game these gave 96K, 48K, 41K, 27K and 24K characters of
   code. Go further than `comments` only if the code is near TIC-80's 512K
   limit, the user wants it under 64K (editing more in TIC-80 needs Pro), or
   they want it as small as possible. Code past 64K plays in every TIC-80,
   tic80.com included. Choose `-m=max` only when `-m` isn't small
   enough: on eight games it saved up to another 11% (7% typical), most on code
   with many long field and method names. `rename-tables` renames keys
   only where an analysis proves it safe: if the report's `table keys:` line
   says `not renamed`, it names the reason and line (often a `pairs` loop
   that prints or concatenates its keys). That is a size note, not an error.
3. **Report the summary.** It is the last lines of the output (and of the
   report file, for a folder build or with `-r`):

   ```
   source: main.lua (21 modules)
   cart: mygame.tic (up-to-date)
   cart size: 110K
   code: 41K (37%)
   assets: 69K (63%)
   code limit: 41K / 512K (8% used, 92% free)
   original code size: 151K (73% reduction with minify: default)
   ```

   The code limit is TIC-80's 512K. From 90% the line adds `- close to
   TIC-80's code limit`. With more than 64K of code, a last line says
   `info: code over 64K needs TIC-80 PRO to edit it in TIC-80 (the cart
   plays in every TIC-80)`: pass it on as a note, since it isn't a problem.
   Exit status 1 means a limit or header violation, printed above the
   summary. Explain it using [check.md](check.md). `--verbose` adds progress and the
   check's detail.

   When the user wants the code smaller, build again with `--verbose` (or
   read the report file). Above the summary, a minified build then shows the
   bytes each option saved per source file:

   ```
   minify: bytes saved, by file and option (negative: the option added bytes)
   file                    source  comments  whitespace  constants  extra  rename-vars   total  reduction
   helpers.lua              1,847     1,212         126         15     58          127     309        83%
   ...
   total                   95,751    44,763      10,323      5,039    826        5,727  29,073        70%
   ```

   Point to the biggest `total` files (bytes after minifying), and to any
   with a low `reduction`. What the code is made of follows (its `function
   names rename-functions would shorten` line applies only without it, and
   its `table field and method names` line is what `-m=max` works on), then the biggest names never renamed, such as globals, which you
   can shorten by hand. A negative entry is normal. An inlined constant's
   bytes move to the file that reads it, and the `(added by ticpak)` row
   holds the aliases and shared literals `extra` declares. `(removed: unused)` marks a module
   that nothing uses.
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
| boot output with `[string "..."]:N:` or `stack traceback` | A syntax or runtime error during boot. Save the quoted output to a file and decode it with `ticpak decode -m=... --log boot.txt`, giving the same `-m` as the build (no `.tic` was saved, so the options must come from you), then fix the source. |
| `TIC-80 reads a line starting -- < ...` | A module comment starts `-- <` in column 0. Reword or indent it, or build with at least `-m=comments`. |
| `x.lua:N: a comment kept by NOMINIFY has a line starting -- <` | A comment that a `NOMINIFY` directive keeps would read as an asset section tag. Reword or indent that line. |
| `x.lua:N starts an asset section (-- <MAP>), but only main.lua's asset sections are packaged` | A module holds asset data, which would be cut off or silently stripped. Move the whole section into `main.lua`'s asset sections, merging with any existing section of the same name. |
| `no asset chunks found` | `main.lua` has no `-- <TILES>`-style section. Save the cart once from TIC-80 Pro, or add the `PALETTE` section from [init.md](init.md). |
| `entry stub requires no modules` | `main.lua` has no `require` lines. A single-file cart doesn't need ticpak. |
| `no TIC-80 Pro binary found` | Set `$TIC80` to the binary, or put `tic80` on PATH. ticpak also looks where TIC-80's download puts it: the newest `tic80-v*-win.exe` in the user's `Downloads` folder (Windows, run from under `C:\Users\<name>`), `/Applications/tic80.app` (macOS), `/usr/bin/tic80` (Linux `.deb`). Only Pro reads `.lua` carts, and it is a paid download from itch.io or a source build with `-DBUILD_PRO=On`. |
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

TIC-80 reports `[string "-- title: ..."]:37: message` and a `stack
traceback:`. Line 37 is a line of the **bundle**, not of a module, and once
minified it can hold a whole function; past `rename-vars` the names in the
message are short ones. Don't decode it by hand: `ticpak decode` does it, for
any build. Run it from the folder holding `main.lua` with the whole error,
traceback included: inline, or a file holding TIC-80's output (it decodes
the last error in it):

```
ticpak decode -e '[string "-- title: ..."]:37: attempt to ...'
ticpak decode --log tic80.log
ticpak decode            # the clipboard: when the user copied the error in TIC-80
```

A bare `ticpak decode` reads redirected stdin first, then the clipboard. Use
it only when the user says they copied the error, from TIC-80's console
(mouse select, Ctrl+C). ticpak rejoins the console's 40-column rows. If
the clipboard holds no error, it exits 1 with `no error to translate`.

To catch errors while the user plays, `ticpak test` runs the package in
TIC-80's window and prints everything TIC-80 prints, each error already
decoded. It returns only when the window is closed.

It finds the cart as `check` does (`<name>.tic` beside `main.lua` or in
`dist/`; `-o`/`-n` for another build) and prints the error with each
location as `file:line` and each name as written, then `source:` and the
error's source line. With `--log` or the clipboard it first prints where
the error came from (`error: the clipboard`). Read the `map:` or `WARN`
line it prints next:

| Line | Meaning |
|---|---|
| `map: dist/<name>.minify.json` or `map: the sources rebuilt (-m=...); they match <cart>` | exact: the map is that cart's |
| `map: <cart> not found; decoding against the sources built now` | there was no cart, so it decoded against a fresh build with the `-m` you gave |
| `WARN <cart> does not match the sources built now` | the sources (or `-m`, or the ticpak version) changed since the build: the result is a guess. Decode against the sources as they were at that release (check them out), or rebuild and reproduce the error |

A location `file:12-14` is a range: that bundle line held several calls the
error could be (the same function called twice, say). `ticpak decode` exits 1
with `no location in the cart found` when the text has no `[string
"..."]:N`; it needs `-m=...` when the cart has no `-- ticpak:` line (built
before 0.3.4) or is missing. `dist/<name>.minify.txt` (a folder build past
`comments`) lists what each pass removed, inlined or renamed, if you need
more than the error.
