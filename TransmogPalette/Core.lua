local ADDON, ns = ...

local function InitDB()
    TransmogPaletteDB = TransmogPaletteDB or {}
    TransmogPaletteDB.primaryColors = TransmogPaletteDB.primaryColors or {}
    -- Development-only capture for the offline colour generator; see
    -- RecordVisual. Defaults off, and the table stays empty for players.
    TransmogPaletteDB.exportedVisuals = TransmogPaletteDB.exportedVisuals or {}
    if TransmogPaletteDB.recordVisuals == nil then
        TransmogPaletteDB.recordVisuals = false
    end
    -- Randomizer: one assigned main colour per armour slot, keyed by invSlot.
    TransmogPaletteDB.slotColors = TransmogPaletteDB.slotColors or {}
    TransmogPaletteDB.randomizerGrain = TransmogPaletteDB.randomizerGrain or ns.DEFAULT_GRAIN

    -- How coarse the FILTER's buckets are. Separate from randomizerGrain --
    -- see ns.FilterGrain. Changing it does NOT clear the mains: ns.SetFilterGrain
    -- translates them, which is only possible because they are an OR'd set.
    TransmogPaletteDB.filterGrain = TransmogPaletteDB.filterGrain or ns.DEFAULT_FILTER_GRAIN

    -- How much of a piece must be one colour before it stops counting as
    -- greyscale. Deliberately NOT tied to any version stamp: it changes which
    -- appearances land in a bucket, never what the buckets are called, so saved
    -- picks stay meaningful across a change and only the cached palettes need
    -- rebuilding.
    if type(TransmogPaletteDB.colorFirst) ~= "number" then
        TransmogPaletteDB.colorFirst = ns.DEFAULT_COLOR_FIRST
    end

    -- Hand corrections, visualID -> { main = ..., accent = ... }. See
    -- ns.ColorOverrides in Palette.lua for the three layers. Keyed by visualID
    -- and holding raw h/s/v rather than bucket keys, so they are immune to
    -- every version stamp in this file -- a grain change, a regrouping or a
    -- regeneration all leave them meaning exactly what they meant.
    --
    -- DELIBERATELY NOT CLEARED BY CLASSIFIER_VERSION. These are the player's
    -- own work, not derived data, and living in SavedVariables they already
    -- survive addon updates. Wiping them on a version bump would throw away
    -- the one thing here the player made by hand.
    TransmogPaletteDB.colorOverrides = TransmogPaletteDB.colorOverrides or {}
    -- The author's staging layer, only written while devOverrides is on.
    TransmogPaletteDB.authorOverrides = TransmogPaletteDB.authorOverrides or {}
    if type(TransmogPaletteDB.devOverrides) ~= "boolean" then
        TransmogPaletteDB.devOverrides = false
    end

    -- Colour chips on every appearance tile (ColorTags.lua). On by default:
    -- seeing what the addon thinks each piece is, filter or no filter, is how a
    -- player learns what a swatch will return before clicking it.
    if type(TransmogPaletteDB.showColorTags) ~= "boolean" then
        TransmogPaletteDB.showColorTags = true
    end

    -- Where the colour strip was dragged to, relative to the Transmogrifier's
    -- item list. Nil means the default spot under the search box.
    -- { point, relPoint, x, y }.
    if type(TransmogPaletteDB.stripPos) ~= "table" then
        TransmogPaletteDB.stripPos = nil
    end

    -- slotColors store bucket KEYS, and the grain decides what the keys are, so
    -- a grain change makes saved picks mean something else -- or nothing. Same
    -- hazard as CLASSIFIER_VERSION, tracked separately so changing the roll
    -- grain doesn't also clear the filter's colours.
    local rollScheme = TransmogPaletteDB.randomizerGrain .. ":" .. ns.ROLL_SCHEME_VERSION
    if TransmogPaletteDB.slotColorsGrain ~= rollScheme then
        TransmogPaletteDB.slotColors = {}
        TransmogPaletteDB.slotColorsGrain = rollScheme
    end

    -- A selection stores the bucket key it was picked from, so it silently
    -- matches nothing once the classifier changes shape — no error, just an
    -- active-looking filter returning zero results. Same hazard when the
    -- filter MODEL changes and old selections mean something different.
    -- Bump this whenever ClassifyColor's key format or the filter model
    -- changes; selections then clear themselves instead of misbehaving.
    --   1: equal-width hue buckets, keys like "h0_dark"
    --   2: perceptual hue bands, keys like "red_dark"
    --   3: positional ranks replaced by OR'd primaries + one any-rank accent
    --   4: neutrals split warm/cool; dark chromatic no longer forced to black
    --   5: greyscale is just black/gray/white, and colour beats tone -- the
    --      warm/cool keys and darkgray/lightgray no longer exist
    --   6: primaryColors went from a 1..3 array to an unbounded SET keyed by
    --      bucket key, and the filter gained a grain (default broad), so the
    --      old fine-grain keys in the old shape mean nothing here
    --   7: teal regrouped from blue to green. The KEYS still exist, but they
    --      mean different sets now -- a saved broad "blue" that was translated
    --      out of fine keys still carries teal_*, which would survive as a
    --      stale mixed-grain selection rather than an error
    --   8: teal reverted to blue. Bumped FORWARD rather than back to 6 so a
    --      client that already ran 7 still clears its now-wrong keys
    local CLASSIFIER_VERSION = 8
    if TransmogPaletteDB.classifierVersion ~= CLASSIFIER_VERSION then
        TransmogPaletteDB.primaryColors = {}
        TransmogPaletteDB.accentColor = nil
        -- Stores bucket keys too, so it rots the same way a filter selection
        -- does when the classifier changes shape.
        TransmogPaletteDB.slotColors = {}
        TransmogPaletteDB.selectedColors = nil  -- old positional slots
        TransmogPaletteDB.hueBucketWidth = nil  -- knob no longer exists
        TransmogPaletteDB.classifierVersion = CLASSIFIER_VERSION
    end

    ns.state = TransmogPaletteDB
end

local visualItemIDCache = {}

-- Resolves a visualID (an appearance's C_TransmogCollection identity) to a
-- representative itemID by taking its first known source. Confirmed working
-- in-game: C_TransmogCollection.GetAppearanceSources(visualID)[1].itemID.
local function ResolveItemIDFromVisualID(visualID)
    if not visualID then return nil end
    if visualItemIDCache[visualID] ~= nil then
        return visualItemIDCache[visualID] or nil
    end
    local itemID
    if C_TransmogCollection and C_TransmogCollection.GetAppearanceSources then
        local ok, sources = pcall(C_TransmogCollection.GetAppearanceSources, visualID)
        if ok and sources and sources[1] then
            itemID = sources[1].itemID
        end
    end
    visualItemIDCache[visualID] = itemID or false
    return itemID
end

-- Records a visualID -> itemID mapping into SavedVariables so
-- tools/generate_color_data.py can rebuild ColorData.lua from real data pulled
-- from a live client.
--
-- OFF BY DEFAULT, and it must stay that way. The shipped ColorData.lua already
-- covers every appearance, so for a player this only grows their SavedVariables
-- without ever being read -- a development session reached 25,000+ entries and
-- half a megabyte. Turn it on with /tmpalette record on when regenerating the
-- colour data after a content patch.
local function RecordVisual(visualID)
    if not ns.state.recordVisuals then return end
    if not visualID or ns.state.exportedVisuals[visualID] then return end
    local itemID = ResolveItemIDFromVisualID(visualID)
    if itemID then
        ns.state.exportedVisuals[visualID] = itemID
    end
end

local function HasActiveFilter()
    if ns.state.accentColor then return true end
    return next(ns.state.primaryColors) ~= nil
end

-- === Filter model ===
-- ColorData.lua's ns.ItemColors maps visualID -> a ranked list of up to 3
-- {h, s, v, weight} clusters, dominant first.
--
-- Up to three PRIMARY colors, OR'd: an item matches if its dominant (rank 1)
-- color is any of them. Plus one optional ACCENT color matched against the
-- item's rank-2 cluster.
--
-- Matching itself is unchanged from the original design — exact bucket
-- equality against a specific rank, no fuzzy tolerance, both sides classified
-- by the same function. What changed is only what the three slots MEAN: they
-- used to be primary/secondary/tertiary of one item (tertiary went unused),
-- and are now three alternatives for the primary. That is a breadth fix: a
-- single primary pick yields a median of 5 results over a real Hands list, so
-- the player needs several at once, and some colors only ever show up as a
-- primary in particular slots.
--
-- The accent is deliberately NOT OR'd with the primaries — it narrows all of
-- them at once ("red or blue or green, all with gold trim").
--
-- `skip` is "primary" or "accent": that part of the filter is ignored, so
-- Palette.lua can count what a swatch would yield given the REST of the
-- filter. A primary swatch's count is independent of the other primaries
-- precisely because they OR together.
local function MatchesFilter(visualID, skip)
    local itemColors = visualID and ns.ItemColors[visualID]
    if not itemColors then return false end

    -- ns.MainAndAccent, not itemColors[1]/[2]. Rank order discounts neutrals by
    -- a fixed 0.50 when ranking, which is a weighting rather than a rule, and it
    -- still left the greyscale buckets holding armour with obvious colour in it.
    -- MainAndAccent applies the colour-first threshold instead. This is NOT the
    -- any-rank matching that was rejected for the filter: an appearance still
    -- has exactly ONE main colour and ONE accent, and a pick still matches by
    -- exact bucket equality against the main. Only WHICH cluster is called the
    -- main has changed.
    -- visualID is passed so hand corrections (ns.OverrideFor) apply. Without
    -- it an override is silently inert here while still showing up in the
    -- swatch counts, which would make a count describe a different set than
    -- clicking it returns -- the recurring failure this file warns about.
    local primary, accentCluster = ns.MainAndAccent(itemColors, visualID)

    if skip ~= "primary" then
        if not primary then return false end
        -- primaryColors is a SET keyed by bucket key, not a 1..3 array. The cap
        -- of three existed because each pick cost a box on screen; with every
        -- bucket permanently on the strip as a toggle there is nothing to cap,
        -- and the matching was already an OR -- this is one lookup instead of a
        -- scan.
        if next(ns.state.primaryColors) then
            local primaryKey = ns.FilterClassify(primary[1], primary[2], primary[3], primary[5])
            if not ns.state.primaryColors[primaryKey] then return false end
        end
    end

    if skip ~= "accent" then
        local accent = ns.state.accentColor
        if accent then
            -- The appearance's SECOND colour, exactly as the old Secondary slot
            -- behaved -- and still literally rank 2 whenever the main colour is
            -- rank 1, which is the usual case. A monochrome item has no second
            -- cluster and so cannot match an accent.
            local c = accentCluster
            if not c then return false end
            if accent.key ~= ns.FilterClassify(c[1], c[2], c[3], c[5]) then
                return false
            end
        end
    end

    return true
end

ns.MatchesFilterExcept = MatchesFilter

-- === The Transmogrifier application window (TransmogFrame) ===
-- Intentionally the only frame this addon touches: the Collections >
-- Appearances journal (WardrobeCollectionFrame) was tried and dropped —
-- not where the player actually wants to filter while assembling a set.
-- Confirmed via in-game /fstack + probing: TransmogFrame.WardrobeCollection
-- .TabContent.ItemsFrame:SetCollectionEntries(entries) is called with the
-- final list to render, where each entry is a table with a .visualID field.

-- === Paging ===
-- Probed live 2026-08-11 via /tmpalette paging, NOT recalled. There is no page
-- accessor on ItemsFrame, nor on ItemsFrame.PagedContent -- it sits one level
-- deeper again, on the PagingControls child:
--   ic.PagedContent.PagingControls:GetCurrentPage()  -> 2
--   ic.PagedContent.PagingControls:GetMaxPages()     -> 3
--   ic.PagedContent.PagingControls:SetCurrentPage(n)
local function GetPagingControls(ic)
    local pc = ic and ic.PagedContent
    return pc and pc.PagingControls
end

local function CurrentPage(ic)
    local c = GetPagingControls(ic)
    if not c or not c.GetCurrentPage then return nil end
    local ok, page = pcall(c.GetCurrentPage, c)
    return ok and page or nil
end

local function MaxPages(ic)
    local c = GetPagingControls(ic)
    if not c or not c.GetMaxPages then return nil end
    local ok, m = pcall(c.GetMaxPages, c)
    return ok and m or nil
end

-- Puts back the page our own re-filter just destroyed.
--
-- PROVEN by /tmpalette pagetrace 2026-08-11, do not re-derive: selecting an
-- appearance runs Blizzard's RefreshCollectionEntries, and the page SURVIVES
-- that -- it still reads 2 when our hook fires. It is this addon's EXTRA
-- SetCollectionEntries that reaches Blizzard_PagedContentFrame's
-- SetDataProvider, which calls SetCurrentPage(1) unconditionally. So this is
-- restoring exactly what our own second pass disturbed, not fighting Blizzard.
local function RestorePage(ic, page)
    if not page or page <= 1 then return end
    local c = GetPagingControls(ic)
    if not c or not c.SetCurrentPage then return end
    -- A filtered list can be shorter than what was on screen, so a saved page
    -- can point past the end. Clamp rather than trusting it.
    local maxPages = MaxPages(ic) or 1
    if page > maxPages then page = maxPages end
    if page > 1 then pcall(c.SetCurrentPage, c, page) end
end

-- Cheap identity for a raw entry list. Selecting an appearance re-runs the
-- refresh with the SAME list, while changing gear slot brings a different one,
-- and only the former should keep its page -- otherwise switching slots would
-- inherit the previous slot's page instead of starting at the top.
local function ListSignature(entries)
    local n = #entries
    if n == 0 then return "0" end
    local first = entries[1] and entries[1].visualID or 0
    local last = entries[n] and entries[n].visualID or 0
    return ("%d:%d:%d"):format(n, first, last)
end

-- Traces WHO moves the page, off by default (/tmpalette pagetrace).
--
-- Needed because the obvious explanation does not survive contact: this addon
-- re-filters from a POST-hook, so Blizzard's own SetCollectionEntries has
-- already run by then, and the filtered list is identical across a selection --
-- so neither call obviously invalidates page 2. The call stack on each
-- SetCurrentPage names the culprit instead of leaving it to be inferred.
local pageTrace, pageTraceHooked = nil, false
local function Trace(fmt, ...)
    if not pageTrace then return end
    pageTrace[#pageTrace + 1] = select("#", ...) > 0 and fmt:format(...) or fmt
end

local function EnsurePageTraceHooks(ic)
    if pageTraceHooked then return end
    local c = GetPagingControls(ic)
    if not c or not c.SetCurrentPage then return end
    hooksecurefunc(c, "SetCurrentPage", function(_, page)
        Trace("  >> SetCurrentPage(%s) called by:\n%s", tostring(page), debugstack(2, 8, 0))
    end)
    if ic.PageToTransmogID then
        hooksecurefunc(ic, "PageToTransmogID", function(_, id)
            Trace("  >> PageToTransmogID(%s) -> page now %s", tostring(id), tostring(CurrentPage(ic)))
        end)
    end
    pageTraceHooked = true
end

local transmogFiltering = false
local lastFilteredCount -- what we last handed the frame; see /tmpalette debug
local sampleEntry -- one raw entry, for inspecting its fields live
local lastListSignature -- see ListSignature: tells a re-select from a slot change
local function ApplyColorFilterToTransmog(ic, entries)
    if transmogFiltering or not entries then return end

    sampleEntry = entries[1] or sampleEntry

    -- Updated on EVERY pass, including the ones that return early below, or a
    -- stale signature would make the next call look like a slot change.
    local signature = ListSignature(entries)
    local sameList = (signature == lastListSignature)
    lastListSignature = signature

    Trace("SetCollectionEntries hook: entries=%d page=%s max=%s sameList=%s",
        #entries, tostring(CurrentPage(ic)), tostring(MaxPages(ic)), tostring(sameList))

    -- Guarded rather than relying on RecordVisual's own early return: this runs
    -- for every entry of every category the player opens, and recording is off
    -- for everyone but whoever is regenerating the colour data.
    if ns.state.recordVisuals then
        for _, entry in ipairs(entries) do
            RecordVisual(entry.visualID)
        end
    end

    -- Guarded above against re-entry, so `entries` here is always the full
    -- unfiltered list for the current category — the right palette source.
    ns.SetCurrentVisuals(entries)

    -- Every swatch on the strip carries a count of what picking it would yield
    -- IN THIS CATEGORY, so they all go stale the moment the category changes.
    -- The old popup rebuilt itself each time it opened and never needed this.
    if ns.RefreshColorPanels then ns.RefreshColorPanels() end

    if not HasActiveFilter() then return end

    local filtered = {}
    for _, entry in ipairs(entries) do
        if MatchesFilter(entry.visualID) then
            table.insert(filtered, entry)
        end
    end
    lastFilteredCount = #filtered
    if #filtered == #entries then return end

    -- Read BEFORE the re-set, which is what moves it. Only worth restoring when
    -- this is the same list the player was already paging through.
    local page = sameList and CurrentPage(ic) or nil

    Trace("  re-setting %d filtered (page=%s max=%s)",
        #filtered, tostring(CurrentPage(ic)), tostring(MaxPages(ic)))
    -- The restore stays INSIDE the re-entry guard: SetCurrentPage redraws the
    -- page, and any SetCollectionEntries that redraw provokes must not start
    -- another filter pass, which would page back to 1 and undo this.
    transmogFiltering = true
    ic:SetCollectionEntries(filtered)
    RestorePage(ic, page)
    transmogFiltering = false
    Trace("  after re-set: page=%s max=%s",
        tostring(CurrentPage(ic)), tostring(MaxPages(ic)))
end

local function GetTransmogItemsFrame()
    return TransmogFrame and TransmogFrame.WardrobeCollection
        and TransmogFrame.WardrobeCollection.TabContent
        and TransmogFrame.WardrobeCollection.TabContent.ItemsFrame
end

local function RefreshTransmog()
    local ic = GetTransmogItemsFrame()
    if not ic then return end
    if ic.RefreshCollectionEntries then
        ic:RefreshCollectionEntries()
    elseif ic.Refresh then
        ic:Refresh()
    end
end

-- Exposed so a slash command that changes what the filter MATCHES can redraw
-- the list. Safe to call with the Transmogrifier closed -- it no-ops.
ns.RefreshFilter = RefreshTransmog

-- Walks an object and its metatable chain for method names. Frame methods live
-- on the metatable's __index, not on the object, so pairs(frame) alone finds
-- almost nothing.
local function CollectMethodNames(obj)
    local names, seen = {}, {}
    local function scan(t, depth)
        if type(t) ~= "table" or depth > 5 then return end
        for k, v in pairs(t) do
            if type(k) == "string" and type(v) == "function" and not seen[k] then
                seen[k] = true
                names[#names + 1] = k
            end
        end
        local mt = getmetatable(t)
        if mt and type(mt.__index) == "table" then scan(mt.__index, depth + 1) end
    end
    scan(obj, 1)
    table.sort(names)
    return names
end

local function DescribeValue(v)
    local t = type(v)
    if t == "table" then
        return (v.GetObjectType and ("frame:" .. tostring(v:GetObjectType()))) or "table"
    end
    return tostring(v)
end

-- Finds the ItemsFrame's paging API. Nothing in this addon touches paging, so
-- the getter/setter names are unknown -- and this project has already paid for
-- guessing a Blizzard API from memory once (see the C_Transmog notes). Run it
-- WITH A FILTER ACTIVE AND SITTING ON PAGE 2, so whichever value reads 2 names
-- the getter, and its Set* twin is the one the filter needs to restore.
--
-- Calls ONLY Get/Is/Has/Can with no arguments. A Set* here would change the
-- very page it is trying to measure -- the same mistake DumpWeapons made when
-- it invoked SetCurrentWeaponOption() on the player's live outfit.
function ns.DumpPaging()
    local lines = {}
    local function add(fmt, ...)
        lines[#lines + 1] = select("#", ...) > 0 and fmt:format(...) or fmt
    end

    local ic = GetTransmogItemsFrame()
    if not ic then
        add("ItemsFrame NOT FOUND -- open the Transmogrifier first.")
        return lines
    end

    add("=== ItemsFrame paging probe ===")
    add("filter active: %s   last filtered count: %s",
        tostring(HasActiveFilter()), tostring(lastFilteredCount))

    -- Fields whose NAME suggests paging, including non-functions: the current
    -- page is often a plain number on the frame or on a PagingControls child.
    add("--- fields matching page/element ---")
    for k, v in pairs(ic) do
        if type(k) == "string" then
            local lk = k:lower()
            if lk:match("pag") or lk:match("element") then
                add("  ic.%s = %s", k, DescribeValue(v))
            end
        end
    end

    add("--- zero-arg getters matching page/element ---")
    for _, name in ipairs(CollectMethodNames(ic)) do
        local isGetter = name:match("^Get") or name:match("^Is")
            or name:match("^Has") or name:match("^Can")
        if isGetter and (name:match("Pag") or name:match("Element")) then
            local ok, a, b = pcall(ic[name], ic)
            add("  ic:%s() -> %s%s", name,
                ok and DescribeValue(a) or ("ERROR " .. tostring(a)),
                (ok and b ~= nil) and (", " .. DescribeValue(b)) or "")
        end
    end

    add("--- ALL method names containing 'Pag' (setters NAMED, never called) ---")
    for _, name in ipairs(CollectMethodNames(ic)) do
        if name:match("Pag") then add("  ic:%s", name) end
    end

    -- Descend into the paging widgets. The first pass found ic.PagedContent and
    -- ic.PagedContent.PagingControls but NO current-page getter on either, so
    -- the page number sits one level deeper than that pass looked -- most
    -- likely a plain field on PagingControls rather than behind a getter.
    local targets = { { "ic", ic } }
    local pc = ic.PagedContent
    if type(pc) == "table" then
        targets[#targets + 1] = { "ic.PagedContent", pc }
        if type(pc.PagingControls) == "table" then
            targets[#targets + 1] = { "ic.PagedContent.PagingControls", pc.PagingControls }
        end
    end

    for _, t in ipairs(targets) do
        local label, obj = t[1], t[2]

        add("--- %s : methods matching Page/Current/Index ---", label)
        for _, name in ipairs(CollectMethodNames(obj)) do
            if name:match("Page") or name:match("Current") or name:match("Index") then
                local isGetter = name:match("^Get") or name:match("^Is")
                    or name:match("^Has") or name:match("^Can")
                if isGetter then
                    local ok, a, b = pcall(obj[name], obj)
                    add("  %s:%s() -> %s%s", label, name,
                        ok and DescribeValue(a) or ("ERROR " .. tostring(a)),
                        (ok and b ~= nil) and (", " .. DescribeValue(b)) or "")
                else
                    -- Named only. Calling a Set*/Advance* here would move the
                    -- very page this probe exists to measure.
                    add("  %s:%s   (NOT called)", label, name)
                end
            end
        end

        -- The current page is very often a plain number, not a getter. On `ic`
        -- itself that would be thousands of frame fields, so it stays filtered;
        -- on the two paging widgets everything scalar is worth seeing.
        add("--- %s : scalar fields ---", label)
        for k, v in pairs(obj) do
            if type(k) == "string" and type(v) ~= "function" and type(v) ~= "table" then
                if label ~= "ic" or k:lower():match("pag") or k:lower():match("current") then
                    add("  %s.%s = %s", label, k, DescribeValue(v))
                end
            end
        end
    end

    return lines
end

-- Finds the frames that draw individual appearances, so a right-click handler
-- can be attached to them and made to yield a visualID.
--
-- Everything this needs is unknown: where the element frames live, whether
-- they carry the visualID directly or behind an elementData accessor, whether
-- they are pooled (the gear-slot buttons are, and a cached mapping to those
-- went stale and produced swatches that appeared to move around), and whether
-- this build exposes GetMouseFoci or the older GetMouseFocus. Guessing any of
-- it is how this project lost four attempts to the C_Transmog API.
--
-- Run it WITH A SLOT OPEN AND AN APPEARANCE UNDER THE CURSOR. Calls only
-- Get/Is/Has with no arguments -- never a setter, which could change the very
-- list being measured.
function ns.DumpAppearanceButtons()
    local lines = {}
    local function add(fmt, ...)
        lines[#lines + 1] = select("#", ...) > 0 and fmt:format(...) or fmt
    end

    local ic = GetTransmogItemsFrame()
    if not ic then
        add("ItemsFrame NOT FOUND -- open the Transmogrifier first.")
        return lines
    end

    add("=== appearance button probe ===")

    -- Which mouse-focus API this build has decides whether right-click can be
    -- resolved from a keybind/macro at all, or must be a script on each frame.
    add("--- mouse focus API ---")
    add("  GetMouseFoci  = %s", type(_G.GetMouseFoci))
    add("  GetMouseFocus = %s", type(_G.GetMouseFocus))
    if type(_G.GetMouseFoci) == "function" then
        local ok, foci = pcall(_G.GetMouseFoci)
        if ok and type(foci) == "table" then
            add("  GetMouseFoci() returned %d frame(s)", #foci)
            for i, f in ipairs(foci) do
                local okType, ot = pcall(f.GetObjectType, f)
                add("    [%d] type=%s name=%s", i,
                    okType and tostring(ot) or "?",
                    tostring(f.GetName and f:GetName() or "<unnamed>"))
                -- The payload we actually need. If a hovered appearance frame
                -- carries any of these, right-click can identify the item.
                for _, key in ipairs({ "visualID", "elementData", "GetElementData" }) do
                    if f[key] ~= nil then
                        add("        .%s = %s", key, DescribeValue(f[key]))
                    end
                end
            end
        end
    elseif type(_G.GetMouseFocus) == "function" then
        local ok, f = pcall(_G.GetMouseFocus)
        if ok and f then
            add("  GetMouseFocus() -> %s", tostring(f.GetName and f:GetName() or "<unnamed>"))
        end
    end

    -- Walk down to the element frames. Depth is capped because ItemsFrame's
    -- tree is large and the interesting layer has proven to be shallow -- the
    -- paging probe found its answer two levels down.
    local seen = {}
    local function walk(obj, label, depth)
        if depth > 3 or not obj or seen[obj] then return end
        seen[obj] = true
        local okKids, kids = pcall(function() return { obj:GetChildren() } end)
        if not okKids or not kids then return end
        -- Frames drawing the same thing are identical in size and count, so a
        -- summary beats printing 30 near-identical children.
        local byType = {}
        for _, kid in ipairs(kids) do
            local okType, ot = pcall(kid.GetObjectType, kid)
            local key = okType and tostring(ot) or "?"
            byType[key] = (byType[key] or 0) + 1
        end
        local summary = {}
        for k, n in pairs(byType) do summary[#summary + 1] = ("%s x%d"):format(k, n) end
        table.sort(summary)
        add("  %s : %d children (%s)", label, #kids, table.concat(summary, ", "))

        for i, kid in ipairs(kids) do
            -- Report a child only if it looks like it identifies an appearance.
            local marks = {}
            for _, key in ipairs({ "visualID", "elementData", "GetElementData",
                                   "GetVisualID", "RegisterForClicks" }) do
                if kid[key] ~= nil then marks[#marks + 1] = key end
            end
            if #marks > 0 then
                local w, h = 0, 0
                pcall(function() w, h = kid:GetWidth(), kid:GetHeight() end)
                add("    %s[%d] %.0fx%.0f carries: %s", label, i, w, h,
                    table.concat(marks, ", "))
                -- Resolve the visualID both plausible ways on the FIRST such
                -- child only; that is enough to settle which one to use.
                if i == 1 then
                    if kid.visualID ~= nil then
                        add("      .visualID = %s", tostring(kid.visualID))
                    end
                    if type(kid.GetElementData) == "function" then
                        local okEd, ed = pcall(kid.GetElementData, kid)
                        if okEd and type(ed) == "table" then
                            -- Two levels deep. The first pass printed scalars
                            -- only and found no visualID, so it is nested --
                            -- the entry table Blizzard hands SetCollectionEntries
                            -- is almost certainly sitting one level in.
                            for k, v in pairs(ed) do
                                if type(v) == "table" then
                                    add("      elementData.%s = <table>", tostring(k))
                                    for k2, v2 in pairs(v) do
                                        if type(v2) ~= "table" and type(v2) ~= "function" then
                                            add("        .%s.%s = %s", tostring(k), tostring(k2), tostring(v2))
                                        else
                                            add("        .%s.%s = <%s>", tostring(k), tostring(k2), type(v2))
                                        end
                                    end
                                elseif type(v) ~= "function" then
                                    add("      elementData.%s = %s", tostring(k), tostring(v))
                                else
                                    add("      elementData:%s()", tostring(k))
                                end
                            end
                        end
                    end
                    -- Pooled or not decides whether a handler may be attached
                    -- once or must be re-attached on every relayout.
                    for _, m in ipairs({ "Init", "Release", "GetOwningFramePool" }) do
                        if kid[m] ~= nil then add("      pooled? has :%s", m) end
                    end
                end
            end
            walk(kid, ("%s[%d]"):format(label, i), depth + 1)
        end
    end

    add("--- frame tree from ic.PagedContent ---")
    if ic.PagedContent then
        walk(ic.PagedContent, "PagedContent", 1)
    else
        add("  ic.PagedContent is nil -- walking ic itself")
        walk(ic, "ic", 1)
    end

    return lines
end

-- === Context menu probe ===
--
-- Blizzard ALREADY owns right-click on an appearance tile (Set Favorite), so
-- the colour override has to be ADDED to that menu, not bolted over it --
-- attaching our own handler would either break favourites or be swallowed by
-- it. The modern menu system is tag-based (Menu.ModifyMenu), but the tag this
-- particular menu uses is unknown and must not be guessed.
--
-- Observes only: enumerates the Menu/MenuUtil namespaces, then hooksecurefuncs
-- every Create*/Modify*/Open* in them and records what fires when a menu opens,
-- with debugstack so Blizzard's own calling file is named. That stack is what
-- identifies the menu -- the same technique that settled the paging bug, where
-- two plausible theories were both wrong until the trace ran.
local menuProbe, menuProbeHooked = nil, false

local function MenuProbeAdd(fmt, ...)
    if not menuProbe then return end
    menuProbe[#menuProbe + 1] = select("#", ...) > 0 and fmt:format(...) or fmt
end

function ns.ToggleMenuProbe()
    if menuProbe then
        local captured = menuProbe
        menuProbe = nil
        return captured
    end

    menuProbe = {}
    MenuProbeAdd("=== context menu probe %s ===", date("%Y-%m-%d %H:%M:%S"))

    for _, name in ipairs({ "Menu", "MenuUtil" }) do
        local t = _G[name]
        if type(t) ~= "table" then
            MenuProbeAdd("%s = %s (NOT a table)", name, type(t))
        else
            local fns = {}
            for k, v in pairs(t) do
                if type(v) == "function" then fns[#fns + 1] = k end
            end
            table.sort(fns)
            MenuProbeAdd("--- %s (%d functions) ---", name, #fns)
            MenuProbeAdd("  %s", table.concat(fns, ", "))
        end
    end

    -- Installed once and left in place: hooksecurefunc cannot be undone, so a
    -- second toggle must not stack another layer of hooks. They are inert
    -- whenever menuProbe is nil.
    if not menuProbeHooked then
        for _, nsName in ipairs({ "Menu", "MenuUtil" }) do
            local t = _G[nsName]
            if type(t) == "table" then
                for k, v in pairs(t) do
                    if type(v) == "function"
                        and (k:match("^Create") or k:match("^Modify") or k:match("^Open")) then
                        hooksecurefunc(t, k, function(a1, a2, a3, a4)
                            MenuProbeAdd("CALL %s.%s(%s, %s, %s, %s)", nsName, k,
                                DescribeValue(a1), DescribeValue(a2),
                                DescribeValue(a3), DescribeValue(a4))
                            -- Blizzard's calling file usually names the menu
                            -- outright, which is the answer being looked for.
                            MenuProbeAdd("   from: %s",
                                (debugstack(2, 3, 0) or ""):gsub("\n", " | "))

                            -- THE tag question. Menu.ModifyMenu needs a tag to
                            -- attach to, and the first probe showed the root
                            -- description created with a nil second argument --
                            -- which does not prove the menu is untagged, since
                            -- the generator can call rootDescription:SetTag
                            -- afterwards. GetOpenMenuTags answers it directly,
                            -- but only while a menu is actually open, which is
                            -- exactly here and nowhere a slash command can
                            -- reach (typing one closes the menu).
                            if k == "CreateContextMenu" and Menu and Menu.GetOpenMenuTags then
                                local okTags, tags = pcall(Menu.GetOpenMenuTags)
                                if okTags and type(tags) == "table" then
                                    -- KEY AND VALUE both. A first pass printed
                                    -- only keys and reported "[1]" -- which is
                                    -- an array index, not a tag. The tag is the
                                    -- VALUE, and that is the string
                                    -- Menu.ModifyMenu needs.
                                    local n = 0
                                    for k, v in pairs(tags) do
                                        n = n + 1
                                        if type(v) == "table" then
                                            MenuProbeAdd("   TAG [%s] = <table>", tostring(k))
                                            for k2, v2 in pairs(v) do
                                                MenuProbeAdd("      .%s = %s", tostring(k2), tostring(v2))
                                            end
                                        else
                                            MenuProbeAdd("   TAG [%s] = %s (%s)",
                                                tostring(k), tostring(v), type(v))
                                        end
                                    end
                                    if n == 0 then
                                        MenuProbeAdd("   OPEN MENU TAGS: NONE -- menu is untagged")
                                    end
                                else
                                    MenuProbeAdd("   GetOpenMenuTags failed: %s", tostring(tags))
                                end
                                -- The owner is the tile, so this confirms the
                                -- click resolves to a visualID the same way the
                                -- override needs it to.
                                if type(a1) == "table" and type(a1.GetElementData) == "function" then
                                    local okEd, ed = pcall(a1.GetElementData, a1)
                                    local info = okEd and type(ed) == "table" and ed.appearanceInfo
                                    MenuProbeAdd("   owner visualID = %s",
                                        tostring(info and info.visualID))
                                end
                            end
                        end)
                    end
                end
            end
        end
        menuProbeHooked = true
        MenuProbeAdd("--- hooks installed; right-click an appearance now ---")
    else
        MenuProbeAdd("--- hooks already installed; right-click an appearance now ---")
    end

    return nil
end

local transmogHooked = false
local function TryHookTransmog()
    if transmogHooked then return true end
    local ic = GetTransmogItemsFrame()
    if not ic or not ic.SetCollectionEntries then return false end

    hooksecurefunc(ic, "SetCollectionEntries", function(self, entries)
        ApplyColorFilterToTransmog(self, entries)
    end)
    transmogHooked = true

    if ns.RegisterColorPanel then
        ns.RegisterColorPanel(ic, ic.SearchBox, RefreshTransmog)
    end
    if ns.RegisterRandomizer then
        ns.RegisterRandomizer(TransmogFrame)
    end
    if ns.RegisterColorTags then
        ns.RegisterColorTags(ic)
    end

    return true
end

-- === Colour correction on the appearance right-click menu ===
--
-- Blizzard already owns right-click on a tile ("Transmogrify as:" / Set
-- Favorite), so this ADDS to that menu rather than replacing it. All of the
-- following was probed live 2026-08-11, not recalled:
--   * the menu's tag is MENU_WARDROBE_ITEMS_MODEL_FILTER (from
--     Menu.GetOpenMenuTags() called inside a CreateContextMenu hook -- it can
--     only be read while a menu is open, which no slash command can reach)
--   * it is built by MenuUtil.CreateContextMenu(tile, generator) from
--     Blizzard_TransmogShared.lua:693
--   * the owner passed in IS the DressUpModel tile, and the appearance is at
--     tile:GetElementData().appearanceInfo.visualID
local OVERRIDE_MENU_TAG = "MENU_WARDROBE_ITEMS_MODEL_FILTER"

-- The tiles are POOLED, so this must resolve from the owner at click time and
-- must never be cached -- the same trap that made the randomiser's swatches
-- appear to move between gear slots.
local function VisualIDFromMenuOwner(owner)
    if type(owner) ~= "table" or type(owner.GetElementData) ~= "function" then
        return nil
    end
    local ok, ed = pcall(owner.GetElementData, owner)
    if not ok or type(ed) ~= "table" then return nil end
    local info = ed.appearanceInfo
    return type(info) == "table" and info.visualID or nil
end

-- Clearing every correction is destructive and irreversible, so it asks first.
-- The count goes in the text because the whole reason to reach for this is not
-- being sure what you set.
StaticPopupDialogs["TRANSMOGPALETTE_CLEAR_OVERRIDES"] = {
    text = "Remove all %d colour correction|4:s;?\n\nThis cannot be undone.",
    button1 = YES,
    button2 = NO,
    OnAccept = function()
        local store, layer = ns.OverrideStore()
        -- Wiped IN PLACE, not reassigned: this is the live SavedVariables
        -- table, and rebinding a local would leave the stored one untouched.
        wipe(store)
        ns.OverridesChanged()
        print(("|cff44ff44TransmogPalette:|r all %s colour corrections removed."):format(layer))
    end,
    timeout = 0,
    whileDead = true,
    hideOnEscape = true,
    showAlert = true,
}

local overrideMenuRegistered = false
local function RegisterOverrideMenu()
    if overrideMenuRegistered then return end
    if type(Menu) ~= "table" or type(Menu.ModifyMenu) ~= "function" then return end

    Menu.ModifyMenu(OVERRIDE_MENU_TAG, function(owner, rootDescription)
        -- Wrapped whole. This callback runs inside Blizzard's menu build, so an
        -- error here would break Set Favorite -- a colour tool must never cost
        -- the player a working favourites menu.
        pcall(function()
            if type(rootDescription) ~= "table"
                or type(rootDescription.CreateButton) ~= "function" then
                return
            end

            local visualID = VisualIDFromMenuOwner(owner)
            -- An override only ever acts through ns.MainAndAccent, which is
            -- reached only when the appearance HAS colour data. Offering the
            -- entry on one that has none would be a button that does nothing.
            if not visualID or not ns.HasColorData(visualID) then return end

            if rootDescription.CreateDivider then rootDescription:CreateDivider() end
            if rootDescription.CreateTitle then
                rootDescription:CreateTitle("Transmog Palette")
            end

            rootDescription:CreateButton("Correct main colour", function()
                ns.OpenOverridePicker(visualID, "main", owner)
            end)
            rootDescription:CreateButton("Correct accent colour", function()
                ns.OpenOverridePicker(visualID, "accent", owner)
            end)

            -- Only offered when there is something to undo, so the menu does
            -- not carry a permanently dead entry.
            if ns.OverrideFor(visualID) then
                rootDescription:CreateButton("Clear colour correction", function()
                    local store = ns.OverrideStore()
                    store[visualID] = nil
                    ns.OverridesChanged()
                end)
            end

            -- The bulk escape hatch, for when a run of judgement calls on
            -- genuinely ambiguous items has left the buckets looking worse
            -- than before. Shows the count, and confirms before wiping.
            local total = ns.OverrideCount()
            if total > 0 then
                rootDescription:CreateButton(
                    ("Clear ALL colour corrections (%d)"):format(total), function()
                        StaticPopup_Show("TRANSMOGPALETTE_CLEAR_OVERRIDES", total)
                    end)
            end
        end)
    end)

    overrideMenuRegistered = true
end

-- TransmogFrame's owning addon name isn't confirmed, so poll briefly for it
-- to appear instead of relying on a specific ADDON_LOADED event.
local pollTicker
local function StartTransmogPoll()
    if pollTicker then return end
    pollTicker = C_Timer.NewTicker(1, function()
        if TryHookTransmog() then
            pollTicker:Cancel()
            pollTicker = nil
        end
    end)
end

local f = CreateFrame("Frame")
f:RegisterEvent("ADDON_LOADED")
f:RegisterEvent("PLAYER_LOGIN")
f:SetScript("OnEvent", function(_, event, name)
    if event == "ADDON_LOADED" and name == ADDON then
        InitDB()
    elseif event == "PLAYER_LOGIN" then
        StartTransmogPoll()
        -- Registered by TAG, so it does not need the Transmogrifier -- or even
        -- Blizzard_TransmogShared -- to be loaded yet. Menu.ModifyMenu just
        -- records the modifier and applies it whenever a menu with that tag is
        -- next built, which is why this is not part of the frame poll.
        RegisterOverrideMenu()
    end
end)

SLASH_TRANSMOGPALETTE1 = "/tmpalette"
SlashCmdList["TRANSMOGPALETTE"] = function(msg)
    if msg and msg:lower():match("^dump") then
        -- Snapshots just the category currently on screen, so the offline
        -- generator can be pointed at one slot for a quick coverage test
        -- instead of the whole recorded set.
        local visuals = ns.GetCurrentVisuals()
        if not visuals or #visuals == 0 then
            print("|cffff4444TransmogPalette:|r nothing listed yet — open the Transmogrifier and select a slot first.")
            return
        end
        TransmogPaletteDB.dumpedVisuals = {}
        for i, vid in ipairs(visuals) do
            TransmogPaletteDB.dumpedVisuals[i] = vid
        end
        print(("|cff44ff44TransmogPalette:|r dumped %d appearances from the current category. Now /reload to flush it to disk."):format(#visuals))
        return
    end

    if msg and msg:lower():match("^roll") then
        -- `if ns.RollRandomOutfit then ... end` used to guard this, which meant
        -- a Randomizer.lua that failed to load produced a command that printed
        -- absolutely nothing. Silence is never an acceptable answer to a typed
        -- command - if the roller isn't there, say so.
        if not ns.RollRandomOutfit then
            print("|cffff4444TransmogPalette:|r the randomizer didn't load (Randomizer.lua errored). Run |cffffff00/console scriptErrors 1|r then |cffffff00/reload|r to see the error.")
            return
        end
        -- Verbose: the player asked for this explicitly, so confirm it happened.
        -- The Roll button stays quiet, since the preview changing says it.
        ns.RollRandomOutfit(true)

        -- Per-slot detail is only worth keeping (and mentioning) when something
        -- actually failed. Capturing it on every successful roll was just noise.
        -- Cleared FIRST, unconditionally. This only used to be written on
        -- failure and then persisted forever, so a months-old capture sat in
        -- SavedVariables looking live -- it has now been misread twice, once
        -- naming C_Transmog.SetPending, a function this build does not even
        -- have. A successful roll must erase the previous failure's evidence.
        TransmogPaletteDB.rollDiag = nil
        if ns.lastRollFailed and ns.lastRollDiag then
            TransmogPaletteDB.rollDiag = {
                when = date and date("%Y-%m-%d %H:%M:%S") or "?",
                lines = ns.lastRollDiag,
            }
            print(("  |cff808080%d diagnostic lines captured - /reload to flush them to disk.|r"):format(#ns.lastRollDiag))
        end
        return
    end

    if msg and msg:lower():match("^watch") then
        -- Records what Blizzard's own UI passes to the staging API when you
        -- click an appearance, so the call can be COPIED rather than guessed.
        if not ns.GetCapturedCalls then
            print("|cffff4444TransmogPalette:|r randomizer not loaded.")
            return
        end
        local calls = ns.GetCapturedCalls()
        if #calls == 0 then
            print("|cffff8800TransmogPalette:|r nothing captured yet. Click an appearance in the Transmogrifier to stage it, then run this again.")
            return
        end
        TransmogPaletteDB.watchDump = calls
        print(("|cff44ff44TransmogPalette:|r captured %d call(s). Now |cffffff00/reload|r."):format(#calls))
        return
    end

    if msg and msg:lower():match("^record") then
        -- Development only: repopulates exportedVisuals for the offline colour
        -- generator. Off by default so a player never accumulates a growing
        -- SavedVariables file for data the shipped ColorData.lua already has.
        local arg = msg:lower():match("^record%s+(%a+)")
        if arg == "on" then
            TransmogPaletteDB.recordVisuals = true
            print("|cffff8800TransmogPalette:|r appearance recording ON - browse the Transmogrifier, then /reload and run tools/generate_color_data.py. Turn it off again when done.")
        elseif arg == "off" then
            TransmogPaletteDB.recordVisuals = false
            print("|cff44ff44TransmogPalette:|r appearance recording OFF. Use |cffffff00/tmpalette record clear|r to discard what was collected.")
        elseif arg == "clear" then
            TransmogPaletteDB.exportedVisuals = {}
            print("|cff44ff44TransmogPalette:|r recorded appearances discarded.")
        else
            local count = 0
            for _ in pairs(TransmogPaletteDB.exportedVisuals) do count = count + 1 end
            print(("|cff44ff44TransmogPalette:|r recording is %s, %d appearances stored. |cffffff00/tmpalette record on|off|clear|r"):format(
                TransmogPaletteDB.recordVisuals and "ON" or "OFF", count))
        end
        return
    end

    if msg and (msg:lower():match("^colou?rfirst")) then
        -- Tunable rather than fixed because it trades two opposite complaints
        -- against each other -- "colourful armour keeps showing up under black"
        -- versus "a black piece with gold trim now rolls as gold" -- and there
        -- is no ground-truth set to settle it from distributions alone.
        local want = tonumber(msg:match("[%d%.]+"))
        if not want then
            print(("|cff44ff44TransmogPalette:|r colour-first threshold is |cffffff00%.2f|r."):format(
                ns.ColorFirstThreshold()))
            print("  An appearance is black/gray/white only if no single colour covers")
            print(("  at least this much of it. Lower = more colour, less greyscale."))
            print("  Set it with |cffffff00/tmpalette colorfirst 0.25|r (default 0.20)")
            return
        end
        if want < 0 or want > 1 then
            print("|cffff4444TransmogPalette:|r that is a share of the item, so it must be between 0 and 1.")
            return
        end
        TransmogPaletteDB.colorFirst = want
        -- Bucket KEYS are unchanged, so saved picks stay valid -- but which
        -- appearances are in each bucket has changed, so every cached palette
        -- and per-slot candidate list is now stale.
        ns.InvalidateSwatchPalettes()
        if ns.InvalidateRandomizerSlots then ns.InvalidateRandomizerSlots() end
        if ns.RefreshRandomizerPanel then ns.RefreshRandomizerPanel() end
        if ns.RefreshFilter then ns.RefreshFilter() end
        print(("|cff44ff44TransmogPalette:|r colour-first threshold set to |cffffff00%.2f|r. Reopen a colour picker to see the new counts."):format(want))
        return
    end

    if msg and msg:lower():match("^grain") then
        -- How coarsely the RANDOMISER buckets colours. The filter is unaffected.
        local want = msg:lower():match("^grain%s+(%a+)")
        if not want then
            print(("|cff44ff44TransmogPalette:|r roll colour grain is |cffffff00%s|r. Coarser means fewer colours with more appearances each."):format(
                TransmogPaletteDB.randomizerGrain))
            local names = {}
            for _, g in ipairs(ns.GRAIN_ORDER) do
                names[#names + 1] = ("%s (%s)"):format(g, ns.Grains[g].label)
            end
            print("  " .. table.concat(names, ", "))
            print("  set it with |cffffff00/tmpalette grain coarse|r")
            return
        end
        if not ns.Grains[want] then
            print(("|cffff4444TransmogPalette:|r unknown grain '%s'. Options: %s"):format(
                want, table.concat(ns.GRAIN_ORDER, ", ")))
            return
        end
        -- Saved picks are bucket keys, which mean something different at a
        -- different grain, so they are cleared rather than left to silently
        -- match nothing.
        local cleared = TransmogPaletteDB.randomizerGrain ~= want
        TransmogPaletteDB.randomizerGrain = want
        if cleared then
            TransmogPaletteDB.slotColors = {}
            TransmogPaletteDB.slotColorsGrain = want .. ":" .. ns.ROLL_SCHEME_VERSION
            if ns.InvalidateRandomizerSlots then ns.InvalidateRandomizerSlots() end
            if ns.RefreshRandomizerPanel then ns.RefreshRandomizerPanel() end
        end
        print(("|cff44ff44TransmogPalette:|r roll colour grain set to |cffffff00%s|r%s"):format(
            want, cleared and " (slot colours cleared - keys change with the grain)" or ""))
        return
    end

    if msg and msg:lower():match("^weapons") then
        -- What the client considers legal for each weapon slot. Probed rather
        -- than assumed, since GetWeaponOptionsForSlot's shape is unknown.
        if not ns.DumpWeapons then
            print("|cffff4444TransmogPalette:|r randomizer not loaded.")
            return
        end
        TransmogPaletteDB.weaponDump = ns.DumpWeapons()
        print(("|cff44ff44TransmogPalette:|r captured %d weapon lines. Now |cffffff00/reload|r."):format(#TransmogPaletteDB.weaponDump))
        return
    end

    if msg and msg:lower():match("^api") then
        -- C_Transmog.SetPending and TransmogUtil.CreateTransmogPendingInfo are
        -- both nil on this build, so the staging call has to be read off the
        -- client instead of guessed at again.
        if not ns.DumpAPI then
            print("|cffff4444TransmogPalette:|r randomizer not loaded.")
            return
        end
        TransmogPaletteDB.apiDump = ns.DumpAPI()
        print(("|cff44ff44TransmogPalette:|r captured %d API lines. Now |cffffff00/reload|r."):format(#TransmogPaletteDB.apiDump))
        return
    end

    if msg and msg:lower():match("^buttons") then
        -- Which of the Transmogrifier's own slot buttons the randomizer found
        -- to hang its swatches on. "NOT FOUND" everywhere means the frame
        -- doesn't key its slot buttons on `transmogLocation` the way the scan
        -- assumes, and the layout needs re-probing with /fstack.
        if not ns.DumpSlotButtons then
            print("|cffff4444TransmogPalette:|r randomizer not loaded.")
            return
        end
        TransmogPaletteDB.slotButtonDump = ns.DumpSlotButtons()
        print(("|cff44ff44TransmogPalette:|r captured %d lines to SavedVariables. Now |cffffff00/reload|r and tell me it's done."):format(#TransmogPaletteDB.slotButtonDump))
        return
    end

    if msg and msg:lower():match("^pagetrace") then
        -- Records every page move AND its call stack while you reproduce the
        -- bug. Deliberately a toggle rather than always-on: one selection can
        -- fire several SetCollectionEntries passes, and an unbounded log would
        -- bury the one transition that matters.
        local ic = GetTransmogItemsFrame()
        if not ic then
            print("|cffff4444TransmogPalette:|r open the Transmogrifier first.")
            return
        end
        if pageTrace then
            TransmogPaletteDB.pageTrace = { when = date("%Y-%m-%d %H:%M:%S"), lines = pageTrace }
            local n = #pageTrace
            pageTrace = nil
            print(("|cff44ff44TransmogPalette:|r page trace OFF, %d lines. Now |cffffff00/reload|r."):format(n))
        else
            pageTrace = {}
            EnsurePageTraceHooks(ic)
            Trace("trace started: page=%s max=%s", tostring(CurrentPage(ic)), tostring(MaxPages(ic)))
            print("|cff44ff44TransmogPalette:|r page trace ON. Now go to page 2, select an appearance, then run |cffffff00/tmpalette pagetrace|r again.")
        end
        return
    end

    if msg and msg:lower():match("^paging") then
        -- Finds the getter/setter the filter needs so re-filtering stops
        -- throwing the player back to page 1. Must be run WITH A FILTER ON,
        -- SITTING ON PAGE 2 -- the getter is identified by reading back 2.
        TransmogPaletteDB.pagingDump = ns.DumpPaging()
        print(("|cff44ff44TransmogPalette:|r captured %d paging lines. Now |cffffff00/reload|r."):format(#TransmogPaletteDB.pagingDump))
        return
    end

    if msg and msg:lower():match("^buttons?probe") then
        -- Finds the frames that draw appearances, so right-click can be hooked
        -- to them. Run with a slot open and an appearance UNDER THE CURSOR.
        TransmogPaletteDB.buttonProbe = ns.DumpAppearanceButtons()
        print(("|cff44ff44TransmogPalette:|r captured %d lines. Now |cffffff00/reload|r."):format(#TransmogPaletteDB.buttonProbe))
        return
    end

    if msg and msg:lower():match("^menuprobe") then
        -- Toggle. Run once, right-click an appearance, run again, /reload.
        local captured = ns.ToggleMenuProbe()
        if captured then
            TransmogPaletteDB.menuProbe = captured
            print(("|cff44ff44TransmogPalette:|r menu probe OFF, %d lines. Now |cffffff00/reload|r."):format(#captured))
        else
            print("|cff44ff44TransmogPalette:|r menu probe ON. Right-click an appearance, then run |cffffff00/tmpalette menuprobe|r again.")
        end
        return
    end

    if msg and msg:lower():match("^matched") then
        -- Identification: which appearance is which. The grid renders the
        -- filtered list in order, so the Nth line here is the Nth tile on
        -- screen -- that is how a wrong-looking item gets turned into a
        -- visualID without any frame poking.
        local visuals = ns.GetCurrentVisuals()
        if not visuals or #visuals == 0 then
            print("|cffff4444TransmogPalette:|r nothing listed yet — open a slot first.")
            return
        end
        local out, shown = {}, 0
        for _, vid in ipairs(visuals) do
            if MatchesFilter(vid) then
                shown = shown + 1
                local ranks = ns.ItemColors[vid]
                local main, accent = ns.MainAndAccent(ranks, vid)
                local mainKey = main and ns.FilterClassify(main[1], main[2], main[3], main[5])
                local accentKey = accent and ns.FilterClassify(accent[1], accent[2], accent[3], accent[5])
                out[#out + 1] = ("%3d. visual %-7d main=%-12s accent=%-12s%s"):format(
                    shown, vid, tostring(mainKey), tostring(accentKey),
                    ns.OverrideFor(vid) and "  [OVERRIDDEN]" or "")
            end
        end
        TransmogPaletteDB.matchedDump = out
        print(("|cff44ff44TransmogPalette:|r %d appearances match. Grid order, written to SavedVariables — |cffffff00/reload|r to read it."):format(shown))
        for i = 1, math.min(#out, 10) do print("  " .. out[i]) end
        if #out > 10 then print(("  ... %d more in SavedVariables"):format(#out - 10)) end
        return
    end

    if msg and msg:lower():match("^override") then
        local rest = msg:match("^%S+%s+(.*)$")

        -- Dev mode decides WHICH layer is written. A player never turns it on,
        -- so their fixes can never be mistaken for shipping data -- and the
        -- author's staging entries can never silently ride along in someone
        -- else's SavedVariables as if they were personal choices.
        if rest == "dev" or rest == "dev on" or rest == "dev off" then
            local want = (rest == "dev") and (not TransmogPaletteDB.devOverrides)
                or (rest == "dev on")
            TransmogPaletteDB.devOverrides = want
            print(("|cff44ff44TransmogPalette:|r override dev mode %s — new overrides go to the |cffffff00%s|r layer."):format(
                want and "ON" or "OFF", want and "author (exportable)" or "player"))
            return
        end

        local overrides, layer = ns.OverrideStore()

        if rest == "export" then
            -- Emits Lua source for ns.ColorOverrides in Palette.lua. Only the
            -- AUTHOR layer is exported: a player's own fixes are theirs and
            -- must never leak into a release.
            local src = { "-- paste into ns.ColorOverrides in Palette.lua",
                          "ns.ColorOverrides = {" }
            local n = 0
            for vid, o in pairs(TransmogPaletteDB.authorOverrides) do
                local parts = {}
                for _, side in ipairs({ "main", "accent" }) do
                    local s = o[side]
                    if type(s) == "number" then
                        parts[#parts + 1] = ("%s = %d"):format(side, s)
                    elseif type(s) == "table" then
                        parts[#parts + 1] = ("%s = { %.1f, %.3f, %.3f%s }"):format(
                            side, s[1], s[2], s[3], s[4] and ", true" or "")
                    end
                end
                if #parts > 0 then
                    n = n + 1
                    src[#src + 1] = ("    [%d] = { %s },"):format(vid, table.concat(parts, ", "))
                end
            end
            src[#src + 1] = "}"
            TransmogPaletteDB.overrideExport = src
            print(("|cff44ff44TransmogPalette:|r exported %d author override(s) to TransmogPaletteDB.overrideExport. Now |cffffff00/reload|r and read it off disk."):format(n))
            return
        end

        if not rest or rest == "" or rest == "list" then
            -- Shows COMPUTED vs EFFECTIVE side by side. A bare list of stored
            -- values cannot answer the question that actually matters after a
            -- run of corrections -- "which of these did I get wrong?" -- because
            -- an override that merely agrees with the classifier looks exactly
            -- like one that fought it.
            local out, n = {}, 0
            for vid, o in pairs(overrides) do
                n = n + 1
                local ranks = ns.ItemColors[vid]
                local line
                if not ranks then
                    line = ("visual %-7d (no colour data -- this override does nothing)"):format(vid)
                else
                    local cm, ca = ns.ComputeMainAndAccent(ranks)
                    local em, ea = ns.MainAndAccent(ranks, vid)
                    local function key(c)
                        return c and ns.FilterClassify(c[1], c[2], c[3], c[5]) or "none"
                    end
                    line = ("visual %-7d main %s   accent %s"):format(vid,
                        o.main and ("%s -> |cffffff00%s|r"):format(key(cm), key(em)) or key(em),
                        o.accent and ("%s -> |cffffff00%s|r"):format(key(ca), key(ea)) or key(ea))
                end
                out[#out + 1] = line
                print("  " .. line)
            end
            TransmogPaletteDB.overrideList = out
            print(("|cff44ff44TransmogPalette:|r %d override(s) in the |cffffff00%s|r layer. An arrow shows what you changed it to."):format(n, layer))
            print("  |cffffff00/tmpalette override <visualID> main|accent off|r undoes one; |cffffff00/tmpalette override clear|r undoes all.")
            print("  Find a visualID with |cffffff00/tmpalette matched|r. Author staging: |cffffff00/tmpalette override dev|r, then |cffffff00... export|r.")
            return
        end

        if rest == "clear" then
            -- Clears only the ACTIVE layer, so an author clearing their staging
            -- area cannot wipe fixes they made as a player, or vice versa.
            if layer == "author" then
                TransmogPaletteDB.authorOverrides = {}
            else
                TransmogPaletteDB.colorOverrides = {}
            end
            ns.InvalidateSwatchPalettes()
            if ns.InvalidateRandomizerSlots then ns.InvalidateRandomizerSlots() end
            if ns.RefreshFilter then ns.RefreshFilter() end
            print(("|cff44ff44TransmogPalette:|r %s overrides cleared."):format(layer))
            return
        end

        local vid, side, value = rest:match("^(%d+)%s+(%a+)%s*(%S*)$")
        vid = tonumber(vid)
        if not vid or (side ~= "main" and side ~= "accent") then
            print("|cffff4444TransmogPalette:|r usage: |cffffff00/tmpalette override <visualID> main|accent <1-3|colourKey|off>|r")
            return
        end

        if value == "off" or value == "" then
            if overrides[vid] then
                overrides[vid][side] = nil
                if overrides[vid].main == nil and overrides[vid].accent == nil then
                    overrides[vid] = nil
                end
            end
            print(("|cff44ff44TransmogPalette:|r visual %d %s override removed."):format(vid, side))
        else
            local spec
            local index = tonumber(value)
            if index then
                -- A cluster index: the extractor found the right colour and
                -- only the ranking was wrong. Cheapest and most faithful form.
                local ranks = ns.ItemColors[vid]
                if not ranks or not ranks[index] then
                    print(("|cffff4444TransmogPalette:|r visual %d has no cluster %d."):format(vid, index))
                    return
                end
                spec = index
            else
                -- A bucket key: for a colour the extractor never found at all.
                -- Stored as the canonical h/s/v for that bucket, which is
                -- guaranteed to classify back into it, rather than as the key
                -- itself -- keys are grain-dependent, h/s/v is not.
                local h, s, v, ac = ns.CanonicalSwatch(value, ns.FilterGrain())
                if not h then
                    print(("|cffff4444TransmogPalette:|r '%s' is not a colour bucket at the current grain."):format(value))
                    return
                end
                spec = { h, s, v, ac }
            end
            overrides[vid] = overrides[vid] or {}
            overrides[vid][side] = spec
            print(("|cff44ff44TransmogPalette:|r visual %d %s set to %s (%s layer)."):format(
                vid, side, value, layer))
        end

        ns.OverridesChanged()
        return
    end

    if msg and msg:lower():match("^weaponcats") then
        -- Which categories each weapon slot is drawing from right now. The
        -- thing to run when weapon rolls work but only ever produce one or two
        -- weapon types.
        if not ns.DumpWeaponCategories then
            print("|cffff4444TransmogPalette:|r randomizer not loaded.")
            return
        end
        TransmogPaletteDB.weaponCatDump = ns.DumpWeaponCategories()
        print(("|cff44ff44TransmogPalette:|r captured %d lines. Now |cffffff00/reload|r."):format(#TransmogPaletteDB.weaponCatDump))
        return
    end

    if msg and msg:lower():match("^slots") then
        -- Per-slot candidate counts. A slot reporting 0 collected appearances
        -- means GetCategoryAppearances returned nothing for it -- an enum or
        -- signature problem, not an empty wardrobe -- and is the first thing
        -- to check when Roll does nothing.
        print("|cff44ff44TransmogPalette:|r per-slot roll candidates.")
        for _, slot in ipairs(ns.RandomizerSlots or {}) do
            local collected, matching, key = ns.GetSlotDebug(slot)
            print(("  %s: %d collected, %s"):format(slot.name, collected,
                key and ("%d match %s"):format(matching, key) or "(no colour assigned)"))
        end
        return
    end

    if msg and msg:lower():match("^hue") then
        -- Equal-width hue buckets are gone: hue is now split into perceptual
        -- bands of deliberately unequal width (see Palette.lua's HUE_BANDS),
        -- because equal slices crowded a quarter of all armor into one warm
        -- bucket that mixed red with brown. There is no single width left to
        -- set, so this reports the bands instead of pretending to tune them.
        local names = {}
        for i = 1, #ns.HueBands do names[i] = ns.HueBands[i][2] end
        print("|cff44ff44TransmogPalette:|r hue is bucketed by perceptual band, not a fixed width.")
        print("  bands: " .. table.concat(names, ", "))
        return
    end

    if msg and msg:lower():match("^entry") then
        -- The frame renders far fewer entries than it is handed, so one of
        -- these fields should say which ones it keeps (collected state being
        -- the prime suspect). Dumps scalars only; nested tables just show
        -- their type so the output stays readable.
        if not sampleEntry then
            print("|cffff4444TransmogPalette:|r no entry captured yet — open the Transmogrifier first.")
            return
        end
        -- Written to SavedVariables rather than printed: WoW's chat window
        -- can't be copied out of, so the dump gets read off disk instead.
        local dump = {}
        for k, v in pairs(sampleEntry) do
            local t = type(v)
            table.insert(dump, ("%s = %s (%s)"):format(tostring(k), t == "table" and "<table>" or tostring(v), t))
        end

        -- Nested tables are where a per-source collected flag would live.
        for k, v in pairs(sampleEntry) do
            if type(v) == "table" then
                for k2, v2 in pairs(v) do
                    if type(v2) ~= "table" then
                        table.insert(dump, ("%s.%s = %s (%s)"):format(tostring(k), tostring(k2), tostring(v2), type(v2)))
                    elseif type(k2) == "number" and k2 == 1 then
                        for k3, v3 in pairs(v2) do
                            if type(v3) ~= "table" then
                                table.insert(dump, ("%s[1].%s = %s (%s)"):format(tostring(k), tostring(k3), tostring(v3), type(v3)))
                            end
                        end
                    end
                end
            end
        end

        local vid = sampleEntry.visualID
        if vid and C_TransmogCollection then
            local itemID = ResolveItemIDFromVisualID(vid)
            if itemID and C_TransmogCollection.PlayerHasTransmog then
                table.insert(dump, ("API PlayerHasTransmog(item %d) = %s"):format(itemID, tostring(C_TransmogCollection.PlayerHasTransmog(itemID))))
            end
            if C_TransmogCollection.PlayerKnowsSource and C_TransmogCollection.GetAppearanceSources then
                local ok, sources = pcall(C_TransmogCollection.GetAppearanceSources, vid)
                if ok and sources and sources[1] then
                    for k, v in pairs(sources[1]) do
                        if type(v) ~= "table" then
                            table.insert(dump, ("API source[1].%s = %s (%s)"):format(tostring(k), tostring(v), type(v)))
                        end
                    end
                end
            end
        end

        -- Also tally, across the whole current list, how many entries each
        -- candidate boolean field is true for — the field whose true-count
        -- lands near the rendered total is the one the frame filters on.
        local visuals = ns.GetCurrentVisuals() or {}
        table.insert(dump, ("-- current list: %d entries"):format(#visuals))

        TransmogPaletteDB.entryDump = dump
        print(("|cff44ff44TransmogPalette:|r captured %d lines to SavedVariables. Now |cffffff00/reload|r and tell me it's done."):format(#dump))
        return
    end

    if msg and msg:lower():match("^tags") then
        if not ns.ToggleColorTags then
            print("|cffff4444TransmogPalette:|r colour tags are unavailable (ColorTags.lua did not load).")
            return
        end
        if msg:lower():match("^tags%s+probe") then
            if ns.ProbeColorTags then ns.ProbeColorTags() end
            return
        end
        local on, withData, total, tiles = ns.ToggleColorTags()
        print(("|cff44ff44TransmogPalette:|r colour tags %s."):format(
            on and "|cffffff00ON|r — each tile shows main / accent" or "OFF"))
        if on then
            if (tiles or 0) == 0 then
                print("  |cffff4444No tiles found.|r Open a gear slot so appearances are")
                print("  listed, then |cffffff00/tmpalette tags probe|r to see what's there.")
            end
            if total > 0 and withData < total then
                print(("  %d of %d listed appearances have no colour data and tag as |cffff4444no data|r."):format(
                    total - withData, total))
            end
        end
        return
    end

    if msg and msg:lower():match("^resetpos") then
        if ns.ResetStripPosition then ns.ResetStripPosition() end
        print("|cff44ff44TransmogPalette:|r colour strip moved back under the search box.")
        return
    end

    if msg and msg:lower():match("^debug") then
        -- Localizes count-vs-results disagreement: `passing` is what the
        -- addon believes matches, `handed to frame` is what it actually
        -- rendered. If those agree but the grid shows fewer, the frame is
        -- filtering further downstream (search box / Sources / pagination).
        local visuals = ns.GetCurrentVisuals() or {}
        local passing, noData = 0, 0
        for _, vid in ipairs(visuals) do
            if not ns.HasColorData(vid) then noData = noData + 1 end
            if MatchesFilter(vid) then passing = passing + 1 end
        end
        local st = ns.lastEntryStats or {}
        print(("|cff44ff44TransmogPalette debug:|r handed %d (collected %d, usable %d, both %d)."):format(st.total or -1, st.collected or -1, st.usable or -1, st.both or -1))
        print(("  of the %d rendered: %d lack color data, %d pass the filter. Last handed to frame: %d."):format(#visuals, noData, passing, lastFilteredCount or -1))
        local mains = {}
        for key in pairs(ns.state.primaryColors) do mains[#mains + 1] = key end
        table.sort(mains)
        print(("  grain: %s. mains (%d): %s"):format(
            ns.FilterGrain(), #mains, #mains > 0 and table.concat(mains, ", ") or "(none)"))
        print(("  accent: %s"):format(ns.state.accentColor and ns.state.accentColor.key or "(empty)"))
        return
    end

    -- Player-facing help. Development commands (dump, entry, buttons, api,
    -- watch, weapons, record) still work but are deliberately not advertised.
    local withData, total = ns.GetCoverage()
    print("|cff44ff44Transmog Palette|r")
    print("  Open the Transmogrifier. Click a colour swatch beside any gear slot to assign a colour, then press |cffffff00Roll|r for a random matching outfit. Nothing is spent until you press Apply.")
    print("  Right-click a swatch to clear it; right-click Roll to clear every slot.")
    print("  |cffffff00/tmpalette grain|r - how coarse the roll colours are (fine, medium, coarse, broad)")
    print("  |cffffff00/tmpalette roll|r - roll without clicking the button")
    print("  |cffffff00/tmpalette slots|r - what each slot can draw from")
    print("  |cffffff00/tmpalette tags|r - show or hide the colour chips on each appearance")
    print("  |cffffff00/tmpalette resetpos|r - put the colour strip back after dragging it")
    if total > 0 then
        print(("  colour data covers %d of the %d appearances currently listed."):format(withData, total))
    end
end
