---
name: ticpak
description: Package a multi-file TIC-80 Lua game (a main.lua cart plus modules loaded with require) into one uploadable .tic with ticpak. Actions are init (set up a new project, split a single-file cart into modules, or check an existing project's layout), build (bundle, minify, boot-test, save the .tic, fix a failed build, decode an error from a packaged cart) and check (check a cart against TIC-80's limits and explain how much room is left). Use for any of these, or when writing TIC-80 Lua that has to survive bundling and minification.
argument-hint: "[init|bundle|check] [ticpak options]"
license: MIT
compatibility: ticpak needs Python 3.9+. build also needs the TIC-80 Pro binary. Targets TIC-80 1.2 (Lua 5.3).
---

# ticpak

A TIC-80 cart is one file, but in TIC-80 **Pro** a text cart (`main.lua`) can
`require` Lua modules from disk, which is how a larger game is developed.
tic80.com, the web player and `export html`/`export win` have no filesystem.
ticpak closes that gap: it inlines the modules into one cart, optionally
minifies it, boots it headless to prove it runs, saves `<name>.tic` beside
`main.lua` (`-o` can choose a `.tic`, the `.lua` bundle, or a folder of
both plus the full report `<name>.bundle.txt`, which `-r` adds to a
single-file build) and checks it
against TIC-80's limits.

## Pick the action

If the skill was invoked with arguments (`/ticpak bundle -m`), the first word
is the action and the rest are options for the `ticpak` command. Otherwise,
work out the action from the request, then read its reference file before
acting:

| Action | When | Read |
|---|---|---|
| `init` | a new project, splitting a single-file cart into modules, adding a module, running the game from its modules, a "will this package?" review | [references/init.md](references/init.md) |
| `bundle` | build, package, bundle, minify, release or upload; a failed build; an error from a packaged or minified cart | [references/bundle.md](references/bundle.md) |
| `check` | check or audit a `.tic`, how much room is left, explaining a limit violation | [references/check.md](references/check.md) |

With no arguments and nothing in the request to go on, look at the folder:
no `main.lua` means `init`, no built `.tic` (`<name>.tic` beside `main.lua`,
or in `dist/` for a folder build), or sources newer than it, means `bundle`,
otherwise `check`.

## Rules for every action

- **Always pass a command: `ticpak bundle` or `ticpak check`.** A bare `ticpak`
  is interactive. With no terminal it refuses to run and exits with status 2.
  `bundle` and `check` never prompt: anything missing becomes an error message.
  Don't pass `-q`: it prints nothing, so you'd have only the exit status
  to read.
- **Find the tool.** Check that `ticpak --version` works. If it doesn't, use
  `uvx --from git+https://github.com/dtempx/ticpak ticpak ...` for a one-off
  run, or install it with
  `uv tool install "ticpak @ git+https://github.com/dtempx/ticpak"`
  (no uv? see the README's "Installing uv"). It is one command: checking
  files and minifying are `ticpak check FILE...` and `ticpak minify FILE`
  (stdout; flags `--comments`, `--rename-vars`, `--rename-functions`,
  `--rename-tables`, `--constants`, `--whitespace`, `--extra`, or `--max`
  for all; none means every option but `--rename-functions` and
  `--rename-tables`; a module's globals and table keys are left alone).
- **Run from the folder holding `main.lua`** (ticpak also finds
  `src/main.lua`), or pass the cart's path as the first argument.
- **The metadata header must be complete.** The comment block at the top of
  `main.lua` needs `title`, `author`, `desc`, `site`, `license`, `version`
  and `script`. Each must be filled in, not left as TIC-80's `new`-cart
  placeholder ("game title", "website link", ...). tic80.com shows them, and
  ticpak refuses to build without them. You can take `title` and `desc` from
  the project's README and `author` from git. **Ask the user** for `site`,
  `license` and `version` rather than inventing them.
- **Code lives in the modules, assets in `main.lua`.** `main.lua` holds the
  header, a short entry stub (`require` lines plus `BOOT`/`TIC`) and the asset
  sections. Never edit the outputs (`<name>.tic`, `dist/`), which every
  build regenerates.

Full reference: the [README](https://github.com/dtempx/ticpak#readme) and
`ticpak --help`.
