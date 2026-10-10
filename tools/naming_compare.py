"""How differently would crowd-sourced colour NAMING file the game's armour?

Holds detection fixed -- the same main colour per appearance that 1.2.1 picks
from the shipped ColorData.lua -- and changes only the step that turns that
colour into a bucket: Palette.lua's hue bands versus color_naming's survey
probabilities. Every disagreement is therefore a naming question, not a
detection one, which is the separation the old scoring never had.

    python naming_compare.py              # summary + confusion matrix
    python naming_compare.py --json out.json   # disagreement samples for review
"""
import argparse
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

import color_naming as cn

COLOR_DATA = Path(__file__).resolve().parent.parent / "TransmogPalette" / "ColorData.lua"
CLUSTER_BYTES = 5

# === Mirror of 1.2.1's Palette.lua (broad grain). Change together. ===
NEUTRAL_SAT_THRESHOLD = 0.15
NEUTRAL_VALUE_THRESHOLD = 0.06
BLACK_MAX, WHITE_MIN = 0.22, 0.60
COLOR_FIRST = 0.20
HUE_BANDS = [(18, "red"), (32, "rust"), (46, "orange"), (70, "gold"),
             (100, "olive"), (155, "green"), (195, "teal"), (250, "blue"),
             (275, "indigo"), (300, "violet"), (325, "purple"), (345, "pink")]
HUE_GROUPS = {"red": "red", "rust": "brown", "orange": "orange", "gold": "gold",
              "olive": "green", "green": "green", "teal": "blue", "blue": "blue",
              "indigo": "purple", "violet": "purple", "purple": "purple",
              "pink": "pink"}


def parse(path=COLOR_DATA):
    """visualID -> [(h, s, v, weight, achromatic)], dominant first."""
    text = path.read_text(encoding="utf-8", errors="replace")
    out = {}
    for m in re.finditer(r"\[(\d+)\]\s*=\s*\"((?:\\\d{3})+)\"", text):
        raw = [int(b) for b in re.findall(r"\\(\d{3})", m.group(2))]
        out[int(m.group(1))] = [
            (raw[i] * 1.5, raw[i + 1] / 255, raw[i + 2] / 255, raw[i + 3] / 255,
             bool(raw[i + 4] & 1))
            for i in range(0, len(raw) - CLUSTER_BYTES + 1, CLUSTER_BYTES)
        ]
    return out


def is_neutral(c):
    return c[4] or c[1] < NEUTRAL_SAT_THRESHOLD or c[2] < NEUTRAL_VALUE_THRESHOLD


def main_cluster(ranks):
    """Mirrors ns.ComputeMainAndAccent's choice of main."""
    colors = sorted((c for c in ranks if not is_neutral(c)),
                    key=lambda c: -(c[3] * c[1] * c[2]))
    neutrals = [c for c in ranks if is_neutral(c)]
    neutral = None
    if neutrals:
        total = sum(c[3] for c in neutrals)
        big = max(neutrals, key=lambda c: c[3])
        v = sum(c[2] * c[3] for c in neutrals) / total if total else big[2]
        neutral = (big[0], big[1], v, total, True)
    if colors and sum(c[3] for c in colors) >= COLOR_FIRST:
        return colors[0]
    return neutral or (colors[0] if colors else ranks[0])


def current_family(c):
    if is_neutral(c):
        return "black" if c[2] < BLACK_MAX else "gray" if c[2] < WHITE_MIN else "white"
    h = c[0] % 360
    for bound, band in HUE_BANDS:
        if h < bound:
            return HUE_GROUPS[band]
    return "red"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, help="write disagreement samples here")
    ap.add_argument("--per-cell", type=int, default=60)
    args = ap.parse_args()

    data = parse()
    vids = sorted(data)
    mains = [main_cluster(data[v]) for v in vids]
    cur = [current_family(c) for c in mains]
    probs = cn.family_probs_hsv([(c[0], c[1], c[2]) for c in mains])
    best = probs.argmax(axis=1)
    sur = [cn.FAMILIES[i] for i in best]
    conf = probs[np.arange(len(best)), best]

    n = len(vids)
    agree = sum(a == b for a, b in zip(cur, sur))
    print(f"{n} appearances. Survey agrees with 1.2.1 on {agree} ({agree / n:.1%}).")
    # "Probable" = the survey gives 1.2.1's answer at least 30%: a genuine
    # second reading rather than a flat contradiction.
    cur_idx = np.array([cn.FAMILY_INDEX[f] for f in cur])
    plausible = (probs[np.arange(n), cur_idx] >= 0.30).sum()
    print(f"1.2.1's answer gets >=30% from the survey on {plausible} ({plausible / n:.1%}).")
    print(f"Survey confidence in its own answer: median {np.median(conf):.0%}, "
          f"under 50% on {(conf < 0.5).mean():.1%} of appearances.\n")

    fams = cn.FAMILIES
    cells = Counter(zip(cur, sur))
    print("rows = 1.2.1 bucket, columns = survey answer (counts)")
    print("        " + "".join(f"{f[:6]:>7s}" for f in fams) + "   total")
    for a in fams:
        row = [cells[(a, b)] for b in fams]
        print(f"{a:7s} " + "".join(f"{x:7d}" for x in row) + f"  {sum(row):6d}")
    print("        " + "".join(f"{sum(cells[(a, b)] for a in fams):7d}" for b in fams))

    print("\nlargest disagreements:")
    for (a, b), k in sorted(((k, v) for k, v in cells.items() if k[0] != k[1]),
                            key=lambda kv: -kv[1])[:15]:
        print(f"  1.2.1 {a:7s} -> survey {b:7s} {k:6d}")

    if args.json:
        rng = random.Random(1)
        by_cell = defaultdict(list)
        for i, v in enumerate(vids):
            by_cell[(cur[i], sur[i])].append(i)
        out = {"families": fams, "cells": []}
        for (a, b), idxs in sorted(by_cell.items(), key=lambda kv: -len(kv[1])):
            if a == b or len(idxs) < 25:
                continue
            pick = rng.sample(idxs, min(args.per_cell, len(idxs)))
            out["cells"].append({
                "current": a, "survey": b, "count": len(idxs),
                "samples": [{
                    "vid": vids[i],
                    "hsv": [round(mains[i][0], 1), round(mains[i][1], 3), round(mains[i][2], 3)],
                    "p": {f: round(float(probs[i][j]), 3) for j, f in enumerate(fams) if probs[i][j] >= 0.02},
                } for i in pick],
            })
        args.json.write_text(json.dumps(out), encoding="utf-8")
        print(f"\nwrote {sum(len(c['samples']) for c in out['cells'])} samples in "
              f"{len(out['cells'])} cells to {args.json}")


if __name__ == "__main__":
    main()
