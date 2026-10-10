# Transmog Palette

A World of Warcraft (Retail) addon for the Transmogrifier window. Filter
appearances by colour, and roll random colour-matched outfits.

## What it does

**Filter by colour.** At the Transmogrifier, a strip of eleven colour swatches
appears under the search box; **More** opens all twenty shades. Click swatches
to filter — several at once are OR'd, "red or blue or green" — and click again
to drop one. Each swatch shows how many appearances it will return.

An appearance matches a swatch by how much of its surface is *close* to that
colour as it looks on screen, and results are sorted best match first: pieces
that are mostly the colour lead, pieces with a trim of it come last. Each tile
shows the two swatches it matches best in its corner. The strip can be dragged
anywhere by its background.

**Roll a random outfit.** Every gear slot gets a small colour swatch beside it.
Assign colours to the slots you care about, press **Roll**, and the addon stages
a random matching appearance in each one. Nothing is spent until you press
Blizzard's own Apply button, so re-roll as often as you like.

- Right-click a swatch to clear it; right-click **Roll** to clear every slot.
- Slots with nothing equipped are skipped — transmog restyles a worn item.
- Appearances your class can't use are filtered out.

## Commands

| Command | Effect |
| --- | --- |
| `/tmpalette` | Help |
| `/tmpalette roll` | Roll, without clicking the button |
| `/tmpalette grain fine\|medium\|coarse\|broad` | How coarsely the roller groups colours |
| `/tmpalette colorfirst <0-1>` | How much colour keeps an item out of black/grey/white when rolling |
| `/tmpalette swatches` | Show or hide the swatches on each appearance tile |
| `/tmpalette resetpos` | Put the colour strip back under the search box |
| `/tmpalette slots` | How many appearances each slot can draw from |

### About `grain`

The filter and the roller want opposite things. Filtering wants precise buckets
— you're naming a colour you can see. Rolling wants a *pool* to draw from, and
the filter's 36 buckets leave some with one or two items per slot, which isn't
something you can randomise over.

So the roller groups colours more coarsely, and `grain` controls how much:

| grain | buckets | median appearances per bucket |
| --- | --- | --- |
| `fine` | 36 | 855 |
| `medium` | 24 | 2,026 |
| `coarse` | 17 | 2,972 |
| `broad` (default) | 10 | 6,594 |

Measured over all 64,722 appearances by `tools/analyze_grain.py`.

Grain only affects the *coloured* buckets. There are always exactly three
greyscale ones — black, grey and white — see **Greyscale** below.

Changing it clears your assigned slot colours, because the colour *names*
themselves change.

## Install

Copy the `TransmogPalette` folder into
`World of Warcraft\_retail_\Interface\AddOns\` so that the path is
`AddOns\TransmogPalette\TransmogPalette.toc`. It must be a direct subfolder, not
nested inside another one.

## How the colour data works

WoW's addon API cannot read texture pixels at runtime, so an addon can't work
out an appearance's colour in-game. Colours are extracted **offline** and
shipped as a lookup table (`ColorData.lua`).

The table shipped in 1.3.0 is still the 1.2.1 one — 63,742 appearances with up
to three colours each. The pipeline described below has moved on since (four
colours, baked weapon textures, 64,722 appearances), and those changes reach
players the next time the table is regenerated.

The pipeline resolves each appearance to its **real worn texture** — not its
item icon, which is hand-drawn and unreliable; "Rainy Day Coat" has gold icon
art and a deep red texture — then extracts up to four ranked dominant colour
clusters in CIE L\*a\*b\* space. A flat average was tried first and is wrong: it
blends a grey-and-purple hood with bronze trim into a muddy orange that matches
none of its actual colours.

Four, not three. A cluster that doesn't fit takes its **area** with it, so the
piece's total coloured share falls below the greyscale threshold and the whole
appearance comes out black or grey. Raising the cap alone, with nothing else
changed, moved 932 appearances out of the greyscale buckets and into a colour —
teal-tusked helms, cyan-spiked shoulders — and dropped greyscale from 15.5% to
13.9%. Only 3.7% of appearances genuinely have no coloured region.

Data is packed at 5 bytes per colour cluster and decoded lazily on first use,
which costs about 13 MB of addon memory. Stored as plain Lua tables it was 95 MB.

### Greyscale

Three buckets: black, grey, white. **Colour beats tone** — an appearance is
greyscale only if its coloured regions together cover less than a fifth of it.

*Together* matters. A shoulder whose red is split across the red and rust bands
is not thereby black; asking whether one single hue dominates gets 1,822
appearances wrong.

Which colour a piece then becomes is its most **colourful** region, not its
largest. Those differ, and not randomly: WoW's shadows are bluish, so shadowed
pixels that barely register as coloured pile up in the blue-violet range and win
on sheer area. Ranking by area quietly made purple the colour of dark armour.

That rule is doing the heavy lifting. Only **3.7%** of appearances have no
coloured region at all, so a greyscale bucket holding much more than that is
simply mislabelling colourful armour. It used to hold 29.5%, about eight times
too many, and 87.4% of the pieces it called neutral had a coloured region
covering a median 17% of the piece. With the rule in place it holds 15.0%.

```
/tmpalette colorfirst 0.25
```

tunes the threshold from 0 to 1; lower means more colour and less greyscale. It
is adjustable rather than fixed because it trades two opposite mistakes against
each other — colourful armour filed as black, versus a black piece with gold
trim rolling as gold — and there's no measurement that settles where the line
belongs.

A piece's greyscale tone is the **area-weighted average of all its greyscale
regions**, not its largest one. The extraction reports shadows, mid tones and
highlights separately, and shadows are always plentiful — picking the biggest
region made mid-grey armour read as black. One shoulder appearance spread evenly
from 0.16 to 0.78 was filed as black on the strength of its shadows alone.

Whether a region counts as *coloured at all* is decided offline in CIE
L\*a\*b\*, against a chroma floor that rises with lightness, and shipped as a
flag alongside the colour. The addon trusts that flag rather than re-deciding
from HSV, which can't tell washed-out purple (still reads purple) from
washed-out orange (reads brown). The flag is also what lets dark colours keep
their hue: judging "is this black?" by brightness alone had put 1,042
appearances in the black bucket that were really dark colours, 657 of them
purple, violet or indigo.

### Coverage

The table is built from every `ItemAppearance` row in the game's data, not from
any one collection, so coverage doesn't depend on how many appearances you own —
someone with a huge wardrobe gets the same coverage as someone starting out.

**99.75%** of every `ItemAppearance` row has colour data — 64,722 of 64,883.
Of the 161 without, most *should* have none: 94 are ammo and other items with
neither a model nor a texture, and 26 are the "hide this slot" entries like
`No Gloves`. About 40 are genuinely unresolved. Anything without data is hidden
while a colour filter is active, and never rolled.

Weapons used to make up the bulk of the gap. Their texture is baked into the M2
rather than referenced through `ItemDisplayInfoMaterialRes`, and the pipeline
read only the latter — so 968 appearances, mostly weapons and model-based armour
going back to Classic, resolved to nothing. See `resolve_baked_texture_fdids`.

Appearances added by a **content patch** won't have data until the table is
regenerated — see below. That's the one case where coverage drops.

## Development

The addon ships with complete colour data; nothing below is needed to use it.

### Updating for a new game patch

Do these in order — each one is a way the addon can look fine and be wrong:

1. **Refresh the colour data.** This reads the game's full appearance list
   (~64,900 rows) straight from Blizzard's data — there is **no in-game step**
   and nothing to browse:
   ```
   cd tools
   python -u generate_color_data.py --all --jobs 6 --refresh-db2
   ```
   `--all` is the default if you give no source, so forgetting it is safe.
   Textures are cached between runs, so a patch update only fetches genuinely
   new artwork rather than repeating the full first run.
   `--refresh-db2` is **required after a patch**. The DB2 CSVs are cached by
   table name and reused indefinitely, so without it the run silently rebuilds
   from the *previous* patch's tables and produces a file with none of the new
   appearances — a run that looks completely successful and changes nothing.
   The script warns if the cache is more than 14 days old.

   Always use `python -u`; without it the progress output buffers and the run
   looks hung. It's resumable — re-run the identical command after any
   interruption.

   `--offline` rebuilds `ColorData.lua` from the existing profile cache and
   never fetches. Use it whenever you change something *downstream* of pixel
   profiling — cluster ranking, which fields are emitted, the pack format —
   since none of that needs new pixels. It takes seconds instead of hours and
   can't accidentally start a multi-gigabyte download. It is **not** valid for
   a patch update: new appearances have no cached profile and are omitted.

2. **Bump `## Interface:`** in the `.toc` to the new build, or the client will
   flag the addon as out of date and players must opt in to loading it. Get the
   number in-game with `/run print(select(4, GetBuildInfo()))`.

3. **Check coverage** against a client on the new patch:
   ```
   python check_coverage.py "<path to SavedVariables\TransmogPalette.lua>"
   ```

4. Bump `## Version:`, add a `CHANGELOG.md` entry, and
   `pwsh tools/build_release.ps1`.

### Recording appearances (rarely needed)

`--all` covers everything, so recording is only useful for targeting a specific
subset. It is **off by default** — left on it grows a player's SavedVariables
with data the shipped table already contains.

```
/tmpalette record on      -- in-game, then browse the Transmogrifier
/reload                   -- flush SavedVariables to disk
/tmpalette record off
```

### Analysis harnesses

These mirror the addon's Lua logic and are the method, not scratch work. Re-run
them after touching the classifier, the hue bands, the colour groups, or the
canonical swatch colours:

- `tools/score_overrides.py` — **the one to use.** Scores the classifier against
  colours you named yourself in game with the override picker, read back out of
  SavedVariables. Start here; the workflow is in its docstring.
- `tools/analyze_names.py` — scores against an answer key mined from item names
  (4,470 appearances, no downloads — `ItemSparse` is already cached). This is
  how the gold band was found to start 6° too high, and it is **exhausted**: the
  key is wrong about a third of the time, and four separate changes have now
  scored well against it and been wrong in game. Good for catching something
  badly broken; useless for choosing between two reasonable options. Read the
  docstring before trusting a number.
- `tools/label_sheets.py` — renders items to contact sheets to be named by hand.
  Faster per item than the override picker, but only items with their own model
  can be drawn (cloaks, shoulders, helms, weapons), so it skews toward weapons
  and cannot see the component slots at all — see `m2_render.py`.
- `tools/analyze_grain.py` — bucket sizes per grain, plus two invariants: a
  bucket's average colour must classify back into that bucket, and so must the
  canonical colour the swatch is drawn as. Both caught real bugs.
- `tools/analyze_groups.py` — grouping balance, and rank-1 vs largest-area for
  choosing an item's colour.
- `tools/analyze_dominance.py` — how much of an item its dominant colour covers.
- `tools/luacheck.ps1` — comment/string-aware Lua block-balance check, since
  there's no Lua interpreter on the dev machine.

### Building a release

```
pwsh tools/build_release.ps1
```

Produces `dist/TransmogPalette-<version>.zip`, structured so the archive
contains a single `TransmogPalette/` folder. Version and interface number are
read from the `.toc`, and it fails if a file listed there is missing.

## Licence

MIT — see `LICENSE`.
