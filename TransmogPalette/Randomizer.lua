local _, ns = ...

-- === Random outfit roller ===
-- Each slot gets a POOL of colours (one or several); pressing Roll picks a
-- random collected appearance per assigned slot from everything matching any
-- colour in its pool, and sets it pending on the Transmogrifier so the character
-- preview wears the whole outfit at once. Applying (and paying) is still
-- Blizzard's Apply button -- SetPending only stages, and the player should get
-- to look before committing gold.
--
-- Deliberately NOT sourced from Palette.lua's `currentVisuals`: that list is
-- whatever category the Transmogrifier happens to be showing, i.e. one slot.
-- A roll needs candidates for eleven slots at once, so each slot's list is
-- pulled straight from C_TransmogCollection.GetCategoryAppearances and cached.
-- Eligibility uses the same isCollected+isUsable rule the palette counts use,
-- so a swatch that says "12 appearances" can really produce twelve rolls.

local SLOTS = {
    { name = "Head",     invSlot = 1,  category = "Head" },
    { name = "Shoulders",invSlot = 3,  category = "Shoulder" },
    { name = "Back",     invSlot = 15, category = "Back" },
    { name = "Chest",    invSlot = 5,  category = "Chest" },
    { name = "Shirt",    invSlot = 4,  category = "Shirt" },
    { name = "Tabard",   invSlot = 19, category = "Tabard" },
    { name = "Wrists",   invSlot = 9,  category = "Wrist" },
    { name = "Hands",    invSlot = 10, category = "Hands" },
    { name = "Waist",    invSlot = 6,  category = "Waist" },
    { name = "Legs",     invSlot = 7,  category = "Legs" },
    { name = "Feet",     invSlot = 8,  category = "Feet" },
    -- Weapons have NO fixed category. Which collection types a weapon slot
    -- accepts depends on the weapon OPTION currently displayed (One Handed /
    -- Two Handed / Off Hand), and is class-filtered on top of that -- measured
    -- live 2026-08-10, see WeaponCategories. They also skip the "is something
    -- equipped" guard; see RollSlot.
    { name = "Main Hand", invSlot = 16, isWeapon = true },
    { name = "Off Hand",  invSlot = 17, isWeapon = true },
}

-- Resolved late: Enum.TransmogCollectionType is not guaranteed to exist at
-- file-load time on every client, and hardcoding the numbers would silently
-- roll the wrong slot if Blizzard ever renumbers the enum.
local function CategoryID(slot)
    local e = Enum and Enum.TransmogCollectionType
    return e and e[slot.category]
end

-- The Transmogrifier's own slot buttons, resolved once the frame exists.
-- Declared up here because the rolling code below needs them: each button is
-- the authority on its own slot, and the standalone API functions are not.
-- [slotID] = { frame, side }
local discovered = {}

local function SlotButton(slot)
    local entry = discovered[slot.invSlot]
    return entry and entry.frame
end

-- The BUTTON's own GetTransmogLocation, not the global one. Confirmed live:
-- TransmogUtil.GetTransmogLocation(1, Appearance, Main) returns nil, while the
-- Head button's own method returns slotID=1 type=0 mod=0. The global appears to
-- look up an already-registered location rather than build one.
local function TransmogLocation(slot)
    local btn = SlotButton(slot)
    if btn and btn.GetTransmogLocation then
        local ok, loc = pcall(btn.GetTransmogLocation, btn)
        if ok and type(loc) == "table" then return loc end
    end
    if TransmogUtil and TransmogUtil.GetTransmogLocation then
        local ok, loc = pcall(TransmogUtil.GetTransmogLocation, slot.invSlot,
            Enum.TransmogType.Appearance, Enum.TransmogModification.Main)
        if ok and type(loc) == "table" then return loc end
    end
    return nil
end

-- This build stages by OUTFIT SLOT (a 0-13 index), not by inventory slot. The
-- button's GetSlot() is the reliable source: confirmed by a captured live call,
-- where clicking a helm produced SetPendingTransmog(0, ...) and the Head
-- button's GetSlot() returns 0. C_TransmogOutfitInfo's own inventory-slot
-- mapper is only a fallback because it returned nil for Head, Tabard and Hands.
local function OutfitSlot(slot)
    local btn = SlotButton(slot)
    if btn and btn.GetSlot then
        local ok, outfitSlot = pcall(btn.GetSlot, btn)
        if ok and type(outfitSlot) == "number" then return outfitSlot end
    end
    if C_TransmogOutfitInfo and C_TransmogOutfitInfo.GetTransmogOutfitSlotFromInventorySlot then
        local ok, res = pcall(C_TransmogOutfitInfo.GetTransmogOutfitSlotFromInventorySlot, slot.invSlot)
        if ok and type(res) == "number" then return res end
    end
    return nil
end

-- === Candidates ===

local slotCandidates = {}  -- [invSlot] = { visualID, ... }
local slotPalettes = {}    -- [invSlot] = swatch list
local allSlotsPalette      -- see GetAllSlotsPalette

local function InvalidateSlots()
    slotCandidates = {}
    slotPalettes = {}
    allSlotsPalette = nil
end

ns.InvalidateRandomizerSlots = InvalidateSlots

-- Which weapon shape the slot is currently DISPLAYING, as a weaponOption
-- number. Read from the button's own GetCurrentWeaponOptionInfo(), confirmed
-- live 2026-08-10: with a two-handed weapon EQUIPPED but transmogged to a
-- one-handed axe, it correctly reports One Handed. That is the whole point --
-- the equipped item is the wrong thing to key on, because the displayed shape
-- is what the roll has to stay inside.
local function CurrentWeaponOption(slot)
    local btn = SlotButton(slot)
    if not btn or not btn.GetCurrentWeaponOptionInfo then return nil end
    local ok, info = pcall(btn.GetCurrentWeaponOptionInfo, btn)
    if ok and type(info) == "table" then return info.weaponOption, info.name end
    return nil
end

-- The collection types this weapon slot accepts RIGHT NOW.
--
-- C_TransmogCollection.GetCategoryAppearances ignores the transmogLocation it
-- is handed -- measured, both weapon buttons returned identical counts, and
-- armour categories returned their full lists too -- so it cannot answer this.
-- GetCollectionInfoForSlotAndOption can, and is the only thing that can.
--
-- Never hardcode the result. On the probed character main hand / One Handed
-- gave Fist, OneHAxe, Dagger, OneHMace, OneHSword, with Polearm and Warglaives
-- absent because the list is CLASS-FILTERED.
local function WeaponCategories(slot)
    local outfitSlot = OutfitSlot(slot)
    local weaponOption = CurrentWeaponOption(slot)
    if not outfitSlot or not weaponOption then return nil end
    if not (C_TransmogOutfitInfo and C_TransmogOutfitInfo.GetCollectionInfoForSlotAndOption) then
        return nil
    end
    local e = Enum and Enum.TransmogCollectionType
    if not e then return nil end

    local cats = {}
    for _, value in pairs(e) do
        local ok, info = pcall(C_TransmogOutfitInfo.GetCollectionInfoForSlotAndOption,
            outfitSlot, weaponOption, value)
        -- isWeapon guards against a non-weapon category answering; the off hand
        -- returns Holdable and nothing else, and armour types must not creep in.
        if ok and type(info) == "table" and info.isWeapon then
            cats[#cats + 1] = value
        end
    end
    return cats, weaponOption
end

local function CollectAppearances(category, loc, seen, list)
    if not (C_TransmogCollection and C_TransmogCollection.GetCategoryAppearances) then return end
    local ok, appearances
    if loc then
        ok, appearances = pcall(C_TransmogCollection.GetCategoryAppearances, category, loc)
    end
    if not ok or not appearances then
        ok, appearances = pcall(C_TransmogCollection.GetCategoryAppearances, category)
    end
    if not ok or not appearances then return end
    for _, a in ipairs(appearances) do
        -- Same eligibility rule as Palette.lua's IsRendered. An uncollected or
        -- class-restricted appearance can't be set pending, so including it
        -- would just make rolls fail at random.
        if a.visualID and a.isCollected and a.isUsable and not a.isHideVisual
            and not seen[a.visualID] then
            seen[a.visualID] = true
            list[#list + 1] = a.visualID
        end
    end
end

local function GetCandidates(slot)
    local cached = slotCandidates[slot.invSlot]
    -- A weapon slot's pool depends on the displayed shape, which the player can
    -- change without anything this addon hooks firing. Cheap to re-read, so the
    -- cache is validated against the live option rather than trusted.
    if cached and slot.isWeapon and cached.weaponOption ~= CurrentWeaponOption(slot) then
        cached = nil
        slotCandidates[slot.invSlot] = nil
        slotPalettes[slot.invSlot] = nil
    end
    if cached then return cached end

    if slot.isWeapon then
        local list = {}
        slotCandidates[slot.invSlot] = list
        local cats, weaponOption = WeaponCategories(slot)
        list.weaponOption = weaponOption
        if not cats then return list end
        -- Anything the slot legally accepts, pooled across every legal
        -- category -- the user's choice at spec time, re-confirmed 2026-08-10:
        -- a sword may roll into an axe. Deduped, since one visualID can appear
        -- under more than one category.
        local loc = TransmogLocation(slot)
        local seen = {}
        for _, category in ipairs(cats) do
            CollectAppearances(category, loc, seen, list)
        end
        return list
    end

    local list = {}
    slotCandidates[slot.invSlot] = list

    local category = CategoryID(slot)
    if not category then return list end
    CollectAppearances(category, TransmogLocation(slot), {}, list)
    return list
end

-- Colours are the filter's general colours (ns.MatchGroups), matched with the
-- filter's own rule: an appearance can be rolled for a colour when
-- ns.MatchScore says it matches (>= 1) -- learned scores where the appearance
-- was captured from the journal, closeness matching on ColorData otherwise.
-- One rule for both, so a colour that filters to twelve pieces rolls from
-- those same twelve. (The roller used to have its own coarse buckets from the
-- 1.2 classifier; saved slot colours from those are cleared by
-- ROLL_SCHEME_VERSION.)
local function Matches(vid, key)
    return ns.HasMatchData(vid) and (ns.MatchScore(vid, key) or 0) >= 1
end

-- A slot's pool is a SET of swatch keys: [key] = true for a colour to roll
-- from, [key] = "exclude" for one to keep out (a piece that also has it is
-- skipped). A pool of only exclusions rolls from everything else. A slot with
-- an empty set is unassigned.
local function SlotPool(slot)
    local set = ns.state.slotColors[slot.invSlot]
    return (type(set) == "table" and next(set)) and set or nil
end

-- The roller's own More / Less, separate from the strip's (Core.lua InitDB).
local function RollDetail()
    return ns.state.rollDetail == "all" and "all" or "general"
end

-- Pool keys in strip order, so names and stripes always read the same way:
-- the colours rolled from, or with `want` = "exclude" the excluded ones.
local function PoolKeys(set, want)
    want = want or true
    local out, listed = {}, {}
    for _, k in ipairs(ns.MatchStripKeys(RollDetail())) do
        if set[k.key] == want then
            out[#out + 1] = k.key
            listed[k.key] = true
        end
    end
    -- Keys from the other mode (General / Light and dark) still count.
    for key, v in pairs(set) do
        if v == want and not listed[key] then out[#out + 1] = key end
    end
    return out
end

local function PoolName(set)
    local function names(keys)
        local out = {}
        for _, key in ipairs(keys) do
            local info = ns.MatchKeyInfo(key)
            out[#out + 1] = info and info.name or key
        end
        return out
    end
    local wanted, excluded = names(PoolKeys(set)), names(PoolKeys(set, "exclude"))
    local text = #wanted > 0 and table.concat(wanted, " + ") or "Any colour"
    if #excluded > 0 then text = text .. ", not " .. table.concat(excluded, " / ") end
    return text
end

-- Identity of a pool, for "do all the slots share one".
local function PoolSignature(set)
    if not set then return "" end
    return table.concat(PoolKeys(set), "+") .. "|" .. table.concat(PoolKeys(set, "exclude"), "+")
end

local function CopyPool(set)
    local out = {}
    for key, v in pairs(set) do out[key] = v end
    return out
end

-- Every candidate matching ANY colour in the slot's pool, each once -- so a
-- gold and purple pool draws evenly from all the gold and purple pieces --
-- minus any that also match an excluded colour.
local function GetMatching(slot)
    local set = SlotPool(slot)
    if not set then return nil end
    local anyWanted = false
    for _, v in pairs(set) do
        if v == true then anyWanted = true break end
    end
    local out = {}
    for _, vid in ipairs(GetCandidates(slot)) do
        local ok = not anyWanted and ns.HasMatchData(vid)
        if anyWanted then
            for key, v in pairs(set) do
                if v == true and Matches(vid, key) then ok = true break end
            end
        end
        if ok then
            -- Looser than matching, like the strip's exclusions (Matching.lua).
            for key, v in pairs(set) do
                if v == "exclude" and ns.MatchExcluded(vid, key) then ok = false break end
            end
        end
        if ok then out[#out + 1] = vid end
    end
    return out
end

-- A palette entry per swatch of the roller's layout (General, or Light and
-- dark), in strip order, with its count. Every swatch is listed even at zero
-- -- the picker dims those -- so the layout never shifts between slots.
local function GroupPalette(count)
    local palette = {}
    for _, k in ipairs(ns.MatchStripKeys(RollDetail())) do
        local h, s, v = ns.RGBToHSV(k.r, k.g, k.b)
        palette[#palette + 1] = { key = k.key, h = h, s = s, v = v, count = count(k.key) }
    end
    return palette
end

local function GetSlotPalette(slot)
    -- GetCandidates FIRST for weapons, not the cache: it is what notices the
    -- displayed shape changed and drops the stale entries. Reading the palette
    -- cache before asking would hand back a One Handed palette while the slot
    -- is showing Two Handed -- swatch counts describing a pool the roll no
    -- longer draws from.
    if slot.isWeapon then GetCandidates(slot) end
    local cached = slotPalettes[slot.invSlot]
    if cached and cached.detail == RollDetail() then return cached end
    local candidates = GetCandidates(slot)
    local palette = GroupPalette(function(key)
        local n = 0
        for _, vid in ipairs(candidates) do
            if Matches(vid, key) then n = n + 1 end
        end
        return n
    end)
    palette.detail = RollDetail()
    slotPalettes[slot.invSlot] = palette
    return palette
end

-- The palette for "set every slot to one colour". Its count is the number of
-- SLOTS that can supply the colour, NOT the total appearances -- the question
-- this button asks is "can a full outfit be built in this colour", and 400
-- appearances all sitting in Chest answers that wrongly.
local function GetAllSlotsPalette()
    if allSlotsPalette and allSlotsPalette.detail == RollDetail() then return allSlotsPalette end
    allSlotsPalette = GroupPalette(function(key)
        local n = 0
        for _, slot in ipairs(SLOTS) do
            for _, vid in ipairs(GetCandidates(slot)) do
                if Matches(vid, key) then
                    n = n + 1
                    break
                end
            end
        end
        return n
    end)
    allSlotsPalette.detail = RollDetail()
    return allSlotsPalette
end

-- === Rolling ===

-- A visualID can be collected while the particular source backing it is not
-- (or is class-restricted), and only a collected source can be set pending --
-- so this returns nil rather than a sourceID the transmogrifier will reject,
-- and the roller moves on to another candidate.
-- Every failure path here returns a REASON STRING alongside the nil. The first
-- version returned a bare nil and wrapped the API calls in bare pcall, so a
-- failing SetPending was indistinguishable from "no matching appearance" -- and
-- since RollAll only printed when nothing at all was assigned, a roll where
-- every slot failed produced no output whatsoever. Silence is the one thing a
-- roll must never do.
-- One appearance can be backed by SEVERAL sources (different items sharing a
-- look), and they are not equally wearable: a class-locked tier piece is
-- collected and has no useError set, yet the client still refuses it and the
-- slot silently reverts to whatever is equipped. `isValidSourceForPlayer` is
-- the field that actually catches that -- checking only isCollected+useError
-- let those through. Returns nil when the source is fine, or why it isn't.
local function SourceRejection(s)
    if s.isCollected == false then return "not collected" end
    if s.isValidSourceForPlayer == false then return "not valid for player" end
    if s.canDisplayOnPlayer == false then return "cannot display on player" end
    if s.useError then return tostring(s.useError) end
    return nil
end

local function ResolveSourceID(visualID, slot)
    if not (C_TransmogCollection and C_TransmogCollection.GetAppearanceSources) then
        return nil, nil, "GetAppearanceSources API missing"
    end
    local category, loc = CategoryID(slot), TransmogLocation(slot)
    local ok, sources, err
    if category and loc then
        ok, sources = pcall(C_TransmogCollection.GetAppearanceSources, visualID, category, loc)
        if not ok then err = "GetAppearanceSources(3-arg): " .. tostring(sources) end
    end
    if not ok or type(sources) ~= "table" then
        ok, sources = pcall(C_TransmogCollection.GetAppearanceSources, visualID)
        if not ok then err = "GetAppearanceSources(1-arg): " .. tostring(sources) end
    end
    if not ok or type(sources) ~= "table" then
        return nil, nil, err or "no sources returned"
    end

    local rejected, lastWhy = 0, nil
    for _, s in ipairs(sources) do
        local why = SourceRejection(s)
        if not why then return s.sourceID, s.name end
        rejected, lastWhy = rejected + 1, why
    end
    return nil, nil, ("%d source(s) all rejected (last: %s)"):format(rejected, tostring(lastWhy))
end

-- Staging goes through C_TransmogOutfitInfo.SetPendingTransmog. C_Transmog on
-- this build has only 7 functions and SetPending is not among them -- the whole
-- pending system moved to the outfit namespace.
--
-- The argument shape is COPIED VERBATIM from a live call captured with
-- hooksecurefunc while clicking a helm in the Transmogrifier:
--
--   SetPendingTransmog(0, 0, 0, 308926, 1)
--
-- arg1 is the outfit slot (Head's GetSlot() is 0), arg3 is the weapon option
-- (see below) and arg4 is the sourceID. Arguments 2 and 5 were 0 and 1 and
-- their meanings are STILL NOT CONFIRMED, so they stay reproduced exactly as
-- observed rather than invented. Do not "tidy" them into named constants
-- without capturing more calls first -- guessing at this API is what cost four
-- wrong attempts, and arg3 was only pinned down by measuring.
local ARG2, ARG5 = 0, 1

-- ARG3 IS THE WEAPON OPTION. Established empirically 2026-08-10 by staging
-- with each candidate shape and reading the slot back: only arg3 moved it, off
-- hand 0 -> 267062, verified first try.
--
-- This is not a weapon special case, it is the general rule -- which is why the
-- original helm capture showed 0 there. Armour's weapon option IS 0, exactly as
-- Blizzard's own SetViewedWeaponOptionForSlot(slot, 0) on every armour slot
-- said. One shape covers both.
--
-- The symptom when it was wrong is worth remembering: staging returned success,
-- raised no error, and changed nothing at all -- 24 attempts with
-- GetEffectiveTransmogID identical before and after. A silent no-op, not a
-- rejection.
local function WeaponOptionArg(slot)
    return CurrentWeaponOption(slot) or 0
end

-- Forward-declared: used by the weapon diagnostic below, and defined alongside
-- PendingTook.
local ReadEffectiveID

-- Per-roll weapon trace, written to SavedVariables by RollAll. Deliberately
-- WIPED at the start of every RollAll: rollDiag persists forever and has
-- already been misread once as a live failure when it was months stale.
local weaponDiag = {}

local function StageRaw(outfitSlot, a2, a3, sourceID)
    -- Flagged purely so /tmpalette watch can tell our staging apart from
    -- Blizzard's; see InstallWatches. Cleared in all paths, including the
    -- error one, or every later Blizzard call would be mislabelled as ours.
    ns.stagingFromAddon = true
    local ok, err = pcall(C_TransmogOutfitInfo.SetPendingTransmog,
        outfitSlot, a2, a3, sourceID, ARG5)
    ns.stagingFromAddon = nil
    return ok, err
end

local function SetPendingAppearance(slot, sourceID)
    if not (C_TransmogOutfitInfo and C_TransmogOutfitInfo.SetPendingTransmog) then
        return false, "C_TransmogOutfitInfo.SetPendingTransmog missing"
    end
    local outfitSlot = OutfitSlot(slot)
    if not outfitSlot then
        return false, ("no outfit slot for %s (button %s)"):format(
            slot.name, SlotButton(slot) and "found" or "NOT found")
    end

    -- One shape for everything: arg3 is the weapon option, and armour's is 0.
    local ok, err = StageRaw(outfitSlot, ARG2, WeaponOptionArg(slot), sourceID)
    if not ok then return false, "SetPendingTransmog: " .. tostring(err) end
    return true
end

-- The raw read-back value, whatever it is. PendingTook turns this into a
-- verdict; the diagnostic wants the number itself.
function ReadEffectiveID(slot)
    local btn = SlotButton(slot)
    if not (btn and btn.GetEffectiveTransmogID) then return nil end
    local ok, id = pcall(btn.GetEffectiveTransmogID, btn)
    if not ok then return nil end
    return id
end

-- Reads the slot back after staging, to confirm the client kept what was set.
-- Returns true, false, or nil when it can't be determined -- and nil must be
-- treated as "assume it worked", since a slot that can't be read back is not
-- evidence of failure.
local function PendingTook(slot, sourceID)
    local btn = SlotButton(slot)
    if not (btn and btn.GetEffectiveTransmogID) then return nil end
    local ok, id = pcall(btn.GetEffectiveTransmogID, btn)
    if not ok or type(id) ~= "number" then return nil end
    return id == sourceID
end

-- A slot can hold hundreds of matching appearances (Shirt reported 902), and
-- each attempt costs an API call plus a staging call, so the search is bounded.
-- Rejections are rare once sources are filtered, so this is generous.
local MAX_ROLL_ATTEMPTS = 12

-- Rolls one slot. Candidates are tried in random order rather than picking one
-- index and giving up: a slot whose only unusable source happened to be drawn
-- would otherwise report "no match" while eleven valid appearances sat behind
-- it. Returns the visualID set, or nil plus a reason.
local function RollSlot(slot)
    local matching = GetMatching(slot)
    if not matching then return nil, "unassigned" end
    if #matching == 0 then return nil, "nomatch" end

    -- Transmog replaces the look of an EQUIPPED item; with the slot empty
    -- there is nothing to restyle and SetPending quietly does nothing. Say so
    -- instead, or an empty shirt slot reads as a broken roller.
    --
    -- NOT for weapons. A two-handed weapon leaves inventory slot 17 physically
    -- empty while the off hand still displays -- and transmogs -- perfectly
    -- well; measured live 2026-08-10, equippedItemID=nil on an off hand that
    -- was showing a transmog. This guard would have silently disabled it.
    if not slot.isWeapon and not GetInventoryItemID("player", slot.invSlot) then
        return nil, "empty"
    end

    -- Fisher-Yates over a copy; order is consumed, so shuffling in place would
    -- reorder nothing that outlives the call.
    local pool = {}
    for i = 1, #matching do pool[i] = matching[i] end
    for i = #pool, 2, -1 do
        local j = math.random(i)
        pool[i], pool[j] = pool[j], pool[i]
    end

    local lastErr
    local fallbackVid, fallbackName, fallbackSource
    local attempts = 0

    for _, vid in ipairs(pool) do
        if attempts >= MAX_ROLL_ATTEMPTS then break end
        local sourceID, name, srcErr = ResolveSourceID(vid, slot)
        if sourceID then
            attempts = attempts + 1
            local before = ReadEffectiveID(slot)
            local ok, setErr = SetPendingAppearance(slot, sourceID)
            -- Weapons only, and only while the first weapon roll is unproven:
            -- every weapon attempt is recorded with what the slot read back, so
            -- "the client reverted it" can be told apart from "the read-back
            -- reports something other than a sourceID for weapons". Guessing
            -- between those two is exactly what this project keeps paying for.
            if slot.isWeapon then
                local optNum, optName = CurrentWeaponOption(slot)
                weaponDiag[#weaponDiag + 1] = ("%s opt=%s(%s) src=%s ok=%s before=%s after=%s"):format(
                    slot.name, tostring(optNum), tostring(optName),
                    tostring(sourceID), tostring(ok), tostring(before),
                    tostring(ReadEffectiveID(slot)))
            end
            if ok then
                -- Staging can "succeed" and then be quietly reverted by the
                -- client -- a class-locked tier piece leaves the slot showing
                -- whatever is equipped. Reading the slot back catches that, and
                -- catches any OTHER rejection reason too, rather than only the
                -- ones there happens to be a flag for.
                if PendingTook(slot, sourceID) ~= false then
                    return vid, nil, name
                end
                if not fallbackVid then
                    fallbackVid, fallbackName, fallbackSource = vid, name, sourceID
                end
                lastErr = "client reverted the staged appearance"
            else
                lastErr = setErr
            end
        else
            lastErr = srcErr
        end
    end

    -- Nothing verified as taking. Re-stage the first one that at least didn't
    -- error, so this is never WORSE than it was before the check existed --
    -- the read-back is a best effort and must not turn a working roll into a
    -- failed one if it reports unreliably.
    if fallbackVid then
        SetPendingAppearance(slot, fallbackSource)
        return fallbackVid, nil, fallbackName
    end
    return nil, "nosource", nil, lastErr
end

local lastRoll = {}  -- [invSlot] = { visualID, name } | { failed = reason }

-- Written to SavedVariables by /tmpalette roll so a failing roll can be read off
-- disk (WoW chat can't be copied out of).
ns.lastRollDiag = nil

local REASON_TEXT = {
    nomatch = "nothing collected in that colour",
    empty = "nothing equipped in that slot",
    nosource = "no usable source",
}

-- The last failure summary printed, so an unchanged one isn't reprinted on
-- every roll. Cleared whenever a roll fully succeeds, so a NEW failure after a
-- good run is always announced.
local lastFailureSummary

local function RollAll(verbose)
    if not (TransmogFrame and TransmogFrame:IsShown()) then
        print("|cffff4444TransmogPalette:|r open the Transmogrifier before rolling - appearances can only be staged there.")
        return
    end

    -- Re-resolve the slot buttons before rolling. They are pooled and re-laid
    -- out by things this code doesn't hook (ignoring a slot, for one), and a
    -- stale mapping here doesn't just mis-place a swatch -- it stages an
    -- appearance onto the wrong slot. Cheap enough at one frame-tree walk per
    -- click, and it makes the roll correct regardless of what moved.
    if ns.ReattachSwatches then ns.ReattachSwatches() end

    -- Fresh every roll, and written unconditionally below -- including on a
    -- SUCCESSFUL roll, unlike rollDiag. A weapon roll that "worked" but landed
    -- on the fallback is exactly the case worth seeing.
    wipe(weaponDiag)

    local rolled, missing, assigned = 0, 0, 0
    local failures = {}

    -- Records which of the staging APIs actually exist on this build, since a
    -- missing one would make every slot fail identically and is the cheapest
    -- thing to rule out.
    local sampleLoc = TransmogLocation(SLOTS[1])
    local diag = { ("API: SetPendingTransmog=%s CommitAndApply=%s | Head outfitSlot=%s loc=%s category=%s"):format(
        type(C_TransmogOutfitInfo and C_TransmogOutfitInfo.SetPendingTransmog),
        type(C_TransmogOutfitInfo and C_TransmogOutfitInfo.CommitAndApplyAllPending),
        tostring(OutfitSlot(SLOTS[1])),
        sampleLoc and ("slotID=" .. tostring(sampleLoc.slotID)) or "nil",
        tostring(CategoryID(SLOTS[1]))) }

    for _, slot in ipairs(SLOTS) do
        local vid, reason, name, detail = RollSlot(slot)
        if reason ~= "unassigned" then assigned = assigned + 1 end

        if vid then
            lastRoll[slot.invSlot] = { visualID = vid, name = name }
            rolled = rolled + 1
            diag[#diag + 1] = ("%s: OK visual=%d %s"):format(slot.name, vid, name or "?")
        elseif reason == "unassigned" then
            lastRoll[slot.invSlot] = nil
        else
            lastRoll[slot.invSlot] = { failed = reason }
            missing = missing + 1
            failures[reason] = (failures[reason] or 0) + 1
            local pool = SlotPool(slot)
            local matching = GetMatching(slot)
            -- Assigned to a local FIRST: on an empty slot GetInventoryItemID
            -- returns no values at all rather than nil, and `tostring(f())`
            -- then passes tostring zero arguments, which is a hard error. The
            -- assignment is what coerces "nothing" into nil.
            local equipped = GetInventoryItemID("player", slot.invSlot)
            diag[#diag + 1] = ("%s: FAILED %s | colour=%s candidates=%d matching=%d equipped=%s | %s"):format(
                slot.name, reason, pool and table.concat(PoolKeys(pool), "+") or "nil",
                #GetCandidates(slot), matching and #matching or -1,
                tostring(equipped), tostring(detail))
        end
    end

    -- Always persisted, and stamped, so it can never be mistaken for a stale
    -- capture the way rollDiag was.
    if TransmogPaletteDB then
        TransmogPaletteDB.weaponDiag = {
            when = date and date("%Y-%m-%d %H:%M:%S") or "?",
            attempts = weaponDiag,
        }
    end

    -- A roll that WORKED says nothing: the character preview changing is the
    -- feedback, and a line of chat on every button press is just noise. Anything
    -- that did NOT work still speaks up -- the original bug here was a button
    -- that silently did nothing, and that must never be possible again.
    -- `verbose` is set by /tmpalette roll, where the player asked explicitly and
    -- a confirmation is wanted.
    if assigned == 0 then
        print("|cffff4444TransmogPalette:|r assign a colour to at least one slot first (click the swatch next to a gear slot).")
    elseif missing == 0 then
        lastFailureSummary = nil
        if verbose then
            print(("|cff44ff44TransmogPalette:|r rolled %d slot%s. Press Apply to commit."):format(rolled, rolled == 1 and "" or "s"))
        end
    else
        local parts = {}
        for reason, n in pairs(failures) do
            parts[#parts + 1] = ("%d %s"):format(n, REASON_TEXT[reason] or reason)
        end
        -- Sorted so the summary string is stable: pairs() order is not, and an
        -- unstable string would defeat the repeat check below.
        table.sort(parts)
        local summary = table.concat(parts, ", ")

        -- Repeated identical failures stay quiet. A slot that can never succeed
        -- -- an assigned colour with nothing equipped, say -- would otherwise
        -- reprint on every single press, which is the same noise problem as
        -- announcing success. The swatch already carries a red rim and the
        -- reason in its tooltip, so the state is still visible.
        if verbose or summary ~= lastFailureSummary then
            print(("|cffff8800TransmogPalette:|r rolled %d of %d - %s."):format(rolled, assigned, summary))
        end
        lastFailureSummary = summary
    end

    ns.lastRollDiag = diag
    ns.lastRollFailed = missing > 0
    ns.RefreshRandomizerPanel()
end

-- === UI ===
--
-- The colour swatches sit NEXT TO the Transmogrifier's own slot buttons rather
-- than in a panel of their own. A side panel was built first and the
-- Transmogrifier drew over it; layering aside, it also duplicated a slot list
-- the player is already looking at.
--
-- Blizzard's slot buttons are found by WALKING TransmogFrame's children for a
-- `transmogLocation` field, never by hardcoded global names. That field is what
-- the transmog UI keys its own slot buttons on, so the search survives the
-- frame being renamed or restructured -- which matters here, since the path to
-- ItemsFrame already had to be found with /fstack rather than read from docs.

local SWATCH_SIZE = 16

-- Shared by Roll and Single Color so the two read as one column. 74 was Roll's
-- own width and was too narrow for any label longer than "Roll" -- "All one
-- colour" overflowed it visibly.
local BUTTON_WIDTH = 92

local slotSwatches = {}   -- [invSlot] = our swatch button
local rollButton, allButton, registered
-- `discovered` is declared near the top of the file, not here: the rolling code
-- above needs the buttons to resolve each slot's outfit index and location.

-- === Finding Blizzard's slot buttons ===

-- The slot buttons are identified by POSITION, because on this build there is
-- nothing else to identify them by. A live dump of TransmogFrame reported
-- "0 frames carry a transmogLocation", and every slot button is unnamed. What
-- the dump did show is an unambiguous geometry: eleven 59x59 buttons under
-- CharacterPreview in two evenly-spaced columns --
--
--   x=586   y = 777 713 649 585 520 456 393   (7)
--   x=1129  y = 680 617 553 489               (4)
--   x=825, x=889 at y=232                     main hand / off hand, ignored
--
-- which is the standard transmog layout. Order within each column is top to
-- bottom, i.e. DESCENDING y (WoW measures y upward from the screen bottom).
local LEFT_COLUMN  = { "Head", "Shoulders", "Back", "Chest", "Shirt", "Tabard", "Wrists" }
local RIGHT_COLUMN = { "Hands", "Waist", "Legs", "Feet" }

local SLOT_BY_NAME = {}
for _, slot in ipairs(SLOTS) do SLOT_BY_NAME[slot.name] = slot end

-- The weapon buttons are the same size as the armour ones, so size alone can't
-- exclude them -- but they sit alone in their own x positions, while every
-- armour button shares a column with at least three others.
local BUTTON_MIN_SIZE, BUTTON_MAX_SIZE = 50, 70
local COLUMN_TOLERANCE = 8
local MIN_COLUMN_MEMBERS = 4

local function ScanRoot()
    return (TransmogFrame and TransmogFrame.CharacterPreview) or TransmogFrame
end

local SLOT_BY_INVSLOT = {}
for _, slot in ipairs(SLOTS) do SLOT_BY_INVSLOT[slot.invSlot] = slot end

-- Returns invSlot -> { frame, side }, or nil plus a reason.
--
-- Identity comes from each button's own GetTransmogLocation().slotID, so a
-- PARTIAL result is safe here and the old "must be exactly 7+4 buttons" rule is
-- gone. That rule existed to protect the positional fallback, but it made the
-- resolver REFUSE to map whenever an outfit hid some slots -- leaving the
-- previous, now-stale mapping in place, which is why Roll worked on only some
-- slots on a character with slots ignored.
--
-- Re-resolving matters because the slot buttons are POOLED (they expose Init
-- and Release): switching outfits hands a frame to a different slot, so a
-- mapping captured earlier can silently point at the wrong slot.
local function ResolveSlotButtons()
    local root = ScanRoot()
    if not root then return nil, "TransmogFrame.CharacterPreview not found" end

    local buttons = {}
    local function walk(frame, depth)
        if not frame or depth > 9 then return end
        local ok, kids = pcall(function() return { frame:GetChildren() } end)
        if not ok then return end
        for _, child in ipairs(kids) do
            local t = child:GetObjectType()
            local w, h = child:GetWidth() or 0, child:GetHeight() or 0
            local x, y = child:GetCenter()
            if (t == "Button" or t == "ItemButton" or t == "CheckButton") and x and y
                and w >= BUTTON_MIN_SIZE and w <= BUTTON_MAX_SIZE
                and h >= BUTTON_MIN_SIZE and h <= BUTTON_MAX_SIZE then
                buttons[#buttons + 1] = { frame = child, x = x, y = y }
            end
            walk(child, depth + 1)
        end
    end
    walk(root, 0)

    if #buttons == 0 then return nil, "no slot-sized buttons under CharacterPreview" end

    -- Preferred path: ask every button which slot it is. Buttons for slots we
    -- don't handle (the two weapons) simply don't match SLOT_BY_INVSLOT and are
    -- dropped, so no column-counting is needed to exclude them.
    local map, mapped = {}, {}
    for _, b in ipairs(buttons) do
        if b.frame.GetTransmogLocation then
            local ok, loc = pcall(b.frame.GetTransmogLocation, b.frame)
            -- The type check matters now that weapons are handled: an ILLUSION
            -- button shares its weapon's slotID and would otherwise claim the
            -- slot. Illusion buttons are 42x41 and so are already excluded by
            -- size, but that is a coincidence of this build's art, not a rule --
            -- and the user asked for illusions to be left alone.
            local isAppearance = not (Enum and Enum.TransmogType)
                or (type(loc) == "table" and loc.type == Enum.TransmogType.Appearance)
            if ok and type(loc) == "table" and loc.slotID and SLOT_BY_INVSLOT[loc.slotID]
                and isAppearance then
                map[loc.slotID] = { frame = b.frame }
                mapped[#mapped + 1] = { slotID = loc.slotID, x = b.x }
            end
        end
    end

    if #mapped > 0 then
        -- Side is still positional -- it only decides which way the swatch
        -- faces -- but it's measured across the buttons actually found, so it
        -- stays correct when an outfit hides some of them.
        local minX, maxX = mapped[1].x, mapped[1].x
        for _, m in ipairs(mapped) do
            if m.x < minX then minX = m.x end
            if m.x > maxX then maxX = m.x end
        end
        local midX = (minX + maxX) / 2
        for _, m in ipairs(mapped) do
            map[m.slotID].side = (m.x > midX) and "right" or "left"
        end
        return map
    end

    -- Group into columns by x.
    table.sort(buttons, function(a, b) return a.x < b.x end)
    local columns, current = {}, nil
    for _, b in ipairs(buttons) do
        if current and math.abs(b.x - current.x) <= COLUMN_TOLERANCE then
            current.items[#current.items + 1] = b
        else
            current = { x = b.x, items = { b } }
            columns[#columns + 1] = current
        end
    end

    local armour = {}
    for _, c in ipairs(columns) do
        if #c.items >= MIN_COLUMN_MEMBERS then armour[#armour + 1] = c end
    end
    if #armour ~= 2 then
        return nil, ("expected 2 armour columns, found %d (from %d buttons)"):format(#armour, #buttons)
    end

    local left, right = armour[1], armour[2]
    if #left.items ~= #LEFT_COLUMN or #right.items ~= #RIGHT_COLUMN then
        return nil, ("column sizes %d/%d, expected %d/%d"):format(
            #left.items, #right.items, #LEFT_COLUMN, #RIGHT_COLUMN)
    end

    table.sort(left.items, function(a, b) return a.y > b.y end)
    table.sort(right.items, function(a, b) return a.y > b.y end)

    -- Reached only if NO button exposed its own location. Falls back to the
    -- measured order -- Tabard before Shirt, as the live client reported it,
    -- not the order that seems natural.
    local map2 = {}
    for i, name in ipairs(LEFT_COLUMN) do
        local slot = SLOT_BY_NAME[name]
        if slot and left.items[i] then
            map2[slot.invSlot] = { frame = left.items[i].frame, side = "left" }
        end
    end
    for i, name in ipairs(RIGHT_COLUMN) do
        local slot = SLOT_BY_NAME[name]
        if slot and right.items[i] then
            map2[slot.invSlot] = { frame = right.items[i].frame, side = "right" }
        end
    end
    return map2
end

local lastResolveError

-- REPLACES the mapping wholesale rather than merging into it. Merging left
-- entries from a previous outfit pointing at pooled buttons that now belong to
-- other slots.
local function ScanForSlotButtons()
    local map, err = ResolveSlotButtons()
    lastResolveError = err
    if not map then return end
    wipe(discovered)
    for invSlot, entry in pairs(map) do
        discovered[invSlot] = entry
    end
end

-- Everything needed to work out the real slot->button mapping in ONE round
-- trip, since each one costs the user a /reload: what each location actually
-- holds, where the frame sits on screen (so a positional mapping is possible if
-- slotID turns out to be useless), and the geometry the placement maths used.
function ns.DumpSlotButtons()
    local lines = {}

    local function geom(f)
        local x, y = f:GetCenter()
        return ("x=%s y=%s w=%s h=%s"):format(
            x and math.floor(x) or "nil", y and math.floor(y) or "nil",
            math.floor(f:GetWidth() or 0), math.floor(f:GetHeight() or 0))
    end

    if TransmogFrame then
        lines[#lines + 1] = "TransmogFrame " .. geom(TransmogFrame)
        lines[#lines + 1] = "CharacterPreview = " ..
            (TransmogFrame.CharacterPreview and geom(TransmogFrame.CharacterPreview) or "MISSING")
    else
        lines[#lines + 1] = "TransmogFrame = nil"
    end

    -- Structural map first: if the slot buttons aren't where they were expected,
    -- the next question is immediately "then what IS under there".
    local function listChildren(frame, label)
        lines[#lines + 1] = "-- direct children of " .. label
        if not frame then
            lines[#lines + 1] = "   (frame is nil)"
            return
        end
        local ok, kids = pcall(function() return { frame:GetChildren() } end)
        if not ok then
            lines[#lines + 1] = "   (GetChildren failed)"
            return
        end
        for i, c in ipairs(kids) do
            lines[#lines + 1] = ("   %d: %s [%s] %s shown=%s"):format(
                i, c:GetName() or "<unnamed>", c:GetObjectType(), geom(c), tostring(c:IsShown()))
        end
    end
    listChildren(TransmogFrame, "TransmogFrame")
    listChildren(TransmogFrame and TransmogFrame.CharacterPreview, "TransmogFrame.CharacterPreview")

    -- The resolved mapping: a positional mapping is only as good as the assumed
    -- column order, so this is the thing to check against the swatch tooltips
    -- in game.
    local map, err = ResolveSlotButtons()
    if map then
        lines[#lines + 1] = "-- resolved slot -> button"
        for _, slot in ipairs(SLOTS) do
            local e = map[slot.invSlot]
            lines[#lines + 1] = ("   %s invSlot=%d %s"):format(slot.name, slot.invSlot,
                e and (e.side .. " column, " .. geom(e.frame)) or "UNMAPPED")
        end
    else
        lines[#lines + 1] = "-- resolve FAILED: " .. tostring(err)
    end

    -- Widened well past what the production scan keys on: transmogLocation may
    -- simply not be the field this build uses, so anything carrying a plausible
    -- slot identity is worth seeing before guessing again.
    local FIELDS = { "transmogLocation", "slotID", "transmogSlot", "slot", "itemLocation", "hasPending" }
    lines[#lines + 1] = "-- frames carrying any slot-ish field, anywhere under TransmogFrame"
    local hits = 0
    local function walkFields(frame, depth, path)
        if not frame or depth > 9 or hits > 150 then return end
        local ok, kids = pcall(function() return { frame:GetChildren() } end)
        if not ok then return end
        for _, child in ipairs(kids) do
            local name = child:GetName() or "<unnamed>"
            local bits = {}
            for _, field in ipairs(FIELDS) do
                local v = child[field]
                if v ~= nil then
                    if type(v) == "table" then
                        bits[#bits + 1] = ("%s={slotID=%s,type=%s,mod=%s}"):format(field,
                            tostring(v.slotID), tostring(v.type), tostring(v.modification))
                    else
                        bits[#bits + 1] = ("%s=%s"):format(field, tostring(v))
                    end
                end
            end
            if #bits > 0 then
                hits = hits + 1
                lines[#lines + 1] = ("FLD %s [%s] %s %s path=%s"):format(
                    name, child:GetObjectType(), geom(child), table.concat(bits, " "), path)
            end
            walkFields(child, depth + 1, path .. "/" .. name)
        end
    end
    walkFields(TransmogFrame, 0, "TF")

    -- Backstop: if no field identifies them, size and screen position are the
    -- remaining signal, and 11 buttons in two columns is a recognisable shape.
    -- Rooted at TransmogFrame, NOT the production scan root -- the whole point
    -- is to see what the narrower scan is missing.
    lines[#lines + 1] = "-- button-shaped frames (30-90px wide), anywhere under TransmogFrame"
    local n = 0
    local function walkButtons(frame, depth, path)
        if not frame or depth > 9 or n > 150 then return end
        local ok, kids = pcall(function() return { frame:GetChildren() } end)
        if not ok then return end
        for _, child in ipairs(kids) do
            local w = child:GetWidth() or 0
            local t = child:GetObjectType()
            if (t == "Button" or t == "CheckButton" or t == "ItemButton") and w >= 30 and w <= 90 and child:IsShown() then
                n = n + 1
                lines[#lines + 1] = ("BTN %s [%s] %s path=%s"):format(child:GetName() or "<unnamed>", t, geom(child), path)
            end
            walkButtons(child, depth + 1, path .. "/" .. (child:GetName() or "?"))
        end
    end
    walkButtons(TransmogFrame, 0, "TF")

    return lines
end

-- Weapons: what the client considers a legal option for each weapon slot, and
-- which outfit slot each weapon button is. Written rather than guessed because
-- GetWeaponOptionsForSlot's return shape is unknown, and every previous
-- assumption about this API has been wrong.
local Describe
Describe = function(v, depth)
    depth = depth or 0
    if type(v) ~= "table" then return tostring(v) end
    if depth > 2 then return "<table>" end
    local n = #v
    if n > 0 then
        local parts = {}
        for i = 1, math.min(n, 4) do parts[#parts + 1] = Describe(v[i], depth + 1) end
        return ("[%d]{%s%s}"):format(n, table.concat(parts, ", "), n > 4 and ", ..." or "")
    end
    local keys = {}
    for k, val in pairs(v) do
        keys[#keys + 1] = ("%s=%s"):format(tostring(k), Describe(val, depth + 1))
    end
    table.sort(keys)
    return "{" .. table.concat(keys, ", ") .. "}"
end

-- What the roller is ACTUALLY drawing from for each weapon slot right now:
-- the live option, every category the client says that option accepts, and how
-- many collected/usable appearances each one contributes. If a weapon type is
-- missing from rolls, this says whether the category was never offered
-- (GetCollectionInfoForSlotAndOption declined it) or was offered and had no
-- usable appearances -- two different problems with two different fixes.
function ns.DumpWeaponCategories()
    local lines = {}

    -- Re-resolve FIRST. The slot buttons are pooled, so a mapping captured
    -- earlier can point at a frame that now belongs to a different slot --
    -- RollAll re-resolves before every roll for this exact reason. Without it
    -- this dump reported Main Hand with the off hand's outfit slot.
    if not (TransmogFrame and TransmogFrame:IsShown()) then
        lines[#lines + 1] = "!! Transmogrifier is not open -- open it at an NPC and run this again."
        return lines
    end
    ScanForSlotButtons()

    for _, slot in ipairs(SLOTS) do
        if slot.isWeapon then
            local optNum, optName = CurrentWeaponOption(slot)
            local outfitSlot = OutfitSlot(slot)
            lines[#lines + 1] = ("%s: outfitSlot=%s option=%s (%s)"):format(
                slot.name, tostring(outfitSlot), tostring(optNum), tostring(optName))

            local e = Enum and Enum.TransmogCollectionType
            if not e or not outfitSlot or not optNum then
                lines[#lines + 1] = "   cannot resolve -- button not found or option unreadable"
            else
                local names = {}
                for name, value in pairs(e) do names[value] = name end
                local accepted = WeaponCategories(slot) or {}
                local acceptedSet = {}
                for _, v in ipairs(accepted) do acceptedSet[v] = true end

                -- Every category, not just the accepted ones, so a type that is
                -- being silently declined is visible rather than absent.
                local ordered = {}
                for _, value in pairs(e) do ordered[#ordered + 1] = value end
                table.sort(ordered)
                for _, value in ipairs(ordered) do
                    local seen, list = {}, {}
                    CollectAppearances(value, nil, seen, list)
                    if acceptedSet[value] or #list > 0 then
                        lines[#lines + 1] = ("   %-12s (%2d) accepted=%s usable=%d"):format(
                            names[value] or "?", value, acceptedSet[value] and "YES" or "no", #list)
                    end
                end
                lines[#lines + 1] = ("   -> pooled candidates: %d"):format(#GetCandidates(slot))
                local pool = SlotPool(slot)
                local matching = GetMatching(slot)
                lines[#lines + 1] = ("   -> colours=%s matching=%s"):format(
                    pool and table.concat(PoolKeys(pool), "+") or "(none)", matching and #matching or "n/a")
            end
        end
    end
    return lines
end

function ns.DumpWeapons()
    local lines = {}

    -- Every slot-sized button with its real identity, so the two weapon
    -- buttons can be told apart from the armour ones.
    lines[#lines + 1] = "-- all slot-sized buttons under CharacterPreview"
    local root = ScanRoot()
    local function walk(frame, depth)
        if not frame or depth > 9 then return end
        local ok, kids = pcall(function() return { frame:GetChildren() } end)
        if not ok then return end
        for _, child in ipairs(kids) do
            local w, h = child:GetWidth() or 0, child:GetHeight() or 0
            local x, y = child:GetCenter()
            local t = child:GetObjectType()
            if (t == "Button" or t == "ItemButton" or t == "CheckButton") and x and y
                and w >= 50 and w <= 70 and h >= 50 and h <= 70 then
                local slotID, outfitSlot = "?", "?"
                if child.GetTransmogLocation then
                    local ok2, loc = pcall(child.GetTransmogLocation, child)
                    if ok2 and type(loc) == "table" then slotID = tostring(loc.slotID) end
                end
                if child.GetSlot then
                    local ok3, s = pcall(child.GetSlot, child)
                    if ok3 then outfitSlot = tostring(s) end
                end
                lines[#lines + 1] = ("BTN x=%d y=%d slotID=%s outfitSlot=%s"):format(
                    math.floor(x), math.floor(y), slotID, outfitSlot)
            end
            walk(child, depth + 1)
        end
    end
    walk(root, 0)

    if not C_TransmogOutfitInfo then
        lines[#lines + 1] = "C_TransmogOutfitInfo missing"
        return lines
    end

    -- Probe every outfit slot, not just the ones assumed to be weapons.
    for outfitSlot = 0, 15 do
        local bits = { ("slot %d:"):format(outfitSlot) }
        for _, fn in ipairs({ "IsSlotWeaponSlot", "GetWeaponOptionsForSlot", "GetSourceIDsForSlot" }) do
            if C_TransmogOutfitInfo[fn] then
                local ok, res = pcall(C_TransmogOutfitInfo[fn], outfitSlot)
                bits[#bits + 1] = ("%s=%s"):format(fn, ok and Describe(res) or ("ERR " .. tostring(res)))
            end
        end
        lines[#lines + 1] = table.concat(bits, " ")
    end

    -- What a weapon option looks like in detail, for the first weapon slot.
    if C_TransmogOutfitInfo.IsSlotWeaponSlot and C_TransmogOutfitInfo.GetWeaponOptionsForSlot then
        for outfitSlot = 0, 15 do
            local okW, isWeapon = pcall(C_TransmogOutfitInfo.IsSlotWeaponSlot, outfitSlot)
            if okW and isWeapon then
                local ok, opts = pcall(C_TransmogOutfitInfo.GetWeaponOptionsForSlot, outfitSlot)
                lines[#lines + 1] = ("-- weapon slot %d options (full): %s"):format(outfitSlot, Describe(opts, 0))
                if C_TransmogOutfitInfo.GetCollectionInfoForSlotAndOption and type(opts) == "table" and opts[1] then
                    local ok2, info = pcall(C_TransmogOutfitInfo.GetCollectionInfoForSlotAndOption, outfitSlot, opts[1])
                    lines[#lines + 1] = ("   GetCollectionInfoForSlotAndOption(%d, opts[1]) ok=%s -> %s"):format(
                        outfitSlot, tostring(ok2), Describe(info, 0))
                end
                break
            end
        end
    end

    -- WHICH weapon option is currently active. The main hand slot offers both
    -- "One Handed Weapon" (1) and "Two Handed Weapon" (2), so a weapon slot's
    -- candidate list is slot -> OPTION -> categories, not slot -> categories.
    -- Rolling without knowing the active option could silently flip a 2H into a
    -- 1H and leave the off hand holding nothing legal. No getter for this is
    -- known, so every plausible source is enumerated rather than guessed at.
    lines[#lines + 1] = ""
    lines[#lines + 1] = "-- C_TransmogOutfitInfo functions mentioning Option/Weapon"
    if C_TransmogOutfitInfo then
        local names = {}
        for name, v in pairs(C_TransmogOutfitInfo) do
            if type(v) == "function" and (name:match("Option") or name:match("Weapon")) then
                names[#names + 1] = name
            end
        end
        table.sort(names)
        lines[#lines + 1] = table.concat(names, " ")
    end

    -- === What the weapon feature actually needs ===
    --
    -- The armour roller gets its candidates from
    -- C_TransmogCollection.GetCategoryAppearances(categoryID, transmogLocation),
    -- where the category is a single Enum.TransmogCollectionType resolved by
    -- NAME. Weapons have no single category: there are many weapon types, and
    -- which ones a slot accepts depends on what is equipped. That mapping is the
    -- one thing standing between here and the feature, and it is not documented
    -- anywhere -- so it gets measured, not assumed.

    lines[#lines + 1] = ""
    lines[#lines + 1] = "-- Enum.TransmogCollectionType, every member on this build"
    if Enum and Enum.TransmogCollectionType then
        local names = {}
        for name, value in pairs(Enum.TransmogCollectionType) do
            names[#names + 1] = ("%s=%s"):format(tostring(name), tostring(value))
        end
        table.sort(names)
        lines[#lines + 1] = table.concat(names, " ")
    else
        lines[#lines + 1] = "MISSING"
    end

    -- The two weapon buttons, by position: they sit alone in their own x
    -- columns at y=232 (armour columns have >= 4 members), which is how the
    -- armour scan already excludes them.
    local weaponButtons = {}
    local function findWeapons(frame, depth)
        if not frame or depth > 9 then return end
        local ok, kids = pcall(function() return { frame:GetChildren() } end)
        if not ok then return end
        for _, child in ipairs(kids) do
            local w, h = child:GetWidth() or 0, child:GetHeight() or 0
            local x, y = child:GetCenter()
            if x and y and w >= 50 and w <= 70 and h >= 50 and h <= 70
                and child.GetTransmogLocation then
                local ok2, loc = pcall(child.GetTransmogLocation, child)
                -- slotID 16/17 are main hand / off hand; type must be
                -- Appearance, since an illusion shares its weapon's slotID.
                if ok2 and type(loc) == "table" and (loc.slotID == 16 or loc.slotID == 17)
                    and (not Enum or not Enum.TransmogType or loc.type == Enum.TransmogType.Appearance) then
                    weaponButtons[#weaponButtons + 1] = { frame = child, loc = loc, x = x, y = y }
                end
            end
            findWeapons(child, depth + 1)
        end
    end
    findWeapons(ScanRoot(), 0)

    lines[#lines + 1] = ""
    lines[#lines + 1] = ("-- weapon buttons found: %d"):format(#weaponButtons)

    for _, wb in ipairs(weaponButtons) do
        local outfitSlot = "?"
        if wb.frame.GetSlot then
            local ok, s = pcall(wb.frame.GetSlot, wb.frame)
            if ok then outfitSlot = tostring(s) end
        end
        local equipped = GetInventoryItemID and GetInventoryItemID("player", wb.loc.slotID)
        lines[#lines + 1] = ("WEAPON x=%d y=%d slotID=%d type=%s mod=%s outfitSlot=%s equippedItemID=%s"):format(
            math.floor(wb.x), math.floor(wb.y), wb.loc.slotID,
            tostring(wb.loc.type), tostring(wb.loc.modification), outfitSlot, tostring(equipped))

        -- The button's OWN methods. Both GetSlot and GetTransmogLocation were
        -- found this way after the standalone API functions returned nil for
        -- the same question, so the active weapon option may well live here too.
        -- Zero-argument getters are called; anything else is only named.
        do
            local names = {}
            local mt = getmetatable(wb.frame)
            local index = mt and mt.__index
            for _, src in ipairs({ wb.frame, type(index) == "table" and index or nil }) do
                for name, v in pairs(src) do
                    if type(v) == "function" and (name:match("Option") or name:match("Weapon")) then
                        names[#names + 1] = name
                    end
                end
            end
            table.sort(names)
            for _, name in ipairs(names) do
                -- ONLY call getters. The first version of this called every
                -- match, which included SetCurrentWeaponOption() -- a setter,
                -- invoked with no arguments, on the player's live outfit. A
                -- probe must not be able to change what it is measuring.
                if name:match("^Get") or name:match("^Is") or name:match("^Has") then
                    local ok, res = pcall(wb.frame[name], wb.frame)
                    lines[#lines + 1] = ("   btn:%s() ok=%s -> %s"):format(
                        name, tostring(ok), ok and Describe(res, 1) or "-")
                else
                    lines[#lines + 1] = ("   btn:%s  (not called: not a getter)"):format(name)
                end
            end
        end

        -- THE decisive measurement: for every collection type, how many
        -- appearances does this weapon slot return, and how many are actually
        -- rollable (isCollected and isUsable, matching IsRendered's rule)?
        -- A category with a nonzero usable count is one this slot accepts.
        if Enum and Enum.TransmogCollectionType and C_TransmogCollection
            and C_TransmogCollection.GetCategoryAppearances then
            local cats = {}
            for name, value in pairs(Enum.TransmogCollectionType) do
                cats[#cats + 1] = { name = name, value = value }
            end
            table.sort(cats, function(a, b) return a.value < b.value end)

            for _, cat in ipairs(cats) do
                local ok, list = pcall(C_TransmogCollection.GetCategoryAppearances, cat.value, wb.loc)
                if not ok or type(list) ~= "table" then
                    -- The one-argument form is the documented fallback the
                    -- armour path also tolerates.
                    ok, list = pcall(C_TransmogCollection.GetCategoryAppearances, cat.value)
                end
                if ok and type(list) == "table" and #list > 0 then
                    local usable = 0
                    for _, e in ipairs(list) do
                        if e.isCollected and e.isUsable then usable = usable + 1 end
                    end
                    if usable > 0 then
                        lines[#lines + 1] = ("   cat %-22s (%s) total=%d usable=%d"):format(
                            cat.name, tostring(cat.value), #list, usable)
                    end
                end
            end
        end

        -- And what the client itself says is legal for the slot, to cross-check
        -- the measurement above. Signature recovered from the client's own
        -- error text: GetCollectionInfoForSlotAndOption(slot, weaponOption,
        -- collectionType) -- note it takes the OPTION FIELD, not the table.
        if C_TransmogOutfitInfo and C_TransmogOutfitInfo.GetWeaponOptionsForSlot
            and type(outfitSlot) == "string" and tonumber(outfitSlot) then
            local slotNum = tonumber(outfitSlot)
            local ok, opts = pcall(C_TransmogOutfitInfo.GetWeaponOptionsForSlot, slotNum)
            if ok and type(opts) == "table" then
                for _, opt in ipairs(opts) do
                    lines[#lines + 1] = ("   option %s -> %s"):format(
                        tostring(opt.weaponOption), Describe(opt, 1))
                    if C_TransmogOutfitInfo.GetCollectionInfoForSlotAndOption and Enum
                        and Enum.TransmogCollectionType then
                        for name, value in pairs(Enum.TransmogCollectionType) do
                            local ok2, info = pcall(C_TransmogOutfitInfo.GetCollectionInfoForSlotAndOption,
                                slotNum, opt.weaponOption, value)
                            if ok2 and info ~= nil and info ~= false then
                                lines[#lines + 1] = ("      opt %s cat %-22s -> %s"):format(
                                    tostring(opt.weaponOption), name, Describe(info, 1))
                            end
                        end
                    end
                end
            end
        end
    end

    return lines
end

-- === Learning the staging call ===
--
-- C_TransmogOutfitInfo.SetPendingTransmog is what this build stages appearances
-- with (C_Transmog.SetPending does not exist here). Its signature isn't
-- available to look up, and four attempts to recall the old API were all wrong,
-- so rather than a fifth guess the real call is INSTRUMENTED: hooksecurefunc
-- records exactly what Blizzard's own UI passes when the player clicks an
-- appearance. hooksecurefunc only observes -- it cannot change the call.
local capturedCalls = {}

local function DescribeArg(v)
    local t = type(v)
    if t ~= "table" then return ("%s(%s)"):format(t, tostring(v)) end
    local parts = {}
    for k, val in pairs(v) do
        parts[#parts + 1] = ("%s=%s"):format(tostring(k),
            type(val) == "table" and "<table>" or tostring(val))
    end
    table.sort(parts)
    return "{" .. table.concat(parts, ", ") .. "}"
end

local WATCHED = {
    "SetPendingTransmog", "ClearAllPendingTransmogs", "CommitAndApplyAllPending",
    "RevertPendingTransmog", "SetViewedWeaponOptionForSlot", "ChangeViewedOutfit",
}

local function InstallWatches()
    if not C_TransmogOutfitInfo then return end
    for _, name in ipairs(WATCHED) do
        if type(C_TransmogOutfitInfo[name]) == "function" then
            hooksecurefunc(C_TransmogOutfitInfo, name, function(...)
                if #capturedCalls >= 60 then return end
                local args = {}
                for i = 1, select("#", ...) do
                    args[i] = DescribeArg((select(i, ...)))
                end
                -- Tagged with WHO made the call. Without this the log is
                -- useless for learning the API the moment the roller runs: a
                -- single Roll fires up to MAX_ROLL_ATTEMPTS staging calls per
                -- slot, which buried the one manual click the capture existed
                -- to record, and reading our own calls back as evidence of the
                -- correct argument shape is circular.
                capturedCalls[#capturedCalls + 1] = ("%s%s(%s)"):format(
                    ns.stagingFromAddon and "[addon] " or "[BLIZZ] ",
                    name, table.concat(args, ", "))
            end)
        end
    end
end

InstallWatches()

function ns.GetCapturedCalls()
    return capturedCalls
end

-- Enumerates the transmog API surface that actually exists on this build.
-- Written because the staging call was guessed three times and was wrong three
-- times: C_Transmog.SetPending and TransmogUtil.CreateTransmogPendingInfo are
-- both nil here, so the names have to be READ off the client rather than
-- recalled. Also dumps a slot button's own fields, since whatever the
-- Transmogrifier itself calls to stage a change is reachable from there.
function ns.DumpAPI()
    local lines = {}

    local function dumpKeys(label, t, withValues)
        if type(t) ~= "table" then
            lines[#lines + 1] = ("%s = %s (not a table)"):format(label, type(t))
            return
        end
        local keys = {}
        for k, v in pairs(t) do
            keys[#keys + 1] = withValues
                and ("%s = %s"):format(tostring(k), tostring(v))
                or ("%s (%s)"):format(tostring(k), type(v))
        end
        table.sort(keys)
        lines[#lines + 1] = ("-- %s: %d entries"):format(label, #keys)
        for i, k in ipairs(keys) do
            if i > 200 then lines[#lines + 1] = "   ...truncated"; break end
            lines[#lines + 1] = "   " .. k
        end
    end

    dumpKeys("C_Transmog", C_Transmog)
    dumpKeys("TransmogUtil", TransmogUtil)
    dumpKeys("Enum.TransmogType", Enum and Enum.TransmogType, true)
    dumpKeys("Enum.TransmogModification", Enum and Enum.TransmogModification, true)
    dumpKeys("Enum.TransmogPendingType", Enum and Enum.TransmogPendingType, true)

    -- What GetTransmogLocation actually wants: it exists but returned nil for
    -- (invSlot, Appearance, Main), so the argument shapes are suspect too.
    local function tryLoc(label, ...)
        local ok, loc = pcall(TransmogUtil.GetTransmogLocation, ...)
        lines[#lines + 1] = ("LOC %s -> ok=%s %s"):format(label, tostring(ok),
            (ok and type(loc) == "table")
                and ("slotID=" .. tostring(loc.slotID) .. " type=" .. tostring(loc.type) .. " mod=" .. tostring(loc.modification))
                or tostring(loc))
    end
    if TransmogUtil and TransmogUtil.GetTransmogLocation then
        tryLoc("(1, Appearance, Main)", 1, Enum.TransmogType.Appearance, Enum.TransmogModification.Main)
        tryLoc("(1, 0, 0)", 1, 0, 0)
        tryLoc("(1)", 1)
    end

    -- C_TransmogOutfitInfo is where this build's staging actually lives, so
    -- probe the read-only parts of it for every slot: the "outfit slot" it maps
    -- an inventory slot to is almost certainly what SetPendingTransmog keys on.
    if C_TransmogOutfitInfo then
        lines[#lines + 1] = "-- C_TransmogOutfitInfo probes"
        for _, slot in ipairs(SLOTS) do
            local ok, a, b = pcall(C_TransmogOutfitInfo.GetTransmogOutfitSlotFromInventorySlot, slot.invSlot)
            lines[#lines + 1] = ("   OutfitSlotFromInvSlot(%d %s) ok=%s -> %s, %s"):format(
                slot.invSlot, slot.name, tostring(ok), tostring(a), tostring(b))
        end
        for _, fn in ipairs({ "GetActiveOutfitID", "GetCurrentlyViewedOutfitID",
            "HasPendingOutfitTransmogs", "IsEquippedGearOutfitDisplayed", "InTransmogEvent" }) do
            if C_TransmogOutfitInfo[fn] then
                local ok, a, b = pcall(C_TransmogOutfitInfo[fn])
                lines[#lines + 1] = ("   %s() ok=%s -> %s, %s"):format(fn, tostring(ok), tostring(a), tostring(b))
            end
        end
        -- What a slot's available sources look like, for the Head slot.
        if C_TransmogOutfitInfo.GetSourceIDsForSlot then
            local okSlot, outfitSlot = pcall(C_TransmogOutfitInfo.GetTransmogOutfitSlotFromInventorySlot, 1)
            if okSlot and outfitSlot then
                local ok, res = pcall(C_TransmogOutfitInfo.GetSourceIDsForSlot, outfitSlot)
                lines[#lines + 1] = ("   GetSourceIDsForSlot(%s) ok=%s -> %s (%s entries)"):format(
                    tostring(outfitSlot), tostring(ok), type(res),
                    type(res) == "table" and #res or "n/a")
            end
        end
    end

    -- Every C_Transmog* namespace, since C_Transmog itself has only 7 functions
    -- and none of them stage anything.
    for k, v in pairs(_G) do
        if type(k) == "string" and k:match("^C_Transmog") and k ~= "C_Transmog" then
            dumpKeys("_G." .. k, v)
        end
    end

    -- The slot button itself. Its OWN fields carry the transmog methods (the
    -- metatable is just the stock Button widget API), so this is where the
    -- staging path has to be found.
    local map = ResolveSlotButtons()
    local headBtn = map and map[1] and map[1].frame
    if headBtn then
        dumpKeys("Head button .slotData", headBtn.slotData, true)

        -- Doubles as a CHECK on the positional mapping: if this reports a
        -- slotID other than 1, the assumed column order is wrong.
        if headBtn.GetTransmogLocation then
            local ok, loc = pcall(headBtn.GetTransmogLocation, headBtn)
            lines[#lines + 1] = ("headBtn:GetTransmogLocation() ok=%s %s"):format(tostring(ok),
                (ok and type(loc) == "table")
                    and ("slotID=" .. tostring(loc.slotID) .. " type=" .. tostring(loc.type) .. " mod=" .. tostring(loc.modification))
                    or tostring(loc))
        end
        for _, method in ipairs({ "GetSlot", "GetSlotInfo", "GetEffectiveTransmogID" }) do
            if headBtn[method] then
                local ok, a, b, c = pcall(headBtn[method], headBtn)
                lines[#lines + 1] = ("headBtn:%s() ok=%s -> %s, %s, %s"):format(
                    method, tostring(ok), tostring(a), tostring(b), tostring(c))
            end
        end

        -- Verify the whole column order in one go.
        lines[#lines + 1] = "-- positional map check (expected invSlot vs button's own slotID)"
        for _, slot in ipairs(SLOTS) do
            local e = map[slot.invSlot]
            local got = "?"
            if e and e.frame.GetTransmogLocation then
                local ok, loc = pcall(e.frame.GetTransmogLocation, e.frame)
                got = (ok and type(loc) == "table") and tostring(loc.slotID) or ("ERR " .. tostring(loc))
            end
            lines[#lines + 1] = ("   %s expected=%d got=%s"):format(slot.name, slot.invSlot, got)
        end
    else
        lines[#lines + 1] = "-- Head slot button not resolved"
    end

    -- The frames that own the pending state and the appearance grid. Whatever
    -- clicking an appearance calls is reachable from one of these.
    dumpKeys("TransmogFrame fields", TransmogFrame)
    dumpKeys("CharacterPreview fields", TransmogFrame and TransmogFrame.CharacterPreview)

    local ic = TransmogFrame and TransmogFrame.WardrobeCollection
        and TransmogFrame.WardrobeCollection.TabContent
        and TransmogFrame.WardrobeCollection.TabContent.ItemsFrame
    dumpKeys("ItemsFrame fields", ic)
    if ic then
        -- One appearance-grid entry: its OnClick is the thing that stages a
        -- pending appearance in the real UI.
        local found
        local function findEntry(frame, depth)
            if found or not frame or depth > 4 then return end
            local ok, kids = pcall(function() return { frame:GetChildren() } end)
            if not ok then return end
            for _, child in ipairs(kids) do
                if not found and child:GetObjectType() == "Button" and child.visualID ~= nil then
                    found = child
                end
                findEntry(child, depth + 1)
            end
        end
        findEntry(ic, 0)
        if found then
            dumpKeys("appearance entry button fields", found)
        else
            lines[#lines + 1] = "-- no appearance entry button with a .visualID found"
        end
    end

    return lines
end

-- === Swatch widget, shared by the inline swatches and the fallback panel ===

local OpenSlotPicker

local function ShowSwatchTooltip(self)
    local slot = self.slot
    GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
    GameTooltip:SetText(slot.name .. " colour")

    -- Weapons roll within the shape currently DISPLAYED, so say which one --
    -- otherwise "why did my two-hander roll a dagger" has no visible answer.
    if slot.isWeapon then
        local _, optionName = CurrentWeaponOption(slot)
        if optionName then
            GameTooltip:AddLine("Rolling within: " .. optionName, 0.6, 0.8, 1)
        end
    end

    local pool = SlotPool(slot)
    if pool then
        local matching = GetMatching(slot)
        local n = matching and #matching or 0
        GameTooltip:AddLine(("%s - %d option%s"):format(PoolName(pool), n, n == 1 and "" or "s"), 0.8, 0.8, 0.8, true)
    else
        local n = #GetCandidates(slot)
        GameTooltip:AddLine(("no colour set - %d collected appearance%s"):format(n, n == 1 and "" or "s"), 0.8, 0.8, 0.8)
    end

    local roll = lastRoll[slot.invSlot]
    if roll and roll.visualID then
        GameTooltip:AddLine("Rolled: " .. (roll.name or ("visual " .. roll.visualID)), 1, 1, 1)
    elseif roll and roll.failed == "nomatch" then
        GameTooltip:AddLine("Nothing collected in this colour", 1, 0.5, 0.5)
    elseif roll and roll.failed == "empty" then
        GameTooltip:AddLine("Nothing equipped in this slot", 1, 0.5, 0.5)
    elseif roll and roll.failed == "nosource" then
        GameTooltip:AddLine("No usable source", 1, 0.5, 0.5)
    end

    GameTooltip:AddLine("Click to pick colours (several make a pool)", 1, 1, 1)
    GameTooltip:AddLine("In the picker, middle-click or Shift-click excludes a colour", 0.6, 0.6, 0.6, true)
    GameTooltip:AddLine("Right-click to clear", 0.6, 0.6, 0.6)
    GameTooltip:Show()
end

local function CreateSwatch(parent, slot, size)
    local btn = CreateFrame("Button", nil, parent, "BackdropTemplate")
    btn.slot = slot
    btn:SetSize(size, size)
    btn:SetBackdrop({
        bgFile = "Interface/Buttons/WHITE8x8",
        edgeFile = "Interface/Buttons/WHITE8x8",
        edgeSize = 1,
    })
    btn:SetBackdropColor(0.08, 0.08, 0.08, 0.85)
    btn:SetBackdropBorderColor(0, 0, 0, 1)

    btn.Swatch = btn:CreateTexture(nil, "ARTWORK")
    btn.Swatch:SetPoint("TOPLEFT", 1, -1)
    btn.Swatch:SetPoint("BOTTOMRIGHT", -1, 1)
    btn.Swatch:Hide()

    btn.Empty = btn:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
    btn.Empty:SetPoint("CENTER")
    btn.Empty:SetText("+")

    btn:RegisterForClicks("LeftButtonUp", "RightButtonUp")
    btn:SetScript("OnClick", function(self, button)
        if button == "RightButton" then
            ns.state.slotColors[self.slot.invSlot] = nil
            lastRoll[self.slot.invSlot] = nil
            ns.RefreshRandomizerPanel()
        else
            OpenSlotPicker(self)
        end
    end)
    btn:SetScript("OnEnter", ShowSwatchTooltip)
    btn:SetScript("OnLeave", GameTooltip_Hide)
    return btn
end

-- Switches the roller between General and Light and dark: every slot's pool
-- is carried across (a colour becomes its two halves and back), then `reopen`
-- redraws the picker that asked.
local function ToggleRollDetail(reopen)
    local toAll = RollDetail() ~= "all"
    for invSlot, set in pairs(ns.state.slotColors) do
        local t = ns.TranslateSelection(set, toAll)
        ns.state.slotColors[invSlot] = (t and next(t)) and t or nil
    end
    ns.state.rollDetail = toAll and "all" or "general"
    InvalidateSlots()
    ns.RefreshRandomizerPanel()
    reopen()
end

OpenSlotPicker = function(swatch)
    local slot = swatch.slot
    local palette = GetSlotPalette(slot)
    local selected = CopyPool(SlotPool(slot) or {})
    local function store()
        ns.state.slotColors[slot.invSlot] = next(selected) and CopyPool(selected) or nil
        lastRoll[slot.invSlot] = nil
        ns.RefreshRandomizerPanel()
    end
    ns.OpenSwatchPicker({
        title = slot.name .. " colours",
        palette = palette,
        columns = ns.MatchStripColumns(RollDetail()),
        detailText = RollDetail() == "all" and "Less" or "More",
        onToggleDetail = function() ToggleRollDetail(function() OpenSlotPicker(swatch) end) end,
        multi = true,
        selected = selected,
        onChange = store,
        onClear = function()
            wipe(selected)
            store()
        end,
    }, swatch, "TOPLEFT", "BOTTOMLEFT", 0, -4)
end

-- A pool shows as side-by-side stripes, one per colour, in strip order.
local function RefreshSwatch(btn)
    local pool = SlotPool(btn.slot)
    local keys = pool and PoolKeys(pool) or {}
    btn.stripes = btn.stripes or { btn.Swatch }
    local inner = btn:GetWidth() - 2
    for i, key in ipairs(keys) do
        local tex = btn.stripes[i]
        if not tex then
            tex = btn:CreateTexture(nil, "ARTWORK")
            btn.stripes[i] = tex
        end
        local info = ns.MatchKeyInfo(key)
        tex:SetColorTexture(info and info.r or 0.5, info and info.g or 0.5, info and info.b or 0.5)
        tex:ClearAllPoints()
        tex:SetPoint("TOPLEFT", btn, "TOPLEFT", 1 + inner * (i - 1) / #keys, -1)
        tex:SetPoint("BOTTOMRIGHT", btn, "BOTTOMLEFT", 1 + inner * i / #keys, 1)
        tex:Show()
    end
    for i = #keys + 1, #btn.stripes do btn.stripes[i]:Hide() end
    -- Excluded colours: a red x over the swatch (the tooltip names them).
    local excluding = pool and #PoolKeys(pool, "exclude") > 0
    if not btn.ExcludeMark then
        btn.ExcludeMark = btn:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
        btn.ExcludeMark:SetPoint("CENTER", 0, 0)
        btn.ExcludeMark:SetText("x")
        btn.ExcludeMark:SetTextColor(1, 0.15, 0.15)
        btn.ExcludeMark:SetShadowColor(0, 0, 0, 1)
        btn.ExcludeMark:SetShadowOffset(1, -1)
    end
    btn.ExcludeMark:SetShown(excluding)
    if #keys > 0 or excluding then btn.Empty:Hide() else btn.Empty:Show() end
    -- A red rim is the only room a 16px swatch has to say the last roll found
    -- nothing; the reason itself is in the tooltip.
    local roll = lastRoll[btn.slot.invSlot]
    if roll and roll.failed then
        btn:SetBackdropBorderColor(1, 0.3, 0.3, 1)
    else
        btn:SetBackdropBorderColor(0, 0, 0, 1)
    end
end

-- === Attaching them to the slot buttons ===

local function AttachSwatches()
    if not TransmogFrame then return 0 end
    ScanForSlotButtons()

    -- anchorBtn/anchorY track the lowest left-column button, which the Roll
    -- button hangs beneath.
    local attached, anchorBtn, anchorY = 0, nil, nil
    local lowestAny, lowestAnyY

    for _, slot in ipairs(SLOTS) do
        local entry = discovered[slot.invSlot]
        local button = entry and entry.frame
        if button then
            local sw = slotSwatches[slot.invSlot]
            if not sw then
                -- Parented to the slot button so it inherits the button's
                -- show/hide -- "Hide Ignored Slots" then takes the swatch with
                -- it instead of leaving it floating over the model.
                sw = CreateSwatch(button, slot, SWATCH_SIZE)
                slotSwatches[slot.invSlot] = sw
            else
                -- Re-parented every pass, not just at creation. The buttons are
                -- pooled, so after an outfit switch this slot's swatch may be
                -- sitting on a frame that now belongs to a different slot.
                sw:SetParent(button)
            end
            sw:SetFrameLevel(button:GetFrameLevel() + 5)
            sw:Show()

            -- Sit on the button's INNER side, i.e. facing the model: the two
            -- columns hug the edges of the preview and the open space is
            -- between each column and the character. The column is known from
            -- the resolve step, so this no longer has to be inferred from
            -- coordinates that may not exist yet.
            sw:ClearAllPoints()
            -- Armour columns hug the edges of the preview, so their swatches go
            -- on the INNER side, facing the model, where the space is.
            -- The two weapon buttons sit side by side in the middle instead, so
            -- inward would put both swatches in the gap between them, on top of
            -- each other -- they face OUTWARD.
            local inward = (entry.side ~= "right")
            if slot.isWeapon then inward = not inward end
            if inward then
                sw:SetPoint("LEFT", button, "RIGHT", 3, 0)
            else
                sw:SetPoint("RIGHT", button, "LEFT", -3, 0)
            end

            local bottom = button:GetBottom()
            if bottom then
                -- Weapons are excluded from the anchor search. They sit well
                -- below the armour columns (y=232 against a lowest armour row
                -- of 393), so including them would drag the Roll button down
                -- into the weapon area and away from the gear list it belongs
                -- to.
                if entry.side == "left" and not slot.isWeapon
                    and (not anchorY or bottom < anchorY) then
                    anchorY, anchorBtn = bottom, button
                end
                if not lowestAnyY or bottom < lowestAnyY then
                    lowestAnyY, lowestAny = bottom, button
                end
            end
            attached = attached + 1
        end
    end

    -- A slot the current outfit doesn't show has no button to hang off. Its
    -- swatch is hidden and detached, rather than left parented to a pooled
    -- frame that now belongs to some other slot.
    for invSlot, sw in pairs(slotSwatches) do
        if not discovered[invSlot] then
            sw:Hide()
            sw:ClearAllPoints()
            sw:SetParent(UIParent)
        end
    end

    -- The Roll button is only placed once something concrete to hang it off
    -- exists; SetPoint against a nil relative frame is a hard error, and the
    -- alternative (TransmogFrame's corner) landed it on top of "Save Outfit".
    local host = anchorBtn or lowestAny
    if attached > 0 and host then
        -- Parented into the SLOT BUTTON'S OWN COLUMN, not to TransmogFrame.
        -- Parented to TransmogFrame it rendered in the right place and was
        -- completely dead to the mouse -- no hover, no press -- because it sat
        -- underneath CharacterPreview's ModelScene, which covers that area and
        -- swallows the clicks. The swatches never had this problem precisely
        -- because they hang off the slot buttons, so the Roll button uses the
        -- same hierarchy. Anchored to the button but parented to its column
        -- container, so "Hide Ignored Slots" hiding that one button doesn't
        -- take the Roll button with it.
        local parent = host:GetParent() or TransmogFrame
        if not rollButton then
            rollButton = CreateFrame("Button", nil, parent, "UIPanelButtonTemplate")
            rollButton:SetSize(BUTTON_WIDTH, 20)
            rollButton:SetText("Roll")
            rollButton:SetScript("OnEnter", function(self)
                GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
                GameTooltip:SetText("Roll a random outfit")
                GameTooltip:AddLine("Stages one appearance per slot that has a colour set. Nothing is spent until you press Apply.", 0.8, 0.8, 0.8, true)
                GameTooltip:AddLine("Right-click: clear every slot colour", 0.6, 0.6, 0.6)
                GameTooltip:Show()
            end)
            rollButton:SetScript("OnLeave", GameTooltip_Hide)
            rollButton:RegisterForClicks("LeftButtonUp", "RightButtonUp")
            rollButton:SetScript("OnClick", function(_, button)
                if button == "RightButton" then
                    wipe(ns.state.slotColors)
                    wipe(lastRoll)
                    ns.RefreshRandomizerPanel()
                else
                    RollAll()
                end
            end)
        end
        -- Re-parented on every attach, not just at creation: the column frame
        -- may not have existed on the pass that built the button.
        rollButton:SetParent(parent)
        rollButton:SetFrameLevel(host:GetFrameLevel() + 10)
        rollButton:EnableMouse(true)
        rollButton:ClearAllPoints()
        rollButton:SetPoint("TOP", host, "BOTTOM", 0, -10)
        rollButton:Show()

        -- "Set every slot to one colour" -- the common case for a themed
        -- outfit, which otherwise costs eleven picker trips. Same hierarchy and
        -- the same re-parenting rules as the Roll button, for the same reason:
        -- parented to TransmogFrame it would render correctly and be dead to
        -- the mouse underneath CharacterPreview's ModelScene.
        if not allButton then
            allButton = CreateFrame("Button", nil, parent, "UIPanelButtonTemplate")
            -- Wider than Roll's original 74: "All one colour" overflowed the
            -- button. Both are set to the same width so the pair reads as a
            -- column rather than two mismatched buttons.
            allButton:SetSize(BUTTON_WIDTH, 20)
            allButton:SetText("All Slots")
            allButton:SetScript("OnEnter", function(self)
                GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
                GameTooltip:SetText("Colours for every slot")
                GameTooltip:AddLine("The colours you pick become one pool every slot rolls from: pick gold and purple, and each slot rolls from all your gold and purple pieces. Middle-click or Shift-click a colour to keep out pieces that have it. Replaces what the slots had. Roll afterwards to stage the outfit.", 0.8, 0.8, 0.8, true)
                GameTooltip:Show()
            end)
            allButton:SetScript("OnLeave", GameTooltip_Hide)
            local function OpenAllPicker(self)
                -- Starts from the slots' shared pool when every slot has the
                -- same one (i.e. this button set it last time).
                local first, same = nil, true
                for _, slot in ipairs(SLOTS) do
                    local name = PoolSignature(SlotPool(slot))
                    if first == nil then first = name elseif name ~= first then same = false end
                end
                local selected = CopyPool((same and SlotPool(SLOTS[1])) or {})
                local function store()
                    for _, slot in ipairs(SLOTS) do
                        ns.state.slotColors[slot.invSlot] = next(selected) and CopyPool(selected) or nil
                    end
                    wipe(lastRoll)
                    ns.RefreshRandomizerPanel()
                end
                ns.OpenSwatchPicker({
                    title = "Colours for every slot",
                    palette = GetAllSlotsPalette(),
                    columns = ns.MatchStripColumns(RollDetail()),
                    detailText = RollDetail() == "all" and "Less" or "More",
                    onToggleDetail = function() ToggleRollDetail(function() OpenAllPicker(self) end) end,
                    multi = true,
                    selected = selected,
                    onChange = store,
                    onClear = function()
                        wipe(selected)
                        store()
                    end,
                }, self, "TOP", "BOTTOM", 0, -4)
            end
            allButton:SetScript("OnClick", OpenAllPicker)
        end
        allButton:SetParent(parent)
        allButton:SetFrameLevel(host:GetFrameLevel() + 10)
        allButton:EnableMouse(true)
        allButton:ClearAllPoints()
        allButton:SetPoint("TOP", rollButton, "BOTTOM", 0, -4)
        allButton:Show()
    end

    return attached
end

-- Exposed because RollAll is defined earlier in the file and re-resolves the
-- mapping before staging anything.
ns.ReattachSwatches = AttachSwatches

-- === Refresh / registration ===
--
-- There is deliberately NO fallback window. One was written, to keep the
-- feature usable if the slot-button search came up empty -- and when the search
-- did fail it quietly produced exactly the separate panel the user had asked to
-- be replaced, disguising a broken scan as a design regression. A failed scan
-- must be loud and produce nothing, so it gets fixed rather than lived with.

function ns.RefreshRandomizerPanel()
    for _, btn in pairs(slotSwatches) do
        RefreshSwatch(btn)
    end
end

local warnedNoButtons = false

local function EnsureUI(parentFrame, reportFailure)
    local attached = AttachSwatches()
    if attached == 0 and reportFailure and parentFrame:IsShown() and not warnedNoButtons then
        warnedNoButtons = true
        print(("|cffff4444TransmogPalette:|r couldn't place the colour swatches - %s. Run |cffffff00/tmpalette buttons|r then |cffffff00/reload|r."):format(
            lastResolveError or "no gear-slot buttons found"))
    end
    ns.RefreshRandomizerPanel()
    return attached
end

-- On a fresh login the buttons exist before they are POSITIONED, and
-- AttachSwatches deliberately bails while GetCenter still returns nil rather
-- than anchoring to a guess. So attaching is retried across the first couple of
-- seconds after each show, stopping as soon as it takes.
local RETRY_DELAYS = { 0.05, 0.2, 0.5, 1.0, 2.0 }

local function EnsureUIWithRetries(parentFrame)
    if EnsureUI(parentFrame, false) > 0 then return end
    for i, delay in ipairs(RETRY_DELAYS) do
        local isLast = (i == #RETRY_DELAYS)
        C_Timer.After(delay, function()
            if not parentFrame:IsShown() then return end
            if next(slotSwatches) and not isLast then return end
            EnsureUI(parentFrame, isLast)
        end)
    end
end

-- Switching outfits in the left-hand list re-lays-out the slot buttons AND,
-- because they are pooled, can hand a given frame to a different slot. Without
-- this the swatches stayed on their old frames -- they appeared to "move
-- around", and Roll then worked on only some slots because the mapping was
-- stale. These are the functions the UI was observed calling on an outfit
-- switch (see /tmpalette watch), so they are known to exist on this build.
local OUTFIT_CHANGE_FUNCS = {
    "ChangeViewedOutfit", "ChangeToOutfit", "ChangeDisplayedOutfit",
    "ClearDisplayedOutfit", "SetOutfitToOutfit", "SetOutfitToSet", "SetOutfitToCustomSet",
}

local function InstallOutfitHooks(parentFrame)
    if not C_TransmogOutfitInfo then return end
    for _, name in ipairs(OUTFIT_CHANGE_FUNCS) do
        if type(C_TransmogOutfitInfo[name]) == "function" then
            hooksecurefunc(C_TransmogOutfitInfo, name, function()
                -- Deferred a frame: the buttons have not been re-laid-out yet
                -- at the moment the call is made, so resolving now would read
                -- the OLD positions.
                C_Timer.After(0, function()
                    if not parentFrame:IsShown() then return end
                    -- A rolled outfit doesn't survive switching to another one.
                    wipe(lastRoll)
                    AttachSwatches()
                    ns.RefreshRandomizerPanel()
                end)
            end)
        end
    end
end

function ns.RegisterRandomizer(parentFrame)
    if registered or not parentFrame then return end
    registered = true
    InstallOutfitHooks(parentFrame)

    -- Slot buttons are built lazily, so attaching is retried on every show
    -- rather than assumed to work the first time.
    parentFrame:HookScript("OnShow", function(self) EnsureUIWithRetries(self) end)
    if parentFrame:IsShown() then EnsureUIWithRetries(parentFrame) end

    -- The collection can grow mid-session (a drop, a vendor purchase), which
    -- changes both what a slot can roll and what colours its picker offers.
    local ev = CreateFrame("Frame")
    ev:RegisterEvent("TRANSMOG_COLLECTION_UPDATED")
    ev:SetScript("OnEvent", function()
        InvalidateSlots()
        ns.RefreshRandomizerPanel()
    end)
end

ns.RandomizerSlots = SLOTS

-- Development (Capture.lua's sweep): show a slot's appearances exactly as
-- clicking its button does. OnSelect is the click minus the sound.
function ns.SelectTransmogSlot(invSlot)
    ScanForSlotButtons()
    local entry = discovered[invSlot]
    local btn = entry and entry.frame
    if not (btn and btn.OnSelect) then return false end
    return (pcall(btn.OnSelect, btn))
end
ns.RollRandomOutfit = RollAll

-- For /tmpalette slots. Returns collected-candidate count, how many of those
-- match the slot's colour pool (nil when unassigned), and the pool's keys.
function ns.GetSlotDebug(slot)
    local pool = SlotPool(slot)
    local matching = GetMatching(slot)
    return #GetCandidates(slot), matching and #matching or nil, pool and table.concat(PoolKeys(pool), "+")
end

