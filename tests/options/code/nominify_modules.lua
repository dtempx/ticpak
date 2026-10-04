-- nominify_modules: module-level directives in a ticpak-shaped bundle (spec
-- R8h). Each keepmod_* module comes out byte for byte; minmod_plain does not.

package.preload["keepmod_top"] = function(...)
-- keepmod_top: NOMINIFY in the module's top comment block
local M = {}

-- a comment inside the module, kept
function M.twice(v)
  return v * 2   -- kept
end

return M
end

package.preload["keepmod_wins"] = function(...)
-- NOMINIFY: this top block runs straight into a function declaration, so it
-- could also read as a function-level directive - module level wins
local function helper(v) return v + 1 end
local M = {}
function M.inc(v)
  -- kept: the whole module is protected, not just helper
  return helper(v)
end
return M
end

package.preload["keepmod_blank"] = function(...)
-- NOMINIFY: module level - a blank line follows, then a function declaration

local function negate(v)
  -- kept
  return -v
end
return {neg = negate}
end

package.preload["minmod_plain"] = function(...)
-- minmod_plain: no directive, minified as usual

local M = {}
function M.half(v)
  -- removed
  return v / 2
end
return M
end

local top = require "keepmod_top"
local wins = require "keepmod_wins"
local blank = require "keepmod_blank"
local plain = require "minmod_plain"

function TIC()
  trace(top.twice(3), wins.inc(4), blank.neg(5), plain.half(6))
end
