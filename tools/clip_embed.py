"""CLIP image embeddings for every tile journal_tiles.py wrote.

Runs in the ML venv (torch + open_clip), not the tools' Python:

    %USERPROFILE%\\.venvs\\transmog-ml\\Scripts\\python clip_embed.py [--tiles DIR]

Uses the on-black version of each tile (<visualID>_k.png), which is what the
CLIP test on Transmogrifier tiles measured. Writes clip_<model>.npz next to the
tiles -- {vids, emb (unit vectors)} -- and resumes from it, so it can be
stopped and restarted.
"""
import argparse
import os
from pathlib import Path

import numpy as np
import open_clip
import torch
from PIL import Image

DEFAULT_TILES = Path(os.environ.get("LOCALAPPDATA", ".")) / "TransmogPalette" / "journal_tiles"
MODEL, PRETRAINED = "ViT-L-14", "laion2b_s32b_b82k"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiles", type=Path, default=DEFAULT_TILES)
    ap.add_argument("--batch", type=int, default=32)
    args = ap.parse_args()
    out = args.tiles / f"clip_{MODEL}.npz"
    torch.set_num_threads(os.cpu_count())
    model, _, pre = open_clip.create_model_and_transforms(MODEL, pretrained=PRETRAINED)
    model.eval()

    vids = sorted(int(p.stem[:-2]) for p in args.tiles.glob("*_k.png"))
    done_v, done_e = [], []
    if out.exists():
        d = np.load(out)
        done_v, done_e = list(d["vids"]), list(d["emb"])
    todo = [v for v in vids if v not in set(done_v)]
    print(f"{len(vids)} tiles, {len(done_v)} already embedded, {len(todo)} to go")
    with torch.no_grad():
        for i in range(0, len(todo), args.batch):
            chunk = todo[i:i + args.batch]
            x = torch.stack([pre(Image.open(args.tiles / f"{v}_k.png").convert("RGB")) for v in chunk])
            e = model.encode_image(x)
            e = (e / e.norm(dim=-1, keepdim=True)).numpy()
            done_v += chunk
            done_e += list(e)
            if (i // args.batch) % 40 == 0 or i + args.batch >= len(todo):
                np.savez(out, vids=np.array(done_v), emb=np.array(done_e, dtype=np.float32))
                print(f"  {len(done_v)}/{len(vids)}", flush=True)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
