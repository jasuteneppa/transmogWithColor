"""Does SQUINTING decide an armour's main colour?

The question this project actually needs answered is "what makes a colour the
main colour of a garment", and every attempt so far has answered a different
one: "which constant is mis-set". Eight tuned constants later the gold bucket is
full of green chests with gold filigree.

Every failure we catalogued has one shape: thin trim beats a big solid body.
And a colour histogram CANNOT tell those apart -- 20% of pixels in hairline
filigree is identical to 20% in one solid panel. The distinguishing information
is spatial, and it is discarded before clustering begins.

A person resolves this by squinting. Trim disappears when you squint; a body
does not. So: downsample the texture hard before doing anything else, and let
thin detail blend into whatever it borders. No new thresholds, no new weights --
one missing input restored.

=== METHODOLOGY ===

Everything today was scored on the same 124 hand labels, which is how you
manufacture progress that is not there. This uses two independent checks:

  A. the 124 override labels, scored by REPEATED RANDOM SPLIT-HALF: the squint
     resolution is chosen on one half and scored on the held-out half, 40 times
     over. The reported number is held-out only, so choosing the resolution
     cannot inflate it.

  B. the item-name key (~4,470 appearances), which is noisy -- roughly a third
     of its labels are wrong -- but is a completely separate sample that has
     never been used to tune anything. It cannot say which option is best; it
     can say whether one is broken.

A result that moves both is real. A result that moves only A is a fit to A.
"""
import argparse
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

import analyze_grain as ag
import analyze_names as an
import audit_stages as aud
import generate_color_data as gcd
import score_overrides as so

HERE = Path(__file__).resolve().parent
SHIPPED = HERE.parent / "TransmogPalette" / "ColorData.lua"
FAMILIES = ["red", "brown", "gold", "green", "blue", "purple", "pink",
            "black", "gray", "white"]

_RAW = {}


def raw_texture(fdid):
    if fdid not in _RAW:
        try:
            _RAW[fdid] = gcd.fetch_texture(fdid, None).convert("RGBA")
        except Exception:
            _RAW[fdid] = None
    return _RAW[fdid]


def squint_colors(fdid, res):
    """(count, RGBA) pairs after squinting the texture down to res x res.

    Alpha is premultiplied before the resize and divided out after, so a
    transparent pixel's junk RGB cannot bleed into its neighbours -- without
    that, cutout regions drag every colour toward whatever the artist left in
    the transparent areas.
    """
    img = raw_texture(fdid)
    if img is None:
        return []
    if res:
        arr = np.asarray(img).astype(np.float64)
        alpha = arr[:, :, 3:4] / 255.0
        pre = np.concatenate([arr[:, :, :3] * alpha, arr[:, :, 3:4]], axis=2)
        small = Image.fromarray(pre.clip(0, 255).astype(np.uint8), "RGBA") \
                     .resize((res, res), Image.BOX)
        s = np.asarray(small).astype(np.float64)
        sa = s[:, :, 3:4] / 255.0
        rgb = np.where(sa > 0.004, s[:, :, :3] / np.maximum(sa, 1e-6), 0.0)
        img = Image.fromarray(
            np.concatenate([rgb, s[:, :, 3:4]], axis=2).clip(0, 255).astype(np.uint8),
            "RGBA")
    return img.point(gcd._QUANT_LUT).getcolors(1 << 20) or []


def classify(vid, pairs, res):
    pooled = gcd.new_profile()
    got = False
    for tex_fdid, _m, _i in pairs.get(vid, []):
        colors = squint_colors(tex_fdid, res)
        if not colors:
            continue
        p = gcd._accumulate(colors)
        if p:
            gcd.add_profiles(pooled, p)
            got = True
    if not got:
        return None
    clusters = gcd.dominant_colors(pooled)
    return an.classify_main(clusters)[0] if clusters else None


class Config:
    """A whole pipeline setting, so 'released-like' and 'today' are comparable."""

    def __init__(self, name, res, **consts):
        self.name, self.res, self.consts = name, res, consts

    def __enter__(self):
        self.saved = {k: getattr(gcd, k) for k in self.consts}
        for k, v in self.consts.items():
            setattr(gcd, k, v)
        return self

    def __exit__(self, *a):
        for k, v in self.saved.items():
            setattr(gcd, k, v)


TODAY = dict(BROWN_EXTRA_PER_LIGHTNESS=0.0, LIT_PERCENTILE=0.40,
             SHADOW_RAMP_DEGREES=25.0, HUE_SUPPRESS_DEGREES=12.0,
             HUE_CORE_DEGREES=6.0, HUE_ASSIGN_WINDOW=None)
RELEASED = dict(BROWN_EXTRA_PER_LIGHTNESS=0.08, LIT_PERCENTILE=1.0,
                SHADOW_RAMP_DEGREES=0.0, HUE_SUPPRESS_DEGREES=50.0,
                HUE_CORE_DEGREES=50.0, HUE_ASSIGN_WINDOW=50.0)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name-sample", type=int, default=500,
                    help="how many item-name-key appearances to score (0 skips)")
    ap.add_argument("--splits", type=int, default=40,
                    help="random split-half repeats on the override labels")
    args = ap.parse_args()

    ag.COLOR_DATA = SHIPPED
    data = ag.parse()
    pairs = aud.visual_pairs()

    truth = {}
    for entries in so.parse_overrides(so.DEFAULT_SV).values():
        for vid, spec in entries.items():
            c = data.get(vid)
            if not c or "main" not in spec:
                continue
            fam = so.family_of(spec["main"], c)
            if fam:
                truth[vid] = fam
    truth = {v: t for v, t in truth.items() if pairs.get(v)}

    names, i2v = an.load_names()
    # build_labels returns (labels, how_many_were_contradictory)
    name_truth, _contested = an.build_labels(names, i2v)
    # Never score an appearance that is in set A: the two checks have to be
    # independent, and an overlap would quietly make B echo A.
    name_truth = {v: t for v, t in name_truth.items()
                  if pairs.get(v) and v not in truth}
    if args.name_sample and len(name_truth) > args.name_sample:
        rng = random.Random(11)
        keep = rng.sample(sorted(name_truth), args.name_sample)
        name_truth = {v: name_truth[v] for v in keep}

    print(f"set A: {len(truth)} override labels (yours, accurate, small)")
    print(f"set B: {len(name_truth)} item-name labels (independent, ~1/3 noisy)\n")

    configs = [Config("released, no squint", None, **RELEASED),
               Config("today, no squint", None, **TODAY)]
    for res in (64, 32, 16, 8):
        configs.append(Config(f"today, squint {res}x{res}", res, **TODAY))

    # Predictions per config, kept so the cross-validation below re-uses them
    # instead of re-profiling 500 textures forty times over.
    preds_a, preds_b = {}, {}
    print(f"{'config':<24}{'set A':>9}{'set B':>9}   biggest bucket in A")
    for cfg in configs:
        with cfg:
            pa = {v: classify(v, pairs, cfg.res) for v in truth}
            pb = {v: classify(v, pairs, cfg.res) for v in name_truth}
        preds_a[cfg.name], preds_b[cfg.name] = pa, pb
        a = sum(1 for v, t in truth.items() if pa.get(v) == t) / max(1, len(truth))
        b = sum(1 for v, t in name_truth.items() if pb.get(v) == t) / max(1, len(name_truth))
        dist = Counter(x for x in pa.values() if x)
        top = max(dist.items(), key=lambda kv: kv[1]) if dist else ("-", 0)
        print(f"{cfg.name:<24}{a:>8.0%}{b:>9.0%}   {top[0]} {top[1]/max(1,len(pa)):.0%}")

    # --- honest number: choose the resolution on one half, score the other ---
    squints = [c.name for c in configs if "squint" in c.name]
    baseline = "today, no squint"
    rng = random.Random(5)
    vids = sorted(truth)
    held_chosen, held_base, picks = [], [], Counter()
    for _ in range(args.splits):
        shuffled = vids[:]
        rng.shuffle(shuffled)
        half = len(shuffled) // 2
        train, test = shuffled[:half], shuffled[half:]
        best = max(squints + [baseline],
                   key=lambda n: sum(1 for v in train if preds_a[n].get(v) == truth[v]))
        picks[best] += 1
        held_chosen.append(sum(1 for v in test if preds_a[best].get(v) == truth[v]) / len(test))
        held_base.append(sum(1 for v in test if preds_a[baseline].get(v) == truth[v]) / len(test))

    print(f"\n=== split-half cross-validation, {args.splits} random splits ===")
    print("(the setting is chosen on one half and scored ONLY on the other)")
    print(f"  chosen-by-train, held-out : {statistics.mean(held_chosen):.1%} "
          f"+/- {statistics.pstdev(held_chosen):.1%}")
    print(f"  no-squint baseline        : {statistics.mean(held_base):.1%} "
          f"+/- {statistics.pstdev(held_base):.1%}")
    print("  what train picked:", ", ".join(f"{k.split(', ')[-1]} x{n}"
                                            for k, n in picks.most_common()))

    best_overall = max(squints, key=lambda n: sum(
        1 for v, t in name_truth.items() if preds_b[n].get(v) == t))
    print(f"\n=== per colour, set A: no squint vs {best_overall} ===")
    print(f"{'you said':<9}{'n':>5}{'none':>8}{'squint':>9}")
    counts = Counter(truth.values())
    for fam in FAMILIES:
        n = counts.get(fam, 0)
        if not n:
            continue
        x = sum(1 for v, t in truth.items() if t == fam and preds_a[baseline].get(v) == t)
        y = sum(1 for v, t in truth.items() if t == fam and preds_a[best_overall].get(v) == t)
        print(f"{fam:<9}{n:>5}{x/n:>7.0%}{y/n:>9.0%}")


if __name__ == "__main__":
    main()
