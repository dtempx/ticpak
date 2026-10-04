-- A stand-in TIC-80 API for running a cart's code under lupa (real Lua 5.3).
-- Every API call is logged with its arguments; RUN(code, frames) loads the
-- code, calls BOOT() once and TIC() `frames` times, and returns the log. Two
-- builds of the same program behave the same iff their logs are equal.
--
-- Values are logged with their type (and integer/float subtype), so a
-- minifier that turned 2.0 into 2 is caught. Tables and functions are logged
-- by type only: their addresses differ between runs.

local LOG = {}
local frame = 0
local seed = 12345
local mem = {}

local function fmt(v)
  local t = type(v)
  if t == "number" then return math.type(v) .. ":" .. tostring(v) end
  if t == "string" or t == "boolean" or t == "nil" then return t .. ":" .. tostring(v) end
  return t
end

local function logged(name, ret)
  return function(...)
    local parts = {name}
    for i = 1, select("#", ...) do
      parts[#parts + 1] = fmt((select(i, ...)))
    end
    LOG[#LOG + 1] = table.concat(parts, " ")
    if type(ret) == "function" then return ret(...) end
    return ret
  end
end

-- drawing, sound and memory calls: logged, return nothing useful
for _, name in ipairs({"cls", "spr", "map", "mset", "rect", "rectb", "circ", "circb",
                       "elli", "ellib", "line", "pix", "tri", "trib", "textri", "ttri",
                       "sfx", "music", "sync", "memcpy", "memset", "poke", "poke1",
                       "poke2", "poke4", "font", "clip", "vbank", "trace", "fset",
                       "reset", "exit"}) do
  _G[name] = logged(name, nil)
end

-- calls whose results a cart reads: deterministic stand-ins
btn = logged("btn", function(i) return (frame + (i or 0)) % 5 == 0 end)
btnp = logged("btnp", function(i) return (frame + (i or 0)) % 7 == 0 end)
key = logged("key", function() return false end)
keyp = logged("keyp", function() return false end)
time = logged("time", function() return frame * 16 end)
tstamp = logged("tstamp", function() return 1700000000 end)
print = logged("print", function(s) return 6 * #tostring(s) end)
mget = logged("mget", function(x, y) return ((x or 0) + (y or 0)) % 4 end)
fget = logged("fget", function() return false end)
peek = logged("peek", function(a) return mem[a] or 0 end)
peek1 = logged("peek1", function() return 0 end)
peek2 = logged("peek2", function() return 0 end)
peek4 = logged("peek4", function() return 0 end)
mouse = logged("mouse", function() return 0, 0, false, false, false end)
pmem = logged("pmem", function(i, v)
  if v ~= nil then mem[-1 - i] = v end
  return mem[-1 - i] or 0
end)

-- math.random is C rand() under lupa, shared by every Lua state in the
-- process: replace it with a seeded LCG so both builds see the same numbers
math.randomseed = function(s) seed = math.tointeger(s) or 12345 end
math.random = function(m, n)
  seed = (seed * 1103515245 + 12345) % 2147483648
  if m == nil then return seed / 2147483648 end
  if n == nil then m, n = 1, m end
  return m + seed % (n - m + 1)
end

function RUN(code, frames)
  local f, err = load(code, "=cart", "t")
  if not f then return "LOADERROR " .. tostring(err) end
  local ok, e = pcall(f)
  if not ok then return "RUNERROR " .. tostring(e) end
  if BOOT then
    ok, e = pcall(BOOT)
    if not ok then LOG[#LOG + 1] = "BOOTERROR " .. tostring(e) end
  end
  for i = 1, frames do
    frame = i
    if TIC then
      ok, e = pcall(TIC)
      if not ok then
        LOG[#LOG + 1] = "TICERROR " .. tostring(e)
        break
      end
    end
  end
  return table.concat(LOG, "\n")
end
