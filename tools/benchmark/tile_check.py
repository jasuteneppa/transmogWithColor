"""How right are the two colour swatches drawn on each appearance tile?

Matching.lua ns.TopSwatches draws the colour with the best score (score =
logit minus that colour's cutoff, so scores compare across colours) and, when
its score is at least 0.5 (logit within 0.5 of the cutoff), the runner-up.
This re-creates that from held-out predictions on the tuning half (the same
2-fold CV and model as journal_eval.py CLIP+hist+slot, F1 cutoffs), and
counts against the eye-judged labels:

  first swatch: a yes colour / unsure / a no colour
  second swatch, when shown: same
  items with a yes colour neither swatch shows

    python benchmark/tile_check.py
"""
import json
import os
from pathlib import Path

import numpy as np

from journal_eval import Eval, f1, pca

HERE = Path(__file__).resolve().parent
TILES = Path(os.environ.get("LOCALAPPDATA", ".")) / "TransmogPalette" / "journal_tiles"
SECOND_MIN = -0.5   # ScoreFor >= 0.5  <=>  logit - cutoff >= -0.5


def main():
    spec = json.loads((HERE / "labels.json").read_text())
    cols = spec["colours"]
    labels = {int(v): l for v, l in spec["labels"].items() if not l["holdout"]}
    cl = np.load(TILES / "clip_ViT-L-14.npz")
    hs = np.load(TILES / "hist.npz")
    T = np.load(TILES / "text_L14.npy")
    ci = {int(v): i for i, v in enumerate(cl["vids"])}
    hi = {int(v): i for i, v in enumerate(hs["vids"])}
    vids = [v for v in labels if v in ci and v in hi]
    ev = Eval(vids, labels, cols)
    E = cl["emb"][[ci[v] for v in vids]]
    H = hs["hist"][[hi[v] for v in vids]]
    slot = np.eye(13)[hs["slot"][[hi[v] for v in vids]]]
    zs = E @ T.T
    zs -= zs.mean(1, keepdims=True)
    F = np.hstack([zs * 50, pca(E), np.sqrt(H) * 3, slot, np.ones((len(vids), 1))])
    out = ev.scores(F=F)

    adj = np.zeros((len(vids), len(cols)))
    for j, c in enumerate(cols):
        test_s, train_s = out[c]
        for a in (0, 1):
            s, y, _ = train_s[a]
            t = max(np.unique(s), key=lambda t: f1(s, y, t))
            te = ev.fold != a
            adj[te, j] = test_s[te] - t

    def verdict(v, c):
        l = labels[v]
        return "yes" if c in l["yes"] else "unsure" if c in l["unsure"] else "no"

    first = {"yes": 0, "unsure": 0, "no": 0}
    second = {"yes": 0, "unsure": 0, "no": 0}
    unshown, coloured, nomatch = 0, 0, 0
    nm_first = {"yes": 0, "unsure": 0, "no": 0}   # closest colour of items matching none
    nm_clear = 0                                    # ... of which labelled with a clear colour
    wrong_first = []
    for i, v in enumerate(vids):
        order = np.argsort(-adj[i])
        a, b = cols[order[0]], cols[order[1]]
        first[verdict(v, a)] += 1
        if verdict(v, a) == "no":
            wrong_first.append((v, a, labels[v]["yes"]))
        shown = {a}
        if adj[i, order[1]] >= SECOND_MIN:
            second[verdict(v, b)] += 1
            shown.add(b)
        if labels[v]["yes"]:
            coloured += 1
            unshown += not (set(labels[v]["yes"]) & shown)
        if (adj[i] < 0).all():
            nomatch += 1
            nm_first[verdict(v, a)] += 1
            nm_clear += bool(labels[v]["yes"])

    n = len(vids)
    print(f"{n} labelled tuning items, each scored by a model that never saw it\n")
    print("first swatch:  " + "  ".join(f"{k} {first[k]} ({first[k] / n:.0%})" for k in first))
    m = sum(second.values())
    print(f"second swatch shown on {m} ({m / n:.0%}):  "
          + "  ".join(f"{k} {second[k]} ({second[k] / max(m, 1):.0%})" for k in second))
    print(f"items with a clear colour that neither swatch shows: {unshown} of {coloured} ({unshown / coloured:.0%})")
    print(f"items matching no colour at all (every score under its cutoff): {nomatch} ({nomatch / n:.0%}), "
          f"{nm_clear} of them labelled with a clear colour")
    print("  their closest colour:  " + "  ".join(f"{k} {nm_first[k]} ({nm_first[k] / max(nomatch, 1):.0%})"
                                                 for k in nm_first))
    print("\nfirst swatch judged wrong (vid, swatch, labelled yes):")
    for w in wrong_first:
        print("  ", *w)


if __name__ == "__main__":
    main()
