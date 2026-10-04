-- title:  syntax
-- author: minify-option tests
-- desc:   sample cart 'syntax' for tests/options
-- site:   https://tic80.com
-- license: MIT License
-- version: 0.1
-- script: lua

-- syntax: Lua 5.3 constructs a minifier must not break. Everything computed
-- here is traced from TIC(), so any change in meaning shows in the log.

local renameme_t = {}

-- strings that contain comment-like and bracket-like text
local s1 = "a -- not a comment"
local s2 = 'single \'quoted\' \\ backslash'
local s3 = [[long
string -- with dashes
  and   spaces]]
local s4 = [==[ level ]] two ]==]

--[[ block
comment ]] local renameme_after_block = 1
--[==[ a level-2 comment
]] still comment ]==]

-- numbers and operators
local n1, n2, n3, n4 = 0xff, 1e3, 3.25, 0x1p4
local i1 = 7 // 2
local f1 = 7 / 2
local b1 = (0xf0 & 0x3c) | 0x01 ~ 0x02
local sh = 1 << 4 >> 2
local neg = - -3
local cat = 1 .. ""
local p = 2 ^ 3 ^ 2
local m = -2 ^ 2
local x, y, z = 1, 2
local prec = (x & y) + 3
local cmp = not (x < y) == false

-- functions, varargs, multiple returns
local function va(...)
  local a, b = ...
  return select("#", ...), a, b
end
local function multi() return 1, 2, 3 end
local t2 = {multi()}
local t3 = {multi(), 10}
local one = (multi())

-- methods and metatables
local obj = {v = 5}
function obj:get() return self.v end
function obj.static(k) return k * 2 end
local mt = setmetatable({}, {__index = function(_, k) return k .. "!" end})

-- goto and labels
local count = 0
do
  ::top::
  count = count + 1
  if count < 3 then goto top end
end

-- repeat-until sees the body's locals
local r = 0
repeat
  local stop = r >= 2
  r = r + 1
until stop

-- shadowing
local shadow = 1
do
  local shadow = shadow + 1
  renameme_t[1] = shadow
end
renameme_t[2] = shadow

-- closures
local function counter()
  local c = 0
  return function()
    c = c + 1
    return c
  end
end
local inc = counter()
inc()

-- loops
local acc = 0
for k = 10, 1, -3 do acc = acc + k end
for _, v in ipairs({4, 5, 6}) do acc = acc + v end
while acc > 100 do acc = acc - 7 end

-- string escapes and library calls
local esc = "tab\tq\"q\" \65\066 \x41 \u{48}"
local up = ("abc"):upper()
local fmt = string.format("%5.2f|%d|%s", 3.14159, 42, "x")
local fl1, fl2 = math.floor(7.9), math.tointeger(3.0)

function TIC()
  trace(s1, s2, s3, s4, renameme_after_block)
  trace(n1, n2, n3, n4, i1, f1, b1, sh, neg, cat, p, m, x, y, z, prec, cmp)
  trace(va(1, nil, 3))
  trace(#t2, #t3, one, obj:get(), obj.static(4), mt.key)
  trace(count, r, renameme_t[1], renameme_t[2], inc(), acc)
  trace(esc, up, fmt, fl1, fl2)
end
