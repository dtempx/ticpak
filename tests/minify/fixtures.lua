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

-- @@ shared literals: one value, many spellings; int vs float; sugar; require
package.preload["shared_mod"] = function(...)
  return {name = "a string written many times over"}
end
local sm = require "shared_mod"
local s = "a string written many times over"
local function show(x) return x end
trace(s == sm.name, show"a string written many times over", ("a string written many times over"):len())
trace(4096, 0x1000, 4096.0, 4096 // 3, 4096.0 // 3, math.type(4096), math.type(4096.0), -4096, 4096 .. "")
trace(0x1000 | 1, 4096 << 1, 4096, 4096, 4096, 4096 == 4096.0)
local t = {[4096] = "int key", ["a string written many times over"] = 1}
trace(t[4096], t[4096.0], t["a string written many times over"], t[sm.name])
for i = 4090, 4096, 3 do trace(i, select("#", 4096, 4096)) end
trace([[a string written many times over]], 'a string written many times over', "a string written many times over")
trace(1, 1.0, 1, 1.0, 1, 1.0, 1, 1.0, 1, 1.0, 1, 1.0, math.type(1), math.type(1.0))

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

-- @@ table keys: fields, methods, constructors, key literals, function paths
local Ship = {}
Ship.__index = Ship
function Ship.new(x, y) return setmetatable({pos_x = x, pos_y = y, ["hit_points"] = 3}, Ship) end
function Ship:move_by(dx, dy) self.pos_x = self.pos_x + dx self["pos_y"] = self.pos_y + dy end
function Ship:alive() return self.hit_points > 0 end
local game = {world = {fleet = {}}}
function game.world.fleet.spawn(x) return Ship.new(x, x * 2) end
local s = game.world.fleet.spawn(5)
s:move_by(1, 2)
s.hit_points = s.hit_points - 1
local cfg = {["scroll_speed"] = 2, wave_count = 4, [1] = "first", [2.5] = "float key"}
trace(s.pos_x, s.pos_y, s:alive(), s["hit_points"], cfg.scroll_speed, cfg["wave_count"], cfg[1], cfg[2.5])

-- @@ table keys: a key also written as a string stays, and still matches
local t = {state_name = "idle", other_field = 7}
local k = "state_name"
trace(t[k], t.state_name, t.other_field, rawlen and "has rawlen")
local function get(tbl, key) return tbl[key] end
trace(get(t, "state_name"), get({mode_flag = 1}, "mode_flag"), t.other_field)

-- @@ table keys: copied through pairs, compared with a literal
local src = {alpha_value = 1, beta_value = 2, gamma_value = 3}
local dst, sum, found = {}, 0, false
for key, v in pairs(src) do
  dst[key] = v * 10
  sum = sum + v
  if key == "beta_value" then found = true end
end
trace(dst.alpha_value, dst.beta_value, dst.gamma_value, sum, found, next({}) == nil)

-- @@ table keys: dispatch on type(), and on a key built by format and ..
local handlers = {number = function(v) return v * 2 end, string = function(v) return #v end,
                  table = function(v) return v.item_count end}
trace(handlers[type(4)](4), handlers[type("abc")]("abc"), handlers[type({item_count = 9})]({item_count = 9}))
local sprites = {sprite_01 = "a", sprite_02 = "b", sprite_10 = "c", big_sprite = "d"}
for i = 1, 2 do trace(sprites[string.format("sprite_%02d", i)], sprites["sprite_" .. i * 10]) end
trace(sprites.big_sprite, sprites["sprite_0" .. 1])

-- @@ table keys: the characters of a literal, and short substrings
local ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
local lookup = {}
for i = 1, #ALPHA do lookup[ALPHA:sub(i, i)] = i - 1 end
local data, acc = "TWFu", 0
for i = 1, #data do acc = acc * 64 + lookup[data:sub(i, i)] end
local cell = {long_name_here = 5, xy = 6}
trace(acc, lookup.Q, cell.long_name_here, cell.xy)

-- @@ table keys: __index and __newindex functions, inheritance
local Base = {}
Base.__index = Base
function Base.new(n) return setmetatable({base_value = n}, Base) end
function Base:describe() return self.base_value * 100 end
local Derived = setmetatable({}, {__index = Base})
Derived.__index = Derived
function Derived.new(n) local o = Base.new(n) o.extra_value = n + 1 return setmetatable(o, Derived) end
function Derived:total() return self:describe() + self.extra_value end
local d = Derived.new(2)
local log, backing = {}, {stored_field = 1}
local proxy = setmetatable({}, {
  __index = function(_, key) return key == "magic_word" and 42 or backing[key] end,
  __newindex = function(_, key, value) log[#log + 1] = value backing[key] = value end,
})
proxy.written_field = 5
trace(d:total(), d.base_value, proxy.magic_word, proxy.anything_else, proxy.stored_field,
      proxy.written_field, backing.written_field, #log)

-- @@ table keys: the library's own tables, string methods, table functions
function string.shout_text(s) return s:upper() .. "!" end
local words = {}
table.insert(words, "one")
table.insert(words, 1, "zero")
local packed = table.pack(10, 20, 30)
trace(("hi"):shout_text(), ("ab"):rep(2), #words, table.concat(words, ","), packed.n, packed[3],
      math.huge > 0, math.floor(3.7), select("#", table.unpack(words)), table.remove(words))
local list = {{rank_order = 3, label_text = "c"}, {rank_order = 1, label_text = "a"}, {rank_order = 2, label_text = "b"}}
table.sort(list, function(a, b) return a.rank_order < b.rank_order end)
trace(list[1].label_text, list[2].label_text, list[3].label_text)

-- @@ table keys: callbacks, varargs, pcall, coroutines carrying tables
local function each(items, fn, ...) for i = 1, #items do fn(items[i], ...) end end
local total = {running_sum = 0}
each({{point_value = 1}, {point_value = 2}}, function(item, bonus) total.running_sum = total.running_sum + item.point_value + bonus end, 10)
local ok, res = pcall(function(o) return o.inner_field * 2 end, {inner_field = 21})
local co = coroutine.wrap(function(o) coroutine.yield(o.first_slot) return o.second_slot end)
trace(total.running_sum, ok, res, co({first_slot = "f", second_slot = "s"}), co())

-- @@ table keys: a key printed from a pairs loop keeps every name (pass off)
local only = {single_entry_key = 1}
for key, v in pairs(only) do trace(key, v) end
local other = {another_long_field = 2}
trace(other.another_long_field)

-- @@ table keys: gsub with a table replacement keeps every name (pass off)
local vars = {player_name = "Ann", level_number = "3"}
trace(("$player_name reached $level_number"):gsub("%$(%w+_%w+)", vars))
trace(vars.player_name)

-- @@ table keys: a key built from data at runtime keeps every name (pass off)
local parts = {"spe", "ed"}
local stats = {speed = 9, power_level = 4}
trace(stats[table.concat(parts)], stats.power_level)

-- @@ table keys: handlers looked up by a built name (on_ .. event)
local Button = {click_count = 0}
function Button:on_click() self.click_count = self.click_count + 1 end
function Button:on_hover() self.hover_seen = true end
local function fire(obj, event) local h = obj["on_" .. event] if h then h(obj) end end
fire(Button, "click") fire(Button, "click") fire(Button, "hover") fire(Button, "drag")
trace(Button.click_count, Button.hover_seen)

-- @@ table keys: a key handed to a helper that prints it keeps every name (pass off)
local function show(x) trace(x) end
for key in pairs({only_key_here = 1}) do show(key) end

-- @@ table keys: a key stored in a list, printed later, keeps every name (pass off)
local names = {}
for key in pairs({stored_key_name = 1}) do names[#names + 1] = key end
trace(names[1])

-- @@ table keys: a key returned and joined into a string keeps every name (pass off)
local function first_key(t) for key in pairs(t) do return key end end
trace(first_key({returned_key = 1}) .. "!")

-- @@ table keys: a key from next() and a sorted key list keep every name (pass off)
local bag = {zeta_entry = 1, alpha_entry = 2}
local keys = {}
for key in next, bag do keys[#keys + 1] = key end
table.sort(keys)
trace(bag[keys[1]], bag[keys[2]], next({lone_key = 1}) ~= nil)

-- @@ table keys: a key ordered by < keeps every name (pass off)
local order = {}
for key in pairs({banana_key = 1, apple_key = 2}) do
  if key < "b" then order[1] = key else order[2] = key end
end
trace(#order)

-- @@ table keys: a key an __index function prints keeps every name (pass off)
local spy = setmetatable({}, {__index = function(_, key) trace("looked up", key) return 0 end})
trace(spy.some_missing_field)

-- @@ table keys: a key yielded from a coroutine keeps every name (pass off)
local gen = coroutine.wrap(function() for key in pairs({yielded_key = 1}) do coroutine.yield(key) end end)
trace(gen())

-- @@ table keys: a key's string methods keep every name (pass off)
for key in pairs({method_key = 1}) do trace(#key, key:upper()) end
