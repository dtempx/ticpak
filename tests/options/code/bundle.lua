-- bundle: the shape ticpak produces - every module inlined as a
-- package.preload entry, then the entry stub's requires and callbacks.
--
--   CONST_*        module-level constants read across modules (`constants`)
--   renameme_*     shortened by `rename-vars`
--   UNUSED_MODULE  a preload entry nothing requires, removed by `extra`

package.preload["constants"] = function(...)
CONST_W = 30
CONST_H = 17
CONST_TITLE = "BUNDLE"
end

package.preload["util"] = function(...)
local M = {}

-- wrap v into 0..n-1
function M.wrap(v, n)
  return v % n
end

function M.lerp(a, b, t)
  return a + (b - a) * t
end

return M
end

package.preload["never_required"] = function(...)
trace("UNUSED_MODULE")
end

require "constants"
local util = require("util")

renameme_tick = 0
local renameme_pos = {x = 0, y = 0}

function TIC()
  renameme_tick = renameme_tick + 1
  renameme_pos.x = util.wrap(renameme_pos.x + 3, CONST_W * 8)
  renameme_pos.y = util.lerp(renameme_pos.y, CONST_H * 4, 0.25)
  cls(1)
  print(CONST_TITLE, renameme_pos.x, renameme_pos.y)
  if renameme_tick % 10 == 0 then
    sync(1, 1)
  end
  trace(renameme_tick, renameme_pos.x, renameme_pos.y)
end
