"""The final check, on the HOLDOUT half of labels.json -- labels no model,
cutoff or tuning step has ever seen. Run it once per finished change.

Scores the addon as it ships: an appearance with learned scores
(TransmogPalette/ColorScores.lua) is returned by a colour when its byte is at
least 128; any other appearance falls back to closeness matching
(match_v2 with tools/palette_v2.json, i.e. Swatches.lua). Side by side with
closeness matching alone and with 1.2.1's one bucket per appearance.

    python benchmark/holdout_check.py
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import match_v2 as mv  # noqa: E402
import naming_compare as nc  # noqa: E402
from score import legacy_method  # noqa: E402

SCORES = HERE.parent.parent / "TransmogPalette" / "ColorScores.lua"


def load_scores():
    text = SCORES.read_text(encoding="utf-8")
    groups = re.search(r"ns\.ColorScoreGroups = \{([^}]*)\}", text).group(1)
    groups = [g.strip().strip('"')[2:] for g in groups.split(",")]
    out = {}
    for m in re.finditer(r'\[(\d+)\] = "((?:\\\d{3})+)"', text):
        out[int(m.group(1))] = [int(b) for b in re.findall(r"\\(\d{3})", m.group(2))]
    return groups, out


def report(name, returns, labels, colours):
    per, ret = {}, {}
    for c in colours:
        tp = fp = fn = 0
        for v, l in labels.items():
            r = returns(v, c)
            ret[v, c] = r
            y, no = c in l["yes"], c not in l["yes"] and c not in l["unsure"]
            tp += r and y
            fp += r and no
            fn += (not r) and y
        per[c] = (tp, fp, fn)
    tp = sum(p[0] for p in per.values()); fp = sum(p[1] for p in per.values()); fn = sum(p[2] for p in per.values())
    colr = [v for v, l in labels.items() if l["yes"]]
    lost = sum(not any(ret[v, c] for c in labels[v]["yes"]) for v in colr) / len(colr)
    print(f"{name:28s} wrong {fp / max(tp + fp, 1):3.0%} missed {fn / max(tp + fn, 1):3.0%} lost {lost:3.0%} | "
          + " ".join(f"{c[:4]} {p[1] / max(p[0] + p[1], 1):.0%}/{p[2] / max(p[0] + p[2], 1):.0%}" for c, p in per.items()))


def main():
    spec = json.loads((HERE / "labels.json").read_text())
    colours = spec["colours"]
    labels = {int(v): l for v, l in spec["labels"].items() if l["holdout"]}
    groups, scores = load_scores()
    data = nc.parse()
    labels = {v: l for v, l in labels.items() if v in data or v in scores}
    closeness = mv.Matcher(mv.load(HERE.parent / "palette_v2.json"), data)
    legacy = legacy_method(data)

    def shipped(v, c):
        if v in scores:
            b = scores[v][:len(groups)]
            j = groups.index(c)
            # Matching.lua Fallback: matching no colour, an appearance joins its closest
            return b[j] >= 128 or (max(b) < 128 and b.index(max(b)) == j)
        return v in data and closeness(v, c)

    n_sc = sum(v in scores for v in labels)
    print(f"HOLDOUT: {len(labels)} labelled appearances, {n_sc} with learned scores, {len(labels) - n_sc} on fallback\n")
    report("1.2.1 (one bucket)", lambda v, c: v in data and legacy(v, c), labels, colours)
    report("closeness matching only", lambda v, c: v in data and closeness(v, c), labels, colours)
    report("SHIPPED (scores + fallback)", shipped, labels, colours)
    scored = {v: l for v, l in labels.items() if v in scores}
    print()
    report("  scored items only", shipped, scored, colours)
    report("  same items, closeness", lambda v, c: v in data and closeness(v, c), scored, colours)


if __name__ == "__main__":
    main()
