-- title:  bundle
-- author: minify-option tests
-- desc:   sample cart 'bundle' for tests/options
-- site:   https://tic80.com
-- license: MIT License
-- version: 0.1
-- script: lua
-- saveid: minitest_bundle

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

-- <TILES>
-- 001:122b598615dcbe810beacd557705a54b5edbbbe5ce7f8fbeebef7a58f99d96fb
-- </TILES>

-- <TILES1>
-- 000:2a0631187348761d11bb570232010b84550c17410b39af09e18c4f72a30e4cfa
-- 005:4a88d041814553e7177e2827b8d8041cd532733057360ee9c66dd01d53fb03b9
-- </TILES1>

-- <MAP2>
-- 000:b90d33960e1dfe62090b927f63bce4bc38332ac630f1f9be4b8ffdf9c75f8d232b54d22149c7ae5934d3a7855e7cb4ee0c5c1f8c8dfba276cc0aee530c6c63c686f40df85e62b0f2fae8e02b5c8415fce9409e0b1ce69f4f928a9a9c26c42917e78133cb6ab2aeb5fe9e4e68a537f6b5b4478cca8ac92b9cf58bef25ac403b5b2d0a7c9f4ba6f346a84db82a6771ab1452de84a3ac71cffa2fce5dce13e4352c9e083b7504d2ae1f72f4041160a74bf04373e616cac53465c69ad4d4ca933f89f87d430666c1408f174a163452e965a82dd1e93806da8c6d45eebcf86fe6fa925bf749693006a1a8ae2df094645c2e82
-- </MAP2>

-- <SPRITES7>
-- 003:ff74976acd761874cd3eccfc96771201cdc783bbf2e7800f1446a7149324d419
-- </SPRITES7>

-- <FLAGS>
-- 000:8f1ba3b3bb8f9401ad0b12ddd75510b590177c2b3277630c2871cd44d4eb15ede5f4b40854d8efe6dd87b1c0d90f887eebe75e9bd37c3dee2cebb5475def5d8ac98a0c16e330baac5a2fc7e30b09f410acf0f67a5a9cfe826b7bb5776e7c8650cfb565f046602e658c00b391bfc32e54e284f299062d459e61ae147b936470a383b24b4d6900a4214fdbf99243024b494277a25d6d1adfb5314c4d7832562a477ece3a71b3c038b7ad714545c439de03d0316d06ca45888799dffc9c5d9eda208de2f856b376d46c529e42b571d1c975c76788850c11f6a91ea5e16b8e881a0d75cf4d9251d2400b6fda3026004098300b83c5d0765d183771675053679a2647
-- </FLAGS>

-- <PALETTE>
-- 000:3bf566c90279b99192f4b9dd35742e24f04c6fb4d63aa9d478fa0103691e7672103c3dd005367288359625003ee007a2
-- </PALETTE>

-- <PALETTE1>
-- 000:783562d8f384ac776fe3fca1e1de7d1c83e99d7573084cd141161855fb2d53d97068176ffe019d6d3ee5594350a18ca4
-- </PALETTE1>

