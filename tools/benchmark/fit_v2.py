"""Fit match_v2's palette to the eye-judged labels -- TUNING HALF ONLY.

1. Swatches, chosen to SEPARATE. Candidates for a chromatic colour are the
   coloured texture clusters of the items judged clearly that colour; for
   black / gray / white, grey tones every 2 L*. Swatches are added greedily,
   each time the candidate that most improves how well the colour's clear
   items are told apart from its clear non-items, up to MAX_K, and only
   while it helps by MIN_GAIN. (Placing swatches at each item's largest
   coloured cluster instead put a "purple" on gold trim and a "gold" on
   brown leather: an item's biggest patch is often not its named colour.)
2. Cutoffs maximise F1 of returned vs clear items. F1, not wrong + missed:
   where a colour separates poorly, wrong + missed is lowest by returning
   everything, which is useless to a player.
3. neutral_k, how hard an item's coloured share pushes it out of the greys,
   is chosen the same way, over all three grey tones at once.

    python benchmark/fit_v2.py            # writes ../palette_v2.json
"""
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import match_eval as me  # noqa: E402
import match_v2 as mv  # noqa: E402
import naming_compare as nc  # noqa: E402

NEUTRALS = ("black", "gray", "white")
MAX_K = int(__import__("os").environ.get("FIT_MAX_K", 3))
MIN_GAIN = 0.02
NK_GRID = (0.0, 0.5, 0.75, 1.0, 1.5, 2.0)


def judged(labels, col):
    """vid -> True (clear yes) / False (clear no); unsure left out."""
    return {v: col in l["yes"] for v, l in labels.items() if col in l["yes"] or col not in l["unsure"]}


def f1_at(raw, truth, t):
    ret = raw >= t
    tp = (ret & truth).sum()
    if tp == 0:
        return 0.0, 1.0, 1.0
    prec, rec = tp / ret.sum(), tp / truth.sum()
    return 2 * prec * rec / (prec + rec), 1 - prec, 1 - rec


def best_cutoff(raw, truth):
    cands = np.unique(raw[truth])
    cands = cands[cands > 0]
    if not len(cands):
        return 1.0, (0.0, 1.0, 1.0)
    t = max(cands, key=lambda t: f1_at(raw, truth, t)[0])
    return float(t), f1_at(raw, truth, t)


def candidate_matrix(cls, cands, nk):
    """raw score of every judged item (rows) against every candidate (cols)."""
    out = np.zeros((len(cls), len(cands)))
    for i, cl in enumerate(cls):
        for j, c in enumerate(cands):
            out[i, j] = mv.raw_score(cl, c, nk)
    return out


def greedy(S, truth):
    chosen, cur, best_f = [], np.zeros(len(truth)), 0.0
    for _ in range(MAX_K):
        gains = [best_cutoff(np.maximum(cur, S[:, j]), truth)[1][0] for j in range(S.shape[1])]
        j = int(np.argmax(gains))
        if gains[j] < best_f + MIN_GAIN:
            break
        chosen.append(j)
        cur = np.maximum(cur, S[:, j])
        best_f = gains[j]
    return chosen, cur


def fit_colour(col, labels, clusters, nk):
    J = judged(labels, col)
    vids = list(J)
    truth = np.array([J[v] for v in vids])
    if col in NEUTRALS:
        cands = [np.array([L, 0.0, 0.0]) for L in range(10, 92, 2)]
    else:
        cands = []
        for v in vids:
            if J[v]:
                cl = clusters[v]
                cands += [cl.lab[i] for i in range(len(cl.w)) if cl.m[i] > 0.5 and cl.w[i] >= 0.1]
    S = candidate_matrix([clusters[v] for v in vids], cands, nk)
    chosen, cur = greedy(S, truth)
    t, (f, wrong, missed) = best_cutoff(cur, truth)
    return [cands[j] for j in chosen], t, f, wrong, missed


def fold_of(vid):
    """A second split inside the tuning half, for honest estimates without
    touching the holdout: fit on one fold, score on the other."""
    import hashlib
    return int(hashlib.sha1(f"fold{vid}".encode()).hexdigest(), 16) % 2


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--fold", type=int, choices=(0, 1), help="fit on this fold only")
    ap.add_argument("--out", default=str(HERE.parent / "palette_v2.json"))
    args = ap.parse_args()
    spec = json.loads((HERE / "labels.json").read_text())
    colours = spec["colours"]
    labels = {int(v): l for v, l in spec["labels"].items() if not l["holdout"]
              and (args.fold is None or fold_of(int(v)) == args.fold)}
    data = nc.parse()
    clusters = {v: mv.Clusters(data[v]) for v in labels}

    nk = max(NK_GRID, key=lambda k: sum(fit_colour(c, labels, clusters, k)[2] for c in NEUTRALS))
    print(f"neutral_k = {nk}")
    sw = []
    for col in colours:
        protos, t, f, wrong, missed = fit_colour(col, labels, clusters, nk)
        desc = []
        for j, p in enumerate(protos):
            sw.append({"name": f"{col}{j + 1}", "group": col, "lab": [round(float(x), 2) for x in p],
                       "min_score": round(t, 4)})
            desc.append(f"L{p[0]:.0f} C{np.hypot(p[1], p[2]):.0f} h{np.degrees(np.arctan2(p[2], p[1])) % 360:.0f}")
        print(f"{col:7s} F1 {f:.2f}  wrong {wrong:.0%} missed {missed:.0%}  cutoff {t:.3f}  swatches: " + ", ".join(desc))
    Path(args.out).write_text(json.dumps({"neutral_k": nk, "swatches": sw}, indent=1))


if __name__ == "__main__":
    main()
