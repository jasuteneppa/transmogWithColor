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
- 2026-10-10: in-game sweep (97 pages, 9 slots x 11 colours, head excluded)
  added 408 newly judged tiles -> 1,456 labelled, 701 held out. In game,
  current matcher, tuning half: 50% of judged page-1 tiles are clearly the
  wrong colour. gold 3%, green 3%, purple 26%, red 38%, white 38%, blue 55%,
  gray 58%, pink 67%, brown 77%, black 92%, orange 100%.
- 2026-10-10: match_v2 (fit_v2.py, one swatch per colour, tuning half) in
  game on branch experiment/match-v2. Page 1 clearly wrong: 23% (70/298
  judged) vs 50% for v1. gray 28 (was 58), red 22 (38), brown 44 (77),
  blue 17 (55), gold 7, green 0, purple 30 (26, slightly worse), white 35,
  black 86, orange/pink too few judged. CAVEAT: 169 tiles this sweep
  surfaced are not judged yet and are left out -- judge them next, then
  refit (more orange/black/pink examples) and re-sweep.

- 2026-10-10: judged the 169 tiles the v2 sweep surfaced (1,625 labelled,
  787 held out). v2 in game, all sweep tiles judged: 27% clearly wrong on
  page 1 (88/332) vs 50% v1. gold 16, purple 33, black 88; others as above.
  Next: refit with the new labels, 2-fold CV, no-regression check, re-sweep.

- 2026-10-10: refit with all 1,625 labels (fit_v2.py, FIT_MAX_K=1), checked
  by 2-fold CV inside the tuning half (fit one fold, score the other).
  Gold: its F1 cutoff let bronze / dark orange metal onto page 1 (in game 8
  of 51 wrong vs 1 of 35 for 1.3.0). Gold's cutoff now maximises F0.35:
  unseen-fold wrong 28% -> 8%, missed 38% -> 50% (1.3.0: 0% / 70%); swatch
  moved lighter and yellower (L77 h82). Purple: the one-swatch fit flipped
  between folds (unseen wrong 21% / 50%) and no variant tried (F0.5, F0.7,
  per-swatch kernel width / lightness weight) beat 1.3.0 on both wrong and
  missed, so purple now uses 1.3.0's two swatches and cutoffs unchanged
  (KEEP_V1): identical results by construction. Most remaining purple
  wrongs are one steel set (125516-125523) whose texture reads lavender but
  renders grey -- a calibration problem, not a swatch one. Per-swatch
  kernels made no CV difference for gold or purple and were dropped.
  Tuning half, new vs previous v2: mean wrong 32% (34), missed 44% (41),
  lost 33% (28; gold stricter, purple back to 1.3.0); brown missed 44%
  (38, 1.3.0 52). Exported as v2:palette_v2b, Lua parity exact. Replay of
  the last sweep's tiles: gold 1 wrong / 30 still shown, purple = 1.3.0's
  10 / 39. Next: re-sweep in game and score.
- 2026-10-10: re-sweep of v2:palette_v2b (89 pages); its 19 new tiles judged
  (1,644 labelled, 797 held out). Page 1 clearly wrong, tuning half: 25%
  (79/320) vs 27% previous v2, 50% 1.3.0. gold 1/38 (3%, = 1.3.0, was 8/51),
  purple 10/39 (26%, = 1.3.0, was 13/39); red 14/55 (one more than before),
  others unchanged. Whole-game unfindable 29.2% vs 24.5% previous v2 and
  22.0% 1.3.0 (1.2.1: 0%, one bucket each): stricter gold returns fewer
  marginal items -- a regression on that number, not yet resolved. Lost
  (obviously coloured, findable nowhere) 34% vs 29% previous v2, 45% 1.3.0.
- 2026-10-10: fallback (match_v2.Matcher.fallback, ns.MatchHit): an
  appearance no colour returns is returned by its best swatch's colour,
  with its below-1 score, so it sorts after every real match. Lua parity on
  2,000 appearances: 0 group decisions differ; 567 matched only by
  fallback. Whole-game unfindable 29.2% -> 0.0%; lost 34% -> 28%; best-20
  unchanged; overall wrong among everything returned rises (brown 52 -> 64%,
  gold 4 -> 12%, purple 25 -> 32%, gray 40 -> 48%) -- those are the
  fallback items at the end of each list. 53 of 89 sweep pages had fewer
  than 20 tiles, so in game fallback items will reach page 1 there:
  re-sweep needed (label v2:palette_v2b-fb).
- 2026-10-10: missing-items check against live build 12.1.0.69933
  (wago.tools): 57,245 item-backed appearances, 1,166 (2.0%) have no
  colour data and so never match a colour filter: 173 added since the
  2026-08-26 table cache, 993 older (627 weapons; only 101 are in
  failures.txt as "no texture resolved", the rest unexplained).
- 2026-10-10: re-sweep with fallback (v2:palette_v2b-fb, 92 pages), 54 new
  tiles judged (1,698 labelled). Page 1 clearly wrong 33% (116/355) vs 25%
  without fallback: gold 12% (was 3), purple 33% (26), brown 66% (43),
  black 15/17. Split: real matches 21% wrong (54/263); fallback fills on
  short pages 67% wrong (62/92). Fallback as a silent match is rejected by
  the acceptance rule; options: mark fallback tiles, or make them opt-in.
  Decision (user): fallback dropped -- an unfindable item is usually one
  with no clear colour, and guessing one is what made 1.2.1's pages wrong.
  Code reverted; game back on v2:palette_v2b. Unfindable stays an open
  number to improve through better matching, not forced guesses.
- 2026-10-10: extractor audit (sheet per wrong brown/black/white page-1
  item: screenshot, raw textures, data colours, screen colours). Found a
  real extractor bug: resolve_texture_fdids reads an item's attached 3D
  model textures (ModelMaterialResourcesID) only when it has NO body
  textures, so belt buckles, chest scarves/collars, boot and glove pieces
  are never sampled. 9,420 appearances (15%): waist 59%, hands 37%, legs
  32%, chest 30%, feet 29%. A gold-and-red buckle belt is "brown" in the
  data (just the strap). Page-1 effect is per slot (waist 7/23 wrong with
  attachment vs 0/5 without; hands 9/21 vs 5/15) but overall 25% either
  way: such items mostly go MISSING under their real colours rather than
  showing wrongly. Other wrongs on the sheet are matcher issues: a 35%
  brownish trim passes brown, dark red reads brown, white's cutoff (0.010)
  passes grey metal with a sliver of highlight, dark grey passes black.
  Screen colours otherwise broadly agree with the data.
- 2026-10-10: extractor fix (generate_color_data.resolve_attachment,
  --attachment-share, default 0.5): attached 3D pieces' textures are now
  blended in. 4,981 texture/model pairs fetched (215 failed). Shipped
  ColorData = tools/ColorData.pre-mc4.lua.bak (63,574/63,742 identical),
  i.e. made BEFORE the scrapped 1.2.2 generator changes (4 colours, baked
  weapon textures, ...); the committed generator's output differs on most
  items, by design. Its texture->screen calibration also differs: refitted
  from the screenshots, gain/offset/chroma 0.94/15.5/1.12 (shipped) vs
  0.69/16.2/0.94 (new); match_eval.FIT is the shipped data's.
  2-fold CV (tuning half), each version with its own FIT, wrong/missed/lost:
  shipped 42/40/37, new generator 45/43/39, new + attachments 44/41/37.
  Items with an attached piece: 44/52/49, 49/55/51, 46/49/44. Better with
  the fix: purple, blue, red wrong, gray missed, black missed; worse: green
  missed 13% -> 42%, gold wrong 7 -> 25%. HUE_SHIFT (per-hue calibration)
  was not refitted for the new data and is the first suspect for green.
- 2026-10-10: WHY everything plateaued. Label self-consistency: 60 random
  tuning tiles re-judged blind, 2 yes<->no flips in 473 decided cells (only
  yes<->unsure drifts), so labels are not the ceiling. A relative rule
  (dominant family) was worse (wrong 58%). Sheets of the remaining errors
  with on-screen colours: shading splits one material into several colours
  (red folds read brown, white reads grey, gold/orange shadow reads brown,
  cool steel reads tinted). Test: group screenshot pixels into MATERIALS by
  shading-invariant chromaticity (hue + C/(L+20) >= 0.15), each keeps its
  full area, chromatic named by its lit 30%, neutrals split dark/light when
  bimodal and named by mean lightness. Same matcher, same 2-fold CV,
  wrong/missed/lost: shipped texture data 42/39/37, screen raw patches
  33/37/35, screen MATERIALS 24/31/29 (brown 59/44 -> 32/31, gray 54/51 ->
  35/37, white 62/41 -> 46/48; red missed 25, green wrong 21 need work).
  Same grouping on texture pixels: 33/42/40 -- does not carry over
  (unweighted textures include unseen regions and painted shading). The
  gain needs on-screen pixels for every appearance.
- 2026-10-10: user's idea -- sort every pixel by colour. Each item -> share
  of its pixels in 112 colour bins (12 hues x 3 colourfulness x 3 lightness
  + 4 grey lightness), per colour an L2 logistic regression on the sqrt
  shares, 2-fold CV (tuning half), F1-best threshold from the training fold.
  TEXTURE pixels (body + attached pieces, unweighted): 25/33/31 wrong/
  missed/lost vs shipped 42/39/37 -- biggest gain yet, no capture needed.
  SCREEN pixels: 18/26/24. Held to <= 9% wrong overall: texture missed 59%
  lost 57%; screen missed 32% lost 30%. Scripts: session scratchpad
  pixel_hist.py (to move into tools/). Next: visible-area weighting of
  texture pixels, more labels; ship as precomputed per-colour scores.
  Visible-area weighting of texture pixels: 29/31/28 (no real change).
  Learning curve (train on 25/50/100% of each fold): texture missed
  61/43/33, screen 53/34/26 at similar wrong -- still steep, so more labels
  are the main lever. Plan: random-page capture for training tiles, judge
  ~2,000 more, retrain; screen capture of everything if texture plateaus.
- 2026-10-10: CLIP (OpenCLIP ViT-L-14 laion2b, venv ~/.venvs/transmog-ml,
  CPU) on the 872 tuning tiles, same labels and 2-fold CV. Zero-shot (no
  training, "a {colour} piece of armor in World of Warcraft"): 25/19/16
  wrong/missed/lost. Per-colour cutoffs at ~10% wrong: red 11/7, green
  11/4, blue 9/0, gold 10/15-30, purple 12/27. Best: CLIP colour answers +
  128-d embedding + screen pixel histogram -> L2 logistic regression,
  cutoff from inner-CV predictions: 26/19/17 overall; red 3/12, gold 8/14,
  green 6/10, blue 9/3, purple 10/10, pink 0/36; weak: black 94/44 (9 yes),
  orange 45/25 (8 yes), white 30/48, gray 25/18, brown 22/41. Needs an
  image of every appearance (full capture) + more labels for the neutrals,
  brown and orange. Holdout still untouched. Scripts in session scratchpad
  (clip_eval2.py, embed.py, pixel_hist.py) -- move into tools/ next.
- 2026-10-11: JOURNAL CAPTURE (Capture.lua `/tmpalette capture journal`):
  Collections > Appearances, border hidden, magenta backdrop, window x1.3,
  one class per run, already-captured items skipped. 6 classes done ->
  36,034 appearances (journal_tiles.py). CLIP L-14 for all (clip_embed.py),
  112-bin pixel histograms (journal_features.py). benchmark/journal_eval.py
  on the 835 tuning items with both tile kinds, 2-fold CV:
  zero-shot TRANSMOG 23/20/17 vs JOURNAL 24/21/19 (journal tiles fine;
  white much better: 12/16 vs 30/44). Trained CLIP+hist+slot, per-colour
  cutoffs held to <=9% wrong on the training fold: 9/27/26 overall; green
  4/4, gold 6/12, gray 8/36, white 7/44, red 11/11, purple 14/21, blue
  15/23, brown 15/39; black, orange, pink never returned (8-11 clear
  examples each). Next: targeted labels for black/orange/pink and borderline
  items, from journal tiles; finish the remaining 7 classes.
- 2026-10-11 (overnight): 51 journal tiles are pixel-identical to the bare
  body (item not rendered); excluded. New labels judged on journal tiles
  (normal + brightened side by side, so dark items are readable), TUNING
  half only (fixed hash), holdout untouched, field source="journal":
  batch 1, 230 items picked by zero-shot score for black/orange/pink plus
  60 random (clear examples: orange 8->51, pink 11->47, black 9->24);
  batch 2, 210 items: 30 most uncertain each for gray/white/brown/blue/
  purple under the trained model + 60 random. 1,275 tuning items now.
  journal_eval, trained CLIP+hist+slot, per-colour cutoffs held to <=9%
  wrong on the training fold: 9/20/19 wrong/missed/lost (balanced F1
  cutoffs: 17/12/11). gold 7/7, green 5/2, orange 9/2, red 9/12, pink
  5-7/17, purple 9-15/10-18, white 8/40, gray 8/43, blue 9-14/14-17, black
  10-16/25-33, brown 16-20/29-34. Caveat: batch 1 was picked by CLIP score,
  so black/orange/pink figures lean optimistic. CLIP components 32..256:
  no difference -- the model is not the limit.
- 2026-10-11: all 13 classes captured: 39,410 distinct appearances (38,922
  of the 63,742 with colour data). Uncaptured 24,820: 7,668 used by no item,
  4,164 "not valid for transmog", 9,117 "hidden until collected", 383 no
  source/can't collect, ~3,500 normal sources (likely opposite faction /
  race-locked; 2,124 Trading Post, unexplained).
  CLIP on TEXTURE images (texture_montage.py: an appearance's diffuse
  textures, body + attached piece, on black, 2x2 grid): zero-shot 43/34/31,
  trained 37/30/27 (~ shipped method 42/39/37). Combined with journal tiles:
  18/14/13 vs journal alone 17/12/11 -- no help, incl. black/brown/white
  (user's hypothesis). Textures are fragments, unlit, partly unseen.
  Journal tiles stay the source; textures only as the fallback.
- 2026-10-11: IN THE ADDON (experiment/match-v2, uncommitted): build_scores.py
  trains the journal model (CLIP+hist+slot) on the tuning half, strict
  per-colour cutoffs (<=9% wrong on held-out predictions inside the tuning
  half), writes TransmogPalette/ColorScores.lua: 39,272 appearances x (11
  score bytes, 128 = cutoff; 11 light/dark bytes, 128 = slot median for that
  colour). Matching.lua: ns.MatchScore uses scores when present (hand
  corrections excepted), closeness on ColorData otherwise; ns.HasMatchData
  gates the filter. "More" row = light / dark halves per colour (CLIP "light
  X" vs "dark X", split per slot; a per-pixel-lightness version mostly split
  weapons from armour and caught trim). Roller (Randomizer.lua) now rolls by
  the filter's general colours and rule; ROLL_SCHEME_VERSION 7 clears old
  slot picks. shade_palette.py: in-game shades are mainly lightness steps;
  hue sub-shades navy/teal, rose/magenta, bronze/gold, dusk/violet; old
  slate/jade/cyan/bright-green swatches do not appear on screen. Lua parity
  of scores and shade keys: 0 mismatches on 200 appearances. Holdout check
  (benchmark/holdout_check.py) deliberately not run yet -- run once when
  tuning is finished.

## Inclusive cutoffs + broader black/white (2026-10-11)

Labels: black/white relabelled on the tuning half under a broader definition
(black +46 yes, white +34 yes). Holdout labels NOT relabelled.

journal_eval, CLIP+hist+slot, tuning-half CV:
- F1-best ("inclusive"): wrong 16% missed 13% lost 12% (was 17/12/11 before the relabel)
- wrong<=9% ("strict"): wrong 10% missed 19% lost 18%

build_scores.py now defaults to `--cutoff inclusive` (F1-best per colour); the addon
lists pieces whose TOP colour is the selected one first (Matching.lua MatchSortScore).
Shipped ColorScores.lua, held-out wrong/missed at cutoff and matches game-wide:

| colour | wrong | missed | matches |
|---|---|---|---|
| black | 14% | 19% | 1450 (was 337) |
| gray | 27% | 15% | 7953 |
| white | 11% | 11% | 2992 |
| red | 4% | 12% | 3013 |
| orange | 4% | 2% | 1559 |
| brown | 17% | 31% | 6197 |
| gold | 6% | 6% | 5767 |
| green | 5% | 2% | 4187 |
| blue | 12% | 5% | 5026 |
| purple | 2% | 17% | 2488 |
| pink | 5% | 11% | 313 |

Lua parity (score_test.py, 200 random appearances incl. light/dark halves): 0 mismatches.
UI at the same time: display colours per group, More row = black/white over dark/light
gray, light/dark halves for the other hues, pink over purple (merged, unsplit); roller uses
the strip's layout and per-slot colour pools (ROLL_SCHEME_VERSION 8).

## FINAL holdout check, then the holdout into training (2026-10-11)

benchmark/holdout_check.py, run ONCE on the 826 holdout appearances (never used
for any fit, cutoff or tuning step), with closest-colour membership counted as
the addon does it (Matching.lua Fallback):

| method | wrong | missed | lost |
|---|---|---|---|
| 1.2.1 (one bucket) | 64% | 62% | 58% |
| closeness matching (texture) | 36% | 47% | 44% |
| SHIPPED (learned scores) | 21% | 8% | 6% |

Per colour (wrong/missed): black 33/20, gray 35/15, white 42/12, red 2/5,
orange 46/12, brown 20/9, gold 10/6, green 17/2, blue 19/3, purple 5/10,
pink 64/33. Caveats: holdout black/white labels use the OLD narrow definition
(not relabelled -- user preferred no manual labelling), so black/white wrong is
overstated; holdout has only 10 black, 8 orange, 6 pink "yes" labels.
Output: %LOCALAPPDATA%/TransmogPalette/holdout_final.txt.

There is no untouched holdout any more: build_scores.py now trains on tuning +
holdout (2,134 labelled appearances), except holdout items for black/white
(old definition). Inner-CV per colour (wrong/missed at F1 cutoff): black 14/19,
gray 22/18, white 11/11, red 6/7, orange 6/5, brown 13/19, gold 9/7, green 8/4,
blue 7/4, purple 8/13, pink 9/9. Matches game-wide: black 1450, gray 7187,
white 2992, red 3455, orange 1594, brown 5566, gold 5988, green 3283,
blue 4081, purple 2665, pink 381. Any future accuracy claim needs NEW labels.

Model saved to tools/color_model.npz (weights, cutoffs, PCA basis, light/dark
slot medians); `build_scores.py --use-model` reproduces ColorScores.lua
byte-for-byte. Updates after a patch: tools/update_colors.bat (UPDATING.md).

Also in this round: tile_check.py (tile swatches on held-out tuning items: first
swatch wrong 7%, second 15%, a clear colour shown by neither 8%); appearances
matching no colour (21%) now join their closest colour, listed last;
exclusions use a looser bar (score >= 0.5).
