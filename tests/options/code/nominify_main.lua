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
