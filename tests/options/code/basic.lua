-- basic: a small game loop - UPPER_CASE constants, global and local state,
-- helper functions and the usual TIC-80 calls.
--
-- Marker names the tests look for:
--   CONST_*           inlined and removed by `constants`
--   renameme_*        shortened by `rename`
--   unused_helper_fn  removed by `extra` (never called)
--   DEAD_BRANCH       removed by `extra` (if false ... end)
--   ("sugar_marker")  becomes "sugar_marker" call sugar under `extra`

CONST_SPEED = 2          -- pixels per frame
CONST_LIMIT = 50
CONST_NAME = "hi"
CONST_HALF = 0.5
CONST_NEG = -3

renameme_score = 0       -- global state
renameme_player = {x = 10, y = 20}

local renameme_frames = 0

local function clamp(v, lo, hi)
  if v < lo then return lo end
  if v > hi then return hi end
  return v
end

local function unused_helper_fn(a)
  return a * 2
end

function BOOT()
  trace("boot " .. CONST_NAME)
end

function TIC()
  renameme_frames = renameme_frames + 1
  local renameme_dx = 0
  if btn(2) then renameme_dx = renameme_dx - CONST_SPEED end
  if btn(3) then renameme_dx = renameme_dx + CONST_SPEED end
  renameme_player.x = clamp(renameme_player.x + renameme_dx, 0, CONST_LIMIT)
  renameme_score = renameme_score + CONST_HALF * renameme_frames + CONST_NEG

  if false then trace("DEAD_BRANCH") end

  cls(0)
  spr(1, renameme_player.x, renameme_player.y, 0)
  map(0, 0, 30, 17)
  print("score " .. renameme_score, 2, 2, 12)
  trace("sugar_marker")
  for i = 1, 3 do
    rect(i * 8, 100, 6, 6, i)
  end
  trace(renameme_frames, renameme_player.x, renameme_score)
end
