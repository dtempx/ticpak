-- markers: text that looks like an asset chunk tag but isn't one. Only a
-- `-- <NAME>` line at column 0 followed by nothing but comments starts the
-- asset sections; strings and indented or mid-line mentions must survive.
-- (A tag line at column 0 inside a long string would also fool TIC-80's own
-- loader, so the long string below indents its fake tags.)

local renameme_tag = "-- <TILES>"
local renameme_end = '-- </MAP>'
local renameme_long = [[
  -- <SPRITES>
  -- 000:00
  -- </SPRITES>
]]
-- a prose comment that mentions -- <PALETTE> mid-line
  -- <WAVES> indented, not at column 0

function TIC()
  trace(renameme_tag, renameme_end, #renameme_long)
end
