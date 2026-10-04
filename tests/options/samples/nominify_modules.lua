-- title:  nominify_modules
-- author: minify-option tests
-- desc:   sample cart 'nominify_modules' for tests/options
-- site:   https://tic80.com
-- license: MIT License
-- version: 0.1
-- script: lua

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

-- <TILES>
-- 001:a4c123b1612dd272d1371c17149d439536b3216fdaeeb975729fae923d5a4fd1
-- </TILES>

-- <TILES1>
-- 000:2aabfe228f219e9cb0eb53f16947ccf25ec84d8dbc74254770f58904dba41ecc
-- 005:cc3fc1626e53a13043b026c48bbf33feff9243a8f506b40928b5b7a767c76fb0
-- </TILES1>

-- <MAP2>
-- 000:08f86bebb2737f6a6f0fb23c6f5da2cec255404e4fb440034d6608697a8d41bed440e50454f31af3176813e02ea68ef786e4d3cea27d26934b484e73cf575dcad6ba2b0aee0ca923732881584d8c4fa2815d2802827283e0ad84173581569969e58b081006f7e3dfc967a64cb14028d512c9791e558e08baa7196b50ac2f86702824c1c099724caf4941d4072014b3ce107f80e222f828767efc2f91624a8940f1f836f99eee3692f09e2e8c662248b483b7ffc050fec94dbca3a0aac36098b2cc2bd818319478da6bd0c621de49f145fda9988c79fc35526f7eaed46725a2a7b860dcd6c8a1f8b46287cced9041dff0
-- </MAP2>

-- <SPRITES7>
-- 003:2cee737443e210471948d33296c87009e8a7f770d9106fd287db7f1adbc60926
-- </SPRITES7>

-- <FLAGS>
-- 000:f6967e7893f57fd14c1604d115cea325a65e19cbae530282bd36cb9d21f6be6abf0d7c1c1e21862ab8a18a8902073fec8df4f50947aaeb26c57d21fa5d328263dfe574de739988b886e7577496a2c8773e130f7eb19731662b5e803b61ba4168160adb59261ff2d3c425c8d99d19bdd0b6cc60d5d32cbe54014c2b54b95523cf6941fa1c257c6f561c5cb347611a3ce9d97dcbee500fe7ee5fc324bdb2e1142a21c402364f9572b85a8e48f687ab165c58ac5831be38cb8cb4ba2e751989a01749ddb14f71010b93b7d946bf54074e3248c801bef750110c57513064d6d59291f0cde2e5738713a818d8962058765a6ca7cff00d796c25410335b400141212b6
-- </FLAGS>

-- <PALETTE>
-- 000:2c376631129f34369aad80b891baf90d0d3bf16295d06910bf3f5fb85967f532f3ab3cc2d0b698d5c7e41ba4ea5ee874
-- </PALETTE>

-- <PALETTE1>
-- 000:ae7689447ab57a683536c4499d863386ce10cd79e048c07dd7753eda83d7c58dfe0d5a0cf318656b3e6f0bade65c3b18
-- </PALETTE1>

