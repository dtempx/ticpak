"""ticpak - package a multi-file TIC-80 Lua project into one distributable cart.

One command, `ticpak` (ticpak.cli), installed by pyproject.toml:
  ticpak bundle / check   build and check a project's package
  ticpak check FILE...   the .tic limit and header checker (ticpak.check)
  ticpak minify FILE     the Lua 5.3 minifier on its own (ticpak.minify)

Documentation: README.md; the minifier in docs/minify.md and docs/minify-spec.md.
"""
__version__ = "0.3.5"     # keep in step with pyproject.toml's version
