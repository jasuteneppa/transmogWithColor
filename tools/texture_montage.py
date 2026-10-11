"""One image per appearance built from its texture FILES, for colour naming
where no in-game picture exists (appearances the journal cannot show, new
items before a capture).

Each appearance's diffuse textures -- body textures plus an attached 3D
piece's (generate_color_data.resolve_texture_fdids / resolve_attachment) --
are alpha-composited on black and packed into a 2x2 grid (up to 4 textures,
largest first), 448 x 448. Written to <out>/<visualID>_k.png so clip_embed.py
can read them like journal tiles.

    python texture_montage.py --labelled      # only the judged appearances
    python texture_montage.py                 # every appearance (slow)
"""
import argparse
import json
import os
from pathlib import Path

import requests
from PIL import Image

import generate_color_data as g

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = Path(os.environ.get("LOCALAPPDATA", ".")) / "TransmogPalette" / "texture_tiles"
CELL = 224


def montage(fdids, sess):
    ims = []
    for f in fdids:
        try:
            im = g.fetch_texture(f, sess).convert("RGBA")
        except Exception:  # noqa: BLE001 - a missing texture just leaves its cell empty
            continue
        bg = Image.new("RGBA", im.size, (0, 0, 0, 255))
        bg.alpha_composite(im)
        ims.append(bg.convert("RGB"))
    if not ims:
        return None
    ims.sort(key=lambda im: -im.width * im.height)
    out = Image.new("RGB", (2 * CELL, 2 * CELL), (0, 0, 0))
    for i, im in enumerate(ims[:4]):
        im.thumbnail((CELL, CELL))
        out.paste(im, ((i % 2) * CELL + (CELL - im.width) // 2, (i // 2) * CELL + (CELL - im.height) // 2))
    if len(ims) == 1:   # a single texture fills the whole image
        out = ims[0].resize((2 * CELL, 2 * CELL))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--labelled", action="store_true", help="only appearances in benchmark/labels.json")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    sess = requests.Session()
    ia, di, mr, tb = g.build_lookup_tables(sess)
    mbd = g.load_model_files()
    if args.labelled:
        vids = sorted(int(v) for v in json.loads((HERE / "benchmark" / "labels.json").read_text())["labels"])
    else:
        vids = sorted(ia)
    made = 0
    for v in vids:
        if (args.out / f"{v}_k.png").exists():
            continue
        fd = g.resolve_texture_fdids(v, ia, di, mr, tb) + g.resolve_attachment(v, ia, di, mr, tb, mbd)[0]
        im = montage(list(dict.fromkeys(fd)), sess)
        if im is not None:
            im.save(args.out / f"{v}_k.png")
            made += 1
    print(f"{made} texture images written to {args.out}")


if __name__ == "__main__":
    main()
