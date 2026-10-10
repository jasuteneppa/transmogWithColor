"""Compare two or more ColorData.lua builds across EVERY bucket at once.

Written because the tuning loop kept going one colour at a time: a change was
judged by what it did to brown, shipped, and then found to have moved gold or
purple somewhere worse. Any per-colour view hides that trade, and every harness
here before this one was a per-colour view.

So this reports the whole picture side by side:

  * agreement with the hand labels, per bucket AND overall
  * what each build turns the whole game into -- bucket sizes, so a change that
    "improves accuracy" by collapsing everything into two buckets is visible
  * the greyscale split and the value distribution behind it, which is where
    white and black armour live or die
  * how many appearances CHANGE bucket between builds, and which way

Usage:
    python compare_builds.py                       # backup vs shipped
    python compare_builds.py a.lua b.lua c.lua     # any set, first is baseline
"""
import sys
from collections import Counter, defaultdict
from pathlib import Path

import analyze_grain as ag
import analyze_names as an
import score_overrides as so

HERE = Path(__file__).resolve().parent
SHIPPED = HERE.parent / "TransmogPalette" / "ColorData.lua"
FAMILIES = ["red", "brown", "gold", "green", "blue", "purple", "pink",
            "black", "gray", "white"]


def load(path):
    ag.COLOR_DATA = Path(path)
    return ag.parse()


def labels(baseline):
    """visualID -> the family you named in game, via the override picker."""
    out = {}
    for entries in so.parse_overrides(so.DEFAULT_SV).values():
        for vid, spec in entries.items():
            clusters = baseline.get(vid)
            if not clusters or "main" not in spec:
                continue
            fam = so.family_of(spec["main"], clusters)
            if fam:
                out[vid] = fam
    return out


def families(data):
    """visualID -> the family this build assigns."""
    return {vid: an.classify_main(c)[0] for vid, c in data.items()}


def neutral_values(data):
    vals = []
    for clusters in data.values():
        m = ag.main_and_accent(clusters)[0]
        if m and ag.is_neutral(m[1], m[2], m[4]):
            vals.append(m[2])
    vals.sort()
    return vals


def main():
    paths = [Path(p) for p in sys.argv[1:]]
    if not paths:
        backup = SHIPPED.with_suffix(".lua.bak-1.2.2")
        paths = ([backup] if backup.exists() else []) + [SHIPPED]
    names = [p.name.replace("ColorData", "").strip("._-lua") or "shipped"
             for p in paths]

    builds = [load(p) for p in paths]
    truth = labels(builds[0])
    print(f"{len(truth)} hand-labelled appearances, "
          f"{len(builds[0]):,} appearances per build\n")

    # --- 1. agreement, per bucket and overall -----------------------------
    fam_by_build = [families(b) for b in builds]
    print("=== agreement with your labels ===")
    header = f"{'you said':<9}{'n':>5}" + "".join(f"{n:>12}" for n in names)
    print(header)
    per = defaultdict(lambda: [0] * len(builds))
    totals = [0] * len(builds)
    counts = Counter(truth.values())
    for vid, want in truth.items():
        for i, fam in enumerate(fam_by_build):
            if fam.get(vid) == want:
                per[want][i] += 1
                totals[i] += 1
    for want in FAMILIES:
        n = counts.get(want, 0)
        if not n:
            continue
        row = "".join(f"{per[want][i]/n:>11.0%} " for i in range(len(builds)))
        print(f"{want:<9}{n:>5}{row}")
    print(f"{'OVERALL':<9}{len(truth):>5}"
          + "".join(f"{t/len(truth):>11.0%} " for t in totals))

    # --- 2. what each build turns the game into ---------------------------
    print("\n=== bucket sizes across the whole game ===")
    print("(a build that scores well by collapsing the palette shows up here)")
    print(f"{'bucket':<9}" + "".join(f"{n:>12}" for n in names))
    dists = [Counter(f.values()) for f in fam_by_build]
    for fam in FAMILIES:
        row = "".join(f"{d.get(fam, 0)/max(1, len(builds[i])):>11.1%} "
                      for i, d in enumerate(dists))
        print(f"{fam:<9}{row}")
    print(f"{'greyscale':<9}"
          + "".join(f"{sum(d.get(k, 0) for k in ('black', 'gray', 'white'))/max(1, len(builds[i])):>11.1%} "
                    for i, d in enumerate(dists)))

    # --- 3. the value scale the greyscale cuts are applied to -------------
    print("\n=== lightness of everything each build calls greyscale ===")
    print("(WHITE_MIN is 0.60; if p95 sits below it, white is unreachable)")
    print(f"{'pct':<9}" + "".join(f"{n:>12}" for n in names))
    vals = [neutral_values(b) for b in builds]
    for p in (25, 50, 75, 90, 95, 99):
        row = ""
        for v in vals:
            row += f"{(v[int(len(v)*p/100)] if v else 0):>11.2f} "
        print(f"p{p:<8}{row}")
    row = "".join(f"{(sum(1 for x in v if x >= 0.60)/len(v) if v else 0):>11.1%} "
                  for v in vals)
    print(f"{'>=0.60':<9}{row}")

    # --- 4. churn between the baseline and each later build ---------------
    base = fam_by_build[0]
    for i in range(1, len(builds)):
        moved = Counter()
        n = 0
        for vid, was in base.items():
            now = fam_by_build[i].get(vid)
            if now and now != was:
                moved[(was, now)] += 1
                n += 1
        print(f"\n=== {names[0]} -> {names[i]}: {n:,} appearances "
              f"({n/max(1,len(base)):.1%}) change bucket ===")
        for (was, now), k in moved.most_common(12):
            print(f"   {was:>7} -> {now:<7} {k:,}")


if __name__ == "__main__":
    main()
