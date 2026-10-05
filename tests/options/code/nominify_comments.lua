-- nominify_comments: comments a no-minify directive keeps (spec R8i). One
-- that is not on or directly above a function or variable keeps its own
-- comment: every comment holding KEPT_ comes out under every option set,
-- GONE_ ones don't, and KEPT_UNLESS_EXTRA goes only with the unused code
-- around it. KEPT_1, after the header, starts the cart's code.

-- NOMINIFY KEPT_1: a block followed by a blank line

local renameme_a = 1
-- NOMINIFY KEPT_2: directly above a call
trace(renameme_a)

local renameme_t = {
  10, 20,
  -- NOMINIFY KEPT_3: between table fields
  30,
}

local function minfn_sum(t)
  local s = 0
  for i = 1, #t do s = s + t[i] end
  return s
  -- NOMINIFY KEPT_4: after a return
end

-- GONE_1: an ordinary comment
renameme_t.x = 5 -- NOMINIFY KEPT_5: after code that declares no variable

function TIC()
  trace(minfn_sum(renameme_t), renameme_t.x)
  trace(renameme_a, -- NOMINIFY KEPT_6: inside a call: moved after it
        2)
  if renameme_a > 0 then
    renameme_a = renameme_a + 1
    -- NOMINIFY KEPT_7: at the end of a block
  end
end

local function unused_helper_fn()
  -- NOMINIFY KEPT_UNLESS_EXTRA: removed with the unused function
  return 1
end
