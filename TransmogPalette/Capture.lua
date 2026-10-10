local _, ns = ...

-- === Screenshot capture: what does each appearance look like ON SCREEN? ===
--
-- Development tool, not advertised to players.
--
-- The colours in ColorData.lua come from texture files, and textures are much
-- darker than the lit model the Transmogrifier draws: the median main colour
-- sits at HSV value 0.35-0.5. Any colour NAMING applied to those numbers names
-- the wrong colour -- a crowd-sourced namer files 45% of the game as brown,
-- because a dark orange really is brown. The fix needs the relationship
-- between texture colour and on-screen colour, and that has to be measured,
-- not guessed.
--
-- So: hide our own overlays, record where every appearance tile is, and take
-- a real screenshot. tools/capture_calibrate.py cuts the tiles back out and
-- compares. Every tile is an answer about what the player sees, with no human
-- judgement in it.
--
--     /tmpalette capture          one page: record tiles + screenshot
--     /tmpalette capture status   how many pages and tiles so far
--     /tmpalette capture clear    forget them (screenshots stay on disk)
--
-- Screenshots must be PNG -- JPEG smears colour at exactly the edges this
-- measures:  /console screenshotFormat png

local pending          -- the record being captured, until the screenshot lands
local restoreTimer

local function SetOverlaysHidden(hidden)
    if ns.SuspendColorTags then ns.SuspendColorTags(hidden) end
    for _, panel in ipairs(ns.panels or {}) do
        if hidden then
            panel.wasShown = panel:IsShown()
            panel:Hide()
        elseif panel.wasShown then
            panel.wasShown = nil
            -- The strip follows the item list; if that closed meanwhile, the
            -- strip must stay hidden with it.
            if not panel.host or panel.host:IsVisible() then panel:Show() end
        end
    end
end

local function Finish(ok)
    if restoreTimer then restoreTimer:Cancel(); restoreTimer = nil end
    SetOverlaysHidden(false)
    if not pending then return end
    if ok then
        local db = TransmogPaletteDB
        db.captures = db.captures or {}
        table.insert(db.captures, pending)
        print(("|cff44ff44TransmogPalette:|r captured %d tiles (page %d, %d tiles total)."):format(
            #pending.tiles, #db.captures, ns.CaptureTileCount()))
    else
        print("|cffff4444TransmogPalette:|r screenshot failed; nothing recorded.")
    end
    pending = nil
end

local events = CreateFrame("Frame")
events:RegisterEvent("SCREENSHOT_SUCCEEDED")
events:RegisterEvent("SCREENSHOT_FAILED")
events:SetScript("OnEvent", function(_, event)
    if pending then Finish(event == "SCREENSHOT_SUCCEEDED") end
end)

function ns.CaptureTileCount()
    local n = 0
    for _, c in ipairs(TransmogPaletteDB.captures or {}) do n = n + #c.tiles end
    return n
end

function ns.CapturePage()
    if pending then return end
    if not ns.VisibleTileRects then
        print("|cffff4444TransmogPalette:|r capture needs ColorTags.lua.")
        return
    end
    local tiles = ns.VisibleTileRects()
    if #tiles == 0 then
        print("|cffff4444TransmogPalette:|r no appearance tiles on screen. Open a gear slot first.")
        return
    end

    local uiScale = UIParent:GetEffectiveScale()
    local physW, physH = GetPhysicalScreenSize()
    pending = {
        -- WoW names screenshots WoWScrnShot_MMDDYY_HHMMSS; the script matches
        -- on this, allowing a second or two of drift.
        stamp = date("%m%d%y_%H%M%S"),
        time = time(),
        screen = { GetScreenWidth() * uiScale, GetScreenHeight() * uiScale },
        physical = { physW, physH },
        tiles = tiles,
    }

    SetOverlaysHidden(true)
    -- One frame for the hidden overlays to actually leave the screen.
    C_Timer.After(0.1, function()
        -- Armed BEFORE the screenshot, so a fast SCREENSHOT_SUCCEEDED can
        -- cancel it. If neither event arrives, never leave the UI hidden.
        restoreTimer = C_Timer.NewTimer(3, function() Finish(false) end)
        Screenshot()
    end)
end

function ns.CaptureCommand(rest)
    rest = (rest or ""):lower()
    local db = TransmogPaletteDB
    if rest:match("^clear") then
        db.captures = nil
        print("|cff44ff44TransmogPalette:|r capture records cleared (screenshot files are untouched).")
        return
    end
    if rest:match("^status") then
        print(("|cff44ff44TransmogPalette:|r %d pages, %d tiles captured. /reload to write them to disk."):format(
            #(db.captures or {}), ns.CaptureTileCount()))
        return
    end
    ns.CapturePage()
end
