# ticpak check: limits and headroom

No TIC-80 binary is needed. From the project folder:

```
ticpak check --verbose                   # the built <name>.tic beside main.lua, full report
ticpak check -o dist/ --verbose          # a folder build's dist/<name>.tic instead
ticpak check main.lua <name>.tic         # source header and package in one run
```

`ticpak check` needs a built cart, at the place the build put it: give the
same `-o` the build used. If it says the `.tic` is not found, build it first
([build.md](build.md)). Given files, `ticpak check` checks exactly those: any
`.tic` or text-cart `.lua` files. For a `.lua`, it checks the header and lists
the banks its `-- <MAP1>`-style section tags use. Both exit 0 when every check
passes and 1 on any violation. To keep the full report in a file, add `-r`
(`ticpak check -r` writes `<name>.ticpak.txt` beside the `.tic`; `-r PATH`
writes it there). `-r` doesn't apply to `check FILE...`.

## What the report lines mean

| Line | Meaning | What to do |
|---|---|---|
| `OVER  <SECTION> bank N` | An asset section exceeds its RAM region and would be truncated on load. A failure. | Shrink that section's data. |
| `OVER  total file` | The `.tic` is over 256 KB, which hosting sites may reject. A failure. | Remove unused assets, or minify the code (`-m`). |
| `MISSING  header field` | A required tag is absent, empty or still TIC-80's placeholder. A failure. | If `main.lua` fails, fill the tag in there. If `main.lua` passes but the `.tic` fails, the package is stale: rebuild with `ticpak build -f`. |
| `WARN  no SCREEN chunk` | No cover screenshot, so tic80.com shows a blank thumbnail. Not a failure. | Run the game in TIC-80, press **F7**, save `main.lua`, rebuild. If `main.lua` already has `-- <SCREEN>`, the package is stale: rebuild. |
| `WARN  banks N carry data but the code never calls sync()` | Data in banks 1–7 that nothing can load, since only `sync()` reads those banks. Often an editor leftover. | Ask the user whether it's intended. |
| `WARN  trailing bytes` | Bytes after the last chunk. The file may be damaged. | Rebuild. |
| `INFO  (non-PRO) ...` | Code over 64 KB, or data in banks 1–7. Never a failure. | The free TIC-80 *editor* can't show this, but every player, including the web player, loads it. Pass this on as a one-line "fine on Pro" note. |

## Reporting

Give the user a compact table (section, used, capacity, utilization) and then
one line each for:

- **Banks**, e.g. "0 only (1–7 unused)" or "0, 1 (MAP), 3 (MAP)". Code is not
  banked. It is one program that a `.tic` stores in 64 KB pieces, so never
  describe code as being "in banks".
- **Screenshot**: present, or missing with the F7 fix.
- **Header**: complete, or the missing tags and which file lacks them.

Leave the SCREEN row out of the table. A cover is always a full 240×136
image, so its size says nothing about headroom.

Then add a few bullets on headroom:

- **100%**: full. Say what that means in practice, e.g. "no more music
  tracks" or "the waveform table is full".
- **90–99%**: nearly full. Give the bytes or slots left.
- **70–89%**: limited headroom. Give roughly what's left.
- **Under 70%**: say nothing, unless the section is one that usually fills
  up.

Use what you know about the game. For example, a MAP at 100% that holds level
data instead of tiles is expected.

## Limits

| Section | Limit |
|---|---|
| Code | 64 KB in the free editor, 512 KB with Pro (one program, never banked) |
| TILES, SPRITES | 8,192 bytes each, per bank |
| MAP | 32,640 bytes per bank |
| SFX samples | 4,224 bytes |
| Waveforms | 256 bytes |
| Music patterns / tracks | 11,520 / 408 bytes |
| Palette / flags | 96 / 512 bytes |
| Total `.tic` | 256 KB |
