-- title:  basic
-- author: minify-option tests
-- desc:   sample cart 'basic' for tests/options
-- site:   https://tic80.com
-- license: MIT License
-- version: 0.1
-- script: lua
-- saveid: minitest_basic

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
-- 001:cd18fc9fb6494384932af3bda6fe8102c0fa7a26774e22af3993a69e2ca79565
-- 002:18f224412c876d8efb2a3fa670837b5ad1347120363c2b310653f610d382729b
-- 017:d51e13c68bf56155a83e50fd9bc840e2a1847fb9b49cd206a577ecd1cd15e285
-- </TILES>

-- <SPRITES>
-- 000:ef01fa9e1d6240cda060036369853fc208e384b34801168ab1fedb56c90448aa
-- 001:b2a118549bc493f719529ca9d33ffaa3f3fd19a45c222671c03c9ef6d2b785d6
-- </SPRITES>

-- <MAP>
-- 000:b320e63fc8616436ecb43f4cdfaff670aaa1484c9f221274190ea54ebc122d69dfc700598a2f89dcc15479a11fd4f24bd1ece13f4014a3b6cf31ea394c9361ceb6eb211f80672d934dd23d23d40edd0fa82b23b0bb507b24606309b0745e3fb8406baf99a52395c447a7759bd140c224d9d4d9b27eb1cd0dae6b9f253834ec5dd57ea4be2f690ee069394df2f7c8038108cce38b9621289a3752d99463dc89eb4533cce49bfd6ffaf1e94f160bfc022c0b1308974963deac5add4e4a465ebcdfc76e61c1725b157929bde1def8f6a81115b09042d7c7e6a32aaea8016b26b66899c8fb71920efe1dfee322734d6e2dc1
-- 001:57f748bad3969ee8870335d7690d13c83b797729a7bf9540ab04c45246f6747cb4f30bfe9075ffa284c6a9c161a7ae78b590b14b0f107107a21bd46ed4b95adc0d8e13dc50442a7570552d3e418ac01f2b94e7b5ca8fc099f181ec3cbf1081896ac863a7b54a014bb99afcd5041e4a0f862d855253cd8990d88aa6d404cbe1d70b56bf07785d2e7e365e2dc88dba290f086ccdc1eb48a0cf412bb0263f1a0ac48d44c91544f11c5b225868a88e4e4151a26e7e5a4f12a023dbeacb34a0540a61d19c15b2d1eb89ed50e86c2b330b05c0aeff21c8032ab3f14910ca545557a0fc1779a57b75deb4c050c5400a011344c0
-- </MAP>

-- <WAVES>
-- 000:dda74b6c24db3dd7fc7c7fc288b0f781
-- 001:ac314c0dcd3ee55afd593bb4bf1685a9
-- </WAVES>

-- <SFX>
-- 000:c19d1d8c6b443b50dce22d45465704fb9a3d85aa4c97cbcf9dd344036385c2103bfa3eb8f752505d6ec804c5e1c2ca7e1f38fcf857b594e22fcd28f7394b3414601c
-- </SFX>

-- <PATTERNS>
-- 000:f3fba3077f9870fba229d7bc4796fb9c43cbf7bbd8bc93f93e4b75af73ccee7c9f7a02fac7d11d286a535b0710c04362e60d2577dcf0d6c180bbae428338044c6a6d33f3ef5ea4d8c2a7e7bfd0e0ce7d78ff47e9bf4269314a1a5ec6df65c1a6a5d4f6e17fa601147e73d9af65bbeceae24734ce6b10c62dd604f9c22f06db92070b4e83e87cca78214af2fdac03d4403d7188c3b9b61a05f08a4b3d28324f17b3657c6eb58b66ea4802a9a12093586be2dd32ea597d910082aa917481cd878a
-- </PATTERNS>

-- <TRACKS>
-- 000:fe3db517fc0729354e0bd37f98cdf15b67479458057d5745790e61d5cc6cf3420207ce8dbc82576112e7e4904bbb9840f6caf9
-- </TRACKS>

-- <PALETTE>
-- 000:e4f9abccc976d6854fa8d9e168e206380655b8000597cfbb2d30508b6c6a55f4d701d142d9a61a4a8ffa82e538ced5d4
-- </PALETTE>

