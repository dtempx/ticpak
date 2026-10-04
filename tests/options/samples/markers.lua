-- title:  markers
-- author: minify-option tests
-- desc:   sample cart 'markers' for tests/options
-- site:   https://tic80.com
-- license: MIT License
-- version: 0.1
-- script: lua

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

-- <PALETTE>
-- 000:8b0e7153bf7c3706d85c524e440066559a6656c90bd5482a90a29b9fa5ff5180bc0dbc0e15637ebb8e3b91d26ab4a829
-- </PALETTE>

