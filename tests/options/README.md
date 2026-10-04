# tests/options — every combination of the minify options

Unit tests for the five minification options of
[`minify.py`](../../docs/minify.md) (`comments`, `rename`, `constants`,
`whitespace`, `extra`), on sample TIC-80 carts, and for `ticpak`'s use of
them.

```
python tests/options/test_options.py              # ~2 s
python tests/options/test_options.py -k Behaviour # one class
TICPAK_BOOT=1 python tests/options/test_options.py -k Boot   # ~4 min, runs TIC-80
```

Needs `lupa` (`pip install lupa`) for the behaviour tests, which skip without
it. The Boot class needs the TIC-80 Pro binary (found as `ticpak` finds it)
and is opt-in because it takes about 4 minutes: 22 headless TIC-80 runs.

## What is tested

The 5 options make 32 subsets. Every option but `comments` implies it, so they
collapse to 17 distinct effective sets. Every test runs every effective set
on every sample cart.

| Class | Checks |
|---|---|
| OptionParsing | empty set, the `max` API alias, unknown names and the old `default`/`all`/`none` presets rejected, implied `comments`, each raw subset gives exactly its effective set's output |
| CommandLine | `ticpak`'s `--minify`: absent = no minification, bare = every option, `=a,b` = just those; presets and `--no-minify` rejected; a path after `--minify` gets a hint |
| Structure | output re-lexes and re-parses; metadata header and asset sections byte-identical; header still complete for the checker; deterministic; a pass report and a valid line map exactly when an option past `comments` is on |
| OptionEffects | each option's signature, on and off: `none` is a passthrough; `comments` alone changes nothing but comments; no comment survives any option; `renameme_*` names shortened by `rename` only; `CONST_*` inlined **and their declarations removed** by `constants`; lines ≤ 120 columns with `whitespace`; source line breaks kept without it; unused function, dead branch, unrequired module and call sugar handled by `extra` |
| Behaviour | original and minified carts run under real Lua 5.3 against a logging stand-in TIC-80 API ([harness.lua](harness.lua)): `BOOT()` once, `TIC()` 12 times; the call logs (every argument with its type and integer/float subtype) must be identical |
| Sizes | adding any option never makes the code longer; `whitespace` never adds lines |
| Nominify | variable-level NOMINIFY: markers found on the right lines (not inside strings); the marked names survive `rename` and are reported |
| NominifyFunctionsAndModules | function- and module-level NOMINIFY: a directive on the declaration line, in the block above, in the block below; a function expression; an unused protected function (kept even by `extra`); a nested one; a module's top block; module level winning over function level; a blank line ending a block (module level at the top, nothing elsewhere); the whole cart; header tags not counting. Every protected body is byte for byte under every option set, and the names it uses (`pinned_*`, `PINNED_*`) survive `rename` and `constants` |
| Bundle | the multi-module [project/](project/) bundled by `ticpak.bundle.bundle()` for every set: assets and header kept, option signatures, same behaviour as the unminified bundle, `minify_label`, the stop on a `-- <` comment line in an unminified bundle |
| BundleAssets | the project rebuilt with each of `make_samples`' asset layouts, plus bank 0 with CRLF, bundled with no options, `comments` and all: asset sections kept by the bundler's own cart split; a cart with no sections stops; a section in a module stops every build, naming its line; a prose `-- <MAP> notes` comment in a module is just stripped when minified |
| Boot | (opt-in) each set's project bundle, then each asset layout's, boots headless in TIC-80 and saves a `.tic` that passes `ticpak check` and whose asset chunks equal `main.lua`'s sections decoded to bytes |

The suite was checked against deliberate faults (2026-10-03). Each of the
following made it fail:

- a one-character change to a minified cart;
- switching off the `constants` declaration removal;
- ignoring NOMINIFY;
- (2026-10-04) not pinning what protected code uses (12 failures), and
  finding no protected regions (19 failures).

## Files

| File | What it is |
|---|---|
| `test_options.py` | the tests (stdlib `unittest`) |
| `harness.lua` | the stand-in TIC-80 API: logs every call, deterministic `btn`/`time`/`math.random` |
| `make_samples.py` | writes `samples/*.lua` and `project/main.lua` from `code/` + generated assets; rerun after editing `code/` |
| `code/*.lua` | the sample programs: `basic` (game loop, constants), `bundle` (ticpak-shaped `package.preload` modules), `syntax` (Lua 5.3 edge cases), `nominify` (variable markers), `nominify_funcs` (function-level directives), `nominify_modules` (module-level directives in a bundle), `nominify_main` (a whole-cart directive; its header gets a NOMINIFY line), `markers` (text that looks like asset tags), `project_main` (the project's entry stub) |
| `samples/*.lua` | generated carts: code + header + assets in different layouts (none; bank 0's full set; chunks in banks 1–7; a 136-line SCREEN cover; a lone PALETTE), plus a CRLF copy of `basic` |
| `project/` | a multi-file port for the ticpak tests: `main.lua` (generated) requiring `constants`, `util`, `game` |

Marker names the tests look for in the samples: `renameme_*` must disappear
under `rename`; `keepme_*` (NOMINIFY) and `pinned_*`/`PINNED_*` (used inside
protected code) must never disappear; `keepfn_*` bodies and `keepmod_*`
modules must come out byte for byte; `CONST_*` must
disappear under `constants`; `unused_helper_fn`, `DEAD_BRANCH`,
`UNUSED_MODULE` and `("sugar_marker")` must disappear under `extra`.
