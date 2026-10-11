# Transmog Palette

A World of Warcraft (Retail) addon. Filter appearances by colour in the
Transmogrifier and in Collections → Appearances, and roll random outfits from
the colours you pick.

## What it does

**Filter by colour.** A strip of colour swatches sits under the search box in
the Transmogrifier, and under the window in Collections → Appearances.

- **Click** colours to filter. Several at once are OR'd: "red or blue". Click
  again to drop one.
- **Right-click** sets an *accent*, which narrows every picked colour at once:
  "red or blue, with gold".
- **Middle-click** or **Shift-click** *excludes* a colour: anything that also
  has it is left out. "Black and white, but nothing with red" is three clicks.
- **More** splits each colour into a light and a dark half: black and white over
  dark and light grey, light and dark versions of each hue, and pink over
  purple.
- Each swatch's tooltip says how many appearances it will return.

An appearance is listed under every colour it plausibly has, so a black robe
with red trim is under black *and* red. Results are sorted with pieces mainly
the picked colour first. Each tile shows its one or two main colours in its
corner. Turn those off with the **Swatches** checkbox. The strip can be dragged
anywhere by its background, and each window remembers its own spot.

In Collections → Appearances the filter covers items you haven't collected yet,
so you can see what exists in a colour before going after it. The journal's own
filters (collected, sources, class) still apply.

**Roll a random outfit.** In the Transmogrifier, every gear slot gets a small
swatch beside it. Click it to pick that slot's colours. Several colours make a
pool, so gold and purple rolls from all your gold and purple pieces.
Middle-click or Shift-click excludes a colour. **All Slots** sets one pool on
every slot. Press **Roll** and the addon stages a random matching appearance in
each slot. Nothing is spent until you press Blizzard's own Apply button, so
re-roll as often as you like.

- Right-click a slot swatch to clear it; right-click **Roll** to clear every
  slot.
- The roller's picker has its own **More** / **Less** for light and dark
  shades.
- Slots with nothing equipped are skipped, because transmog restyles a worn
  item.
- Appearances your class can't use are left out.

## Commands

| Command | Effect |
| --- | --- |
| `/tmpalette` | Help |
| `/tmpalette roll` | Roll, without clicking the button |
| `/tmpalette swatches` | Show or hide the colour swatches on each appearance tile |
| `/tmpalette resetpos` | Put the colour strips back in their default spots |
| `/tmpalette slots` | How many appearances each slot can draw from |

## Install

Copy the `TransmogPalette` folder into
`World of Warcraft\_retail_\Interface\AddOns\` so that the path is
`AddOns\TransmogPalette\TransmogPalette.toc`. It must be a direct subfolder,
not nested inside another one.

## How the colours are decided

WoW's addon API can't read an appearance's pixels at runtime, so colours are
worked out offline and shipped with the addon (`ColorScores.lua`).

Every appearance in the Collections journal (39,272 of them) was captured as
the game draws it: lit and shaded on a character. A model then scored each one
for eleven colours: black, grey, white, red, orange, brown, gold, green, blue,
purple and pink. The model is an image model (CLIP) plus a count of the tile's
pixel colours, and it was trained on a set of appearances judged by eye.

Judging from the rendered picture rather than the texture files is the whole
point. Shading is what fooled every earlier version: shaded red leather read as
brown, white plate as grey, dark purple as black. Textures don't carry the
lighting, and nothing about how colours were named or grouped could make up for
it.

An appearance joins every colour it clears a cutoff for. One that clears none
joins its closest colour, listed last. Excluding is deliberately looser than
including, so a noticeable amount of red is enough to drop a piece from
"nothing with red".

On 826 eye-judged appearances that no part of the training ever saw:

| | wrong | missed | lost |
| --- | --- | --- | --- |
| 1.2.1 | 64% | 62% | 58% |
| 1.3.0 | 21% | 8% | 6% |

*Wrong*: listed under a colour it doesn't have. *Missed*: not listed under a
colour it clearly has. *Lost*: a clearly coloured item you couldn't find under
any of its colours.

Appearances the journal never shows (mostly the other faction's gear) fall
back to the older texture-based colour data in `ColorData.lua`. Appearances
added by a game patch have no colours until the next update of the addon.

## Development

The addon ships with complete colour data; nothing below is needed to use it.

### After a game patch

See [`tools/UPDATING.md`](tools/UPDATING.md). In short: in game, run
`/tmpalette capture journal` with Collections → Appearances open, then
`/reload`. Then run `tools/update_colors.bat`, which scores the new appearances
with the saved model (`tools/color_model.npz`) and writes a new
`ColorScores.lua`.

Then:

1. **Bump `## Interface:`** in the `.toc` to the new build, or the client
   flags the addon as out of date and players must opt in to loading it. Get
   the number in game with `/run print(select(4, GetBuildInfo()))`.
2. Bump `## Version:`, add a `CHANGELOG.md` entry, and
   `pwsh tools/build_release.ps1`.

### Retraining and measuring

- `tools/build_scores.py` trains the model on `tools/benchmark/labels.json`
  and writes `ColorScores.lua`; `--use-model` scores with the saved model
  instead.
- `tools/benchmark/` holds the labels, the evaluation scripts and `README.md`,
  a log of every method tried and what it scored. Read it before changing the
  method. Several approaches that looked promising are recorded there as dead
  ends, with numbers.
- The held-back test half of the labels is now part of training. Any new
  accuracy claim needs newly labelled appearances.

### The texture pipeline (fallback data)

`tools/generate_color_data.py` builds `ColorData.lua` from the game's texture
files. Only appearances without journal scores use it now. Run it with
`python -u generate_color_data.py --all --jobs 6 --refresh-db2`. After a patch,
`--refresh-db2` is required, or it rebuilds from the previous patch's tables.

### Building a release

```
pwsh tools/build_release.ps1
```

Produces `dist/TransmogPalette-<version>.zip`, structured so the archive
contains a single `TransmogPalette/` folder. Version and interface number are
read from the `.toc`, and it fails if a file listed there is missing.

## Licence

MIT — see `LICENSE`.
