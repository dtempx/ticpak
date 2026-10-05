-- Names a no-minify directive keeps (spec R8g). (This block never names the
-- directive itself: it would be kept as a comment.)
--
--   keepme_*    marked by a comment block directly above, or a comment after
--               code on their declaring/assigning line: never renamed,
--               inlined or removed
--   renameme_*  unmarked: renamed (one has the word only inside a string,
--               one only as part of a longer word)

local keepme_speed = 1          -- tuning knob, NOMINIFY
keepme_lives = 3                --[[ nominify: read by a debugger ]]
local renameme_count = 0
local keepme_later
keepme_later = 0                -- NoMiNiFy on an assignment
local renameme_marker_in_string = "nominify"
local renameme_longer_word = 2  -- nominifying is not the word
-- NOMINIFY: the comment block directly above a local
-- (two lines long)
local keepme_above = 5
-- nominify: directly above a global's assignment
keepme_global_above = 6
local keepme_const = 7          -- NOMINIFY: a constant, still not inlined
local keepme_unused = 8         -- NOMINIFY: never read, still not removed
local keepme_table = {
  1, 2,
} -- NOMINIFY: on the closing line of the statement

function TIC()
  renameme_count = renameme_count + keepme_speed
  keepme_speed = keepme_speed + 1
  keepme_lives = keepme_lives + 1
  keepme_later = keepme_later + renameme_count
  for keepme_i = 1, 2 do        -- NOMINIFY: a for variable
    keepme_later = keepme_later + keepme_i
  end
  trace(renameme_count, keepme_speed, keepme_lives, keepme_later, renameme_marker_in_string)
  trace(renameme_longer_word, keepme_above, keepme_global_above, keepme_const, #keepme_table)
end
