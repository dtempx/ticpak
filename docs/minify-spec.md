# ticpak minifier: `max` mode — specification

Status: **implemented 2026-10-02** in [`minify.py`](minify.py), and verified on
all 8 TIC-80 ports (§6). Usage is in [`minify.md`](minify.md). This file is the
contract. Each requirement has an ID so code, tests and review comments can cite
it.

Where the implementation departs from the original draft, the requirement
says so in an **As built** note, and §7 logs the decision.

## 1. Purpose and scope

Shrink the code of a packaged TIC-80 cart far beyond comment and whitespace
removal. The passes are: inlining constants, folding constant expressions,
removing dead code, tree shaking unreferenced definitions, and renaming
non-function variables. Behaviour must stay identical, and the result must stay
debuggable: function names survive, and each function starts on its own line.

**Out of scope:**
- renaming table fields (`obj.x`, `M.update`, `{k=…}`, string keys), method
  names, and the implicit `self`;
- renaming function names (see D11);
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

- **I1. Mode.** `max` (`ticpak --minify=max`, `minify.py --mode=max`).
  `default` stays the default, and `none` and `default` keep their output byte
  for byte (checked against the pre-change baseline on wavynavy).
- **I1a. Fragment mode** (added as built). `whole_program=False` /
  `--fragment` minifies one module on its own: no pass touches globals.
  beyondcastlewolfenstein's `check.py` uses it for per-module size estimates.
- **I2. Pass switches.** `--passes=<list>` picks a subset of the max-mode
  passes: `fold,inline,dce,shake,rename,sugar,alias,merge`, defaulting to all.
  Layout (R3) and tidy (R11d) always run in max mode.
- **I3. Width.** `--width=N` sets the line width, default 120 (R3).
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
  `g = function…`). Function bindings are **never renamed**, so names in
  tracebacks still read as the source wrote them. They can still be removed by
  tree shaking (R7).
- **D12. Function-start statement.** A `function` statement, a `local function`
  statement, or an assignment or `local` statement whose first right-hand-side
  expression is a function expression. The `package.preload["m"] =
  function(...)` lines are function-start statements.

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
  is needed, plus the token's length fits within `--width` (default 120);
  otherwise a newline replaces the separator and the token starts the next line.
  Length counts characters and excludes the newline.
- **c.** Lines break **only between tokens**, never inside one. In Lua 5.3 a
  newline is a valid separator between any two tokens: the `f\n(g)` ambiguity
  that was an error in 5.1 parses identically since 5.2.
- **d.** A token longer than the width (a long string) sits on a line of its own
  and is the only allowed overflow.
- **e.** No indentation and no trailing whitespace. The code ends with a single
  `\n` before the chunks, as the current modes do.
- **f.** For example, with `--width=40`:

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
  `--inline=all` overrides the check. **As built:** the new name's length is
  estimated as 2 when renaming (R8) runs, and as the name's own length when it
  doesn't (the `constants` option without `rename`, 2026-10-03); the
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

**R8. Renaming** (non-function bindings only).
- **a. What is renamed:** locals (including parameters, `for` variables and
  labels) and non-reserved globals. Function bindings (D11), reserved names
  (D4), fields and the implicit `self` are not renamed. Globals are renamed only
  when no dynamic access (D6) is present.
- **b. Name pool,** in order: all 1-character identifiers (`a`–`z`, `A`–`Z`,
  `_`), then 2-character ones, then 3-character ones, and so on. The pool
  excludes:
  - keywords (the 2-character ones are `do`, `if`, `in`, `or`);
  - reserved names;
  - function-binding names in use;
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
  unrenamed (function bindings, reserved names, and in fragment mode all
  globals). Bytecode identity under local renaming is proven on every port
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
  any `local` and the function's name are emitted as usual. The comment
  carrying the directive is removed like any other comment unless it lies
  inside the protected text.
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

**R9. Pass order.** `fold → inline → dce → shake`, repeated until nothing
changes (and at most 10 rounds; reaching the cap is an error), then `rename`,
then the optional passes (R11), then layout (R3). Each pass is a set of token
edits on the original token stream, planned from the parse.

**As built:** the passes edit the lossless tree described in R10b. Each pass
works on a fresh parse and re-emits it. The fixpoint loop allows 20 rounds,
and 2–3 is typical. The small passes (sugar, alias, merge, tidy) run *before*
`rename`, so the aliases they create get short names too.

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
     subexpression with a literal, or renaming, so a token no pass touched
     comes out unchanged.
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
- **Excluded:** removing "redundant" parentheses. It saves little and is
  exactly how npm luamin miscompiled wavynavy.

**R12. Integration.**
- The minifier is `ticpak/minify.py`, also run on its own as
  `ticpak minify`.
- `ticpak` reaches it only through `minify.minify_cart()` /
  `minify_cart_ex()`.
- The reserved-name list (D4.2) is generated by a small headless TIC-80 probe
  script, `scripts/update_reserved.py`.

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
  byte-identical).
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
