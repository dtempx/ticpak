-- title:  basic_crlf
-- author: minify-option tests
-- desc:   sample cart 'basic_crlf' for tests/options
-- site:   https://tic80.com
-- license: MIT License
-- version: 0.1
-- script: lua

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

-- <TILES>
-- 001:4283fefc63f0cd0e873a0000c6d07ef7b77e90d3593ad699fc1f7cd5bb2e35cb
-- 002:f0f19c557067cbbe80c46d1fb6dfbdb0ae0755281220e087835b92558589eaff
-- 017:309cad68386d070c415ed7e70cad19461922995d84016e51c6b36d6f3c9f0ac9
-- </TILES>

-- <SPRITES>
-- 000:056a4ad683cbf721245568a8baa397f43a1d2c44a3c2728b93e8319002d3167d
-- 001:53e5753dc98fa36a1009aecac22ae386fb856967b282e2a7c91a5a97a327707c
-- </SPRITES>

-- <MAP>
-- 000:2822009bff43a25544a9394641a659d51782ed8ee0ca58f0d01b44488cc527f05ae77aff7da8712b56999b5e23c548d61fcbc512838242e7cdc5ae4f63dd3987c06e007865946898e5bfd36c693030942b9dba03eeb9caf3cc6086ed95e6b0cdca2f790d4c8520b8d94e8f5e183d2b2e0552c89667a822be1598b7cc5f8a7870cad78625e48e544eb9c7369237caf3511061fea83537c7fec5779ec6e8af362100fac96c5400c41c842e90114183d260f486eca887715bd1bd6d282853416d112fb3a141e4ce0828a291c18a48c393d76aacf34e0956bca3db4219ad9ab8a034aaa2e8febc2141f87abbc9ea50487435
-- 001:d13836822265d0bf976f7deb6f28d60cf2cd1be069039a9dd9e94e4580d1bdc90220c8e8bface3fb4d4058b49d89d8daf6fcd2246470384f3c502d16db13d3885f162c3e9fc3f34c658d9f6af30b81e937887d4486d14d88f98f6fbf7a55e41a46affa344872153769da0097278a8c03ab43841b2239a781b024cb73a80a3b48c2fdc979413576d80888f4c3b2b09e44246fab954cec3489004c3e0dd8bdce13f10134b8bf773b531adb81ddcb9ae741a35fa30f6c5c737aa7efbf6dec3f8440cd3025ec944380ec7c07d55a7255c06d71627ce31c23f17009e8d54aed5cc6f8b48852ba4888bc8e04487626d74ec622
-- </MAP>

-- <WAVES>
-- 000:410ccd4427c496cb5794bf9296e093be
-- 001:811a5433d76c36c48036cf78157d8dc8
-- </WAVES>

-- <SFX>
-- 000:f3450e1f6ca7321de656cb67b2a1e1549f12c2c9c8bf1f0d9a482bdc03103aab1b2f2ea05ab6443cadba8b1278c92258d24987638f1962aa941eb10ad51d5673438e
-- </SFX>

-- <PATTERNS>
-- 000:61beab700f15810725166e97fbac26569dfb0f03daa2d6ffef589c88901eeb7e6fa4cd13b0819c0aa9162a3249da705b99cde26d71777cc649b09ef540bdafa398d092f378db71354912601d02101aa006f6898756c17e1aad30525675931a42e4719b12e675316132798d7186abbecc2d7fa5372d89abdebbacf0b4959445e445287ba58f92d4be34a25f116bbbba35c186179ac7b17906347b845729def5b6d286744605fb51b2762e6a506af11bfb4f2a9a2fad282a05a7a889fd095913dd
-- </PATTERNS>

-- <TRACKS>
-- 000:68bf985a4b3cb6ce4f717221ffa5fc0ce5b1bbe792eb654e1ba5ff071e56ce3a845a4597dee9596940a3dc5eeeb61233c4ec5f
-- </TRACKS>

-- <PALETTE>
-- 000:e16efc9b5850127eaea3c1e8dea35cdf4a4b4676e433d1e4ba8c0cfe99ca953f5e4e33aafaaeafc657671a1ad0bbbd69
-- </PALETTE>

