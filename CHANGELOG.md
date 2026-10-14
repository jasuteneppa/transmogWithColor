# Changelog

## 1.3.1

**Colours for appearances added in 12.1.5.** The new swords, back pieces,
shoulders, boots and helm now show swatches and turn up under their colours,
like everything else. No other appearance's colours changed.

## 1.3.0

**Colours that match what you see.** Every appearance in the Collections
journal was looked at as the game actually draws it, lit and shaded on a
character, and its colours judged from that picture rather than from the
texture files. Shading was what kept fooling the old method: shaded red leather
came out brown, white plate came out grey, dark purple came out black. Tested
on items held back from the start, the number of clearly coloured items you
couldn't find under any of their colours fell from more than half to about 1 in
20.

**Items show up under every colour they have.** A black robe with red trim is
under black *and* red. Pieces that are mainly the colour you picked come first;
pieces that only carry some of it come after. Items with no clear colour are
still under their closest one, at the end of the list.

**Exclude colours.** Middle-click or Shift-click a swatch to leave out
everything that also has that colour. "Black and white, but nothing with red,
blue or green" is three clicks.

**Light and dark.** **More** now splits each colour into a light and a dark
half: black and white over dark and light grey, light and dark red, orange,
brown, gold, green and blue, and pink over purple.

**Colour filters in Collections → Appearances.** The same strip works in the
journal, including items you haven't collected yet, so you can see what's out
there in a colour before you go and get it. The journal's own filters
(collected, sources, class) still apply. Each tile shows its colours there too.

**Roll from a pool of colours.** A slot's colour can now be several colours:
pick gold and purple, and the slot rolls from all your gold and purple pieces.
Exclusions work here too. **All Slots** (was **Single Color**) sets one pool on
every slot at once. The roller's picker has its own **More** / **Less**, and
closes with the Transmogrifier.

**Swatches on every tile.** Each appearance shows its one or two main colours
in its corner, filter or no filter. Turn them off with the **Swatches**
checkbox or `/tmpalette swatches`.

**The strip can be moved.** Drag it by its background; each window remembers
its own spot. `/tmpalette resetpos` puts it back.

**Your saved colour picks are cleared once**, on the strip and on the roller's
slots, because the colours they named don't exist any more. Hand corrections
made with the override picker still apply.

`/tmpalette grain` is retired: the roller uses the strip's colours now.

Items added in a game patch have no colours until the next update of this
addon, which follows each patch.

Marked compatible with 12.1.0 and 12.1.5.

## 1.2.1

Support for game patch 12.1.

The addon is marked compatible with 12.1, so it loads on the new patch without
having to be enabled by hand.

**Colour data covers the patch's new appearances.** 12.1 adds 1,517 of them, and
1,503 have colour data — 99.1%, slightly ahead of the 98.7% coverage across the
rest of the game. The fourteen without are the usual display types that don't
resolve to a texture; like the others in that category they stay hidden while a
colour filter is active, and are never rolled.

**Fixed: choosing an appearance no longer throws you back to page 1.** With a
colour filter active, selecting something from page 2 or beyond returned the
list to the top — the choice itself was applied correctly, but you lost your
place and had to page back every time. The filter now restores the page it was
on. Changing gear slot still starts you at page 1, as it should.

Otherwise nothing changes. Filtering, the roller and the swatch strip behave
exactly as they did in 1.2.0, and your saved colours carry over untouched.

## 1.2.0

Usability. Picking a colour no longer means opening a popup, clicking, looking at
the results, and opening it again to try the next one.

**Every colour is on screen at once.** The three "main colour" boxes and the
accent box are replaced by a strip of swatches sitting under the search box.
Left-click one to filter by it, left-click again to drop it. There's no limit any
more — pick as many colours as you like and see the whole palette the entire
time. The three-box cap only ever existed because each pick cost a box.

**Right-click sets the accent.** It works the way it always did — the
appearance's *second* colour, narrowing every main colour at once — it just lives
on the same strip now, marked with a white corner.

**Broad colours by default, with shades a click away.** The strip starts with one
swatch per colour: eleven of them, a single row. The **More** button splits each
into its dark, mid and light shades when you want to be specific, and **Less**
groups them back. Your picks carry across the switch rather than being cleared —
one broad "green" becomes exactly the green shades it covered.

**Every swatch shows what it will find.** Hovering gives the number of
appearances in the current slot that match it as a main colour and as an accent.
Colours the slot has nothing in are dimmed rather than hidden, so the swatches
stay in the same place when you change slot — and a dimmed swatch answers "does
this slot have anything green" on its own.

**Randomiser: "All one colour".** A new button under Roll sets every slot to a
single colour in one pick, instead of eleven trips through the picker. Its
counts are the number of *slots* that can supply the colour, not the number of
appearances, since the question it answers is whether a full outfit exists.

**Randomiser: weapons.** Main hand and off hand now take a colour like every
other slot, and Roll stages them with the rest.

Rolls stay inside the shape you're currently displaying: a two-hander rolls
another two-hander, and one-hand-plus-off-hand rolls a one-hander and an off
hand. It never flips the silhouette on you — and because it reads what's
*displayed* rather than what's equipped, a two-handed weapon transmogged to a
one-handed axe rolls one-handers, which is what you're looking at. The swatch
tooltip names the shape it's rolling within.

Within that shape it draws from anything the slot legally accepts, so a sword
can roll into an axe or a mace. Illusions are left alone.

Existing filter selections are cleared on upgrade — the saved picks are stored as
bucket names, and both the shape and the default grain changed.

## 1.1.0

Colour matching accuracy, aimed at the black and grey buckets returning armour
that plainly didn't belong in them.

**Colour beats tone.** An appearance is now black, grey or white only if its
coloured regions *together* cover less than a fifth of it. Before, the greyscale buckets were
holding armour with obvious red, green or purple in it: only **3.7% of
appearances have no coloured region at all**, yet 29.5% were being filed as
greyscale — roughly eight times what the data supports. Of the pieces called
neutral, 87.4% had a coloured region, a median of 17% of the piece. Reported
case: *Beacons of the Black Talon*, four variants, none of them black, all
offered under a black shoulder roll.

Pooling the colours matters on its own: a shoulder whose red is split across the
red and rust bands is not thereby black, and 1,822 appearances were in exactly
that state. Which colour a piece becomes is still its largest single hue.

Greyscale drops to 15.0% of appearances, and the same rule now decides an
appearance's colour for both the filter and the roller, which previously
disagreed.

`/tmpalette colorfirst <0-1>` tunes it. Lower means more colour and less
greyscale. It's adjustable because it trades two opposite mistakes against each
other — colourful armour filed as black, versus a black piece with gold trim
rolling as gold — and the right balance is a matter of taste, not measurement.

**Purple stops being the colour of dark armour.** An appearance's colour was
decided by whichever coloured region covered the most surface — so a large dull
region beat a smaller vivid one, and that had a direction rather than being
noise. WoW's shadows are bluish, so shadowed pixels that barely register as
coloured at all pile up in the blue-violet range, and being numerous they won.
A chest that reads plainly green, off a glowing green panel, was filed under
purple behind a larger murky violet.

A region's colour now counts for how *colourful* it is as well as how large:
1,501 appearances had their area winner beaten by a rival at least 25% more
saturated and 15% brighter, and the loser was nearly always red, gold, green or
orange giving way to violet, indigo or blue. Purple drops from 8,335
appearances to 6,905, with orange, brown and red picking up the difference.

**Grey armour stops reading as black.** A piece's greyscale is measured as up to
three separate lightness regions — its shadows, its mid tones and its highlights
— and the addon was picking whichever single region was largest to decide the
whole piece's tone. Shadows are always plentiful, so that answer skewed dark:
one shoulder appearance is 92% greyscale spread evenly from 0.16 to 0.78, an
obvious mid grey, and it was filed as black because its shadows held 41%. Those
regions are now averaged by area, and on a live Shoulders list this moved 10 of
17 appearances out of black and into grey where they belong. It also fixes the
accent, which could previously be a second shade of the *same* grey.

**Three greyscale buckets, not five.** Black, grey and white. `darkgray` and
`lightgray` are gone, and so is the warm/cool split that briefly replaced them:
at the brightness where "black" lives, a warm black and a cool black render as
`rgb(35,27,19)` and `rgb(19,27,35)`, which is not a distinction anyone can see
on a swatch. The picker had grown eleven near-identical dark squares.

**Dark colours stay colours.** An appearance used to be called black on
brightness alone, before saturation was even considered. That put 1,042
appearances in the black bucket that were really dark colours — 657 of them
purple, violet or indigo. Whether something has a hue is now decided
perceptually, in CIE L\*a\*b\*, at data-generation time.

Your saved filter colours and slot assignments are cleared once on upgrade,
because the bucket names have changed and an old pick would otherwise sit there
looking active while matching nothing.

Colour data is regenerated: still 63,742 appearances, now carrying each
cluster's true tint and an explicit achromatic flag. Packing goes from 4 to 5
bytes per cluster, about 10 MB of addon memory rather than 8 MB.

All three analysis harnesses now share one parser and one classifier, so they
can't drift from each other or from the addon. `analyze_grain.py`'s two
invariants — a bucket's mean colour and its drawn swatch must each classify back
into that bucket — pass at all four grains, and `analyze_groups.py` prints the
neutral-discount sweep the shipped value was chosen from.
`generate_color_data.py` gains `--offline`, which rebuilds the table from the
cached texture profiles without any network access.

Known and not fixed: on items with two models (shoulders, mostly), the second
texture is paired with the wrong model's geometry and so is analysed unweighted.
Measured cost is 29 appearances, so it is a correctness issue rather than a
visible one.

## 1.0.0

First public release.

**Colour filter** — in the Transmogrifier window, pick up to three main colours
(OR'd together) plus an optional accent colour, and the appearance list narrows
to matching items. The picker only offers colours that actually occur in the
current slot, and every swatch shows how many appearances it will return.

**Random outfit roller** — assign a colour to any gear slot from the swatch
beside it, then press Roll to stage a random matching appearance in every
assigned slot at once. Nothing is spent until you press Blizzard's Apply.

- `/tmpalette` — help
- `/tmpalette grain fine|medium|coarse|broad` — how coarsely the roller groups
  colours. Coarser means fewer colours with more appearances behind each.
- `/tmpalette roll`, `/tmpalette slots`

Colour data covers 63,742 appearances, extracted offline from the real worn
textures (not item icons) as ranked dominant colour clusters in CIE L\*a\*b\*
space. Packed to about 8 MB of addon memory.

Coverage is built from the game's full appearance list rather than any one
collection, so it doesn't depend on how much you own — measured at 98.7% of the
appearances the Transmogrifier lists. The remainder are display types that don't
resolve to a texture; they're hidden while a colour filter is active.
