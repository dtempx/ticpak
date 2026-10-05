-- title:  nominify_funcs
-- author: minify-option tests
-- desc:   sample cart 'nominify_funcs' for tests/options
-- site:   https://tic80.com
-- license: MIT License
-- version: 0.1
-- script: lua

-- nominify_funcs: function-level directives (spec R8h). Every keepfn_*
-- body must come out byte for byte, comments and spacing included; the
-- minfn_* functions are minified as usual.

local pinned_count = 0          -- read and written inside protected code
PINNED_LIMIT = 9                -- a constant read inside protected code
local renameme_local = 3        -- used only by unprotected code: renamed

local function keepfn_same_line(a, b) -- NOMINIFY: on the declaration line
  -- this comment stays
  local   sum   =   a + b    -- odd spacing stays too
  pinned_count = pinned_count + 1
  return sum
end

-- NOMINIFY: the comment block directly above the declaration
function keepfn_above(x)
  -- kept
  return x * PINNED_LIMIT
end

local function keepfn_closing(v)
  -- kept
  return v + pinned_count
end -- NOMINIFY: on the line that closes it

local keepfn_expr = function(t) -- NOMINIFY: a function expression
  return #t   -- kept
end

function minfn_below(x)
  -- NOMINIFY KEPT_BELOW: a block in the body, above a return: it protects
  -- nothing (the function is minified), but is kept itself
  return x - 2   -- this comment is removed
end

-- NOMINIFY here is followed by a blank line: it protects nothing

local function minfn_after_blank(v)
  -- this comment is removed
  return v - 1
end

local function keepfn_unused() -- NOMINIFY: kept although nothing calls it
  return "UNUSED_BUT_KEPT"
end

local function minfn_outer(n)
  local function keepfn_inner(k) -- NOMINIFY: a nested function
    -- kept
    return k * 2
  end
  -- removed with the outer function's other comments
  return keepfn_inner(n) + renameme_local
end

function TIC()
  local r = keepfn_same_line(1, 2) + keepfn_above(2) + keepfn_closing(3)
  r = r + keepfn_expr({1, 2, 3}) + minfn_after_blank(10) + minfn_outer(4) + minfn_below(5)
  trace(r, pinned_count, PINNED_LIMIT)
end

-- <TILES>
-- 001:2f8104fba08f6d3682da2bd8e369316bf60b7d9b3263896cf7460650a9bcc94f
-- 002:15dc3e72eec2df9d268ef50038b68ea8ddf8fff4cf9eab5c8acf590e1503bbf1
-- 017:6480df2f73bb47a41331fe204258ef046efee8f29b9b12888fdeb127715ab116
-- </TILES>

-- <SPRITES>
-- 000:da253c4ef242b054594c774d5a70c6ace0c47b85454c2101f133b117d792f215
-- 001:e33510d98e766808a21bb370bad1b400a2f0e828744d57cdf884916e3530534c
-- </SPRITES>

-- <MAP>
-- 000:fff6c4e0ad8a49bb70952d726cd441fbac828413432236ba575574fe34e6b4a828010fea1083ca3b44bfc043eb04f82f3c65ea8b98e170f851a069648189b6502b5b5f7fcb32d16e871f88b9db3d581a1231ed258b0289bcc239fe89701c479038430c8f628544306adffeae65374c7be8670d7c31abf8dc9bb1d599f73e5bdea2edf032fd10bb55f2c30b788cb0bd95fb106010f3dfaf66b436178d7bfb4b86166c1d022363fa5e607a6940093c66df2d5469d9c1e6697db1abbcdbd9486e504278e06911fc3ba490848a2b3079662d0ba6dc115779585bb97524e1321bbec87ddaec712dc3ea532366f70b511c09e3
-- 001:6f500fb74ecd7a63ce1698387ab98cdaeb63d827b12350a0d146038567360ac20b5e4d81c9f0994069340bb36bda3683ed3ab70d8350100a2e14889777a85127e3cfca4248717a0cba5e63a546425f7d0ee13a0afe72dc0f40e103225666f723b33f0a753f87a36d1a233b33c2c49e50705349dd2b2878db6a8b3c958d05ad90d96967f00d5e7dbfb66034e64fb87f472619c96593f86f71721dd88763ee7fe1db696f59995e781aeab479f3222cbf259170d10e9a18c057800e65e4850ff40773d5316c45f318269784b39f7639a0cf5cd7d0d0e1b14fefae532eeab7dfd684acf3614f64c098a0c49bb296f246d661
-- </MAP>

-- <WAVES>
-- 000:00e69e80b252ee165c0c762d5392ae65
-- 001:53c635e0316d2ea4bb5e4b2a9a92d3fb
-- </WAVES>

-- <SFX>
-- 000:e7c736d55c60d121ea234139006a5205fa18770ece72b038e69bcba057873df86b20887f9f4240a5fe54de76ca00ea937fd2b9a42a31b1bc6e0d7813c5b46a073acc
-- </SFX>

-- <PATTERNS>
-- 000:06d3531ddd2c56c2a6a18bd4ed96ee2a856f9ad2deff4f81398e093991b33297cef2ba7b5a0cbaabed418553627d94ae1865a2056f62976fc8485cfc375419a02eb9f9725578514b8d94107e1f370746418551f47ef48b7d4c3a36279f4a34aa845de591f33f3a70068843d6bf946ec120768d2a1a1a384b97d9109bdeccdb3f13573179a63618049a770d043118d51f6e133cb893ab7b2930a447d818a8e9dadc2c63629e8821463777a90d74bfe0103259737d84c35dbdcc97409366b4afe7
-- </PATTERNS>

-- <TRACKS>
-- 000:b5c2c656f4de62e6a4870ec0c61aa5625036eaeec122f78cc8a9b28340d4321ed33d49c6dccc10ebfbbd1306db692839e30c63
-- </TRACKS>

-- <PALETTE>
-- 000:e77a7ee280d6c2617b9979fe47440a21a573655793d4a768409f14d9aecb8e30bddc606e063f16ebe1f7d731372fbe3c
-- </PALETTE>

