-- nominify: names a NOMINIFY comment keeps through `rename` (spec R8g).
--
--   keepme_*    marked on their declaring/assigning line: never renamed
--   renameme_*  unmarked: renamed (one has "nominify" only inside a string)

local keepme_speed = 1          -- tuning knob, NOMINIFY
keepme_lives = 3                --[[ nominify: read by a debugger ]]
local renameme_count = 0
local keepme_later
keepme_later = 0                -- NoMiNiFy on an assignment
local renameme_marker_in_string = "nominify"

function TIC()
  renameme_count = renameme_count + keepme_speed
  keepme_speed = keepme_speed + 1
  keepme_lives = keepme_lives + 1
  keepme_later = keepme_later + renameme_count
  trace(renameme_count, keepme_speed, keepme_lives, keepme_later, renameme_marker_in_string)
end
