"""Colour naming from journal tiles, scored against the frozen labels.

Same rules as score.py: tuning half only (never the holdout), 2-fold CV with
fit_v2.fold_of, "unsure" never counted. For each method, per colour:
wrong (returned items labelled no) and missed (yes items not returned), plus
lost (clearly coloured items none of their colours return), at the cutoff
fitted inside the training fold -- and again at a cutoff per colour chosen to
keep the training fold's wrong rate <= TARGET.

Inputs (from journal_tiles.py, clip_embed.py, journal_features.py):
    <tiles>/clip_ViT-L-14.npz, <tiles>/hist.npz, <tiles>/text_L14.npy
Optional --tm: a {vids, emb} npz of the SAME items' Transmogrifier tiles,
to check journal tiles name colours as well as the tiles the labels came from.

    python benchmark/journal_eval.py [--tm emb.npz]
"""
import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from fit_v2 import fold_of  # noqa: E402

TILES = Path(os.environ.get("LOCALAPPDATA", ".")) / "TransmogPalette" / "journal_tiles"
TARGET = 0.09


def logreg(X, y, lam, it=25):
    w = np.zeros(X.shape[1])
    reg = lam * np.r_[np.ones(len(w) - 1), 0]
    for _ in range(it):
        p = 1 / (1 + np.exp(-np.clip(X @ w, -30, 30)))
        step = np.linalg.solve((X * (p * (1 - p))[:, None]).T @ X + np.diag(reg), X.T @ (p - y) + reg * w)
        w -= step
        if np.abs(step).max() < 1e-4:
            break
    return w


def f1(s, y, t):
    r = s >= t
    return 2 * (r & y).sum() / max(r.sum() + y.sum(), 1)


def wrong_rate(s, y, no, t):
    r = s >= t
    n = (r & (y | no)).sum()
    return (r & no).sum() / n if n else 0.0


class Eval:
    def __init__(self, vids, labels, colours):
        self.V = np.array(vids)
        self.lab = labels
        self.cols = colours
        self.fold = np.array([fold_of(int(v)) for v in self.V])
        self.inner = np.array([fold_of(int(v) * 7 + 3) for v in self.V])
        self.Y = {c: np.array([c in labels[v]["yes"] for v in self.V]) for c in colours}
        self.NO = {c: np.array([c not in labels[v]["yes"] and c not in labels[v]["unsure"] for v in self.V])
                   for c in colours}

    def scores(self, F=None, zs=None):
        """Held-out scores per colour (each item scored by the fold it was not
        fitted on), plus held-out training-fold scores for choosing cutoffs.
        F: features for a trained model; zs: (n, colours) zero-shot scores."""
        out = {}
        for j, c in enumerate(self.cols):
            y, no = self.Y[c], self.NO[c]
            judged = y | no
            test_s, cut = np.zeros(len(self.V)), {}
            train_s = {}
            for a in (0, 1):
                tr, te = (self.fold == a) & judged, self.fold != a
                if zs is not None:
                    test_s[te] = zs[te, j]
                    train_s[a] = (zs[tr, j], y[tr], no[tr])
                    continue
                if y[tr].sum() < 2:
                    test_s[te] = -99
                    train_s[a] = (np.full(tr.sum(), -99.0), y[tr], no[tr])
                    continue
                best = None
                for lam in (0.3, 1, 3, 10):
                    held = np.zeros(len(self.V))
                    for b in (0, 1):
                        t1, t2 = tr & (self.inner != b), tr & (self.inner == b)
                        held[t2] = F[t2] @ logreg(F[t1], y[t1].astype(float), lam) if y[t1].any() else -99
                    hs = held[tr]
                    t = max(np.unique(hs), key=lambda t: f1(hs, y[tr], t))
                    if best is None or f1(hs, y[tr], t) > best[0]:
                        best = (f1(hs, y[tr], t), lam, hs)
                test_s[te] = F[te] @ logreg(F[tr], y[tr].astype(float), best[1])
                train_s[a] = (best[2], y[tr], no[tr])
            out[c] = (test_s, train_s)
        return out

    def report(self, name, out):
        for mode in ("F1", f"wrong<={TARGET:.0%}"):
            ret = {}
            per = {}
            for c, (test_s, train_s) in out.items():
                r = np.zeros(len(self.V), bool)
                for a in (0, 1):
                    s, y, no = train_s[a]
                    cands = np.unique(s)
                    if mode == "F1":
                        t = max(cands, key=lambda t: f1(s, y, t))
                    else:
                        ok = [t for t in cands if wrong_rate(s, y, no, t) <= TARGET and (s >= t).sum() >= 3]
                        t = min(ok) if ok else np.inf
                    te = self.fold != a
                    r[te] = test_s[te] >= t
                ret[c] = r
                y, no = self.Y[c], self.NO[c]
                per[c] = ((r & y).sum(), (r & no).sum(), (~r & y).sum())
            tp = sum(p[0] for p in per.values()); fp = sum(p[1] for p in per.values()); fn = sum(p[2] for p in per.values())
            colr = [i for i, v in enumerate(self.V) if self.lab[v]["yes"]]
            lost = sum(not any(ret[c][i] for c in self.lab[self.V[i]]["yes"]) for i in colr) / len(colr)
            print(f"{name:34s} {mode:11s} wrong {fp / max(tp + fp, 1):3.0%} missed {fn / max(tp + fn, 1):3.0%} lost {lost:3.0%} | "
                  + " ".join(f"{c[:4]} {p[1] / max(p[0] + p[1], 1):.0%}/{p[2] / max(p[0] + p[2], 1):.0%}" for c, p in per.items()))


def pca(E, k=128):
    Ec = E - E.mean(0)
    _, sv, Vt = np.linalg.svd(Ec, full_matrices=False)
    return Ec @ Vt[:k].T / sv[0] * 30


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiles", type=Path, default=TILES)
    ap.add_argument("--tm", type=Path, help="Transmogrifier-tile CLIP embeddings {vids, emb} for comparison")
    ap.add_argument("--tex", type=Path, help="CLIP embeddings of texture-file images (texture_montage.py) to "
                    "compare and combine with the journal tiles")
    args = ap.parse_args()
    spec = json.loads((HERE / "labels.json").read_text())
    labels = {int(v): l for v, l in spec["labels"].items() if not l["holdout"]}
    cl = np.load(args.tiles / "clip_ViT-L-14.npz")
    hs = np.load(args.tiles / "hist.npz")
    T = np.load(args.tiles / "text_L14.npy")
    ci = {int(v): i for i, v in enumerate(cl["vids"])}
    hi = {int(v): i for i, v in enumerate(hs["vids"])}
    tm = None
    if args.tm:
        d = np.load(args.tm)
        tm = {int(v): e for v, e in zip(d["vids"], d["emb"])}
    tex = None
    if args.tex:
        d = np.load(args.tex)
        tex = {int(v): e for v, e in zip(d["vids"], d["emb"])}
    vids = [v for v in labels if v in ci and v in hi and (tm is None or v in tm) and (tex is None or v in tex)]
    ev = Eval(vids, labels, spec["colours"])
    print(f"{len(vids)} labelled tuning items with a journal tile" + (" and a Transmogrifier tile" if tm else ""))

    E = cl["emb"][[ci[v] for v in vids]]
    H = hs["hist"][[hi[v] for v in vids]]
    slot = np.eye(13)[hs["slot"][[hi[v] for v in vids]]]
    one = np.ones((len(vids), 1))
    zs = E @ T.T
    zs_c = zs - zs.mean(1, keepdims=True)
    if tm is not None:
        Et = np.array([tm[v] for v in vids])
        zt = Et @ T.T
        ev.report("TRANSMOG tiles, zero-shot", ev.scores(zs=zt - zt.mean(1, keepdims=True)))
        ev.report("TRANSMOG tiles, trained", ev.scores(F=np.hstack([(zt - zt.mean(1, keepdims=True)) * 50, pca(Et), one])))
    ev.report("JOURNAL tiles, zero-shot", ev.scores(zs=zs_c))
    ev.report("JOURNAL tiles, trained (CLIP)", ev.scores(F=np.hstack([zs_c * 50, pca(E), one])))
    journal_f = np.hstack([zs_c * 50, pca(E), np.sqrt(H) * 3, slot])
    ev.report("JOURNAL, trained (CLIP+hist+slot)", ev.scores(F=np.hstack([journal_f, one])))
    if tex is not None:
        Ex = np.array([tex[v] for v in vids])
        zx = Ex @ T.T
        zx_c = zx - zx.mean(1, keepdims=True)
        ev.report("TEXTURE images, zero-shot", ev.scores(zs=zx_c))
        ev.report("TEXTURE images, trained (+slot)", ev.scores(F=np.hstack([zx_c * 50, pca(Ex), slot, one])))
        ev.report("JOURNAL + TEXTURE, trained", ev.scores(F=np.hstack([journal_f, zx_c * 50, pca(Ex, 64), one])))


if __name__ == "__main__":
    main()
