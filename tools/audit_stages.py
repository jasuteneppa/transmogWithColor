"""Where in the pipeline does a colour get lost?

Every tuning attempt so far has changed a constant and looked at the score. That
cannot tell you WHICH STAGE is wrong, so it degenerates into guessing -- and a
colour can be lost at four different places, each needing an opposite fix:

  1. IN THE TEXTURE     is the colour even there, by a dumb pixel count?
  2. CHROMA FLOOR       did those pixels survive _chroma_floor, or get filed as
                        having no hue and dumped into the greyscale bands?
  3. PEAK FINDING       did the surviving pixels form a peak, or get swallowed by
                        a neighbouring peak's suppression radius?
  4. RANKING            was a cluster of that colour emitted but beaten to
                        "main" by another cluster's salience?

Stage 1 failing means the appearance genuinely isn't that colour and the label
is wrong. Stage 2 is the chroma floor. Stage 3 is HUE_SUPPRESS_DEGREES. Stage 4
is ColorSalience in Palette.lua, which is Lua and needs no re-profiling at all.

Usage:
    python audit_stages.py            # audits whichever family scores worst
    python audit_stages.py gold       # audits one family
"""
import pickle
import sys
from collections import Counter
from pathlib import Path

import analyze_grain as ag
import analyze_names as an
import generate_color_data as gcd
import score_overrides as so

HERE = Path(__file__).resolve().parent
SHIPPED = HERE.parent / "TransmogPalette" / "ColorData.lua"
PAIRS_CACHE = HERE / "visual_pairs.pkl"

# HSV hue spans, mirroring Palette.lua's HUE_BANDS grouped to families.
FAMILY_HUE = {
    "red": [(345, 360), (0, 18)], "brown": [(18, 32)], "gold": [(32, 58)],
    "green": [(58, 155)], "blue": [(155, 250)], "purple": [(250, 325)],
    "pink": [(325, 345)],
}
VISIBLE_S, VISIBLE_V = 0.20, 0.20


def in_family(h, s, v, family):
    if s < VISIBLE_S or v < VISIBLE_V:
        return False
    return any(lo <= h < hi for lo, hi in FAMILY_HUE[family])


def visual_pairs():
    """visualID -> [(texture_fdid, model_fdid, tex_index), ...]."""
    if not PAIRS_CACHE.exists():
        sys.exit(f"No {PAIRS_CACHE.name}. It is written by the subset harness;\n"
                 "regenerate it or pass one in.")
    with open(PAIRS_CACHE, "rb") as f:
        return pickle.load(f)


_STAGE_CACHE = {}


def texture_stage_counts(fdid, family):
    """(visible-in-family share, share of those surviving the chroma floor)."""
    key = (fdid, family)
    if key in _STAGE_CACHE:
        return _STAGE_CACHE[key]
    _STAGE_CACHE[key] = result = _texture_stage_counts(fdid, family)
    return result


def _texture_stage_counts(fdid, family):
    try:
        img = gcd.fetch_texture(fdid, None)
    except Exception:
        return None
    img = img.convert("RGBA").point(gcd._QUANT_LUT)
    colors = img.getcolors(1 << 20) or []
    import colorsys
    import math
    total = fam = survived = 0.0
    for count, (r, g, b, a) in colors:
        if a == 0:
            continue
        total += count
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if not in_family(h * 360, s, v, family):
            continue
        fam += count
        L, a_star, b_star = gcd._rgb_to_lab(r, g, b)
        chroma = math.hypot(a_star, b_star)
        hue_lab = math.degrees(math.atan2(b_star, a_star)) % 360.0
        if chroma >= gcd._chroma_floor(L, hue_lab):
            survived += count
    if not total:
        return None
    return fam / total, (survived / fam if fam else 0.0)


def main():
    ag.COLOR_DATA = SHIPPED
    data = ag.parse()

    truth = {}
    for entries in so.parse_overrides(so.DEFAULT_SV).values():
        for vid, spec in entries.items():
            c = data.get(vid)
            if not c or "main" not in spec:
                continue
            fam = so.family_of(spec["main"], c)
            if fam:
                truth[vid] = fam

    pairs = visual_pairs()
    only = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] != "all" else None
    if only and only not in FAMILY_HUE:
        sys.exit(f"'{only}' is not a hue family: {', '.join(FAMILY_HUE)}")

    def audit(family):
        """(rows, stage counter) for every appearance labelled `family`."""
        rows, stages = [], Counter()
        for vid in sorted(v for v, t in truth.items() if t == family):
            clusters = data.get(vid) or []
            got = an.classify_main(clusters)[0] if clusters else "?"

            # stage 3/4: is a cluster of this family emitted at all?
            emitted = [c for c in clusters if not ag.is_neutral(c[1], c[2], c[4])
                       and in_family(c[0], c[1], c[2], family)]

            # stage 1/2: in the pixels, and surviving the chroma floor? EVERY
            # texture, not the first few -- an early cap here would report a
            # colour as missing when it is simply on another texture.
            share = survive = None
            for tex_fdid, _m, _i in pairs.get(vid, []):
                r = texture_stage_counts(tex_fdid, family)
                if r and (share is None or r[0] > share):
                    share, survive = r

            if share is None:
                verdict = "no texture"
            elif share < 0.05:
                verdict = "1 not in texture"
            elif survive is not None and survive < 0.35:
                verdict = "2 chroma floor"
            elif not emitted:
                verdict = "3 peak lost"
            elif got != family:
                verdict = "4 ranking"
            else:
                verdict = "ok"
            stages[verdict] += 1
            rows.append((vid, got, share, survive, len(emitted), verdict))
        return rows, stages

    STAGES = ["ok", "1 not in texture", "2 chroma floor", "3 peak lost",
              "4 ranking", "no texture"]

    if only:
        rows, stages = audit(only)
        print(f"auditing {len(rows)} appearances you labelled '{only}'\n")
        print(f"{'visual':>8} {'says':>7} {'in tex':>7} {'survive':>8} "
              f"{'clust':>6}  where it is lost")
        for vid, got, share, survive, n, verdict in rows:
            s = f"{share:>6.0%}" if share is not None else "     -"
            sv = f"{survive:>7.0%}" if survive is not None else "      -"
            print(f"{vid:>8} {got:>7} {s} {sv} {n:>6}  {verdict}")
        print(f"\n=== where '{only}' is lost ===")
        for verdict, n in stages.most_common():
            print(f"   {verdict:<18} {n:>3}  ({n/max(1,len(rows)):.0%})")
    else:
        # The whole picture at once: one row per colour you labelled, so a fix
        # aimed at one stage can be weighed against every colour it touches.
        print("where each colour you named is lost, across every label\n")
        print(f"{'you said':<9}{'n':>4}" + "".join(f"{s.split(' ',1)[-1][:11]:>13}"
                                                  for s in STAGES))
        grand = Counter()
        for fam in FAMILY_HUE:
            rows, stages = audit(fam)
            if not rows:
                continue
            grand.update(stages)
            cells = "".join(f"{stages.get(s, 0):>13}" for s in STAGES)
            print(f"{fam:<9}{len(rows):>4}{cells}")
        n = sum(grand.values())
        print(f"{'TOTAL':<9}{n:>4}" + "".join(f"{grand.get(s, 0):>13}" for s in STAGES))
        print(f"{'':<13}" + "".join(f"{grand.get(s, 0)/max(1,n):>12.0%} " for s in STAGES))

    print("\n1 = the colour isn't in the texture we analysed")
    print("      -- either the label is wrong, or we resolved the WRONG texture")
    print("2 = _chroma_floor is eating it        -> re-profile needed")
    print("3 = HUE_SUPPRESS_DEGREES swallowed it -> offline, seconds")
    print("4 = ColorSalience picked another main -> Lua only, no rebuild")


if __name__ == "__main__":
    main()
