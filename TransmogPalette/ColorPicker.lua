local _, ns = ...

-- === The colour strip ===
--
-- Replaces three "main" boxes plus an accent box, each of which opened a popup
-- grid. That model made comparing colours expensive: every look at a different
-- colour cost open-popup / click / read the results / reopen, and the cap of
-- three meant picking several shades of one colour spent the whole filter.
--
-- Instead every bucket the current grain can produce is on screen permanently
-- as a toggle. Left-click adds or removes a main colour -- any number of them,
-- OR'd, since MatchesFilter was already an OR and the cap only ever existed
-- because each pick cost a box. Right-click sets the accent, which is still
-- singular and still matched against the appearance's SECOND colour, a
-- different axis from the mains rather than a fourth main.
--
-- The strip shows EVERY bucket of the grain, not just the ones present in the
-- slot on screen. Colours the slot has nothing in render dimmed with a count of
-- zero. This is deliberate: a grid built only from what is present would
-- reshuffle every time the player changed slot, and an always-visible grid whose
-- swatches move is worse than a popup -- knowing where a colour lives is the
-- entire benefit. It also answers "does this slot have anything green" directly.
--
-- The popup itself is kept, generalised, because the randomiser still raises it
-- per armour slot (see ns.OpenSwatchPicker).

local SWATCH_SIZE = 20
local SWATCH_GAP = 2
local HEADER_HEIGHT = 18
-- Enough to clear the backdrop's border. Without a backdrop the swatches read as
-- debris scattered over Blizzard's own labels and buttons; with one the strip
-- reads as a panel that happens to sit in front of them.
local PANEL_INSET = 7

-- Only an upper bound; the real column count is fitted to the parent's width at
-- layout time, since the strip has to sit inside Blizzard's frame.
local MAX_COLUMNS = 20
local MIN_COLUMNS = 6

ns.panels = {}
local refreshCallbacks = {}

local function RefreshAll()
    for _, fn in ipairs(refreshCallbacks) do
        pcall(fn)
    end
end

-- === Selection state ===
--
-- ns.state.primaryColors is a SET keyed by bucket key (see CLASSIFIER_VERSION 6
-- in Core.lua), so a toggle is an assignment rather than a search for a free
-- slot. The stored value keeps h/s/v so anything drawing the selection doesn't
-- have to re-derive the swatch colour.

-- Selections are keyed by swatch key (Matching.lua); the value only needs
-- the key, and stays a table so `next()`-based checks elsewhere are unchanged.
local function SelectionColor(key)
    return { key = key }
end

local SyncAllPanels

local function AfterSelectionChange()
    -- The accent's swatch counts are conditioned on the main selections and
    -- vice versa, so every palette goes stale on any change.
    ns.InvalidateSwatchPalettes()
    SyncAllPanels()
    RefreshAll()
end

local function ToggleMain(key)
    if ns.state.primaryColors[key] then
        ns.state.primaryColors[key] = nil
    else
        ns.state.primaryColors[key] = SelectionColor(key)
    end
    AfterSelectionChange()
end

local function ToggleAccent(key)
    local current = ns.state.accentColor
    if current and current.key == key then
        ns.state.accentColor = nil
    else
        ns.state.accentColor = SelectionColor(key)
    end
    AfterSelectionChange()
end

local function ClearAll()
    ns.state.primaryColors = {}
    ns.state.accentColor = nil
    AfterSelectionChange()
end

local function SelectedCount()
    local n = 0
    for _ in pairs(ns.state.primaryColors) do n = n + 1 end
    return n
end

-- === Labels ===

local VALUE_WORD = { dark = "Dark", mid = "Mid", light = "Light" }

local function BucketLabel(key)
    -- Strip and override-picker keys are swatches; the outfit roller's popup
    -- still uses the older bucket keys, which fall through to the parsing below.
    local info = ns.MatchKeyInfo and ns.MatchKeyInfo(key)
    if info then return info.name end
    local band, vband = key:match("^(%a+)_(%a+)$")
    band = band or key
    local name = band:sub(1, 1):upper() .. band:sub(2)
    if vband and VALUE_WORD[vband] then
        return VALUE_WORD[vband] .. " " .. band
    end
    return name
end

-- === Swatch-grid popup ===
--
-- Kept for the randomiser, which assigns one colour per armour slot and so
-- genuinely wants a one-shot picker rather than a persistent multi-select.
-- Only offers colours that actually occur (see Palette.lua's
-- BuildPaletteFromColors), so picking is inherently constrained to real,
-- matchable colours instead of an arbitrary wheel position.

local GRID_COLUMNS = 12
local POPUP_SWATCH_SIZE = 20
local swatchPopup

local function CreateSwatchPopup()
    local popup = CreateFrame("Frame", "TransmogPaletteSwatchPopup", UIParent, "BackdropTemplate")
    popup:SetBackdrop({
        bgFile = "Interface/Tooltips/UI-Tooltip-Background",
        edgeFile = "Interface/Tooltips/UI-Tooltip-Border",
        edgeSize = 12,
        insets = { left = 4, right = 4, top = 4, bottom = 4 },
    })
    popup:SetBackdropColor(0, 0, 0, 0.95)
    popup:SetFrameStrata("DIALOG")
    popup:EnableMouse(true)
    popup:Hide()

    popup.Title = popup:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    popup.Title:SetPoint("TOPLEFT", 12, -10)

    popup.ClearButton = CreateFrame("Button", nil, popup, "UIPanelButtonTemplate")
    popup.ClearButton:SetSize(70, 20)
    popup.ClearButton:SetPoint("TOPRIGHT", -10, -8)
    popup.ClearButton:SetText("Clear")
    popup.ClearButton:SetScript("OnClick", function()
        popup.onClear()
        popup:Hide()
    end)

    popup.buttons = {}
    return popup
end

-- `spec` is { title, palette, onPick, onClear }.
local function LayoutSwatchPopup(popup, spec)
    popup.onClear = spec.onClear
    popup.Title:SetText(spec.title)

    local palette = spec.palette
    for i, swatch in ipairs(palette) do
        local btn = popup.buttons[i]
        if not btn then
            btn = CreateFrame("Button", nil, popup, "BackdropTemplate")
            btn:SetSize(POPUP_SWATCH_SIZE, POPUP_SWATCH_SIZE)
            btn:SetBackdrop({ edgeFile = "Interface/Buttons/WHITE8x8", edgeSize = 1 })
            btn:SetBackdropBorderColor(0, 0, 0, 1)
            btn.Swatch = btn:CreateTexture(nil, "ARTWORK")
            btn.Swatch:SetPoint("TOPLEFT", 1, -1)
            btn.Swatch:SetPoint("BOTTOMRIGHT", -1, 1)
            btn:SetScript("OnEnter", function(self)
                GameTooltip:SetOwner(self, "ANCHOR_TOP")
                GameTooltip:SetText(BucketLabel(self.swatch.key))
                -- Count is optional. This popup is generic, so it must not
                -- require a field only the filter's palette carries -- the
                -- override picker offers every bucket regardless of what is on
                -- screen, and has no count to show.
                local n = self.swatch.count
                if n then
                    GameTooltip:AddLine(("%d appearance%s"):format(n, n == 1 and "" or "s"), 0.8, 0.8, 0.8)
                end
                GameTooltip:Show()
            end)
            btn:SetScript("OnLeave", GameTooltip_Hide)
            popup.buttons[i] = btn
        end

        local col = (i - 1) % GRID_COLUMNS
        local row = math.floor((i - 1) / GRID_COLUMNS)
        btn:ClearAllPoints()
        btn:SetPoint("TOPLEFT", popup, "TOPLEFT", 12 + col * (POPUP_SWATCH_SIZE + 4), -36 - row * (POPUP_SWATCH_SIZE + 4))

        local r, g, b = ns.HSVToRGB(swatch.h, swatch.s, swatch.v)
        btn.Swatch:SetColorTexture(r, g, b)
        btn.swatch = swatch
        btn:SetScript("OnClick", function()
            -- Carry the bucket key the swatch was built from rather than
            -- re-deriving it from the averaged h/s/v at match time, which
            -- could land in a neighbouring bucket near a band boundary.
            spec.onPick({ h = swatch.h, s = swatch.s, v = swatch.v, key = swatch.key })
            popup:Hide()
        end)
        btn:Show()
    end

    for i = #palette + 1, #popup.buttons do
        popup.buttons[i]:Hide()
    end

    local rows = math.ceil(#palette / GRID_COLUMNS)
    popup:SetSize(12 + GRID_COLUMNS * (POPUP_SWATCH_SIZE + 4) + 8, 44 + rows * (POPUP_SWATCH_SIZE + 4))
end

function ns.OpenSwatchPicker(spec, anchorFrame, point, relPoint, x, y)
    if not swatchPopup then
        swatchPopup = CreateSwatchPopup()
    end
    LayoutSwatchPopup(swatchPopup, spec)
    swatchPopup:ClearAllPoints()
    swatchPopup:SetPoint(point or "TOP", anchorFrame, relPoint or "BOTTOM", x or 0, y or -4)
    swatchPopup:Show()
end

-- Hand-correct one appearance's colour, opened from the right-click menu on an
-- appearance tile. `side` is "main" or "accent".
--
-- Writes through ns.OverrideStore so dev mode decides the layer: a player's
-- correction lands in their own store, the author's in the exportable one.
-- Nothing here knows or cares which.
function ns.OpenOverridePicker(visualID, side, anchor)
    local store = ns.OverrideStore()
    ns.OpenSwatchPicker({
        title = (side == "accent") and "Correct accent colour" or "Correct main colour",
        palette = ns.OverridePalette(),
        onPick = function(swatch)
            local spec = ns.OverrideSpecFromKey(swatch.key)
            if not spec then return end
            store[visualID] = store[visualID] or {}
            store[visualID][side] = spec
            ns.OverridesChanged()
        end,
        onClear = function()
            local o = store[visualID]
            if not o then return end
            o[side] = nil
            -- Drop the row entirely once neither side is corrected, so an
            -- empty table can never look like a live override in the list or
            -- the export.
            if o.main == nil and o.accent == nil then store[visualID] = nil end
            ns.OverridesChanged()
        end,
    }, anchor, "TOPLEFT", "BOTTOMLEFT", 0, -4)
end

-- === Strip swatches ===

local function SwatchTooltip(self)
    GameTooltip:SetOwner(self, "ANCHOR_TOP")
    GameTooltip:SetText(BucketLabel(self.key))
    local info = ns.MatchKeyInfo(self.key)
    if info and info.members and info.members ~= info.name then
        GameTooltip:AddLine("Includes " .. info.members, 0.7, 0.7, 0.7, true)
    end

    -- Both counts, because a colour common as a main can be nonexistent as an
    -- accent -- they are drawn from separate palettes (rank-1 vs rank-2
    -- clusters). Showing only one would make right-click a guess.
    if self.countsKnown then
        local mainCount = self.mainCount or 0
        local accentCount = self.accentCount or 0
        GameTooltip:AddLine(("%d as a main colour"):format(mainCount), 0.8, 0.8, 0.8)
        GameTooltip:AddLine(("%d as an accent"):format(accentCount), 0.6, 0.6, 0.6)
    else
        GameTooltip:AddLine("Counts appear once a slot is open", 0.6, 0.6, 0.6)
    end

    if ns.state.primaryColors[self.key] then
        GameTooltip:AddLine("Left-click to remove this main colour", 1, 1, 1)
    else
        GameTooltip:AddLine("Left-click to add as a main colour", 1, 1, 1)
    end
    local accent = ns.state.accentColor
    if accent and accent.key == self.key then
        GameTooltip:AddLine("Right-click to clear the accent", 1, 1, 1)
    else
        GameTooltip:AddLine("Right-click to use as the accent", 0.7, 0.7, 0.7)
        GameTooltip:AddLine("The accent narrows every main colour at once", 0.6, 0.6, 0.6)
    end
    GameTooltip:Show()
end

local function CreateStripSwatch(panel)
    local btn = CreateFrame("Button", nil, panel, "BackdropTemplate")
    btn:SetSize(SWATCH_SIZE, SWATCH_SIZE)
    btn:SetBackdrop({
        bgFile = "Interface/Buttons/WHITE8x8",
        edgeFile = "Interface/Buttons/WHITE8x8",
        edgeSize = 2,
    })
    btn:SetBackdropColor(0.08, 0.08, 0.08, 1)
    btn:SetBackdropBorderColor(0, 0, 0, 1)

    btn.Swatch = btn:CreateTexture(nil, "ARTWORK")
    btn.Swatch:SetPoint("TOPLEFT", 2, -2)
    btn.Swatch:SetPoint("BOTTOMRIGHT", -2, 2)

    -- The accent gets a corner mark rather than a second border: at 20px there
    -- is only one border to spend, and it is spent on the mains.
    btn.AccentMark = btn:CreateTexture(nil, "OVERLAY")
    btn.AccentMark:SetSize(6, 6)
    btn.AccentMark:SetPoint("BOTTOMRIGHT", -2, 2)
    btn.AccentMark:SetColorTexture(1, 1, 1, 1)
    btn.AccentMark:Hide()

    btn:RegisterForClicks("LeftButtonUp", "RightButtonUp")
    btn:SetScript("OnClick", function(self, button)
        if button == "RightButton" then
            ToggleAccent(self.key)
        else
            ToggleMain(self.key)
        end
        -- The tooltip is still up and its text just went stale.
        SwatchTooltip(self)
    end)
    btn:SetScript("OnEnter", SwatchTooltip)
    btn:SetScript("OnLeave", GameTooltip_Hide)
    return btn
end

-- Colours a swatch for its current selection state.
--
-- A bucket the current slot holds nothing in is dimmed hard but stays
-- clickable: selections persist across slots, so refusing the click would be
-- surprising, and the zero in the tooltip is the honest signal.
local function RefreshStripSwatch(btn, anySelected)
    local isMain = ns.state.primaryColors[btn.key] ~= nil
    local accent = ns.state.accentColor
    local isAccent = accent and accent.key == btn.key

    if not btn.countsKnown then
        -- Nothing listed yet, so a count of zero means "not asked" rather than
        -- "this slot has none". Dimming here would make the whole strip look
        -- broken on the first open, which is a worse lie than no count at all.
        btn.Swatch:SetAlpha((isMain or not anySelected) and 1 or 0.4)
    elseif (btn.mainCount or 0) == 0 then
        btn.Swatch:SetAlpha(0.15)
    elseif isMain or not anySelected then
        -- With nothing selected the whole strip stays lit; dimming everything
        -- by default would make the resting state look disabled.
        btn.Swatch:SetAlpha(1)
    else
        btn.Swatch:SetAlpha(0.4)
    end

    if isMain then
        btn:SetBackdropBorderColor(1, 0.82, 0, 1)
    else
        btn:SetBackdropBorderColor(0, 0, 0, 1)
    end

    if isAccent then
        btn.AccentMark:Show()
    else
        btn.AccentMark:Hide()
    end
end

-- === Counts ===
--
-- How many listed appearances each strip key would return as a main colour
-- and as an accent, given the REST of the filter -- the same MatchesFilter
-- the list uses, so a count is exactly what clicking yields. Cached until
-- the selection or the listed category changes (ns.InvalidateSwatchPalettes).
local function Counts()
    local cached = ns.swatchPalettes.matchCounts
    if cached then return cached end
    local visuals = ns.GetCurrentVisuals()
    if not visuals then return nil end
    local keys = ns.MatchStripKeys()
    local mains, accents = {}, {}
    for _, vid in ipairs(visuals) do
        if ns.HasColorData(vid) then
            local asMain = ns.MatchesFilterExcept(vid, "primary")
            local asAccent = ns.MatchesFilterExcept(vid, "accent")
            if asMain or asAccent then
                for _, k in ipairs(keys) do
                    local r = ns.MatchScore(vid, k.key)
                    if r and r >= 1 then
                        if asMain then mains[k.key] = (mains[k.key] or 0) + 1 end
                        if asAccent then accents[k.key] = (accents[k.key] or 0) + 1 end
                    end
                end
            end
        end
    end
    cached = { mains = mains, accents = accents }
    ns.swatchPalettes.matchCounts = cached
    return cached
end

-- === Panel ===

local function LayoutPanel(panel)
    local keys = ns.MatchStripKeys()
    local counts = Counts()
    local anySelected = next(ns.state.primaryColors) ~= nil
    -- Nil, not empty: the Transmogrifier has not listed a category yet, so
    -- every count is "not asked" rather than zero.
    local countsKnown = counts ~= nil

    -- Fitted to the parent rather than fixed: at broad grain 11 swatches are one
    -- row, but fine grain is 39 and has to wrap inside Blizzard's frame.
    -- Measured against the item list, not the parent: the strip floats on
    -- UIParent so it can be dragged anywhere (see "Floating" below).
    local available = panel.host and panel.host:GetWidth() or 0
    if not available or available < 120 then available = 440 end
    local columns = math.floor((available - 2 * PANEL_INSET) / (SWATCH_SIZE + SWATCH_GAP))
    columns = math.max(MIN_COLUMNS, math.min(MAX_COLUMNS, columns))

    for i, k in ipairs(keys) do
        local btn = panel.swatches[i]
        if not btn then
            btn = CreateStripSwatch(panel)
            panel.swatches[i] = btn
        end

        btn.key = k.key
        btn.mainCount = counts and counts.mains[k.key] or 0
        btn.accentCount = counts and counts.accents[k.key] or 0
        btn.countsKnown = countsKnown
        btn.Swatch:SetColorTexture(k.r, k.g, k.b)

        local col = (i - 1) % columns
        local row = math.floor((i - 1) / columns)
        btn:ClearAllPoints()
        btn:SetPoint("TOPLEFT", panel, "TOPLEFT",
            PANEL_INSET + col * (SWATCH_SIZE + SWATCH_GAP),
            -(PANEL_INSET + HEADER_HEIGHT) - row * (SWATCH_SIZE + SWATCH_GAP))
        RefreshStripSwatch(btn, anySelected)
        btn:Show()
    end

    for i = #keys + 1, #panel.swatches do
        panel.swatches[i]:Hide()
    end

    local n = SelectedCount()
    if n > 0 then
        panel.Label:SetText(("Colours (%d):"):format(n))
    else
        panel.Label:SetText("Colours:")
    end
    panel.GrainButton:SetText(ns.MatchDetail() == "all" and "Less" or "More")

    local rows = math.ceil(#keys / columns)
    -- Sized to the swatches actually laid out, not to the column budget: at
    -- broad grain there are 11 of them and a panel stretched to a 20-column
    -- width would be mostly empty backdrop.
    local usedColumns = math.min(columns, #keys)
    -- ...but never narrower than the header needs, or the buttons hang off it.
    -- The header holds the label, the Swatches checkbox and two buttons.
    local width = math.max(2 * PANEL_INSET + usedColumns * (SWATCH_SIZE + SWATCH_GAP), 270)
    panel:SetSize(width, 2 * PANEL_INSET + HEADER_HEIGHT + rows * (SWATCH_SIZE + SWATCH_GAP))
end

SyncAllPanels = function()
    for _, panel in ipairs(ns.panels) do
        LayoutPanel(panel)
    end
end

-- Called after the Transmogrifier hands over a new category: the counts on
-- every swatch describe what is on screen, so they go stale on a slot change.
function ns.RefreshColorPanels()
    SyncAllPanels()
end

local function ToggleGrain()
    -- Does NOT clear the selection -- ns.SetMatchDetail translates it: a
    -- general "Green" becomes its member greens, and back.
    ns.SetMatchDetail(ns.MatchDetail() == "all" and "general" or "all")
    ns.InvalidateSwatchPalettes()
    SyncAllPanels()
    RefreshAll()
end

-- === Floating ===
--
-- The strip's default spot, under the search box, covers the top row of the
-- appearance grid, so it can be dragged anywhere by its background. It is
-- parented to UIParent rather than to the item list for that reason: a child
-- of the list could be clipped at the list's edges, and could not be parked
-- beside the Transmogrifier at all. Visibility follows the list instead (see
-- ns.RegisterColorPanel).
--
-- The saved position is a plain UIParent anchor. Nil means the default spot,
-- which stays attached to the search box and so follows Blizzard's layout.

local function PlaceStrip(panel)
    panel:ClearAllPoints()
    local pos = ns.state and ns.state.stripPos
    if pos then
        panel:SetPoint(pos[1], UIParent, pos[2], pos[3], pos[4])
    elseif panel.anchorFrame then
        panel:SetPoint("TOPRIGHT", panel.anchorFrame, "BOTTOMRIGHT", 0, -6)
    else
        panel:SetPoint("TOPRIGHT", panel.host, "TOPRIGHT", -20, -40)
    end
end

function ns.ResetStripPosition()
    ns.state.stripPos = nil
    for _, panel in ipairs(ns.panels) do PlaceStrip(panel) end
end

local function CreatePanel(name, host, anchorFrame)
    local panel = CreateFrame("Frame", name, UIParent, "BackdropTemplate")
    panel.host = host
    panel.anchorFrame = anchorFrame
    -- Opaque, because wherever it is dragged the strip sits in front of
    -- something. Floating unbacked swatches read as a rendering fault; a
    -- bordered panel reads as something deliberately on top.
    panel:SetBackdrop({
        bgFile = "Interface/Tooltips/UI-Tooltip-Background",
        edgeFile = "Interface/Tooltips/UI-Tooltip-Border",
        edgeSize = 12,
        insets = { left = 3, right = 3, top = 3, bottom = 3 },
    })
    panel:SetBackdropColor(0.05, 0.05, 0.05, 0.96)
    panel:SetFrameStrata("HIGH")
    -- The strip sits over the appearance grid, so it has to swallow clicks on
    -- its own background. Without this a click on the gap between two swatches
    -- falls through and selects whatever appearance is underneath.
    panel:EnableMouse(true)

    -- Dragged by any part of the panel that isn't a control: the swatches and
    -- buttons take their own clicks, so a drag can only start on the backdrop.
    panel:SetMovable(true)
    panel:SetClampedToScreen(true)
    panel:RegisterForDrag("LeftButton")
    panel:SetScript("OnDragStart", panel.StartMoving)
    panel:SetScript("OnDragStop", function(self)
        self:StopMovingOrSizing()
        -- StartMoving marks a named frame as user-placed, which hands its
        -- position to the client's layout cache. This file owns the position,
        -- and two owners would fight after a /tmpalette resetpos.
        self:SetUserPlaced(false)
        local point, _, relPoint, x, y = self:GetPoint(1)
        ns.state.stripPos = { point, relPoint, x, y }
        PlaceStrip(self)
    end)
    PlaceStrip(panel)

    panel.Label = panel:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    panel.Label:SetPoint("TOPLEFT", panel, "TOPLEFT", PANEL_INSET, -PANEL_INSET)
    panel.Label:SetText("Colours:")

    -- Coverage is reported on hover rather than in the header: a low ratio, not
    -- a bad swatch, is the usual reason a pick returns fewer results than
    -- expected, but it does not deserve permanent space.
    panel.LabelHit = CreateFrame("Frame", nil, panel)
    panel.LabelHit:SetAllPoints(panel.Label)
    panel.LabelHit:SetScript("OnEnter", function(self)
        local withData, total = ns.GetCoverage()
        GameTooltip:SetOwner(self, "ANCHOR_TOP")
        GameTooltip:SetText("Filter by colour")
        GameTooltip:AddLine("Left-click a swatch for a main colour, right-click for the accent.", 0.8, 0.8, 0.8, true)
        if total > 0 and withData < total then
            GameTooltip:AddLine(("Colour data for %d of %d shown"):format(withData, total), 1, 0.5, 0.5)
        end
        GameTooltip:AddLine("Drag the panel to move it. /tmpalette resetpos puts it back.", 0.6, 0.6, 0.6, true)
        GameTooltip:Show()
    end)
    panel.LabelHit:SetScript("OnLeave", GameTooltip_Hide)

    panel.ClearButton = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
    panel.ClearButton:SetSize(46, 18)
    panel.ClearButton:SetPoint("TOPRIGHT", panel, "TOPRIGHT", -PANEL_INSET, -PANEL_INSET + 3)
    panel.ClearButton:SetText("Clear")
    panel.ClearButton:SetScript("OnClick", ClearAll)
    panel.ClearButton:SetScript("OnEnter", function(self)
        GameTooltip:SetOwner(self, "ANCHOR_TOP")
        GameTooltip:SetText("Clear every colour")
        GameTooltip:Show()
    end)
    panel.ClearButton:SetScript("OnLeave", GameTooltip_Hide)

    panel.GrainButton = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
    panel.GrainButton:SetSize(46, 18)
    panel.GrainButton:SetPoint("TOPRIGHT", panel.ClearButton, "TOPLEFT", -4, 0)
    panel.GrainButton:SetText("More")
    panel.GrainButton:SetScript("OnClick", ToggleGrain)
    panel.GrainButton:SetScript("OnEnter", function(self)
        GameTooltip:SetOwner(self, "ANCHOR_TOP")
        if ns.MatchDetail() == "all" then
            GameTooltip:SetText("Fewer colours")
            GameTooltip:AddLine("Groups the shades back into one swatch per colour.", 0.8, 0.8, 0.8, true)
        else
            GameTooltip:SetText("More colours")
            GameTooltip:AddLine("Shows every shade: maroon and red, bronze and brown, jade, teal, slate and more.", 0.8, 0.8, 0.8, true)
        end
        GameTooltip:AddLine("Your picks carry across.", 0.6, 0.6, 0.6)
        GameTooltip:Show()
    end)
    panel.GrainButton:SetScript("OnLeave", GameTooltip_Hide)

    -- The colour swatches drawn on every appearance tile (ColorTags.lua). A
    -- checkbox rather than a third button because it is the only control on
    -- the strip with a persistent state.
    panel.TagsCheck = CreateFrame("CheckButton", nil, panel, "UICheckButtonTemplate")
    panel.TagsCheck:SetSize(20, 20)
    panel.TagsCheck:SetPoint("TOPRIGHT", panel.GrainButton, "TOPLEFT", -6, 2)
    panel.TagsCheck.Label = panel.TagsCheck:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    panel.TagsCheck.Label:SetPoint("RIGHT", panel.TagsCheck, "LEFT", -1, 0)
    panel.TagsCheck.Label:SetText("Swatches")
    panel.TagsCheck:SetChecked(TransmogPaletteDB and TransmogPaletteDB.showColorTags or false)
    panel.TagsCheck:SetScript("OnClick", function(self)
        if ns.ToggleColorTags then ns.ToggleColorTags() end
        -- Read the state back rather than trusting the click: the slash command
        -- writes the same setting, so the checkbox must follow the setting.
        self:SetChecked(TransmogPaletteDB.showColorTags or false)
    end)
    panel.TagsCheck:SetScript("OnEnter", function(self)
        GameTooltip:SetOwner(self, "ANCHOR_TOP")
        GameTooltip:SetText("Show swatches on appearances")
        GameTooltip:AddLine("Marks every appearance with the two colours it matches best, whether or not a filter is on.", 0.8, 0.8, 0.8, true)
        GameTooltip:AddLine("NO DATA means the appearance has no colour information: it is hidden while any filter is active, and never rolled.", 0.9, 0.5, 0.5, true)
        GameTooltip:Show()
    end)
    panel.TagsCheck:SetScript("OnLeave", GameTooltip_Hide)

    -- So /tmpalette swatches and the checkbox cannot disagree.
    ns.UpdateTagsCheckbox = function()
        if panel.TagsCheck then
            panel.TagsCheck:SetChecked(TransmogPaletteDB.showColorTags or false)
        end
    end

    panel.swatches = {}
    return panel
end

-- Called by Core.lua once the Transmogrifier frame exists. Creates one strip
-- anchored near `anchorFrame` inside `parent`, and registers `refreshFn` to be
-- called whenever the selection changes so the filter gets re-applied.
function ns.RegisterColorPanel(host, anchorFrame, refreshFn)
    local panel = CreatePanel("TransmogPalettePanel" .. (#ns.panels + 1), host, anchorFrame)
    table.insert(ns.panels, panel)
    if refreshFn then
        table.insert(refreshCallbacks, refreshFn)
    end
    -- Not a child of the list, so it has to be told when the list comes and
    -- goes -- closing the Transmogrifier or switching to the Sets tab must
    -- take the strip with it.
    host:HookScript("OnShow", function() panel:Show() end)
    host:HookScript("OnHide", function() panel:Hide() end)
    panel:SetShown(host:IsVisible())
    LayoutPanel(panel)
end
