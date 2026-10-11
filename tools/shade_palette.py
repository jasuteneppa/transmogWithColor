"""Which shades does each general colour actually come in, ON SCREEN?

The old swatch palette (palette.json, the "More" row) came from clustering
texture colours. This redoes it from the journal tiles: for each colour, the
tuning-half items judged clearly that colour and nothing else; from each, the
item pixels that carry the colour (chromatic pixels for a chromatic colour,
grey pixels for black / gray / white; never the magenta backdrop, its fringe
or the uncovered silhouette -- journal_tiles.item_mask); an equal sample per item, so big items do not outvote small ones.
k-means in Lab (lightness at half weight) finds the shade groups. Writes a
sheet: per colour, the new on-screen shades (size = share of items' pixels),
then the old texture-derived swatches of the same colour.

    python shade_palette.py [--k 4] [--out sheet.png]
"""
import argparse
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import color_naming as cn
from export_swatches import lab_to_rgb01, GROUPS
from journal_tiles import item_mask, bare_references, TILE_SIZE

HERE = Path(__file__).resolve().parent
TILES = Path(os.environ.get("LOCALAPPDATA", ".")) / "TransmogPalette" / "journal_tiles"
NEUTRAL = ("black", "gray", "white")
PER_ITEM = 400


def item_pixels(vid, colour, rng, ref):
    a = np.asarray(Image.open(TILES / f"{vid}.png").convert("RGB").resize(TILE_SIZE, Image.NEAREST))
    px = a[item_mask(a, ref)] / 255.0
    lab = cn.srgb_to_lab(px)
    C = np.hypot(lab[:, 1], lab[:, 2])
    s = C / (lab[:, 0] + 20)
    keep = s < 0.12 if colour in NEUTRAL else s >= 0.12
    lab = lab[keep]
    if len(lab) < 30:
        return None
    return lab[rng.choice(len(lab), min(PER_ITEM, len(lab)), replace=False)]


def kmeans(X, k, it=40, seed=0):
    rng = np.random.default_rng(seed)
    W = np.array([0.5, 1, 1])
    C = X[rng.choice(len(X), k, replace=False)]
    for _ in range(it):
        a = np.argmin((((X[:, None] - C[None]) * W) ** 2).sum(-1), 1)
        C = np.array([X[a == j].mean(0) if (a == j).any() else C[j] for j in range(k)])
    return C, np.bincount(a, minlength=k) / len(X)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--out", type=Path, default=HERE.parent / "research" / "shades-ingame-vs-texture.png")
    args = ap.parse_args()
    spec = json.loads((HERE / "benchmark" / "labels.json").read_text())
    labels = {int(v): l for v, l in spec["labels"].items() if not l["holdout"]}
    have = {int(p.stem) for p in TILES.glob("*.png") if p.stem.isdigit()}
    old = {p["name"]: p for p in json.loads((HERE / "palette.json").read_text())}
    rng = np.random.default_rng(1)
    index = {int(k): v for k, v in json.loads((TILES / "index.json").read_text()).items()}
    refs = bare_references(TILES, index)

    rows = []
    for col in spec["colours"]:
        items = [v for v, l in labels.items() if l["yes"] == [col] and v in have]
        pix = [p for p in (item_pixels(v, col, rng, refs.get(index[v]["slot"])) for v in items) if p is not None]
        if not pix:
            continue
        C, share = kmeans(np.concatenate(pix), args.k)
        order = np.argsort(C[:, 0])                     # dark to light
        members = next(m for g, _, m, _ in GROUPS if g == f"g_{col}")
        rows.append((col, len(pix), C[order], share[order], [old[m] for m in members if m in old]))
        print(f"{col:7s} {len(pix):3d} items: " + "  ".join(
            f"L{c[0]:.0f} C{np.hypot(c[1], c[2]):.0f} h{np.degrees(np.arctan2(c[2], c[1])) % 360:.0f} ({s:.0%})"
            for c, s in zip(C[order], share[order])))

    W, H = 1100, 70
    sheet = Image.new("RGB", (W, len(rows) * (H + 30) + 40), (28, 28, 32))
    d = ImageDraw.Draw(sheet)
    d.text((10, 8), "in-game shades (width = share)  |  old texture-derived swatches", fill=(230, 230, 230))
    for i, (col, n, C, share, olds) in enumerate(rows):
        y = 34 + i * (H + 30)
        d.text((10, y), f"{col} ({n} items)", fill=(230, 230, 230))
        x = 120
        for c, s in zip(C, share):
            w = max(8, int(s * 600))
            r, g, b = lab_to_rgb01(*c)
            d.rectangle([x, y, x + w - 2, y + H], fill=(int(r * 255), int(g * 255), int(b * 255)))
            d.text((x + 3, y + H + 2), f"L{c[0]:.0f}", fill=(170, 170, 170))
            x += w
        x = 780
        for p in olds:
            r, g, b = lab_to_rgb01(*p["lab"])
            d.rectangle([x, y, x + 70, y + H], fill=(int(r * 255), int(g * 255), int(b * 255)))
            d.text((x + 3, y + H + 2), p["name"][:10], fill=(170, 170, 170))
            x += 78
    args.out.parent.mkdir(exist_ok=True)
    sheet.save(args.out)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
