"""Scores the classifier against an answer key mined from ITEM NAMES.

Every colour rule in this addon used to be decided from anecdote -- someone
noticed one wrong item in game, a rule changed, and whether that helped the
other 63,753 was unknowable. This makes it measurable.

WHERE THE ANSWER KEY COMES FROM. WoW item names state a colour constantly, and
ItemSparse.csv is already in db2_cache. The join is two hops:

    ItemSparse.Display_lang -> ItemModifiedAppearance.ItemID
                            -> ItemModifiedAppearance.ItemAppearanceID == visualID

9,002 items name a colour, reaching 4,652 appearances; 4,497 of those have every
naming item agreeing. That agreement is the reason to trust it at all: when two
DIFFERENT items share an appearance and both name a colour, they concur 97% of
the time, so the names are describing the appearance rather than lore.

HOW MUCH TO TRUST IT -- read this before acting on a number. The key is a WEAK
proxy. Roughly a third of labels are wrong, in ways that are obvious once seen:
"Brass-Studded Bracers" is leather with brass studs (the name is the trim),
"Verdant Aspirant's" armour is brown (the name is a set), "Darkspear (Purple
Glow)" names an effect. So:

  * A gross failure is unmistakable. Gold scored 4.2% against 42-51% for red,
    blue, brown and purple. That found a real bug -- the gold band started at
    46 deg and WoW's gold sits at 34-45 -- which was then confirmed by eye.
  * A small difference means nothing. Seven materially different methods were
    scored here and all landed between 22% and 25%: reweighting vividness
    against area, prototype anchors, exemplar anchors, hand-placed true-colour
    anchors, exposure correction, and reading colour off a lit 3D render. When
    approaches that different tie, the tie is the answer key's ceiling, not a
    result about any of them.

So: use this to catch something badly broken, and to keep a change from silently
regressing. Do NOT use it to choose between two reasonable options -- for that,
label items by hand with label_sheets.py and pass --hand.

Scoring is at BROAD grain (the 11 colour families), because that is the coarsest
honest reading of a name: "Crimson" promises red, not red_mid.

    python analyze_names.py                    # score the shipped classifier
    python analyze_names.py --sweep orange     # move one band edge and re-score
    python analyze_names.py --hand labels.csv  # score against hand labels
"""
import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import analyze_grain as ag

DB2 = Path(__file__).resolve().parent / "db2_cache"
csv.field_size_limit(10 ** 7)

# Mapped straight to broad-grain family names. Deliberately conservative: words
# whose colour reading is secondary to a lore reading (ebon, midnight, sable,
# rose, silver) still appear because dropping them changed the headline number
# by under two points, but every one of them adds noise.
LEXICON = {
    "red": "crimson scarlet ruby sanguine vermillion cardinal",
    "brown": "rust russet copper bronze umber chestnut mahogany",
    "orange": "orange tangerine",
    "gold": "gold golden gilded brass saffron amber",
    "green": "green emerald verdant jade viridian malachite olive",
    "blue": "blue azure cobalt sapphire cerulean navy teal turquoise aquamarine cyan",
    "purple": "purple amethyst violet indigo mauve lavender",
    "pink": "pink rose magenta fuchsia",
    "black": "black obsidian onyx ebon ebony sable midnight",
    "gray": "gray grey ashen slate silver",
    "white": "white ivory alabaster pearl snowy",
}
WORD = {w: fam for fam, ws in LEXICON.items() for w in ws.split()}
PATTERN = re.compile(r"\b(" + "|".join(sorted(WORD)) + r")\b", re.I)
FAMILY = lambda band: ag.HUE_GROUPS[band]


def label_of(name):
    """The one colour family a name states, or None. A name mentioning two
    ("Black and Gold Tabard") states neither for our purposes."""
    hits = {WORD[m.lower()] for m in PATTERN.findall(name)}
    return hits.pop() if len(hits) == 1 else None


def load_names():
    names = {}
    with open(DB2 / "ItemSparse.csv", encoding="utf-8", errors="replace", newline="") as fh:
        for row in csv.DictReader(fh):
            if row.get("Display_lang"):
                names[int(row["ID"])] = row["Display_lang"]
    item_to_visual = defaultdict(set)
    with open(DB2 / "ItemModifiedAppearance.csv", encoding="utf-8",
              errors="replace", newline="") as fh:
        for row in csv.DictReader(fh):
            vid = int(row["ItemAppearanceID"])
            if vid:
                item_to_visual[int(row["ItemID"])].add(vid)
    return names, item_to_visual


def build_labels(names, item_to_visual):
    """visualID -> family, keeping only appearances every naming item agrees on."""
    votes = defaultdict(Counter)
    for item_id, name in names.items():
        fam = label_of(name)
        if fam:
            for vid in item_to_visual.get(item_id, ()):
                votes[vid][fam] += 1
    unanimous = {v: c.most_common(1)[0][0] for v, c in votes.items() if len(c) == 1}
    return unanimous, len(votes) - len(unanimous)


def classify_main(clusters, bands=None):
    """The family the addon assigns, optionally under a modified band table."""
    m = ag.main_and_accent(clusters)[0]
    if bands is None:
        return ag.classify(m[0], m[1], m[2], FAMILY, 1, m[4]), m
    if ag.is_neutral(m[1], m[2], m[4]):
        return ("black" if m[2] < ag.BLACK_MAX else
                "gray" if m[2] < ag.WHITE_MIN else "white"), m
    h = m[0] % 360
    for bound, band in bands:
        if h < bound:
            return ag.HUE_GROUPS[band], m
    return ag.HUE_GROUPS[bands[0][1]], m


def report(labels, data, bands=None, title=""):
    per = defaultdict(lambda: [0, 0])
    where = defaultdict(Counter)
    ok = total = 0
    for vid, truth in labels.items():
        clusters = data.get(vid)
        if not clusters:
            continue
        got, _ = classify_main(clusters, bands)
        total += 1
        per[truth][1] += 1
        if got == truth:
            ok += 1
            per[truth][0] += 1
            where[truth]["main"] += 1
            continue
        # Distinguish "ranked the wrong cluster" from "never extracted it" --
        # completely different bugs, and only the first is fixable downstream.
        accent = ag.main_and_accent(clusters)[1]
        anywhere = {ag.classify(c[0], c[1], c[2], FAMILY, 1, c[4]) for c in clusters}
        if accent and ag.classify(accent[0], accent[1], accent[2], FAMILY, 1, accent[4]) == truth:
            where[truth]["accent"] += 1
        elif truth in anywhere:
            where[truth]["other cluster"] += 1
        else:
            where[truth]["absent"] += 1

    if title:
        print(f"\n=== {title} ===")
    print(f"main colour matches the name: {ok:,}/{total:,} = {ok/total:.1%}\n")
    print(f"{'family':<8}{'n':>6}{'correct':>9}{'as accent':>11}{'elsewhere':>11}{'absent':>9}")
    for fam, (o, t) in sorted(per.items(), key=lambda kv: -kv[1][1]):
        w = where[fam]
        print(f"{fam:<8}{t:>6}{o/t:>9.1%}{w['accent']/t:>11.1%}"
              f"{w['other cluster']/t:>11.1%}{w['absent']/t:>9.1%}")
    return ok / total if total else 0.0


def score_hand(path, data):
    """Score against hand labels from label_sheets.py -- the trustworthy key."""
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    labels = {}
    for r in rows:
        answer = (r.get("your_answer") or "").strip().lower()
        if answer and answer in set(ag.HUE_GROUPS.values()) | {"black", "gray", "white"}:
            labels[int(r["visualID"])] = answer
    blank = len(rows) - len(labels)
    print(f"hand labels: {len(labels)} filled in, {blank} still blank")
    if not labels:
        print("Nothing to score yet. Fill in the your_answer column.")
        return
    report(labels, data, title="hand-labelled")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sweep", metavar="BAND",
                    help="Band whose upper edge to sweep, e.g. 'orange'. Re-scores "
                         "at each candidate edge so a boundary move can be judged "
                         "before it ships.")
    ap.add_argument("--hand", type=Path, metavar="CSV",
                    help="Score against hand labels written by label_sheets.py "
                         "instead of item names. Far more trustworthy; use this "
                         "whenever the file exists.")
    args = ap.parse_args()

    data = ag.parse()
    print(f"{len(data):,} appearances with colour data")

    if args.hand:
        score_hand(args.hand, data)
        return

    names, item_to_visual = load_names()
    labels, contested = build_labels(names, item_to_visual)
    scored = sum(1 for v in labels if v in data)
    print(f"{len(labels):,} appearances labelled by item name "
          f"({contested:,} contested and dropped); {scored:,} also have colour data")

    if not args.sweep:
        report(labels, data)
        return

    band_names = [n for _, n in ag.HUE_BANDS]
    if args.sweep not in band_names:
        sys.exit(f"--sweep must name a band: {', '.join(band_names)}")
    i = band_names.index(args.sweep)
    lower = ag.HUE_BANDS[i - 1][0] if i else 0
    current = ag.HUE_BANDS[i][0]
    upper = ag.HUE_BANDS[i + 1][0] if i + 1 < len(ag.HUE_BANDS) else 360

    print(f"\nsweeping the upper edge of '{args.sweep}' (currently {current}); "
          f"it may sit anywhere in ({lower}, {upper})")
    print(f"\n{'edge':>6}{'overall':>10}   per-family recall")
    for edge in range(lower + 2, upper, 2):
        bands = [(edge if n == args.sweep else b, n) for b, n in ag.HUE_BANDS]
        per = defaultdict(lambda: [0, 0])
        ok = total = 0
        for vid, truth in labels.items():
            clusters = data.get(vid)
            if not clusters:
                continue
            got, _ = classify_main(clusters, bands)
            total += 1
            per[truth][1] += 1
            if got == truth:
                ok += 1
                per[truth][0] += 1
        watch = [args.sweep, ag.HUE_GROUPS[args.sweep]]
        if i + 1 < len(ag.HUE_BANDS):
            watch.append(ag.HUE_GROUPS[ag.HUE_BANDS[i + 1][1]])
        cells = " ".join(f"{f} {per[f][0]}/{per[f][1]}"
                         for f in dict.fromkeys(watch) if per[f][1])
        mark = "  <- shipped" if edge == current else ""
        print(f"{edge:>6}{ok/total:>10.1%}   {cells}{mark}")
    print("\nA lower edge is not automatically better: an edge can 'improve' by "
          "swallowing its neighbour entirely. Check the bucket sizes with "
          "analyze_filter_grain.py before moving one.")


if __name__ == "__main__":
    main()
