"""What fraction of a real client's appearances does ColorData.lua cover?

ColorData is built from every ItemAppearance row in the game's DB2 data, not
from any one character's collection, so coverage should be independent of how
much a player owns. This checks that claim against an actual client: the
recorded exportedVisuals table in SavedVariables is every appearance the
Transmogrifier listed while browsing, collected or not.

An uncovered appearance is not broken, but it can never match a colour -- the
filter hides it while a filter is active, and the roller never picks it.

    python check_coverage.py "<path to SavedVariables\\TransmogPalette.lua>"
"""
import re
import sys
from pathlib import Path

ADDON = Path(__file__).resolve().parent.parent / "TransmogPalette"


def color_data_ids():
    text = (ADDON / "ColorData.lua").read_text(encoding="utf-8", errors="replace")
    return {int(m.group(1)) for m in re.finditer(r"\[(\d+)\]\s*=\s*\"", text)}


def recorded_ids(sv_path):
    """exportedVisuals maps visualID -> itemID. WoW's SavedVariables writer
    emits the dense part positionally (bare values and `nil,` placeholders) and
    the sparse part as [key] = value, so both forms have to be handled or the
    positional ids are silently missed."""
    text = Path(sv_path).read_text(encoding="utf-8", errors="replace")
    m = re.search(r'\["exportedVisuals"\]\s*=\s*\{', text)
    if not m:
        return set()

    i, depth, start = m.end() - 1, 0, m.end()
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    body = text[start:i]

    ids, index = set(), 0
    for tok in body.split(","):
        tok = tok.strip()
        if not tok:
            continue
        kv = re.match(r"\[(\d+)\]\s*=\s*(.+)", tok)
        if kv:
            ids.add(int(kv.group(1)))
            continue
        index += 1
        if tok != "nil":
            ids.add(index)
    return ids


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    have = color_data_ids()
    seen = recorded_ids(sys.argv[1])
    if not seen:
        print("no exportedVisuals recorded in that SavedVariables file")
        return

    covered = seen & have
    missing = seen - have
    print(f"ColorData.lua entries:        {len(have):>7}")
    print(f"appearances seen by client:   {len(seen):>7}")
    print(f"  covered:                    {len(covered):>7}  ({100*len(covered)/len(seen):.2f}%)")
    print(f"  no colour data:             {len(missing):>7}  ({100*len(missing)/len(seen):.2f}%)")

    if missing:
        lo = sorted(missing)
        print(f"\nuncovered visualID range: {lo[0]} .. {lo[-1]}")
        # If the misses cluster at high ids, they are appearances added after
        # the data was generated -- a content-patch problem, not a player one.
        cutoff = sorted(have)[-1]
        newer = sum(1 for v in missing if v > cutoff)
        print(f"newer than the highest id in ColorData ({cutoff}): {newer}")


if __name__ == "__main__":
    main()
