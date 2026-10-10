"""Colour matching by CLOSENESS, scored against what is on screen.

Every bucket scheme this project has tried had to decide which single name an
appearance deserves, and a lot of WoW armour has no single name: a red and gold
gauntlet is both, shaded red reads brown to a namer that never saw shading,
metal gold reads mustard. So this drops names altogether.

A swatch is a colour. An appearance scores against it by how much of its
surface is CLOSE to that colour -- its texture clusters, moved to on-screen
brightness by the measured calibration, weighted by coverage, with a kernel on
perceptual distance. The filter then sorts by score instead of passing or
failing, so a piece that is mostly the colour comes first and a piece with a
trim of it comes last.

SCORED WITHOUT LABELS. The captured screenshot tiles (capture_calibrate.py)
give the same score computed from the pixels actually on screen. For each
swatch, the question is whether the items ranked highest from texture data are
the ones whose on-screen pixels are closest to the swatch. Both sides use one
distance, so nothing is graded by a namer; the comparison is texture data
against the game's own render of the same item.

    python match_eval.py
"""
import colorsys

import numpy as np

import capture_calibrate as cc
import color_naming as cn
import naming_compare as nc

FIT = (0.95, 15.8, 1.13)

# Lightness counts for less than hue and chroma. Shading moves a surface's
# lightness a long way while a person still sees one colour (colour
# constancy); it moves hue and chroma much less. Not zero: black, grey and white
# differ ONLY in lightness.
K_L = 0.5
# Distance at which a pixel or cluster counts half. ~12 is "same colour family,
# visibly different shade".
SIGMA = 12.0
# Pixels darker than this are shadow and silhouette remnants, not surface
# anyone looks at.
MIN_SCREEN_L = 12.0

# The broad strip's swatches, as drawn (Palette.lua's CANONICAL_* at broad
# grain). A swatch is what the player SEES, so it is not calibrated.
SWATCHES = {
    "black": (0, 0.0, 0.10), "gray": (0, 0.0, 0.48), "white": (0, 0.0, 0.90),
    "red": (6, 0.85, 0.74), "brown": (25, 0.65, 0.45), "orange": (38, 0.90, 0.74),
    "gold": (52, 0.85, 0.74), "green": (120, 0.75, 0.74), "blue": (215, 0.80, 0.74),
    "purple": (312, 0.70, 0.74), "pink": (335, 0.70, 0.74),
}


def swatch_lab(hsv):
    return cn.srgb_to_lab(np.array([colorsys.hsv_to_rgb(hsv[0] / 360, hsv[1], hsv[2])]))[0]


# A grey swatch (black, grey, white) is the one place tint must count MORE, not
# less: dark brown leather sits a short a*/b* step from black, and with the
# chromatic weighting it ranked as black -- seen in review as brown boots and a
# gold gauntlet on the black row. Lightness is also what separates the greys
# from each other, so it counts in full.
NEUTRAL_TARGET_CHROMA = 10.0
NEUTRAL_K_TINT = 2.5


def closeness(lab, target):
    """(N, 3) Lab -> (N,) in [0, 1], 1 at the target colour."""
    d = lab - target
    if np.hypot(target[1], target[2]) < NEUTRAL_TARGET_CHROMA:
        d2 = d[:, 0] ** 2 + NEUTRAL_K_TINT ** 2 * (d[:, 1] ** 2 + d[:, 2] ** 2)
    else:
        d2 = (K_L * d[:, 0]) ** 2 + d[:, 1] ** 2 + d[:, 2] ** 2
    return np.exp(-0.5 * d2 / SIGMA ** 2)


# === Coloured or not is a hard line ===
#
# Distance alone put white trousers under a pale cyan swatch and dark red ones
# under black: by the numbers those ARE near each other. To a person they are
# not -- whether a surface has any colour at all is the first thing anyone
# judges, before which colour. So each cluster gets a colourfulness m in [0, 1]
# from its on-screen chroma (a short ramp, not a step, so a cluster right at
# the edge does not flip an item's results on a rounding difference):
#   - a colour swatch counts only the coloured part of a cluster (m), so a
#     cool white or a steel grey never matches pale cyan or slate;
#   - a grey-tone swatch counts only the grey part (1 - m), and is scaled down
#     by how much of the item is coloured at all, so red trousers with dark
#     seams are not "black", and black armour with gold trim ranks below
#     plain black armour.
COLOR_C_LO, COLOR_C_HI = 8.0, 18.0


def colourfulness(lab, achromatic):
    c = np.hypot(lab[:, 1], lab[:, 2])
    m = np.clip((c - COLOR_C_LO) / (COLOR_C_HI - COLOR_C_LO), 0, 1)
    # The generator's own perceptual verdict wins where it says "no hue".
    return np.where(achromatic, 0.0, m)


def texture_score(ranks, target):
    """Coverage-weighted closeness of an appearance's texture clusters."""
    hsv = [c[:3] for c in ranks]
    w = np.array([c[3] for c in ranks])
    lab = cc.calibrated_lab(hsv, *FIT)
    m = colourfulness(lab, np.array([bool(c[4]) for c in ranks]))
    total = max(w.sum(), 1e-9)
    close = closeness(lab, target)
    if np.hypot(target[1], target[2]) < NEUTRAL_TARGET_CHROMA:
        coloured_share = (w * m).sum() / total
        return float((w * (1 - m) * close).sum() / total * (1 - coloured_share))
    return float((w * m * close).sum() / total)


def screen_score(tile, target):
    px = tile["lab"][tile["mask"]]
    px = px[px[:, 0] >= MIN_SCREEN_L]
    if len(px) < 100:
        return np.nan
    return float(closeness(px, target).mean())


def main():
    pages = cc.load_pages()
    data = nc.parse()
    tiles, bare = cc.load_tiles(pages, set(data))
    cc.item_masks(tiles, bare)
    # Head tiles carry some of the character's face (a helm changes the head
    # around it), so they are scored but reported separately.
    tiles = [t for t in tiles if t["slot"] != 0]
    print(f"{len(tiles)} captured appearances (head slot excluded)\n")

    K = 20
    print(f"swatch    screen-closeness of the top {K}       rank corr.")
    print(f"          ideal   closeness  1.2.1 bucket")
    totals = []
    for name, hsv in SWATCHES.items():
        target = swatch_lab(hsv)
        scr = np.array([screen_score(t, target) for t in tiles])
        tex = np.array([texture_score(data[t["vid"]], target) for t in tiles])
        ok = ~np.isnan(scr)
        scr, tex = scr[ok], tex[ok]
        cur = np.array([nc.current_family(nc.main_cluster(data[t["vid"]])) == name
                        for t, k in zip(tiles, ok) if k])
        ideal = np.sort(scr)[::-1][:K].mean()
        ours = scr[np.argsort(-tex)[:K]].mean()
        # 1.2.1 does not rank: its result is the whole bucket in game order,
        # so its expected top-K is the bucket's mean.
        bucket = scr[cur].mean() if cur.any() else np.nan
        rs = np.corrcoef(np.argsort(np.argsort(tex)), np.argsort(np.argsort(scr)))[0, 1]
        totals.append((ours / ideal, bucket / ideal if cur.any() else np.nan))
        print(f"{name:8s}  {ideal:5.3f}   {ours:5.3f} {ours / ideal:4.0%}  "
              f"{bucket:5.3f} {bucket / ideal:4.0%}  (n={cur.sum():3d})   {rs:5.2f}")
    t = np.array(totals)
    print(f"\nmean share of ideal: closeness {np.nanmean(t[:, 0]):.0%}, "
          f"1.2.1 bucket {np.nanmean(t[:, 1]):.0%}")


if __name__ == "__main__":
    main()
