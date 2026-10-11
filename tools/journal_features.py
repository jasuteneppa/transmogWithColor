"""Pixel colour histograms for every tile journal_tiles.py wrote.

Every non-magenta pixel of a tile (the item, plus the character silhouette,
which is the same in every tile of a slot -- the model gets the slot too and
learns to discount it) is sorted into 112 colour bins: 12 hues x 3
colourfulness (C*/(L*+20)) x 3 lightness, plus 4 grey lightness bins. Writes
hist.npz next to the tiles: {vids, hist (shares), slot (index into SLOTS)}.

    python journal_features.py [--tiles DIR]
"""
import argparse
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image

import color_naming as cn
from journal_tiles import magenta_mask

DEFAULT_TILES = Path(os.environ.get("LOCALAPPDATA", ".")) / "TransmogPalette" / "journal_tiles"
SLOTS = ["HEADSLOT", "SHOULDERSLOT", "BACKSLOT", "CHESTSLOT", "SHIRTSLOT", "TABARDSLOT", "WRISTSLOT",
         "HANDSSLOT", "WAISTSLOT", "LEGSSLOT", "FEETSLOT", "MAINHANDSLOT", "SECONDARYHANDSLOT"]
NBINS = 112


def hist(lab):
    L, a, b = lab[:, 0], lab[:, 1], lab[:, 2]
    C = np.hypot(a, b)
    h = np.degrees(np.arctan2(b, a)) % 360
    s = C / (L + 20)
    chrom = s >= 0.12
    idx = np.where(chrom, (h // 30).astype(int) % 12 * 9 + np.digitize(s, [0.3, 0.5]) * 3 + np.digitize(L, [35, 60]),
                   108 + np.digitize(L, [20, 40, 65]))
    out = np.bincount(idx, minlength=NBINS).astype(np.float32)
    return out / max(out.sum(), 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiles", type=Path, default=DEFAULT_TILES)
    args = ap.parse_args()
    index = {int(k): v for k, v in json.loads((args.tiles / "index.json").read_text()).items()}
    vids = sorted(index)
    H = np.zeros((len(vids), NBINS), np.float32)
    # Tiles already measured keep their histogram (updates only add tiles).
    done = {}
    if (args.tiles / "hist.npz").exists():
        d = np.load(args.tiles / "hist.npz")
        done = {int(v): h for v, h in zip(d["vids"], d["hist"])}
    for i, v in enumerate(vids):
        if v in done:
            H[i] = done[v]
            continue
        a = np.asarray(Image.open(args.tiles / f"{v}.png").convert("RGB"))
        px = a[~magenta_mask(a)] / 255.0
        if len(px):
            H[i] = hist(cn.srgb_to_lab(px))
        if i % 5000 == 0:
            print(f"  {i}/{len(vids)}", flush=True)
    slot = np.array([SLOTS.index(index[v]["slot"]) for v in vids])
    np.savez(args.tiles / "hist.npz", vids=np.array(vids), hist=H, slot=slot)
    print(f"wrote {args.tiles / 'hist.npz'} ({len(vids)} tiles, {len(vids) - len(set(vids) & set(done))} new)")


if __name__ == "__main__":
    main()
