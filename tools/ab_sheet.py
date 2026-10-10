"""A/B: the palette-v3 setup against the current (1.3.0) setup, on the same
captured items, per GENERAL swatch -- the row the addon shows by default.

  A  palette v3 (research/palette-v3.json) scored the way it was when v3 was
     reviewed: no hue rotation, no coloured/grey split, no cutoff.
  B  tools/palette.json scored as Matching.lua does now: hue rotation,
     coloured/grey split, per-swatch cutoffs.

A general swatch matches its best member in both, as the addon does.

    python ab_sheet.py --slot 5        # legs
    python ab_sheet.py                 # all captured slots
"""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import capture_calibrate as cc
import match_eval as me
import naming_compare as nc

TOOLS = Path(__file__).resolve().parent
RESEARCH = TOOLS.parent / "research"

V3_NAMES = {1: "black", 2: "dark gray", 3: "light gray", 4: "white", 5: "maroon", 6: "red",
            7: "bronze", 8: "brown", 9: "gold", 10: "green", 11: "bright green", 12: "jade",
            13: "teal", 15: "cyan", 16: "sky blue", 17: "slate", 18: "blue", 19: "violet",
            20: "purple"}
GROUPS = [
    ("Black", ["black"]), ("Gray", ["dark gray", "light gray", "slate"]), ("White", ["white"]),
    ("Red", ["maroon", "red"]), ("Orange", ["orange"]), ("Brown", ["bronze", "brown"]),
    ("Gold", ["gold"]), ("Green", ["green", "bright green", "jade"]),
    ("Blue", ["teal", "cyan", "blue", "sky blue"]), ("Purple", ["violet", "purple"]),
    ("Pink", ["pink"]),
]


def score_v3(ranks, target):
    """texture_score as it was when palette v3 was reviewed."""
    hsv = [c[:3] for c in ranks]
    w = np.array([c[3] for c in ranks])
    lab = cc.calibrated_lab(hsv, *me.FIT, rotate=False)
    d = lab - target
    d2 = (me.K_L * d[:, 0]) ** 2 + d[:, 1] ** 2 + d[:, 2] ** 2
    return float((w * np.exp(-0.5 * d2 / me.SIGMA ** 2)).sum() / max(w.sum(), 1e-9))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", type=int)
    ap.add_argument("--dominance", type=float, default=0.0,
                    help="B also requires the swatch to reach this share of the item's best "
                         "score in any OTHER general group (0 = off, the shipped 1.3.0 build)")
    args = ap.parse_args()

    v3 = {V3_NAMES[s["index"]]: np.array(s["lab"])
          for s in json.loads((RESEARCH / "palette-v3.json").read_text()) if s["index"] in V3_NAMES}
    cur = {p["name"]: p for p in json.loads((TOOLS / "palette.json").read_text())}

    data = nc.parse()
    tiles, bare = cc.load_tiles(cc.load_pages(), set(data))
    cc.item_masks(tiles, bare)
    tiles = [t for t in tiles if t["slot"] != 0 and t["mask"].mean() >= 0.06
             and (args.slot is None or t["slot"] == args.slot)]

    # Relative scores for every current swatch, once per item.
    names = [p["name"] for p in cur.values()]
    rel = np.array([[me.texture_score(data[t["vid"]], np.array(cur[nm]["lab"])) / cur[nm]["min_score"]
                     for nm in names] for t in tiles])
    group_of = {m: g for g, ms in GROUPS for m in ms}

    n, tw, th, gap, label_w = 10, 70, 95, 3, 150
    row_h = th + gap
    sheet = Image.new("RGB", (label_w + n * (tw + gap), len(GROUPS) * (2 * row_h + 10)), (22, 21, 27))
    d = ImageDraw.Draw(sheet)
    for j, (gname, members) in enumerate(GROUPS):
        y = j * (2 * row_h + 10)
        a_members = [v3[m] for m in members if m in v3]
        b_members = [cur[m] for m in members if m in cur]
        a = np.array([max([score_v3(data[t["vid"]], lab) for lab in a_members], default=0) for t in tiles])
        idx = [names.index(p["name"]) for p in b_members]
        b = rel[:, idx].max(axis=1) if idx else np.zeros(len(tiles))
        if args.dominance > 0:
            others = [k for k, nm in enumerate(names) if group_of.get(nm) != gname]
            best_other = rel[:, others].max(axis=1)
            b = np.where(b >= args.dominance * best_other, b, 0)
        a_pick = list(np.argsort(-a)[:n])
        b_pick = [i for i in np.argsort(-b)[:n] if b[i] >= 1]
        d.text((8, y + 8), gname, fill=(255, 255, 255))
        d.text((8, y + 28), "A: palette v3", fill=(190, 220, 190))
        d.text((8, y + row_h + 8), "B: 1.3.0" + (f" +dom {args.dominance}" if args.dominance else ""),
               fill=(220, 190, 170))
        d.text((8, y + row_h + 28), f"{int((b >= 1).sum())} pass cutoff", fill=(150, 150, 160))
        for row, picks in ((0, a_pick), (1, b_pick)):
            for k, i in enumerate(picks):
                im = Image.fromarray((tiles[i]["rgb"] * 255).astype(np.uint8)).resize((tw, th))
                sheet.paste(im, (label_w + k * (tw + gap), y + row * row_h))
        d.line([(0, y + 2 * row_h + 4), (sheet.width, y + 2 * row_h + 4)], fill=(60, 58, 70))
    name = ("ab-all" if args.slot is None else f"ab-slot{args.slot}") +         (f"-dom{args.dominance}" if args.dominance else "") + ".png"
    sheet.save(RESEARCH / name)
    print(f"{len(tiles)} items -> {RESEARCH / name}")


if __name__ == "__main__":
    main()
