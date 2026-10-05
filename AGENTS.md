# AGENTS.md

This file provides guidance to AI coding agents working with code in this repository.

## What this is

ticpak packages a multi-file TIC-80 Lua project (`main.lua` + modules loaded with `require`) into one uploadable `.tic`: it inlines modules as `package.preload` entries, optionally minifies, boots the bundle headless in TIC-80 Pro, saves the `.tic`, and checks it against TIC-80's limits. README.md is the full user reference; keep it in sync when behaviour or options change. `skills/ticpak/` is an Agent Skill for ticpak's *users'* agents (`SKILL.md` routes to `references/init.md`, `bundle.md`, `check.md`); it restates CLI flags, error messages and limits, so update it too when those change.

## Commands

```
pip install -e ".[prompts,test]"     # editable install; `test` adds lupa (real Lua 5.3)
python -m ticpak                      # run from a clone without installing

python tests/options/test_options.py              # every minify-option combination (~2 s)
python tests/options/test_options.py -k Behaviour # one test class (stdlib unittest)
TICPAK_BOOT=1 python tests/options/test_options.py -k Boot   # boots each in TIC-80, compares .tic assets (~4 min)
python tests/minify/run.py [fold|bytecode|fixtures]          # minifier suites
python tests/minify/difftest.py path/to/game/tic80            # frame-by-frame diff on a real port
python tests/minify/difftest.py --all                         # every <game>/tic80 under $TICPAK_GAMES

python tests/options/make_samples.py   # regenerate samples/ and project/main.lua after editing tests/options/code/
python scripts/update_reserved.py      # refresh minify.py's TIC-80 reserved-name block from the binary
```

There is no linter or pytest config; tests are plain scripts using stdlib `unittest`. Behaviour tests skip without `lupa`. Anything that boots TIC-80 needs the **Pro** binary, found via `$TIC80`, then `tools/tic80.exe` / `tools/tic80/build/bin/tic80` in the nearest ancestor folder, then `tic80` on PATH.

## Constraints

- Python 3.9+ and **no runtime dependencies** (questionary is an optional extra; `console.py` falls back to plain numbered prompts). Don't add required deps.
- Target Lua is TIC-80 1.2's embedded **Lua 5.3** (no `<const>`); every minifier semantic rule is Lua 5.3's.
- `bundle` and `check` must never prompt; only the bare `ticpak` command is interactive, and it exits with status 2 when there is no terminal.

## Before committing

Whenever you make a change, bump the version as part of it unless the uncommitted changes already bump it (check `git diff HEAD -- pyproject.toml ticpak/__init__.py`). Bump `version` in `pyproject.toml` and `__version__` in `ticpak/__init__.py` together and keep them equal: users install from git, so the version is how they, and bug reports, tell builds apart, and `ticpak --version` prints the one in `__init__.py`.

## Architecture

`cli.py` is only the front end (argparse, interactive questions, dispatch). The pipeline:

1. `bundle.py` — `find_cart` → `Target`, which turns `-o` into the outputs to keep (`out_kind`: none → `<name>.tic` beside `main.lua`; `X.tic` → that file only; `X.lua` → the bundle only; a folder → `<name>.lua`/`.tic`/`.txt` plus the decode maps; anything not kept is `None`). `is_cart` tells a cart (`main.lua`, or a header or asset sections) from a module on its own, which `minify_module` minifies as a fragment to `<module>.min.lua`. `freshness` (timestamp-only up-to-date check), `assemble` (header + stub + one `package.preload["mod"] = function(...) ... end` per required module; asset chunks set aside; `origin` maps each bundle line to `file:line`), then `minify.minify_cart_ex`, then `add_stamp` (the `-- ticpak: VERSION -m...` line after the header tags, added after minifying since the minifier would strip it; the decode map's output lines shift past it). `built_options` reads that line back from an existing `.tic`/`.lua`, for the force-rebuild hint's `-m` and the note when `-m` changed; the summary's `minify:` comes from it too. The bundle text goes to `t.code`, and to disk only for a folder build (then the `.minify.txt`/`.minify.json` decode maps for any option past `comments`) or, once it boots, for `-o X.lua` (`save_bundle`). Also guards against unminified comment lines starting `-- <`, which TIC-80 reads as the start of asset sections, and stops on an asset section in a module (minified, it would be stripped silently): only `main.lua`'s sections are packaged.
2. `run.py` — finds TIC-80 Pro, writes `t.code` into an isolated temp folder, boots it headless, saves the `.tic` (to `t.tic`, or a temp path for a `.lua`-only build's check).
3. `report.py` + `check.py` — parse the `.tic` chunks, check code budget/banks/cover/header, print the summary (the minify savings only as `--verbose` detail), and with `-r` write the full report to `t.txt` (`<name>.ticpak.txt` beside the output, or `-r PATH`; `Target` resolves it). `check.py` also serves `ticpak check FILE...`. `-q` swaps `sys.stdout` for devnull in `cli.main`, so nothing needs its own quiet switch; that includes `console.Progress`, the build's gray progress bar, which draws on the stream behind `sys.stdout` only when it is a real console. The pipeline moves it with `console.step(key, message, seconds)` (a no-op when no bar is showing), and `FlatStdout` erases and redraws it around each printed line.
4. `header.py` — metadata tags, output name (`saveid` → `title` → slug), filling in missing tags.

### The minifier (`minify.py`, ~3k lines, also `ticpak minify`)

Self-contained: lexer → AST parser → tree passes → emitter → layout. Key ideas that span the file:

- User-facing **options** (`OPTIONS`: comments, rename, constants, whitespace, extra) map to internal **passes** (`ALL_PASSES`: fold, inline, dce, shake, rename, sugar, alias, merge) via `OPTION_PASSES`; `whitespace` controls reflow, not a pass. Every option implies `comments`. The `max` preset exists only for the module API/tests; the `ticpak` CLI rejects presets.
- `minify_ex` short-circuits: no options → passthrough; `comments` only → `strip_comments` with a token-stream equality check; otherwise `minify_max`, which iterates fold/inline/dce/shake to a fixpoint, then sugar/alias/merge, then rename, then layout.
- Safety nets are deliberate: output is re-lexed and must equal the emitted tokens, re-parsed, and must not contain a `-- <X` line. Failing these raises `AssertionError` rather than emitting. Keep them.
- **Whole-program mode** (default) may inline/remove/rename globals because the bundle is the whole program; `whole_program=False` (fragment) never touches globals. Names that TIC-80 or Lua define are never renamed: `TIC80_GLOBALS` is an embedded generated block between `# <reserved>` markers (regenerate with `scripts/update_reserved.py`, don't hand-edit), plus `CALLBACKS` and `EXTRA_RESERVED`.
- Function names are never renamed and each function starts on its own line, so runtime errors stay decodable.
- `savings=True` (off by default) also measures what each option saved, by source line (`Savings`; every token carries its source line through the passes). It only measures and nothing reads it back. With `constants` and `extra` both on, `_max_savings` reruns the fixpoint loop with `inline` alone (`fixpoint_only`) to split them. `bundle.py` groups it per file through `origin` into `t.savings`; `report.savings_table` shows it as `--verbose` detail and in the `-r` report, never in the default output.
- `NOMINIFY` directives (a comment block, or a comment after code) attach to statements: they keep variables (pinned), functions, modules, the whole cart, or else their own comment. `directives()` resolves them against one parse; `protect` turns protected bodies into verbatim `raw` tokens and inserts kept comments as `comment` tokens (`Comment` statements / table fields).

`docs/minify-spec.md` is the contract, with requirement IDs (e.g. D7, R10c) that code and tests cite; `docs/minify.md` is usage. Update the spec when changing minifier semantics.

### Tests

- `tests/options/` runs original and minified sample carts under real Lua 5.3 against a logging stub of the TIC-80 API (`harness.lua`) and requires identical call logs. Samples rely on marker names (`renameme_*`, `keepme_*`, `pinned_*`, `keepfn_*`, `keepmod_*`, `CONST_*`, `unused_helper_fn`, ...) described in `tests/options/README.md`; `samples/` and `project/main.lua` are generated.
- `tests/minify/run.py` fuzzes constant folding against Lua, checks bytecode equality for rename-only output, and runs `fixtures.lua`; `difftest.py` compares real games frame by frame.
