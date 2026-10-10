"""What does each appearance look like ON SCREEN, against its texture colours?

Reads the pages recorded by /tmpalette capture (see TransmogPalette/Capture.lua)
from SavedVariables, finds each page's screenshot, and cuts every appearance
tile back out. Each tile is the game's own lit render of that appearance -- the
thing a player actually looks at -- with no human judgement anywhere in it.

    python capture_calibrate.py --contact out.png   # sanity sheet of crops
    python capture_calibrate.py                     # the analysis
"""
import argparse
import re
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

WOW = Path(r"C:\Program Files (x86)\World of Warcraft\_retail_")
DEFAULT_SV = WOW / "WTF" / "Account" / "SP0RSK" / "SavedVariables" / "TransmogPalette.lua"
SCREENSHOTS = WOW / "Screenshots"


# --- a minimal reader for the Lua literal SavedVariables writes ------------

_TOKEN = re.compile(r'\s*(?:(--[^\n]*)|(\[)|(\])|(\{)|(\})|(=)|(,)|'
                    r'("(?:\\.|[^"\\])*")|(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)|'
                    r'(true|false|nil)|([A-Za-z_]\w*))')


def _tokens(text):
    pos = 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            if text[pos:].strip() == "":
                return
            raise ValueError(f"unparseable SavedVariables near {text[pos:pos + 40]!r}")
        pos = m.end()
        if m.group(1):
            continue
        for i in range(2, 12):
            if m.group(i) is not None:
                yield i, m.group(i)
                break


def _value(tok, it):
    kind, s = tok
    if kind == 4:  # {
        return _table(it)
    if kind == 9:
        return float(s) if any(c in s for c in ".eE") else int(s)
    if kind == 8:
        return bytes(s[1:-1], "utf-8").decode("unicode_escape")
    if kind == 10:
        return {"true": True, "false": False, "nil": None}[s]
    raise ValueError(f"unexpected token {s!r}")


def _table(it):
    arr, d = [], {}
    while True:
        tok = next(it)
        if tok[0] == 5:  # }
            return d if d else arr
        if tok[0] == 7:  # ,
            continue
        if tok[0] == 2:  # [key] = value
            key = _value(next(it), it)
            next(it)  # ]
            next(it)  # =
            d[key] = _value(next(it), it)
        else:
            arr.append(_value(tok, it))


def read_savedvariable(path, name="TransmogPaletteDB"):
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(rf"^{name}\s*=\s*", text, re.M)
    if not m:
        raise ValueError(f"{name} not found in {path}")
    it = _tokens(text[m.end():])
    return _value(next(it), it)


# --- pages and tiles ---------------------------------------------------------

def _stamp_time(stamp):
    return datetime.strptime(stamp, "%m%d%y_%H%M%S")


def load_pages(sv_path=DEFAULT_SV, shots=SCREENSHOTS, max_drift=3):
    """[(record, screenshot path)] for every capture whose screenshot exists.
    Screenshot names carry the second they were written, which can trail the
    recorded stamp by a moment."""
    db = read_savedvariable(sv_path)
    files = {}
    for p in shots.glob("WoWScrnShot_*.png"):
        try:
            files[_stamp_time(p.stem[len("WoWScrnShot_"):])] = p
        except ValueError:
            pass
    out = []
    for rec in db.get("captures") or []:
        t = _stamp_time(rec["stamp"])
        near = [(abs((ft - t).total_seconds()), p) for ft, p in files.items()]
        near = [x for x in near if x[0] <= max_drift]
        if near:
            out.append((rec, min(near)[1]))
    return out


def tile_boxes(rec, img_size):
    """visualID and pixel box (left, top, right, bottom) for each tile. Tile
    rects are in unscaled screen units with the origin at the BOTTOM left; the
    screenshot's origin is top left, so y flips."""
    sw, sh = rec["screen"]
    iw, ih = img_size
    fx, fy = iw / sw, ih / sh
    for vid, left, bottom, width, height in rec["tiles"]:
        yield int(vid), (round(left * fx), round(ih - (bottom + height) * fy),
                         round((left + width) * fx), round(ih - bottom * fy))


# --- separating the item from the character ---------------------------------
#
# Armour tiles show the appearance worn by the player's character, lit, on a
# black backdrop; outside the head slot the body is drawn as a dark silhouette.
# A pixel belongs to the item when it differs clearly from the same pixel of a
# BARE tile -- the slot's "hidden" appearance, which every armour slot lists and
# which has no colour data. Weapons have no bare tile; their reference is the
# per-pixel median of the slot's tiles, which is just the backdrop since every
# weapon sits somewhere different.

# The equipped appearance's tile carries a purple border, and the hidden one an
# eye icon in its corner. Both live at the edge, so the edge is dropped.
INSET = 0.08
# CIELAB distance from the bare tile above which a pixel is the item's. ~10 is
# "clearly a different colour"; JPEG-free PNG noise sits well under 2.
MASK_DELTA_E = 10.0


def _display_types():
    import csv
    path = Path(__file__).resolve().parent / "db2_cache" / "ItemAppearance.csv"
    with path.open(encoding="utf-8") as f:
        return {int(r["ID"]): int(r["DisplayType"]) for r in csv.DictReader(f)}


def load_tiles(pages, color_vids):
    """One entry per distinct visualID: {vid, slot, lab (H,W,3), rgb}. Tiles
    are resized to a common size per slot so they can be compared per pixel.
    Bare tiles are returned separately, keyed by slot."""
    import color_naming as cn
    disp = _display_types()
    tiles, bare, seen = [], {}, set()
    for rec, path in pages:
        img = Image.open(path).convert("RGB")
        boxes = list(tile_boxes(rec, img.size))
        known = [disp[v] for v, _ in boxes if v in disp]
        slot = max(set(known), key=known.count) if known else -1
        for vid, (l, t, r, b) in boxes:
            dx, dy = round((r - l) * INSET), round((b - t) * INSET)
            crop = img.crop((l + dx, t + dy, r - dx, b - dy)).resize((100, 136), Image.BILINEAR)
            rgb = np.asarray(crop, dtype=np.float64) / 255.0
            entry = {"vid": vid, "slot": slot, "rgb": rgb,
                     "lab": cn.srgb_to_lab(rgb.reshape(-1, 3)).reshape(rgb.shape)}
            # Known to the game, no colour data: the slot's hidden appearance.
            # Not for weapons (DisplayType 11), which have no hidden entry --
            # a weapon without data is just a weapon.
            if vid in disp and vid not in color_vids and slot != 11:
                bare.setdefault(slot, entry)
            elif vid not in seen and vid in color_vids:
                seen.add(vid)
                tiles.append(entry)
    return tiles, bare


def item_masks(tiles, bare):
    refs = {}
    for slot in {t["slot"] for t in tiles}:
        if slot in bare:
            refs[slot] = bare[slot]["lab"]
        else:
            refs[slot] = np.median(np.stack([t["lab"] for t in tiles if t["slot"] == slot]), axis=0)
    for t in tiles:
        d = np.linalg.norm(t["lab"] - refs[t["slot"]], axis=2)
        t["mask"] = d > MASK_DELTA_E
    return refs


# --- the measurement -----------------------------------------------------------

def _lch(lab):
    lab = np.atleast_2d(lab)
    return (lab[:, 0], np.hypot(lab[:, 1], lab[:, 2]),
            np.degrees(np.arctan2(lab[:, 2], lab[:, 1])) % 360)


def _hsv_to_lab(hsv):
    import colorsys
    import color_naming as cn
    rgb = np.array([colorsys.hsv_to_rgb((h % 360) / 360, s, v) for h, s, v in hsv])
    return cn.srgb_to_lab(rgb)


HUE_MATCH_DEGREES = 25.0
MIN_CHROMA = 8.0
LIT_SHARE = 0.40   # same statistic as generate_color_data's LIT_PERCENTILE


def calibrate(tiles, data):
    """Per chromatic main colour: where its hue shows up on screen, how light
    and how colourful is it there, against what the texture data says."""
    import naming_compare as nc
    rows = []
    for t in tiles:
        main = nc.main_cluster(data[t["vid"]])
        if nc.is_neutral(main):
            continue
        Lt, Ct, Ht = (x[0] for x in _lch(_hsv_to_lab([main[:3]])))
        px = t["lab"][t["mask"]]
        if len(px) < 200:
            continue
        L, C, H = _lch(px)
        gap = np.abs((H - Ht + 180) % 360 - 180)
        sel = (C >= MIN_CHROMA) & (gap <= HUE_MATCH_DEGREES)
        share = sel.mean()
        if sel.sum() < 30:
            rows.append((t["vid"], t["slot"], Lt, Ct, np.nan, np.nan, share))
            continue
        order = np.argsort(-L[sel])[:max(1, int(sel.sum() * LIT_SHARE))]
        rows.append((t["vid"], t["slot"], Lt, Ct, L[sel][order].mean(), C[sel][order].mean(), share))
    return np.array(rows, dtype=np.float64)


def calibrated_lab(hsv, gain, offset, chroma_ratio):
    """Texture colour -> the colour it shows on screen, by the measured fit."""
    lab = _hsv_to_lab(hsv)
    L = np.clip(gain * lab[:, 0] + offset, 0, 100)
    ab = lab[:, 1:] * chroma_ratio
    return np.column_stack([L, ab])


def score_naming(tiles, data, fit):
    """Scores ways of NAMING an appearance's main colour against the same
    colour as it appears on screen.

    Detection is held fixed: every method names the one cluster 1.2.1 picks
    as main. The answer key is the survey's name for that cluster's lit pixels
    ON SCREEN (for a neutral main, the item's lit screen pixels). So this asks
    only "is the colour named the way people would name what they see".
    """
    import color_naming as cn
    import naming_compare as nc
    fam = cn.FAMILIES
    keys, a, b, c, vids = [], [], [], [], []
    for t in tiles:
        main = nc.main_cluster(data[t["vid"]])
        px = t["lab"][t["mask"]]
        if len(px) < 200:
            continue
        L, C, H = _lch(px)
        if nc.is_neutral(main):
            sel = C < MIN_CHROMA * 2
        else:
            Ht = _lch(_hsv_to_lab([main[:3]]))[2][0]
            sel = (C >= MIN_CHROMA) & (np.abs((H - Ht + 180) % 360 - 180) <= HUE_MATCH_DEGREES)
        if sel.sum() < 30:
            continue
        lit = px[sel][np.argsort(-L[sel])[:max(1, int(sel.sum() * LIT_SHARE))]]
        keys.append(lit.mean(axis=0))
        a.append(nc.current_family(main))
        b.append(main[:3])
        vids.append(t["vid"])
    key = [fam[i] for i in cn.family_probs_lab(np.array(keys)).argmax(1)]
    raw = [fam[i] for i in cn.family_probs_hsv(b).argmax(1)]
    cal = [fam[i] for i in cn.family_probs_lab(calibrated_lab(b, *fit)).argmax(1)]
    return vids, key, a, raw, cal


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sv", type=Path, default=DEFAULT_SV)
    ap.add_argument("--contact", type=Path, help="write a sheet of tile crops and stop")
    ap.add_argument("--pages", type=int, default=2, help="pages on the contact sheet")
    ap.add_argument("--masks", type=Path, help="write a sheet showing the item masks and stop")
    args = ap.parse_args()

    pages = load_pages(args.sv)
    n_tiles = sum(len(r["tiles"]) for r, _ in pages)
    print(f"{len(pages)} pages matched to screenshots, {n_tiles} tiles")

    if args.masks:
        import naming_compare as nc
        data = nc.parse()
        tiles, bare = load_tiles(pages, set(data))
        item_masks(tiles, bare)
        print(f"{len(tiles)} distinct appearances; bare tiles for slots {sorted(bare)}")
        # Two of each slot: the tile, then the tile with non-item pixels magenta.
        pick = []
        for slot in sorted({t["slot"] for t in tiles}):
            pick += [t for t in tiles if t["slot"] == slot][3:6]
        h, w = pick[0]["rgb"].shape[:2]
        sheet = Image.new("RGB", (6 * (2 * w + 6), -(-len(pick) // 6) * (h + 3)), (40, 40, 40))
        for i, t in enumerate(pick):
            shown = (t["rgb"] * 255).astype(np.uint8)
            masked = shown.copy()
            masked[~t["mask"]] = (255, 0, 255)
            x, y = (i % 6) * (2 * w + 6), (i // 6) * (h + 3)
            sheet.paste(Image.fromarray(shown), (x, y))
            sheet.paste(Image.fromarray(masked), (x + w, y))
        sheet.save(args.masks)
        print(f"wrote mask sheet to {args.masks}")
        return

    if args.contact:
        crops = []
        for rec, path in pages[:args.pages]:
            img = Image.open(path).convert("RGB")
            for vid, box in tile_boxes(rec, img.size):
                crops.append(img.crop(box))
        w = max(c.width for c in crops)
        h = max(c.height for c in crops)
        cols = 9
        sheet = Image.new("RGB", (cols * (w + 4), -(-len(crops) // cols) * (h + 4)), (255, 0, 255))
        for i, c in enumerate(crops):
            sheet.paste(c, ((i % cols) * (w + 4), (i // cols) * (h + 4)))
        sheet.save(args.contact)
        print(f"wrote {len(crops)} crops to {args.contact}")
        return

    import naming_compare as nc
    data = nc.parse()
    tiles, bare = load_tiles(pages, set(data))
    item_masks(tiles, bare)
    rows = calibrate(tiles, data)
    found = ~np.isnan(rows[:, 4])
    print(f"\n{len(rows)} appearances with a coloured main colour; "
          f"its hue is visible on screen for {found.sum()} ({found.mean():.0%})")
    print(f"share of item pixels in the main colour's hue: median {np.median(rows[:, 6]):.0%}")
    r = rows[found]
    Lt, Ct, Ls, Cs = r[:, 2], r[:, 3], r[:, 4], r[:, 5]
    print("\n                 texture   screen   (lit surface, CIELAB)")
    for name, a, b in (("lightness L*", Lt, Ls), ("chroma C*", Ct, Cs)):
        print(f"{name:14s} p25 {np.percentile(a, 25):6.1f}  {np.percentile(b, 25):6.1f}")
        print(f"{'':14s} p50 {np.median(a):6.1f}  {np.median(b):6.1f}")
        print(f"{'':14s} p75 {np.percentile(a, 75):6.1f}  {np.percentile(b, 75):6.1f}")
    a, b = np.polyfit(Lt, Ls, 1)
    print(f"\nfit: L_screen = {a:.2f} * L_texture + {b:.1f}   "
          f"(r = {np.corrcoef(Lt, Ls)[0, 1]:.2f})")
    print(f"chroma ratio screen/texture: median {np.median(Cs / Ct):.2f}")
    names = {0: "head", 1: "shoulder", 3: "chest", 4: "waist", 5: "legs", 6: "feet",
             7: "wrist", 8: "hands", 9: "back", 11: "weapon"}
    print("\nby slot      n   L tex -> screen   C tex -> screen")
    for slot in sorted(set(r[:, 1].astype(int))):
        m = r[:, 1] == slot
        print(f"{names.get(slot, slot):9s} {m.sum():4d}   {np.median(Lt[m]):5.1f} -> {np.median(Ls[m]):5.1f}"
              f"     {np.median(Ct[m]):5.1f} -> {np.median(Cs[m]):5.1f}")

    # Naming, scored against the screen. Fitted on half the appearances and
    # scored on the other half, so the calibration cannot grade its own work.
    import color_naming as cn
    from collections import Counter
    rng = np.random.default_rng(0)
    vids_all = r[:, 0].astype(int)
    train = set(rng.choice(vids_all, len(vids_all) // 2, replace=False).tolist())
    m = np.array([v in train for v in vids_all])
    g, o = np.polyfit(Lt[m], Ls[m], 1)
    fit = (g, o, float(np.median(Cs[m] / Ct[m])))
    vids, key, cur, raw, cal = score_naming(tiles, data, fit)
    held = [i for i, v in enumerate(vids) if v not in train]
    print(f"\nnaming scored on {len(held)} held-out appearances "
          f"(calibration fitted on the other {len(train)}):")
    for name, pred in (("1.2.1 hue bands", cur), ("survey, raw texture", raw),
                       ("survey, calibrated", cal)):
        hits = sum(pred[i] == key[i] for i in held)
        print(f"  {name:22s} {hits / len(held):.0%}")
    print("\nscreen says (rows) vs calibrated survey (cols), held-out:")
    fams = cn.FAMILIES
    cells = Counter((key[i], cal[i]) for i in held)
    print("        " + "".join(f"{f[:6]:>7s}" for f in fams))
    for f in fams:
        print(f"{f:7s} " + "".join(f"{cells[(f, g2)]:7d}" for g2 in fams))
    print("\nscreen says (rows) vs 1.2.1 (cols), held-out:")
    cells = Counter((key[i], cur[i]) for i in held)
    print("        " + "".join(f"{f[:6]:>7s}" for f in fams))
    for f in fams:
        print(f"{f:7s} " + "".join(f"{cells[(f, g2)]:7d}" for g2 in fams))


if __name__ == "__main__":
    main()
