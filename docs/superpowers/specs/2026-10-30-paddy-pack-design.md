# Design: the `paddy` wild pack

*Asked, 30 October 2026, by Tomas: "Yes, spec it", after a test that same day of whether satellites show the rice
cycle near node #1. The test, its figures and its scripts are in the FAB CITY folder under
`Claude outputs/s1-rice-test-2026-10-30/`, outside any repository.*

**Status: proposed 30 October 2026, its three questions answered the same day (§10), built 31 October in
`packs/paddy/`.** §11 is what done means, and says which items are done.

## 1. What it is for

The pack answers whether the rice land around a house is still farmed, and whether any of it is being lost. In Bali
the sawah is where food comes from and how the subak shares water, and it is sold for villas one field at a time.
Nobody in a house sees that across a few kilometres. The pack counts the hectares in the node's square that still go
through rice seasons, and says where the season stands at the last clear look. It also counts the hectares that
were green a year ago and are bare ground or roofs now.

What to do with that is for the household and its subak to decide. In Indonesia, rice land a regency has designated
as protected (*lahan pertanian pangan berkelanjutan*, Law 41 of 2009) may not be converted. The pack does not know
which fields are designated. It gives a date and a place to someone who does.

If the keeper's square has no rice, the pack has no decision there and the page says so in one line. Node #1's own
ground at Ungasan has none (§7).

## 2. Decisions taken, and why

- **A wild pack.** The node's rule is that a pack written for one place is wild, and it comes into `packs/` only by
  promotion, once it is useful beyond its place (planetai-node `skills/write-a-pack`, §1). The thresholds below were
  measured on one strip of Badung. A second place with rice, such as one crop a year in the Ebro delta or another
  Asian Fab City, is what would earn the promotion. Until then a wild pack cannot mount a route, so v1 has no map
  (§9).
- **Sentinel-2 only.** In the test the radar did not follow a field's own greenness (§4), and optical did.
- **Standard library only.** Planetary Computer stores the Sentinel-2 bands as 15-bit samples. `surface-heat`'s COG
  reader refuses that layout by name, and rasterio reads it. A plain-Python unpacker of about ten lines decoded a real
  478 kB tile in 0.05 s and matched rasterio on all 262,144 pixels (30 October). The rule over a 3 km square and 25
  months runs in 1.0 s in plain Python. So the pack copies `surface-heat`'s reader (Apache-2.0), adds the unpacker,
  and declares no `pip:` line. It needs no image rebuild, and its tests stay within what this repository allows:
  the standard library, PyYAML and duckdb.
- **Monthly lows and highs.** Keeping each pixel's lowest and highest greenness per month gave the
  same rice area as keeping every look, 90 % of the time (§5). That is 18 MB on disk instead of about 100 MB.
- **Pixels, then hectares and H3 cells.** Nothing is said per parcel or per owner.
- **Rice only.** Tomas asked whether the method works for other crops and plantations, and if it does not, to stay with
  rice. It does not (§4). Going bare and green twice is what any field sown and harvested twice does, barley as much as
  rice, and the rule cannot say which crop it saw. Tree crops seldom pass it. So the pack counts rice and nothing else,
  and where it can, it asks for a flood before it calls a field rice.
- **The keeper sets the square, in every place.** Most nodes have no rice, and the rice that matters to a house may
  not be around the house. So there is no default square. In Set up the keeper gives a centre (`PADDY_AT`, blank means
  the node's own coordinates), a half-width (`PADDY_RADIUS_KM`, up to 10), and whether the fields there stand flooded
  in open water (`PADDY_FLOOD_CHECK`, `on` or `off`, §5). Until the half-width and the flood answer are set, the
  adapter reads nothing and writes `months_read` as 0.

## 3. The data and its licence

- **Collection:** `sentinel-2-l2a` on Microsoft Planetary Computer. STAC search and a SAS token, both anonymous, the
  calls `surface-heat` already makes. Bands B04 (red) and B08 (near infrared) at 10 m, and SCL, the scene
  classification, at 20 m. Microsoft hosts the files, and the data is the Copernicus programme's.
- **Licence:** Copernicus Sentinel data is free, full and open under the Copernicus data policy (Commission Delegated
  Regulation (EU) No 1159/2013), with attribution. The node's `earth-engine` basemap credits it as "Contains modified
  Copernicus Sentinel data <years>". Owed before listing: a registry entry in awesome-fabcity-data,
  `environmental/bioregion/sentinel-2-l2a`, `status: candidate`, with the legal notice read and quoted from its
  text, and `sources:` naming it.
- **The offset.** Since processing baseline 04.00 (January 2022) every reflectance carries +1000, so reflectance is
  `(DN − 1000) / 10000`. The STAC items do not publish it: `raster:bands` was empty on baseline 05.13 on 30 October.
  The adapter reads `s2:processing_baseline` and subtracts 1000 from 04.00 on. Without it the test's greenness read
  near zero everywhere and found almost no rice.
- **Packing.** B04 and B08: deflate, no predictor, 15 bits a sample, packed most significant bit first, each row padded
  to a whole byte. SCL is 8-bit, and the existing reader opens it.
- **Clear pixels:** SCL classes 4 (vegetation), 5 (bare soil) and 6 (water). Anything else gives the pixel no look that
  day.
- **Cadence over Bali:** a scene every 2 to 5 days. On the test strip, 180 scenes from October 2024 to October 2026
  had some clear land. In December to February there was about one effective clear look a month, and none at all in
  December 2024, January 2025 and February 2026.

## 4. What the test showed

On a strip from Canggu to Pemogan, 14 to 21 km north of node #1, every 10 m pixel, October 2024 to October 2026:

| | Sentinel-2 greenness (NDVI) | Sentinel-1 radar |
|---|---|---|
| a rice field bare or flooded, then green | NDVI below 0.3, then above 0.7 | VV −7.3 dB both times |
| a field's own series against its own greenness | it is the greenness | median correlation −0.06 |
| land going through rice seasons | 1,420 ha | 54 ha that flood often enough to show |
| green in the first year, bare or built in the last four months | 40 ha by the strict rule, up to 127 ha | partly: a new building reads +15 dB |

The radar processing was simple: a 3 × 3 mean, one descending orbit, 10 m pixels. That rules out this method, and
radar itself might still work with better processing. It can see through the wet season, when optical goes blind,
which is the one reason to try it again (§9).

### Other crops and plantations (30 October)

The same monthly stacks, 24 to 25 months, were read over two places in Catalonia where every field's crop is declared,
and over the Bali strip. Labels in Catalonia are the farmers' declarations (DUN, Socrata `uwe8-jqcu`, Llicència
oberta d'ús d'informació – Catalunya), parcels with the same crop in 2024 and 2025, pixels inside the parcel only. The
Ebro delta grows rice in open flooded basins, one crop a year. Segrià, around Lleida, grows no rice: fruit, barley,
alfalfa and maize. In Bali the only label at hand is OpenStreetMap's farmland outlines, which can be old and can
include dry fields.

| labelled pixels | bare and green twice | and also flooded, then green (MNDWI above 0.2) |
|---|---|---|
| Ebro, rice, 6,393 ha | 96 % | 78 % |
| Ebro, every other crop, 1,338 ha | 13 % | 0.1 % |
| Ebro, other annual crops, 149 ha | 53 % | 0.1 % |
| Segrià, barley and triticale | 95 % | 0 % |
| Segrià, alfalfa, maize | 81 % | 0 % |
| Segrià, peach, nectarine, pear | 31 to 36 % | 0 % |
| Segrià, almond, apple, olive | 13 to 19 % | 0 % |
| Bali, OSM farmland, 1,479 ha | 46 % | 3 % |

The bare-and-green rule on its own finds land sown and harvested by season. In Segrià it would call 95 % of the barley
rice. Trees mostly fail it, and the third of peach and pear that passes is probably the mown or tilled rows between
them. Oil palm, coffee and cacao were not tested, since no labels were at hand. They stay green all year, so the rule
should not fire on them.

A flood followed by a crop is what makes it rice in Spain. With water above 0.2 on the index, 78 % of the Ebro's rice
stays and almost nothing else does, and Segrià drops to nothing. At 0.0 the Ebro keeps 90 %, but 13 % of Segrià
passes, probably the furrow and flood watering of its orchards and cereals. So the threshold is 0.2.

In Bali the same check keeps 3 % of the mapped farmland. A terrace stands flooded for a few weeks, mostly in the wet
season, when there is about one clear look a month, and a 10 m pixel there mixes water, bund and palm. So Bali runs
with the check off. There the count is land that cycles like sawah, rice and the *palawija* sown between rice crops
both, and the README says so.

## 5. The method

Per pixel, inside the keeper's square, half-width `PADDY_RADIUS_KM` around `PADDY_AT` (or the node's own coordinates,
never the published, rounded ones):

1. **NDVI** from B04 and B08 after the offset, for pixels SCL calls clear, and with the flood check on, MNDWI from
   B03 and B11 (resampled from 20 m) for the same pixels.
2. **On disk:** each month's lowest and highest NDVI per pixel, two byte arrays (NDVI × 100 + 100, with 255 for no
   clear look that month), for the last 25 months, in `out/paddy/`. With the flood check on, a third array holds each
   month's highest water index, MNDWI = (B03 − B11) / (B03 + B11), stored as MNDWI × 100 + 101. Against every look on the test strip, the rice
   area agreed 90 %: 1,519 ha from monthly values, 1,420 ha from every look, 1,395 ha in both.
3. **Rice:** at least two falls from above 0.65 to below 0.35 and two rises back, and some month in the last 200 days
   above 0.6. It takes two swings because one fall from green to bare is also what clearing land looks like. A
   one-swing rule in the test picked six "cleanest rice" pixels, and all six went from green in 2025 to bare in 2026
   and stayed bare. One of them shows a building going up in its radar. With `PADDY_FLOOD_CHECK=on`, the pixel also
   needs a month with MNDWI above 0.2 followed within four months by NDVI above 0.65. A pixel wet in more than 60 %
   of its clear months counts as water.
4. **Lost:** the median of the monthly highs over the first 12 of the 25 months is above 0.55, and no month in the
   last four rises above 0.15. A field left fallow grows weeds within weeks, and cleared ground or a roof does not.
   Here monthly and every-look values agree less: 32 ha against 40 ha, 25 ha in both. The page says "green a year
   ago, bare or built now", never "converted", because the pack cannot tell a roof from a field scraped bare.
5. **Every pixel lands in exactly one state:** `rice`, `lost`, `green` (trees, gardens, other crops), `bare_or_built`,
   `water`, or `unclear` (fewer than 8 months with a clear look). The six counts add up to the pixels in the square,
   and a test asserts it. Without that, a cloudy pixel would be counted as "no rice".

The README says where each threshold came from. The greenness thresholds came from one Bali strip with two crops a
year, and the flood threshold from the Ebro delta and Segrià. A node elsewhere checks them before trusting them. 25
months covers two seasons of a one-crop place like the Ebro, so the two-swing rule does not shut those out.

## 6. What it shows, and where

Sensor `paddy-square`, `kind='model'`, stamped with the date of the newest clear look, never the time of the poll.

| metric | meaning | role in `channels.yml` |
|---|---|---|
| `rice_ha` | hectares in state `rice` | `ambient`, `comparable: false` |
| `rice_lost_ha` | hectares in state `lost` | `derived` |
| `rice_bare_pct` | share of the rice bare or flooded at the newest clear look, which is the season's stage | `derived` |
| `clear_days` | days since a clear look covered at least half the square | `device_health` |
| `months_read` | months of history read so far, up to 25 | `device_health` |

- **Readouts on the `land` issue,** declared in `pack.yaml`: rice, lost, the stage, and days since a clear look.
  `land` is a context issue, so it reads them in its sentence and draws no line. The `earth` pack owns `land`, so
  on a node without `earth` the readouts are left out with a line in the log, and the section below carries them.
- **A declared section,** `stage: observe`, `wall: true`, titled "Rice around this node", with the same readouts plus
  `months_read`. A wild pack ships no code for the page, so the section has no conditional text. While fewer than 13
  months are read, the adapter writes only `months_read` and `clear_days`, and the other cards stay empty.
- **One rule, `paddy/lost`, `level: info`,** when `rice_lost_ha` has risen by at least 0.5 ha since the read before.
  `cooldown_minutes: 43200` with `long_cooldown_ok: true`. The message names hectares and the H3 res-8 cell, never a
  parcel or an owner: "1.2 ha around <cell> that was green a year ago reads as bare or built now." The `id` and `es`
  strings will be drafted by an assistant and need a native reader.
- **One report contributor, `paddy`,** so the report and the Wall can quote the numbers.
- **`agent_scripts: [verify]`,** and `requires: { node: ">=0.82.0" }` for sections on the Wall.
- **No cell** (§8).

## 7. Cost, and node #1

Measured from the tile byte-count tables of four recent scenes over Canggu. A node reads whole 512 × 512 tiles.

| half-width | per scene, B04 + B08 + SCL | a year, about 120 scenes under 70 % cloud | on disk |
|---|---|---|---|
| 3 km | 3.5 MB | about 0.4 GB, less with SCL read first | 18 MB |
| 10 km, the most a keeper can set | 22.6 MB | about 2.7 GB | 200 MB |

Scenes count when their cloud cover is under 50 %, the cut the test used, so a year is fewer scenes than the 120
counted above at 70 %.

The flood check adds B03 at 10 m and B11 at 20 m, and a third array on disk. That cost was not measured; B03 should
weigh about what B04 does, and B11 about a quarter of it. Set up shows the keeper the yearly figure for the size they
choose.

- **SCL first:** read a scene's SCL tiles, about 0.2 MB, and skip B04 and B08 when under 20 % of the square is clear.
- **Polite:** one STAC search a day, at most `PADDY_READS` scenes read a day (default 4), and a scene read once is
  remembered in `out/paddy/state.json`, as `surface-heat` does.
- **Backfill on command:** `planetai run paddy backfill` reads 25 months, about 0.8 GB at 3 km. Without it, the pack
  fills itself at `PADDY_READS` a day.
- **Code packs:** a wild pack's adapter runs only with `PACKS_ALLOW_CODE=1` on the node.
- **Sign again on a 403.** The Bali backfill on 30 October lost 7 of 222 scenes to 403s, probably a token that
  expired during a long run. The adapter asks for a fresh token on a 403 and retries the scene once.

Node #1 sits on dry limestone at Ungasan. Its radar was flat for two years, a 1.7 dB swing, and the nearest solid rice
is 14 km north. Centred on the node, any square would read "no rice here", which is true and useless. Since the
square is the keeper's, Tomas can centre node #1 on the paddies he wants to follow, for example the Canggu strip at
`-8.6388,115.1212`, with the flood check off.

The standing rule holds: node #1 runs the pack through a real cycle before it is listed. With its square on the
Canggu strip, that cycle proves the full case. `planetai run paddy verify` checks the kept square, the rule and the
database without the network, and is the one script an agent may run. `planetai run paddy reproduce --box
115.09,-8.71,115.23,-8.61 --flood off --end 2026-10 --expect-rice 1420 --expect-lost 36-44` re-runs the test strip
from nothing; it reads several GB, so it stays off the agent list (§11).

## 8. The Index

No cell in v1. A node's square is not a place, and the Index's food half is computed per place, where the production
gap is.

The Index-side job is separate. The fci-index build would run the same rule over each Index place once a year and
publish rice area and seasons per year as `state: partial`, labelled modelled. Area times seasons times a published
yield would estimate local rice production. Before modelling that, check whether BPS (Statistics Indonesia) publishes
rice production by regency under terms that pass the open rule. An official figure beats a modelled one.

## 9. Not in v1

- **A map** of the square, rice in green and lost in red, as in the test. It needs a route, which a wild pack cannot
  mount. It comes with promotion to core.
- **Radar** for the wet-season months, once field-averaged processing has been shown to follow greenness.
- **Flooded or harvested at the newest look.** The flood check looks back over months. The stage card still reads
  greenness only, and greenness cannot tell a flooded field from a harvested one.
- **Joins to other issues:** flooded fields and mosquitoes, straw burning after harvest and the air issue. Each
  waits for a household to say it happened here.
- **Field polygons** from OpenStreetMap or the subak's own maps, to speak per field.
- **Any crop but rice, and tree plantations.** Decided out (§2), on the evidence in §4.

## 10. Decided, and still open

Tomas answered on 30 October:

1. **The square is set by the keeper in every place,** and not every place has rice. So: centre, half-width and flood
   check in Set up, no default (§2), and the check of other crops in §4, which kept the pack to rice.
2. **Wild first.** Hosted here as `packs/paddy`, author Tomas Diez (Fab City). The Ebro run shows the method travels
   with the flood check on. A second node running it is what promotes it to core, and the map comes with that.
3. **The lost-land alert,** `info`, naming hectares and an H3 cell, never a parcel (§6).

Still open, and neither blocks v1:

- **Thresholds in terraces.** Only 48 % of Bali's mapped farmland passes two full swings at 0.65 and 0.35. At 0.55 and
  0.40 it is 63 %. OSM farmland is a weak label, so the thresholds stay as measured on the Canggu strip until a
  subak's own field map or a walk through the fields settles it.
- **Tree plantations in the tropics.** Oil palm, coffee and cacao are untested (§4).

## 11. Done means

1. The registry entry `environmental/bioregion/sentinel-2-l2a` is filed as a candidate, with the licence quoted from
   its text, and `sources:` names it.
2. `packs/paddy/` here holds `pack.yaml` (`env:`, `readouts:`, `sections:`, `agent_scripts:`, `requires:`,
   attribution), `adapter.py`, `rules.yml`, `channels.yml`, the `backfill` and `verify` scripts, and a README that
   answers the five questions of planetai-node `docs/decisions/2026-10-03-pack-design.md`.
3. `reproduce --box` re-runs the rule on a known paddy and asserts the six states add up to the box. On the
   Canggu strip, with the flood check off, it reproduces 1,420 ha of rice and the strict rule's 40 ha lost, each within 10 %. Done 31 Oct:
   1,424 ha and 41 ha. (This item said 25 to 40 ha until the run; 25 was where the monthly and every-look counts
   overlapped, and the test's own figure is 40.)
   `verify` checks the node's own square offline.
4. `packs/paddy/tests/test_paddy.py`, standard library only, on synthetic pixels: two rice seasons a year, one
   flooded season a year, barley sown twice and never flooded, a field cleared to bare, a lawn, a fish pond, and a
   pixel never clear. It asserts the partition, that the barley is rice with the flood check off and not with it on,
   the offset on baselines before and after 04.00, and the 15-bit unpacker against values it packed itself.
5. The Ebro run in §4 is reproduced once with the pack's own code, by hand, and recorded in the README: with the flood
   check on, at least 75 % of the declared rice and under 1 % of the other crops.
6. `python3 tools/check.py --node ../planetai-node` exits 0. One entry in `packs.json`, `kind: code`,
   `status: listed`, `tested_with` the release node #1 ran it on, and a CODEOWNERS line.
7. Node #1 runs it through a real cycle, on the square Tomas sets, before the pull request that lists it.
