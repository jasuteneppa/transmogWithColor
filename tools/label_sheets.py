"""Renders items onto contact sheets so their colours can be named by hand.

WHY THIS EXISTS. Item names give a free answer key (analyze_names.py) but about
a third of them are wrong, and every method scored against it lands between 22%
and 25% -- that band is the key's ceiling, not a fact about any method. To
choose between two reasonable rules, the key has to be right, and the only way
to get a right one is to look at the armour and say what colour it is.

Five minutes with the first sheet found more than a day of statistics did: the
gold-band bug visible twice on one page, several plainly mislabelled items, and
the fact that many appearances have no main colour at all ("Spines of the
Vermillion" is red and yellow and green). That last one matters: when an item
has no answer, leave the row blank rather than guessing. A blank is data. A
coin-flip is poison.

USAGE

    python label_sheets.py                     # 120 items -> sheets + labels.csv
    python label_sheets.py --count 300
    python label_sheets.py --family gold       # only items the addon calls gold
    python label_sheets.py --disagree          # only where addon and name differ

Then open the PNGs, and for each numbered tile write the colour you'd actually
call it into the your_answer column of labels.csv. Valid answers are the eleven
broad families: red brown orange gold green blue purple pink black gray white.
Score what you wrote with:

    python analyze_names.py --hand labels.csv

COVERAGE LIMIT. Only items with their own model can be drawn -- cloaks,
shoulders, helms and weapons. Chests, legs, gloves and boots are component
textures on the character body and are skipped entirely, so these sheets skew
toward weapons and away from the armour that matters most. See m2_render's
docstring. Labelling the component slots means doing it in game.
"""
import argparse
import csv
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw

import analyze_grain as ag
import analyze_names as an
import generate_color_data as g
import m2_render

HERE = Path(__file__).resolve().parent
COLS, CELL, GAP, CAPTION = 6, 150, 26, 34
BG, TILE_BG, TEXT, DIM = (24, 24, 28), (44, 44, 50), (222, 222, 226), (140, 140, 148)


def build_sheet(tiles, path):
    rows = (len(tiles) + COLS - 1) // COLS
    sheet = Image.new("RGB", (COLS * (CELL + GAP) + GAP,
                              rows * (CELL + GAP + CAPTION) + GAP), BG)
    draw = ImageDraw.Draw(sheet)
    for i, (img, idx, name, addon) in enumerate(tiles):
        x = GAP + (i % COLS) * (CELL + GAP)
        y = GAP + (i // COLS) * (CELL + GAP + CAPTION)
        cell = Image.new("RGB", (CELL, CELL), TILE_BG)
        cell.paste(img, (0, 0), img)
        sheet.paste(cell, (x, y))
        draw.text((x + 2, y + CELL + 3), f"{idx}. {name[:26]}", fill=TEXT)
        draw.text((x + 2, y + CELL + 16), f"addon says {addon}", fill=DIM)
    sheet.save(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", type=int, default=120)
    ap.add_argument("--family", help="Only items the addon currently calls this")
    ap.add_argument("--disagree", action="store_true",
                    help="Only items where the addon and the item name conflict. "
                         "Densest in real errors, but a BIASED sample -- never "
                         "quote an accuracy figure off one.")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", type=Path, default=HERE / "labels")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    data = ag.parse()
    names, item_to_visual = an.load_names()
    name_labels, _ = an.build_labels(names, item_to_visual)

    example = {}
    for item_id, name in names.items():
        for vid in item_to_visual.get(item_id, ()):
            example.setdefault(vid, name)

    print("loading model/texture tables...")
    ia, di, mbd, tbm = g.build_lookup_tables(None)
    mbdisp = g.load_model_files()
    if not mbdisp:
        sys.exit("ModelFileData.csv is not cached; nothing can be rendered.")

    pool = list(data)
    random.Random(args.seed).shuffle(pool)

    tiles, rows, tried = [], [], 0
    for vid in pool:
        if len(tiles) >= args.count:
            break
        tried += 1
        addon, _ = an.classify_main(data[vid])
        if args.family and addon != args.family:
            continue
        if args.disagree and name_labels.get(vid) in (None, addon):
            continue
        model, skin, textures = m2_render.resolve(vid, ia, di, mbd, tbm, mbdisp)
        if model is None:
            continue  # component slot, or an unparseable model
        try:
            img = m2_render.render(model, skin, textures, res=CELL, exposure=1.25)
        except Exception:  # noqa: BLE001 - a bad model must not stop the sheet
            continue
        if img is None:
            continue
        idx = len(tiles) + 1
        label = example.get(vid, f"visual {vid}")
        tiles.append((img, idx, label, addon))
        rows.append({"index": idx, "visualID": vid, "item_name": label,
                     "addon_says": addon, "name_says": name_labels.get(vid, ""),
                     "your_answer": ""})
        if len(tiles) % 30 == 0:
            print(f"  {len(tiles)}/{args.count} rendered ({tried} examined)")

    if not tiles:
        sys.exit("Nothing renderable matched those filters.")

    per_sheet = COLS * 5
    for s in range(0, len(tiles), per_sheet):
        path = args.out / f"sheet_{s // per_sheet + 1:02d}.png"
        build_sheet(tiles[s:s + per_sheet], path)
        print(f"wrote {path}")

    csv_path = args.out / "labels.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["index", "visualID", "item_name",
                                           "addon_says", "name_says", "your_answer"])
        w.writeheader()
        w.writerows(rows)

    agree = sum(1 for r in rows if r["name_says"] and r["name_says"] == r["addon_says"])
    named = sum(1 for r in rows if r["name_says"])
    print(f"\nwrote {csv_path} -- {len(rows)} rows to fill in")
    print(f"of these, {named} carry an item-name label; the addon agrees with "
          f"{agree} of them")
    print("\nValid answers: " + " ".join(sorted(
        set(ag.HUE_GROUPS.values()) | {"black", "gray", "white"})))
    print("Leave a row BLANK if the item genuinely has no single main colour.")
    print(f"Then: python analyze_names.py --hand {csv_path}")


if __name__ == "__main__":
    main()
