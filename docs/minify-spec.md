# ticpak minifier: `max` mode — specification

Status: **implemented 2026-10-02** in [`minify.py`](minify.py), and verified on
all 8 TIC-80 ports (§6). Usage is in [`minify.md`](minify.md). This file is the
contract. Each requirement has an ID so code, tests and review comments can cite
it.

Where the implementation departs from the original draft, the requirement
says so in an **As built** note, and §7 logs the decision.

Field renaming (I1b, D13, D14, R13, drafted 2026-10-06) is a proposal: every
part of it is marked **NOT IMPLEMENTED**, and nothing in the code cites it yet.

## 1. Purpose and scope

Shrink the code of a packaged TIC-80 cart far beyond comment and whitespace
removal. The passes are: inlining constants, folding constant expressions,
removing dead code, tree shaking unreferenced definitions, and renaming
variables, and on request functions. Behaviour must stay identical, and the
result must stay debuggable: each function starts on its own line, and unless
`rename-functions` is chosen (I1c), function names survive.

**Out of scope:**
- renaming table fields (`obj.x`, `M.update`, `{k=…}`, string keys), method
  names, and the implicit `self`. **NOT IMPLEMENTED:** R13 proposes renaming
  table keys when checks on the whole program pass. Until it is built,
  table keys stay out of scope;
- any transform that re-prints an expression from an AST.

## 2. Environment (verified facts)

- **Target:** TIC-80 1.2.0 Pro. Its embedded Lua reports `_VERSION = "Lua 5.3"`,
  `math.type(1) == "integer"`, and **does not** accept Lua 5.4's
  `local x <const>` (probed headless on the Windows box, 2026-10-02). Every
  semantic rule below is Lua 5.3's.
- **Input:** the bundle that `ticpak` builds and passes to
  `minify.minify_cart()`, in this order:
  1. the cart's metadata header (`-- title:` … `-- script: lua`, plus the
     optional `saveid`, `input` and `menu`);
  2. the entry stub's top-level code;
  3. one `package.preload["<module>"] = function(...) <module source> end`
     closure per required module;
  4. the rest of the stub, including `BOOT()`/`TIC()`.

  `ticpak` sets the asset chunks aside before minifying and appends them
  afterwards. `minify_cart()` also passes any chunks it is given straight
  through.
- **Consequences of that structure:**
  - a module's top-level `local`s are locals of its preload closure;
  - module constants are mostly **globals** (wavynavy's `constants.lua` defines
    about 100);
  - modules run when they are first `require`d, not in file order.

## 3. Interface

- **I1. Mode.** Max mode is this spec's whole-program pipeline: every option
  past `comments` runs it. Two presets name option sets (revised 2026-10-06):
  - `default`: every option but `rename-functions`. It is `ticpak bundle
    --minify`, `ticpak minify` with no option flags, and `mode="default"`.
  - `max`: every option. It is `ticpak bundle --minify=max`, `ticpak minify
    --max`, and `mode="max"` (the API's default).

  A preset can be listed with options (`--minify=default,rename-functions` is
  `max`). When max mode was added, the minifier's earlier `none` and `default`
  modes kept their output byte for byte (checked against the pre-change
  baseline on wavynavy).
- **I1a. Fragment mode** (added as built). `whole_program=False` minifies one
  module on its own: no pass touches globals. `ticpak minify` uses it for any
  file but a cart that requires no modules.
  beyondcastlewolfenstein's `check.py` uses it for per-module size estimates.
- **I1b. The `fields` option. NOT IMPLEMENTED.** `--minify=fields`
  (`ticpak bundle` and `ticpak minify`) turns on key renaming (R13). Like
  every option, it implies `comments`. It is **opt-in**: a bare `--minify`
  and the `max` preset leave it out until R13 passes acceptance (§6), and
  O2 decides whether it joins them then. In fragment mode it does nothing
  (R13a). Pass name for `passes=` (I2): `fields`.
- **I1c. The rename options (added 2026-10-06).** `rename-vars` (named
  `rename` until 2026-10-06) renames variables (R8). `rename-functions`
  renames function bindings too (R8j). It is **opt-in**: `default` leaves it
  out, because error messages and tracebacks then show the short names, and
  `max` includes it. Each implies `comments`. Pass names for `passes=` (I2):
  `rename-vars` and `rename-functions`.
- **I2. Pass switches.** `passes=<list>` (API only) picks a subset of the
  max-mode passes: `fold,inline,dce,shake,rename-vars,rename-functions,sugar,
  alias,literals,merge`, defaulting to all. Layout (R3) and tidy (R11d) always run in max mode.
- **I3. Width.** `width=N` (API only) sets the line width, default 120 (R3).
- **I4. Python API.** `minify(src, mode, **opts)` and
  `minify_cart(text, mode, meta_keys, **opts)` keep their signatures.
  Max mode also returns a report (R10f) and maps (R10g) through a
  `minify.Result` object, which `minify_cart_ex()` exposes. Existing callers
  keep getting a `str`.
- **I5. Outputs written by `ticpak`** in max mode, for a folder build
  (`-o dist/`; a `.tic` or `.lua` build on its own writes just that file, no
  report or maps):
  - `dist/<game>.lua` and `dist/<game>.tic`;
  - `dist/<game>.minify.txt`, the report;
  - `dist/<game>.minify.json`, the rename map and line map.

  All of them are git-ignored build artifacts. Below, `dist/` stands for the
  folder `-o` names.

## 4. Definitions

- **D1. Program.** The code section of the bundle: everything after the
  metadata header and before the first asset chunk.
  - The **header** is the metadata lines found in the leading run of comment and
    blank lines.
  - An **asset chunk** starts at a line consisting only of `-- <NAME>` (pattern
    `^-- <[A-Z]+\d?>[ \t]*$`) when every line from there to the end of file is
    a comment or blank. Prose comments that begin `-- <MAP> region …` must not
    count; wavynavy's `a2boot.lua` has one.
- **D2. Chunk** (a unit of execution, not an asset chunk). The main chunk (the
  stub's code) or the body of one `package.preload["m"]` closure.
  - **Execution order** is the depth-first order of literal top-level
    `require "m"` / `require("m")` calls, starting at the main chunk. A module
    runs at its first `require`.
  - A non-literal `require`, or a `require` inside a function body, makes the
    order of the chunks it could load unknown (D6).
- **D3. Binding.** Either:
  - a **local**, declared by `local`, `local function`, a function parameter, a
    numeric or generic `for` variable, or a `::label::`, with Lua 5.3 scoping
    (a `local` statement's names come into scope after the statement, a
    `local function`'s name before its body, a `repeat` body's locals stay in
    scope in its `until`); or
  - a **global**, meaning a free name, which is a field of `_ENV`.

  A field name is not a binding: the name after `.` or `:`, a key in a table
  constructor, or a bracketed string key.
- **D4. Reserved name.** Never renamed, inlined or removed:
  1. the Lua 5.3 keywords;
  2. every key of `_G` in the target TIC-80 runtime (the standard library and
     the TIC-80 API), captured by enumerating `_G` in the real binary;
     regenerate it when TIC-80 is upgraded. **As built:** the list (82 names
     from 1.2.0 Pro) is embedded in `minify.py` between `# <reserved>` markers,
     not kept in a `.txt` file, so a port copies one file.
     `scripts/update_reserved.py` rewrites the block. Also reserved, though
     TIC-80 1.2 lacks them: `utf8 os io bit32 unpack loadstring module setfenv
     getfenv jit`;
  3. the callbacks `TIC BOOT SCN BDR OVR MENU`, which are absent from `_G` until
     the cart defines them;
  4. `_ENV`, `_G`, `self`, `arg`, and `...`.
- **D5. Write.** Each of these writes a binding:
  - an assignment target;
  - a `local` declaration, with or without initializer (without one, it writes
    `nil`);
  - a parameter receiving an argument;
  - a `for` control variable;
  - `function n()` and `local function n()`.
- **D6. Dynamic access.** Any of:
  - a read or write of `_G` or `_ENV`;
  - `load`, `loadstring`, `dofile`, `loadfile`;
  - `rawget`, `rawset` or `rawequal` whose first argument is `_G`/`_ENV`;
  - `setmetatable`/`getmetatable` on `_G`/`_ENV`;
  - any `debug.*` call;
  - a non-literal `require` argument.

  If the program has any of these, every pass that touches **globals** is
  disabled (inlining, folding through globals, tree shaking, global renaming)
  and the report names the first trigger by line. Passes on locals still run.

  **As built (more conservative):** *any* read of the global names `_G`,
  `_ENV`, `load`, `loadstring`, `dofile`, `loadfile`, `debug`, `rawget`,
  `rawset`, `rawequal`, `getfenv` or `setfenv`, a local named `_ENV`, or a
  non-literal `require` triggers it. The implementation doesn't inspect
  arguments.
- **D6a. Escaping `require`** (added as built). If the global `require` is read
  anywhere other than as the callee of a literal call (`pcall(require, "m")`,
  `local r = require`), every `package.preload` module is treated as live, and
  only the main chunk's execution order is trusted for D8.5.
- **D7. Constant expression.** Built only from:
  - literals (`nil`, `true`, `false`, numbers, strings) and reads of constant
    bindings (D8);
  - the binary operators `+ - * / // % ^ & | ~ << >> .. == ~= < <= > >=` and
    `and`/`or`, the unary operators `- ~ not #`, and parentheses.

  It is evaluated with exact Lua 5.3 semantics:
  - 64-bit two's-complement integers that wrap on overflow, and IEEE-754
    doubles;
  - `/` and `^` always give a float;
  - `//` and `%` round toward negative infinity, for integers and floats alike;
  - bitwise operators convert floats that hold an exact integer value;
  - comparing an integer with a float compares their exact mathematical values;
  - `..` converts numbers as 5.3's `tostring` does: integers with `%d`, floats
    with `%.14g`, plus a trailing `.0` when that result looks like an integer
    (`2.0` gives `"2.0"`, `1e15` gives `"1e+15"`).

  These cases are **not folded** and stay as written:
  - integer `//` or `%` by zero (a runtime error);
  - a float result of ±inf or NaN (there's no literal for it);
  - a bitwise operation on a float without an exact integer value;
  - arithmetic with a string operand (string coercion);
  - `#` on anything except a string literal;
  - a result equal to `math.mininteger` (its negation can't be written as a
    literal).

  `and`/`or` fold whenever the left operand is constant, even if the right one
  isn't: falsy `L and e` gives `L`, truthy `L and e` gives `e`, truthy `L or e`
  gives `L`, falsy `L or e` gives `e`.
- **D8. Constant binding.** A binding B for which all of these hold:
  1. B has exactly one write in the program, and no dynamic access (D6) is
     present for globals.
  2. **Local:** the write is the initializer in B's own `local` declaration.
     **Global:** the write is a plain statement `NAME = e` (or one position of
     `a, b = e1, e2`) at the **top level of a chunk**, not inside any function,
     loop, conditional or `do` block.
  3. The value folds (D7) to `nil`, a boolean, a number or a string. A table
     constructor, a function, a call, `...`, or a read of a non-constant binding
     disqualifies B. Tables are excluded because they have identity and
     mutable contents.
  4. In a multiple assignment each position qualifies on its own. A position
     whose value comes from the last expression's extra results (a call or
     `...`) disqualifies.
  5. **No read before the write:** none of B's reads can run before the write.
     - For a local, scoping guarantees this.
     - For a global written in chunk W, a read is **safe** when it is inside a
       function body (by assumption, functions are called after loading
       finishes), or textually after the write at W's top level, or at the top
       level of a chunk that runs after W completes in execution order (D2).
     - Any other read disqualifies B.
  6. **UPPER_CASE is a reporting hint only.** Qualification ignores the name's
     case. Any binding matching `^[A-Z][A-Z0-9_]*$` that does not qualify is
     listed in the report with the clause that failed, because it is either a
     mistaken constant or a bug.
- **D9. Always-falsy binding.** Either:
  - a binding with no dynamic access whose every write is a constant `false` or
    `nil`; or
  - a global that is not reserved and has zero writes (it is always `nil`).

  Its reads have known truthiness for R6 but are not inlined. Zero-write
  globals are listed in the report, since they are often typos.
- **D10. Pure expression.** An expression with no side effects: a literal, a
  read of a binding, a constant expression, a function expression, or a table
  constructor whose keys and values are all pure. A call, an indexing (which
  could hit `__index`), or an arithmetic or concat operator on a non-constant
  operand (which could hit a metamethod) is **not** pure.
- **D11. Function binding.** A binding with at least one write whose value is a
  function definition: a `function n()` statement, a `local function n()`, or
  a function expression as the assigned value (`local f = function…`,
  `g = function…`). Function bindings are renamed only by the
  `rename-functions` option (I1c, R8j). Without it they keep their names, so
  names in tracebacks still read as the source wrote them. Either way they can
  be removed by tree shaking (R7).
- **D12. Function-start statement.** A `function` statement, a `local function`
  statement, or an assignment or `local` statement whose first right-hand-side
  expression is a function expression. The `package.preload["m"] =
  function(...)` lines are function-start statements.
- **D13. Key name. NOT IMPLEMENTED.** An identifier written in the source as
  a string table key, in a **key position**:
  - the name after `.` in an index (`t.k`) or after `:` in a method call
    (`t:k()`);
  - each name after the first in a `function` statement's path, and its
    method name (`function a.k:m()`: `k` and `m`);
  - a named field in a table constructor (`{k=…}`);
  - a string literal whose value is an identifier but not a keyword, written
    as an index key (`t["k"]`) or a bracketed constructor key
    (`{["k"]=…}`). Such a literal is a **key literal**.

  Every other string literal is a **value literal**, including one whose
  value is an identifier (`state = "dead"`, `t[k]` after `local k = "dead"`).
  `rawget` and `rawset` would be key positions too, but any read of them
  triggers D6 as built, which disables R13.
- **D14. Key shape. NOT IMPLEMENTED.** A conservative description of the
  identifier strings an expression can evaluate to **at runtime without being
  written as a literal** (a synthesized string). It is a union of these
  alternatives:
  - **none:** the expression cannot produce an identifier string:
    - a number literal, `nil`, `true` or `false`, a table constructor, a
      function expression;
    - an arithmetic, bitwise or comparison operator, `not`, or `#`;
    - a concatenation with at least one literal piece that holds a character
      that can't occur in an identifier (`a..","..b`, `"x="..n`);
    - a value literal (R13c keeps its name, so it is never renamed);
    - a key value (R13f), which is always a key name the program has
      already renamed consistently.
  - **a finite set** of strings:
    - `type(…)`: `nil number string boolean table function thread
      userdata`;
    - `math.type(…)`: `integer float`;
    - `coroutine.status(…)`: `suspended running normal dead`;
    - `s:sub(i, i)` or `string.sub(s, i, i)` where `s` is a string literal:
      each character of `s`.
  - **contains P:** a concatenation one of whose literal pieces is P, made
    only of identifier characters: every result contains P
    (`l.."_s"..n`).
  - **any:** every other synthesized string: other `string` library calls
    and string methods (`format`, `rep`, `char`, `upper`, `gsub`, `sub` on a
    non-literal, …), `tostring`, a concatenation with no literal piece, and
    any other library or TIC-80 API call that returns a string.

  It is computed for the whole program at once, ignoring statement order,
  and repeated until nothing changes. A function **escapes** when its value
  is stored anywhere but its own binding: under a key, in another variable,
  as an argument or as a return value. An implementation may swap any rule
  below for a more precise one, provided the result still covers every
  string the expression could produce:
  - **A local or global:** the union of the shapes of every value written to
    it.
  - **A parameter:** the union of the argument in the same position (counting
    `self` in a method call or definition) of every call that may reach the
    function:
    - calls whose callee resolves to the function's binding;
    - if the function escapes, every call whose callee isn't resolved.

    A parameter past the last argument is `nil`. `...` is the union over the
    remaining positions. A function given directly as a `gsub` replacement
    has parameters of shape **any**. A `table.sort` comparator's parameters
    take the shape of a key read.
  - **A call:**
    - to a function the program defines, resolved: the union of its `return`
      expressions;
    - with a callee that isn't resolved: the union of the `return`
      expressions of every escaping function;
    - to a library function: its own shape (above). For the ones that hand
      back what the program gave them (`select`, `table.unpack`,
      `table.remove`, `pcall`, `xpcall`, `coroutine.*`), the union of their
      arguments and of the `return` expressions of every function.
  - **A generic `for` variable:**
    - over `pairs` or `next`, the first is a key value and the second a key
      read;
    - over `ipairs`, the first is **none** and the second a key read;
    - over `string.gmatch`/`:gmatch`, **any**;
    - over any other iterator, as for a call whose callee isn't resolved.
  - **A key read:**
    - for `t.k` or a key literal: the union of the shapes of every value
      stored under that key name, in an assignment or a constructor;
    - for `t[e]` with any other key: the union over every key;
    - either way, plus the `return` expressions of every function stored
      under `__index`.

  If the program defines an arithmetic or `__concat` metamethod (D13 key
  name `__add` … `__concat` anywhere), then operators can return anything.
  Arithmetic and `..` are then **any**.

## 5. Requirements

**R1. Pass-through.** The metadata header and every asset chunk come out byte
for byte. The output must not contain a code line matching `^-- <[A-Z]` (TIC-80
would read it as a chunk marker). This can only happen through a multi-line long
string, and if it does, the run aborts with the line.

**R2. Comments.** All comments in the program are removed.

**R3. Layout (max mode).**
- **a.** A newline comes before the first token of every function-start
  statement (D12), at any nesting depth, unless that token is already first on
  its line.
- **b.** Otherwise tokens are packed greedily. A token goes on the current line
  when the line's length, plus one separating space if `_needs_space` says one
  is needed, plus the token's length fits within `width` (default 120);
  otherwise a newline replaces the separator and the token starts the next line.
  Length counts characters and excludes the newline.
- **c.** Lines break **only between tokens**, never inside one. In Lua 5.3 a
  newline is a valid separator between any two tokens: the `f\n(g)` ambiguity
  that was an error in 5.1 parses identically since 5.2.
- **d.** A token longer than the width (a long string) sits on a line of its own
  and is the only allowed overflow.
- **e.** No indentation and no trailing whitespace. The code ends with a single
  `\n` before the chunks, as the current modes do.
- **f.** For example, with `width=40`:

  ```lua
  function update(dt) local a=x+1 if a>3
  then reset() end end
  function draw() cls(0) spr(1,a,b) end
  ```

**R4. Inlining constants.** Every read of a constant binding (D8) is replaced by
its folded value, and the binding's write is removed. A `local` statement left
with no names is removed.
- **a.** `nil`, booleans and numbers are always inlined. A global read becomes
  a constant load, which is faster.

  **As built:** every kind of value goes through the size check in R4b, not
  only strings. A long float such as `1/60` (20 characters as a literal) read
  30 times would otherwise add ~500 characters. In practice nearly all integer
  and boolean constants still inline. Folding and dead-code removal use a
  constant's value whether or not it is inlined, so `if DEBUG then` disappears
  either way. A never-written global (D9) has no declaration to save, so it is
  inlined only when `nil` is shorter than its renamed name, which is never.
- **b.** A string is inlined only when the result is no larger:
  `len(literal) × reads ≤ len(declaration) + reads × len(new name)`. A string
  constant that fails this stays as an ordinary binding, renamed by R8.
  `inline_all=True` (API only) overrides the check. **As built:** the new name's length is
  estimated as 2 when renaming (R8) runs, and as the name's own length when it
  doesn't (the `constants` option without `rename-vars`, 2026-10-03); the
  declaration as `N + 1 + len(literal) + 1` with the same N.
- **R4 removal without tree shaking (2026-10-03).** "The binding's write is
  removed" is done by R7 when it runs. When R4 runs without R7 (the
  `constants` option without `extra`), a restricted removal does it instead:
  the declaration or assignment of every binding that is a constant (D8) and
  has no reads left is deleted, with the R7f rules for pure values and
  multiple-value expressions. Nothing else is removed: functions, modules,
  unused non-constant bindings and parameters stay.
- **c.** Splicing: the inserted text is wrapped in parentheses when the literal
  is negative (`a-K` with `K = -1` must not become `a--1`, a comment), or when
  it lands in prefix position (`K.f`, `K()`, `K:m()`, `K[i]`, or a string
  call/index). Otherwise it goes in bare. The re-lex check (R10b) runs after
  every splice.

  **As built:** a negative literal is parenthesised only as the left operand
  of `^` (`(-1)^2`) or in prefix position. Everywhere else a unary minus parses
  the same bare, and the layout's space rule turns `a-(-1)` into `a- -1`,
  never `a--1`. In the tree, a negative value is a unary-minus node over a
  positive literal, never a single token.

**R5. Folding.** Each maximal constant expression (D7) is replaced by its value,
**but only when the literal is not longer than the source text it replaces**.
Lua 5.3's compiler already folds numeric constants, so this pass is for size
only; it never makes code slower.
- **a.** An integer is written in the shorter of decimal and `0x` hex; a
  negative one as `-` plus the literal.
- **b.** A float is written in the shortest form that reads back to the same
  double, and the form must contain `.` or an exponent so it stays a float
  (`4.0` may become `4.`, never `4`).
- **c.** A string is written with whichever of `"` and `'` needs fewer escapes,
  using only standard Lua escapes, and must reproduce the same bytes.
- **d.** Examples: `local a=60*60` becomes `local a=3600`, and
  `f('the answer is: '..1+3*2)` becomes `f('the answer is: 7')` (`+` binds more
  tightly than `..`), which R11a then turns into `f'the answer is: 7'`.
  `1/60` stays as it is, because `0.016666666666666666` is longer.

**R6. Dead-code removal.** "Truthy" and "falsy" mean the condition is a constant
expression, or a read of an always-falsy binding (D9).
- **a.** In an `if`/`elseif`/`else` chain, arms are checked in order:
  - an arm whose condition is falsy is dropped;
  - the first arm whose condition is truthy becomes an unconditional `else`, and
    every arm after it is dropped;
  - if no arms remain, the statement is removed;
  - if only an unconditional arm remains, the statement becomes its body,
    wrapped in `do … end` when the body declares a local or a label at its top
    level (to keep scoping), and emitted bare otherwise.
- **b.** `while <falsy> do … end` is removed. A numeric `for` whose constant
  bounds and step never iterate (`for i=1,0`) is removed.
- **c.** Statements after `break`, `goto` or `return` in the same block are
  removed, unless the removed region contains a `::label::`. In that case the
  run stops at the label.
- **d.** A removed region takes its references with it. R7 then removes
  definitions that only dead code used (R9 iteration).

**R7. Tree shaking** (reachability, not reference counting).
- **a. Live code:**
  - every top-level statement of the main chunk;
  - the top level of every chunk that live code `require`s;
  - the body of every live function (a function expression is live when the
    binding it is assigned to is live, or when it appears anywhere else in live
    code, such as an argument or a table field).
- **b. Live binding:** read by live code, or reserved (D4, which includes the
  callbacks). Recursive and mutually recursive functions that no live code
  reaches are dead.
- **c.** A write to a dead binding is removed when its value is pure (D10). A
  value that is a call stays behind as a call statement (`local x = f()` becomes
  `f()`). Anything else impure stays as written. In a multiple assignment the
  right-hand side keeps its expressions and order, and only targets that are
  dead and whose value position is pure are dropped.
- **d.** A `package.preload["m"]` entry that no live code `require`s is removed
  whole.
- **e.** Trailing parameters that are never read are dropped from a function
  definition, unless the function uses `...` (dropping a named parameter would
  shift the varargs).
- **f.** Table fields are never removed. A function stored as `M.fn` is live if
  `M` is live.

**R8. Renaming** (the `rename-vars` option: non-function bindings; R8j adds
function bindings).
- **a. What is renamed:** locals (including parameters, `for` variables and
  labels) and non-reserved globals. Function bindings (D11, unless R8j),
  reserved names (D4), fields and the implicit `self` are not renamed. Globals
  are renamed only when no dynamic access (D6) is present.
- **b. Name pool,** in order: all 1-character identifiers (`a`–`z`, `A`–`Z`,
  `_`), then 2-character ones, then 3-character ones, and so on. The pool
  excludes:
  - keywords (the 2-character ones are `do`, `if`, `in`, `or`);
  - reserved names;
  - function-binding names in use, unless R8j renames them;
  - anything matching `^_[A-Z]`.
- **c. Globals:** sorted by reference count (most first, ties by first
  occurrence) and given pool names in that order. A global's new name must not
  equal the name of any local visible at any of its references.
- **d. Locals:** handled per function, outermost scope first, in the same
  order. Bindings whose lifetimes don't overlap reuse names. A local's new name
  must not capture or shadow any other binding referenced within the local's
  scope.
- **e. Labels:** renamed per function, from a separate pool (labels have their
  own namespace).
- **f. Determinism:** the same input and options always give the same output.
- **g. NOMINIFY for variables (added 2026-10-03, revised 2026-10-05).** A
  NOMINIFY directive (R8i a) attached to a `local` statement, an assignment or
  a `for` loop keeps each variable that statement declares or assigns: a name
  in a `local` list, a plain-name assignment target (`x = …`, local or
  global; `t.x = …` assigns no variable), or a loop variable. One directive
  keeps the binding at every occurrence, reads included. A binding marked at
  any one of its declaration/assignment statements is kept. A statement that
  only reads a variable marks nothing.
  - A kept binding is **pinned** like a name used by protected code (R8h g):
    never renamed, never a constant (R4) or always-falsy (D9), never
    aliased (R11), always live for tree shaking (R7). So a kept constant is
    not inlined and a kept unused binding is not removed.
  - The directive's comment is removed like any other comment.
  - A kept name joins the excluded set of the name pool (b), so no renamed
    binding can take it.
  - The report lists each kept name with the line of the statement that
    declares or assigns it (R10f).
  - **As built:** `directives()` records each kept variable as (source line,
    name) of its declaring/assigning name token; `Info` pins every binding
    with a declaration or write at such a pair.
- **As built:** globals and locals share one allocation, ordered by occurrence
  count. A local's lifetime is the span from its first to its last occurrence
  (declaration, reads and writes). Two locals may share a name when their spans
  don't overlap; that test is sound because Lua resolves names by position. A
  local and a global may share a name only when no occurrence of the global
  falls inside the local's scope. The pool also excludes every name that stays
  unrenamed (function bindings without R8j, reserved names, and in fragment
  mode all globals). Bytecode identity under local renaming is proven on every port
  (R10c).

**R8h. NOMINIFY for functions and modules (added 2026-10-04, revised
2026-10-05).** A NOMINIFY directive (R8i a) can also protect a whole function
or module from every option: no comment removal, renaming, inlining, folding,
layout or anything else inside it. It comes out byte for byte.
- **a. Function level.** A directive protects:
  - the function of a `function` statement or `local function` it is
    attached to;
  - each function value (`function … end` written directly) among the
    expressions of a `local` statement or assignment it is attached to;
  - each function whose `function` keyword is on the line the directive
    applies to (R8i b): the line after a block, or the line of a comment
    after code.
  A directive inside a function's body is attached to the statement after
  it, never to the function.
- **b. Module level.** A module is protected when a NOMINIFY comment is in
  its top comment block: the first comment lines of the module, after any
  leading blank lines. In a bundle, a module is the body of `package.preload["m"]
  = function(...) … end`, and its top block is the comment lines that follow
  that declaration. A directive attached to the preload assignment itself
  (a block above it) does not protect the module.
- **c. Comment blocks.** As R8i a. A blank line ends a block, so a NOMINIFY
  block, then a blank line, then a function does not protect the function.
  In a module's top block it is a module-level directive; anywhere else it
  keeps its own comment (R8i).
- **d. Module level wins.** When a directive could be read as both — a
  module's top block running straight into a function declaration — the
  module is protected. More generally, a protected region inside another
  protected region is covered by the outer one.
- **e. Whole cart.** A NOMINIFY in a cart's top comment block (its metadata
  header block) leaves the whole cart unminified. So does one in the top
  comment block of a plain source file given to `minify()`. The header tags'
  own values (a `title` or `desc` that says "nominify") don't count.
- **f. What is protected exactly.** The function's parameter list and body,
  from its `(` to its `end`, are the protected text. The `function` keyword,
  any `local` and the function's name are emitted as usual, but the name is
  kept: a directive attached to a `function name` or `local function name`
  statement keeps `name` as R8g keeps a variable (pinned), so R8j leaves it
  alone (added 2026-10-06; `local name = function` was already kept by R8g).
  A method or a function in a table (`function M.f`) keeps its name anyway.
  The comment carrying the directive is removed like any other comment unless
  it lies inside the protected text.
- **g. Interface.** The protected text is opaque to every pass, so every name
  it uses (except fields after `.`/`:`) **pins** the binding of that name
  visible at the function's declaration. A pinned binding is:
  - never renamed (R8);
  - never a constant (R4), never always-falsy (D9);
  - never aliased (R11);
  - always live for tree shaking (R7).
  This is conservative: the protected code may read or write any of them.
  A protected function's own binding is never removed as unused.
- **h. Layout.** The protected text keeps its line breaks and indentation, so
  in `whitespace` mode it spans several output lines. The line map gives each
  of its lines its own source line (R10g).
- **i. `comments` alone** skips protected text when it strips comments.
- **As built:** `directives()` lexes and parses the source once, recording
  every statement's token span and every function's `function`, `(` and
  `end` tokens, and resolves each directive against them. `protect()`
  replaces each protected region's tokens with one `raw` token. The parser
  turns that token into a `Func` that carries the text, and the emitter
  writes it back unchanged. The final re-lex proof expands raw tokens before
  comparing (R10b). The report lists each protected region's start line.

**R8i. NOMINIFY directives and kept comments (added 2026-10-05).**
- **a. Directives.** A comment containing the word `NOMINIFY` — any case, a
  whole word (`\bnominify\b`: not `nominifying`, not `NOMINIFY_X`), never
  inside a string literal — makes a directive in one of two forms:
  - a **comment block**: a run of one or more comments, each starting on a
    line with no code before it. A blank line or a line of code ends it. The
    block is a directive if any of its comments holds the word;
  - a **trailing comment**: one comment that follows code on its line.
- **b. Attachment.** A block applies to the line right after its last line
  (or to its last line, when code follows the block's last comment there),
  and is attached to every statement, at any depth, that starts on that
  line. A trailing comment applies to its own line and is attached to every
  statement that starts or ends on it. A blank line or the end of the source
  after a block means it applies to nothing. Then R8g and R8h a say what
  each attached statement and function keeps.
- **c. Kept comments.** A directive that keeps nothing by R8g, R8h a or
  R8h b (a block before a blank line, a call, an `if`, a `return` or the end
  of a block; a trailing comment after such code) keeps its own comment: the
  source text from the first comment's `--` to the end of the last comment,
  byte for byte. A kept comment inside protected text (R8h) is part of it.
- **d. Placement.** A kept comment stays where it was when that is between
  two statements or table fields (or at the start or end of a block or
  table). Anywhere else, inside an expression, it moves to just after the
  innermost statement around it, and is treated as a trailing comment.
- **e. Layout.** A comment that had its own line(s) starts a new output
  line; a trailing one is appended to the current line, after a space. Code
  after a kept comment always starts a new line. Kept comments don't count
  toward the 120-column width (R3). The line map gives each of a comment's
  lines its own source line, and the line after it a later one (R10g).
- **f. Other passes.** A kept comment goes with the code around it: one in a
  block, function or module that a pass removes is removed too. It is never
  removed as unreachable (R6). Two `local` statements with a kept comment
  between them are not adjacent for merging (R11).
- **g. Asset tags.** A kept comment with a line starting `-- <` and a letter
  (the first line after any indentation) is an error naming that line:
  TIC-80 would read it as the start of the asset sections (D1).
- **h. Carts.** `split_cart` ends a cart's leading comment run at a
  NOMINIFY block after the header block, provided no metadata tag follows
  it, so that block becomes code and is kept. The code's own first block is
  then not a whole-module directive (R8h e covers the cart's top block).
  When the code starts with a kept comment, a blank line separates it from
  the header block.
- **As built:** `directives()` gives each kept comment's span and the index
  of the token it goes before; `protect()` inserts it there as one
  `("comment", CommentText)` token. The parser makes it a `Comment`
  statement, or a `"comment"` table field. The emitter writes it back. The
  final re-lex proof skips comment tokens (R10b).

**R8j. Function renaming (the `rename-functions` option, added 2026-10-06).**
- **a. What is renamed:** function bindings (D11) that R8a would rename if
  they were variables: locals, and non-reserved globals when no dynamic
  access (D6) is present, in whole-program mode only. Still never renamed:
  functions stored in tables and methods (`function M.f`, `obj:m`: fields),
  the TIC-80 callbacks and every other reserved name (D4), and a binding a
  NOMINIFY directive pins (R8g, R8h f, R8h g).
- **b. One allocation.** Variables and functions are renamed by one pass,
  under R8b–d: one name pool, one order by occurrence count, the same
  capture and shadowing rules. A function gets a short name only when it is
  used more than the variables competing for that name.
- **c. Alone.** With `rename-functions` on and `rename-vars` off, only
  function bindings are renamed, and labels (R8e) keep their names.
- **d. Layout.** R3a still starts each function on its own line, so the
  line map (R10g) stays exact, and the maps record each renamed function
  like a variable (kind `local` or `global`).
- **e. Savings.** The report's bytes saved by option (R10f) splits the
  rename pass between the two options: `rename-functions` gets the bytes its
  renaming took off function names, counted as it renames them, and
  `rename-vars` the rest.
- **f. Measured (2026-10-06):** on the 8 ports it took 1.9–12.1% off the
  `default` output, 5.8% overall (361,456 → 340,534 characters). The least
  where functions live in module tables (fields), the most where a game is
  written as many global functions with long names. zaxxon reads `load`, so
  D6 keeps its global functions' names. `difftest` (R10d): 8/8 ports
  identical over 3,600 frames.

**R9. Pass order.** `fold → inline → dce → shake`, repeated until nothing
changes (and at most 10 rounds; reaching the cap is an error), then renaming
(R8 and R8j, one pass), then the optional passes (R11), then layout (R3). Each pass is a set of token
edits on the original token stream, planned from the parse.

**As built:** the passes edit the lossless tree described in R10b. Each pass
works on a fresh parse and re-emits it. The fixpoint loop allows 20 rounds,
and 2–3 is typical. The small passes (sugar, alias, literals, merge, tidy) run
*before* renaming, so the locals they create get short names too.

**NOT IMPLEMENTED:** key renaming (R13) would run between the fixpoint loop
and the small passes (R13l).

**R10. Safety and verification.**
- **a. Refuse rather than guess.** A parse error aborts with its line. A
  construct the analysis doesn't model disables the affected passes, and the
  report says which ones and why. A partly correct output is never emitted.
- **b. Self-check, every run:** the output parses with the minifier's own parser.
  Outside the planned edits, the token streams match: every token the minifier did not
  edit by design, re-lexed, is identical in order, extending the current
  `lex(out) == lex(in)` safety net.

  **As built**, as an equivalent but simpler guarantee:
  1. Every parse, the first and each one after a pass, is proven
     **lossless**: the tree must re-emit exactly the token stream it was built
     from, or the run aborts naming the token.
  2. Passes change the tree only by deleting statements, replacing a whole
     subexpression with a literal or with a local holding the same value
     (R11b, R11e), or renaming, so a token no pass touched comes out
     unchanged.
  3. The final text must lex back to exactly the emitted tokens, and parse.
  4. No output line may read as an asset-chunk marker.
- **c. Bytecode proof (test suite):** with only comment removal, layout and
  local renaming enabled, the stripped bytecode (`string.dump(load(src), true)`
  under a real Lua 5.3, via `lupa.lua53`) of input and output is identical.
  `lupa` is a test dependency only.

  **As built:** Lua 5.3's stripped dump still records every function's
  `linedefined` and `lastlinedefined`, so the proof keeps each token on its
  source line and changes only the names (`run.py bytecode`). Result
  (2026-10-02): identical on all 8 ports.
- **d. Behaviour (test suite and packaging):** the minified `.tic` boots
  headless from a directory holding only the bundle (`ticpak` already checks
  this), and where the port has a probe or test suite, it passes against the
  minified bundle.

  **As built:** the existing per-port probes drive the development cart, not
  the bundle, so behaviour is checked by `tests/minify/difftest.py`
  instead. It runs the original and minified bundles in lockstep in Lua 5.3
  under a deterministic TIC-80 API stub, and every output call must match frame
  for frame. It is backed by `run.py fixtures` (targeted programs) and
  `run.py fold` (the evaluator against real Lua). See `minify.md` "Testing".
- **e. Isolation:** each pass can be switched off (I2), so a regression can be
  bisected to one pass.
- **f. Report** (`dist/<game>.minify.txt`):
  - characters before and after, overall and per pass;
  - the UTF-8 bytes each option saved, and what the minified code is made of
    (strings, field names, names never renamed, ...) with the biggest names
    that stayed. These are measured only, by source line, so `ticpak` can
    print them per file (`minify.md` "What each option saved"). No pass reads
    them;
  - the constants inlined (name, value, number of reads);
  - the strings kept by the size check;
  - the expressions folded;
  - the branches and loops removed (with source lines);
  - the bindings and preload entries removed;
  - the UPPER_CASE names that failed D8, with the clause;
  - the zero-write globals;
  - any dynamic-access trigger and the passes it disabled;
  - the names kept by a NOMINIFY directive (R8g), with the line of their
    declaring or assigning statement;
  - the functions and modules kept verbatim by a NOMINIFY directive (R8h),
    with the line each starts on;
  - the comments kept by a NOMINIFY directive (R8i), with the line each
    starts on.
- **g. Maps** (`dist/<game>.minify.json`): for each renamed binding, the new
  name, original name, kind (local, global or label), enclosing function and
  source line; and for each output line, the source module and line of its
  first token. Together they translate a TIC-80 runtime error back to source.
  **As built:** each rename records its new name, old name, kind and source
  `file:line` (from `ticpak`'s origin map), but not its enclosing function.
  The source line is enough to find it.
- **h. Runtime:** standard library only for packaging, and under 5 s on
  wavynavy's ~150K-character bundle.

**R11. Optional size passes**, which are in max mode by default and
individually switchable:
- **a. `sugar`:** `f("s")` becomes `f"s"`, and `f({…})` becomes `f{…}`, when
  the call's only argument is a string literal or a table constructor.
- **b. `alias`:** a reserved global with one or more field lookups (`math.floor`,
  `spr`, …) read N times is aliased by a `local` at the top of the chunk that
  uses it, when that saves size: `N × (len(original) − len(alias)) >
  len(declaration)`. It only applies when the program never writes that global
  or field, and never pushes a function past Lua's 200-local limit. It is also
  faster.

  **As built:** one `local` statement at the top of the **main chunk** covers
  every module, because each `package.preload` body is a closure nested in the
  main chunk. A name is aliased only if it is in TIC-80's own `_G` list (D4.2),
  and `package`, `require`, `_G`, `_ENV` and the callbacks are never aliased.
  The pass is reverted if any function would need more than 250 upvalues (Lua's
  limit is 255). The main chunk's top-level locals plus aliases are capped at
  180. On wavynavy it aliases 20 names (`ipairs` 36 uses, `spr` 30,
  `math.floor` 29, …).
- **c. `merge`:** consecutive `local` statements merge
  (`local a=1 local b=2` becomes `local a,b=1,2`), but only when no later
  initializer reads a name an earlier statement declared, and no initializer is
  a multi-value expression in a non-final position.
- **d. Tidy** (always on): drop `;` separators, empty `else` arms, and empty
  `do end` blocks with no locals.
- **e. `literals`** (added 2026-10-06): a string or number literal written N
  ≥ 2 times is replaced by one `local` at the top of the main chunk, when
  that saves size: `Σ (len(spelling) − len(name)) > len(name) + len(literal)
  + 2`, a use written `f"s"` costing 2 more as it goes back to `f(a)`. Uses
  are grouped by value (D7's subtype-aware values: `0x10` and `16` are one
  value, `16` and `16.0` are two), and the declaration takes the shortest
  spelling. Never shared: the argument of a literal `require "m"` and the
  key of `package.preload[…]`/`package.loaded[…]`, which R7 and the module
  timeline read. Fragments are shared too: a local at the top of a module
  changes nothing outside it.

  **As built:** runs after `alias`, sharing the cap of 180 top-level locals
  (alias first). Names are costed at 2 characters with `rename-vars`, else 5
  (`__l12`). If any function would need more than 250 upvalues, the pass is
  undone and retried sharing half as many (the best first), and the report
  says so. A shared number in arithmetic becomes an upvalue read instead of
  a constant operand: a small runtime cost, accepted for size. Result on the
  8 ports: 363,290 → 359,484 characters (−1.0%; beyondcastlewolfenstein
  −2.3%, dinoeggs −2.0%), 8/8 identical in `difftest`.
- **Excluded:** removing "redundant" parentheses. It saves little and is
  exactly how npm luamin miscompiled wavynavy.

**R12. Integration.**
- The minifier is `ticpak/minify.py`, also run on its own as
  `ticpak minify`.
- `ticpak` reaches it only through `minify.minify_cart()` /
  `minify_cart_ex()`, and `minify_ex()` for a module on its own (which
  `ticpak minify` also uses for a file that is not a cart).
- The reserved-name list (D4.2) is generated by a small headless TIC-80 probe
  script, `scripts/update_reserved.py`.

**R13. Key renaming (the `fields` option). NOT IMPLEMENTED.** Key names (D13)
are shortened. Renaming goes **by spelling, not by table**: every occurrence
of a key name, on whatever table, becomes the same new name. The pass never
asks which tables the program defines. Consistent renaming preserves
everything the program does with its own keys: keys copied between tables,
`__index` chains, keys read back from `pairs` and used as keys again, and
module tables passed around all still match. Two kinds of thing can still go
wrong: a key that the platform reads or provides (b), and a string that is
not written as a key literal but is used as a key or compared with one
(c–g). Each of those is either kept by name or disables the pass. The pass
is sound only when its checks pass. It is never a guess (R10a).

- **a. Scope. NOT IMPLEMENTED.** Whole-program mode only. In fragment mode
  (I1a) a module's keys are its interface to code the minifier can't see, so
  the pass does nothing.
- **b. Platform keys, kept. NOT IMPLEMENTED.** Never renamed:
  - every key of every table reachable from `_G` in the target TIC-80
    (`math.floor`, `string.sub`, `table.insert`, `package.preload`, …).
    `scripts/update_reserved.py` lists these from the binary, as D4.2 does
    for globals, into a second generated block in `minify.py`;
  - every name starting with `__` (metamethods, `__name`, `__mode`,
    `__metatable`, and the program's own `__` names);
  - `n`, which `table.pack` writes.

  The names of globals are not kept. Any `_G`/`_ENV` access triggers D6,
  which disables the pass (h), so a key never names a global. The pass relies
  on TIC-80 1.2's API neither taking nor returning tables with string keys.
  The probe must confirm this when the pass is built and whenever TIC-80 is
  upgraded.
- **c. Names in literals, kept. NOT IMPLEMENTED.** A key name equal to the
  value of any value literal (D13) is never renamed. This covers keys reached
  through data (`local k = "speed"; t[k]`), and comparisons with key values
  (`if k == "speed"`). Key literals are renamed with their key: the literal's
  text changes (`t["speed"]` becomes `t["q"]`). Rewriting it to `t.q` or
  `{q=…}` would save more and is a later step.
- **d. Synthesized keys. NOT IMPLEMENTED.** For every index key expression
  (`t[e]`, `{[e]=…}`), take its key shape (D14):
  - **none:** nothing to do;
  - **a finite set:** each string in the set is kept as a name (never
    renamed) and excluded from the pool (j);
  - **contains P:** every key name containing P is kept, and no new name
    may contain P;
  - **any:** the pass is disabled (h).
- **e. `gsub` with a table. NOT IMPLEMENTED.** `string.gsub` or `:gsub`
  looks up each captured string as a key of a replacement table. The pass is
  disabled by a `gsub` call whose third argument (second for `:gsub`) might
  be a table, or a function that isn't written in place. That argument is
  allowed when it is:
  - a string literal, a concatenation, or a call to `tostring` or a `string`
    function;
  - a function expression, whose parameters then have shape **any** (D14).
- **f. Key values stay keys. NOT IMPLEMENTED.** These are **key values**,
  strings the runtime hands back that are key names:
  - the first variable of a generic `for` over `pairs(…)` or `next`;
  - the first result of a `next(…)` call;
  - the second parameter of a function stored under `__index` or
    `__newindex`, whether in a constructor (`{__index=function(t,k) …}`)
    or an assignment (`mt.__index = f`, with `f` resolved to a function
    binding; an unresolved one disables the pass).

  A variable holding a key value may only be:
  - used as an index key;
  - an operand of `==` or `~=`;
  - copied into a local that obeys the same rules.

  Any other use disables the pass, because the renamed key could become
  visible. Examples: `print(k)`, `k..":"`, `k:sub(1,1)`, passing `k` to a
  function, storing `k` as a value.
- **g. Protected code. NOT IMPLEMENTED.** Text kept verbatim by NOMINIFY
  (R8h) is opaque. Every identifier in it, and every identifier-valued string
  literal in it, is kept as a key name.
- **h. Disabling. NOT IMPLEMENTED.** The whole pass is off, and the report
  names the first trigger with its `file:line`, when:
  - dynamic access (D6) is present;
  - a key shape is **any** (d);
  - a `gsub` replacement could be a table (e);
  - a key value is used as anything but a key (f).

  The other passes run as usual. Dropping only the affected names is not
  possible for these triggers, because the pass can't tell which key names
  they reach.
- **i. Function-valued keys. NOT IMPLEMENTED.** A key name is
  function-valued when any of its occurrences stores a function definition:
  - the last path name or method name of a `function` statement;
  - a constructor field `k=function…`;
  - an assignment `t.k = function…` or `t["k"] = function…`.

  As D11 does for function bindings, these keep their names, so tracebacks
  (`in method 'update'`, `in function 'M.update'`) still read as the source
  wrote them. Open as O1.
- **j. Name pool. NOT IMPLEMENTED.** Keys have their own namespace,
  separate from variables (R8). The new names follow R8b's order (1
  character, then 2, …) and exclude:
  - keywords;
  - every key name that stays (b, c, d, g, i, k);
  - every identifier-valued string literal in the program;
  - every string in a finite key shape, and every name containing a P from
    a contains-P key shape (d);
  - anything starting with `_`.

  Key names are sorted by occurrence count (most first, ties by first
  occurrence) and given pool names in that order. A name is renamed only
  when its new name is shorter.
- **k. NOMINIFY for keys. NOT IMPLEMENTED.** A NOMINIFY comment with
  `keys:` followed by names (separated by spaces or commas) keeps those key
  names everywhere in the program. It keeps nothing else, and is removed like
  any other comment. A NOMINIFY attached to `t.x = …` still keeps nothing by
  R8g, so R8i c keeps its comment, as today. Open as O3.
- **l. Pass order. NOT IMPLEMENTED.** After the R9 fixpoint, so dead code
  and the literals it held are gone, and before `sugar`, `alias`, `literals`
  and `merge` (R11). `literals` would otherwise move key literals into
  locals and hide them. `alias` only touches library keys, which (b) keeps.
- **m. Report and maps. NOT IMPLEMENTED.** The report (R10f) gains:
  - the number of keys renamed and the characters saved;
  - the keys that stayed, by reason (b, c, d, g, i, k);
  - the trigger that disabled the pass, if any.

  The maps (R10g) record each key rename as kind `field`, with the new name,
  the old name and the `file:line` of its first occurrence. A runtime error
  such as `attempt to index a nil value (field 'q')` can then be translated
  back to the source.
- **n. Visible differences. NOT IMPLEMENTED.** These remain when every check
  passes, and are accepted:
  - error messages and tracebacks show the new key names (decoded by m);
  - `pairs` order may change, because the new keys hash differently. Lua 5.3
    seeds its string hash per run, so a program that depends on `pairs`
    order is already non-deterministic. Renaming adds no new hazard.
- **o. Expected gain (estimate, 2026-10-06).** Measured on the 8 ports'
  `max` output. The estimate applies (b), (c) and (j) and assigns short
  names by frequency. It does not model (d) or (h), so a port that (h)
  would disable still counts in full. It took the library key list from
  desktop Lua 5.3, not TIC-80. "Kept by i" is the saving when
  function-valued keys keep their names:

  | Port | Code after `max` | Key-name share | Saved, all keys | Saved, kept by i |
  |---|---|---|---|---|
  | dinoeggs | 69,370 | 21.7% | 9,325 (13.4%) | 8,025 (11.6%) |
  | beyondcastlewolfenstein | 45,480 | 16.9% | 5,112 (11.2%) | 3,447 (7.6%) |
  | loderunner | 28,859 | 15.3% | 3,039 (10.5%) | 1,700 (5.9%) |
  | castlewolfenstein | 49,136 | 13.3% | 4,185 (8.5%) | 2,468 (5.0%) |
  | serpentine | 51,899 | 12.5% | 4,295 (8.3%) | 4,257 (8.2%) |
  | zaxxon | 36,306 | 12.3% | 2,690 (7.4%) | 1,942 (5.3%) |
  | impossible-mission | 33,514 | 8.6% | 1,670 (5.0%) | 1,298 (3.9%) |
  | wavynavy | 44,912 | 4.6% | 930 (2.1%) | 783 (1.7%) |
  | **total** | 359,476 | | **31,246 (8.7%)** | **23,920 (6.7%)** |

  The hazards occur at only a few sites:
  - 13 `pairs` loops, none of which uses a key value as a string;
  - 7 index keys built from strings, in 3 ports:
    - castlewolfenstein's base64 table (`f[alphabet:sub(i,i)]`), a finite
      set;
    - dinoeggs' `aG[l.."_s"..tostring(x)]`, which contains `_s`;
    - dinoeggs' `af[s:sub(l,l)]` with `s` a variable. Through D14's analysis
      of where values come from, this may still be shown safe; otherwise it
      disables the pass for dinoeggs;
    - serpentine's `e[a..","..b]`, which has shape none.
  - Two dinoeggs `gsub` calls whose replacement is `tostring(…)`, allowed by
    (e).
- **Open decisions.**
  - **O1.** Should function-valued keys keep their names (i, as drafted, for
    D11's readable tracebacks) or be renamed and decoded through the maps
    (about 2 more points of saving overall)?
  - **O2.** Should `fields` join a bare `--minify` and `max` once accepted, or
    stay opt-in? It is the only pass whose soundness depends on checks about
    how the program uses strings, rather than on Lua's semantics alone.
  - **O3.** Is the `keys:` form (k) the right escape hatch, or should a
    NOMINIFY attached to a table constructor or to `t.k = …` keep the keys
    it writes? The latter changes what R8i c keeps today.

## 6. Implementation phases and acceptance

All five phases were delivered on 2026-10-02, in one pass rather than in
sequence.

| Phase | Delivers | Accepted when | Result |
|---|---|---|---|
| 1 | Lua 5.3 recursive-descent parser on `lex()` (every node keeps its token span), scope resolver, R3 layout, max mode with only layout and tidy | Parses every port's bundle; R10b and R10c pass; the other modes stay byte-identical | Every parse proven lossless on all 8 bundles. `default`/`none` byte-identical to the baseline. The `luaparser` cross-check was not built: the lossless-parse proof plus the bytecode proof cover it. |
| 2 | D7 folding and D8 inlining (R4, R5), report skeleton | Fixtures for D7 exclusions and R4c splices; every port boots headless | `run.py fold`: 2,167 random folds, 0 mismatches against real Lua. Fixtures for negative and prefix splices. All 8 ports boot in TIC-80 1.2.0 Pro. |
| 3 | R6 dead-code removal, R7 tree shaking, R9 fixpoint | Fixtures for `do … end` wrapping, label stops, multiple-assignment arity, recursive dead functions | Covered by `fixtures.lua` (19 cases, all identical) |
| 4 | R8 renaming plus the R10g maps | R10c bytecode identity with local renaming only; maps round-trip | Bytecode identical on all 8 ports. `dist/<game>.minify.json` resolves every output line to `file:line`. |
| 5 | R11 optional passes | Each pass saves size on at least one port and stays equivalent | `difftest.py`: all 8 ports identical frame for frame over 3,600 frames, seeds 1–3 |

Size (code characters, 2026-10-02): old one-line `max` → new `max`. wavynavy
54,746 → 42,039. Others, raw → new: beyondcastlewolfenstein 140,746 → 46,877,
castlewolfenstein 121,637 → 49,797, loderunner 95,740 → 29,130, serpentine
171,721 → 51,152, dinoeggs 130,294 → 70,951, impossible-mission 76,662 → 33,920,
zaxxon 65,481 → 36,636. Minification takes 0.3–0.8 s per port.

Tests live in `tests/minify/`: `run.py` (fold, bytecode, fixtures),
`fixtures.lua`, and `difftest.py`.

**Phase 6, key renaming (R13). NOT IMPLEMENTED.** Accepted when all of these
hold:
- **Fixtures.** `fixtures.lua` has a case for each rule, each run with the
  pass on and its output compared:
  - kept names: platform keys (R13b), names in literals (R13c), protected
    code (R13g);
  - each key shape (D14), including a flow through a local, a parameter, a
    return value and a stored value;
  - `gsub` with a table (R13e);
  - each kind of key value use (R13f);
  - each trigger that disables the pass (R13h), with the report line.
- **Behaviour tests.** `tests/options` gains marker names (`renamefield_*`
  must be renamed, `keepfield_*` must not be) and `fields` in its option
  combinations.
- **`difftest`.** Its order-stable `pairs` stub sorts keys by name, and
  renaming changes that order. For the minified run, the stub must sort by
  each key's original name, read from the R13m map. Then all 8 ports must
  be identical over 3,600 frames, seeds 1–3, with `fields` on.
- **Runtime key check** (test only). `difftest` gains a mode that runs the
  original bundle with every non-literal index key (`t[e]`, `{[e]=…}`)
  wrapped, so that each string used as a key at runtime is recorded. It fails
  if a recorded string is a renamed key's old name or any new name. This
  covers only the code the run reaches, so it backs R13d up rather than
  proving it.
- **Gain.** On the ports that the pass does not disable, the saving is close
  to the R13o estimate.

## 7. Decision log

- **2026-10-02:** target confirmed as Lua 5.3, not 5.4 (headless probe of TIC-80
  1.2.0 Pro).
- **2026-10-02:** table fields and the implicit `self` are out of scope (Q1).
- **2026-10-02:** function names are not renamed, for debuggability (D11).
- **2026-10-02:** inlining strings is size-guarded (Q2, R4b).
- **2026-10-02:** the max layout puts each function start on its own line
  and wraps at 120 columns (Q3, R3).
- **2026-10-02 (as built):** every constant is size-guarded, not only strings
  (R4a). The reserved list is embedded in `minify.py` (D4.2). D6 triggers on
  any read of the dynamic names. D6a (escaping `require`) and I1a (fragment
  mode) were added. R10b/c/d were implemented as described in their notes.
- **2026-10-02:** two harness traps found while testing, both recorded in
  `difftest.py`. Lua 5.3's `math.random` is C `rand()`, one generator shared
  by every Lua state in the process, so builds stepped in lockstep consumed
  each other's random numbers. String-hash seeds differ per state, so `pairs`
  order needs a stable stub.
- **2026-10-02:** asset-chunk detection is strict (D1), after the looser
  `^-- <NAME>` match cut wavynavy's bundle at a prose comment in `a2boot.lua`.
  TIC-80's own loader has the looser behaviour, so a `--minify=none` bundle of
  wavynavy fails to boot (pre-existing; see `minify.md`).
- **2026-10-02:** `luaparser` (4.0.1 and 4.2.0) was rejected as the
  foundation: it has no source positions on binding sites (about 63% of names in
  wavynavy), its printer emits `--x` for `- -x` and breaks `[==[…]==]` strings,
  and it can't parse hex floats. It stays useful as a test cross-check.
- **2026-10-03:** a per-binding rename opt-out by comment marker, `NOMINIFY`
  (R8g), at the owner's request, so a name a debugger or a reader must
  recognise can survive `rename`. Its scope is the declaring/assigning line, not
  the reads, so one marker covers every occurrence. Output for code with no
  marker is unchanged (all 210 port modules byte-identical).
- **2026-10-03:** two option-interaction bugs from splitting `max` into options,
  found by the owner on wavynavy with `--minify=comments,constants`. (1) R4's
  declaration removal lived only in R7 (shake), so without `extra` the inlined
  constants' declarations stayed: 145 inlined, 0 removed. A restricted removal
  now runs when R4 runs without R7. (2) The R4b size check assumed renamed
  2-character names, so without `rename` it kept constants such as
  `FLD_X1 = 243` whose inlining saves space. It now uses the real name length
  when R8 is off. Result on wavynavy: 143 of 145 declarations removed, code
  66,262 → 56,769 characters. `all`/`max` output is unchanged (210 modules
  byte-identical). (The `rename` option is `rename-vars` since 2026-10-06.)
- **2026-10-04:** NOMINIFY extended to functions and modules (R8h), at the
  owner's request: the same marker, placed on or around a function
  declaration or in a module's top comment block, keeps that code byte for
  byte. Implemented as one opaque token, not as per-pass exceptions, so no
  pass can reach inside. What the protected code uses is pinned rather than
  analysed — conservative but safe, and checked by the behaviour tests. Code
  with no marker is unchanged (210 port modules byte-identical).
- **2026-10-05:** NOMINIFY reworked around comment blocks and statements
  (R8g, R8h, R8i), at the owner's request. A directive is a comment block or
  a trailing comment, attached to the statement after the block or on the
  comment's line, instead of to source lines. Changes: a block above a
  `local`, assignment or `for` now keeps those variables; a kept variable is
  pinned, so it is no longer inlined or removed; a function's closing line
  marks it too; a block in a function body's first lines no longer protects
  the function; a directive that keeps nothing keeps its own comment; a
  directive above a preload line no longer protects the module; the word
  must be a whole word. Port output is unchanged (218 port files
  byte-identical under four option sets; 8/8 ports identical in `difftest`).
- **2026-10-06:** `literals` (R11e) added to `extra`, at the owner's request,
  after measuring what is left in the minified ports. Inlining small
  functions was measured and rejected: about 1%, all of it from deleting
  definitions of functions called once or twice; a function called in many
  places grows the code when inlined, as its unrenamed name is shorter than
  its body. `alias`'s traversal became the shared `slot_walk` (port output
  without `literals` byte-identical), and its revert now keeps call sugar's
  edits, which it used to drop.
- **2026-10-06:** key renaming drafted as I1b, D13, D14 and R13, at the
  owner's request. It is **NOT IMPLEMENTED**, and table keys stay out of
  scope (§1) until it is.
  - **Approach.** Keys are renamed by spelling, the way Closure Compiler
    renames properties. Working out which tables the program defines was
    rejected: tables flow through parameters, globals, closures and
    metatables, so tracking them would cost a lot and still lump most tables
    together. Renaming by spelling needs only the list of names the platform
    can see, and on TIC-80 that list is short.
  - **Why it is opt-in (I1b).** Every earlier pass is sound by Lua's
    semantics. This one is sound only when its checks on the whole program
    pass (R13h).
  - **What it would save.** Measured first: key names are 4.6–21.7% of the
    ports' `max` output, and renaming them would save an estimated 6.7–8.7%
    overall (R13o). That is the largest saving still available. `literals`
    saved 1.0%.
- **2026-10-06:** function renaming added as an opt-in option,
  `rename-functions` (I1c, R8j), at the owner's request; D11 now keeps
  function names only without it. `rename` became `rename-vars`. The presets
  became `default` (every option but `rename-functions`: a bare `--minify`)
  and `max` (every option), both accepted by `--minify`; the CLI used to call
  every option `all` and rejected preset names. Measured first: 5.8% off the
  8 ports' `default` output (R8j f), against readable error messages, so it
  stays out of `default`. A NOMINIFY on a `function`/`local function`
  statement now keeps its name as well as its body (R8h f). Output without
  `rename-functions` is unchanged: the port sizes under `default` match the
  previous `max` exactly.
