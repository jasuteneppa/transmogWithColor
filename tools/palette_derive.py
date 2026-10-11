"""Derive the swatch palette from the game's own colours.

The broad strip's swatches were chosen as textbook hues for the old hue-slice
classifier. Under closeness matching (match_eval.py) a swatch IS the query, so
a swatch that sits where WoW has little armour returns the nearest thing it can
find: the old "orange" returned gold, the old "purple" returned magenta.

So the swatches are taken from the data: every texture cluster of every
appearance, moved to on-screen brightness by the measured calibration, grouped
by weighted k-means in the same distance match_eval scores with (lightness
counting half). The group centres are colours WoW actually uses, in the
proportions it uses them.

Neutrals and chromatic colours are grouped separately -- greys differ only in
lightness, and in one pool the far more numerous chromatic clusters would take
every centre.

    python palette_derive.py                # palette + review sheet
    python palette_derive.py --k 18
"""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import capture_calibrate as cc
import match_eval as me
import naming_compare as nc

RESEARCH = Path(__file__).resolve().parent.parent / "research"
NEUTRAL_CHROMA = 10.0   # calibrated C* below this is a grey tone


def all_clusters(data):
    hsv, w, vid = [], [], []
    for v, ranks in data.items():
        for c in ranks:
            hsv.append(c[:3]); w.append(c[3]); vid.append(v)
    lab = cc.calibrated_lab(hsv, *me.FIT)
    return lab, np.array(w), np.array(vid)


def kmeans(x, w, k, iters=60, seed=0):
    """Weighted Lloyd's with k-means++ seeding. x is already in the scaled
    space (lightness halved), so plain Euclidean is the match distance."""
    rng = np.random.default_rng(seed)
    centers = [x[rng.choice(len(x), p=w / w.sum())]]
    for _ in range(k - 1):
        d2 = np.min(((x[:, None, :] - np.array(centers)[None]) ** 2).sum(-1), axis=1)
        p = w * d2
        centers.append(x[rng.choice(len(x), p=p / p.sum())])
    c = np.array(centers)
    for _ in range(iters):
        lab = np.argmin(((x[:, None, :] - c[None]) ** 2).sum(-1), axis=1)
        new = np.array([np.average(x[lab == j], axis=0, weights=w[lab == j])
                        if (lab == j).any() else c[j] for j in range(k)])
        if np.allclose(new, c, atol=1e-3):
            break
        c = new
    return c


def to_scaled(lab):
    return np.column_stack([lab[:, 0] * me.K_L, lab[:, 1], lab[:, 2]])


def from_scaled(s):
    return np.column_stack([s[:, 0] / me.K_L, s[:, 1], s[:, 2]])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=16, help="chromatic swatches")
    ap.add_argument("--neutrals", type=int, default=4)
    ap.add_argument("--balance", type=float, default=0.7, help="hue balancing power, 0..1")
    ap.add_argument("--name", default=None, help="output name (default palette-k<K>)")
    args = ap.parse_args()

    data = nc.parse()
    lab, w, _ = all_clusters(data)
    chroma = np.hypot(lab[:, 1], lab[:, 2])
    neu = chroma < NEUTRAL_CHROMA

    # Subsample for speed; weights carry the proportions.
    rng = np.random.default_rng(1)
    def sample(mask, n=40000):
        idx = np.where(mask)[0]
        return idx if len(idx) <= n else rng.choice(idx, n, replace=False)
    ci, ni = sample(~neu), sample(neu)
    # Hue balancing. WoW is overwhelmingly brown and grey, so plain weighting
    # spends every extra centre on another brown and never one on pink. Each
    # cluster's weight is divided by its hue bin's total mass to a power:
    # 0 is plain k-means, 1 gives every hue equal say.
    hue = np.degrees(np.arctan2(lab[ci, 2], lab[ci, 1])) % 360
    bins = (hue // (360 / 24)).astype(int)
    mass = np.bincount(bins, weights=w[ci], minlength=24)
    wc = w[ci] / np.maximum(mass[bins], 1e-9) ** args.balance
    chrom_c = from_scaled(kmeans(to_scaled(lab[ci]), wc, args.k))

    # Gap filling. Even balanced, k-means can leave a whole hue without a
    # swatch when the hue is rare (pink, in WoW). Any 30-degree sector holding
    # a real share of the game's colour but with no centre within 20 degrees
    # gets one: its typical VIVID member -- median hue, and the 75th
    # percentile of chroma and lightness, i.e. the clearest common version.
    centre_hue = np.degrees(np.arctan2(chrom_c[:, 2], chrom_c[:, 1])) % 360
    total = w[ci].sum()
    extra = []
    for lo in range(0, 360, 30):
        inside = (hue >= lo) & (hue < lo + 30)
        share = w[ci][inside].sum() / total
        mid = lo + 15
        gap = np.min(np.abs((centre_hue - mid + 180) % 360 - 180))
        if share >= 0.003 and gap > 20:
            sl = lab[ci][inside]
            c = np.hypot(sl[:, 1], sl[:, 2])
            h = np.radians(np.median(hue[inside]))
            cc_ = np.percentile(c, 75)
            extra.append([np.percentile(sl[:, 0], 75), cc_ * np.cos(h), cc_ * np.sin(h)])
            print(f"  gap filled at hue {lo}-{lo + 30} ({share:.1%} of colour)")
    if extra:
        chrom_c = np.vstack([chrom_c, extra])

    # Greys at fixed lightness. WoW's grey surfaces are mostly dark, so
    # percentiles bunched three tones into L 22-38. These are the on-screen
    # lightness of a black, dark grey, light grey and white surface; nothing
    # rendered sits below ~16 after calibration, so black is not 0.
    neut_c = np.array([[L, 0.0, 0.0] for L in (20.0, 36.0, 60.0, 88.0)][:args.neutrals])
    palette = np.vstack([neut_c[np.argsort(neut_c[:, 0])],
                         chrom_c[np.argsort(np.degrees(np.arctan2(chrom_c[:, 2], chrom_c[:, 1])) % 360)]])

    # How many appearances each swatch would return near the top: items whose
    # score against it is at least half its best item's.
    scores = np.array([[me.texture_score(r, p) for p in palette] for r in data.values()])
    strong = (scores >= 0.5 * scores.max(axis=0)).sum(axis=0)

    # Review sheet: swatch, then its top captured items.
    pages = cc.load_pages()
    tiles, bare = cc.load_tiles(pages, set(data))
    cc.item_masks(tiles, bare)
    # Head tiles carry some of the character's face; and a tile with almost
    # no visible item (a piece hidden under the silhouette) cannot be judged
    # on a sheet -- it showed up in review as an empty panel.
    tiles = [t for t in tiles if t["slot"] != 0 and t["mask"].mean() >= 0.04]
    tile_scores = np.array([[me.texture_score(data[t["vid"]], p) for p in palette] for t in tiles])

    n_show, tw, th = 10, 70, 95
    sheet = Image.new("RGB", (150 + n_show * (tw + 3), len(palette) * (th + 4)), (25, 25, 30))
    d = ImageDraw.Draw(sheet)
    out = []
    for j, p in enumerate(palette):
        y = j * (th + 4)
        hexc = me_hex(p)
        d.rectangle([4, y + 4, 64, y + th - 4], fill=hexc)
        d.text((70, y + 8), f"#{j + 1}", fill=(255, 255, 255))
        d.text((70, y + 24), hexc, fill=(200, 200, 200))
        d.text((70, y + 40), f"L{p[0]:.0f} C{np.hypot(p[1], p[2]):.0f}", fill=(160, 160, 170))
        d.text((70, y + 56), f"{strong[j]} items", fill=(160, 160, 170))
        for k, i in enumerate(np.argsort(-tile_scores[:, j])[:n_show]):
            im = Image.fromarray((tiles[i]["rgb"] * 255).astype(np.uint8)).resize((tw, th))
            sheet.paste(im, (150 + k * (tw + 3), y))
        out.append({"index": j + 1, "lab": [round(float(v), 2) for v in p], "hex": hexc,
                    "strong_items": int(strong[j])})
    RESEARCH.mkdir(exist_ok=True)
    name = args.name or f"palette-k{args.k}"
    sheet_path = RESEARCH / f"{name}.png"
    sheet.save(sheet_path)
    (RESEARCH / f"{name}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"{len(palette)} swatches -> {sheet_path}")
    for s in out:
        print(f"  #{s['index']:2d} {s['hex']}  L{s['lab'][0]:5.1f}  {s['strong_items']:6d} items")


def me_hex(lab):
    import review_page
    return review_page._hex(lab)


if __name__ == "__main__":
    main()
