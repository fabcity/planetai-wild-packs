# paddy

How much rice land in a square you choose is still farmed, and how much was green a year ago and reads bare or
built now. I wrote it for Bali, where the sawah is where food comes from and how the subak shares water, and where it
is sold for villas one field at a time. Nobody in a house sees that across a few kilometres.

It reads Sentinel-2 from Microsoft Planetary Computer, every clear 10 m pixel over 25 months, with no key and no new
library. It counts rice and nothing else. The design and the tests behind every threshold are in
`docs/superpowers/specs/2026-10-30-paddy-pack-design.md` in this repository.

## The five questions

| | |
|---|---|
| Which issue or decision does it inform? | `land`. Whether the rice land around you is still farmed, and when some of it goes. In Indonesia, rice land a regency has protected under Law 41 of 2009 may not be converted; the pack does not know which fields are protected, and gives a date and a place to someone who does. |
| Where does it show? | A section on Now, "Rice around this node", which the Wall reads aloud, and three readouts on Land. Land belongs to the `earth` pack, so without earth the readouts are left out and the section still carries them. |
| What can alert? | One `info` alert when at least half a hectare more reads as lost than at the read before. It names hectares and an H3 res-8 cell, never a parcel or an owner, and waits a month before it says it again. |
| What stays on this machine? | Nothing private: the land seen from orbit. The square's months stay in `out/paddy/` because nobody else needs them. |
| What outside service? | Planetary Computer's STAC search and blob storage, anonymous. `planetai run paddy verify` checks the settings, what is kept, the rule and the database. |

## Settings

There is no default square, because most places have no rice, and the rice that matters to a house may not be
around it. Until you set the size and answer the flood question, the pack does nothing.

```
PADDY_AT=              # lat,lon of the square's centre; blank is this node's own point
PADDY_RADIUS_KM=       # half-width, at most 10
PADDY_FLOOD_CHECK=     # on or off, see below
PADDY_READS=4          # the most scenes read in a day, one per poll
```

The flood question is there because going bare and green twice is what any field sown and harvested twice does. On declared
parcels in Segrià, Catalonia, which grows no rice at all, 95 % of the barley passed that alone. A flood followed by
a crop is what makes it rice. So with the check on, a pixel also needs a month with standing water (MNDWI above 0.2)
and canopy within four months after. In the Ebro delta that keeps 78 % of the declared rice and 0.1 % of every other
crop, and in Segrià nothing passes. Turn it on where the fields stand flooded in open basins.

Turn it off for terraced or tropical sawah. In Bali the check kept 3 % of the mapped farmland: a terrace stands
flooded for a few weeks, mostly in the wet season, when there is about one clear look a month, and a 10 m pixel
there mixes water, bund and palm. With the check off, the count is land that cycles like sawah, so the palawija sown
between rice crops is counted with the rice.

It needs `PACKS_ALLOW_CODE=1`. The history fills at PADDY_READS scenes a day, which takes weeks, or at once with:

```
planetai run paddy backfill      # 3 km on node #1: 95 scenes, 0.35 GB, 18 min; stop and restart it as you like
```

The hectares appear only once all 25 months are read. Before that the first year is empty, so lost would read zero
and rice would read low.

## What it counts

Every pixel of the square lands in exactly one of six states, and a test holds that they add up:

- **unclear**, fewer than 8 months with a clear look;
- **water**, most months' greenness at or below zero (or, with the flood check, wet in most of its looks);
- **lost**, green above 0.55 in most of its first-year months, and nothing above 0.15 for the last four. A fallow
  field grows weeds within weeks, and cleared ground or a roof does not. The page says "green a year ago, bare or
  built now", never "converted", because the satellite cannot tell a roof from a field scraped bare;
- **rice**, at least two falls in greenness from above 0.65 to below 0.35 and two rises back, and green above 0.6 in
  the last seven months. It takes two swings because one fall from green to bare is also what clearing land looks
  like. With the flood check, the flood as above;
- **green**, most months above 0.4: trees, gardens, other crops;
- **bare or built**, the rest.

## Where the thresholds come from

- **Greenness**, from a strip of Badung from Canggu to Pemogan, October 2024 to October 2026, two crops a year
  (`Claude outputs/s1-rice-test-2026-10-30/` in the Fab City folder). There 1,420 ha cycled as rice, and 25 to 40 ha
  went from green to bare or built. `planetai run paddy reproduce` re-runs it.
- **The flood**, from declared parcels in the Ebro delta and Segrià, 2024 and 2025 (DUN, Generalitat de Catalunya).
- **The cloud cut**, scenes under 50 % cloud, and SCL classes 4, 5 and 6 as clear, as in the Badung test.

These were measured in Badung and the Ebro. Anywhere else, check them against fields you know before you trust them.

## How it was checked

- The reader against rasterio, on two scenes at Canggu (18 and 23 Oct 2026): every pixel's greenness and water
  index the same.
- The rule against the numpy rule of 30 Oct, on the same monthly stacks: the same rice pixels in the Badung strip
  (1,529 ha) and in the Ebro delta with the flood check on (7,194 ha).
- `tests/test_paddy.py`, offline: the 15-bit unpacker, a tiled TIFF written by the test and read back, the offset,
  the six states on made-up pixels (two crops, one flooded crop, barley, a cleared field, a lawn, a pond, cloud),
  and the poll's pace.

## What it does not know

- Which crop. With the flood check off, any field sown and harvested twice counts.
- Tree plantations in the tropics. Oil palm, coffee and cacao were not tested. They stay green all year, so the
  rule should not count them, but nobody has checked.
- Whether the thresholds hold in terraces. Only 48 % of Bali's OpenStreetMap farmland passes two full swings at
  0.65 and 0.35, and 63 % at 0.55 and 0.40. OSM farmland is a weak label, so the numbers stay as measured at Canggu
  until a subak's own map or a walk through the fields settles it.
- Flooded or harvested at the newest look. Greenness cannot tell them apart, so the stage reads "bare or flooded".
- The wet season. In December to February there is about one clear look a month, and some months none.
- A square on a UTM zone edge reads only its own zone's tiles.
- Fields, parcels and owners. It speaks in hectares and H3 cells.

## Licence

The code is Apache-2.0, and its TIFF reader and projection come from the node's `surface-heat` pack. The data is
Copernicus Sentinel data, free, full and open under the Copernicus data policy (Commission Delegated Regulation (EU)
No 1159/2013), with the notice the Commission asks for, "Contains modified Copernicus Sentinel data [year]". The pack
fills in the years it read. Microsoft hosts it.
