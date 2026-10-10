"""Why does picking purple return a mostly-silver piece?

ColorData ranks clusters with ACHROMATIC_RANK_PENALTY applied, which discounts
neutrals when ranking so that a piece's identifying trim wins over its shading.
That is right for the FILTER (people name the salient colour, and the user
explicitly chose it) but it means rank 1 can be a small purple trim on armour
that is 70% silver. Rolling a whole outfit wants the opposite: the piece should
READ as the colour you picked.

The stored weight is the true pixel share, so this measures how much area rank 1
actually covers, and what a minimum-weight requirement would cost in pool size.

    python analyze_dominance.py
"""
import statistics
from collections import Counter

# Shared with the other harnesses so all three agree with each other and with
# Palette.lua. HUE_GROUPS here is the CURRENT grouping, not the old red+rust one.
from analyze_grain import HUE_GROUPS, classify, main_and_accent, parse


def broad_key(h, s, v, achromatic=False):
    """The 'broad' grain the user is working with."""
    return classify(h, s, v, lambda b: HUE_GROUPS[b], 1, achromatic)


def main():
    data = parse()
    print(f"{len(data)} appearances\n")

    w1 = [c[0][3] for c in data.values()]
    w1.sort()
    print("rank-1 weight (share of pixels the dominant cluster covers):")
    for p in (10, 25, 50, 75, 90):
        print(f"   p{p:<3} {w1[int(len(w1) * p / 100)]:.2f}")
    print(f"   mean {statistics.mean(w1):.2f}\n")

    # How often is rank 1 a CHROMATIC colour that covers less area than a
    # neutral cluster further down? That is exactly the purple-trim-on-silver
    # case the user hit.
    trim = 0
    for clusters in data.values():
        h, s, v, w, achromatic = main_and_accent(clusters)[0]
        if not achromatic:
            bigger_neutral = any(c[3] > w and c[4] for c in clusters[1:])
            if bigger_neutral:
                trim += 1
    print(f"appearances where rank 1 is chromatic but a NEUTRAL cluster covers "
          f"more area: {trim} ({100 * trim / len(data):.1f}%)")
    print("   ^ these are the 'picked purple, got silver armour' pieces\n")

    # What does a minimum-weight requirement cost in pool size?
    print("pool size per broad bucket at various rank-1 minimum weights:")
    thresholds = [0.0, 0.30, 0.35, 0.40, 0.50]
    tables = []
    for t in thresholds:
        counts = Counter()
        for clusters in data.values():
            h, s, v, w, achromatic = main_and_accent(clusters)[0]
            if w >= t:
                counts[broad_key(h, s, v, achromatic)] += 1
        tables.append(counts)

    keys = sorted(tables[0], key=lambda k: -tables[0][k])
    header = "   " + f"{'bucket':<14}" + "".join(f"{'>=' + str(t):>9}" for t in thresholds)
    print(header)
    for k in keys:
        row = "".join(f"{tab[k]:>9}" for tab in tables)
        print(f"   {k:<14}{row}")

    print("\n   totals" + "".join(f"{sum(t.values()):>9}" for t in tables))


if __name__ == "__main__":
    main()
