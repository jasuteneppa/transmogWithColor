"""Cuts every appearance captured by /tmpalette capture journal out of its
screenshot, one tile per visualID, into a folder outside the repo.

Journal pages are drawn on pure magenta (see Capture.lua, Journal), so the
item comes out with an exact mask. For each appearance this writes
    <out>/<visualID>.png        the tile as captured (magenta background)
    <out>/<visualID>_k.png      the same on black, like the Transmogrifier
                                tiles the colour work was measured on
Blank tiles (models that had not loaded) and tiles Blizzard greyed out are
skipped; when an appearance was captured more than once, the latest good
tile wins. index.json maps visualID -> {slot, class, collected}.

Appearances already in index.json (with their tile on disk) are KEPT and not
re-cut, so an update only cuts what is new -- and cleaning old screenshots
out of WoW's Screenshots folder never drops anything already captured.
--recut cuts everything again from the screenshots still on disk.

    python journal_tiles.py [--out DIR] [--recut]
"""
import argparse
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image

import capture_calibrate as cc

DEFAULT_OUT = Path(os.environ.get("LOCALAPPDATA", ".")) / "TransmogPalette" / "journal_tiles"


def magenta_mask(a):
    """True where the pixel is the magenta backdrop, at any brightness (the
    edge of a tile darkens it). Armour is never this hue with almost no green."""
    a = a.astype(np.int32)
    mx = a.max(2)
    return (a[:, :, 1] < 0.25 * mx) & (np.abs(a[:, :, 0] - a[:, :, 2]) < 0.2 * mx) & (mx > 30)


TILE_SIZE = (127, 169)   # tiles differ by a pixel between pages; compared at one size


def bare_references(tiles_dir, index):
    """slot -> the bare-body tile (H, W, 3), the most duplicated tile of the
    slot: the character with nothing on, identical every time it is drawn.
    Cached in <tiles_dir>/bare_refs.npz."""
    cache = tiles_dir / "bare_refs.npz"
    if cache.exists():
        d = np.load(cache)
        return {k: d[k] for k in d.files}
    refs = {}
    for slot in sorted({i["slot"] for i in index.values()}):
        vs = [v for v in index if index[v]["slot"] == slot]
        X = np.stack([np.asarray(Image.open(tiles_dir / f"{v}.png").convert("RGB").resize((48, 64), Image.BILINEAR))
                      .astype(np.int16) for v in vs])
        rng = np.random.default_rng(0)
        cand = rng.choice(len(vs), min(300, len(vs)), replace=False)
        best = max(cand, key=lambda i: ((np.abs(X - X[i]).max(3) > 12).mean((1, 2)) < 0.01).sum())
        refs[slot] = np.asarray(Image.open(tiles_dir / f"{vs[best]}.png").convert("RGB").resize(TILE_SIZE, Image.NEAREST))
    np.savez(cache, **refs)
    return refs


def item_mask(a, ref=None):
    """True on the ITEM's pixels: not the magenta backdrop, not its one-pixel
    blended fringe, and (given the slot's bare reference, at TILE_SIZE) not
    the uncovered silhouette, which is pixel-identical to the bare body. An
    item drawn over the body -- a black one included -- differs from it."""
    bg = magenta_mask(a)
    fringe = bg.copy()
    fringe[1:] |= bg[:-1]; fringe[:-1] |= bg[1:]
    fringe[:, 1:] |= bg[:, :-1]; fringe[:, :-1] |= bg[:, 1:]
    keep = ~fringe
    if ref is not None and ref.shape == a.shape:
        keep &= ~((np.abs(a.astype(np.int16) - ref.astype(np.int16)).max(2) <= 6) & ~magenta_mask(ref))
    return keep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--recut", action="store_true", help="re-cut appearances already in index.json")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    kept = {}
    if (args.out / "index.json").exists() and not args.recut:
        kept = {int(v): e for v, e in json.loads((args.out / "index.json").read_text()).items()
                if (args.out / f"{v}_k.png").exists()}

    pages = [(r, p) for r, p in cc.load_pages()
             if isinstance(r.get("sweep"), dict) and r["sweep"].get("journal")]
    pages.sort(key=lambda x: x[0]["time"], reverse=True)   # latest first
    index, blank, grey = {}, 0, 0
    for rec, path in pages:
        img = None
        for (vid, box), tile in zip(cc.tile_boxes(rec, Image.open(path).size), rec["tiles"]):
            if vid in index or vid in kept:
                continue
            if len(tile) > 5 and tile[5]:
                grey += 1
                continue
            img = img or Image.open(path).convert("RGB")
            crop = img.crop(box)
            a = np.asarray(crop)
            key = magenta_mask(a)
            if key.mean() > 0.97:
                blank += 1
                continue
            crop.save(args.out / f"{vid}.png")
            k = a.copy()
            k[key] = 0
            Image.fromarray(k).save(args.out / f"{vid}_k.png")
            index[vid] = {"slot": rec["sweep"]["slot"], "class": rec["sweep"]["class"],
                          "collected": bool(len(tile) > 6 and tile[6])}
    new = len(index)
    index = {**kept, **index}
    (args.out / "index.json").write_text(json.dumps(index))
    print(f"{new} new appearances cut, {len(index)} in all, in {args.out} "
          f"({blank} blank and {grey} greyed tiles skipped)")


if __name__ == "__main__":
    main()
