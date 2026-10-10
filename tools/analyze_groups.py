"""Pick a BALANCED coarse grouping, and decide how the roll should pick an
item's colour.

Two problems observed in game at the 'broad' grain:

  1. `red` held 20,839 of 63,742 appearances (33%) and read as a brown grab-bag.
     Merging red+rust undid an earlier fix in this project, which split those
     apart precisely because one bucket spanned dark maroon to saturated rust
     and a "brown" swatch returned red gloves.

  2. Picking purple returned mostly-silver plate, because rank 1 is ranked with
     neutrals discounted, so a small purple trim outranks the silver that
     covers most of the piece.

  3. The fix for (2) -- pick the largest-area cluster, no discount at all --
     overcorrected. It put 38.4% of appearances in a neutral roll bucket and
     11.2% in a black one, against 22.1% and 6.6% by rank order, so 41% of the
     roller's black bucket had a genuinely coloured dominant colour. Confirmed
     in game: "Beacons of the Black Talon", four variants, none black, all
     offered under a black roll.

So: compare groupings for balance, and sweep the neutral area penalty that
decides an item's roll colour, since both extremes of it are wrong.

    python analyze_groups.py
"""
import statistics
from collections import Counter

# Parsing and classification live in analyze_grain so the two harnesses cannot
# drift apart -- they must agree with each other as well as with Palette.lua.
from analyze_grain import (DEFAULT_COLOR_FIRST, HUE_BANDS, classify,
                           main_and_accent, parse)

GROUPINGS = {
    "G1 current (6)": {
        "red": "red", "rust": "red", "orange": "gold", "gold": "gold",
        "olive": "green", "green": "green", "teal": "blue", "blue": "blue",
        "indigo": "purple", "violet": "purple", "purple": "purple", "pink": "pink",
    },
    "G2 split red/rust (7)": {
        "red": "red", "rust": "brown", "orange": "gold", "gold": "gold",
        "olive": "green", "green": "green", "teal": "blue", "blue": "blue",
        "indigo": "purple", "violet": "purple", "purple": "purple", "pink": "pink",
    },
    "G3 + orange apart (8)": {
        "red": "red", "rust": "brown", "orange": "orange", "gold": "gold",
        "olive": "green", "green": "green", "teal": "blue", "blue": "blue",
        "indigo": "purple", "violet": "purple", "purple": "purple", "pink": "pink",
    },
    "G4 + olive apart (9)": {
        "red": "red", "rust": "brown", "orange": "orange", "gold": "gold",
        "olive": "olive", "green": "green", "teal": "blue", "blue": "blue",
        "indigo": "purple", "violet": "purple", "purple": "purple", "pink": "pink",
    },
    "G5 + teal apart (10)": {
        "red": "red", "rust": "brown", "orange": "orange", "gold": "gold",
        "olive": "olive", "green": "green", "teal": "teal", "blue": "blue",
        "indigo": "purple", "violet": "purple", "purple": "purple", "pink": "pink",
    },
}


def key_for(cluster, groups):
    """Broad grain: hue groups, no value split. cluster is (h,s,v,w,achromatic)."""
    return classify(cluster[0], cluster[1], cluster[2],
                    lambda b: groups[b], 1, cluster[4])


def pick_rank1(clusters):
    return clusters[0]


def pick_main(clusters, threshold=DEFAULT_COLOR_FIRST):
    """The appearance's main colour under the colour-first rule."""
    return main_and_accent(clusters, threshold)[0]


def report(data, groups, pick, label):
    counts = Counter()
    for clusters in data.values():
        counts[key_for(pick(clusters), groups)] += 1
    sizes = sorted(counts.values(), reverse=True)
    total = sum(sizes)
    share = 100 * sizes[0] / total
    print(f"   {label:26} buckets={len(counts):>3} biggest={sizes[0]:>6} "
          f"({share:>4.1f}%) median={statistics.median(sizes):>6.0f} min={sizes[-1]:>5}")
    return counts


def main():
    data = parse()
    print(f"{len(data)} appearances\n")

    print("GROUPING BALANCE (broad grain, rank-1 colour):")
    for name, groups in GROUPINGS.items():
        report(data, groups, pick_rank1, name)

    print(f"\nSame, but using the main colour (colour-first {DEFAULT_COLOR_FIRST}):")
    for name, groups in GROUPINGS.items():
        report(data, groups, pick_main, name)

    best = GROUPINGS["G3 + orange apart (8)"]
    print(f"\nfull distribution, G3, main colour:")
    counts = Counter()
    for clusters in data.values():
        counts[key_for(pick_main(clusters), best)] += 1
    for k, n in counts.most_common():
        print(f"   {k:<14} {n:>6}  ({100 * n / len(data):>4.1f}%)")

    # THE COLOUR-FIRST SWEEP -- what /tmpalette colorfirst moves.
    #
    # The anchor for reading it: only 2,372 appearances (3.7%) have NO coloured
    # region at all. Any greyscale total far above that is the classifier
    # calling colourful armour grey, which is the complaint this rule exists to
    # fix. Too low and the opposite failure returns -- a black piece with gold
    # trim rolls as gold.
    print("\ncolour-first sweep (G3, broad grain):")
    print(f"   {'min colour':>10}  {'greyscale':>9} {'black':>7} {'gray':>7} "
          f"{'white':>7}  {'vs default':>12}")
    base = {vid: key_for(pick_main(c), best) for vid, c in data.items()}
    for t in (0.10, 0.15, 0.20, 0.25, 0.30, 0.40):
        counts, moved = Counter(), 0
        for vid, clusters in data.items():
            k = key_for(pick_main(clusters, t), best)
            counts[k] += 1
            if k != base[vid]:
                moved += 1
        grey = counts["black"] + counts["gray"] + counts["white"]
        tag = "  <- default" if abs(t - DEFAULT_COLOR_FIRST) < 1e-9 else ""
        print(f"   {t:10.2f}  {grey/len(data):8.1%} {counts['black']:7d} "
              f"{counts['gray']:7d} {counts['white']:7d}  "
              f"{moved:7d} ({moved/len(data):4.1%}){tag}")


if __name__ == "__main__":
    main()
