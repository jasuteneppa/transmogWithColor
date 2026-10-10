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
--     /tmpalette capture sweep    page 1 of every general swatch in every
--                                 slot, as a player sees it (see Sweep)
--     /tmpalette capture stop     abandon a running sweep
--
-- Screenshots must be PNG -- JPEG smears colour at exactly the edges this
-- measures:  /console screenshotFormat png

local pending          -- the record being captured, until the screenshot lands
local pendingDone      -- called with ok once that record is settled
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
    local done = pendingDone
    pendingDone = nil
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
    if done then done(ok) end
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

-- meta, if given, is stored on the record as `sweep`; onDone(ok) runs once the
-- screenshot has landed or failed (not at all if nothing was captured).
function ns.CapturePage(meta, onDone)
    if pending then return false end
    if not ns.VisibleTileRects then
        print("|cffff4444TransmogPalette:|r capture needs ColorTags.lua.")
        return false
    end
    local tiles = ns.VisibleTileRects()
    if #tiles == 0 then
        if not meta then
            print("|cffff4444TransmogPalette:|r no appearance tiles on screen. Open a gear slot first.")
        end
        return false
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
        sweep = meta,
    }
    pendingDone = onDone

    SetOverlaysHidden(true)
    -- One frame for the hidden overlays to actually leave the screen.
    C_Timer.After(0.1, function()
        -- Armed BEFORE the screenshot, so a fast SCREENSHOT_SUCCEEDED can
        -- cancel it. If neither event arrives, never leave the UI hidden.
        restoreTimer = C_Timer.NewTimer(3, function() Finish(false) end)
        Screenshot()
    end)
    return true
end

-- === Sweep: what each filter's first page looks like ===
--
-- The calibration pages above are whatever the player happened to open, ~110
-- appearances a slot. What a filter is judged on is its FIRST PAGE out of
-- thousands, and only the game can show that. So: for each slot, for each
-- general swatch, set that one swatch as the whole filter, go to page 1, and
-- capture it. Each record carries { slot, filter, matched } so the tools know
-- what was asked for. The player's own filter is put back afterwards.
--
-- Head is left out (the face shows through helms). Main hand shows whichever
-- weapon shape is displayed, as it does for the player.
local SWEEP_SLOTS = { 3, 5, 6, 7, 8, 9, 10, 15, 16 }
local SLOT_SETTLE = 1.5    -- seconds for a newly selected slot's list to build
local PAGE_SETTLE = 2.0    -- seconds for the tiles' models to finish loading

local sweep

local function EndSweep(reason)
    if not sweep then return end
    local s = sweep
    sweep = nil
    if ns.SetFilterForCapture then ns.SetFilterForCapture(s.savedPrimary, s.savedAccent) end
    print(("|cff44ff44TransmogPalette:|r sweep %s: %d pages captured, %d with no matches. |cffffff00/reload|r to write them to disk."):format(
        reason, s.captured, s.empty))
end

local SweepStep

local function After(seconds, fn)
    local token = sweep
    C_Timer.After(seconds, function()
        if sweep and sweep == token then fn() end
    end)
end

SweepStep = function()
    if not (TransmogFrame and TransmogFrame:IsShown()) then return EndSweep("stopped (Transmogrifier closed)") end
    local s = sweep
    s.g = s.g + 1
    if s.g > #ns.MatchGroups or s.si == 0 then
        s.si, s.g = s.si + 1, 0
        local invSlot = SWEEP_SLOTS[s.si]
        if not invSlot then return EndSweep("done") end
        ns.SetFilterForCapture({}, nil)
        if not ns.SelectTransmogSlot(invSlot) then
            print(("|cffff8800TransmogPalette:|r slot %d has no button here; skipped."):format(invSlot))
            s.g = #ns.MatchGroups
        end
        return After(SLOT_SETTLE, SweepStep)
    end
    local g = ns.MatchGroups[s.g]
    ns.SetFilterForCapture({ [g.key] = { key = g.key } }, nil)
    ns.ResetTransmogPage()
    After(PAGE_SETTLE, function()
        local meta = { slot = SWEEP_SLOTS[s.si], filter = g.key, matched = ns.LastFilteredCount() or 0,
            matcher = ns.MatchConstants.version or "v1" }
        local started = meta.matched > 0 and ns.CapturePage(meta, function(ok)
            if ok then s.captured = s.captured + 1 end
            After(0.3, SweepStep)
        end)
        if not started then
            s.empty = s.empty + 1
            local db = TransmogPaletteDB
            db.sweepEmpty = db.sweepEmpty or {}
            table.insert(db.sweepEmpty, meta)
            SweepStep()
        end
    end)
end

local function StartSweep()
    if sweep then print("|cffff8800TransmogPalette:|r a sweep is already running."); return end
    if not (TransmogFrame and TransmogFrame:IsShown()) then
        print("|cffff4444TransmogPalette:|r open the Transmogrifier first.")
        return
    end
    sweep = {
        si = 0, g = 0, captured = 0, empty = 0,
        savedPrimary = ns.state.primaryColors, savedAccent = ns.state.accentColor,
    }
    print(("|cff44ff44TransmogPalette:|r sweeping %d slots x %d swatches, about %d minutes. Don't touch the Transmogrifier until it says done."):format(
        #SWEEP_SLOTS, #ns.MatchGroups, math.ceil(#SWEEP_SLOTS * (SLOT_SETTLE + #ns.MatchGroups * (PAGE_SETTLE + 1)) / 60)))
    SweepStep()
end

function ns.CaptureCommand(rest)
    rest = (rest or ""):lower()
    local db = TransmogPaletteDB
    if rest:match("^clear") then
        db.captures = nil
        db.sweepEmpty = nil
        print("|cff44ff44TransmogPalette:|r capture records cleared (screenshot files are untouched).")
        return
    end
    if rest:match("^sweep") then return StartSweep() end
    if rest:match("^stop") then return EndSweep("stopped") end
    if rest:match("^status") then
        print(("|cff44ff44TransmogPalette:|r %d pages, %d tiles captured. /reload to write them to disk."):format(
            #(db.captures or {}), ns.CaptureTileCount()))
        return
    end
    ns.CapturePage()
end
