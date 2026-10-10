"""Extract the visualIDs snapshotted by `/tmpalette dump` into a seed file.

The dump is one category's worth of appearances as the Transmogrifier listed
them, so it's the right input for a quick coverage test:

    python tools/dumped_to_seed.py            # writes tools/seed_dumped.txt
    python tools/generate_color_data.py --seed-file tools/seed_dumped.txt

Note the shape differs from `exportedVisuals` (visualID -> itemID): here the
table key is just an array index and the VALUE is the visualID.
"""

import re
import sys
from pathlib import Path

SAVEDVARS = Path(
    r"C:\Program Files (x86)\World of Warcraft\_retail_\WTF\Account"
    r"\SP0RSK\SavedVariables\TransmogPalette.lua"
)
OUT = Path(__file__).parent / "seed_dumped.txt"


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else SAVEDVARS
    if not path.exists():
        sys.exit(f"SavedVariables not found: {path}")

    src = path.read_text(encoding="utf-8", errors="replace")

    m = re.search(r'\["dumpedVisuals"\]\s*=\s*\{', src)
    if not m:
        sys.exit(
            "No dumpedVisuals table found. In game: open the Transmogrifier, "
            "select the slot you want, then /tmpalette dump followed by /reload."
        )

    # Walk braces from the opening one so we stop at this table's end.
    depth, start = 0, m.end() - 1
    for i in range(start, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                body = src[start + 1 : i]
                break
    else:
        sys.exit("dumpedVisuals table is unterminated — is the file mid-write?")

    # WoW serializes a sequential array as bare comma-separated values, but
    # writes `[k] = v` if the table ever became sparse. Accept either.
    visual_ids = [
        int(keyed or bare)
        for keyed, bare in re.findall(
            r"\[\s*\d+\s*\]\s*=\s*(\d+)|(\d+)\s*(?=,|\s*\})", body
        )
    ]
    # Preserve order but drop repeats; the generator treats the list as a set.
    seen, ordered = set(), []
    for v in visual_ids:
        if v not in seen:
            seen.add(v)
            ordered.append(v)

    OUT.write_text("\n".join(str(v) for v in ordered) + "\n", encoding="utf-8")
    print(f"Wrote {len(ordered)} visualIDs to {OUT}")


if __name__ == "__main__":
    main()
