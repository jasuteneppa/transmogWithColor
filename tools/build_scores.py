"""Writes TransmogPalette/ColorScores.lua: a score per general colour for
every appearance captured from the journal, from the model the benchmark
measured best (benchmark/journal_eval.py: CLIP colour answers + CLIP image
components + pixel histogram + slot, one L2 logistic regression per colour).

Two ways to run it:

    python build_scores.py               TRAIN, then score: fits the model on
                                         benchmark/labels.json and saves it to
                                         color_model.npz (about 30 minutes)
    python build_scores.py --use-model   score only, with the saved model: what
                                         an update after a patch runs (minutes).
                                         Appearances already scored get the
                                         same scores as before; new ones are
                                         scored by the same model.

Training uses every label, holdout included: the one-time holdout check
(benchmark/holdout_check.py) was run on 2026-10-11 before the holdout went
into training -- results in benchmark/README.md. One exception: holdout
items were labelled under the old, narrower black / white, so they train
every colour but those two. --tuning-only trains on the tuning half alone, as
before the check.

Each colour's cutoff comes from predictions for items held out inside the
training labels (2-fold): by default the F1-best cutoff ("inclusive": an
appearance joins every colour it plausibly has, and the addon lists the
pieces MAINLY that colour first), or with --cutoff strict the loosest whose
wrong rate stays <= TARGET. A score is stored as one byte:
    128 + SCALE * (logit - cutoff), clamped to 0..255
so 128 means exactly at the cutoff, and the addon matches on >= 128.

Tiles where the item never rendered (pixel-identical to the bare body) get
no scores; neither do appearances the journal could not show. For those the
addon keeps using its closeness matching on ColorData.
"""
import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "benchmark"))
from fit_v2 import fold_of  # noqa: E402
from journal_eval import logreg, f1, wrong_rate, TARGET  # noqa: E402

TILES = Path(os.environ.get("LOCALAPPDATA", ".")) / "TransmogPalette" / "journal_tiles"
OUT = HERE.parent / "TransmogPalette" / "ColorScores.lua"
MODEL = HERE / "color_model.npz"
GROUP_KEYS = ["g_black", "g_gray", "g_white", "g_red", "g_orange", "g_brown", "g_gold", "g_green",
              "g_blue", "g_purple", "g_pink"]
SCALE = 16.0
SCALE_LD = 2000.0   # CLIP light-minus-dark similarity differences are ~0.01
LAMBDAS = (0.3, 1, 3, 10)
PCA_K = 128
OLD_HOLDOUT_DEFINITION = ("black", "white")   # holdout labels predate the broader definition


BARE_CACHE = TILES / "bare_check.npz"


def _small(v):
    return np.asarray(Image.open(TILES / f"{v}_k.png").convert("RGB").resize((48, 64), Image.BILINEAR)).astype(np.int16)


def _near(X, ref):
    return (np.abs(X - ref).max(-1) > 12).mean((-2, -1)) < 0.01


def bare_tiles(index):
    """visualIDs whose tile is pixel-identical to the bare body: per slot, the
    most duplicated tile is the bare one (a real item, however small, changes
    hundreds of pixels), and anything within 1% of its pixels matches it.

    Reading every tile takes ~10 minutes, so the result is cached in
    bare_check.npz with each slot's bare tile: later runs (an update) only
    compare the NEW tiles against those."""
    if BARE_CACHE.exists():
        c = np.load(BARE_CACHE)
        checked, bare = set(int(v) for v in c["checked"]), set(int(v) for v in c["bare"])
        refs = {str(s): r for s, r in zip(c["ref_slots"], c["refs"])}
        new = [v for v in index if v not in checked]
        for v in new:
            ref = refs.get(index[v]["slot"])
            if ref is not None and _near(_small(v), ref):
                bare.add(v)
        # New tiles identical to each other are bare too: two appearances never
        # look the same, but a model that never rendered leaves the same empty
        # body every time -- even when the framing has moved off the saved
        # reference (12.1.5: three shoulders, 17.5% off it, all identical).
        by_slot = {}
        for v in new:
            by_slot.setdefault(index[v]["slot"], []).append(v)
        for vs in by_slot.values():
            if len(vs) >= 2:
                X = np.stack([_small(v) for v in vs])
                for i, v in enumerate(vs):
                    if _near(X, X[i]).sum() >= 2:
                        bare.add(v)
        print(f"bare-tile check: {len(new)} new tiles checked ({len(checked)} from the cache)")
    else:
        bare, refs = set(), {}
        for slot in sorted({i["slot"] for i in index.values()}):
            vs = [v for v in index if index[v]["slot"] == slot]
            X = np.stack([_small(v) for v in vs])
            rng = np.random.default_rng(0)
            cand = rng.choice(len(vs), min(300, len(vs)), replace=False)
            best = max(cand, key=lambda i: _near(X, X[i]).sum())
            hits = _near(X, X[best])
            if hits.sum() >= 2:
                bare.update(vs[i] for i in np.where(hits)[0])
                refs[slot] = X[best]
    ref_slots = sorted(refs)
    np.savez(BARE_CACHE, checked=np.array(sorted(index)), bare=np.array(sorted(bare)),
             ref_slots=np.array(ref_slots), refs=np.array([refs[s] for s in ref_slots]))
    return bare


def load_inputs():
    """Every appearance with a usable journal tile, and its raw inputs."""
    index = {int(k): v for k, v in json.loads((TILES / "index.json").read_text()).items()}
    cl = np.load(TILES / "clip_ViT-L-14.npz")
    hs = np.load(TILES / "hist.npz")
    ci = {int(v): i for i, v in enumerate(cl["vids"])}
    hi = {int(v): i for i, v in enumerate(hs["vids"])}
    missing = [v for v in index if v not in ci or v not in hi]
    if missing:
        sys.exit(f"ERROR: {len(missing)} tiles have no CLIP embedding or histogram yet -- "
                 "run clip_embed.py and journal_features.py first.")
    bare = bare_tiles(index)
    vids = [v for v in index if v not in bare]
    print(f"{len(vids)} appearances to score ({len(bare)} bare tiles left out)")
    E = cl["emb"][[ci[v] for v in vids]]
    H = hs["hist"][[hi[v] for v in vids]]
    slot_ix = hs["slot"][[hi[v] for v in vids]]
    return index, vids, E, H, slot_ix


def features(E, H, slot_ix, T, pca_mean, pca_basis, pca_sv0):
    zs = E @ T.T
    zs -= zs.mean(1, keepdims=True)
    P = (E - pca_mean) @ pca_basis.T / pca_sv0 * 30
    slot = np.eye(13)[slot_ix]
    return np.hstack([zs * 50, P, np.sqrt(H) * 3, slot, np.ones((len(E), 1))])


def train(args, vids, E, H, slot_ix, T, colours):
    spec = json.loads((HERE / "benchmark" / "labels.json").read_text())
    labels = {int(v): l for v, l in spec["labels"].items() if not (args.tuning_only and l["holdout"])}
    # The image-component basis is fixed here and saved, so an update scores
    # new tiles in the same space the weights were fitted in.
    pca_mean = E.mean(0)
    _, sv, Vt = np.linalg.svd(E - pca_mean, full_matrices=False)
    pca_basis, pca_sv0 = Vt[:PCA_K], sv[0]
    F = features(E, H, slot_ix, T, pca_mean, pca_basis, pca_sv0)

    pos = {v: i for i, v in enumerate(vids)}
    tv = [v for v in labels if v in pos]
    Ft = F[[pos[v] for v in tv]]
    inner = np.array([fold_of(v) for v in tv])
    print(f"training on {len(tv)} labelled appearances"
          + (" (tuning half only)" if args.tuning_only else " (tuning + holdout)"))
    W = np.zeros((len(colours), F.shape[1]))
    cuts = np.zeros(len(colours))
    for j, c in enumerate(colours):
        y = np.array([c in labels[v]["yes"] for v in tv])
        no = np.array([c not in labels[v]["yes"] and c not in labels[v]["unsure"] for v in tv])
        if c in OLD_HOLDOUT_DEFINITION:
            old = np.array([labels[v]["holdout"] for v in tv])
            y, no = y & ~old, no & ~old
        judged = y | no
        yt = y.astype(float)
        best = None
        for lam in LAMBDAS:
            held = np.zeros(len(tv))
            for b in (0, 1):
                fit, pred = judged & (inner != b), inner == b
                held[pred] = Ft[pred] @ logreg(Ft[fit], yt[fit], lam)
            hs_, hy, hn = held[judged], y[judged], no[judged]
            t = max(np.unique(hs_), key=lambda t: f1(hs_, hy, t))
            if best is None or f1(hs_, hy, t) > best[0]:
                best = (f1(hs_, hy, t), lam, hs_, hy, hn)
        _, lam, hs_, hy, hn = best
        if args.cutoff == "strict":
            ok = [t for t in np.unique(hs_) if wrong_rate(hs_, hy, hn, t) <= TARGET and (hs_ >= t).sum() >= 3]
            cut = min(ok) if ok else np.inf
        else:   # inclusive: the F1-best cutoff -- an item joins every colour it plausibly has
            cut = max(np.unique(hs_), key=lambda t: f1(hs_, hy, t))
        W[j] = logreg(Ft[judged], yt[judged], lam)
        cuts[j] = cut
        r = hs_ >= cut
        print(f"  {c:7s} lambda {lam:<4} held-out at cutoff: wrong {wrong_rate(hs_, hy, hn, cut):.0%} "
              f"missed {1 - (r & hy).sum() / max(hy.sum(), 1):.0%}")
    return dict(W=W, cuts=cuts, pca_mean=pca_mean, pca_basis=pca_basis, pca_sv0=pca_sv0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--use-model", action="store_true",
                    help=f"score with the saved model ({MODEL.name}) instead of training")
    ap.add_argument("--cutoff", choices=("inclusive", "strict"), default="inclusive",
                    help="when training. inclusive: F1-best per colour (the addon sorts main-colour "
                         "pieces first); strict: wrong <= TARGET")
    ap.add_argument("--tuning-only", action="store_true", help="when training: leave the holdout half out")
    args = ap.parse_args()
    colours = [k[2:] for k in GROUP_KEYS]
    T = np.load(TILES / "text_L14.npy")
    LD = np.load(TILES / "text_lightdark.npy")

    index, vids, E, H, slot_ix = load_inputs()
    if args.use_model:
        if not MODEL.exists():
            sys.exit(f"ERROR: no saved model at {MODEL} -- run build_scores.py once without --use-model.")
        m = dict(np.load(MODEL, allow_pickle=False))
        assert list(m["colours"]) == colours
        print(f"scoring with the saved model {MODEL.name}")
    else:
        m = train(args, vids, E, H, slot_ix, T, colours)

    F = features(E, H, slot_ix, T, m["pca_mean"], m["pca_basis"], m["pca_sv0"])
    B = np.zeros((len(vids), len(colours)), np.uint8)
    for j in range(len(colours)):
        if np.isfinite(m["cuts"][j]):
            B[:, j] = np.clip(np.round(128 + SCALE * (F @ m["W"][j] - m["cuts"][j])), 0, 255)
    for j, c in enumerate(colours):
        print(f"  {c:7s} matches {int((B[:, j] >= 128).sum())} appearances")

    # Light / dark (the "More" row): how much more "light X" than "dark X" CLIP
    # finds the tile (prompts in text_lightdark.npy), split at the median of
    # the appearances matching X IN THE SAME SLOT -- weapons are lit brighter
    # than armour on the body, so a split over all slots mostly split by slot.
    # The medians are saved with the model, so an update splits new tiles at
    # the same point instead of shifting every existing appearance.
    slots = np.array([index[v]["slot"] for v in vids])
    if "ld_slots" in m:
        med = {(str(s), j): m["ld_median"][i, j] for i, s in enumerate(m["ld_slots"]) for j in range(len(colours))}
    else:
        med = {}
        for j in range(len(colours)):
            val = E @ LD[j, 0] - E @ LD[j, 1]
            for s in np.unique(slots):
                sel = (slots == s) & (B[:, j] >= 128)
                med[s, j] = np.median(val[sel]) if sel.sum() >= 4 else np.median(val[slots == s])
        ld_slots = sorted(np.unique(slots))
        m["ld_slots"] = np.array(ld_slots)
        m["ld_median"] = np.array([[med[s, j] for j in range(len(colours))] for s in ld_slots])
    Lb = np.full_like(B, 128)
    for j in range(len(colours)):
        val = E @ LD[j, 0] - E @ LD[j, 1]
        for s in np.unique(slots):
            sel = slots == s
            Lb[sel, j] = np.clip(np.round(128 + SCALE_LD * (val[sel] - med[str(s), j])), 0, 255)

    if not args.use_model:
        np.savez(MODEL, colours=np.array(colours), **{k: v for k, v in m.items()})
        print(f"saved the model -> {MODEL}")

    lines = [
        "local _, ns = ...",
        "",
        "-- GENERATED by tools/build_scores.py -- do not hand-edit. A colour score per",
        "-- general colour for every appearance captured from the Collections journal,",
        "-- from a model trained on eye-judged labels (tools/benchmark). One byte per",
        "-- colour, in ns.ColorScoreGroups order: 128 is exactly at that colour's",
        "-- cutoff, higher is a stronger match. Then one byte per colour for the",
        "-- light / dark split: 128 is the middle of that colour within the",
        "-- appearance's slot, higher is lighter. Appearances not listed fall back to",
        "-- closeness matching on ColorData (Matching.lua).",
        "",
        "ns.ColorScoreGroups = { " + ", ".join(f'"{k}"' for k in GROUP_KEYS) + " }",
        f"ns.ColorScoreScale = {SCALE}",
        "",
        "local packed = {",
    ]
    for i in np.argsort(vids):
        lines.append(f'    [{vids[i]}] = "' + "".join(f"\\{b:03d}" for b in list(B[i]) + list(Lb[i])) + '",')
    lines += [
        "}",
        "",
        "-- visualID -> { score bytes..., light bytes... } in group order, decoded on",
        "-- first use: [i] is colour i's score, [n + i] its light / dark byte.",
        "ns.ColorScores = setmetatable({}, { __index = function(t, visualID)",
        "    local s = packed[visualID]",
        "    if not s then return nil end",
        "    local out = { s:byte(1, -1) }",
        "    t[visualID] = out",
        "    return out",
        "end })",
        "",
    ]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {len(vids)} appearances -> {OUT}")


if __name__ == "__main__":
    main()
