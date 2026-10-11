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
--     /tmpalette capture stop     abandon a running sweep or journal run
--     /tmpalette capture journal  every appearance in Collections >
--                                 Appearances, every class (see Journal)
--     /tmpalette capture journal class  the class picked in the journal only;
--                                 resumable -- captured items are skipped
--     /tmpalette capture journal test   two pages of each slot, current class
--     /tmpalette capture journal reset  forget which items the journal run
--                                 has captured (keeps every captured page)
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
-- tiles, if given, replaces the Transmogrifier tile walk (journal capture).
function ns.CapturePage(meta, onDone, tiles)
    if pending then return false end
    if not tiles and not ns.VisibleTileRects then
        print("|cffff4444TransmogPalette:|r capture needs ColorTags.lua.")
        return false
    end
    tiles = tiles or ns.VisibleTileRects()
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
    if ns.SetFilterForCapture then ns.SetFilterForCapture(s.savedPrimary, s.savedAccent, s.savedExclude) end
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
        savedExclude = ns.state.excludeColors,
    }
    print(("|cff44ff44TransmogPalette:|r sweeping %d slots x %d swatches, about %d minutes. Don't touch the Transmogrifier until it says done."):format(
        #SWEEP_SLOTS, #ns.MatchGroups, math.ceil(#SWEEP_SLOTS * (SLOT_SETTLE + #ns.MatchGroups * (PAGE_SETTLE + 1)) / 60)))
    SweepStep()
end

-- === Journal: every appearance in the game, as a lit model ===
--
-- Colour naming learned from screen pixels (and CLIP) needs a picture of
-- EVERY appearance, and only Collections > Appearances can show the whole
-- game: uncollected items are drawn there too, and the class dropdown reaches
-- every armour type and class-only gear. So: for each class, each slot (each
-- weapon type), each page, screenshot the grid. Appearances already captured
-- are skipped -- their visualID is known before the models finish loading,
-- so a page with nothing new costs no screenshot and no wait.
--
-- Changes while capturing, all undone afterwards:
--   - the tile border is hidden. The uncollected border (a dark vignette) is
--     the only difference Blizzard draws between collected and uncollected --
--     the model is identical, see Blizzard_Wardrobe.lua UpdateItems -- and the
--     collected border darkens the edges too, so neither is drawn.
--   - Collections is scaled up by JOURNAL_SCALE: at the default scale a tile
--     is 97 x 130 px on a 1440p screen, against 125 x 165 in the
--     Transmogrifier, whose tiles the colour naming was measured on.
--   - each tile's black backdrop becomes pure magenta, a colour no armour
--     uses, so the tools can cut the item out exactly -- black items included,
--     which vanish against black. The tools put it back on black for CLIP.
-- Tiles Blizzard greys out (slot not allowed) are flagged so the tools can
-- drop them. Keep the mouse off the grid: hover draws a highlight.
local JOURNAL_SLOTS = { "HEADSLOT", "SHOULDERSLOT", "BACKSLOT", "CHESTSLOT", "SHIRTSLOT", "TABARDSLOT",
    "WRISTSLOT", "HANDSSLOT", "WAISTSLOT", "LEGSSLOT", "FEETSLOT", "MAINHANDSLOT", "SECONDARYHANDSLOT" }
local JOURNAL_SETTLE = 1.5   -- seconds for a page's models to load
-- The first page of a slot loads slower, and the very first after the window
-- is rescaled slower still: a test run's whole first slot came out blank.
local JOURNAL_SLOT_SETTLE = 3.0
local JOURNAL_WARMUP = 5.0
local JOURNAL_SCALE = 1.3    -- capped so the window still fits the screen
local KEY_R, KEY_G, KEY_B = 1, 0, 1

local journal

-- Core.lua leaves the journal unfiltered while this runs.
function ns.IsJournalCapturing()
    return journal ~= nil
end

local function JournalFrames()
    local wc = WardrobeCollectionFrame
    local items = wc and wc.ItemsCollectionFrame
    if not (items and items:IsVisible() and items.Models and items.PagingFrame) then return end
    return wc, items
end

-- The template's unnamed black BACKGROUND texture behind each model.
local function Backdrop(model)
    if model.tpBackdrop == nil then
        model.tpBackdrop = false
        for _, r in ipairs({ model:GetRegions() }) do
            if r:GetObjectType() == "Texture" and r:GetDrawLayer() == "BACKGROUND" then
                model.tpBackdrop = r
                break
            end
        end
    end
    return model.tpBackdrop or nil
end

-- Makes the visible tiles capture-clean and returns their records.
local function PrepareJournalTiles(items)
    local out = {}
    for _, model in ipairs(items.Models) do
        local info = model:IsShown() and model.visualInfo
        if info and info.visualID and not info.isHideVisual then
            model.Border:Hide()
            local bg = Backdrop(model)
            if bg then bg:SetColorTexture(KEY_R, KEY_G, KEY_B) end
            model.NewString:Hide()
            model.NewGlow:Hide()
            if model.Favorite and model.Favorite.Icon then model.Favorite.Icon:Hide() end
            local left, bottom, width, height = model:GetRect()
            if left then
                local sc = model:GetEffectiveScale()
                -- 6th / 7th: greyed out by Blizzard, collected (1/0). Positional,
                -- because the tools' SavedVariables reader keeps either a table's
                -- list part or its keys, not both.
                out[#out + 1] = { info.visualID, left * sc, bottom * sc, width * sc, height * sc,
                    model.SlotInvalidTexture:IsShown() and 1 or 0, info.isCollected and 1 or 0 }
            end
        end
    end
    return out
end

local function RestoreJournalTiles(items)
    for _, model in ipairs(items and items.Models or {}) do
        local bg = Backdrop(model)
        if bg then bg:SetColorTexture(0, 0, 0) end
        model.Border:Show()
    end
    -- Blizzard redraws borders, NEW tags and favourites from its own state.
    if items and items:IsVisible() then items:UpdateItems() end
end

function ns.JournalSeenCount()
    local n = 0
    for _ in pairs(TransmogPaletteDB.journalSeen or {}) do n = n + 1 end
    return n
end

local function EndJournal(reason)
    if not journal then return end
    local j = journal
    journal = nil
    if ns.SyncColorPanelVisibility then ns.SyncColorPanelVisibility() end
    local wc, items = JournalFrames()
    RestoreJournalTiles(items)
    C_TransmogCollection.SetCollectedShown(j.saved.collected)
    C_TransmogCollection.SetUncollectedShown(j.saved.uncollected)
    for i, on in pairs(j.saved.sources) do C_TransmogCollection.SetSourceTypeFilter(i, on) end
    if wc and j.saved.class then wc.ClassDropdown:SetClassFilter(j.saved.class) end
    if CollectionsJournal and j.saved.scale then
        CollectionsJournal:SetScale(j.saved.scale)
        if wc then wc:RefreshCameras() end
    end
    print(("|cff44ff44TransmogPalette:|r journal capture %s: %d pages screenshotted, %d new appearances (%d known in all). |cffffff00/reload|r to write them to disk."):format(
        reason, j.shots, j.new, ns.JournalSeenCount()))
end

local function JAfter(seconds, fn)
    local token = journal
    C_Timer.After(seconds, function()
        if journal and journal == token then fn() end
    end)
end

-- The work list: { class, slot, category } for every class x slot; the two
-- weapon slots once per weapon category (invalid ones are skipped as they come).
local function BuildJournalPlan(mode)
    local classes = {}
    if mode ~= "all" then
        classes[1] = C_TransmogCollection.GetClassFilter()
    else
        for classID = 1, GetNumClasses() do
            if C_CreatureInfo.GetClassInfo(classID) then classes[#classes + 1] = classID end
        end
    end
    local plan = {}
    for _, classID in ipairs(classes) do
        for _, slotName in ipairs(JOURNAL_SLOTS) do
            if slotName == "MAINHANDSLOT" or slotName == "SECONDARYHANDSLOT" then
                for category = FIRST_TRANSMOG_COLLECTION_WEAPON_TYPE, LAST_TRANSMOG_COLLECTION_WEAPON_TYPE do
                    plan[#plan + 1] = { class = classID, slot = slotName, category = category }
                end
            else
                plan[#plan + 1] = { class = classID, slot = slotName }
            end
        end
    end
    return plan
end

local JournalStep

local function JournalPage()
    local j = journal
    local _, items = JournalFrames()
    if not items then return EndJournal("stopped (journal closed)") end
    if j.page > items.PagingFrame:GetMaxPages() or (j.test and j.page > 2) then return JournalStep() end
    items.PagingFrame:SetCurrentPage(j.page, true)
    local seen = TransmogPaletteDB.journalSeen
    local fresh = false
    for _, model in ipairs(items.Models) do
        local info = model:IsShown() and model.visualInfo
        if info and info.visualID and not info.isHideVisual and not seen[info.visualID] then fresh = true end
    end
    if not fresh then
        j.page = j.page + 1
        return JournalPage()     -- nothing new here: no wait, no screenshot
    end
    JAfter(j.page == 1 and JOURNAL_SLOT_SETTLE or JOURNAL_SETTLE, function()
        GameTooltip:Hide()
        local tiles = PrepareJournalTiles(items)
        local cur = j.plan[j.i]
        local meta = { journal = true, class = cur.class, slot = cur.slot, category = cur.category,
            page = j.page, key = "magenta" }
        local started = ns.CapturePage(meta, function(ok)
            if ok then
                j.shots = j.shots + 1
                for _, t in ipairs(tiles) do
                    if t[6] == 0 and not seen[t[1]] then
                        seen[t[1]] = true
                        j.new = j.new + 1
                    end
                end
            end
            j.page = j.page + 1
            JAfter(0.2, JournalPage)
        end, tiles)
        if not started then
            j.page = j.page + 1
            JournalPage()
        end
    end)
end

JournalStep = function()
    local j = journal
    local wc, items = JournalFrames()
    if not items then return EndJournal("stopped (journal closed)") end
    j.i = j.i + 1
    local cur = j.plan[j.i]
    if not cur then return EndJournal("done") end
    if cur.class ~= j.class then
        j.class = cur.class
        wc.ClassDropdown:SetClassFilter(cur.class)
        local info = C_CreatureInfo.GetClassInfo(cur.class)
        print(("|cff44ff44TransmogPalette:|r journal: %s (step %d/%d, %d pages so far)."):format(
            info and info.className or cur.class, j.i, #j.plan, j.shots))
    end
    local loc = TransmogUtil.GetTransmogLocation(cur.slot, Enum.TransmogType.Appearance, false)
    if cur.category then
        local _, isWeapon, _, canMainHand, canOffHand = C_TransmogCollection.GetCategoryInfo(cur.category)
        local ok = isWeapon and ((loc:IsMainHand() and canMainHand) or (loc:IsOffHand() and canOffHand))
        if not ok then return JournalStep() end
    end
    items:SetActiveSlot(loc, cur.category)
    if cur.category and items:GetActiveCategory() ~= cur.category then return JournalStep() end
    j.page = 1
    JAfter(0.5, JournalPage)
end

-- mode: "all" (every class), "class" (the class picked in the dropdown, every
-- page), "test" (that class, two pages per slot).
local function StartJournal(mode)
    if journal or sweep then
        print("|cffff8800TransmogPalette:|r a capture is already running.")
        return
    end
    local wc, items = JournalFrames()
    if not items then
        print("|cffff4444TransmogPalette:|r open Collections > Appearances > Items first.")
        return
    end
    if wc.SearchBox and wc.SearchBox:GetText() ~= "" then
        print("|cffff4444TransmogPalette:|r clear the journal's search box first.")
        return
    end
    TransmogPaletteDB.journalSeen = TransmogPaletteDB.journalSeen or {}
    local saved = { collected = C_TransmogCollection.GetCollectedShown(),
        uncollected = C_TransmogCollection.GetUncollectedShown(),
        class = C_TransmogCollection.GetClassFilter(), sources = {} }
    for i = 1, C_TransmogCollection.GetNumTransmogSources() do
        saved.sources[i] = C_TransmogCollection.IsSourceTypeFilterChecked(i)
    end
    C_TransmogCollection.SetCollectedShown(true)
    C_TransmogCollection.SetUncollectedShown(true)
    C_TransmogCollection.SetAllSourceTypeFilters(true)
    -- Bigger tiles, as far as the screen allows (see JOURNAL_SCALE).
    saved.scale = CollectionsJournal:GetScale()
    local fit = UIParent:GetHeight() * 0.97 / CollectionsJournal:GetHeight()
    CollectionsJournal:SetScale(math.min(saved.scale * JOURNAL_SCALE, fit))
    -- Tiles re-apply their camera only when its ID changes, so after a rescale
    -- the open slot's models are framed for the old size and render blank (a
    -- whole run of helms came out empty). Blizzard refreshes them on
    -- UI_SCALE_CHANGED; a frame rescale has to ask.
    wc:RefreshCameras()
    local test = mode == "test"
    journal = { plan = BuildJournalPlan(mode), i = 0, shots = 0, new = 0, test = test, saved = saved }
    -- No colour filter or strip during a capture (Core.lua's journal hook).
    if ns.SyncColorPanelVisibility then ns.SyncColorPanelVisibility() end
    print(("|cff44ff44TransmogPalette:|r journal capture started (%s). Keep the mouse off the grid and the journal open; |cffffff00/tmpalette capture stop|r ends it early."):format(
        ({ test = "test: two pages per slot, current class", class = "current class, every slot and page",
            all = "every class, slot and page" })[mode]))
    JAfter(JOURNAL_WARMUP, JournalStep)
end

function ns.CaptureCommand(rest)
    rest = (rest or ""):lower()
    local db = TransmogPaletteDB
    if rest:match("^clear") then
        db.captures = nil
        db.sweepEmpty = nil
        db.journalSeen = nil
        print("|cff44ff44TransmogPalette:|r capture records cleared (screenshot files are untouched).")
        return
    end
    if rest:match("^sweep") then return StartSweep() end
    if rest:match("^journal reset") then
        db.journalSeen = nil
        print("|cff44ff44TransmogPalette:|r journal progress forgotten; the next run captures every page again. Captured pages are kept.")
        return
    end
    if rest:match("^journal") then
        return StartJournal(rest:match("test") and "test" or rest:match("class") and "class" or "all")
    end
    if rest:match("^stop") then
        if journal then return EndJournal("stopped") end
        return EndSweep("stopped")
    end
    if rest:match("^status") then
        print(("|cff44ff44TransmogPalette:|r %d pages, %d tiles captured; the journal run has %d distinct appearances. /reload to write them to disk."):format(
            #(db.captures or {}), ns.CaptureTileCount(), ns.JournalSeenCount()))
        return
    end
    ns.CapturePage()
end
