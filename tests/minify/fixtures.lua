-- minifier fixtures: one whole program per "-- @@ name" section, printing with
-- trace(). run.py minifies each in max mode and compares the output with the
-- original's. Add a case whenever a transform gets a new rule or a bug fix.

-- @@ constants: globals, locals, chains, folding
SPEED = 3
SCALE = SPEED * 2
local W, H = 240, 136
local AREA = W * H
NAME = "a long string constant that is read several times"
trace(SPEED, SCALE, AREA, W // 7, H / 8, 2 ^ 10, 7 // 2, -7 // 2, 7 % -3, -7 % 3, 5.5 % 2)
trace(NAME, NAME, NAME, #NAME)
trace("the answer is: " .. 1 + 3 * 2, 10 .. "", 2.0 .. "", 1e15 .. "", 1e16 .. "", -0.0 .. "")
trace(0x7fffffffffffffff + 1, math.maxinteger * 2, 1 << 63, 1 << 64, -1 >> 1, 3 & 5, 3 | 5, 3 ~ 5, ~0)
trace(1 == 1.0, "1" == 1, 2 < 3, 1 / 0 > 0, 0.1 + 0.2, 1 / 3)

-- @@ negative constants in every operator position
local K = -1
local F = -2.5
local x = 5
trace(x - K, x + K, x * K, x ^ K, K ^ 2, -K, - -K, x .. K, K .. x, x // K, x % K)
trace(F ^ 2, -F, x - F, F < 0, K < F)
local t = {K, F, [K] = "neg", n = K}
trace(t[1], t[2], t[-1], t.n)

-- @@ strings in prefix position
local S = "hello"
local P = "%d-%d"
trace(S:upper(), S:sub(2, 3), #S, S .. S, P:format(1, 2), ("x"):rep(3))
local T = {S = 1}
trace(T.S, T[S])

-- @@ booleans, nil, and/or folding
DEBUG = false
VERBOSE = nil
ON = true
local function f() return 1, 2, 3 end
trace(DEBUG and "d" or "nd", VERBOSE or "v", ON and "on", ON or f())
trace((ON and f()))
trace(ON and f())
trace(select("#", ON and f()))
trace(DEBUG or f())
trace(false or nil, nil and 1, ON and nil, DEBUG == false, VERBOSE == nil, not DEBUG)

-- @@ dead branches, scoping of an unwrapped body
local DEV = false
local LIVE = true
local v = "outer"
if DEV then trace("dev") v = "dev" end
if LIVE then local v = "inner" trace(v) end
trace(v)
if DEV then trace("no") elseif LIVE then trace("yes") else trace("never") end
if DEV then trace("a") elseif DEV then trace("b") end
while DEV do trace("loop") end
for i = 1, 0 do trace("empty for") end
for i = 3, 1, -1 do trace("down", i) end
local function early(n)
  if n > 1 then return "big" end
  do return "small" end
end
trace(early(1), early(2))

-- @@ shadowing and closures
local a = 1
local function get() return a end
local a = 2
trace(a, get())
local fns = {}
for i = 1, 3 do local j = i * 10 fns[i] = function() return i + j end end
trace(fns[1](), fns[2](), fns[3]())
local x = 1
do local x = x + 1 trace(x) end
trace(x)
local y = 5
local y = y * 2
trace(y)

-- @@ multiple assignment and varargs
local function three() return 1, 2, 3 end
local p, q, r = three()
local s, u = 1
local m, n = three(), 10
trace(p, q, r, s, u, m, n)
local A, B, C = 1, 2
trace(A, B, C)
local function va(...) local a, b = ... return select("#", ...), a, b end
trace(va(), va(1), va(1, 2, 3))
local function pack(...) return {...} end
trace(#pack(three()), #pack(three(), 4), #pack((three())))
local g1, g2
g1, g2 = three()
trace(g1, g2)

-- @@ unused things: trailing params, dead locals, impure initialisers
local calls = 0
local function bump() calls = calls + 1 return calls end
local unused1 = bump()
local unused2 = 42
local unused3 = {1, 2, 3}
local function unused_fn() trace("never") end
local function takes(a, b, c) return a end
trace(takes(1, 2, 3), calls)
local _, keep = bump(), 7
trace(keep, calls)
GLOBAL_UNUSED = bump()
trace(calls)

-- @@ globals: renaming, functions keep names, reads before write
counter = 0
function step(n) counter = counter + n return counter end
step(2); step(3)
trace(counter, step(1))
trace(late_const)
late_const = 99
trace(late_const)
local tbl = {}
function tbl.method(self, k) return k * 2 end
function tbl:other(k) return self.method(self, k) + 1 end
trace(tbl:method(3), tbl:other(4))

-- @@ goto and labels
for i = 1, 3 do
  for j = 1, 3 do
    if j == 2 then goto continue end
    trace(i, j)
    ::continue::
  end
end
do
  local k = 0
  ::top::
  k = k + 1
  if k < 3 then goto top end
  trace("k", k)
end

-- @@ repeat-until scope, numeric for float steps, while
local i = 0
repeat local done = i >= 2 i = i + 1 until done
trace(i)
for f = 0, 1, 0.25 do trace(f) end
local n = 3
while n > 0 do n = n - 1 end
trace(n)

-- @@ table constructors and call sugar
local t = {1, 2, 3; n = 4, ["k"] = 5, [10] = 6,}
trace(#t, t.n, t.k, t[10])
local function id(x) return x end
trace(id("str"), id({7})[1], type(id{}), (id"s"))
local s = ("%s|%s"):format("a", "b")
trace(s)

-- @@ integer and float edge literals
trace(0x10, 0xff, 0x7fffffffffffffff, 0xffffffffffffffff, 9223372036854775807, 9223372036854775808)
trace(1e300 * 10 > 1e300, 2^63, -2^63, 0x1p4, 0x.8, 3., .5, 1e-5, 123456789.125)
trace(math.type(3 // 1), math.type(3.0 // 1), math.type(2^2), 7 // 0.0 == math.huge)

-- @@ string escapes survive folding
local E = "tab\there\nnl \"q\" 'a' \\ \0 \1\2 \65\066 \x41 \u{48}\z
           continued"
trace(E .. "!", #E)
local L1 = [[
long
string]]
trace(L1 .. "", #L1)
trace("é" .. "ß", #("é" .. "ß"))

-- @@ aliasing library functions and fields
local acc = 0
for k = 1, 30 do
  acc = acc + math.floor(k / 3) + math.max(k, 5) + math.abs(-k) + math.min(k, 9)
  acc = acc + math.floor(k * 1.5) + math.max(1, 2) + string.len("abc") + string.byte("a")
end
trace(acc, math.pi, math.huge > 1)

-- @@ local merge must not merge a dependent initialiser
local m1 = 1
local m2 = m1 + 1
local m3, m4 = 3, 4
local m5 = 5
trace(m1, m2, m3, m4, m5)
local function cl() return m5 end
local m6 = cl()
trace(m6)

-- @@ module-style tables and preload
package.preload["mod"] = function(...)
  local M = {}
  local PRIVATE = 7
  function M.get() return PRIVATE end
  M.value = PRIVATE * 2
  return M
end
package.preload["unused_mod"] = function(...)
  trace("unused module ran")
  return {}
end
local mod = require "mod"
trace(mod.get(), mod.value)

-- @@ constants defined in a required module, read at top level after require
package.preload["consts"] = function(...)
  LIMIT = 10
  LABEL = "lim"
end
require "consts"
local doubled = LIMIT * 2
trace(doubled, LABEL)

-- @@ modules loaded through pcall(require) and an aliased require
package.preload["viapcall"] = function(...)
  return {v = "loaded through pcall"}
end
package.preload["viaalias"] = function(...)
  return {v = "loaded through an alias"}
end
local ok, m = pcall(require, "viapcall")
trace(ok, m.v)
local r = require
trace(r("viaalias").v)
