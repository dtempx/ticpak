-- util: small helpers; `sign` is never used (removed by `extra`)

local M = {}

function M.clamp(v, lo, hi)
  if v < lo then return lo end
  if v > hi then return hi end
  return v
end

function M.sign(v)
  if v < 0 then return -1 end
  return 1
end

return M
