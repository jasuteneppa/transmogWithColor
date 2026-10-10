"""What would PEOPLE call this colour? Crowd-sourced colour naming.

Every bucket boundary this project has shipped was placed by argument and then
judged by one person in game, one item at a time -- and the person doing the
judging found their own answers depended on what they had just looked at. Rust
looks orange after brown and brown after orange. That is a property of human
colour perception (simultaneous/successive contrast), not of the labeller, and
no amount of careful labelling by one person removes it.

This replaces the judgement with a measurement taken from a very large number
of people, each naming one colour patch in isolation:

    The XKCD colour survey (2010): ~2.7 million namings by ~200,000
    participants, as cleaned and modelled by Heer & Stone, "Color Naming
    Models for Color Selection, Image Editing and Palette Design" (CHI 2012).
    Data: https://github.com/StanfordHCI/c3 (BSD licence, see
    color_naming/LICENSE-c3).

The data is a grid of CIELAB colours at 5-unit spacing (8,325 of them, every
one named at least 56 times) with a count of how often each of 153 terms was
used for it. This folds the 153 terms onto the addon's 11 families -- which
are the 11 "basic colour terms" of colour-naming research, with gold standing
in for yellow -- and answers P(family | colour).

Probabilities rather than a single answer, on purpose: a colour that 55% of
people call brown and 45% call red IS ambiguous, and saying so is more honest
than a hard edge that flips on one unit of hue.

    import color_naming
    color_naming.family_probs_hsv([(25, 0.7, 0.45)])  # -> (1, 11) array
"""
import colorsys
import json
from pathlib import Path

import numpy as np

DATA_PATH = Path(__file__).resolve().parent / "color_naming" / "c3_data.json"

# The addon's broad buckets, in the order Palette.lua's strip shows them.
FAMILIES = ["black", "gray", "white", "red", "brown", "orange", "gold",
            "green", "blue", "purple", "pink"]
FAMILY_INDEX = {f: i for i, f in enumerate(FAMILIES)}

# Each survey term -> the family (or families) it means, as weights summing to
# 1. Most are unambiguous. The split ones are terms that genuinely straddle two
# families -- "rust", "salmon", "periwinkle" -- and are split rather than forced
# so the ambiguity carries through to the result instead of being decided here.
#
# Two mappings follow the addon rather than the dictionary:
#   - yellow is "gold". WoW's yellows are overwhelmingly gold armour.
#   - teal / cyan / turquoise / aqua are "blue", because Palette.lua groups the
#     teal band under blue and moving it to green was rejected in game
#     (see HUE_GROUPS there). Terms that are explicitly blue-AND-green split.
TERM_FAMILY = {
    # --- red
    "red": "red", "darkred": "red", "maroon": "red", "brickred": "red",
    "burgundy": "red", "crimson": "red", "brick": "red", "wine": "red",
    "bloodred": "red", "deepred": "red", "brightred": "red",
    "orangered": {"red": 0.6, "orange": 0.4},
    "pinkred": {"red": 0.6, "pink": 0.4},
    "lightred": {"red": 0.5, "pink": 0.5},
    # --- brown
    "brown": "brown", "tan": "brown", "lightbrown": "brown", "darkbrown": "brown",
    "redbrown": {"brown": 0.6, "red": 0.4},
    "orangebrown": {"brown": 0.6, "orange": 0.4},
    "yellowbrown": {"brown": 0.6, "gold": 0.4},
    "taupe": {"brown": 0.6, "gray": 0.4},
    "beige": {"brown": 0.6, "white": 0.4},
    "sand": {"brown": 0.6, "gold": 0.4},
    "khaki": {"brown": 0.5, "gold": 0.3, "green": 0.2},
    "puce": {"brown": 0.5, "pink": 0.5},
    "rust": {"brown": 0.4, "orange": 0.3, "red": 0.3},
    "burntsienna": {"brown": 0.5, "orange": 0.3, "red": 0.2},
    "terracotta": {"orange": 0.4, "brown": 0.3, "red": 0.3},
    # --- orange
    "orange": "orange", "lightorange": "orange", "darkorange": "orange",
    "burntorange": {"orange": 0.6, "brown": 0.4},
    "redorange": {"orange": 0.6, "red": 0.4},
    "yelloworange": {"orange": 0.6, "gold": 0.4},
    "peach": {"orange": 0.5, "pink": 0.5},
    # --- gold (yellow)
    "yellow": "gold", "gold": "gold", "mustard": "gold", "goldenrod": "gold",
    "darkyellow": "gold", "mustardyellow": "gold", "paleyellow": "gold",
    "lightyellow": "gold", "brightyellow": "gold",
    "ochre": {"gold": 0.6, "brown": 0.4},
    "greenyellow": {"gold": 0.5, "green": 0.5},
    # --- green
    "green": "green", "lightgreen": "green", "limegreen": "green",
    "darkgreen": "green", "brightgreen": "green", "forestgreen": "green",
    "palegreen": "green", "lime": "green", "neongreen": "green",
    "grassgreen": "green", "kellygreen": "green", "peagreen": "green",
    "springgreen": "green", "chartreuse": "green", "pastelgreen": "green",
    "armygreen": "green", "huntergreen": "green", "leafgreen": "green",
    "mossgreen": "green", "sage": "green", "applegreen": "green",
    "mint": "green", "seafoamgreen": "green", "olive": "green",
    "yellowgreen": "green", "seagreen": "green",
    "greygreen": {"green": 0.6, "gray": 0.4},
    "puke": {"green": 0.5, "brown": 0.5},
    "aquamarine": {"green": 0.5, "blue": 0.5},
    "bluegreen": {"green": 0.5, "blue": 0.5},
    "greenblue": {"blue": 0.5, "green": 0.5},
    # --- blue (teal family included, see above)
    "blue": "blue", "lightblue": "blue", "skyblue": "blue", "darkblue": "blue",
    "navyblue": "blue", "royalblue": "blue", "brightblue": "blue",
    "paleblue": "blue", "babyblue": "blue", "deepblue": "blue",
    "robinseggblue": "blue", "cerulean": "blue", "seablue": "blue",
    "steelblue": "blue", "mediumblue": "blue", "oceanblue": "blue",
    "midnightblue": "blue", "cornflowerblue": "blue", "electricblue": "blue",
    "azure": "blue", "teal": "blue", "darkteal": "blue", "lightteal": "blue",
    "turquoise": "blue", "darkturquoise": "blue", "lightturquoise": "blue",
    "cyan": "blue", "aqua": "blue",
    "greyblue": {"blue": 0.6, "gray": 0.4},
    "bluegrey": {"gray": 0.5, "blue": 0.5},
    "slate": {"gray": 0.6, "blue": 0.4},
    "slateblue": {"blue": 0.6, "purple": 0.4},
    "purpleblue": {"blue": 0.6, "purple": 0.4},
    "periwinkle": {"blue": 0.5, "purple": 0.5},
    # --- purple
    "purple": "purple", "violet": "purple", "lavender": "purple",
    "lightpurple": "purple", "darkpurple": "purple", "lilac": "purple",
    "indigo": "purple", "brightpurple": "purple", "plum": "purple",
    "royalpurple": "purple", "deeppurple": "purple", "palepurple": "purple",
    "eggplant": "purple", "neonpurple": "purple",
    "bluepurple": {"purple": 0.6, "blue": 0.4},
    "blueviolet": {"purple": 0.6, "blue": 0.4},
    "pinkpurple": {"purple": 0.6, "pink": 0.4},
    "darkmagenta": {"purple": 0.6, "pink": 0.4},
    "magenta": {"purple": 0.5, "pink": 0.5},
    "mauve": {"purple": 0.5, "pink": 0.5},
    # --- pink
    "pink": "pink", "hotpink": "pink", "darkpink": "pink", "lightpink": "pink",
    "rose": "pink", "brightpink": "pink", "palepink": "pink",
    "dustyrose": "pink", "neonpink": "pink",
    "fuchsia": {"pink": 0.6, "purple": 0.4},
    "salmon": {"pink": 0.6, "orange": 0.4},
    "coral": {"pink": 0.4, "orange": 0.3, "red": 0.3},
    "flesh": {"pink": 0.5, "orange": 0.5},
    "skin": {"pink": 0.4, "orange": 0.3, "brown": 0.3},
    # --- neutrals
    "black": "black",
    "grey": "gray", "darkgrey": "gray", "lightgrey": "gray",
    "white": "white", "offwhite": "white",
    "cream": {"white": 0.7, "gold": 0.3},
}

# Smoothing between grid points. The grid is 5 Lab units apart; a kernel of
# about one spacing blends the immediate neighbours, so a colour between two
# grid points gets a mix of both rather than snapping to the nearer one.
KERNEL_SIGMA = 5.0
K_NEAREST = 12

_model = None


def _load():
    global _model
    if _model is not None:
        return _model
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    grid = np.asarray(data["color"], dtype=np.float64).reshape(-1, 3)
    terms = data["terms"]
    n_colors, n_terms = len(grid), len(terms)

    unmapped = [t for t in terms if t not in TERM_FAMILY]
    if unmapped:
        raise ValueError(f"survey terms with no family mapping: {unmapped}")

    counts = np.zeros((n_colors, n_terms))
    flat = data["T"]
    for i in range(0, len(flat), 2):
        c, w = divmod(flat[i], n_terms)
        counts[c, w] = flat[i + 1]

    to_family = np.zeros((n_terms, len(FAMILIES)))
    for w, term in enumerate(terms):
        spec = TERM_FAMILY[term]
        if isinstance(spec, str):
            spec = {spec: 1.0}
        for fam, weight in spec.items():
            to_family[w, FAMILY_INDEX[fam]] = weight

    fam_counts = counts @ to_family
    _model = (grid, fam_counts, counts.sum(axis=1))
    return _model


def srgb_to_lab(rgb):
    """(N, 3) sRGB in 0-1 -> (N, 3) CIELAB, D65. Same white point as the C3 data
    (d3.lab) and as generate_color_data's own converter."""
    rgb = np.asarray(rgb, dtype=np.float64)
    lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124564, 0.3575761, 0.1804375],
                  [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]])
    xyz = lin @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack([116 * f[:, 1] - 16,
                     500 * (f[:, 0] - f[:, 1]),
                     200 * (f[:, 1] - f[:, 2])], axis=1)


def family_probs_lab(lab, chunk=4096):
    """(N, 3) Lab -> (N, 11) P(family), rows summing to 1, columns in FAMILIES
    order. Pools the survey counts of the nearest grid colours, Gaussian
    weighted by distance -- pooling COUNTS (not per-colour probabilities) so a
    well-sampled neighbour counts for more than a sparse one."""
    grid, fam_counts, _ = _load()
    lab = np.atleast_2d(np.asarray(lab, dtype=np.float64))
    out = np.empty((len(lab), len(FAMILIES)))
    g2 = (grid ** 2).sum(axis=1)
    for start in range(0, len(lab), chunk):
        q = lab[start:start + chunk]
        d2 = (q ** 2).sum(axis=1)[:, None] + g2[None, :] - 2 * q @ grid.T
        idx = np.argpartition(d2, K_NEAREST, axis=1)[:, :K_NEAREST]
        near = np.take_along_axis(d2, idx, axis=1).clip(min=0)
        w = np.exp(-near / (2 * KERNEL_SIGMA ** 2))
        # A colour far outside the surveyed gamut still gets its nearest
        # neighbour's answer rather than NaN.
        w[w.sum(axis=1) == 0, 0] = 1.0
        pooled = np.einsum("nk,nkf->nf", w, fam_counts[idx])
        out[start:start + chunk] = pooled / pooled.sum(axis=1, keepdims=True)
    return out


def family_probs_hsv(hsv):
    """(N, 3) of (h degrees, s 0-1, v 0-1) -> (N, 11) P(family)."""
    hsv = np.atleast_2d(np.asarray(hsv, dtype=np.float64))
    rgb = np.array([colorsys.hsv_to_rgb((h % 360) / 360.0, s, v) for h, s, v in hsv])
    return family_probs_lab(srgb_to_lab(rgb))


if __name__ == "__main__":
    # Spot checks against colours whose names are not in dispute.
    probes = {
        "pure red": (0, 1.0, 1.0), "navy": (230, 0.9, 0.35),
        "leather brown": (25, 0.65, 0.40), "rust": (18, 0.75, 0.60),
        "gold": (45, 0.80, 0.85), "orange": (30, 1.0, 1.0),
        "olive": (60, 0.7, 0.45), "teal": (180, 0.8, 0.55),
        "steel grey": (210, 0.10, 0.60), "near black": (0, 0.1, 0.08),
        "cream": (45, 0.15, 0.95), "magenta": (300, 0.9, 0.8),
    }
    probs = family_probs_hsv(list(probes.values()))
    for name, p in zip(probes, probs):
        top = np.argsort(-p)[:3]
        print(f"{name:14s} " + "  ".join(f"{FAMILIES[i]} {p[i]:.0%}" for i in top))
