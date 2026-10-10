"""How coarse should the RANDOMISER's colour buckets be?

The filter's classifier splits hue into 12 perceptual bands crossed with
dark/mid/light, which is right for filtering (you pick one known colour) and
wrong for rolling (you want a pool to draw from). Green alone becomes
olive_dark/mid/light + green_dark/mid/light -- six buckets, most of them tiny.

This measures the real distribution in ColorData.lua under the current scheme
and several coarser ones, so the grain is chosen from counts rather than taste.
Mirrors Palette.lua's ClassifyColor exactly; if that changes, change this too.

    python analyze_grain.py
"""
import math
import re
import statistics
from collections import Counter
from pathlib import Path

COLOR_DATA = Path(__file__).resolve().parent.parent / "TransmogPalette" / "ColorData.lua"

NEUTRAL_SAT_THRESHOLD = 0.15
NEUTRAL_VALUE_THRESHOLD = 0.06

# Mirrors Palette.lua. Three greyscale tones, and colour beats tone.
BLACK_MAX = 0.22
WHITE_MIN = 0.60
DEFAULT_COLOR_FIRST = 0.20


def is_neutral(s, v, achromatic):
    return achromatic or s < NEUTRAL_SAT_THRESHOLD or v < NEUTRAL_VALUE_THRESHOLD


def merge_neutrals(ranks):
    """Mirrors ns.MainAndAccent's MergeNeutrals. Greyscale arrives as up to
    three separate lightness bands; the largest band is not the item's tone."""
    bands = [c for c in ranks if is_neutral(c[1], c[2], c[4])]
    if not bands:
        return None
    total = sum(c[3] for c in bands)
    biggest = max(bands, key=lambda c: c[3])
    if len(bands) == 1 or total <= 0:
        return biggest
    value = sum(c[2] * c[3] for c in bands) / total
    return (biggest[0], biggest[1], value, total, True)


def main_and_accent(ranks, threshold=DEFAULT_COLOR_FIRST):
    """Mirrors ns.MainAndAccent: the cluster that decides the appearance's
    colour, and its accent."""
    # Ranked by total CHROMA (weight * s * v), not area -- see ns.ColorSalience.
    colors = sorted((c for c in ranks if not is_neutral(c[1], c[2], c[4])),
                    key=lambda c: -(c[3] * c[1] * c[2]))
    first = colors[0] if colors else None
    second = colors[1] if len(colors) > 1 else None
    neutral = merge_neutrals(ranks)
    # Tested against ALL the colour on the piece, not just its largest hue --
    # see the comment on ns.MainAndAccent.
    colored_total = sum(c[3] for c in colors)

    if first is not None and colored_total >= threshold:
        if second is not None and neutral is not None:
            return first, (second if second[3] >= neutral[3] else neutral)
        return first, (second if second is not None else neutral)
    if neutral is not None:
        return neutral, first
    return (first if first is not None else ranks[0]), None

HUE_BANDS = [
    # No orange band: orange and gold are one band [32,58), and the old gold
    # band's 58-70 tail went to olive. See the HUE_BANDS note in Palette.lua.
    (18, "red"), (32, "rust"), (58, "gold"),
    (100, "olive"), (155, "green"), (195, "teal"), (250, "blue"),
    (275, "indigo"), (300, "violet"), (325, "purple"), (345, "pink"),
]

# Coarse hue groups: adjacent bands that read as "the same colour" when the
# question is "give me something greenish" rather than "give me this green".
# teal groups with BLUE. Moving it to green was tried and rejected in game on
# 2026-08-11 -- see the comment on HUE_GROUPS in Palette.lua. Change both
# together.
HUE_GROUPS = {
    "red": "red", "rust": "brown",
    "gold": "gold",
    "olive": "green", "green": "green",
    "teal": "blue", "blue": "blue",
    "indigo": "purple", "violet": "purple", "purple": "purple",
    "pink": "pink",
}

# Mirrors Palette.lua's CANONICAL_* tables. A swatch is drawn as this colour
# instead of the bucket mean, so it MUST classify back into its own bucket.
CANONICAL_HUE = {
    "red": (6, 0.85), "brown": (25, 0.65), "gold": (42, 0.85),
    "green": (120, 0.75), "blue": (215, 0.80), "purple": (312, 0.70), "pink": (335, 0.70),
    "rust": (25, 0.65), "olive": (85, 0.70), "teal": (175, 0.75),
    "indigo": (262, 0.70), "violet": (287, 0.70),
}
CANONICAL_NEUTRAL = {"black": 0.10, "gray": 0.48, "white": 0.90}
CANONICAL_VALUE = {"dark": 0.34, "mid": 0.52, "light": 0.80}


def canonical(key):
    """Returns (h, s, v, achromatic) or None."""
    if key in CANONICAL_NEUTRAL:
        return 0.0, 0.0, CANONICAL_NEUTRAL[key], True
    band, _, vband = key.partition("_")
    if band not in CANONICAL_HUE:
        return None
    h, s = CANONICAL_HUE[band]
    v = CANONICAL_VALUE.get(vband) if vband else (0.45 if band == "brown" else 0.74)
    if v is None:
        return None
    if band == "brown" and vband == "light":
        v = 0.71
    return h, s, v, False


def hue_band(h):
    h %= 360
    for bound, name in HUE_BANDS:
        if h < bound:
            return name
    return HUE_BANDS[0][1]  # wraps into red


CLUSTER_BYTES = 5


def parse():
    """visualID -> list of (h, s, v, weight, achromatic), dominant first."""
    text = COLOR_DATA.read_text(encoding="utf-8", errors="replace")
    out = {}
    for m in re.finditer(r"\[(\d+)\]\s*=\s*\"((?:\\\d{3})+)\"", text):
        vid = int(m.group(1))
        raw = [int(b) for b in re.findall(r"\\(\d{3})", m.group(2))]
        clusters = []
        for i in range(0, len(raw) - CLUSTER_BYTES + 1, CLUSTER_BYTES):
            h, s, v, w, flags = raw[i:i + CLUSTER_BYTES]
            clusters.append((h * 1.5, s / 255, v / 255, w / 255, bool(flags & 1)))
        if clusters:
            out[vid] = clusters
    return out


def classify(h, s, v, hue_fn, value_bands, achromatic=False):
    """value_bands: 3 = dark/mid/light, 2 = dark/light, 1 = merged.
    Greyscale does not vary with grain -- always black/gray/white."""
    if is_neutral(s, v, achromatic):
        if v < BLACK_MAX:
            return "black"
        return "gray" if v < WHITE_MIN else "white"

    band = hue_fn(hue_band(h))
    if value_bands == 1:
        return band
    if value_bands == 3:
        if v < 0.35: vb = "dark"
        elif v < 0.65: vb = "mid"
        else: vb = "light"
    else:
        vb = "dark" if v < 0.5 else "light"
    return f"{band}_{vb}"


SCHEMES = [
    ("12 bands x 3 values (fine)", lambda b: b, 3),
    ("12 bands x 2 values", lambda b: b, 2),
    ("groups x 3 values (medium)", lambda b: HUE_GROUPS[b], 3),
    ("groups x 2 values (coarse)", lambda b: HUE_GROUPS[b], 2),
    ("groups, no value split (broad)", lambda b: HUE_GROUPS[b], 1),
]


def main():
    data = parse()
    print(f"{len(data)} appearances with colour data\n")

    for label, hue_fn, vbands in SCHEMES:
        counts = Counter()
        for clusters in data.values():
            # The appearance's MAIN colour, the same one both the filter and the
            # randomiser match on -- not rank 1, which is only the generator's
            # ranking and can be a trim sitting on a much larger neutral.
            h, s, v, _, ac = main_and_accent(clusters)[0]
            counts[classify(h, s, v, hue_fn, vbands, ac)] += 1

        sizes = sorted(counts.values())
        tiny = sum(1 for n in sizes if n < 200)
        print(f"{label}")
        print(f"   buckets={len(counts)}  median={statistics.median(sizes):.0f}  "
              f"min={sizes[0]}  max={sizes[-1]}  buckets<200={tiny}")
        greens = {k: v for k, v in counts.items() if "green" in k or "olive" in k}
        print(f"   green-ish buckets: {greens}")
        print()

    # SWATCH INVARIANT. A swatch is drawn as the circular mean of its bucket,
    # but matching is exact key equality -- so if the mean classifies into a
    # DIFFERENT bucket, the swatch shows one colour and returns another. Wider
    # buckets make this more likely, so every grain gets checked. Hue must be
    # averaged as an angle (the red band wraps through 0); a plain mean once
    # rendered the red bucket green.
    print("\nswatch invariant (mean of bucket must classify back to that bucket):")
    for label, hue_fn, vbands in SCHEMES:
        buckets = {}
        for clusters in data.values():
            h, s, v, _, ac = main_and_accent(clusters)[0]
            key = classify(h, s, v, hue_fn, vbands, ac)
            b = buckets.setdefault(key, [0.0, 0.0, 0.0, 0.0, 0, 0])
            rad = math.radians(h)
            b[0] += math.cos(rad); b[1] += math.sin(rad)
            b[2] += s; b[3] += v; b[4] += 1
            b[5] += 1 if ac else 0

        bad = []
        for key, (sx, sy, ss, sv, n, nac) in buckets.items():
            mh = math.degrees(math.atan2(sy / n, sx / n)) % 360
            # The mean inherits the bucket's majority achromatic verdict: the
            # swatch stands for the bucket, and a neutral bucket's mean must be
            # classified as a neutral or the check tests a colour that no member
            # of the bucket has.
            got = classify(mh, ss / n, sv / n, hue_fn, vbands, nac * 2 >= n)
            if got != key:
                bad.append((key, got, n))
        status = "OK" if not bad else f"{len(bad)} MISMATCH"
        print(f"   {label:32} {status}")
        for key, got, n in bad:
            print(f"      {key} -> mean classifies as {got} ({n} appearances)")

    # The specific complaint: how thin are the small chromatic buckets today?
    counts = Counter()
    for clusters in data.values():
        h, s, v, _, ac = clusters[0]
        counts[classify(h, s, v, lambda b: b, 3, ac)] += 1
    print("current scheme, 12 smallest buckets:")
    for name, n in sorted(counts.items(), key=lambda kv: kv[1])[:12]:
        print(f"   {name:16} {n}")

    # CANONICAL SWATCH CHECK. The picker draws these instead of bucket means,
    # so each must classify back into its own bucket or the swatch advertises a
    # colour that matches something else.
    print("\ncanonical swatch colours classify back to their own bucket:")
    for label, hue_fn, vbands in SCHEMES:
        keys = set()
        for clusters in data.values():
            h, s, v, _, ac = main_and_accent(clusters)[0]
            keys.add(classify(h, s, v, hue_fn, vbands, ac))
        bad = []
        for key in sorted(keys):
            c = canonical(key)
            if c is None:
                bad.append((key, "NO CANONICAL"))
                continue
            got = classify(c[0], c[1], c[2], hue_fn, vbands, c[3])
            if got != key:
                bad.append((key, got))
        print(f"   {label:32} {'OK' if not bad else str(len(bad)) + ' BAD'}")
        for key, got in bad:
            print(f"      {key} -> {got}")


if __name__ == "__main__":
    main()

