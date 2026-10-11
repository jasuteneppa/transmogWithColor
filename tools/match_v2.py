"""Closeness matching, second version: the same scoring as match_eval (texture
clusters moved to on-screen colour, a closeness kernel, coverage weighting,
coloured and grey kept apart), with everything that decides WHICH colour an
item is -- the swatches, their groups, the cutoffs, how hard colour pushes an
item out of the greys -- read from a palette file fitted to the eye-judged
labels (benchmark/fit_v2.py) instead of set by hand.

Palette file:
    { "neutral_k": float,
      "swatches": [ { "name", "group", "lab": [L, a, b], "min_score" }, ... ] }
A general colour (group) returns an appearance when any of its swatches scores
at least that swatch's min_score; the ratio is what results are sorted by.
"""
import json
from pathlib import Path

import numpy as np

import capture_calibrate as cc
import match_eval as me

HERE = Path(__file__).resolve().parent


class Clusters:
    """An appearance's texture clusters, calibrated once."""
    __slots__ = ("lab", "w", "m")

    def __init__(self, ranks):
        self.lab = cc.calibrated_lab([c[:3] for c in ranks], *me.FIT)
        w = np.array([c[3] for c in ranks], float)
        self.w = w / max(w.sum(), 1e-9)
        self.m = me.colourfulness(self.lab, np.array([bool(c[4]) for c in ranks]))


def is_neutral(lab):
    return np.hypot(lab[1], lab[2]) < me.NEUTRAL_TARGET_CHROMA


def raw_score(cl, target, neutral_k):
    close = me.closeness(cl.lab, target)
    if is_neutral(target):
        coloured = (cl.w * cl.m).sum()
        return float((cl.w * (1 - cl.m) * close).sum() * max(0.0, 1 - neutral_k * coloured))
    return float((cl.w * cl.m * close).sum())


def load(path):
    return json.loads(Path(path).read_text())


class Matcher:
    def __init__(self, palette, data):
        self.pal = palette
        self.data = data
        self.groups = {}
        for s in palette["swatches"]:
            s["_lab"] = np.array(s["lab"], float)
            self.groups.setdefault(s["group"], []).append(s)
        self._cl, self._cache = {}, {}

    def clusters(self, vid):
        c = self._cl.get(vid)
        if c is None:
            c = self._cl[vid] = Clusters(self.data[vid])
        return c

    def rank(self, vid, group):
        key = (vid, group)
        r = self._cache.get(key)
        if r is None:
            cl = self.clusters(vid)
            r = self._cache[key] = max(raw_score(cl, s["_lab"], self.pal["neutral_k"]) / s["min_score"]
                                       for s in self.groups[group])
        return r

    def __call__(self, vid, group):
        return self.rank(vid, group) >= 1
