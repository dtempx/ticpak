# ticpak check: limits and headroom

No TIC-80 binary is needed. From the project folder:

```
ticpak check --verbose                   # the built <name>.tic beside main.lua or in dist/, full report
ticpak check -o out/ --verbose           # a folder build's out/<name>.tic instead
ticpak check main.lua <name>.tic         # source header and package in one run
```

`ticpak check` needs a built cart, at the place the build put it. Without
`-o` it finds `<name>.tic` beside `main.lua` or in `dist/` (the newer if
both); for anywhere else, give the same `-o` the build used. If it says `(not built yet)`, it exits 1 with
`hint: ticpak bundle -m to build` (plus the `-o` given): build it first
([bundle.md](bundle.md)). Given files, `ticpak check` checks exactly those: any
`.tic` or text-cart `.lua` files. For a `.lua`, it checks the header and lists
the banks its `-- <MAP1>`-style section tags use. Both exit 0 when every check
passes and 1 on any violation. To keep the full report in a file, add `-r`
(`ticpak check -r` writes `<name>.bundle.txt` beside the `.tic`; `-r PATH`
writes it there). `-r` doesn't apply to `check FILE...`. Without `-r`, a
`hint: see <path> for more info` line names a report an earlier build left beside
the `.tic` (a folder build always writes one); read it for the savings by
file and option, which `check` alone doesn't show.

## What the report lines mean

`ticpak check` (not `check FILE...`) first lists the sources: `modules:`
with a status per module `main.lua` requires, `unreferenced:` with up to 10
other `.lua` files under its folder that nothing requires (then `(+N more)`),
and `header:` for `main.lua`'s metadata header.

| Line | Meaning | What to do |
|---|---|---|
| `MISSING  <module>  <path> not found` | `main.lua` requires a module whose file isn't there. A failure. | Create the file, fix the name in the `require`, or drop the `require`. |
| `WARN  <module> ... required by X.lua but not main.lua` | Only another module requires it. ticpak packages only `main.lua`'s requires, so this `require` fails in the `.tic`. Not a failure of `check`. | Add `require "<module>"` to `main.lua`. |
| `unreferenced: N other .lua files` | `.lua` files that aren't packaged. Not a failure. | Mention them; ask the user whether any should be required. |
| `header: MISSING` / `header: INCOMPLETE` | `main.lua`'s header is absent, or tags are missing or TIC-80's placeholders. A failure. | Fill in the tags named in `main.lua`. |
| `OVER  <SECTION> bank N` | An asset section exceeds its RAM region and would be truncated on load. A failure. | Shrink that section's data. |
| `OVER  code` | The code is at or over TIC-80's 512 KB code limit, so TIC-80 would cut it off. A failure. `bundle` stops on this before booting: `the code is N bytes, over TIC-80's 512K code limit`. | Minify (`-m`, then `-m=max`), or trim the code. |
| `MISSING  header field` | A required tag is absent, empty or still TIC-80's placeholder. A failure. | If `main.lua` fails, fill the tag in there. If `main.lua` passes but the `.tic` fails, the package is stale: rebuild with `ticpak bundle -f`. |
| `WARN  no SCREEN chunk` | No cover screenshot, so tic80.com shows a blank thumbnail. Not a failure. | Run the game in TIC-80, press **F7**, save `main.lua`, rebuild. If `main.lua` already has `-- <SCREEN>`, the package is stale: rebuild. |
| `WARN  banks N carry data but the code never calls sync()` | Data in banks 1–7 that nothing can load, since only `sync()` reads those banks. Often an editor leftover. | Ask the user whether it's intended. |
| `WARN  trailing bytes` | Bytes after the last chunk. The file may be damaged. | Rebuild. |
| `INFO  (non-PRO) ...` | Code over 64 KB, or data in banks 1–7. Never a failure. | Editing it in TIC-80 needs Pro, but every player loads it, including the web player and tic80.com. Pass this on as a one-line note. |

## Reporting

Give the user a compact table (section, used, capacity, utilization) and then
one line each for:

- **Banks**, e.g. "0 only (1–7 unused)" or "0, 1 (MAP), 3 (MAP)". The full
  report lists each used bank's sections and a `bank N total` line, in bytes
  used of the bank's 82,360 (`/ 82,360 bytes (NN%)`). Code is not
  banked. It is one program that TIC-80 saves in `CODE` chunks of up to
  64 KB each and joins back together on load, so never describe code as
  being "in banks".
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
| Code | 512 KB (524,287 bytes) in every build. Over 64 KB plays everywhere, but editing it in TIC-80 needs Pro. |
| TILES, SPRITES | 8,192 bytes each, per bank |
| MAP | 32,640 bytes per bank |
| SFX samples | 4,224 bytes |
| Waveforms | 256 bytes |
| Music patterns / tracks | 11,520 / 408 bytes |
| Palette / flags | 96 / 512 bytes |
| Screen | 16,320 bytes |
| One bank (all of the above but code) | 82,360 bytes |
| Total `.tic` | No limit (tic80.com hosts carts of up to 1 MB) |
