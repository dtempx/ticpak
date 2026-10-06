-- game: a bouncing ball, with state that `rename-vars` shortens and a
-- function that `rename-functions` does

local util = require "util"

local M = {}

local renameme_ball = {x = 40, y = 20, vy = 0}
local renameme_bounces = 0   -- counted for the trace
local keepme_frame = 0       -- NOMINIFY: kept for a debugger watch

local function renamefn_land()
  renameme_ball.y = CONST_FLOOR
  renameme_ball.vy = CONST_JUMP
  renameme_bounces = renameme_bounces + 1
end

function M.update()
  keepme_frame = keepme_frame + 1
  renameme_ball.vy = renameme_ball.vy + CONST_GRAVITY
  renameme_ball.y = renameme_ball.y + renameme_ball.vy
  if renameme_ball.y >= CONST_FLOOR then
    renamefn_land()
  end
  renameme_ball.x = util.clamp(renameme_ball.x + 2, 0, 232)
end

function M.draw()
  cls(0)
  circ(renameme_ball.x, renameme_ball.y, 4, CONST_COLORS[renameme_bounces % 3 + 1])
  trace(keepme_frame, renameme_ball.x, renameme_ball.y, renameme_bounces)
end

return M
