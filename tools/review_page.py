"""Builds the naming review page from captured screenshot tiles.

For each contested pair of colour families (brown/gold, gray/blue, ...) the
page shows captured appearances sorted from "most A" to "most B" by the
crowd-sourced namer's own odds on the CALIBRATED main colour, with the
namer's dividing line pre-set. The reviewer moves the line to where the items
actually change colour. Seeing the whole ramp at once is the point: one
judgement per boundary, made with every neighbour visible, instead of one
judgement per item made in whatever order the items happened to come up.

A cut becomes a threshold on s = P(B) / (P(A) + P(B)): B wins where s exceeds
it, which is the same as weighting the two families' probabilities.

    python review_page.py out.html
"""
import base64
import io
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

import capture_calibrate as cc
import color_naming as cn
import naming_compare as nc

TEMPLATE = Path(__file__).resolve().parent / "review" / "naming_review.html"
FIT = (0.95, 15.8, 1.13)   # capture_calibrate's measured texture -> screen fit
MAX_PER_STRIP = 48
MIN_PAIR_MASS = 0.5        # an item belongs to a strip when A and B together hold this much

PAIRS = [
    ("brown", "gold"), ("brown", "orange"), ("orange", "gold"), ("red", "brown"),
    ("red", "pink"), ("pink", "purple"), ("blue", "purple"),
    ("black", "gray"), ("gray", "white"),
    ("gray", "brown"), ("gray", "blue"), ("gray", "purple"),
]


def _jpeg(rgb):
    buf = io.BytesIO()
    Image.fromarray((rgb * 255).astype(np.uint8)).save(buf, "JPEG", quality=82)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _hex(lab):
    L, a, b = lab
    fy = (L + 16) / 116
    fx, fz = fy + a / 500, fy - b / 200
    def inv(f):
        return f ** 3 if f ** 3 > 216 / 24389 else (116 * f - 16) / (24389 / 27)
    xyz = np.array([inv(fx) * 0.95047, inv(fy), inv(fz) * 1.08883])
    m = np.array([[3.2404542, -1.5371385, -0.4985314],
                  [-0.9692660, 1.8760108, 0.0415560],
                  [0.0556434, -0.2040259, 1.0572252]])
    lin = np.clip(m @ xyz, 0, 1)
    srgb = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * lin ** (1 / 2.4) - 0.055)
    return "#" + "".join(f"{int(round(c * 255)):02x}" for c in srgb)


def build():
    pages = cc.load_pages()
    data = nc.parse()
    tiles, _ = cc.load_tiles(pages, set(data))
    mains = [nc.main_cluster(data[t["vid"]]) for t in tiles]
    labs = cc.calibrated_lab([m[:3] for m in mains], *FIT)
    probs = cn.family_probs_lab(labs)
    fi = cn.FAMILY_INDEX
    strips = []
    for a, b in PAIRS:
        pa, pb = probs[:, fi[a]], probs[:, fi[b]]
        mass = pa + pb
        idx = np.where(mass >= MIN_PAIR_MASS)[0]
        if len(idx) < 6:
            continue
        s = pb[idx] / mass[idx]
        order = idx[np.argsort(s)]
        if len(order) > MAX_PER_STRIP:
            # Even across the A->B SCALE, not by rank. Most pairs are lopsided
            # (453 browns against a handful of golds), and sampling by rank
            # shows forty browns and the one gold -- the transition, which is
            # the only part being judged, gets almost no tiles.
            s_sorted = np.sort(s)
            bins = [list(np.where((s_sorted >= lo) & (s_sorted < lo + 1 / 16 + (lo >= 15 / 16)))[0])
                    for lo in np.arange(16) / 16]
            take = set()
            while len(take) < MAX_PER_STRIP:
                for members in bins:
                    if members and len(take) < MAX_PER_STRIP:
                        take.add(members.pop(len(members) // 2))
            order = order[sorted(take)]
        items = []
        for i in order:
            items.append({
                "vid": tiles[i]["vid"],
                "img": _jpeg(tiles[i]["rgb"]),
                "chip": _hex(labs[i]),
                "s": round(float(probs[i, fi[b]] / mass[i]), 4),
                "now": nc.current_family(mains[i]),
            })
        default_cut = next((k for k, it in enumerate(items) if it["s"] > 0.5), len(items))
        strips.append({"id": f"{a}-{b}", "a": a, "b": b, "items": items,
                       "defaultCut": default_cut, "pool": int(len(idx))})
    return {"strips": strips, "fit": FIT}


def main():
    out = Path(sys.argv[1])
    payload = build()
    html = TEMPLATE.read_text(encoding="utf-8").replace(
        "/*__REVIEW_DATA__*/null", json.dumps(payload, separators=(",", ":")))
    out.write_text(html, encoding="utf-8")
    n = sum(len(s["items"]) for s in payload["strips"])
    print(f"{len(payload['strips'])} strips, {n} tiles, {out.stat().st_size / 1e6:.1f} MB -> {out}")
    for s in payload["strips"]:
        print(f"  {s['id']:14s} {len(s['items']):3d} shown of {s['pool']:4d}, survey cut at {s['defaultCut']}")


if __name__ == "__main__":
    main()
