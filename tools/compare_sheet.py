"""Before/after sheet: the same captured items, filtered the 1.2.1 way and the
closeness way, one swatch per pair of rows.

For each swatch in tools/palette.json:
  NEW   -- the ten captured items scoring highest by closeness
           (match_eval.texture_score), best first.
  1.2.1 -- what picking the nearest 1.2.1 swatch returns: captured items
           whose 1.2.1 main colour lands in that bucket. 1.2.1 filters but does
           not rank, so with --slot the row is the game's own listing order
           (what the first page really shows); across all slots, where the
           game never mixes slots, it is a random draw from the bucket.

Both rows draw from the same captured appearances, so the difference is
purely the method.

    python compare_sheet.py              # all slots -> research/compare.png
    python compare_sheet.py --slot 5     # legs only -> research/compare-legs.png
"""
import colorsys
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import capture_calibrate as cc
import match_eval as me
import naming_compare as nc
import review_page

TOOLS = Path(__file__).resolve().parent
RESEARCH = TOOLS.parent / "research"
PALETTE = TOOLS / "palette.json"
# Tiles with less visible item than this are pieces hidden under the
# silhouette; they cannot be judged on a sheet.
MIN_VISIBLE = 0.06
# Below this closeness score an item is not shown at all, the way 1.2.1 hides
# a non-match. Without it every swatch fills its page: a slot with four gold
# leg pieces showed six red and grey ones after them. Matches that are real sat
# at 0.2-0.75 and filler at 0.11 and under in the legs data.
MIN_SCORE = 0.15


def lab_to_hsv(lab):
    hx = review_page._hex(lab)
    r, g, b = (int(hx[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    return h * 360, s, v


SLOT_NAMES = {1: "shoulder", 3: "chest", 4: "waist", 5: "legs", 6: "feet", 7: "wrist",
              8: "hands", 9: "back", 11: "weapon"}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", type=int, help="ItemAppearance DisplayType, e.g. 5 = legs")
    args = ap.parse_args()
    palette = json.loads(PALETTE.read_text(encoding="utf-8"))
    data = nc.parse()
    tiles, bare = cc.load_tiles(cc.load_pages(), set(data))
    cc.item_masks(tiles, bare)
    tiles = [t for t in tiles if t["slot"] != 0 and t["mask"].mean() >= MIN_VISIBLE
             and (args.slot is None or t["slot"] == args.slot)]
    rng = np.random.default_rng(7)
    old = [nc.current_family(nc.main_cluster(data[t["vid"]])) for t in tiles]

    n, tw, th, gap = 10, 70, 95, 3
    label_w = 170
    row_h = th + gap
    sheet = Image.new("RGB", (label_w + n * (tw + gap), len(palette) * (2 * row_h + 10)), (22, 21, 27))
    d = ImageDraw.Draw(sheet)
    for j, sw in enumerate(palette):
        lab = np.array(sw["lab"])
        y = j * (2 * row_h + 10)
        h, s, v = lab_to_hsv(lab)
        bucket = nc.current_family((h, s, v, 1.0, False))
        d.rectangle([6, y + 6, 40, y + 2 * row_h - 6], fill=sw["hex"])
        d.text((48, y + 8), sw["name"], fill=(255, 255, 255))
        d.text((48, y + 26), "NEW: closest first", fill=(190, 220, 190))
        d.text((48, y + row_h + 8), f"1.2.1: '{bucket}'", fill=(220, 190, 170))
        d.text((48, y + row_h + 26), "game order" if args.slot else "random first page",
               fill=(150, 150, 160))

        scores = np.array([me.texture_score(data[t["vid"]], lab) for t in tiles])
        new = [i for i in np.argsort(-scores)[:n] if scores[i] >= MIN_SCORE]
        legacy = [i for i, f in enumerate(old) if f == bucket]
        if args.slot is None and len(legacy) > n:
            legacy = sorted(rng.choice(legacy, n, replace=False).tolist())
        legacy = legacy[:n]
        for row, picks in ((0, new), (1, legacy)):
            for k, i in enumerate(picks):
                im = Image.fromarray((tiles[i]["rgb"] * 255).astype(np.uint8)).resize((tw, th))
                sheet.paste(im, (label_w + k * (tw + gap), y + row * row_h))
        d.line([(0, y + 2 * row_h + 4), (sheet.width, y + 2 * row_h + 4)], fill=(60, 58, 70))
    RESEARCH.mkdir(exist_ok=True)
    out = RESEARCH / ("compare.png" if args.slot is None
                      else f"compare-{SLOT_NAMES.get(args.slot, args.slot)}.png")
    sheet.save(out)
    print(f"{len(palette)} swatches, {len(tiles)} items -> {out}")


if __name__ == "__main__":
    main()
