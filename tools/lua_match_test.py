"""Checks the addon's Lua matching against the Python evaluation.

Runs tools/lua_match_test.lua (the addon's real Matching.lua, outside the
game) on a random sample of appearances and compares every relative score with
match_eval.texture_score / min_score. They must agree, or the addon is not
matching the way the evaluation measured.

    python lua_match_test.py [--n 300]
"""
import argparse
import json
import subprocess
from pathlib import Path

import numpy as np

import match_eval as me
import naming_compare as nc

TOOLS = Path(__file__).resolve().parent
LUA = Path.home() / "AppData" / "Local" / "Programs" / "Lua" / "bin" / "lua.exe"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--v2", help="a match_v2 palette (the one exported to Swatches.lua)")
    args = ap.parse_args()

    data = nc.parse()
    palette = json.loads((TOOLS / "palette.json").read_text(encoding="utf-8"))
    if args.v2:
        import match_v2 as mv
        v2 = json.loads(Path(args.v2).read_text(encoding="utf-8"))
        palette = v2["swatches"]
    rng = np.random.default_rng(5)
    vids = rng.choice(sorted(data), args.n, replace=False).tolist()

    out = subprocess.run([str(LUA), str(TOOLS / "lua_match_test.lua"),
                          str(TOOLS.parent / "TransmogPalette"), *map(str, vids)],
                         capture_output=True, text=True, check=True).stdout
    worst, flips = 0.0, 0
    for line in out.strip().splitlines():
        vid, *vals = line.split()
        lua = np.array([float(v) for v in vals])
        if args.v2:
            cl = mv.Clusters(data[int(vid)])
            py = np.array([mv.raw_score(cl, np.array(p["lab"]), v2["neutral_k"]) / p["min_score"]
                           for p in v2["swatches"]])
        else:
            py = np.array([me.texture_score(data[int(vid)], np.array(p["lab"])) / p["min_score"]
                           for p in palette])
        worst = max(worst, float(np.max(np.abs(lua - py))))
        # What matters is the decision: does it match (>= 1) the same way?
        flips += int(np.sum((lua >= 1) != (py >= 1)))
    print(f"{len(vids)} appearances x {len(palette)} swatches")
    print(f"largest difference in relative score: {worst:.4f}")
    print(f"match decisions that differ: {flips}")


if __name__ == "__main__":
    main()
