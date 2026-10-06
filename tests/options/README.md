# tests/options — every combination of the minify options

Unit tests for the seven minification options of
[`minify.py`](../../docs/minify.md) (`comments`, `rename-vars`,
`rename-functions`, `rename-tables`, `constants`, `whitespace`, `extra`) and
its two presets (`default`, `max`), on sample TIC-80 carts, and for `ticpak`'s
use of them.

```
python tests/options/test_options.py              # ~20 s
python tests/options/test_options.py -k Behaviour # one class
TICPAK_BOOT=1 python tests/options/test_options.py -k Boot   # ~12 min, runs TIC-80
```

Needs `lupa` (`pip install lupa`) for the behaviour tests, which skip without
it. The Boot class needs the TIC-80 Pro binary (found as `ticpak` finds it)
and is opt-in because it takes about 12 minutes: 70 headless TIC-80 runs.

## What is tested

The 7 options make 128 subsets. Every option but `comments` implies it, so
they collapse to 65 distinct effective sets. Every test runs every effective
set on every sample cart.

| Class | Checks |
|---|---|
| OptionParsing | empty set, the `default` and `max` presets, unknown names (`rename`, `all`, `none`, ...) rejected, implied `comments`, each raw subset gives exactly its effective set's output |
| CommandLine | `ticpak`'s `--minify`: absent = no minification, bare = `default` (every option but `rename-functions` and `rename-tables`), `=max` = every option, `=a,b` = just those; other names rejected; a path after `--minify` gets a hint; `-q` (not without a command, not with `--verbose`); `-r` alone, `-r PATH`, `-r=PATH`, `--report=PATH`, a `.lua`/`.tic` path refused, not with `check FILE...`; the rerun hint's `-r`; `ticpak minify`'s flags (none = `default`, `--max`, `--rename-functions`, `--rename-tables`) |
| Outputs | `-o` kinds and targets; `-r`'s report path beside each output, in a folder, or a named file; the interactive minification menu (`default`, `comments`, `max`, `none`, then the checkboxes) and the rerun command's `-m` / `-m=max` |
| Structure | output re-lexes and re-parses; metadata header and asset sections byte-identical; header still complete for the checker; deterministic; a pass report and a valid line map exactly when an option past `comments` is on |
| OptionEffects | each option's signature, on and off: `none` is a passthrough; `comments` alone changes nothing but comments; no comment survives any option, except those a NOMINIFY directive keeps; `renameme_*` names shortened by `rename-vars` only; `renamefn_*` functions shortened by `rename-functions` only, and `keepfn_*` never; `renamekey_*` table keys (fields, a method, a key literal) shortened by `rename-tables` only, and `keepkey_*` (also written as a string) never; `CONST_*` inlined **and their declarations removed** by `constants`; lines ≤ 120 columns with `whitespace`; source line breaks kept without it; unused function, dead branch, unrequired module and call sugar handled by `extra` |
| RenameTables | `rename-tables` on small programs: library keys, metamethods, `n` and keys also written as a string keep their names, others are renamed; key literals become fields; methods and functions in tables are renamed, at their first line in the decode map; keys a `string.format` or `..` could spell are kept; each reason the pass turns off (fragment, dynamic access, a key built at runtime, a key printed, joined, ordered or sorted, a `gsub` table, NOMINIFY code) is in the report; 80 keys get distinct new names that collide with nothing kept; `default` leaves keys alone; behaviour under Lua 5.3 |
| Behaviour | original and minified carts run under real Lua 5.3 against a logging stand-in TIC-80 API ([harness.lua](harness.lua)): `BOOT()` once, `TIC()` 12 times; the call logs (every argument with its type and integer/float subtype) must be identical |
| Sizes | adding any option never makes the code longer; `whitespace` never adds lines |
| Summary | the closing summary's lines and arithmetic on a hand-made `.tic`; the savings table only with `--verbose` and in the `-r` report, never in the default output |
| Savings | what each option saved (`savings=True`), on every set: same output as without it; bytes balance line by line, `before` is the input's size and `after` the output's; an option that is off saves nothing; what the code is made of adds up to the output, no entry negative; `constants` and `extra` each get a share with both on, and so do `rename-vars` and `rename-functions`; `rename-tables` gets its own share, alone and with every option; the report's section; the bundle's per-file groups (`main.lua`, modules in require order, `(added by ticpak)` last) and `savings_table`'s columns and `(removed: unused)` mark |
| Nominify | variable-level NOMINIFY: a comment after the declaration or assignment, a block above it, the closing line of a multi-line statement, a `for` variable; not inside strings, not part of a longer word; the kept names survive `rename-vars`, `constants` (not inlined) and `extra` (not removed), and are reported |
| NominifyFunctionsAndModules | function- and module-level NOMINIFY: a directive on the declaration line, in the block above, on the closing line; a function expression; a block inside a body keeping only itself, not the function; an unused protected function (kept even by `extra`); a nested one; a module's top block; module level winning over function level; a blank line ending a block (module level at the top, nothing elsewhere); the whole cart; header tags not counting. Every protected body is byte for byte, and its function's name kept, under every option set, and the names it uses (`pinned_*`, `PINNED_*`) survive `rename-vars`, `rename-functions` and `constants` |
| NominifyComments | kept comments: a block before a blank line (at the top of a cart's code too), above a call, between table fields, after a `return`, at the end of a block, after code with no variable; one inside a call's arguments moved after the call; one in unused code removed with it by `extra`; a kept `-- <` line stops; the word must stand alone |
| Bundle | the multi-module [project/](project/) bundled by `ticpak.bundle.bundle()` for every set: assets and header kept, option signatures (`renamekey_spin` renamed across modules by `rename-tables`), same behaviour as the unminified bundle, `minify_label`, the `-m` flag a build records read back (an older build's `rename` too), the stop on a `-- <` comment line in an unminified bundle |
| BundleAssets | the project rebuilt with each of `make_samples`' asset layouts, plus bank 0 with CRLF, bundled with no options, `comments` and all: asset sections kept by the bundler's own cart split; a cart with no sections stops; a section in a module stops every build, naming its line; a prose `-- <MAP> notes` comment in a module is just stripped when minified |
| Boot | (opt-in) each set's project bundle, then each asset layout's, boots headless in TIC-80 and saves a `.tic` that passes `ticpak check` and whose asset chunks equal `main.lua`'s sections decoded to bytes |

The suite was checked against deliberate faults (2026-10-03). Each of the
following made it fail:

- a one-character change to a minified cart;
- switching off the `constants` declaration removal;
- ignoring NOMINIFY;
- (2026-10-04) not pinning what protected code uses (12 failures), and
  finding no protected regions (19 failures).
- (2026-10-05) keeping no variables a directive marks (39 failures), and
  keeping no comments (19 failures).
- (2026-10-06) five faults in `rename-tables`' analysis, each caught by
  `tests/minify/run.py fixtures` and mostly by `TestRenameTables` too: no
  library keys (14 fixtures, 5 tests), `type()` results unknown (2, 1), a
  concatenation never a key (2, 1), `__index`'s argument not a key (2
  fixtures), `pairs` keys not keys (9, 4).

## Files

| File | What it is |
|---|---|
| `test_options.py` | the tests (stdlib `unittest`) |
| `harness.lua` | the stand-in TIC-80 API: logs every call, deterministic `btn`/`time`/`math.random` |
| `make_samples.py` | writes `samples/*.lua` and `project/main.lua` from `code/` + generated assets; rerun after editing `code/` |
| `code/*.lua` | the sample programs: `basic` (game loop, constants, a table with renamable keys), `bundle` (ticpak-shaped `package.preload` modules), `syntax` (Lua 5.3 edge cases), `nominify` (variable markers), `nominify_funcs` (function-level directives), `nominify_modules` (module-level directives in a bundle), `nominify_main` (a whole-cart directive; its header gets a NOMINIFY line), `nominify_comments` (comments a directive keeps; `KEPT_*` must survive, `GONE_*` must not), `markers` (text that looks like asset tags), `project_main` (the project's entry stub) |
| `samples/*.lua` | generated carts: code + header + assets in different layouts (none; bank 0's full set; chunks in banks 1–7; a 136-line SCREEN cover; a lone PALETTE), plus a CRLF copy of `basic` |
| `project/` | a multi-file port for the ticpak tests: `main.lua` (generated) requiring `constants`, `util`, `game` |

Marker names the tests look for in the samples: `renameme_*` must disappear
under `rename-vars`; `renamefn_*` (functions) under `rename-functions`;
`renamekey_*` (table keys) under `rename-tables`, while `keepkey_*` (a key
also written as a string) must stay; `keepme_*` (NOMINIFY) and `pinned_*`/`PINNED_*` (used inside
protected code) must never disappear; `keepfn_*` bodies and `keepmod_*`
modules must come out byte for byte; `CONST_*` must
disappear under `constants`; `unused_helper_fn`, `DEAD_BRANCH`,
`UNUSED_MODULE` and `("sugar_marker")` must disappear under `extra`.
