"""Investigation: does the appearance ICON describe an item's perceived color
better than its raw TEXTURE?

Raw textures include surfaces the rendered model never shows (hood linings,
undersides), which is why near-black primaries keep outranking the visible
shell. Icons are pre-rendered exterior art, so they should not have that
failure mode -- but they carry their own risks (stylized lighting, dark
backdrops, ornamentation), so this compares the two side by side rather than
assuming icons win.

Writes an HTML contact sheet for eyeballing plus a summary on stdout.
"""

import csv
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_color_data as gcd  # reuse the exact clustering pipeline

import requests
from PIL import Image

SCRIPT_DIR = Path(__file__).resolve().parent
ICON_CACHE_DIR = SCRIPT_DIR / "icon_cache"
OUT_HTML = SCRIPT_DIR / "icon_vs_texture.html"
SAMPLE = 60


def load_icon_fdids():
    path = gcd.DB2_CACHE_DIR / "ItemAppearance.csv"
    with open(path, encoding="utf-8") as f:
        return {
            int(r["ID"]): int(r["DefaultIconFileDataID"])
            for r in csv.DictReader(f)
            if r.get("DefaultIconFileDataID", "0") not in ("", "0")
        }


def fetch_icon(fdid, session):
    ICON_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for url, ext in gcd.TEXTURE_URLS:
        cache = ICON_CACHE_DIR / f"{fdid}.{ext}"
        if cache.exists():
            return Image.open(cache)
        resp = session.get(url.format(fdid=fdid), timeout=20)
        if resp.status_code == 200 and len(resp.content) > 100:
            cache.write_bytes(resp.content)
            return Image.open(cache)
    raise ValueError(f"no icon for {fdid}")


def classify(h, s, v, hw=30):
    if v < 0.15: return "black"
    if s < 0.15:
        if v > 0.85: return "white"
        if v > 0.55: return "lightgray"
        if v > 0.30: return "gray"
        return "darkgray"
    band = "dark" if v < 0.35 else ("mid" if v < 0.65 else "light")
    return "h%d_%s" % (int((h % 360) // hw), band)


def hsv_to_css(h, s, v):
    r, g, b = gcd_hsv_to_rgb(h, s, v)
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


def gcd_hsv_to_rgb(h, s, v):
    c = v * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = v - c
    if h < 60: r, g, b = c, x, 0
    elif h < 120: r, g, b = x, c, 0
    elif h < 180: r, g, b = 0, c, x
    elif h < 240: r, g, b = 0, x, c
    elif h < 300: r, g, b = x, 0, c
    else: r, g, b = c, 0, x
    return r + m, g + m, b + m


def main():
    seed = [int(l) for l in (SCRIPT_DIR / "seed_dumped.txt").read_text().split()]
    step = max(1, len(seed) // SAMPLE)
    seed = seed[::step][:SAMPLE]

    icon_fdids = load_icon_fdids()
    session = requests.Session()
    session.headers["User-Agent"] = gcd.__doc__ and "TransmogPalette-IconProbe/0.1" or "x"

    lookups = gcd.build_lookup_tables(session)

    rows = []
    agree = disagree = 0
    for vid in seed:
        tex_fdids = gcd.resolve_texture_fdids(vid, *lookups)
        pooled = gcd.new_profile()
        for fdid in tex_fdids:
            try:
                gcd.add_profiles(pooled, gcd.texture_profile(gcd.fetch_texture(fdid, session)))
            except Exception:
                pass
            time.sleep(gcd.REQUEST_DELAY_SECONDS)
        tex = gcd.dominant_colors(pooled)

        icon_fdid = icon_fdids.get(vid)
        ico = None
        if icon_fdid:
            try:
                ico = gcd.dominant_colors(gcd.texture_profile(fetch_icon(icon_fdid, session)))
            except Exception:
                ico = None
            time.sleep(gcd.REQUEST_DELAY_SECONDS)

        if not tex or not ico:
            continue
        kt, ki = classify(*tex[0][:3]), classify(*ico[0][:3])
        if kt == ki:
            agree += 1
        else:
            disagree += 1
        rows.append((vid, icon_fdid, tex, ico, kt, ki))

    print(f"compared {len(rows)} appearances: primary bucket agrees on {agree}, differs on {disagree}")

    ACH = ("black", "white", "gray", "lightgray", "darkgray")
    tex_ach = sum(1 for r in rows if r[4] in ACH)
    ico_ach = sum(1 for r in rows if r[5] in ACH)
    print(f"primary classifies as achromatic: texture {tex_ach}/{len(rows)}, icon {ico_ach}/{len(rows)}")

    parts = ["<style>body{font-family:sans-serif;background:#1b1b1b;color:#ddd}"
             "table{border-collapse:collapse}td{padding:6px;border-bottom:1px solid #333}"
             "img{width:56px;height:56px;image-rendering:pixelated}"
             ".sw{display:inline-block;width:26px;height:26px;border:1px solid #000}</style>",
             "<h2>Icon vs texture — primary color</h2>",
             "<p>Left swatch group = from raw texture (current pipeline). "
             "Right = from the rendered icon. Judge against the icon image itself.</p>",
             "<table><tr><th>icon</th><th>texture colors</th><th>icon colors</th><th>agree?</th></tr>"]
    for vid, ifd, tex, ico, kt, ki in rows:
        img = f'<img src="https://wow.zamimg.com/modelviewer/live/textures/{ifd}.webp">'
        tsw = "".join(f'<span class="sw" style="background:{hsv_to_css(*c[:3])}"></span>' for c in tex)
        isw = "".join(f'<span class="sw" style="background:{hsv_to_css(*c[:3])}"></span>' for c in ico)
        mark = "✓" if kt == ki else f"✗ {kt} vs {ki}"
        parts.append(f"<tr><td>{img}</td><td>{tsw}</td><td>{isw}</td><td>{mark}</td></tr>")
    parts.append("</table>")
    OUT_HTML.write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {OUT_HTML}")


if __name__ == "__main__":
    main()
