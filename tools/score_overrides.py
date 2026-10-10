"""Scores the classifier against colours YOU named in game.

The addon already has the right labelling tool: the override picker. Right-click
an appearance in the Transmogrifier, pick the colour it should have been, and
that lands in SavedVariables as visualID -> {h,s,v}. This reads those back and
treats each one as ground truth.

WHY THIS BEATS EVERYTHING ELSE HERE. The item-name key (analyze_names.py) is
wrong about a third of the time, and this session established that it is
exhausted -- four separate changes scored well against it and were wrong:

  * the orange/gold band edge, which improved the score and made the orange and
    gold filters return the same-looking armour
  * a lit 3D render, which improved the score by darkening everything into the
    black bucket
  * chroma-weighting colorFirst, which improved the score by calling a third of
    the game greyscale
  * intensity reweighting, which moved nothing at all

Every one of those beat a proxy that could not see what was wrong. An override
you set while looking at the item in game has no such gap.

label_sheets.py renders contact sheets, which is faster per item, but it can
only draw items with their own model -- cloaks, shoulders, helms, weapons. The
override picker works in EVERY slot, including the component ones (chest, legs,
hands, wrist, feet) that make up most of the wardrobe and most of the
complaints. Prefer this.

WORKFLOW

  1. /tmpalette override dev
       Sends what you set to the `authorOverrides` layer, keeping your own
       personal corrections in `colorOverrides` untouched.
  2. Open the Transmogrifier, pick a slot, turn on one colour filter.
  3. For anything that does not belong, right-click it and name the colour it
       should have been. Skip anything genuinely multi-coloured -- a guess is
       worse than no label.
  4. /reload            (SavedVariables is only written on reload or logout)
  5. python score_overrides.py

Aim for a few hundred spread across slots and colours. Labelling only the
mistakes gives a biased set that cannot produce an accuracy figure -- it is
still perfectly good for asking "does this change fix the things I flagged",
which is the question that actually matters.
"""
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import analyze_grain as ag
import analyze_names as an

DEFAULT_SV = Path(r"C:\Program Files (x86)\World of Warcraft\_retail_\WTF"
                  r"\Account\SP0RSK\SavedVariables\TransmogPalette.lua")


def _block(text, key):
    """The balanced {...} body of ["key"] = { ... }, or None."""
    m = re.search(r'\["%s"\]\s*=\s*\{' % re.escape(key), text)
    if not m:
        return None
    i, depth, start = m.end() - 1, 0, m.end()
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i]
        i += 1
    return None


def _side(body, name):
    """['main'] or ['accent'] as a cluster index, an (h,s,v,achro) tuple, or None."""
    m = re.search(r'\["%s"\]\s*=\s*' % name, body)
    if not m:
        return None
    rest = body[m.end():].lstrip()
    if rest.startswith("{"):
        depth, i = 0, 0
        while i < len(rest):
            if rest[i] == "{":
                depth += 1
            elif rest[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        nums = re.findall(r"(-?\d+\.?\d*(?:e-?\d+)?|true|false)", rest[1:i])
        if len(nums) < 3:
            return None
        h, s, v = (float(x) for x in nums[:3])
        achro = len(nums) > 3 and nums[3] == "true"
        return (h, s, v, achro)
    num = re.match(r"(\d+)", rest)
    return int(num.group(1)) if num else None


def parse_overrides(path):
    """{layer: {visualID: {'main': spec, 'accent': spec}}}"""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    out = {}
    for layer in ("authorOverrides", "colorOverrides"):
        body = _block(text, layer)
        if not body:
            continue
        entries = {}
        for m in re.finditer(r"\[(\d+)\]\s*=\s*\{", body):
            vid, i, depth, start = int(m.group(1)), m.end() - 1, 0, m.end()
            while i < len(body):
                if body[i] == "{":
                    depth += 1
                elif body[i] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            inner = body[start:i]
            spec = {}
            for side in ("main", "accent"):
                s = _side(inner, side)
                if s is not None:
                    spec[side] = s
            if spec:
                entries[vid] = spec
        if entries:
            out[layer] = entries
    return out


def family_of(spec, clusters):
    """The broad-grain family an override names, or None if unresolvable."""
    if isinstance(spec, int):
        if spec < 1 or spec > len(clusters):
            return None
        c = clusters[spec - 1]
        return ag.classify(c[0], c[1], c[2], an.FAMILY, 1, c[4])
    h, s, v, achro = spec
    return ag.classify(h, s, v, an.FAMILY, 1, achro)


def parse_sample(path):
    """The visualIDs /tmpalette sample drew at random, as a set.

    These are the only labels that can answer "is this better". Everything else
    in the override store was recorded because it looked WRONG, which makes it a
    list of one classifier's failures -- any replacement scores well on it
    regardless of merit. Keep the two apart.
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    body = _block(text, "sampleVisuals")
    if not body:
        return set()
    return {int(m.group(1)) for m in re.finditer(r"\[(\d+)\]\s*=", body)}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sample_only = "--sample" in sys.argv
    path = Path(args[0]) if args else DEFAULT_SV
    if not path.exists():
        sys.exit(f"No SavedVariables at {path}\nPass the path as an argument.")

    sample = parse_sample(path)
    if sample_only:
        if not sample:
            sys.exit("No random sample found. In game: /tmpalette sample on, "
                     "browse every slot,\nlabel what it shows, /reload, then rerun.")
        print(f"Scoring against the RANDOM sample only ({len(sample)} drawn).\n"
              "This is the one key here that can go down as well as up.\n")
    elif sample:
        print(f"NOTE: {len(sample)} appearances were drawn at random by "
              f"/tmpalette sample.\nPass --sample to score against only those "
              f"-- the numbers below mix them with\nlabels chosen because they "
              f"looked wrong, which no change can fail against.\n")

    layers = parse_overrides(path)
    if not layers:
        print("No overrides found yet. See the workflow in this file's docstring:")
        print("  /tmpalette override dev, correct some items, /reload, rerun.")
        return

    data = ag.parse()
    for layer, entries in layers.items():
        if sample_only:
            entries = {v: s for v, s in entries.items() if v in sample}
            if not entries:
                continue
        labels, unresolved = {}, 0
        for vid, spec in entries.items():
            clusters = data.get(vid)
            # An accent-only override says nothing about the main colour, and an
            # appearance with no colour data cannot be scored either way.
            if not clusters or "main" not in spec:
                unresolved += 1
                continue
            fam = family_of(spec["main"], clusters)
            if fam:
                labels[vid] = fam
            else:
                unresolved += 1

        print(f"\n=== {layer}: {len(entries)} override(s), "
              f"{len(labels)} usable as labels"
              + (f", {unresolved} unresolvable" if unresolved else "") + " ===")
        if not labels:
            continue

        per = defaultdict(lambda: [0, 0])
        ok = 0
        wrong = Counter()
        for vid, truth in labels.items():
            got, _ = an.classify_main(data[vid])
            per[truth][1] += 1
            if got == truth:
                ok += 1
                per[truth][0] += 1
            else:
                wrong[(got, truth)] += 1

        print(f"classifier agrees with you on {ok}/{len(labels)} = "
              f"{ok/len(labels):.0%}")
        print("\nNOTE: if you only labelled items that looked WRONG, a low score "
              "here is expected\nand meaningless. What matters is whether a "
              "change moves it up.")
        print(f"\n{'you said':<9}{'n':>5}{'classifier agreed':>19}")
        for fam, (o, t) in sorted(per.items(), key=lambda kv: -kv[1][1]):
            print(f"{fam:<9}{t:>5}{o/t:>18.0%}")
        if wrong:
            print("\nmost common disagreements (classifier -> you):")
            for (got, truth), n in wrong.most_common(10):
                print(f"   {got:>7} -> {truth:<7} {n}")


if __name__ == "__main__":
    main()
