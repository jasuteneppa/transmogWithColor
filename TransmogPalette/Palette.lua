local _, ns = ...

-- Data-driven palette: instead of a free-form color wheel matched with a
-- fuzzy tolerance (tried and abandoned — any fixed tolerance is either too
-- narrow, splitting one real color like "gold" across several picks a
-- player would have to try one at a time, or too wide, bleeding into
-- neighboring colors like a dark oxblood matching a bright salmon pick),
-- the picker only offers colors that actually exist in ColorData.lua,
-- bucketed by hue+lightness and averaged into one representative swatch
-- per bucket. Matching is then exact bucket equality — the same
-- classifier run on both the picked swatch and the item's stored color —
-- so there's no tolerance to mistune.

function ns.RGBToHSV(r, g, b)
    local maxc, minc = math.max(r, g, b), math.min(r, g, b)
    local v = maxc
    local delta = maxc - minc
    local s = (maxc == 0) and 0 or (delta / maxc)
    local h
    if delta == 0 then
        h = 0
    elseif maxc == r then
        h = ((g - b) / delta) % 6
    elseif maxc == g then
        h = (b - r) / delta + 2
    else
        h = (r - g) / delta + 4
    end
    h = h * 60
    if h < 0 then h = h + 360 end
    return h, s, v
end

function ns.HSVToRGB(h, s, v)
    local c = v * s
    local x = c * (1 - math.abs((h / 60) % 2 - 1))
    local m = v - c
    local r, g, b
    if h < 60 then r, g, b = c, x, 0
    elseif h < 120 then r, g, b = x, c, 0
    elseif h < 180 then r, g, b = 0, c, x
    elseif h < 240 then r, g, b = 0, x, c
    elseif h < 300 then r, g, b = x, 0, c
    else r, g, b = c, 0, x end
    return r + m, g + m, b + m
end

-- === Live tuning state ===
--
-- Declared up here rather than beside the tuning code further down, because the
-- two things that are tunable -- the greyscale cuts and the hue band bounds --
-- sit at opposite ends of this file and both need to be told when a slider has
-- moved. See "Live bucket tuning" below for what the numbers mean.
--
-- Two dirty flags, not one: each cache clears its own, and a single shared flag
-- would be cleared by whichever rebuilt first, leaving the other stale.
local tunedBands, tunedDirty = nil, true
local tunedBlack, tunedWhite, tonesDirty = nil, nil, true

function ns.InvalidateBucketTuning()
    tunedDirty, tonesDirty = true, true
end

-- Below these thresholds a color reads as achromatic (black/white/gray) to
-- the eye regardless of its hue value, which becomes noisy/meaningless.
--
-- These are only a BACKSTOP now. ColorData's 5th field is the generator's
-- CIE L*a*b* verdict on whether a cluster has a hue at all, computed against a
-- lightness- and hue-dependent chroma floor. That beats a flat HSV test and is
-- what should normally decide; these catch clusters the generator called
-- chromatic whose averaged HSV still reads grey.
local NEUTRAL_SAT_THRESHOLD = 0.15

-- Deliberately far below the old 0.15. That value discarded the hue of any
-- dark cluster, which fought the generator directly: its chroma floor has a
-- LOW base specifically so dark blue, bronze and brown keep their colour, and
-- then this threw it away at the last step. Measured over the shipped data,
-- 1,042 appearances had a genuinely chromatic primary -- h=228 s=0.49,
-- h=64 s=0.72 -- forced into "black" by value alone. 0.06 is where hue really
-- has stopped being nameable; above it, trust the generator's flag.
local NEUTRAL_VALUE_THRESHOLD = 0.06

-- True when this cluster has no nameable hue. `achromatic` is ColorData's
-- flag; the rest is the backstop described above.
local function IsNeutral(s, v, achromatic)
    return achromatic or s < NEUTRAL_SAT_THRESHOLD or v < NEUTRAL_VALUE_THRESHOLD
end

-- === Greyscale: three tones, and only for pieces that really have no colour ===
--
-- There are exactly THREE greyscale buckets. Five tones were tried (black /
-- darkgray / gray / lightgray / white), and so was a warm/cool tint axis on top
-- of them; both were the wrong answer to the right complaint. The complaint was
-- that the greyscale buckets return armour that is plainly not greyscale, and
-- neither slicing the greys more finely nor tinting them addresses that -- they
-- just produce more, near-identical swatches. Measured: at v <= 0.15 a "warm
-- black" swatch renders rgb(35,27,19) against a "cool black" rgb(19,27,35),
-- which is not a distinction anyone can see at swatch size, and the user
-- assigned three different buckets to nine slots believing they were all black.
-- Cut on the MERGED greyscale value (see MergeNeutrals), which is a weighted
-- mean over the piece's shadows as well as its lit surface and so sits lower
-- than the colour you would name looking at it. WoW's greyscale armour is
-- heavily dark-skewed -- p50 0.26, p90 0.52 -- so a light cut of 0.75 left only
-- 137 appearances in "white" across the whole game. 0.60 gives 623, which is a
-- bucket you can actually roll from, and still means "averages brighter than
-- mid-grey once its own shadows are counted".
local BLACK_MAX = 0.22
local WHITE_MIN = 0.60

-- Never let a tone close entirely: a bucket that can match nothing looks
-- exactly like the addon having lost a colour.
local MIN_TONE_SPAN = 0.04

-- The greyscale cuts as tuned. `ns.state.neutralWidth[tone]` widens one tone in
-- hundredths of value, the same unit the slider reads in.
--
-- Black and white each have one movable edge -- their other side is 0 and 1 --
-- so widening them moves that edge outright. Grey has two, and widening it
-- pushes both, half each, exactly as a hue group's run does.
local function EffectiveTones()
    if not tonesDirty then return tunedBlack, tunedWhite end
    local black, white = BLACK_MAX, WHITE_MIN
    local w = ns.state and ns.state.neutralWidth
    if w then
        local db = (type(w.black) == "number" and w.black or 0) / 100
        local dg = (type(w.gray) == "number" and w.gray or 0) / 100
        local dw = (type(w.white) == "number" and w.white or 0) / 100
        black = black + db - dg / 2
        white = white - dw + dg / 2
        -- Order matters: pin black inside the scale first, then white against
        -- black, so widening two neighbours at once can't invert the pair.
        if black < MIN_TONE_SPAN then black = MIN_TONE_SPAN end
        if black > 1 - 2 * MIN_TONE_SPAN then black = 1 - 2 * MIN_TONE_SPAN end
        if white < black + MIN_TONE_SPAN then white = black + MIN_TONE_SPAN end
        if white > 1 - MIN_TONE_SPAN then white = 1 - MIN_TONE_SPAN end
    end
    tunedBlack, tunedWhite, tonesDirty = black, white, false
    return black, white
end

local function NeutralTone(v)
    local black, white = EffectiveTones()
    if v < black then return "black" end
    if v < white then return "gray" end
    return "white"
end

-- How much of a piece has to be one colour before it stops being greyscale.
--
-- THE key number in this file. Only 2,372 appearances (3.7%) have no coloured
-- region at all, yet the roller was putting 29.5% of them in greyscale buckets
-- -- roughly 8x what the data supports. Of the appearances it called neutral,
-- 87.4% had a coloured region, median 17% of the piece.
--
-- So colour beats tone: an appearance is greyscale only when it has no coloured
-- region reaching this share. Note this is an ABSOLUTE share, not a ratio
-- against the neutral area -- "a fifth of this piece is gold" is a fact about
-- the piece, whereas a ratio makes a gold-trimmed item's bucket depend on how
-- dark its shadows happen to be.
--
-- The number trades the two opposite complaints directly against each other,
-- and there is no ground-truth set to fit it against, so it is tunable at
-- runtime with /tmpalette colorfirst rather than pretending to be derived.
-- Measured greyscale totals: 0.15 -> 11.1%, 0.20 -> 15.0%, 0.25 -> 19.2%,
-- 0.30 -> 23.7%.
ns.DEFAULT_COLOR_FIRST = 0.20

function ns.ColorFirstThreshold()
    local t = ns.state and ns.state.colorFirst
    if type(t) ~= "number" then return ns.DEFAULT_COLOR_FIRST end
    return t
end

-- Which of an appearance's clusters decides its colour, and which is its
-- accent. Returns main, accent.
--
-- Replaces two earlier rules that this subsumes: ColorData's rank order (which
-- discounts neutrals 0.50 when ranking) and the roller's own area penalty. Both
-- were relative weightings trying to express "don't call a colourful thing
-- grey"; the threshold says it directly.
--
-- The accent is whichever cluster comes FIRST IN RANK ORDER that isn't the
-- main one, so when the main colour is rank 1 -- the common case -- the accent
-- is rank 2, exactly as it has always been.
-- An appearance's greyscale pixels arrive as up to THREE separate clusters, not
-- one: the generator pools them into dark/mid/light lightness bands, and each
-- band then competes as its own cluster. Taking the largest band as "the"
-- neutral is wrong, and wrong in one direction -- shadowed pixels are always
-- plentiful, so the dark band usually wins and mid-grey armour reads as black.
--
-- Measured on a live Shoulders list: visual 115178 is 92% greyscale spread
-- 0.16 / 0.52 / 0.78 across the three bands, i.e. a mid grey, and it landed in
-- "black" because the dark band held 41% against 32% and 19%. Merging the bands
-- by weight gives 0.41 and it classifies grey, which is what it looks like.
--
-- Merging also fixes the accent: before this, an appearance's "second colour"
-- could be another band of the SAME grey as its first.
local function MergeNeutrals(ranks)
    local total, valueSum, biggest = 0, 0, nil
    for i = 1, #ranks do
        local c = ranks[i]
        if IsNeutral(c[2], c[3], c[5]) then
            total = total + c[4]
            valueSum = valueSum + c[3] * c[4]
            if not biggest or c[4] > biggest[4] then biggest = c end
        end
    end
    if not biggest then return nil end
    -- One band needs no merging, and returning it as-is avoids a table per
    -- appearance in loops that run over a whole slot.
    if biggest[4] == total then return biggest end
    -- h and s are carried from the largest band purely so the shape matches a
    -- real cluster; nothing reads them once IsNeutral is true.
    return { biggest[1], biggest[2], valueSum / total, total, true }
end

-- How strongly a coloured cluster reads, which is NOT how much of the piece it
-- covers. In HSV, chroma is exactly s * v, so this is the cluster's total
-- chroma: its area times how colourful it is. The extractor already weights
-- pixels by chroma when it looks for hue peaks; this carries the same measure
-- through to deciding which peak wins.
--
-- Ranking by raw area instead had a systematic bias, not just noise. WoW's
-- shadows are bluish, so dark shadowed pixels that barely clear the chroma
-- floor pile up in the blue-violet arc -- and being numerous, they won.
-- "Purple" was quietly becoming the colour of dark armour. Confirmed in game
-- twice: a chest that reads plainly green (a glowing s0.64 v0.89 green) filed
-- under purple behind a larger dull violet, and a silver-and-red shoulder
-- likewise. Measured, 1,501 appearances have their area winner beaten by a
-- rival at least 0.25 more saturated and 0.15 brighter, and the rival is
-- almost always red/gold/green/orange losing to violet/indigo/blue.
local function ColorSalience(c)
    return c[4] * c[2] * c[3]
end

-- === Hand corrections ===
--
-- An escape hatch for appearances the statistics cannot get right, NOT a
-- tuning knob. Pooled cluster statistics have a documented ceiling: they
-- cannot separate "red piece with a green glow" from "green piece with red
-- trim", because both are the same three numbers. Measured 2026-08-11, every
-- rule change that fixed one such item (a value exponent, a value floor, an
-- area cap) roughly DOUBLED the count of mains handed to a duller, darker
-- cluster -- i.e. it bought one item by re-creating the purple-shadow bug in
-- ~250 others. Correcting the handful by name is honest; bending the model to
-- fit them is not.
--
-- Keyed by visualID, which is stable across every classifier change, so these
-- need no version bump and survive a regeneration.
--
-- An override is a table with an optional `main` and an optional `accent`, so
-- either colour can be corrected without disturbing the other:
--
--   [12345] = { main = 2 }                    -- use cluster 2 as the main; the
--                                                extractor found the right
--                                                colour, the ranking picked
--                                                the wrong one
--   [12345] = { main = { 120, 0.75, 0.5 } }   -- h, s, v (optional 4th =
--                                                achromatic) for a colour the
--                                                extractor never found at all,
--                                                e.g. a panel that lost its
--                                                cluster slot to neutral
--                                                shading bands
--   [12345] = { main = 2, accent = 3 }        -- both
--
-- An absent field means "compute it normally", which is why the computed
-- answer is worked out first and then patched rather than short-circuited.
--
-- THREE LAYERS, highest first. The split exists so an addon update can never
-- destroy a player's own corrections:
--
--   1. TransmogPaletteDB.colorOverrides  -- the player's own fixes
--   2. TransmogPaletteDB.authorOverrides -- the author's staging area, only
--                                           written while dev mode is on
--   3. ns.ColorOverrides (below)         -- shipped with the addon
--
-- Layers 1 and 2 live in SavedVariables (WTF\Account\...), which an addon
-- update never touches -- only Interface\AddOns\ is replaced. So a player's
-- fixes survive every patch by construction, and they are also deliberately
-- exempt from the CLASSIFIER_VERSION wipe in Core.lua: an override is keyed by
-- visualID and stores raw h/s/v, so unlike a bucket key it cannot go stale.
--
-- The player's layer wins so a bad SHIPPED correction can always be worked
-- around in game, without editing the addon or waiting for a release.
ns.ColorOverrides = {}

function ns.OverrideFor(visualID)
    if not visualID then return nil end
    local db = ns.state
    if db then
        local own = db.colorOverrides and db.colorOverrides[visualID]
        if own ~= nil then return own end
        local author = db.authorOverrides and db.authorOverrides[visualID]
        if author ~= nil then return author end
    end
    return ns.ColorOverrides[visualID]
end

-- How many appearances the ACTIVE layer corrects. Counted rather than stored,
-- because the store is edited from three places (slash command, picker, menu)
-- and a cached count is one more thing to keep honest.
function ns.OverrideCount()
    local store = ns.OverrideStore()
    local n = 0
    for _ in pairs(store) do n = n + 1 end
    return n
end

-- Every bucket at the FILTER's grain, drawn canonically, for the override
-- picker. Unlike the filter's palette this is not built from what is on
-- screen: correcting an item means naming the colour it should have had, which
-- may be one nothing in this category currently carries. So there are no
-- counts, and every bucket is offered.
function ns.OverridePalette()
    local grain = ns.FilterGrain()
    local out = {}
    for _, key in ipairs(ns.GrainBuckets(grain)) do
        local h, s, v = ns.CanonicalSwatch(key, grain)
        if h then
            out[#out + 1] = { key = key, h = h, s = s, v = v }
        end
    end
    return out
end

-- Turns a picked swatch into the stored override form. The achromatic flag is
-- re-derived from the KEY rather than taken from the swatch, because
-- OpenSwatchPicker's onPick only carries h/s/v/key -- and a neutral stored
-- without its flag would be at the mercy of the HSV backstop instead of
-- stating plainly that it has no hue.
function ns.OverrideSpecFromKey(key)
    local h, s, v, achromatic = ns.CanonicalSwatch(key, ns.FilterGrain())
    if not h then return nil end
    return { h, s, v, achromatic or false }
end

-- Everything that goes stale when an override changes. Bucket KEYS are
-- untouched, so saved picks stay valid -- but which appearances sit in each
-- bucket has moved, so every cached palette and per-slot candidate list is
-- stale. Same sequence as /tmpalette colorfirst.
function ns.OverridesChanged()
    ns.InvalidateSwatchPalettes()
    if ns.InvalidateRandomizerSlots then ns.InvalidateRandomizerSlots() end
    if ns.RefreshRandomizerPanel then ns.RefreshRandomizerPanel() end
    if ns.RefreshColorPanels then ns.RefreshColorPanels() end
    if ns.RefreshFilter then ns.RefreshFilter() end
end

-- Which store /tmpalette override and the right-click menu write to. Dev mode
-- is the AUTHOR's switch: entries staged there are the ones exported into the
-- shipped table above. A player never turns this on, so their fixes stay in
-- their own layer and are never confused with shipping data.
function ns.OverrideStore()
    -- Guarded: this is reachable from the right-click menu, which lives outside
    -- this addon's own load order, so it must not assume InitDB has run.
    if not ns.state then return {}, "none" end
    if ns.state.devOverrides then
        ns.state.authorOverrides = ns.state.authorOverrides or {}
        return ns.state.authorOverrides, "author"
    end
    ns.state.colorOverrides = ns.state.colorOverrides or {}
    return ns.state.colorOverrides, "player"
end

-- Resolves one side of an override to a cluster, or nil if it cannot be
-- honoured (an index pointing past the clusters this appearance actually has).
local function OverrideCluster(ranks, spec)
    if type(spec) == "number" then
        return ranks[spec]
    elseif type(spec) == "table" then
        -- Weight is 1 because a hand-named colour is a statement about the
        -- whole piece. Nothing downstream reads a main's weight anyway --
        -- BuildPaletteFromColors takes only h/s/v and the achromatic flag.
        return { spec[1], spec[2], spec[3], 1, spec[4] or false }
    end
    return nil
end

-- visualID is optional and used ONLY to look up a hand correction. Every
-- caller that has one must pass it, or that appearance silently keeps the
-- colour the override was written to fix.
function ns.MainAndAccent(ranks, visualID)
    if not ranks then return nil, nil end
    local main, accent = ns.ComputeMainAndAccent(ranks)

    local override = ns.OverrideFor(visualID)
    if override then
        -- Patched, not short-circuited: an override may name only one of the
        -- two, and the other must still be computed. An unhonourable side
        -- keeps its computed value rather than becoming nil -- a stale
        -- correction should degrade to normal behaviour, not blank the
        -- appearance out of every bucket.
        main = OverrideCluster(ranks, override.main) or main
        accent = OverrideCluster(ranks, override.accent) or accent
    end

    return main, accent
end

function ns.ComputeMainAndAccent(ranks)
    local threshold = ns.ColorFirstThreshold()
    local first, second
    local firstScore, secondScore = -1, -1
    local coloredTotal = 0
    for i = 1, #ranks do
        local c = ranks[i]
        if not IsNeutral(c[2], c[3], c[5]) then
            coloredTotal = coloredTotal + c[4]
            local score = ColorSalience(c)
            if score > firstScore then
                first, second = c, first
                firstScore, secondScore = score, firstScore
            elseif score > secondScore then
                second, secondScore = c, score
            end
        end
    end

    local neutral = MergeNeutrals(ranks)

    -- The threshold is tested against ALL the colour on the piece, not just its
    -- largest single hue. "Is this greyscale?" is a question about how much of
    -- the piece is coloured at all; a shoulder whose red is split across the red
    -- and rust bands is not thereby black. Measured: 1,822 appearances (2.9%)
    -- have no single colour reaching the threshold while their colours together
    -- clear it, and they are exactly the ones that looked wrong in game --
    -- visual 90550 reads plainly red (a vivid s0.73 highlight) off two clusters
    -- of 0.14 and 0.12 sitting on a very dark neutral.
    --
    -- WHICH colour it becomes is still the largest single hue; only the
    -- greyscale decision pools them.
    if first and coloredTotal >= threshold then
        -- Accent is the appearance's other colour, whichever that is: its
        -- second hue, or its greyscale if that covers more. Compared by AREA,
        -- not salience -- greyscale has no chroma to compare against, so the
        -- only question the two share is how much of the piece each covers.
        if second and neutral then
            return first, (second[4] >= neutral[4]) and second or neutral
        end
        return first, second or neutral
    end

    -- No colour big enough: the piece is greyscale, and its accent is whatever
    -- colour it does carry.
    if neutral then return neutral, first end
    return first or ranks[1], nil
end

-- Hue is bucketed into PERCEPTUAL bands, not equal slices, because hue
-- discrimination is not uniform and neither is WoW's armor art. Equal 30°
-- slices were measured on a live Hands list: one bucket held 41 of 180
-- appearances (23%) spanning h3 (dark maroon) through h28 (saturated rust) —
-- so a "brown" swatch returned red gloves, which is what prompted this.
--
-- The warm end gets narrow bands (people separate red / rust / orange / gold
-- sharply, and most armor lives there); the cool end gets wide ones (a broad
-- sweep of blue-green all reads as "blue-ish"). Total swatch count across the
-- whole dataset is unchanged at 41 — the degrees are redistributed, not added,
-- because near-duplicate swatches were already a complaint.
--
-- Each entry is the band's upper bound, exclusive. The last band wraps past
-- 345° back into red.
--
-- THERE IS NO ORANGE BAND. Orange and gold are one band, [32,58), 2026-08-30.
-- This reverses the split made in ROLL_SCHEME_VERSION 2, so the reasoning is
-- kept in full rather than left to be re-derived.
--
-- WoW's orange and WoW's gold are the same hue. Real gold armour extracts at
-- h=33-45 -- "Golden Scale Cuirass" h=42 covering 81%, "Gilded Ornamental
-- Mantle" h=40 covering 97% -- and sRGB orange is h=39. The old edge at 46 put
-- almost all actual gold on the ORANGE side, so the gold bucket held 2,422
-- appearances and hardly any of them were gold. Measured against item names,
-- gold matched 4.2%, three times worse than any other family.
--
-- Moving the edge was tried first (46 -> 40) and REVERTED the same day. It
-- improved every number and made the filter worse: the two buckets' median hues
-- closed from 15 apart to 9, and both swatches started returning the same
-- amber-looking armour. The lesson is about the metric. analyze_names.py scores
-- "does this bucket match the word in the item name"; whether two adjacent
-- buckets feel like different filters is not in that metric at all. Do not move
-- a band edge on that score alone -- look at the buckets in game.
--
-- Merging is the honest fix, because the boundary was never real. The hue
-- histogram over all appearances has NO valley anywhere between 0 and 70: red,
-- rust, orange and gold are one continuous ramp peaking at h=30, and a bucket
-- edge on a smooth slope is arbitrary wherever it is placed.
--
-- The original reason for splitting them was bucket balance, and it no longer
-- holds. Merged gold is 10,126 of 64,722 appearances, 15.6% -- SMALLER than
-- brown (19.2%) and red (18.1%), both of which are unmerged. The grab-bag
-- failure that killed the red+rust merge was 32.7% in one bucket.
--
-- The upper edge is 58, not 70. The old gold band reached to 70, and 807
-- appearances in it sat at h >= 58 -- olive and chartreuse, confirmed green by
-- eye on rendered sheets before this was changed. They now group to green.
--
-- Still unfixed and NOT a band problem: 21% of this bucket is trim, a gold
-- filigree cluster out-ranking a base that is mostly black or grey. No hue
-- boundary touches that -- see the note on ColorSalience.
local HUE_BANDS = {
    { 18, "red" }, { 32, "rust" }, { 58, "gold" },
    { 100, "olive" }, { 155, "green" }, { 195, "teal" }, { 250, "blue" },
    { 275, "indigo" }, { 300, "violet" }, { 325, "purple" }, { 345, "pink" },
}

-- === Live bucket tuning ===
--
-- Every boundary in this file was placed by argument, shipped, and then judged
-- in game -- which is a terrible loop, because the person who can see whether a
-- bucket is right has to wait for someone else to guess a number. One boundary
-- was moved and reverted the same day on exactly that cycle.
--
-- So the bounds are tunable at runtime. `ns.state.bucketWidth[group]` widens or
-- narrows a whole colour GROUP in degrees: half is taken off its lower edge and
-- half added to its upper, pushing into whichever neighbours it meets. Groups
-- rather than bands because a group is what the player actually sees -- "green"
-- at broad grain is olive+green, and widening it should move the outside of
-- that pair, not split it.
--
-- Bucket KEYS never change, only which appearances land in them, so a saved
-- selection stays valid and no version stamp is needed.
--
-- The effective table is cached and rebuilt only when a slider moves: HueBand
-- runs once per appearance per palette build, several thousand times per slot.
local MIN_BAND_WIDTH = 5

-- Forward declaration: HUE_GROUPS is defined below, after the swatch ordering
-- it depends on, but EffectiveBands needs it. Without this the reference
-- resolves to a nil GLOBAL rather than the local declared later, and every
-- band silently loses its group.
local HUE_GROUPS

local function EffectiveBands()
    if tunedBands and not tunedDirty then return tunedBands end
    local widths = ns.state and ns.state.bucketWidth
    local out = {}
    for i = 1, #HUE_BANDS do out[i] = { HUE_BANDS[i][1], HUE_BANDS[i][2] } end

    if widths then
        -- A group owns a contiguous run of bands; widening it moves the run's
        -- OUTER edges. The lower edge of a run is the upper bound of whatever
        -- band precedes it, so this writes to index-1 -- with a wrap, since red
        -- begins at the last band's bound and runs through 0.
        local first, last = {}, {}
        for i = 1, #out do
            local grp = HUE_GROUPS[out[i][2]]
            if grp then
                if not first[grp] then first[grp] = i end
                last[grp] = i
            end
        end
        for grp, d in pairs(widths) do
            if type(d) == "number" and d ~= 0 and first[grp] then
                local half = d / 2
                out[last[grp]][1] = out[last[grp]][1] + half
                local before = first[grp] - 1
                if before < 1 then before = #out end
                out[before][1] = out[before][1] - half
            end
        end
        -- Keep the bounds strictly increasing. Widening two neighbours at once
        -- can otherwise invert a pair, which would make a band match nothing and
        -- look exactly like the addon losing a colour.
        for i = 2, #out do
            if out[i][1] < out[i - 1][1] + MIN_BAND_WIDTH then
                out[i][1] = out[i - 1][1] + MIN_BAND_WIDTH
            end
        end
        for i = 1, #out do
            if out[i][1] > 360 - MIN_BAND_WIDTH then out[i][1] = 360 - MIN_BAND_WIDTH end
        end
        for i = #out - 1, 1, -1 do
            if out[i][1] > out[i + 1][1] - MIN_BAND_WIDTH then
                out[i][1] = out[i + 1][1] - MIN_BAND_WIDTH
            end
        end
    end

    tunedBands, tunedDirty = out, false
    return out
end

local function HueBand(h)
    h = h % 360
    local bands = EffectiveBands()
    for i = 1, #bands do
        if h < bands[i][1] then return bands[i][2] end
    end
    return bands[1][2]  -- above the last bound: wraps into red
end

-- === The tuning API the slider talks to ===
--
-- One set of calls covers both axes, because from the player's side there is
-- only one gesture: pick a swatch, widen or narrow it. What "wider" means
-- differs underneath -- degrees of hue for a colour, hundredths of lightness
-- for black/grey/white -- but both are stored in the slider's own units and
-- converted at the point of use, so the UI never has to know which it has.

local NEUTRAL_TONES = { black = true, gray = true, white = true }

function ns.IsNeutralBucket(group)
    return NEUTRAL_TONES[group] or false
end

-- The tunable group a bucket key belongs to. Keys carry a value suffix at the
-- finer grains ("olive_dark"), and the band they name may group with others --
-- widening what the player calls green has to move olive with it.
function ns.BucketGroup(key)
    if not key then return nil end
    if NEUTRAL_TONES[key] then return key end
    local band = key:match("^(%a+)_") or key
    return HUE_GROUPS[band] or band
end

local function TuneStore(group)
    if not ns.state then return nil end
    if NEUTRAL_TONES[group] then
        ns.state.neutralWidth = ns.state.neutralWidth or {}
        return ns.state.neutralWidth
    end
    ns.state.bucketWidth = ns.state.bucketWidth or {}
    return ns.state.bucketWidth
end

-- How far this group has been tuned, in slider units. Read back rather than
-- remembered by the slider, so the control can't drift from the classifier.
function ns.TuneDelta(group)
    local store = TuneStore(group)
    local d = store and store[group]
    return type(d) == "number" and d or 0
end

function ns.SetTuneDelta(group, points)
    local store = TuneStore(group)
    if not store then return end
    store[group] = (points ~= 0) and points or nil
    ns.InvalidateBucketTuning()
end

function ns.ResetBucketTuning()
    ns.state.bucketWidth = {}
    ns.state.neutralWidth = {}
    ns.InvalidateBucketTuning()
end

function ns.AnyBucketTuning()
    -- Not ipairs over a two-element table: either store can be nil, and ipairs
    -- would stop at the hole and report "no tuning" while a group is tuned.
    local hue, neutral = ns.state.bucketWidth, ns.state.neutralWidth
    if hue and next(hue) ~= nil then return true end
    if neutral and next(neutral) ~= nil then return true end
    return false
end

-- The effective span of a hue group in degrees. Returns nil for a neutral,
-- which is measured on the lightness scale instead.
function ns.BucketSpan(group)
    if NEUTRAL_TONES[group] then return nil end
    local bands = EffectiveBands()
    local lo, hi
    for i = 1, #bands do
        if HUE_GROUPS[bands[i][2]] == group then
            local before = i - 1
            if before < 1 then before = #bands end
            if not lo then lo = bands[before][1] end
            hi = bands[i][1]
        end
    end
    if not lo then return nil end
    local span = hi - lo
    if span <= 0 then span = span + 360 end
    return span, lo, hi
end

-- Which buckets sit either side of this one, so the tuner can say "green grows
-- into gold and blue" instead of describing degrees of hue. Naming the two
-- buckets that actually gain and lose appearances is the only description of
-- the control that means anything without reading the source.
function ns.TuneNeighbours(group)
    if NEUTRAL_TONES[group] then
        if group == "black" then return "gray" end
        if group == "white" then return "gray" end
        return "black", "white"
    end
    local bands = EffectiveBands()
    local first, last
    for i = 1, #bands do
        if HUE_GROUPS[bands[i][2]] == group then
            first = first or i
            last = i
        end
    end
    if not first then return nil end
    local before = first - 1
    if before < 1 then before = #bands end
    local after = last + 1
    if after > #bands then after = 1 end
    local lo = HUE_GROUPS[bands[before][2]] or bands[before][2]
    local hi = HUE_GROUPS[bands[after][2]] or bands[after][2]
    if lo == hi then return lo end
    return lo, hi
end

-- Where a group's bounds actually sit right now, as text. The slider shows this
-- rather than its own value alone: two neighbours widened at once clamp against
-- each other, and a readout that reported the requested number would then be
-- quietly lying about what the classifier is doing.
function ns.TuneRangeText(group)
    if NEUTRAL_TONES[group] then
        local black, white = EffectiveTones()
        if group == "black" then return ("0.00 – %.2f"):format(black) end
        if group == "gray" then return ("%.2f – %.2f"):format(black, white) end
        return ("%.2f – 1.00"):format(white)
    end
    local span, lo, hi = ns.BucketSpan(group)
    if not span then return nil end
    return ("%d° – %d° (%d° wide)"):format(lo % 360, hi % 360, span)
end

-- Everything that goes stale when a bound moves. Bucket KEYS are untouched, so
-- saved picks stay valid -- only which appearances sit in each bucket changes,
-- which is the same blast radius as an override.
function ns.BucketTuningChanged()
    ns.InvalidateBucketTuning()
    ns.OverridesChanged()
end

ns.HueBands = HUE_BANDS

-- Stable grid position for a swatch, derived from its bucket key. Sorting by
-- the averaged hue would scatter a wrapping band (red) across both ends.
local NEUTRAL_ORDER = { black = 1, gray = 2, white = 3 }
local BAND_ORDER = {}
for i = 1, #HUE_BANDS do BAND_ORDER[HUE_BANDS[i][2]] = i end

function ns.SwatchSortOrder(swatch)
    local key = swatch.key
    if NEUTRAL_ORDER[key] then return NEUTRAL_ORDER[key] end
    -- `or key` covers the coarsest grain, where a key is a bare band name with
    -- no value suffix ("green" rather than "green_dark").
    local band = key:match("^(%a+)_") or key
    -- Offset must clear every NEUTRAL_ORDER value (now 15, not 5) or a hue
    -- swatch sorts into the middle of the neutrals.
    return 100 + (BAND_ORDER[band] or 99)
end

-- === Grain: how coarse the RANDOMISER's buckets are ===
--
-- The filter keeps ClassifyColor untouched -- picking one known colour wants
-- fine buckets. Rolling wants the opposite: a bucket you can draw from. Under
-- the filter's 41 buckets, green splits into olive/green x dark/mid/light, and
-- measured over all 63,742 appearances the thin ones are genuinely unusable --
-- green_light 201, olive_light 193, pink_light 20 in the whole game. Divided
-- across a single slot's collected appearances that is the "one or two pieces"
-- that makes a roll pointless.
--
-- Groups are adjacent bands that read as one colour when the question is
-- "something greenish" rather than "this exact green". Measured bucket medians:
-- fine 723, medium 1575, coarse 3829, broad 5716. See tools/analyze_grain.py,
-- which mirrors this logic -- change both together.
-- red and rust are NOT merged. Merging them was tried and put 20,839 of 63,742
-- appearances (32.7%) into one bucket that read as a brown grab-bag -- and it
-- re-created the exact failure HUE_BANDS was introduced to fix, where one
-- bucket spanned dark maroon to saturated rust and a "brown" swatch returned
-- red gloves. Split apart, the biggest bucket drops to 16.8%. Orange is kept
-- out of gold for the same balance reason. See tools/analyze_groups.py.
--
-- TEAL STAYS WITH BLUE. Moving it to green was tried on 2026-08-11 and the
-- user rejected it in game the same day: "it ended up putting some very blue
-- looking items in the green bucket and it doesn't seem worth it". Do not
-- re-derive it from the (real) statistic below.
--
-- The motivation was sound: broad "green" covers only h70-155, so jade and
-- sea-green armour is filed as blue and cannot be found under a green filter.
-- A live Shoulders dump showed visual 109812 = gold w0.27 plus an h162 s0.55
-- w0.18 jade panel invisible to the green swatch, and 1,591 appearances have a
-- teal-band main at p50 s0.64. Regrouping took green 3,444 -> 5,035 and blue
-- 8,284 -> 6,693, which also looked like it would fix green being the thinnest
-- chromatic bucket.
--
-- Why it failed anyway: the teal BAND is 155-195, and its upper half is cyan,
-- not jade -- 689 of those appearances sit at h180-199. Whatever it does for
-- jade, it also drags plainly blue armour into green, and a wrong item in the
-- bucket you asked for is far more visible than a missing one. Fixing it
-- properly means splitting the band around h180, which changes HUE_BANDS and
-- so changes the signed-off FINE grain -- a much bigger move than this was.
-- No `orange` entry: orange and gold are a single band now, not two bands that
-- group together. See the note on HUE_BANDS.
-- Assignment, not declaration: forward-declared above so EffectiveBands can see it.
HUE_GROUPS = {
    red = "red", rust = "brown",
    gold = "gold",
    olive = "green", green = "green",
    teal = "blue", blue = "blue",
    indigo = "purple", violet = "purple", purple = "purple",
    pink = "pink",
}

-- "brown" is a group name, not a band name, so it needs a grid position of its
-- own -- it sits where rust does.
BAND_ORDER.brown = BAND_ORDER.rust

-- Swatches for coarse buckets are drawn as a CANONICAL colour, not as the
-- bucket's average. Averaging worked while buckets were narrow, but a coarse
-- "blue" bucket spans navy through sky through slate, and its mean is a murky
-- grey-blue that reads as no colour at all. The picker's job is to say "blue",
-- so it shows blue.
--
-- Hues sit inside their group's band range so the canonical colour classifies
-- back into its own bucket; that is asserted at runtime, not assumed.
local CANONICAL_HUE = {
    red    = { h = 6,   s = 0.85 },
    brown  = { h = 25,  s = 0.65 },
    -- 42, not the old 52. The merged band is [32,58) and its contents sit at
    -- hue p25=34, median 39, p75=44 -- 52 was out past the 95th percentile, so
    -- the swatch advertised a yellow the bucket barely contains. 42 reads as
    -- gold rather than orange while sitting next to the median.
    gold   = { h = 42,  s = 0.85 },
    green  = { h = 120, s = 0.75 },
    blue   = { h = 215, s = 0.80 },
    -- 312, not 285: "purple" is BOTH a band (300-325) and a group name, and 285
    -- falls in the violet band -- so at fine grain the purple swatch classified
    -- as violet. 312 is inside the purple band and still groups to purple.
    purple = { h = 312, s = 0.70 },
    pink   = { h = 335, s = 0.70 },
    -- Also valid when the grain doesn't group, so a fine key still works.
    rust   = { h = 25,  s = 0.65 },
    olive  = { h = 85,  s = 0.70 },
    teal   = { h = 175, s = 0.75 },
    indigo = { h = 262, s = 0.70 },
    violet = { h = 287, s = 0.70 },
}

-- Sits mid-band so each classifies back into its own bucket, which is asserted
-- by tools/analyze_grain.py rather than assumed.
local CANONICAL_NEUTRAL = { black = 0.10, gray = 0.48, white = 0.90 }

-- Value chosen so it lands inside the key's own value band. Brown is the one
-- hue that must stay dark -- a bright h=25 is just orange.
local CANONICAL_VALUE = {
    dark = 0.34, mid = 0.52, light = 0.80,
}

-- The 4th return is the achromatic flag. Callers must forward it to the
-- round-trip check, or a neutral swatch can classify as a hue.
function ns.CanonicalSwatch(key, grainName)
    local nv = CANONICAL_NEUTRAL[key]
    if nv then return 0, 0, nv, true end

    local band, vband = key:match("^(%a+)_(%a+)$")
    band = band or key
    local c = CANONICAL_HUE[band]
    if not c then return nil end

    local v
    if vband then
        v = CANONICAL_VALUE[vband]
    else
        v = (band == "brown") and 0.45 or 0.74
    end
    if not v then return nil end
    -- Light brown must clear the "light" band floor (>0.65) or it classifies as
    -- brown_mid; 0.62 did exactly that. Tan is the honest look for it.
    if band == "brown" and vband == "light" then v = 0.71 end
    return c.h, c.s, v
end

local GRAINS = {
    fine   = { group = false, values = 3, label = "fine (same as the filter)" },
    medium = { group = true,  values = 3, label = "medium" },
    coarse = { group = true,  values = 2, label = "coarse" },
    broad  = { group = true,  values = 1, label = "broad (hue only)" },
}

ns.Grains = GRAINS
ns.GRAIN_ORDER = { "fine", "medium", "coarse", "broad" }
ns.DEFAULT_GRAIN = "broad"

-- Bump whenever HUE_GROUPS or the value bands change: saved slot colours store
-- bucket KEYS, and a regrouping makes an old key mean something different or
-- nothing at all. Same hazard as CLASSIFIER_VERSION, tracked separately so this
-- never clears the filter's colours.
--   1: red+rust merged, orange+gold merged
--   2: red/rust split (rust renamed brown), orange split from gold
--   3: neutral tones split warm/cool at every grain
--   4: greyscale reduced to black/gray/white, no tint keys
--   5: teal regrouped from blue to green
--   6: teal reverted to blue (5 was rejected in game the same day). Bumped
--      FORWARD rather than back to 4, so a client that ran 5 still clears
--   7: orange and gold merged into one band again, undoing 2. The "orange" key
--      no longer exists at any grain, so a saved slot colour holding it would
--      silently match nothing
ns.ROLL_SCHEME_VERSION = 7

-- Same contract as ClassifyColor -- the SAME function classifies both the
-- item's colour and the picked swatch, so a match is exact bucket equality.
function ns.ClassifyColorGrained(h, s, v, grainName, achromatic)
    local g = GRAINS[grainName] or GRAINS[ns.DEFAULT_GRAIN]

    -- Greyscale does NOT vary with grain. Three tones is already the coarsest
    -- honest split, and making it finer at fine grain would only re-create the
    -- pile of near-identical dark swatches this replaced.
    if IsNeutral(s, v, achromatic) then
        return NeutralTone(v)
    end

    local band = HueBand(h)
    if g.group then band = HUE_GROUPS[band] or band end
    if g.values == 1 then return band end
    if g.values == 3 then
        local vb = (v < 0.35) and "dark" or (v < 0.65) and "mid" or "light"
        return band .. "_" .. vb
    end
    return band .. "_" .. ((v < 0.5) and "dark" or "light")
end

-- Assigns any (h,s,v) to a bucket key. The SAME function classifies both
-- an item's stored color and whatever swatch the player picked, so two
-- colors "match" exactly when they land in the same bucket.
function ns.ClassifyColor(h, s, v, achromatic)
    if IsNeutral(s, v, achromatic) then
        return NeutralTone(v)
    end
    local vBand
    if v < 0.35 then vBand = "dark"
    elseif v < 0.65 then vBand = "mid"
    else vBand = "light" end
    return HueBand(h) .. "_" .. vBand
end

-- === The FILTER's grain ===
--
-- The filter used to be locked to `fine`. It now shares the grain machinery
-- with the randomiser, for a usability reason rather than a colour one: the
-- picker is an always-visible strip of toggles now, not a popup of three slots,
-- and 39 permanently-visible swatches is a wall. At `broad` it is 11, one row,
-- and picking "several greens" costs one click instead of spending a slot on
-- each shade -- which is exactly what the three-slot cap made expensive.
--
-- ClassifyColorGrained(..., "fine", ...) is identical to ClassifyColor, so this
-- is a strict generalisation: the fine path is byte-for-byte what shipped and
-- was verified in game.
--
-- Stored SEPARATELY from randomizerGrain. They answer different questions --
-- "how precisely do I want to search" versus "how big a pool do I want to roll
-- from" -- and tying them would make changing one silently invalidate the
-- other's saved keys.
ns.DEFAULT_FILTER_GRAIN = "broad"

function ns.FilterGrain()
    local g = ns.state and ns.state.filterGrain
    if not g or not GRAINS[g] then return ns.DEFAULT_FILTER_GRAIN end
    return g
end

-- The single classifier the filter uses on BOTH sides of a match. Every call
-- site that used ns.ClassifyColor for filtering must go through this instead,
-- or the swatch grid and MatchesFilter start disagreeing about what bucket an
-- appearance is in -- the recurring failure this file keeps warning about.
function ns.FilterClassify(h, s, v, achromatic)
    return ns.ClassifyColorGrained(h, s, v, ns.FilterGrain(), achromatic)
end

-- Every bucket key a grain can produce, in grid order.
--
-- The strip renders THIS, not just the buckets present in the current slot, so
-- a swatch keeps the same position when you switch from Hands to Legs. A grid
-- built only from what is on screen would reshuffle on every slot change, and
-- an always-visible grid whose contents move is worse than a popup -- the whole
-- point is that you learn where a colour lives. Absent colours render dimmed
-- with a count of 0, which is also a straight answer to "does this slot have
-- anything green".
local VALUE_SUFFIXES = {
    [1] = { "" },
    [2] = { "dark", "light" },
    [3] = { "dark", "mid", "light" },
}

local grainBucketCache = {}

function ns.GrainBuckets(grainName)
    local cached = grainBucketCache[grainName]
    if cached then return cached end
    local g = GRAINS[grainName] or GRAINS[ns.DEFAULT_GRAIN]

    -- Greyscale does not vary with grain (see ClassifyColorGrained), so these
    -- three are constant across every grain and sort first.
    local keys = { "black", "gray", "white" }

    local bands, seen = {}, {}
    for i = 1, #HUE_BANDS do
        local band = HUE_BANDS[i][2]
        if g.group then band = HUE_GROUPS[band] or band end
        if not seen[band] then
            seen[band] = true
            bands[#bands + 1] = band
        end
    end

    for _, band in ipairs(bands) do
        for _, suffix in ipairs(VALUE_SUFFIXES[g.values]) do
            keys[#keys + 1] = (suffix == "") and band or (band .. "_" .. suffix)
        end
    end

    grainBucketCache[grainName] = keys
    return keys
end

-- Carries a selection across a grain change instead of clearing it.
--
-- Selections store bucket KEYS, so a grain change would normally rot them the
-- way CLASSIFIER_VERSION does. But the mains are an OR'd SET now, which makes
-- the translation expressible: one broad "green" is exactly the set of fine
-- greens, and a set can hold all of them.
--
-- Both directions are probed, and the results unioned, because neither alone is
-- right on its own. Probing new keys against the old grain (a new key is in if
-- its canonical colour classified to something selected) is lossless going
-- COARSE -> FINE but drops shades going the other way; probing old keys forward
-- through the new grain is right going FINE -> COARSE and lossy going finer.
-- The union is correct in both, and needs nothing from the Transmogrifier --
-- deliberately, since the grain button has to work before any slot is listed.
local function TranslateKeys(selected, oldGrain, newGrain)
    local out = {}
    if not next(selected) then return out end

    for _, key in ipairs(ns.GrainBuckets(newGrain)) do
        local h, s, v, achromatic = ns.CanonicalSwatch(key)
        if h and selected[ns.ClassifyColorGrained(h, s, v, oldGrain, achromatic)] then
            out[key] = true
        end
    end

    for key in pairs(selected) do
        local h, s, v, achromatic = ns.CanonicalSwatch(key)
        if h then
            out[ns.ClassifyColorGrained(h, s, v, newGrain, achromatic)] = true
        end
    end

    return out
end

-- Rebuilds a stored selection table ({key -> colour}) against a new grain,
-- re-deriving each surviving key's swatch colour so the strip draws it right.
local function RemapSelection(selection, oldGrain, newGrain)
    local asSet = {}
    for key in pairs(selection) do asSet[key] = true end
    local translated = TranslateKeys(asSet, oldGrain, newGrain)

    local out = {}
    for key in pairs(translated) do
        local h, s, v = ns.CanonicalSwatch(key)
        if h then out[key] = { h = h, s = s, v = v, key = key } end
    end
    return out
end

function ns.SetFilterGrain(newGrain)
    if not GRAINS[newGrain] then return false end
    local old = ns.FilterGrain()
    if old == newGrain then return true end

    ns.state.primaryColors = RemapSelection(ns.state.primaryColors, old, newGrain)

    -- The accent is singular, so it cannot expand the way the mains can. It
    -- takes the single new bucket its own colour lands in, which is the honest
    -- one-to-one answer; going coarse -> fine that necessarily narrows it.
    local accent = ns.state.accentColor
    if accent then
        local h, s, v, achromatic = ns.CanonicalSwatch(accent.key)
        if h then
            local key = ns.ClassifyColorGrained(h, s, v, newGrain, achromatic)
            local ch, cs, cv = ns.CanonicalSwatch(key)
            ns.state.accentColor = ch and { h = ch, s = cs, v = cv, key = key } or nil
        else
            ns.state.accentColor = nil
        end
    end

    ns.state.filterGrain = newGrain
    ns.InvalidateSwatchPalettes()
    return true
end

-- Two palettes, keyed "primary" and "accent". The primary picker offers the
-- colours that occur as some appearance's MAIN colour; the accent picker offers
-- its second. Sourcing each from what it actually matches against is deliberate
-- — offering a colour in a picker that can never match there just produces a
-- swatch that returns zero results.
--
-- Averages each bucket into one representative swatch. Cached per kind;
-- ColorData.lua doesn't change during a session.
ns.swatchPalettes = {}

-- The visualIDs the Transmogrifier is currently listing, which the game has
-- already scoped to this character's class / armor type / slot / collected
-- state. The palette is built from THESE, not from all of ns.ItemColors:
-- otherwise the swatches (and their counts) describe the whole offline
-- dataset — including appearances this character can't equip — while the
-- filter only ever runs against what's on screen. That mismatch is what
-- made counts look plausible and then return nothing on click.
local currentVisuals

-- The frame is handed every appearance for the slot but only renders the ones
-- the player has collected AND can use (class restrictions -- an entry's
-- useError reads "This appearance can't be used by your class"). Confirmed
-- live: 907 entries handed over, 254 rendered. Counting the full list made
-- every swatch count roughly 3.5x too high, so eligibility is applied here,
-- at the palette source, rather than anywhere near the color logic.
local function IsRendered(entry)
    return entry.isCollected and entry.isUsable
end

function ns.SetCurrentVisuals(entries)
    currentVisuals = {}
    ns.lastEntryStats = { total = #entries, collected = 0, usable = 0, both = 0 }
    for _, e in ipairs(entries) do
        if e.isCollected then ns.lastEntryStats.collected = ns.lastEntryStats.collected + 1 end
        if e.isUsable then ns.lastEntryStats.usable = ns.lastEntryStats.usable + 1 end
        if e.visualID and IsRendered(e) then
            ns.lastEntryStats.both = ns.lastEntryStats.both + 1
            table.insert(currentVisuals, e.visualID)
        end
    end
    ns.swatchPalettes = {}
end

function ns.GetCurrentVisuals()
    return currentVisuals
end

-- Selections on other slots change which appearances remain eligible, so
-- the counts shown on this slot's swatches go stale when they change.
function ns.InvalidateSwatchPalettes()
    ns.swatchPalettes = {}
end

-- How much of what's on screen we actually have color data for. Surfaced in
-- the picker because a low ratio, not a bad swatch, is the usual reason a
-- pick returns fewer results than expected.
function ns.GetCoverage()
    if not currentVisuals then return 0, 0 end
    local withData = 0
    for _, vid in ipairs(currentVisuals) do
        -- HasColorData, not a table lookup: this runs over every listed
        -- appearance and only needs existence, so it must not force a decode.
        if ns.HasColorData(vid) then withData = withData + 1 end
    end
    return withData, #currentVisuals
end

-- Walks the colors a picker should offer, for every currently-listed
-- appearance that still passes the REST of the filter, so a swatch's count is
-- exactly the number of results clicking it will produce.
--
-- "primary" reads the main colour and ignores the current primary selections
-- when testing eligibility — those OR together, so adding one can only ever
-- widen the result set, and conditioning on them would understate every count.
-- "accent" reads the second colour and ignores the current accent likewise.
--
-- Both come from ns.MainAndAccent, the SAME call MatchesFilter uses. Reading
-- ranks[1]/ranks[2] here instead would make a swatch's count describe a
-- different cluster than the one a click matches on, which is the recurring
-- failure this file keeps warning about.
local function ForEachEligibleColor(kind, fn)
    -- Deliberately NO whole-dataset fallback. There used to be one, so the
    -- picker would never look empty before the Transmogrifier had listed
    -- anything -- but it produced swatch counts drawn from all 63k
    -- appearances (a "brown" helm swatch reported 4000+ results for a slot
    -- holding a few hundred), and clicking one then returned almost nothing.
    -- That is the same class of bug already fixed once: a count must describe
    -- what is on screen, or it is worse than no count. An empty picker is
    -- honest; a lying one is not.
    if not currentVisuals then return end
    for _, vid in ipairs(currentVisuals) do
        local ranks = ns.ItemColors[vid]
        if ranks and ns.MatchesFilterExcept(vid, kind) then
            local main, accent = ns.MainAndAccent(ranks, vid)
            local c = (kind == "accent") and accent or main
            if c then fn(c) end
        end
    end
end

-- Averages a stream of {h,s,v,...} clusters into one representative swatch per
-- bucket, sorted for the grid. `emit` is handed a callback and is expected to
-- call it once per colour.
--
-- Shared by the filter's pickers (which stream the currently listed category)
-- and the randomiser's per-slot pickers (which stream one slot's whole
-- collected set). Both grids must be built and sorted by identical rules --
-- a swatch that looks the same in two places but means a different bucket is
-- the same class of lie as a wrong count.
-- `classify` defaults to the filter's ClassifyColor; the randomiser passes its
-- own grained classifier. Whatever is passed here MUST be the same function the
-- matching code uses, or a swatch's count stops describing what picking it
-- yields -- the exact failure this file's comments keep returning to.
function ns.BuildPaletteFromColors(emit, classify)
    classify = classify or ns.ClassifyColor
    local buckets = {}
    emit(function(entry)
        -- entry[5] is ColorData's achromatic flag. It MUST be forwarded: the
        -- swatch grid and the matching code have to classify identically, and
        -- dropping the flag here would silently file every tinted neutral
        -- under a hue bucket in the picker while matching filed it under a
        -- neutral one -- a swatch whose count describes nothing.
        local h, s, v, achromatic = entry[1], entry[2], entry[3], entry[5]
        local key = classify(h, s, v, achromatic)
        local b = buckets[key]
        if not b then
            b = { sumX = 0, sumY = 0, sumS = 0, sumV = 0, count = 0 }
            buckets[key] = b
        end
        -- Hue is an ANGLE, so it must be averaged as unit vectors, not with a
        -- plain arithmetic mean. The red band wraps through 0 (345°..18°), and
        -- (350 + 10) / 2 = 180 — the red bucket rendered as a cyan-green
        -- swatch that returned red items when clicked. A plain mean happened to
        -- be safe only while buckets were equal slices that never wrapped.
        local rad = math.rad(h)
        b.sumX = b.sumX + math.cos(rad)
        b.sumY = b.sumY + math.sin(rad)
        b.sumS = b.sumS + s
        b.sumV = b.sumV + v
        b.count = b.count + 1
    end)

    local palette = {}
    for key, b in pairs(buckets) do
        local h = math.deg(math.atan2(b.sumY / b.count, b.sumX / b.count)) % 360
        table.insert(palette, {
            key = key,
            h = h,
            s = b.sumS / b.count,
            v = b.sumV / b.count,
            count = b.count, -- how many appearances land in this bucket
        })
    end

    -- Sort by the band's position in HUE_BANDS rather than by the averaged
    -- hue: a wrapping band's mean can land near 355 or near 5, which would
    -- scatter the reds to both ends of the grid. Neutrals sort first.
    table.sort(palette, function(a, b)
        local ao, bo = ns.SwatchSortOrder(a), ns.SwatchSortOrder(b)
        if ao ~= bo then return ao < bo end
        return a.v < b.v
    end)

    return palette
end

function ns.BuildSwatchPalette(kind)
    if ns.swatchPalettes[kind] then return ns.swatchPalettes[kind] end
    -- ns.FilterClassify, not ns.ClassifyColor: the filter has a grain now, and
    -- the palette must be bucketed by the SAME function MatchesFilter uses or a
    -- swatch's count stops describing what clicking it yields.
    local grain = ns.FilterGrain()
    local palette = ns.BuildPaletteFromColors(function(fn)
        ForEachEligibleColor(kind, fn)
    end, ns.FilterClassify)

    -- Draw each swatch as its canonical colour rather than the bucket average,
    -- for the same reason the randomiser does: at broad grain "blue" spans navy
    -- to sky to slate and averages to a murky grey that reads as no colour. Kept
    -- only if it classifies back into its own bucket, so a swatch can never
    -- advertise a colour that would match something else.
    for _, swatch in ipairs(palette) do
        local h, s, v, achromatic = ns.CanonicalSwatch(swatch.key, grain)
        if h and ns.ClassifyColorGrained(h, s, v, grain, achromatic) == swatch.key then
            swatch.h, swatch.s, swatch.v = h, s, v
        end
    end

    ns.swatchPalettes[kind] = palette
    return palette
end

-- The same palette keyed by bucket, for the strip -- which walks every bucket
-- the grain can produce (ns.GrainBuckets) in fixed order and looks each one up,
-- rather than iterating whatever happens to be present.
function ns.SwatchesByKey(kind)
    local cacheKey = kind .. ":byKey"
    if ns.swatchPalettes[cacheKey] then return ns.swatchPalettes[cacheKey] end
    local byKey = {}
    for _, swatch in ipairs(ns.BuildSwatchPalette(kind)) do
        byKey[swatch.key] = swatch
    end
    ns.swatchPalettes[cacheKey] = byKey
    return byKey
end
