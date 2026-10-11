# Updating colours after a patch

New armour and weapons have no colour scores until they are captured and
scored. Until then they show **NO DATA** on their tile and don't appear under
any colour. Nothing needs relabelling: the saved model (`tools/color_model.npz`)
scores new items the same way it scored the old ones.

## 1. Capture in game

1. Open **Collections → Appearances**.
2. Capture, either all classes in one go:

   ```
   /tmpalette capture journal
   ```

   or one class at a time: pick the class in the journal's class dropdown,
   then run

   ```
   /tmpalette capture journal class
   ```

   and repeat for each class. The capture only screenshots pages that have
   something new on them, so after a patch it's much quicker than the first
   full run. Don't touch the journal while it runs.
   `/tmpalette capture stop` cancels it.
3. `/reload` (or log out) so the capture is written to disk.

Don't run `/tmpalette capture clear`. It deletes the capture records the
update reads, and it forgets which pages were already done.

## 2. Run the update

Double-click **`tools/update_colors.bat`**. It:

1. backs up the current `TransmogPalette/ColorScores.lua` to
   `%LOCALAPPDATA%\TransmogPalette\backups\`,
2. cuts the new item tiles out of the screenshots,
3. runs the image model on the new tiles (the slow step; it only does new
   ones),
4. measures their colours,
5. scores everything with the saved model and writes a new `ColorScores.lua`,
   printing how many items each colour matches.

If a step fails, it stops and says which one. The scores file is only
replaced by the last step.

## 3. Check and ship

- `/reload` in game and look at the new items. Their tiles should show colour
  swatches instead of NO DATA.
- If something looks badly wrong, copy the backup back over
  `TransmogPalette/ColorScores.lua` and `/reload`.
- Ship the new `ColorScores.lua` in an addon update. Players only get new
  scores through an update.

## When to retrain instead

Only if a patch brings a very different art style and new items start
landing in the wrong colours. Retraining is `python build_scores.py` (no
`--use-model`, about 30 minutes). It refits on `tools/benchmark/labels.json`,
so new items only help if some of them get labelled first.

## What it needs

- Python on PATH with the tools' requirements (`tools/requirements.txt`).
- The ML environment at `%USERPROFILE%\.venvs\transmog-ml` (torch CPU +
  open_clip), used by the image-model step.
- `%LOCALAPPDATA%\TransmogPalette\journal_tiles\`: the tiles cut so far, plus
  `text_L14.npy` and `text_lightdark.npy` (the model's colour prompts). Keep
  this folder. Without it every item would have to be captured again.
- WoW installed at `C:\Program Files (x86)\World of Warcraft\_retail_`, with
  the account folder set in `tools/capture_calibrate.py`.
