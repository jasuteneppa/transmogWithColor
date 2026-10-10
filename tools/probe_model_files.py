"""Step 1 of the visibility investigation: can we resolve and fetch the actual
.m2 model for a helm appearance?

The plan is to weight texture pixels by how much outward-facing geometry maps
to each UV region, so a hood's inward-facing lining stops outranking the shell.
That only works if the model files are reachable, so this checks that first --
cheaply, before any parser gets written.

Chain: visualID -> ItemAppearance.ItemDisplayInfoID -> ItemDisplayInfo
.ModelResourcesID_0 -> ModelFileData.FileDataID -> CASC download.
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_color_data as gcd

import requests

SAMPLE = 8


def main():
    session = requests.Session()
    session.headers["User-Agent"] = "TransmogPalette-ModelProbe/0.1 (WoW addon dev tool)"

    # ModelFileData isn't in the generator's table list yet; fetch_db2_csv
    # caches it alongside the others.
    try:
        mfd_rows = gcd.fetch_db2_csv("ModelFileData", session)
    except Exception as e:
        sys.exit(f"could not fetch ModelFileData: {e}")

    print("ModelFileData columns:", list(mfd_rows[0].keys()))
    by_modelres = {}
    for r in mfd_rows:
        key = r.get("ModelResourcesID")
        if key:
            by_modelres.setdefault(int(key), []).append(int(r["FileDataID"]))

    app = {}
    with open(gcd.DB2_CACHE_DIR / "ItemAppearance.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            app[int(r["ID"])] = r

    di = {}
    with open(gcd.DB2_CACHE_DIR / "ItemDisplayInfo.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            di[int(r["ID"])] = r

    seed = [int(l) for l in (gcd.SCRIPT_DIR / "seed_dumped.txt").read_text().split()]
    step = max(1, len(seed) // SAMPLE)
    sample = seed[::step][:SAMPLE]

    resolved = 0
    for vid in sample:
        a = app.get(vid)
        if not a:
            print(f"  visual {vid}: no ItemAppearance row")
            continue
        d = di.get(int(a["ItemDisplayInfoID"]))
        if not d:
            print(f"  visual {vid}: no ItemDisplayInfo row")
            continue
        mr = d.get("ModelResourcesID_0", "0")
        fdids = by_modelres.get(int(mr), []) if mr not in ("", "0") else []
        if not fdids:
            print(f"  visual {vid}: ModelResourcesID_0={mr} -> no model FileDataID")
            continue

        fdid = fdids[0]
        url = f"https://wago.tools/api/casc/{fdid}"
        try:
            resp = session.get(url, timeout=30)
            ok = resp.status_code == 200 and len(resp.content) > 100
            magic = resp.content[:4] if ok else b""
            print(f"  visual {vid}: model fdid {fdid} -> HTTP {resp.status_code}, "
                  f"{len(resp.content)} bytes, magic={magic!r}")
            if ok and magic in (b"MD21", b"MD20"):
                resolved += 1
        except Exception as e:
            print(f"  visual {vid}: model fdid {fdid} -> fetch failed: {e}")

    print(f"\n{resolved}/{len(sample)} sampled helms produced a real M2 file.")


if __name__ == "__main__":
    main()
