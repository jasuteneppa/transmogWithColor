"""Score colour matching against the frozen eye-judged labels (see README.md).

For each general colour, over the labelled appearances (tuning half only,
unless --holdout):
  wrong   -- of what the filter returns that is labelled yes or no, the share
             labelled no. "Unsure" items are never counted either way.
  missed  -- of the items labelled yes, the share the filter does not return.
and overall:
  lost    -- items with at least one yes colour that NONE of their yes
             colours' filters return: obviously coloured, findable nowhere.
  unfindable -- whole-game share of appearances no colour filter returns.

Always printed for 1.2.1 (each appearance's single main bucket) and for the
current matcher (match_eval.texture_score / min_score >= 1, the addon's rule).

    python benchmark/score.py              # tuning half
    python benchmark/score.py --holdout    # ONCE, at the end
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import capture_calibrate as cc  # noqa: E402
import match_eval as me  # noqa: E402
import naming_compare as nc  # noqa: E402
import scorecard as sc  # noqa: E402

SLOTS = set(sc.SLOTS)
PAGE = 20


def legacy_method(data):
    """1.2.1: one bucket per appearance, from its main colour."""
    def returns(vid, colour):
        return nc.current_family(nc.main_cluster(data[vid])) == colour
    return returns


def current_method(data, palette_path=HERE.parent / "palette.json"):
    """The addon's closeness matching: a general colour returns an appearance
    when any member swatch scores at least its cutoff."""
    pal = {p["name"]: p for p in json.loads(Path(palette_path).read_text())}
    members = {g.lower(): m for g, m, _ in sc.GROUPS}
    cache = {}

    def rank(vid, colour):
        key = (vid, colour)
        if key not in cache:
            cache[key] = max(me.texture_score(data[vid], np.array(pal[m]["lab"])) / pal[m]["min_score"]
                             for m in members[colour])
        return cache[key]

    def returns(vid, colour):
        return rank(vid, colour) >= 1
    returns.rank = rank
    return returns


def v2_method(data, path):
    import match_v2 as mv
    m = mv.Matcher(mv.load(path), data)
    m.rank = m.rank  # sortable, like current_method
    return m


def score(method, labels, colours):
    rows = {}
    for c in colours:
        ret_yes = ret_no = yes = hit = 0
        for vid, l in labels.items():
            r = method(vid, c)
            is_yes, is_no = c in l["yes"], c not in l["yes"] and c not in l["unsure"]
            if is_yes:
                yes += 1
                hit += r
            if r:
                ret_yes += is_yes
                ret_no += is_no
        judged = ret_yes + ret_no
        rows[c] = dict(wrong=ret_no / judged if judged else np.nan, returned=judged,
                       missed=1 - hit / yes if yes else np.nan, yes=yes, top=np.nan)
        # Page 1: the first PAGE judged (yes/no) items in the method's own
        # order. Only for methods that sort; 1.2.1 shows game order.
        if hasattr(method, "rank"):
            got = sorted((v for v in labels if method(v, c)), key=lambda v: -method.rank(v, c))
            judged_top = [c in labels[v]["yes"] for v in got if c in labels[v]["yes"] or c not in labels[v]["unsure"]][:PAGE]
            rows[c]["top"] = 1 - np.mean(judged_top) if judged_top else np.nan
    coloured = [v for v, l in labels.items() if l["yes"]]
    lost = sum(not any(method(v, c) for c in labels[v]["yes"]) for v in coloured)
    return rows, lost / len(coloured), len(coloured)


def whole_game_unfindable(method, data, colours):
    disp = cc._display_types()
    vids = [v for v in data if disp.get(v) in SLOTS]
    return sum(not any(method(v, c) for c in colours) for v in vids) / len(vids)


def sweep_pages(labels, colours):
    """What the player actually saw: each in-game sweep page (current matcher,
    see /tmpalette capture sweep), scored by its labelled tiles."""
    out = {c: [0, 0] for c in colours}   # [judged, no]
    per = {}
    for rec, _ in cc.load_pages():
        sw = rec.get("sweep")
        if not isinstance(sw, dict):
            continue
        c = sw["filter"][2:]
        for t in rec["tiles"]:
            l = labels.get(int(t[0]))
            if not l or c in l["unsure"]:
                continue
            no = c not in l["yes"]
            out[c][0] += 1
            out[c][1] += no
            d = per.setdefault((c, sw["slot"]), [0, 0])
            d[0] += 1
            d[1] += no
    return out, per


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdout", action="store_true", help="score the held-back half (do this once, at the end)")
    ap.add_argument("--game", action="store_true", help="also compute whole-game unfindable (slow)")
    ap.add_argument("--candidate", action="append", default=[], help="a match_v2 palette file to score too")
    ap.add_argument("--fold", type=int, choices=(0, 1), help="score only this fold of the tuning half")
    args = ap.parse_args()

    spec = json.loads((HERE / "labels.json").read_text())
    colours = spec["colours"]
    labels = {int(v): l for v, l in spec["labels"].items() if l["holdout"] == args.holdout}
    if args.fold is not None:
        from fit_v2 import fold_of
        labels = {v: l for v, l in labels.items() if fold_of(v) == args.fold}
    data = nc.parse()
    methods = [("1.2.1", legacy_method(data)), ("current", current_method(data))]
    methods += [(Path(c).stem[-8:], v2_method(data, c)) for c in args.candidate]

    print(f"{'holdout' if args.holdout else 'tuning'} half: {len(labels)} labelled appearances\n")
    results = [(name, *score(m, labels, colours)) for name, m in methods]
    print(f"{'':8s}" + "".join(f"{n + ' wrong':>15s}{n + ' missed':>16s}" for n, *_ in results) + "   (yes / returned)")
    for c in colours:
        cells = ""
        for _, rows, _, _ in results:
            r = rows[c]
            w = f"{r['wrong']:.0%}" if not np.isnan(r["wrong"]) else "-"
            cells += f"{w:>15s}{r['missed']:>16.0%}"
        print(f"{c:8s}{cells}   ({results[0][1][c]['yes']} / " + ", ".join(str(r[1][c]["returned"]) for r in results) + ")")
    print()
    for name, rows, _, _ in results:
        if not np.isnan(rows[colours[0]]["top"]):
            print(f"{name:8s} wrong among its best {PAGE}: " + "  ".join(
                f"{c} {rows[c]['top']:.0%}" if not np.isnan(rows[c]["top"]) else f"{c} -" for c in colours))
    print()
    for name, rows, lost, n in results:
        w = np.nanmean([r["wrong"] for r in rows.values()])
        mi = np.nanmean([r["missed"] for r in rows.values()])
        print(f"{name:8s} mean wrong {w:.0%}  mean missed {mi:.0%}  lost {lost:.0%} of {n} obviously coloured items")
    out, per = sweep_pages(labels, colours)
    print("\nIN GAME, page 1 as seen (current matcher), clearly wrong / judged:")
    print("  " + "  ".join(f"{c} {n}/{j}" + (f" {n / j:.0%}" if j else "") for c, (j, n) in out.items()))
    tj, tn = sum(v[0] for v in out.values()), sum(v[1] for v in out.values())
    print(f"  overall {tn}/{tj} = {tn / tj:.0%} of judged page-1 tiles are clearly the wrong colour")
    if args.game:
        for name, m in methods:
            print(f"{name:8s} whole-game unfindable {whole_game_unfindable(m, data, colours):.1%}")


if __name__ == "__main__":
    main()
