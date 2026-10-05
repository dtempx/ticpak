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
