"""How light is an appearance IN EACH OF ITS COLOURS, on screen? For the
"More" row: every general colour split into a light and a dark half.

The item's pixels (journal_tiles.item_mask: no backdrop, fringe or bare
silhouette) are sorted into the 11 colours: grey pixels (C*/(L*+20) < 0.12)
into black / gray / white by lightness; coloured pixels to the nearest
chromatic colour centre. The centres are the median on-screen colour of the
coloured pixels of tuning-half items judged clearly that colour and nothing
else. An appearance's lightness in colour X is the median L* of its X pixels
(none -> no value). Writes <tiles>/lightness.npz {vids, L (n, 11), centres}.

    python light_dark.py
    python light_dark.py --sheet out.png      # light vs dark examples
"""
import argparse
import json
import os
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import color_naming as cn
from journal_tiles import item_mask, bare_references, TILE_SIZE

HERE = Path(__file__).resolve().parent
TILES = Path(os.environ.get("LOCALAPPDATA", ".")) / "TransmogPalette" / "journal_tiles"
NEUTRAL = ("black", "gray", "white")
GREY_S = 0.12
BLACK_L, WHITE_L = 25, 70   # grey pixels darker than this are black, lighter are white


def pixels(vid, index, refs):
    a = np.asarray(Image.open(TILES / f"{vid}.png").convert("RGB").resize(TILE_SIZE, Image.NEAREST))
    px = a[item_mask(a, refs.get(index[vid]["slot"]))] / 255.0
    return cn.srgb_to_lab(px) if len(px) else np.zeros((0, 3))


def assign(lab, colours, centres):
    """index into colours for every pixel"""
    L = lab[:, 0]
    s = np.hypot(lab[:, 1], lab[:, 2]) / (L + 20)
    chrom = [c for c in colours if c not in NEUTRAL]
    C = np.array([centres[c] for c in chrom])
    d = ((0.5 * (lab[:, None, 0] - C[None, :, 0])) ** 2 + ((lab[:, None, 1:] - C[None, :, 1:]) ** 2).sum(-1))
    out = np.array([colours.index(chrom[j]) for j in np.argmin(d, 1)]) if len(lab) else np.zeros(0, int)
    grey = s < GREY_S
    out[grey & (L < BLACK_L)] = colours.index("black")
    out[grey & (L >= BLACK_L) & (L <= WHITE_L)] = colours.index("gray")
    out[grey & (L > WHITE_L)] = colours.index("white")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", type=Path)
    args = ap.parse_args()
    spec = json.loads((HERE / "benchmark" / "labels.json").read_text())
    colours = spec["colours"]
    labels = {int(v): l for v, l in spec["labels"].items() if not l["holdout"]}
    index = {int(k): v for k, v in json.loads((TILES / "index.json").read_text()).items()}
    refs = bare_references(TILES, index)
    out_path = TILES / "lightness.npz"

    if not out_path.exists():
        centres = {}
        for c in colours:
            if c in NEUTRAL:
                continue
            pts = []
            for v, l in labels.items():
                if l["yes"] == [c] and v in index:
                    lab = pixels(v, index, refs)
                    lab = lab[np.hypot(lab[:, 1], lab[:, 2]) / (lab[:, 0] + 20) >= GREY_S]
                    if len(lab) >= 30:
                        pts.append(np.median(lab, 0))
            centres[c] = np.median(pts, 0)
            print(f"  centre {c:7s} L{centres[c][0]:.0f} a{centres[c][1]:.0f} b{centres[c][2]:.0f} ({len(pts)} items)")
        vids = sorted(index)
        Lmat = np.full((len(vids), len(colours)), np.nan, np.float32)
        for i, v in enumerate(vids):
            lab = pixels(v, index, refs)
            if len(lab) < 20:
                continue
            a = assign(lab, colours, centres)
            for j in range(len(colours)):
                sel = a == j
                if sel.sum() >= 15:
                    Lmat[i, j] = np.median(lab[sel, 0])
            if i % 5000 == 0:
                print(f"  {i}/{len(vids)}", flush=True)
        np.savez(out_path, vids=np.array(vids), L=Lmat, centres=np.array([centres.get(c, [0, 0, 0]) for c in colours]))
        print(f"wrote {out_path}")

    if args.sheet:
        d = np.load(out_path)
        vids, Lmat = d["vids"], d["L"]
        txt = (HERE.parent / "TransmogPalette" / "ColorScores.lua").read_text(encoding="utf-8")
        sc = {int(m.group(1)): [int(b) for b in re.findall(r"\\(\d{3})", m.group(2))]
              for m in re.finditer(r'\[(\d+)\] = "((?:\\\d{3})+)"', txt)}
        rng = np.random.default_rng(2)
        show = ["red", "blue", "green", "purple", "gold", "gray"]
        T, n = 70, 8
        sheet = Image.new("RGB", (2 * n * (T + 4) + 40, len(show) * (int(T * 1.33) + 22) + 30), (28, 28, 32))
        dr = ImageDraw.Draw(sheet)
        dr.text((10, 6), "DARK half  |  LIGHT half   (random items matched to the colour)", fill=(230, 230, 230))
        for r, c in enumerate(show):
            j = colours.index(c)
            m = [(int(v), Lmat[i, j]) for i, v in enumerate(vids)
                 if int(v) in sc and sc[int(v)][j] >= 128 and not np.isnan(Lmat[i, j])]
            thr = np.median([x for _, x in m])
            dark = [v for v, x in m if x < thr]
            light = [v for v, x in m if x >= thr]
            y = 26 + r * (int(T * 1.33) + 22)
            dr.text((4, y + int(T * 1.33) + 4), f"{c}: split at L{thr:.0f} ({len(m)} items)", fill=(200, 200, 200))
            for k, v in enumerate(list(rng.choice(dark, n, replace=False)) + list(rng.choice(light, n, replace=False))):
                x = 10 + k * (T + 4) + (30 if k >= n else 0)
                sheet.paste(Image.open(TILES / f"{v}_k.png").resize((T, int(T * 1.33))), (x, y))
        sheet.save(args.sheet)
        print(f"wrote {args.sheet}")


if __name__ == "__main__":
    main()
