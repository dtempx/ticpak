-- entry stub: the requires and the callbacks, nothing else. ticpak inlines
-- only the modules listed here, so every module is required by name.
require "constants"
require "util"
local game = require "game"

function TIC()
  game.update()
  game.draw()
end
