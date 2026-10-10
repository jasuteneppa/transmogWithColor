"""Checks the FILTER's new grain machinery: ns.GrainBuckets and the
broad<->fine selection translation in Palette.lua.

Mirrors the Lua, exactly like analyze_grain.py does, and imports its classifier
so there is one source of truth rather than a fourth drifting copy.

Run after touching ns.GrainBuckets, TranslateKeys, ns.SetFilterGrain, HUE_BANDS,
HUE_GROUPS or the canonical tables.
"""
import sys
from collections import defaultdict

from analyze_grain import (
    HUE_BANDS, HUE_GROUPS, canonical, classify, parse, main_and_accent,
)

BAND_NAMES = [name for _, name in HUE_BANDS]
VALUE_SUFFIXES = {1: [""], 2: ["dark", "light"], 3: ["dark", "mid", "light"]}

# grain -> (hue_fn, value_bands), mirroring GRAINS in Palette.lua.
GRAINS = {
    "fine":   (lambda b: b, 3),
    "medium": (lambda b: HUE_GROUPS[b], 3),
    "coarse": (lambda b: HUE_GROUPS[b], 2),
    "broad":  (lambda b: HUE_GROUPS[b], 1),
}


def grain_buckets(grain):
    """Mirrors ns.GrainBuckets."""
    hue_fn, values = GRAINS[grain]
    keys = ["black", "gray", "white"]
    bands, seen = [], set()
    for name in BAND_NAMES:
        band = hue_fn(name)
        if band not in seen:
            seen.add(band)
            bands.append(band)
    for band in bands:
        for suffix in VALUE_SUFFIXES[values]:
            keys.append(band if suffix == "" else f"{band}_{suffix}")
    return keys


def classify_at(grain, h, s, v, achromatic):
    hue_fn, values = GRAINS[grain]
    return classify(h, s, v, hue_fn, values, achromatic)


def translate(selected, old_grain, new_grain):
    """Mirrors TranslateKeys: union of both probe directions."""
    if not selected:
        return set()
    out = set()
    for key in grain_buckets(new_grain):
        c = canonical(key)
        if c and classify_at(old_grain, *c) in selected:
            out.add(key)
    for key in selected:
        c = canonical(key)
        if c:
            out.add(classify_at(new_grain, *c))
    return out


def main():
    failures = []

    # 1. Every key GrainBuckets emits must be one the classifier can actually
    #    produce, and every key the classifier produces must be in the list.
    #    A key in one and not the other is a swatch that can never match, or a
    #    bucket with no swatch to reach it.
    items = parse()
    print(f"parsed {len(items)} appearances\n")

    for grain in ("broad", "coarse", "medium", "fine"):
        declared = grain_buckets(grain)
        assert len(declared) == len(set(declared)), f"{grain}: duplicate keys"

        produced = defaultdict(int)
        for ranks in items.values():
            main_c, _ = main_and_accent(ranks)
            if main_c:
                key = classify_at(grain, main_c[0], main_c[1], main_c[2], main_c[4])
                produced[key] += 1

        missing = sorted(set(produced) - set(declared))
        empty = sorted(set(declared) - set(produced))
        status = "ok " if not missing else "FAIL"
        if missing:
            failures.append(f"{grain}: classifier produces keys not in GrainBuckets: {missing}")
        print(f"{status} {grain:7s} {len(declared):3d} declared, "
              f"{len(produced):3d} occur, never-occurring: {empty or 'none'}")

    print()

    # 2. Canonical round-trip. The strip draws an EMPTY bucket using its
    #    canonical colour, so if that colour classifies into a different bucket
    #    the swatch advertises a colour it does not filter for.
    for grain in ("broad", "fine"):
        bad = []
        for key in grain_buckets(grain):
            c = canonical(key)
            if c is None:
                bad.append((key, "no canonical colour"))
            elif classify_at(grain, *c) != key:
                bad.append((key, f"round-trips to {classify_at(grain, *c)}"))
        status = "ok  " if not bad else "FAIL"
        if bad:
            failures.append(f"{grain}: canonical round-trip: {bad}")
        print(f"{status} {grain:7s} canonical round-trip: {len(bad)} bad")

    print()

    # 3. THE key property of the strip's grain button: switching grain must not
    #    silently change what the filter matches. Going broad -> fine must be
    #    LOSSLESS -- every appearance matching the broad pick still matches the
    #    translated fine set -- because a broad bucket is exactly the union of
    #    its fine ones and the mains are an OR'd set that can hold all of them.
    worst = None
    for broad_key in grain_buckets("broad"):
        fine_set = translate({broad_key}, "broad", "fine")
        before = after = 0
        for ranks in items.values():
            main_c, _ = main_and_accent(ranks)
            if not main_c:
                continue
            h, s, v, achro = main_c[0], main_c[1], main_c[2], main_c[4]
            if classify_at("broad", h, s, v, achro) == broad_key:
                before += 1
                if classify_at("fine", h, s, v, achro) in fine_set:
                    after += 1
        if before != after:
            failures.append(
                f"broad->fine LOSSY for '{broad_key}': {before} matched, {after} survive")
        lost = before - after
        if worst is None or lost > worst[1]:
            worst = (broad_key, lost)
        print(f"{'ok ' if before == after else 'FAIL'} broad '{broad_key:7s}' "
              f"{before:6d} appearances -> {len(fine_set)} fine keys, {after:6d} kept")

    print()

    # 4. And the reverse must be STABLE, not drifting: fine -> broad -> fine
    #    should land back where it started, or repeatedly tapping the button
    #    would widen the filter each time.
    drift = 0
    for fine_key in grain_buckets("fine"):
        b = translate({fine_key}, "fine", "broad")
        back = translate(b, "broad", "fine")
        again = translate(translate(back, "fine", "broad"), "broad", "fine")
        if back != again:
            drift += 1
            failures.append(f"round trip not stable for '{fine_key}': {back} vs {again}")
    print(f"{'ok  ' if not drift else 'FAIL'} fine->broad->fine stable for "
          f"{len(grain_buckets('fine')) - drift}/{len(grain_buckets('fine'))} keys")

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print("  " + f)
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
