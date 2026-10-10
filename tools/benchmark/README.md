# Matching benchmark

The one place that says whether a change to colour matching is an improvement.
Written after an evaluation that graded the matcher with its own distance and
called a broken orange filter 94% right. Read this before tuning anything.

## The goal

1. A filter for a colour shows things a player would call that colour.
2. Every appearance can be found under the colours it obviously has.

Nothing else is in scope. A change that does not move one of these is not
matching work.

## Truth is judged by eye, but only where it is obvious

Where exactly brown turns into orange depends on what you are looking at next
to it, so nobody judges boundaries. Each captured tile gets, per general colour
(black, gray, white, red, orange, brown, gold, green, blue, purple, pink), one
of:

- **yes** -- a player filtering for this colour would be glad to see it: the
  colour is a main, plainly visible part of the item (not a gem, a rim, a glow
  dot).
- **no** -- clearly not that colour. A player would call it a wrong result.
- anything in between is **unsure** and is never scored either way.

Rules for the judge:

- Judge the item as rendered in the Transmogrifier tile, nothing else.
- Metal is judged by what it looks like: yellow metal is gold, brown/copper
  metal is brown, white/steel metal is gray (or white when bright).
- Black is for items that read black, not merely dark.
- When in doubt, unsure. Unsure costs nothing; a wrong yes/no corrupts the set.

`labels.json` holds the judgements: `{ visualID: { "yes": [...], "unsure":
[...] } }`; every colour not listed is "no".

## Frozen

Labels are made once, spot-checked by the user (a random 50, agreement
recorded below), and then not edited while tuning. A label is only changed
when the user agrees it was wrong, and the change is logged below.

Half of the labelled appearances (`holdout` in `labels.json`, chosen by a
hash of the visualID) are never looked at while tuning. They are scored once,
at the end, to check the result did not just fit the tuned half.

## The numbers, per colour and slot, always next to 1.2.1

- **wrong on page 1** -- of the first page's labelled items, how many are "no".
- **missed** -- of the "yes" items, how many the filter does not return.
- **unfindable** -- appearances that match no colour at all (whole game).

Page 1 comes from the in-game sweep (`/tmpalette capture sweep`) where one
exists, otherwise from ranking the whole game pool offline.

## Accepting a change

A change is kept only if no colour gets worse on any of the three numbers
beyond noise, and the comparison sheet (same fixed items every time) looks
better. Otherwise it is reverted, however good the idea sounded.

## Log

- 2026-10-10: benchmark defined. 1,048 captured tiles judged by Claude
  (labels.json); 487 held out. Spot-check sheet for the user:
  research/spotcheck-labels.png (ids in spotcheck_ids.json) -- agreement TBD.
- 2026-10-10 baseline, tuning half (561 items, 318 with a clear colour):
  1.2.1 mean wrong 58%, missed 61%, lost 59%; current (1.3.0 branch) wrong
  50%, missed 55%, lost 49%. Current best-20 wrong: red 15, purple 10,
  gold 0, green 0, but brown 100 (gold metal), orange 100, black 90,
  gray 60, blue 55, pink 50, white 50.
