local _, ns = ...

-- === Colour tags: what colour does the addon think each tile is? ===
--
-- Draws the computed main and accent bucket on every appearance in the
-- Transmogrifier, WITHOUT a filter being active. That last part is the point.
-- With a filter on you only ever see what the classifier let through, so a
-- wrong answer is invisible unless it happens to land in the bucket you picked.
-- Every classifier decision this project has argued about was found by noticing
-- one bad item in a filtered list, which is a terrible sampling method: it can
-- only find false positives, never false negatives, and never tells you what
-- share of a slot is wrong.
--
-- It also answers "is anything being left out entirely" directly. An appearance
-- with no colour data is hidden whenever a filter is active and is never
-- rolled, so it is invisible by construction -- exactly the thing you cannot
-- notice by browsing. Those tag as NO DATA, and toggling the overlay prints the
-- count for the current slot.
--
-- ON by default. Started as a development aid, kept for players because it
-- shows what a swatch will return before it is clicked. Players know these as
-- "swatches" (the file keeps its development name). Toggled by the Swatches
-- checkbox on the colour strip or:
--
--     /tmpalette swatches
--
-- Refresh is a throttled ticker rather than an event callback. The tiles are
-- POOLED and reused across pages and slots, so a tag written once is wrong as
-- soon as the pool hands that frame to a different appearance; the tag must be
-- re-derived from the frame's CURRENT element data, not cached. A ticker gets
-- that right for every cause of a change -- paging, slot changes, filter edits,
-- a search term -- without needing to enumerate them. It only runs while the
-- overlay is on and the frame is shown.
--
-- TILES ARE FOUND BY WALKING, not by naming a container. The list is a
-- PagedContentFrame (ic.PagedContent), not a ScrollBox -- a first attempt used
-- ScrollBox:ForEachFrame and silently tagged nothing, because that field does
-- not exist here. Rather than swap one guessed field name for another, this
-- looks for the property that is actually PROVEN about a tile: the right-click
-- menu code establishes that a tile answers GetElementData().appearanceInfo
-- .visualID. Any descendant that does is a tile; anything else gets descended
-- into. That survives Blizzard moving the container, which the paging code in
-- Core.lua has already been bitten by once.
--
-- The text goes on a CHILD FRAME with a raised frame level, not on a
-- FontString parented to the tile. A tile is a DressUpModel, and a model draws
-- its 3D content over its own regions -- text attached directly to it renders
-- behind the armour.

local REFRESH = 0.15
local MAX_DEPTH = 5

local itemsFrame
local ticker
local overlays = {}      -- tile -> overlay frame, so tiles are decorated once
local lastTileCount = 0
-- Held off for a moment by the capture tool (Capture.lua) so the chips are not
-- in the screenshot: they would be read as the item's own pixels.
local suspended = false

local function Enabled()
    return TransmogPaletteDB and TransmogPaletteDB.showColorTags and not suspended
end

-- Pooled tiles: resolve from the frame every time, never cache the result.
local function VisualIDOf(frame)
    if type(frame) ~= "table" or type(frame.GetElementData) ~= "function" then
        return nil
    end
    local ok, ed = pcall(frame.GetElementData, frame)
    if not ok or type(ed) ~= "table" then return nil end
    local info = ed.appearanceInfo
    return type(info) == "table" and info.visualID or nil
end

-- Every descendant that identifies an appearance. Stops descending at a tile:
-- a tile's own children are its artwork, never more tiles.
local function CollectTiles(root, out, depth)
    if not root or depth > MAX_DEPTH then return end
    local ok, kids = pcall(function() return { root:GetChildren() } end)
    if not ok then return end
    for _, kid in ipairs(kids) do
        if VisualIDOf(kid) then
            out[#out + 1] = kid
        else
            CollectTiles(kid, out, depth + 1)
        end
    end
end

local function Tiles()
    local out = {}
    if not itemsFrame then return out end
    -- PagedContent first because that is where they live today; the whole
    -- frame is the fallback so a Blizzard reshuffle degrades to slower rather
    -- than broken.
    CollectTiles(itemsFrame.PagedContent, out, 1)
    if #out == 0 then CollectTiles(itemsFrame, out, 1) end
    lastTileCount = #out
    return out
end

-- Bare colour chips, no border. Borders were tried and removed: at this size a
-- gold and a silver outline are two more high-contrast edges on a tile that is
-- already busy with armour art, and they compete with the colours they are
-- supposed to be framing. Main is simply the LEFT chip.
local SIZE, GAP = 13, 3

local function MakeChip(parent)
    local t = parent:CreateTexture(nil, "OVERLAY")
    t:SetSize(SIZE, SIZE)
    return t
end

local function SetChip(chip, r, g, b)
    if r then
        chip:SetColorTexture(r, g, b, 1)
        chip:Show()
    else
        chip:Hide()
    end
end

local function OverlayOf(tile)
    local o = overlays[tile]
    if o then return o end
    local ok, created = pcall(function()
        local f = CreateFrame("Frame", nil, tile)
        f:SetAllPoints(tile)
        -- Above the model, or the armour renders over the squares.
        f:SetFrameLevel((tile:GetFrameLevel() or 0) + 10)

        -- Main on the LEFT, accent on the right: reading order matches which
        -- one the filter actually matches on.
        f.main = MakeChip(f)
        f.main:SetPoint("TOPRIGHT", f, "TOPRIGHT", -(SIZE + GAP + 3), -3)
        f.accent = MakeChip(f)
        f.accent:SetPoint("TOPRIGHT", f, "TOPRIGHT", -3, -3)

        -- Sits exactly where the chips would be, because it is what an
        -- appearance has INSTEAD of them -- putting it below would read as an
        -- annotation on colours that aren't there.
        local fs = f:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
        fs:SetPoint("TOPRIGHT", f, "TOPRIGHT", -3, -3)
        fs:SetJustifyH("RIGHT")
        f.text = fs
        return f
    end)
    if not ok or not created then return nil end
    overlays[tile] = created
    return created
end

-- Returns the best and second-best matching swatches (Matching.lua) and a
-- status. The SAME scores the filter sorts by, so a tile's swatches say what
-- clicking those strip swatches would find it under. status is nil when
-- everything resolved.
local function DescribeVisual(visualID)
    if not visualID then return nil, nil, nil end
    if not ns.HasColorData or not ns.HasColorData(visualID) then
        return nil, nil, "no data"
    end
    local first, second = ns.TopSwatches(visualID)
    if not first then return nil, nil, "no data" end
    -- An override is a hand correction, so the squares are not showing what
    -- was computed. Saying so prevents reading a corrected item as evidence
    -- that the matching got it right.
    local status
    if ns.OverrideFor and ns.OverrideFor(visualID) then
        status = "fixed"
    end
    return first, second, status
end

local function SwatchRGB(sw)
    if not sw then return nil end
    return sw.r, sw.g, sw.bl
end

local function Refresh()
    if not Enabled() or not itemsFrame then return end
    for _, tile in ipairs(Tiles()) do
        local overlay = OverlayOf(tile)
        if overlay then
            local visualID = VisualIDOf(tile)
            if not visualID then
                overlay:Hide()
            else
                local first, second, status = DescribeVisual(visualID)
                SetChip(overlay.main, SwatchRGB(first))
                SetChip(overlay.accent, SwatchRGB(second))
                -- The label sits in the chip row only when it REPLACES the
                -- chips. FIXED annotates chips that are there, so it belongs
                -- under them -- sharing one anchor put it on top of them.
                overlay.text:ClearAllPoints()
                if status == "fixed" then
                    overlay.text:SetPoint("TOPRIGHT", overlay.accent, "BOTTOMRIGHT", 0, -2)
                    overlay.text:SetText("|cff44ff44FIXED|r")
                elseif status then
                    overlay.text:SetPoint("TOPRIGHT", overlay, "TOPRIGHT", -3, -3)
                    overlay.text:SetText("|cffff4444" .. status:upper() .. "|r")
                else
                    overlay.text:SetPoint("TOPRIGHT", overlay, "TOPRIGHT", -3, -3)
                    overlay.text:SetText("")
                end
                overlay:Show()
            end
        end
    end
end

local function Stop()
    if ticker then
        ticker:Cancel()
        ticker = nil
    end
    for _, overlay in pairs(overlays) do
        pcall(overlay.Hide, overlay)
    end
end

local function Start()
    if ticker then return end
    ticker = C_Timer.NewTicker(REFRESH, function()
        if not Enabled() or not itemsFrame or not itemsFrame:IsShown() then
            return
        end
        Refresh()
    end)
end

function ns.SuspendColorTags(on)
    suspended = on and true or false
    if suspended then
        for _, overlay in pairs(overlays) do pcall(overlay.Hide, overlay) end
    elseif Enabled() then
        Refresh()
    end
end

-- Every appearance tile currently on screen, as { visualID, left, bottom,
-- width, height } in UNSCALED screen units -- the frame's rect times its
-- effective scale -- so the capture script can map them onto a screenshot of
-- any resolution by proportion alone.
function ns.VisibleTileRects()
    local out = {}
    for _, tile in ipairs(Tiles()) do
        local vid = VisualIDOf(tile)
        if vid and tile:IsVisible() then
            local left, bottom, width, height = tile:GetRect()
            if left then
                local s = tile:GetEffectiveScale()
                out[#out + 1] = { vid, left * s, bottom * s, width * s, height * s }
            end
        end
    end
    return out
end

function ns.RegisterColorTags(ic)
    itemsFrame = ic
    if Enabled() then Start() end
end

-- Returns the new state, coverage for what is currently listed, and how many
-- tiles were found. The tile count matters: zero means the walk failed to find
-- the list, which looks exactly like "the overlay is broken" from the outside.
function ns.ToggleColorTags()
    TransmogPaletteDB.showColorTags = not TransmogPaletteDB.showColorTags
    if Enabled() then
        Start()
        Refresh()
    else
        Stop()
    end
    -- The checkbox on the colour strip shows the same setting, and either can
    -- change it, so whichever was not used has to be told.
    if ns.UpdateTagsCheckbox then ns.UpdateTagsCheckbox() end
    local withData, total = 0, 0
    if ns.GetCoverage then withData, total = ns.GetCoverage() end
    return Enabled(), withData, total, lastTileCount
end

-- Reports what the tile walk can actually see. Exists because the first version
-- of this file tagged nothing and gave no way to tell whether the cause was the
-- container, the element data or the font string -- the same class of problem
-- the paging code solved by probing rather than reasoning.
function ns.ProbeColorTags()
    if not itemsFrame then
        print("|cffff4444TransmogPalette:|r no items frame yet — open the Transmogrifier first.")
        return
    end
    print(("|cff44ff44TransmogPalette:|r itemsFrame=%s PagedContent=%s"):format(
        tostring(itemsFrame:GetName() or "<anon>"),
        itemsFrame.PagedContent and "yes" or "|cffff4444missing|r"))

    local tiles = Tiles()
    print(("  tiles found by walk: |cffffff00%d|r"):format(#tiles))
    if #tiles == 0 then
        local ok, kids = pcall(function() return { itemsFrame:GetChildren() } end)
        print(("  itemsFrame children: %d"):format(ok and #kids or -1))
        if ok then
            for i, kid in ipairs(kids) do
                if i > 8 then break end
                local okT, t = pcall(kid.GetObjectType, kid)
                print(("    [%d] %s name=%s GetElementData=%s"):format(
                    i, okT and t or "?", tostring(kid:GetName() or "<anon>"),
                    type(kid.GetElementData) == "function" and "yes" or "no"))
            end
        end
        return
    end

    for i, tile in ipairs(tiles) do
        if i > 5 then break end
        local vid = VisualIDOf(tile)
        local okT, t = pcall(tile.GetObjectType, tile)
        local first, second, status = DescribeVisual(vid)
        print(("    tile[%d] %s visualID=%s data=%s -> best=%s next=%s%s"):format(
            i, okT and t or "?", tostring(vid),
            (vid and ns.HasColorData and ns.HasColorData(vid)) and "yes" or "NO",
            first and first.key or "nil", second and second.key or "nil",
            status and (" [" .. status .. "]") or ""))
    end
end
