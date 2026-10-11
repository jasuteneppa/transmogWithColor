#!/usr/bin/env python3
"""Generates TransmogPalette/ColorData.lua by resolving each known transmog
appearance (visualID) to its ACTUAL armor/weapon texture(s) and extracting
its ranked DOMINANT colors from real pixels — not the 2D icon art.

Icon art was the original approach and is WRONG for a meaningful fraction of
appearances: confirmed in-game that "Rainy Day Coat" (itemID 242338,
visualID 116247) has yellow/gold icon art, but its actual worn texture is
deep red. Blizzard's hand-drawn icons don't reliably track the true garment
color. This addon exists specifically to match what the player visually
picks, so icon-based color is not good enough — hence this rewrite.

Resolution chain (verified working end-to-end, both against a known armor
piece and a known weapon, via direct Python execution, not just research):
  visualID (== ItemAppearance.ID)
    -> ItemAppearance.csv            -> ItemDisplayInfoID
    -> ItemDisplayInfoMaterialRes.csv -> MaterialResourcesID(s)  [armor path]
       (if none: ItemDisplayInfo.csv -> ModelMaterialResourcesID_0/_1)  [weapon path]
    -> TextureFileData.csv (UsageType == 0, diffuse) -> FileDataID(s)
    -> https://wow.zamimg.com/modelviewer/live/textures/{fdid}.webp
       (fallback: https://wago.tools/api/casc/{fdid}, raw BLP2)
    -> opaque pixels pooled across ALL component textures
    -> up to 4 ranked dominant color clusters -> HSV + coverage weight

Why clusters and not an average: a flat mean of R/G/B produces a *blended*
color, not a *dominant* one, and the blend routinely lands in a hue nobody
would name. Confirmed in-game: "Reshii Hood" (visualID 118119) is gray and
purple with bronze trim, but its mean is HSV hue 20 — it showed up under an
orange filter. "Topsy Turvy Clown's Mask" (visualID 109887) reads green but
its mean is a muddy yellow (hue 56) that is neither of its real colors.

Extraction (see dominant_colors), all in CIE L*a*b* rather than HSV because
HSV badly misjudges how colorful a pixel looks:
  - Pixels below an adaptive chroma floor (see _chroma_floor) are treated as
    ACHROMATIC and pooled into three lightness bands (dark/mid/light). The
    floor rises with L*, and rises further in the brown/tan hue band — that
    combination is what stops WoW's endless leather/wood/bronze from claiming
    the "orange" filter without also flattening genuinely muted colors like
    steel blue into gray.
  - Remaining pixels go into a 72-bin circular histogram of L*a*b* hue angle
    weighted by C*, Gaussian-smoothed (sigma 25 deg) so one broad perceptual
    color (e.g. leaf green spanning yellow-green to teal) stays a single peak
    instead of fragmenting across bins and losing to a narrower rival.
  - Peaks are picked greedily with +/-50 deg non-maximum suppression; each
    contributing pixel is assigned to its nearest peak.
  - Clusters (hue peaks AND achromatic bands compete on equal terms) are
    ranked by share of opaque pixels. Achromatic clusters carry an explicit
    ACHROMATIC FLAG plus their true h/s/v.

    They used to be emitted as s=0, which flagged them implicitly but threw
    the tint away. Measured over the 12,063 appearances with an achromatic
    primary, 36.8% of those "neutral" pixels have a real HSV saturation at or
    above the runtime's own 0.15 threshold, and their hues are sharply
    bimodal: ~3,000 in the 0-60 deg warm band (leather/tan blacks) and ~1,100
    in the 180-240 deg cold band (blue steel greys). Flattening both to s=0
    put warm tan-grey and cold blue-grey in one bucket, which is the single
    biggest source of "this item doesn't belong in this colour". The flag
    keeps the perceptual Lab judgement — strictly better than the runtime's
    crude HSV test — while the hue lets the addon split warm from cool.

Output is up to 4 ranked entries per appearance, primary first:
    [visualID] = {{h, s, v, weight, achromatic}, ...}
weight is that cluster's share of the appearance's opaque pixels. Ranks 2
through 4 are each dropped when no genuinely distinct, meaningfully-sized
region exists (min 5% coverage), so a monochrome piece emits a single entry;
the primary is always emitted.

Per-texture pixel data is reduced to a small fixed-size profile (per-hue-bin
and per-band sums) that is *additive*, so pooling an appearance's component
textures is just summing profiles — identical to pooling the raw pixels, but
cacheable across the many appearances that share a texture. Pixels are
quantized to 5 bits per channel first, which keeps the per-pixel Python work
proportional to distinct colors rather than to texture area.

The DB2 CSVs are ~78MB total and are cached locally after the first run
(tools/db2_cache/). Texture images are deduplicated and cached too
(tools/texture_cache/).

Scale, measured rather than assumed (an earlier version of this comment
claimed texture sharing put the fetch count "well under the appearance
count" — that is false): the full universe is every ItemAppearance row,
64,879 of them, of which 63,767 resolve to at least one texture. Those
resolve to 91,483 UNIQUE textures — a dedup ratio of only 1.2x. At ~60KB
each that is ~5.5GB. Scoping to one character's collection is not an option:
the addon ships to everyone, so it needs colours for appearances the machine
generating the data has never seen.

That scale is why this script fetches in parallel and checkpoints:
  - Textures are fetched and profiled in a process pool (--jobs), which also
    parallelises the CPU-bound pixel work that the GIL would otherwise
    serialise. Each worker rate-limits itself (--delay).
  - Every completed texture profile is appended to tools/profile_cache.bin
    immediately, so an interrupted run resumes from where it stopped instead
    of losing hours. Deleting that file forces a clean re-analysis; it does
    NOT force a re-download, since the texture cache is separate.
  - The texture cache is deliberately kept rather than discarded after
    profiling. Any future change to the colour maths — in particular
    weighting pixels by visible geometry, see m2_geometry.py — needs the
    original pixels back, and re-downloading 5.5GB from volunteer-run
    community servers to recover them would be rude and slow.

Both wago.tools and wow.zamimg.com are third-party/community services with
no documented rate limits or terms — this script caches aggressively and
rate-limits itself to avoid hammering them, but there's no guarantee they
stay available or unchanged. Keep --jobs and --delay conservative.

Input: a list of visualIDs, sourced from EITHER:
  1) (Recommended) Your own WoW client. The addon records every appearance
     you browse automatically (Core.lua's RecordVisual) — just open the
     Transmogrifier and browse through gear slots for a while, then
     `/reload` to flush SavedVariables to disk. Then pass --savedvars
     pointing at the file, e.g.:
       WTF/Account/<ACCOUNT>/SavedVariables/TransmogPalette.lua
     Run `/tmpalette` in-game any time to see how many have been recorded.
  2) A plain text file with one visualID per line, via --seed-file.

Usage:
    pip install -r requirements.txt
    python generate_color_data.py --savedvars "path\\to\\TransmogPalette.lua"
    # or
    python generate_color_data.py --seed-file seed_visuals.txt
    # or the full ship-to-everyone set, resumable — just rerun if interrupted:
    python generate_color_data.py --all
"""

import argparse
import colorsys
import concurrent.futures
import csv
import hashlib
import math
import re
import struct
import sys
import time
from pathlib import Path

try:
    import numpy as np
    import requests
    from PIL import Image
except ImportError:
    print("Missing dependencies. Run: pip install -r requirements.txt", file=sys.stderr)
    sys.exit(1)

import m2_geometry

DB2_TABLES = ["ItemAppearance", "ItemDisplayInfo", "ItemDisplayInfoMaterialRes", "TextureFileData"]
DB2_CSV_URL = "https://wago.tools/db2/{table}/csv"
TEXTURE_URLS = [
    ("https://wow.zamimg.com/modelviewer/live/textures/{fdid}.webp", "webp"),
    ("https://wago.tools/api/casc/{fdid}", "blp"),
]
CASC_URL = "https://wago.tools/api/casc/{fdid}"
WEIGHT_GRID_RES = 128

REQUEST_DELAY_SECONDS = 0.1
ALPHA_THRESHOLD = 16  # pixels this transparent or more are skipped (empty texture regions)

HUE_BINS = 72
HUE_BIN_WIDTH = 360.0 / HUE_BINS
HUE_SMOOTH_DEGREES = 25.0

# === One window used to do three different jobs ===
#
# HUE_PEAK_WINDOW was the non-maximum suppression radius, the assignment window
# deciding which bins counted toward a peak's SHARE, and the window whose mean
# RGB became the peak's reported COLOUR. Those want opposite values, so the one
# constant could not be right: every attempt to narrow it fixed the colour and
# broke the share (bins beyond it are orphaned, the piece's coloured total
# falls, and colorFirst files it as greyscale), and every attempt to widen it
# did the reverse. That is why narrowing it "broke as much as it fixed" and the
# knob was written off as exhausted.
#
# Scored against 124 appearances labelled by hand in game with the override
# picker -- the only answer key here that has not lied (see score_overrides.py)
# -- the shipped single window agrees on 5. Split into the three constants
# below it agrees on 20.
#
# HOW THE OLD VALUE FAILED. At a 50-degree window the reported hue is the
# chroma-weighted centroid of a 100-degree-wide swath. WoW's entire warm palette
# (red ~10, brown ~25, gold ~45) fits inside one, and the game's textures are
# dominated by dark red-brown leather and bronze, so a gold item's warm peak is
# dragged down onto that mass. The signature is unmistakable in the override
# scores: EVERY hue disagreement had the classifier reporting a lower hue than
# the truth -- red where you said brown, brown where you said gold, gold where
# you said green, purple where you said pink. A boundary error scatters in both
# directions; this only ever went one way.
HUE_SUPPRESS_DEGREES = 12.0   # how far apart two peaks must be to be separate
HUE_CORE_DEGREES = 6.0        # which bins define a peak's reported COLOUR
# Which bins count toward a peak's SHARE. None means nearest-peak with no cap,
# so every chromatic pixel lands on some cluster. With a cap, bins further than
# it from every peak vanish from the coverage total while still counting in
# `total`, which understates how coloured the piece is and pushes it toward the
# greyscale buckets -- the exact failure MAX_CLUSTERS 3 -> 4 was raised to fix.
HUE_ASSIGN_WINDOW = None
# Kept separate so --peak-window's help text can name the default without
# reading the mutable global, which would clash with main()'s `global` statement.
DEFAULT_HUE_PEAK_WINDOW = HUE_SUPPRESS_DEGREES
# Tuned 2026-08-08 by grid search against 33 in-game ground-truth items, then
# checked against the primary-colour distribution over 295 helms to catch
# overfitting. Scores 28/33; see scratchpad/sweep2.py and truth.py.
#
# The floor deliberately has a LOW base and a STEEP lightness slope. Those pull
# in opposite directions on purpose: dark pixels need a gentle floor or real
# colour collapses to black (dark blue, bronze and brown all did), while pale
# pixels need a firm one or a cream helm gets called orange. A single flat
# threshold cannot do both — an earlier attempt at 5.0/0.14 fixed the darks and
# regressed the pale case.
CHROMA_FLOOR_BASE = 4.0
CHROMA_FLOOR_PER_LIGHTNESS = 0.22
BROWN_HUE_RANGE = (20.0, 100.0)  # L*a*b* hue angles covering red-orange..amber, i.e. brown/tan
# ZERO as of 2026-08-30. This was a per-hue correction bolted onto a general
# algorithm: it raised the chroma floor across 20-100 degrees so WoW's endless
# leather and bronze would stop owning the orange filter. It worked, and it
# caused a worse failure than the one it fixed.
#
# Those are exactly the hue angles GOLD occupies. Mid-chroma gold and tan pixels
# failed the raised floor, were filed as having no hue at all, and never reached
# the histogram -- so a gold item's warm peak had nothing left to land on but
# the dark red-brown that survived, and the piece came out brown. Confirmed by
# eye: rolling the brown bucket returns bright gold shoulders, gold bracers and
# gold boots. Scored against the hand labels, removing it takes brown from 12%
# to 38% agreement.
#
# The general fix for "washed-out orange reads brown" is the lightness-scaled
# floor below, which applies to every hue equally. Special-casing one hue family
# meant every later change had to be reasoned about twice, once inside the
# special case and once outside it.
BROWN_EXTRA_PER_LIGHTNESS = 0.0

# === What a cluster's colour is measured FROM ===
#
# A cluster used to report the chroma-weighted mean RGB over all its pixels,
# lit and shadowed together. WoW bakes shading into the texture rather than
# lighting it at runtime, so that mean is far darker and flatter than the colour
# anyone would name looking at the item: measured over the shipped data, only
# 5.5% of everything the extractor called greyscale reached WHITE_MIN, median
# 0.28, while a white tabard renders on screen at about 0.95. White armour could
# not land in the white bucket no matter where the threshold was put.
#
# So each hue bin and each lightness band now reports the mean of its BRIGHTEST
# pixels -- the lit surface, which is what a person names. The bin's true chroma
# mass and true pixel count are kept unchanged, so peak finding and coverage
# shares are unaffected; only the colour attached to them moves.
#
# 1.0 restores the old behaviour exactly.
LIT_PERCENTILE = 0.40
LIGHTNESS_BANDS = ((0.0, 30.0), (30.0, 65.0), (65.0, 101.0))  # dark / mid / light neutrals
# 4, raised from 3 on 2026-08-30. Three was not just "fewer colours recorded",
# it was actively pushing colourful armour into the greyscale buckets: the
# clusters that did not fit took their AREA with them, colored_total fell under
# Palette.lua's colorFirst threshold, and the appearance came out black or grey.
# Measured over a 1-in-8 sample, greyscale drops 15.5% -> 13.9% purely from
# raising this, with nothing else changed. Only 3.7% of appearances have no
# coloured region at all, so any move toward that number is the right direction.
#
# Confirmed by eye before shipping: of 1,799 appearances that change bucket,
# the movement is overwhelmingly one-way -- gray -> blue/gold/red/brown/green
# /purple, 932 of them -- and a rendered sheet showed pieces like a teal-tusked
# helm and a cyan-spiked shoulder leaving grey for the colour they plainly are.
#
# Costs CLUSTER_BYTES (5) more per appearance: ColorData.lua 4.5 -> 5.1 MB. The
# Lua decoder walks the packed string in 5-byte steps rather than assuming a
# count, so nothing in the addon needed changing.
MAX_CLUSTERS = 4
# See DEFAULT_HUE_PEAK_WINDOW: named separately so --max-clusters' help text can
# read the default without tripping main()'s `global` declaration.
DEFAULT_MAX_CLUSTERS = MAX_CLUSTERS
MIN_CLUSTER_SHARE = 0.05
# How much of an item's colour its attached 3D piece gets when it also has
# body textures (see resolve_attachment). Chosen against in-game screenshots.
ATTACHMENT_SHARE = 0.5

# Achromatic clusters are discounted when RANKING only; the emitted weight
# stays the true pixel share. Ranking by raw area picks the wrong winner
# systematically, because shading and dark underlayers cover more surface than
# the trim that actually identifies a piece — users name the salient colour,
# not the largest one. Confirmed on a helm the user described as "dark blue,
# bronze most prominent" whose bronze held 32% against 41% neutral.
#
# Deliberately NOT tuned to maximise the ground-truth score. Two guards:
#  - An early candidate (floor 3.0/0.06, penalty 0.45) scored 5/5 on the then
#    5-item truth set but drove achromatic primaries to 4.7% across 295 helms,
#    plainly wrong in a game full of black plate and grey steel.
#  - Several 28/33 variants reach that score by failing WORSE: penalty 0.43
#    turns a confirmed-black item pink. A colourful item mislabelled black is a
#    conservative error; a black item mislabelled pink is not. This value keeps
#    every remaining failure on the conservative side, at ~22% achromatic.
ACHROMATIC_RANK_PENALTY = 0.50

# === Shadow is not a colour ===
#
# WoW bakes shading into the texture rather than lighting it at runtime, so one
# painted surface arrives as a RAMP of adjacent hue clusters whose value falls
# as they darken: gold reads h=38 v=0.84 lit, h=30 v=0.54 mid, h=22 v=0.38 in
# shadow. Ranked as three separate colours they compete with each other, and
# shadow always covers the most surface -- so the shadow rung wins and a gold
# piece is filed as brown. Visual 80168 is exactly this, and rolling the brown
# bucket returned gold shoulders because of it.
#
# This is the third time the same failure has appeared. It was fixed INSIDE a
# cluster by LIT_PERCENTILE and BETWEEN colour and tone by colorFirst; this is
# the between-cluster case.
#
# A cluster is absorbed into a brighter one when it is close in hue AND
# materially darker. It keeps contributing its COVERAGE -- the surface is real,
# it is just unlit -- but stops competing as a colour of its own. Absorption is
# asymmetric: only the darker cluster is ever absorbed, which is the whole
# claim. Two different paints at similar brightness (a gold panel beside a
# green one) fail the value test and stay separate.
#
# Rejected alternative: merge on hue alone and report the brightest member.
# That scores nearly as well and is wrong -- yellow has the highest HSV value of
# any hue, so "brightest" silently means "prefer gold". It made gold the largest
# bucket in the game and took green 31% -> 12% and blue 14% -> 0%. The rule
# below leaves red, green and blue agreement completely unchanged and moves only
# gold (8% -> 38%) and brown (42% -> 58%).
#
# Measured over 124 hand-labelled appearances: 22 -> 33. The neighbourhood is
# flat (20/0.70 gives 31, 25/0.80 gives 31), so this is not a knife edge.
#
# NOT in the profile fingerprint: like MAX_CLUSTERS this acts in
# dominant_colors, after profiling, so --offline retunes it in seconds.
SHADOW_RAMP_DEGREES = 25.0
SHADOW_VALUE_RATIO = 0.70

SCRIPT_DIR = Path(__file__).resolve().parent
DB2_CACHE_DIR = SCRIPT_DIR / "db2_cache"
TEXTURE_CACHE_DIR = SCRIPT_DIR / "texture_cache"
MODEL_CACHE_DIR = SCRIPT_DIR / "model_cache"

# A cached profile already has the chroma floor and the hue binning baked into
# it, so changing any of those constants silently invalidates every record.
# Without this fingerprint in the filename, a resumed run would blend profiles
# computed under different colour maths across the same output file — hours of
# quietly wrong data with nothing to indicate it. Changing a tuning constant
# now simply starts a new cache file, and the old one stays reusable if the
# value is changed back.
#
# ACHROMATIC_RANK_PENALTY, MAX_CLUSTERS and MIN_CLUSTER_SHARE are deliberately
# NOT included: they act in dominant_colors(), after profiling, so they can be
# retuned without discarding any cached work.
# HUE_SMOOTH_DEGREES and HUE_PEAK_WINDOW were in here and should not have been.
# Both act inside dominant_colors(), on the ALREADY STORED hue histogram -- they
# change how peaks are picked out of a profile, never the profile itself. Having
# them here made retuning either one orphan the whole cache and force a
# multi-hour refetch to recompute bytes that would have come out identical, so
# in practice they could not be tuned at all.
#
# That mattered: at the old 50-degree window WoW's entire warm palette (red ~10,
# brown ~25, gold ~45) fits inside one suppression radius, so a gold-trimmed
# brown item could only ever yield ONE warm cluster at the mean of both. Items
# came out as a single cluster covering 100% of the piece -- the flat-average
# failure this pipeline exists to avoid -- and the gold was unrecoverable
# downstream because it was never emitted.
#
# When changing this tuple, RENAME the existing cache to the new hash rather
# than letting it be orphaned; nothing in it needs recomputing unless a value
# above genuinely affects profiling.
_PROFILE_FINGERPRINT = hashlib.sha1(repr((
    ALPHA_THRESHOLD, HUE_BINS,
    CHROMA_FLOOR_BASE, CHROMA_FLOOR_PER_LIGHTNESS,
    BROWN_HUE_RANGE, BROWN_EXTRA_PER_LIGHTNESS,
    LIGHTNESS_BANDS, WEIGHT_GRID_RES,
    LIT_PERCENTILE,
)).encode()).hexdigest()[:10]
# Keyed by (texture, model, texture index). The index is part of the key
# because it selects which of the model's dynamic texture slots supplies the
# weighting, and two slots on one model are different surfaces entirely.
PROFILE_CACHE_PATH = SCRIPT_DIR / f"profile_cache_{_PROFILE_FINGERPRINT}.bin"
DEFAULT_OUTPUT = SCRIPT_DIR.parent / "TransmogPalette" / "ColorData.lua"

# Fixed-size records so the cache is append-only and needs no index: an
# interrupted run leaves at most one torn record, which load_profile_cache
# discards. Doubles rather than floats because the accumulators are sums over
# every pixel of a texture and precision here is cheaper than a subtle
# colour-drift bug later.
PROFILE_FLOAT_COUNT = HUE_BINS * 5 + len(LIGHTNESS_BANDS) * 4 + 1
PROFILE_RECORD = struct.Struct("<III%dd" % PROFILE_FLOAT_COUNT)  # texture fdid, model fdid (0 = unweighted), texture index


# Set by --refresh-db2. The DB2 cache is keyed only by table name, so after a
# content patch a rerun would silently reuse the PREVIOUS patch's CSVs and
# produce a ColorData.lua with none of the new appearances in it -- a run that
# looks completely successful and changes nothing. Regenerating for a new patch
# MUST refresh these.
REFRESH_DB2 = False
DB2_STALE_DAYS = 14


def fetch_db2_csv(table: str, session: requests.Session):
    DB2_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = DB2_CACHE_DIR / f"{table}.csv"

    if cache_path.exists() and REFRESH_DB2:
        cache_path.unlink()

    if not cache_path.exists():
        print(f"Downloading {table}.csv...")
        resp = session.get(DB2_CSV_URL.format(table=table), timeout=120)
        resp.raise_for_status()
        cache_path.write_bytes(resp.content)
    else:
        age_days = (time.time() - cache_path.stat().st_mtime) / 86400
        if age_days > DB2_STALE_DAYS:
            print(f"  WARNING: cached {table}.csv is {age_days:.0f} days old. "
                  f"If the game has patched since, rerun with --refresh-db2 or "
                  f"the new appearances will be missing.")

    with open(cache_path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_lookup_tables(session: requests.Session):
    item_appearance = {int(r["ID"]): r for r in fetch_db2_csv("ItemAppearance", session)}
    display_info = {int(r["ID"]): r for r in fetch_db2_csv("ItemDisplayInfo", session)}

    matres_by_display = {}
    for r in fetch_db2_csv("ItemDisplayInfoMaterialRes", session):
        matres_by_display.setdefault(int(r["ItemDisplayInfoID"]), []).append(int(r["MaterialResourcesID"]))

    texture_by_matres = {}
    for r in fetch_db2_csv("TextureFileData", session):
        if r.get("UsageType") == "0":  # diffuse/base color, not normal maps etc.
            texture_by_matres.setdefault(int(r["MaterialResourcesID"]), []).append(int(r["FileDataID"]))

    return item_appearance, display_info, matres_by_display, texture_by_matres


def resolve_texture_fdids(visual_id, item_appearance, display_info, matres_by_display, texture_by_matres):
    app = item_appearance.get(visual_id)
    if not app:
        return []
    display_id = int(app["ItemDisplayInfoID"])

    fdids = []
    for matres_id in matres_by_display.get(display_id, []):
        fdids.extend(texture_by_matres.get(matres_id, []))

    if not fdids:
        di = display_info.get(display_id)
        if di:
            for key in ("ModelMaterialResourcesID_0", "ModelMaterialResourcesID_1"):
                matres_id = di.get(key)
                if matres_id and matres_id != "0":
                    fdids.extend(texture_by_matres.get(int(matres_id), []))

    return list(dict.fromkeys(fdids))  # dedupe, keep order


def resolve_attachment(visual_id, item_appearance, display_info, matres_by_display,
                       texture_by_matres, model_by_display):
    """(texture fdids, model fdid) of the 3D piece attached to a body-texture
    item -- a belt buckle, a scarf or collar on a chest, cuffs on boots and
    gloves -- or ([], 0) when there is none.

    WHY THIS EXISTS. resolve_texture_fdids reads ModelMaterialResourcesID only
    when an item has NO body (component) textures. An item with both is drawn
    as body paint PLUS this model, and the model is often the most visible part:
    a red-and-gold buckle belt came out "brown", the strap behind the buckle
    being the only thing sampled. 9,420 appearances (59% of belts, about a third
    of chests, legs, feet and hands) were in that state.

    The model's own geometry can weight these textures (they use its UV
    layout), unlike the body textures; see resolve_model_fdid."""
    app = item_appearance.get(visual_id)
    if not app:
        return [], 0
    display_id = int(app["ItemDisplayInfoID"])
    di = display_info.get(display_id)
    if display_id not in matres_by_display or not di:
        return [], 0
    fdids = []
    for key in ("ModelMaterialResourcesID_0", "ModelMaterialResourcesID_1"):
        matres_id = di.get(key)
        if matres_id and matres_id != "0":
            fdids.extend(texture_by_matres.get(int(matres_id), []))
    fdids = list(dict.fromkeys(fdids))
    if not fdids:
        return [], 0
    model_fdid = 0
    model_res = di.get("ModelResourcesID_0", "0")
    if model_by_display and model_res not in ("", "0"):
        models = model_by_display.get(int(model_res), [])
        model_fdid = models[0] if models else 0
    return fdids, model_fdid


def scale_profile(profile, factor):
    """Every count in a profile times `factor`. dominant_colors works on shares,
    so this changes how much a profile counts against another, nothing else."""
    for slot in profile["hue"]:
        for i in range(5):
            slot[i] *= factor
    for band in profile["bands"]:
        for i in range(4):
            band[i] *= factor
    profile["total"] *= factor
    return profile


def load_model_files():
    """ModelResourcesID -> model FileDataID, from the locally cached CSV."""
    path = DB2_CACHE_DIR / "ModelFileData.csv"
    if not path.exists():
        print("ModelFileData.csv not cached — geometry weighting disabled.", file=sys.stderr)
        return {}
    out = {}
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = row.get("ModelResourcesID")
            if key:
                out.setdefault(int(key), []).append(int(row["FileDataID"]))
    return out


def resolve_model_fdid(visual_id, item_appearance, display_info, matres_by_display, model_by_display):
    """The model whose visible geometry should weight this appearance's texture,
    or 0 when weighting must not be applied.

    The guard on the component path is the important part. resolve_texture_fdids
    prefers ItemDisplayInfoMaterialRes, so when an item has BOTH a component
    texture and a model, the texture sampled is the character body's — and its
    UV layout belongs to the body mesh, not to this item's M2. Weighting it with
    the model's UV map would sample an unrelated atlas and yield confident
    nonsense. Measured: 9,236 appearances are in exactly that state.
    """
    if not model_by_display:
        return 0
    app = item_appearance.get(visual_id)
    if not app:
        return 0
    display_id = int(app["ItemDisplayInfoID"])
    if display_id in matres_by_display:
        return 0  # component path — see above
    di = display_info.get(display_id)
    if not di:
        return 0
    model_res = di.get("ModelResourcesID_0", "0")
    if model_res in ("", "0"):
        return 0
    fdids = model_by_display.get(int(model_res), [])
    return fdids[0] if fdids else 0


def resolve_baked_texture_fdids(model_fdid: int, session, delay=0.0):
    """Textures baked into the model's own TXID chunk, for appearances that have
    no MaterialRes entry at all.

    WHY THIS EXISTS. 1,063 of the 1,129 appearances with no colour data reach
    neither texture path: ItemDisplayInfoMaterialRes has no row, and
    ItemDisplayInfo.ModelMaterialResourcesID_0/_1 are zero. They plainly render
    in game, so the texture is somewhere -- it is inside the M2.

    m2_geometry's TXID note explains why it was skipped: a ZERO entry means a
    slot the game binds at runtime, which for armour is the item texture, so a
    NON-zero entry is baked-in model decoration. That is right for armour and
    backwards for weapons. A sword has no character slot to bind to, so its own
    baked texture IS its texture, and treating it as decoration discarded the
    only copy. Measured on 40 such appearances whose model was already cached,
    38 carry a non-zero TXID and only 2 are genuinely runtime-bound.

    The gap is almost entirely weapons and model-based armour (cloaks, helms,
    shoulders) and reaches back to Classic -- Stormwind Guard Shield, Teebu's
    Blazing Longsword, Wirt's Last Leg. Only ONE of the 1,129 was newer than the
    generated data, so this was never a content-patch problem.
    """
    try:
        model = m2_geometry.M2Model(fetch_casc_file(model_fdid, session, delay))
    except Exception:  # noqa: BLE001 - an unparseable model is just a miss
        return []
    return [fd for fd in model.texture_fdids if fd]


def parse_savedvariables_visuals(path: Path):
    """Extracts visualIDs (keys of exportedVisuals) from the SavedVariables
    file Core.lua's RecordVisual() writes automatically as you browse."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r'\["exportedVisuals"\]\s*=\s*\{(.*?)\n\}', text, re.DOTALL)
    if not match:
        raise ValueError(
            'Could not find an "exportedVisuals" table in that file. '
            "Browse some appearances in-game and /reload first."
        )
    body = match.group(1)
    return sorted(set(int(m) for m in re.findall(r"\[(\d+)\]\s*=", body)))


def parse_seed_file(path: Path):
    # utf-8-sig, not utf-8: a BOM makes the first line fail isdigit(), so a seed
    # file written by almost any Windows tool would silently lose one entry.
    ids = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip().split("#", 1)[0].strip()
        if line.isdigit():
            ids.append(int(line))
    return sorted(set(ids))


def fetch_texture(fdid: int, session: requests.Session, delay=0.0) -> Image.Image:
    """Returns the texture image, from disk when already cached.

    `delay` is applied only after a request that actually went out — sleeping
    on cache hits would add hours to a resumed run for no politeness benefit.
    """
    TEXTURE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for url_template, ext in TEXTURE_URLS:
        cache_path = TEXTURE_CACHE_DIR / f"{fdid}.{ext}"
        if cache_path.exists():
            return Image.open(cache_path)
    for url_template, ext in TEXTURE_URLS:
        cache_path = TEXTURE_CACHE_DIR / f"{fdid}.{ext}"
        resp = session.get(url_template.format(fdid=fdid), timeout=20)
        ok = resp.status_code == 200 and len(resp.content) > 100
        if delay:
            time.sleep(delay)
        if ok:
            # Write via a temp file and rename: a run killed mid-write would
            # otherwise leave a truncated image that every later run treats as
            # a valid cache hit.
            tmp = cache_path.with_suffix(cache_path.suffix + ".part")
            tmp.write_bytes(resp.content)
            tmp.replace(cache_path)
            return Image.open(cache_path)
    raise ValueError(f"no texture image found for FileDataID {fdid}")


def fetch_casc_file(fdid: int, session: requests.Session, delay=0.0) -> bytes:
    """Downloads a raw CASC file (used for .m2 models and .skin geometry)."""
    MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = MODEL_CACHE_DIR / f"{fdid}.bin"
    if cache_path.exists():
        return cache_path.read_bytes()
    resp = session.get(CASC_URL.format(fdid=fdid), timeout=60)
    if delay:
        time.sleep(delay)
    if resp.status_code != 200 or len(resp.content) < 8:
        raise ValueError(f"no CASC file for FileDataID {fdid} (HTTP {resp.status_code})")
    tmp = cache_path.with_suffix(".part")
    tmp.write_bytes(resp.content)
    tmp.replace(cache_path)
    return resp.content


def build_weight_grid(model_fdid: int, tex_index: int, session: requests.Session, delay=0.0):
    """Visible-geometry UV weight grid for the texture at `tex_index`, or None.

    A model can carry several dynamic texture slots, each its own texture with
    its own UV layout. The object texture path reads ModelMaterialResourcesID_0
    then _1, so the Nth resolved texture belongs to the Nth drawn dynamic slot;
    only the submeshes wearing that slot may contribute weight to it.

    Returns None whenever that pairing can't be made, or anything else is
    unexpected -- an unparseable model, a missing .skin, no visible area. The
    caller then falls back to unweighted analysis, which is a far smaller error
    than weighting a texture with the wrong surface's geometry."""
    try:
        model = m2_geometry.M2Model(fetch_casc_file(model_fdid, session, delay))
        if not model.skin_fdids:
            return None
        skin = m2_geometry.M2Skin(fetch_casc_file(model.skin_fdids[0], session, delay))
        slots = m2_geometry.dynamic_slot_order(model, skin)
        if tex_index >= len(slots):
            return None  # no slot to pair this texture with
        grid, _ = m2_geometry.build_uv_weight_map(
            model, skin, resolution=WEIGHT_GRID_RES, slot=slots[tex_index]
        )
    except Exception:  # noqa: BLE001 - see docstring
        return None
    if grid is None:
        return None
    arr = np.asarray(grid, dtype=np.float64)
    return arr if arr.sum() > 0 else None


_LINEAR = [(c / 255.0 / 12.92) if c <= 10 else (((c / 255.0 + 0.055) / 1.055) ** 2.4) for c in range(256)]
# 5-bit-per-channel quantization + a binary alpha, so Image.point collapses a
# texture to at most a few thousand distinct colors before any Python runs.
_QUANT_LUT = (
    [(c >> 3) * 8 + 4 for c in range(256)] * 3
    + [0 if c <= ALPHA_THRESHOLD else 255 for c in range(256)]
)


def _rgb_to_lab(r, g, b):
    lr, lg, lb = _LINEAR[r], _LINEAR[g], _LINEAR[b]
    x = (0.4124 * lr + 0.3576 * lg + 0.1805 * lb) / 0.95047
    y = 0.2126 * lr + 0.7152 * lg + 0.0722 * lb
    z = (0.0193 * lr + 0.1192 * lg + 0.9505 * lb) / 1.08883
    fx, fy, fz = (t ** (1 / 3) if t > 0.008856 else t * 7.787 + 16 / 116 for t in (x, y, z))
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def _chroma_floor(lightness, hue):
    """How colorful a pixel must be to count as having a hue at all.

    Scales with lightness because C* shrinks as pixels darken: a flat floor
    misfiles shadowed-but-colored pixels as neutral while promoting pale muted
    tans to vivid orange. Brown/tan gets an extra penalty because it is the one
    hue family whose desaturated form takes a *different* color name — a washed
    out purple still reads "purple", but washed out orange reads "brown", and
    WoW's endless leather/wood/bronze would otherwise own the orange filter."""
    per_lightness = CHROMA_FLOOR_PER_LIGHTNESS
    if BROWN_HUE_RANGE[0] <= hue <= BROWN_HUE_RANGE[1]:
        per_lightness += BROWN_EXTRA_PER_LIGHTNESS
    return CHROMA_FLOOR_BASE + per_lightness * lightness


def new_profile():
    return {
        # per hue bin: chroma-weighted r/g/b sums, chroma sum, pixel count
        "hue": [[0.0, 0.0, 0.0, 0.0, 0] for _ in range(HUE_BINS)],
        # per lightness band: r/g/b sums, pixel count
        "bands": [[0.0, 0.0, 0.0, 0] for _ in LIGHTNESS_BANDS],
        "total": 0,
    }


def add_profiles(into, other):
    for dst, src in zip(into["hue"], other["hue"]):
        for i in range(5):
            dst[i] += src[i]
    for dst, src in zip(into["bands"], other["bands"]):
        for i in range(4):
            dst[i] += src[i]
    into["total"] += other["total"]
    return into


def texture_profile(img: Image.Image):
    """Reduces one texture to the additive summary dominant_colors() consumes.

    Returns (profile, used_opaque_fallback). profile is None only when the
    texture is genuinely blank: alpha is zero everywhere AND there's no real
    colour variation once alpha is ignored. Some textures -- glow/illusion-
    style effects whose engine blend mode ignores alpha entirely -- have real
    painted detail but zero alpha everywhere; those are salvaged by treating
    every pixel as opaque instead of being silently discarded. A texture
    that's actually blank (flat single colour once alpha drops out) is left
    as None rather than risk tagging it with a fabricated colour."""
    img = img.convert("RGBA").point(_QUANT_LUT)
    colors = img.getcolors(1 << 20) or []
    profile = _accumulate(colors)
    if profile is not None:
        return profile, False
    if len({(r, g, b) for _, (r, g, b, _a) in colors}) <= 1:
        return None, False
    opaque_colors = [(count, (r, g, b, 255)) for count, (r, g, b, _a) in colors]
    return _accumulate(opaque_colors), True


def weighted_texture_profile(img: Image.Image, grid):
    """Same reduction, but each pixel counts for the amount of VISIBLE, outward
    facing 3D surface that maps to it, instead of counting 1.

    This is what stops a hood's black lining outranking its gold shell: the
    lining's pixels are really in the texture, they just aren't really on
    screen. Returns None when no visible geometry maps onto this texture at
    all, which tells the caller to fall back to the unweighted profile.

    Works at full texture resolution -- the grid is sampled per pixel rather
    than the image being downscaled to the grid -- so weighted and unweighted
    appearances stay statistically comparable.
    """
    img = img.convert("RGBA").point(_QUANT_LUT)
    arr = np.asarray(img)
    height, width = arr.shape[0], arr.shape[1]
    res = grid.shape[0]

    ys = np.minimum((np.arange(height) * res) // height, res - 1)
    xs = np.minimum((np.arange(width) * res) // width, res - 1)
    weights = grid[ys[:, None], xs[None, :]]

    opaque = arr[:, :, 3] > 0
    weights = np.where(opaque, weights, 0.0)
    if weights.sum() <= 0:
        return None

    # Group by distinct quantized colour, summing weights -- the same shape of
    # input texture_profile gets from getcolors(), so the accumulation below is
    # shared and the two paths cannot drift apart.
    packed = (arr[:, :, 0].astype(np.uint32) << 16
              | arr[:, :, 1].astype(np.uint32) << 8
              | arr[:, :, 2].astype(np.uint32))
    flat_packed = packed.ravel()
    flat_weights = weights.ravel()
    keep = flat_weights > 0
    if not keep.any():
        return None
    uniq, inverse = np.unique(flat_packed[keep], return_inverse=True)
    summed = np.bincount(inverse, weights=flat_weights[keep])

    colors = [
        (float(w), (int(c >> 16 & 0xFF), int(c >> 8 & 0xFF), int(c & 0xFF), 255))
        for c, w in zip(uniq.tolist(), summed.tolist())
    ]
    return _accumulate(colors)


def _lit_mean(entries, chroma_weighted):
    """Mean RGB over the brightest LIT_PERCENTILE of `entries` by pixel count.

    `entries` are (lightness, r, g, b, chroma, count). Returns (r, g, b) means,
    or None. See LIT_PERCENTILE: this is the whole point of the statistic --
    naming a colour from the lit surface rather than from an average that
    includes the item's own baked-in shadow.
    """
    if not entries:
        return None
    want = sum(e[5] for e in entries) * LIT_PERCENTILE
    r_sum = g_sum = b_sum = w_sum = 0.0
    taken = 0.0
    # Brightest first, so the cut keeps the lit surface and drops the shadow.
    for lightness, r, g, b, chroma, count in sorted(entries, key=lambda e: -e[0]):
        w = count * chroma if chroma_weighted else count
        r_sum += r * w
        g_sum += g * w
        b_sum += b * w
        w_sum += w
        taken += count
        if taken >= want:
            break
    if w_sum <= 0:
        return None
    return r_sum / w_sum, g_sum / w_sum, b_sum / w_sum


def _accumulate(colors):
    """Folds (count, RGBA) pairs into a profile. `count` may be a float weight.

    Two passes: the first bins every pixel, the second reduces each bin to the
    colour of its lit surface. The profile SHAPE is unchanged -- same hue bins,
    same lightness bands, same packing -- so nothing downstream or in the addon
    needed touching. Only the RGB stored per bin moves; each bin's chroma mass
    and pixel count stay exactly what they always were, which is what peak
    finding and the coverage shares read.
    """
    hue_entries = [[] for _ in range(HUE_BINS)]
    band_entries = [[] for _ in LIGHTNESS_BANDS]
    total = 0.0

    for count, (r, g, b, a) in colors:
        if a == 0:
            continue
        lightness, a_star, b_star = _rgb_to_lab(r, g, b)
        chroma = math.hypot(a_star, b_star)
        hue = math.degrees(math.atan2(b_star, a_star)) % 360.0
        total += count
        entry = (lightness, r, g, b, chroma, count)
        if chroma < _chroma_floor(lightness, hue):
            for (low, high), bucket in zip(LIGHTNESS_BANDS, band_entries):
                if low <= lightness < high:
                    bucket.append(entry)
                    break
        else:
            hue_entries[int(hue // HUE_BIN_WIDTH) % HUE_BINS].append(entry)

    if not total:
        return None

    profile = new_profile()
    profile["total"] = total
    for entries, slot in zip(hue_entries, profile["hue"]):
        if not entries:
            continue
        mean = _lit_mean(entries, chroma_weighted=True)
        if mean is None:
            continue
        weight = sum(e[4] * e[5] for e in entries)   # true chroma mass
        slot[0] = mean[0] * weight
        slot[1] = mean[1] * weight
        slot[2] = mean[2] * weight
        slot[3] = weight
        slot[4] = sum(e[5] for e in entries)         # true pixel count
    for entries, band in zip(band_entries, profile["bands"]):
        if not entries:
            continue
        mean = _lit_mean(entries, chroma_weighted=False)
        if mean is None:
            continue
        count = sum(e[5] for e in entries)
        band[0] = mean[0] * count
        band[1] = mean[1] * count
        band[2] = mean[2] * count
        band[3] = count
    return profile


def _smoothed_hue_mass(profile):
    mass = [slot[3] for slot in profile["hue"]]
    radius = int(HUE_SMOOTH_DEGREES / HUE_BIN_WIDTH)
    kernel = [math.exp(-0.5 * (i * HUE_BIN_WIDTH / HUE_SMOOTH_DEGREES) ** 2) for i in range(-radius, radius + 1)]
    return [
        sum(mass[(i + j) % HUE_BINS] * kernel[j + radius] for j in range(-radius, radius + 1))
        for i in range(HUE_BINS)
    ]


def _hue_gap(a, b):
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def _absorb_shadows(clusters):
    """Folds each shadow rung of a shading ramp into the lit cluster it belongs
    to. See SHADOW_RAMP_DEGREES.

    `clusters` are (h, s, v, share, rank_score, achromatic). Only chromatic
    clusters take part -- the greyscale bands are a separate axis, already
    pooled by lightness, and a dark neutral is not the shadow of a bright one in
    the same sense.
    """
    if SHADOW_RAMP_DEGREES <= 0:
        return clusters
    chroma = [c for c in clusters if not c[5]]
    if len(chroma) < 2:
        return clusters
    neutral = [c for c in clusters if c[5]]

    # Brightest first, so a cluster is only ever absorbed into a brighter one
    # and the lit end of a ramp always survives.
    order = sorted(range(len(chroma)), key=lambda i: -chroma[i][2])
    parent = {}

    def root_of(i):
        while i in parent:
            i = parent[i]
        return i

    for pos, i in enumerate(order):
        for j in order[:pos]:
            r = root_of(j)
            if (_hue_gap(chroma[i][0], chroma[r][0]) <= SHADOW_RAMP_DEGREES
                    and chroma[i][2] <= SHADOW_VALUE_RATIO * chroma[r][2]):
                parent[i] = r
                break

    gained = {}
    for i in parent:
        r = root_of(i)
        gained[r] = gained.get(r, 0.0) + chroma[i][3]

    out = list(neutral)
    for i, c in enumerate(chroma):
        if i in parent:
            continue
        share = c[3] + gained.get(i, 0.0)
        # rank_score tracks share for chromatic clusters (only the achromatic
        # ones carry a penalty), so it moves with the absorbed coverage.
        out.append((c[0], c[1], c[2], share, share, c[5]))
    return out


def dominant_colors(profile):
    """Returns up to MAX_CLUSTERS (h 0-360, s, v, weight, achromatic) tuples,
    most dominant first. weight is the cluster's share of opaque pixels;
    achromatic is 1 for the lightness-band clusters, 0 for hue peaks."""
    total = profile["total"]
    if not total:
        return []

    # Each cluster carries (h, s, v, true share, ranking score, achromatic).
    # share and ranking score differ only for achromatic clusters — see
    # ACHROMATIC_RANK_PENALTY.
    clusters = []
    for band in profile["bands"]:
        if band[3]:
            # The TRUE tint is kept and the achromatic verdict is carried in
            # the flag instead of being encoded as s=0. These pixels failed the
            # perceptual Lab chroma test, so the addon must not treat the hue
            # as a colour name — but "warm near-black" and "cold near-black"
            # are different buckets to a player, and that distinction only
            # survives if h and s are actually stored.
            h, s, v = colorsys.rgb_to_hsv(
                band[0] / band[3] / 255.0,
                band[1] / band[3] / 255.0,
                band[2] / band[3] / 255.0,
            )
            share = band[3] / total
            clusters.append((h * 360.0, s, v, share, share * ACHROMATIC_RANK_PENALTY, 1))

    smoothed = _smoothed_hue_mass(profile)
    peaks = []
    for _ in range(MAX_CLUSTERS):
        best = max(range(HUE_BINS), key=lambda i: smoothed[i])
        if smoothed[best] <= 0:
            break
        center = (best + 0.5) * HUE_BIN_WIDTH
        peaks.append(center)
        for i in range(HUE_BINS):
            gap = abs((i + 0.5) * HUE_BIN_WIDTH - center)
            if min(gap, 360.0 - gap) <= HUE_SUPPRESS_DEGREES:
                smoothed[i] = 0.0

    # Two accumulators per peak, because the two questions have different
    # answers: the CORE says what colour this is, the whole assignment says how
    # much of the piece it covers. See HUE_SUPPRESS_DEGREES above.
    core = [[0.0, 0.0, 0.0, 0.0] for _ in peaks]  # chroma-weighted r/g/b + weight
    share_count = [0 for _ in peaks]
    cap = HUE_ASSIGN_WINDOW if HUE_ASSIGN_WINDOW is not None else 360.0
    for i, slot in enumerate(profile["hue"]):
        if not slot[4]:
            continue
        hue = (i + 0.5) * HUE_BIN_WIDTH
        nearest, best_gap = -1, cap
        for p, center in enumerate(peaks):
            gap = abs(hue - center)
            gap = min(gap, 360.0 - gap)
            if gap <= best_gap:
                nearest, best_gap = p, gap
        if nearest < 0:
            continue
        share_count[nearest] += slot[4]
        if best_gap <= HUE_CORE_DEGREES:
            for j in range(4):
                core[nearest][j] += slot[j]

    for p in range(len(peaks)):
        count = share_count[p]
        r_sum, g_sum, b_sum, weight = core[p]
        # A peak found on the SMOOTHED mass can have an empty core: smoothing
        # spreads mass into bins that hold no real pixels. Emitting a colour for
        # it would be inventing one, so it is dropped and its share goes unused.
        if not count or weight <= 0:
            continue
        h, s, v = colorsys.rgb_to_hsv(r_sum / weight / 255.0, g_sum / weight / 255.0, b_sum / weight / 255.0)
        share = count / total
        clusters.append((h * 360.0, s, v, share, share, 0))

    # Before ranking, and before MIN_CLUSTER_SHARE can drop anything: a shadow
    # rung's coverage has to reach the surface it belongs to, not be discarded.
    clusters = _absorb_shadows(clusters)

    clusters.sort(key=lambda c: -c[4])
    ranked = [c for c in clusters if c[3] >= MIN_CLUSTER_SHARE][:MAX_CLUSTERS]
    ranked = ranked or clusters[:1]  # a primary is always emitted
    return [(h, s, v, share, achro) for h, s, v, share, _, achro in ranked]


def pack_profile(profile):
    flat = []
    for slot in profile["hue"]:
        flat.extend(slot)
    for band in profile["bands"]:
        flat.extend(band)
    flat.append(profile["total"])
    return flat


def unpack_profile(flat):
    profile = new_profile()
    i = 0
    for slot in profile["hue"]:
        for j in range(5):
            slot[j] = flat[i]
            i += 1
    for band in profile["bands"]:
        for j in range(4):
            band[j] = flat[i]
            i += 1
    profile["total"] = flat[i]
    return profile


def trim_profile_cache():
    """Drops a trailing partial record left by a run killed mid-write.

    This has to physically truncate the file, not just skip the tail on read:
    appending after a torn record would push every subsequent record off the
    fixed-size grid, so they would all decode as garbage on the next resume —
    losing exactly the work this cache exists to protect."""
    if not PROFILE_CACHE_PATH.exists():
        return
    size = PROFILE_CACHE_PATH.stat().st_size
    extra = size % PROFILE_RECORD.size
    if extra:
        with open(PROFILE_CACHE_PATH, "r+b") as f:
            f.truncate(size - extra)
        print(f"Discarded a torn {extra}-byte record at the end of the profile cache.")


def load_profile_cache():
    """Reads the append-only profile cache."""
    trim_profile_cache()
    if not PROFILE_CACHE_PATH.exists():
        return {}
    data = PROFILE_CACHE_PATH.read_bytes()
    out = {}
    for off in range(0, len(data) - PROFILE_RECORD.size + 1, PROFILE_RECORD.size):
        fields = PROFILE_RECORD.unpack_from(data, off)
        out[(fields[0], fields[1], fields[2])] = unpack_profile(list(fields[3:]))
    return out


def append_profiles(handle, batch):
    for (tex_fdid, model_fdid, tex_index), profile in batch:
        handle.write(
            PROFILE_RECORD.pack(tex_fdid, model_fdid, tex_index, *pack_profile(profile))
        )
    handle.flush()


# One session per worker process. Created in the initializer so connections are
# pooled across the thousands of fetches each worker handles.
_worker_session = None
_worker_delay = 0.0
_worker_grids = {}  # model fdid -> weight grid, memoized per process

# Sentinel returned in place of an error message when texture_profile() used
# the zero-alpha opaque fallback -- lets build_profiles() report which
# appearances it affected without treating the fetch as having failed.
_OPAQUE_FALLBACK = "opaque-fallback"


def _init_worker(delay):
    global _worker_session, _worker_delay
    _worker_session = requests.Session()
    _worker_session.headers["User-Agent"] = (
        "TransmogPalette-ColorDataGenerator/0.5 (WoW addon dev tool)"
    )
    _worker_delay = delay


def _fetch_and_profile(job):
    """Runs in a worker process: fetch, decode and reduce one texture.

    The pixel reduction is deliberately done here rather than in the parent —
    it is pure-Python and CPU-bound, so leaving it in the parent would make the
    GIL, not the network, the ceiling on a 91k-texture run.

    `job` is (texture fdid, model fdid); model fdid 0 means analyse the texture
    unweighted. Chunksize batching tends to group a model's textures together,
    so the memoized grid is usually still warm."""
    tex_fdid, model_fdid, tex_index = job
    try:
        img = fetch_texture(tex_fdid, _worker_session, _worker_delay)
    except Exception as e:  # noqa: BLE001 - one bad texture must not kill the run
        return job, None, f"{type(e).__name__}: {e}"

    if model_fdid:
        key = (model_fdid, tex_index)
        if key not in _worker_grids:
            _worker_grids[key] = build_weight_grid(
                model_fdid, tex_index, _worker_session, _worker_delay
            )
        grid = _worker_grids[key]
        if grid is not None:
            try:
                profile = weighted_texture_profile(img, grid)
            except Exception:  # noqa: BLE001 - fall back rather than lose the item
                profile = None
            if profile is not None:
                return job, profile, None

    try:
        profile, used_opaque_fallback = texture_profile(img)
        return job, profile, (_OPAQUE_FALLBACK if used_opaque_fallback else None)
    except Exception as e:  # noqa: BLE001
        return job, None, f"{type(e).__name__}: {e}"


def build_profiles(job_list, jobs, delay, checkpoint_every=200, offline=False):
    """Fetches and profiles every needed (texture, model) pair, resuming from
    and extending the on-disk profile cache."""
    profiles = load_profile_cache()
    if profiles:
        print(f"Resuming: {len(profiles)} texture profiles already cached.")

    todo = [j for j in job_list if j not in profiles]
    if not todo:
        print("All textures already profiled.")
        return profiles, []

    if offline:
        # Retuning anything downstream of profiling (cluster ranking, the
        # emitted fields, the pack format) needs no new pixels at all, so an
        # experiment should not be able to start a multi-hour download by
        # accident — or hit the community servers again for data already here.
        print(
            f"Offline: {len(todo)} texture/model pairs are not in the profile "
            f"cache and will be SKIPPED. Appearances that depend only on those "
            f"will be missing from the output."
        )
        return profiles, []

    print(f"Profiling {len(todo)} textures with {jobs} workers ({delay}s delay each)...")
    failed = 0
    opaque_fallback_jobs = []
    started = time.time()
    pending = []

    with open(PROFILE_CACHE_PATH, "ab") as cache_handle:
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=jobs, initializer=_init_worker, initargs=(delay,)
        ) as pool:
            for done, (job, profile, error) in enumerate(
                pool.map(_fetch_and_profile, todo, chunksize=8), 1
            ):
                if profile is None:
                    failed += 1
                    # Not cached: a failure here is usually a transient fetch
                    # error, and caching it would make it permanent.
                    profiles[job] = None
                else:
                    profiles[job] = profile
                    pending.append((job, profile))
                    if error == _OPAQUE_FALLBACK:
                        opaque_fallback_jobs.append(job)

                if len(pending) >= checkpoint_every:
                    append_profiles(cache_handle, pending)
                    pending = []

                if done % 500 == 0 or done == len(todo):
                    rate = done / max(time.time() - started, 1e-6)
                    remaining = (len(todo) - done) / rate if rate else 0
                    print(
                        f"  {done}/{len(todo)} textures  "
                        f"{rate:.1f}/s  {failed} failed  "
                        f"~{remaining / 60:.0f} min left"
                    )
            append_profiles(cache_handle, pending)

    return profiles, opaque_fallback_jobs


CLUSTER_BYTES = 5
FLAG_ACHROMATIC = 1


def _pack_colors(clusters):
    """Encodes an appearance's ranked colours as CLUSTER_BYTES bytes each.

    h is quantized to 1.5 degrees (240 steps) so it still fits one byte while
    staying far finer than Palette.lua's 30-degree classification buckets; s, v
    and weight get a full byte each. The fifth byte is flags, currently just
    FLAG_ACHROMATIC. Emitted as three-digit decimal escapes, which are
    unambiguous in Lua source (\\01 would otherwise be read as a two-digit
    escape) and safe for any byte value.

    The flag needs its own byte rather than stealing spare hue codes (h only
    uses 0-240): a player-visible bucket boundary should not depend on a
    packing trick that the next person to widen the hue resolution would
    silently break. The cost is ~64k extra bytes per rank, about 2 MB of addon
    memory against the 8 MB this format already uses."""
    out = []
    for h, s, v, w, achro in clusters:
        for value in (
            min(240, max(0, round((h % 360.0) / 1.5))),
            min(255, max(0, round(s * 255))),
            min(255, max(0, round(v * 255))),
            min(255, max(0, round(w * 255))),
            FLAG_ACHROMATIC if achro else 0,
        ):
            out.append(f"\\{value:03d}")
    return "".join(out)


def write_lua_output(visual_colors: dict, output_path: Path):
    lines = [
        "local ADDON, ns = ...",
        "",
        "-- GENERATED FILE - do not hand-edit. Regenerate with tools/generate_color_data.py.",
        "--",
        "-- Maps visualID (an appearance's C_TransmogCollection identity) to its",
        "-- ranked dominant REAL TEXTURE colors (not icon art), primary first.",
        "-- There are 1 to 3 entries per appearance - secondary and tertiary exist",
        "-- only when the texture really has a distinct region that size.",
        "--",
        "-- Achromatic clusters (black/gray/white) carry achromatic = 1 as their",
        "-- 5th field, and keep their TRUE hue and saturation. Do not read the",
        "-- flag off s == 0; it no longer is. The flag is the perceptual CIE Lab",
        "-- verdict from the generator and should beat any HSV test done here,",
        "-- but h and s still matter: they separate warm near-black leather from",
        "-- cold near-black plate, which players do not consider the same colour.",
        "--",
        "-- STORAGE: colours are packed 5 bytes per cluster (hue/1.5, s*255,",
        "-- v*255, weight*255, flags) into one string per appearance, and decoded",
        "-- lazily on first access. Storing them as nested Lua tables instead cost",
        "-- 71 MB of addon memory at ~64k appearances: that is roughly 237,000",
        "-- tables, almost all of which are never looked at in a session. Access",
        "-- is unchanged - ns.ItemColors[visualID][rank] yields",
        "-- {h, s, v, weight, achromatic}.",
        "--",
        "-- Use ns.HasColorData(visualID) for existence checks (no decode), and",
        "-- ns.ForEachItemColor(rank, fn) to walk the whole dataset: pairs() on",
        "-- ns.ItemColors only sees appearances already decoded.",
        "",
        "local packed = {",
    ]
    for visual_id in sorted(visual_colors):
        lines.append(f'    [{visual_id}] = "{_pack_colors(visual_colors[visual_id])}",')
    lines.extend([
        "}",
        "",
        "local function decode(s)",
        "    local out = {}",
        f"    for i = 1, #s, {CLUSTER_BYTES} do",
        f"        local h, sat, val, w, flags = s:byte(i, i + {CLUSTER_BYTES - 1})",
        "        out[#out + 1] = { h * 1.5, sat / 255, val / 255, w / 255,"
        + " flags %% %d >= %d }" % (FLAG_ACHROMATIC * 2, FLAG_ACHROMATIC),
        "    end",
        "    return out",
        "end",
        "",
        "ns.ItemColors = setmetatable({}, {",
        "    __index = function(t, visualID)",
        "        local s = packed[visualID]",
        "        if not s then return nil end",
        "        local decoded = decode(s)",
        "        rawset(t, visualID, decoded)",
        "        return decoded",
        "    end,",
        "})",
        "",
        "function ns.HasColorData(visualID)",
        "    return packed[visualID] ~= nil",
        "end",
        "",
        "-- Walks every appearance that has a cluster at `rank`, passing the",
        "-- decoded {h,s,v,weight} to fn. Does not populate the decode cache:",
        "-- a full sweep would otherwise materialise every table this format",
        "-- exists to avoid.",
        "function ns.ForEachItemColor(rank, fn)",
        "    for visualID, s in pairs(packed) do",
        "        local offset = (rank - 1) * %d" % CLUSTER_BYTES,
        "        if #s >= offset + %d then" % CLUSTER_BYTES,
        "            local h, sat, val, w, flags = s:byte(offset + 1, offset + %d)"
        % CLUSTER_BYTES,
        "            fn(visualID, { h * 1.5, sat / 255, val / 255, w / 255,"
        + " flags %% %d >= %d })" % (FLAG_ACHROMATIC * 2, FLAG_ACHROMATIC),
        "        end",
        "    end",
        "end",
    ])
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    # Not required: with no source given this does --all, which is the only
    # thing a release build should ever use. --savedvars predates the full run
    # and needed the appearances to have been browsed in-game first; it is kept
    # for targeting a subset, but it can only ever produce a PARTIAL table, so
    # it must not be what you get by forgetting an argument.
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--savedvars", type=Path, help="Only appearances recorded in a SavedVariables file (needs /tmpalette record on and in-game browsing first). Produces a PARTIAL table — not for releases")
    src.add_argument("--seed-file", type=Path, help="Plain text file with one visualID per line. Produces a PARTIAL table")
    src.add_argument("--all", action="store_true", help="Every appearance in ItemAppearance (~64,900), read straight from the game's data with no in-game step. THE DEFAULT, and what a release ships")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Where to write ColorData.lua")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N visuals, lowest visualID first (for a quick test run)")
    parser.add_argument("--sample", type=int, default=None, help="Process N visuals evenly spread across the full sorted range instead of just the lowest (better mix of old/new appearances)")
    parser.add_argument("--jobs", type=int, default=6, help="Parallel fetch/profile workers (default 6 — these are free community servers, don't get greedy)")
    parser.add_argument("--delay", type=float, default=REQUEST_DELAY_SECONDS, help="Per-worker delay after each network request, in seconds")
    parser.add_argument("--no-geometry", action="store_true", help="Skip visible-geometry weighting and analyse raw texture pixels (the pre-0.5 behaviour)")
    parser.add_argument("--offline", action="store_true", help="Never fetch: rebuild the output from the existing profile cache only. For retuning anything downstream of profiling (cluster ranking, emitted fields, pack format), which needs no new pixels. Appearances with no cached profile are omitted")
    parser.add_argument("--attachment-share", type=float, default=ATTACHMENT_SHARE, metavar="F", help=f"Share of an item's colour given to its attached 3D piece when it also has body textures (default {ATTACHMENT_SHARE}). Acts after profiling, so --offline retunes it")
    parser.add_argument("--refresh-db2", action="store_true", help="Re-download the DB2 CSVs instead of reusing tools/db2_cache/. REQUIRED after a content patch — otherwise the run reuses the previous patch's tables and silently omits every new appearance")
    parser.add_argument("--peak-window", type=float, default=None, metavar="DEG", help=f"Override HUE_PEAK_WINDOW (default {DEFAULT_HUE_PEAK_WINDOW:.0f}): how far apart two hue peaks must be to count as separate colours. Acts after profiling, so --offline retunes it in seconds. Lower splits gold from brown on the same item; too low fragments one colour into several")
    parser.add_argument("--max-clusters", type=int, default=None, metavar="N", help=f"Override MAX_CLUSTERS (default {DEFAULT_MAX_CLUSTERS}): how many colour clusters an appearance may emit. Acts after profiling, so --offline retunes it. Raising it costs {CLUSTER_BYTES} bytes per appearance and stops a narrow --peak-window draining colour into the greyscale buckets")
    args = parser.parse_args()

    if args.max_clusters is not None:
        # Also post-profiling, and also safe to retune offline. The Lua decoder
        # walks the packed string in 5-byte steps rather than assuming three, so
        # a different count needs no addon change -- only more bytes per
        # appearance (5 each) in ColorData.lua.
        global MAX_CLUSTERS
        MAX_CLUSTERS = args.max_clusters
        print(f"MAX_CLUSTERS overridden to {MAX_CLUSTERS} "
              f"({MAX_CLUSTERS * CLUSTER_BYTES} bytes per appearance)")

    if args.peak_window is not None:
        # Deliberately a global rather than threaded through: dominant_colors is
        # called from a worker pool and reads it directly, and the value is
        # fixed for the whole run.
        global HUE_SUPPRESS_DEGREES
        HUE_SUPPRESS_DEGREES = args.peak_window
        print(f"HUE_SUPPRESS_DEGREES overridden to {HUE_SUPPRESS_DEGREES:.0f} "
              f"(profile cache is unaffected — this acts after profiling)")

    global REFRESH_DB2
    REFRESH_DB2 = args.refresh_db2

    if not (args.savedvars or args.seed_file or args.all):
        args.all = True
        print("No source given, using --all (every appearance in the game's data).")

    session = requests.Session()
    session.headers["User-Agent"] = "TransmogPalette-ColorDataGenerator/0.4 (WoW addon dev tool)"

    item_appearance, display_info, matres_by_display, texture_by_matres = build_lookup_tables(session)
    print(f"ItemAppearance rows: {len(item_appearance)}")

    if args.all:
        visual_ids = sorted(item_appearance)
    elif args.savedvars:
        visual_ids = parse_savedvariables_visuals(args.savedvars)
    else:
        visual_ids = parse_seed_file(args.seed_file)
    if args.sample and args.sample < len(visual_ids):
        step = len(visual_ids) / args.sample
        visual_ids = [visual_ids[int(i * step)] for i in range(args.sample)]
    elif args.limit:
        visual_ids = visual_ids[: args.limit]

    print(f"Processing {len(visual_ids)} appearances...")

    # Resolve every appearance to its textures up front. This is pure local CSV
    # work, and knowing the whole texture set in advance is what lets the fetch
    # phase be parallel, deduplicated and resumable.
    model_by_display = {} if args.no_geometry else load_model_files()

    failures = []
    jobs_by_visual = {}
    attachment_by_visual = {}
    needed = set()
    weighted_visuals = 0
    baked_visuals = 0
    for visual_id in visual_ids:
        fdids = resolve_texture_fdids(
            visual_id, item_appearance, display_info, matres_by_display, texture_by_matres
        )
        model_fdid = resolve_model_fdid(
            visual_id, item_appearance, display_info, matres_by_display, model_by_display
        )

        baked = False
        if not fdids:
            # Neither MaterialRes path resolved. Before giving up, look inside
            # the model -- see resolve_baked_texture_fdids. This is the only
            # place in the resolve loop that touches the network, and it fires
            # for ~1.6% of appearances, all of which would otherwise be dropped.
            if model_fdid:
                # Offline still takes this path, it just may not fetch: passing
                # no session means a cached model resolves and an uncached one
                # raises inside resolve_baked_texture_fdids and comes back
                # empty. Skipping the path entirely instead would silently drop
                # ~1,000 already-profiled weapons from an offline rebuild, which
                # looks exactly like a regression in the output.
                fdids = resolve_baked_texture_fdids(
                    model_fdid, None if args.offline else session, args.delay
                )
                baked = bool(fdids)
            if not fdids:
                failures.append((visual_id, "no texture FileDataID resolved (unsupported display type?)"))
                continue

        if baked:
            baked_visuals += 1
            # Weighting is deliberately OFF for baked textures. build_weight_grid
            # pairs the Nth texture with the Nth DYNAMIC slot, and a baked
            # texture has no dynamic slot -- the pairing would either fail or,
            # worse, silently credit one surface's geometry to another's atlas,
            # which is the bug that once turned a purple helm red. Unweighted is
            # the same fallback the pairing already takes when it cannot match.
            pairs = [(fdid, 0, i) for i, fdid in enumerate(fdids)]
        else:
            if model_fdid:
                weighted_visuals += 1
            # tex_index pairs each texture with the model slot that wears it.
            pairs = [(fdid, model_fdid, i) for i, fdid in enumerate(fdids)]
        jobs_by_visual[visual_id] = pairs
        needed.update(pairs)
        if not baked:
            att_fdids, att_model = resolve_attachment(
                visual_id, item_appearance, display_info, matres_by_display,
                texture_by_matres, model_by_display
            )
            if att_fdids:
                att_pairs = [(fdid, att_model, i) for i, fdid in enumerate(att_fdids)]
                attachment_by_visual[visual_id] = att_pairs
                needed.update(att_pairs)

    if baked_visuals:
        print(f"  {baked_visuals} appearances recovered from textures baked into "
              f"the model (weapons, cloaks, helms — no MaterialRes row exists).")

    print(
        f"{len(jobs_by_visual)} appearances resolved to {len(needed)} unique texture/model pairs "
        f"({len(failures)} unresolvable)."
    )
    if attachment_by_visual:
        print(f"  {len(attachment_by_visual)} appearances also have an attached 3D piece "
              f"(buckle, scarf, cuffs) whose textures are blended in at "
              f"{args.attachment_share:.0%} -- see resolve_attachment.")
    pair_to_visuals = {}
    for visual_id, pairs in list(jobs_by_visual.items()) + list(attachment_by_visual.items()):
        for pair in pairs:
            pair_to_visuals.setdefault(pair, []).append(visual_id)
    if not args.no_geometry:
        print(
            f"  geometry weighting applies to {weighted_visuals} "
            f"({weighted_visuals / max(len(jobs_by_visual), 1):.1%}); the rest are component "
            f"textures painted on the character mesh, which have no per-item model."
        )

    profile_cache, opaque_fallback_jobs = build_profiles(
        sorted(needed), jobs=args.jobs, delay=args.delay, offline=args.offline
    )
    if opaque_fallback_jobs:
        affected_visuals = sorted({
            v for job in opaque_fallback_jobs for v in pair_to_visuals.get(job, [])
        })
        fallback_report_path = SCRIPT_DIR / "opaque_fallback.txt"
        fallback_report_path.write_text(
            "\n".join(
                f"visual {v}: a texture had zero alpha everywhere but real colour "
                f"data, so it was treated as opaque instead of skipped"
                for v in affected_visuals
            ),
            encoding="utf-8",
        )
        print(
            f"{len(opaque_fallback_jobs)} textures ({len(affected_visuals)} appearances) "
            f"used the zero-alpha opaque fallback — see {fallback_report_path}"
        )

    visual_colors = {}
    for visual_id, pairs in jobs_by_visual.items():
        # Pool every component texture's pixels into one analysis. Clustering
        # each texture separately and merging the results would reintroduce
        # the same blending flaw one level up.
        pooled = new_profile()
        for pair in pairs:
            profile = profile_cache.get(pair)
            if profile:
                add_profiles(pooled, profile)
        # The attached piece, pooled the same way, then blended in as a fixed
        # share of the item. Body pixel counts and geometry weights are on
        # different scales, so each part is normalised first.
        attached = new_profile()
        for pair in attachment_by_visual.get(visual_id, []):
            profile = profile_cache.get(pair)
            if profile:
                add_profiles(attached, profile)
        if attached["total"] and pooled["total"]:
            share = args.attachment_share
            scale_profile(pooled, (1 - share) / pooled["total"])
            add_profiles(pooled, scale_profile(attached, share / attached["total"]))
        elif attached["total"]:
            pooled = attached

        clusters = dominant_colors(pooled)
        if clusters:
            visual_colors[visual_id] = clusters
        else:
            failures.append((visual_id, "all resolved textures failed to fetch"))

    write_lua_output(visual_colors, args.output)
    print(f"Wrote {len(visual_colors)} entries to {args.output}")

    if failures:
        report_path = SCRIPT_DIR / "failures.txt"
        report_path.write_text(
            "\n".join(f"visual {v}: {reason}" for v, reason in failures), encoding="utf-8"
        )
        print(f"{len(failures)} appearances failed — see {report_path}")


if __name__ == "__main__":
    main()
