-- title:  nominify_main
-- author: minify-option tests
-- desc:   sample cart 'nominify_main' for tests/options
-- site:   https://tic80.com
-- license: MIT License
-- version: 0.1
-- script: lua
-- NOMINIFY: this whole cart ships as written

-- nominify_main: the cart's top comment block (its metadata header, which
-- make_samples.py ends with a NOMINIFY line for this sample) turns
-- minification off for the whole cart: it comes out byte for byte.

local plain_counter = 0         -- would be renamed, but must not be

local function plain_step(v)
  -- this comment must survive every option
  return v + 1
end

function TIC()
  plain_counter = plain_step(plain_counter)
  trace(plain_counter)
end

-- <PALETTE>
-- 000:7bc4612476c0efecf6c2f708dfc3832cc31a72f6421f64ee9bd453abf694b927b709a781d8c9d5c35065930ca5d74ded
-- </PALETTE>

