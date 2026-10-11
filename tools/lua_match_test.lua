-- Loads the addon's own Palette/ColorData/Swatches/Matching outside the game
-- and prints match scores, so tools/lua_match_test.py can check them against
-- the Python evaluation the palette was tuned with.
--
--   lua tools/lua_match_test.lua <addon dir> <visualID> [<visualID> ...]

local dir = arg[1]
-- WoW's Lua 5.1 has math.atan2; standalone 5.3+ folds it into math.atan.
math.atan2 = math.atan2 or math.atan

local ns = {}
for _, f in ipairs({ "Palette.lua", "ColorData.lua", "Swatches.lua", "Matching.lua" }) do
    local chunk = assert(loadfile(dir .. "/" .. f))
    chunk("TransmogPalette", ns)
end

for i = 2, #arg do
    local vid = tonumber(arg[i])
    local parts = {}
    for _, sw in ipairs(ns.MatchSwatches) do
        parts[#parts + 1] = ("%.5f"):format(ns.MatchScore(vid, sw.key) or -1)
    end
    print(vid .. " " .. table.concat(parts, " "))
end
