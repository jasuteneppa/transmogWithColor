"""One scorecard for every general swatch in every captured slot.

Built because fixing whichever colour was pointed at, and checking that one
colour on one sheet, never told whether the whole thing got better.

TRUTH comes from the screenshots: how much of an item's on-screen surface is
close to the swatch, with the same coloured/grey rule the addon uses (a grey
swatch counts only the grey pixels, scaled down by how coloured the item is on
screen; a colour swatch counts only coloured pixels). A general swatch takes
its best member.

An item TRULY matches a general swatch when its on-screen relevance reaches
TRUE_SHARE of what that swatch's clearest captured items reach (the 98th
percentile over all captured items). Then, per slot x general swatch:
  right -- share of the FIRST PAGE (top 20) that truly matches
  found -- share of the truly matching items the filter returns at all
for the new matching (texture data, cutoff, sorted) and for 1.2.1 (the
matching bucket, game order). Cases with no true match in the slot are
skipped. Two numbers, because one can always be bought with the other:
showing less raises "right", showing more raises "found".

    python scorecard.py
"""
import json
from pathlib import Path

import numpy as np

import capture_calibrate as cc
import match_eval as me
import naming_compare as nc

TOOLS = Path(__file__).resolve().parent
PAGE = 20
TRUE_SHARE = 0.35
GROUPS = [
    ("Black", ["black"], "black"), ("Gray", ["dark gray", "light gray", "slate"], "gray"),
    ("White", ["white"], "white"), ("Red", ["maroon", "red"], "red"),
    ("Orange", ["orange"], "orange"), ("Brown", ["bronze", "brown"], "brown"),
    ("Gold", ["gold"], "gold"), ("Green", ["green", "bright green", "jade"], "green"),
    ("Blue", ["teal", "cyan", "blue"], "blue"), ("Purple", ["violet", "purple"], "purple"),
    ("Pink", ["pink"], "pink"),
]
SLOTS = {1: "shoulder", 3: "chest", 4: "waist", 5: "legs", 6: "feet", 7: "wrist",
         8: "hands", 9: "back", 11: "weapon"}


def screen_relevance(tile, target):
    px = tile["lab"][tile["mask"]]
    px = px[px[:, 0] >= me.MIN_SCREEN_L]
    if len(px) < 100:
        return np.nan
    m = me.colourfulness(px, np.zeros(len(px), bool))
    close = me.closeness(px, target)
    if np.hypot(target[1], target[2]) < me.NEUTRAL_TARGET_CHROMA:
        return float(((1 - m) * close).mean() * (1 - m.mean()))
    return float((m * close).mean())


def main():
    pal = {p["name"]: p for p in json.loads((TOOLS / "palette.json").read_text())}
    data = nc.parse()
    tiles, bare = cc.load_tiles(cc.load_pages(), set(data))
    cc.item_masks(tiles, bare)
    tiles = [t for t in tiles if t["slot"] in SLOTS and t["mask"].mean() >= 0.06]
    old = [nc.current_family(nc.main_cluster(data[t["vid"]])) for t in tiles]

    # Per item, per swatch: truth (screen) and prediction (texture, relative).
    names = list(pal)
    truth = np.array([[screen_relevance(t, np.array(pal[n]["lab"])) for n in names] for t in tiles])
    pred = np.array([[me.texture_score(data[t["vid"]], np.array(pal[n]["lab"])) / pal[n]["min_score"]
                      for n in names] for t in tiles])
    slot_of = np.array([t["slot"] for t in tiles])

    print(f"{len(tiles)} captured items, first page = {PAGE}, "
          f"true match >= {TRUE_SHARE:.0%} of the clearest")
    print()
    res = {}
    for gname, members, bucket in GROUPS:
        idx = [names.index(m) for m in members]
        tr = np.nan_to_num(np.nanmax(truth[:, idx], axis=1))
        pr = pred[:, idx].max(axis=1)
        thr = TRUE_SHARE * np.percentile(tr, 98)
        for s_ in SLOTS:
            sel = np.where(slot_of == s_)[0]
            pos = tr[sel] >= thr
            if pos.sum() == 0:
                continue
            passing = pr[sel] >= 1
            page = [i for i in np.argsort(-pr[sel]) if passing[i]][:PAGE]
            in_bucket = np.array([old[k] == bucket for k in sel])
            legacy_page = list(np.where(in_bucket)[0][:PAGE])
            res[(gname, s_)] = (
                pos[page].mean() if page else np.nan, (pos & passing).sum() / pos.sum(),
                pos[legacy_page].mean() if legacy_page else np.nan, (pos & in_bucket).sum() / pos.sum(),
                int(pos.sum()))

    def table(title, k):
        print(f"--- {title}")
        print(f"{'':8s}" + "".join(f"{v[:7]:>8s}" for v in SLOTS.values()) + "    mean")
        for gname, _, _ in GROUPS:
            vals = [res.get((gname, s_), (np.nan,) * 5)[k] for s_ in SLOTS]
            print(f"{gname:8s}" + "".join(f"{v:8.0%}" if not np.isnan(v) else f"{'-':>8s}" for v in vals)
                  + f"  {np.nanmean(vals):6.0%}")

    table("NEW: right (first page)", 0)
    table("1.2.1: right (first page)", 2)
    table("NEW: found", 1)
    table("1.2.1: found", 3)
    v = np.array(list(res.values()), dtype=float)
    print()
    print(f"overall  right: new {np.nanmean(v[:, 0]):.0%} vs 1.2.1 {np.nanmean(v[:, 2]):.0%}"
          f"   found: new {np.nanmean(v[:, 1]):.0%} vs 1.2.1 {np.nanmean(v[:, 3]):.0%}"
          f"   ({len(res)} slot x colour cases)")


if __name__ == "__main__":
    main()
