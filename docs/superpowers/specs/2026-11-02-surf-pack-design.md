# Design: the `surf` wild pack

*Asked, 2 November 2026, by Tomas: "can we explore making a surf forecast pack for the planetai node?", then "it is
about personal decision at this level, as a personal node", then "for me is enough to get a message in the bot
suggesting where surf could be good, and suggesting checking more details about them", and "Evening before".*

**Status: proposed 2 November 2026. Nothing built.** §9 lists what is still open, §10 says what done means.

## 1. What it is for

One decision, made the evening before: is it worth getting up for a surf tomorrow, and where? The node does not
decide it. It reads swell, wind and tide for the breaks the keeper surfs, and when one or more of them look good
for tomorrow, the bot sends one message around 17:00 that names up to three spots with their best hours, the
numbers behind each, and a Windy link to check them properly. On a day where nothing looks good the node says
nothing.

This is a personal pack for a personal node. Node #1 is Tomas's house in Ungasan, a few kilometres from Uluwatu,
Padang Padang and Bingin. It is not a community surf report, and the pack makes no claim about a break that a surfer
looking at the water would not make better.

## 2. Decisions taken, and why

- **A wild pack.** It is written for one place (Bali's spots) and one person's habit. The node's rule makes that
  wild (planetai-node `skills/write-a-pack`, §1). A second coastal node with its own spots file is what would make
  it worth promoting.
- **Open-Meteo, not Windy, for the data.** Windy's Point Forecast API is its own product, separate from the Windy
  app subscription Tomas pays for: 990 € a year for real data, and its free key returns "randomly shuffled and
  slightly modified data", for development only (api.windy.com/point-forecast/pricing, read 2 November). Open-Meteo
  is free for non-commercial use, CC BY 4.0, and the node already uses it: the core `coast` pack reads the same
  marine API, and `forecast` reads the weather one.
- **Windy for the looking.** Each spot in the message carries a windy.com link to its coordinates. Tested 2 November
  in a browser: `https://www.windy.com/-8.815/115.085?swell1,-8.815,115.085,12` opens the Uluwatu point forecast with
  its Wave & Tide tab. Whether it opens the Windy app on a phone instead of the website is not tested.
- **The pack screens, it does not forecast surf.** The marine model's grid is about 8 km (MeteoFrance MFWAM, 0.08°),
  so Uluwatu and Bingin read the same cell, and Open-Meteo says itself that "accuracy at coastal areas is limited".
  What tells one break from the next is how it faces the swell and the wind, and what tide it needs. Those are
  written down per spot (§4) and are the pack's real content.
- **Season comes from the wind.** The west and Bukit breaks work when the south-east trades blow (roughly April to
  October), the east coast when westerlies blow (roughly November to March). A spot's offshore wind direction
  already encodes that, so there is no season setting. November is the change-over, which is when the message is
  most useful.
- **A `warn` rule sends the message.** In the node, `act` alerts always reach the phone but each one is an open ask
  counted in ρ; a surf tip is not an ask the node should measure itself by. `warn` reaches Telegram when
  `ALERT_LEVEL` is `warn` or `info`, and node #1 runs `ALERT_LEVEL=warn`. A keeper on the default `act` will not get
  the message, and the README says so.
- **Standard library only.** Two HTTP calls and some arithmetic. No `pip:` line, no image rebuild.

## 3. The data and its licence

Two Open-Meteo endpoints, both key-free, both multi-location (one request carries every spot, comma-separated):

- **Marine, swell**, `https://marine-api.open-meteo.com/v1/marine` with `models=ncep_gfswave016`, hourly:
  `swell_wave_height`, `swell_wave_period`, `swell_wave_direction`, `secondary_swell_wave_height`,
  `secondary_swell_wave_period`, `secondary_swell_wave_direction`, `wind_wave_height`. `forecast_days=3`, `timezone`
  = the node's. Registry: `environmental/bioregion/open-meteo-marine` (already pinned, used by `coast`).
- **Marine, tide**, the same endpoint with the default model, hourly `sea_level_height_msl` only (MeteoFrance SMOC;
  GFS Wave has no sea level).
- **Weather**, `https://api.open-meteo.com/v1/forecast`, hourly: `wind_speed_10m`, `wind_direction_10m`,
  `wind_gusts_10m`. Registry: `environmental/planet/open-meteo`.

**Why GFS Wave for the swell.** Open-Meteo's default for Bali is MeteoFrance MFWAM (0.08°). For Uluwatu at 07:00 on
28 October, a day Tomas remembers as good, MFWAM gave 2.06 m at 8.8 s from 204°, and GFS Wave 0.16° gave 1.54 m at
12.1 s from 203°. Both are "swell period", but MFWAM's runs about 3 s shorter, much like a mean period next to a peak
period. Surf apps, Windy included, show numbers like GFS's. With GFS the message reads like the Windy screen it links
to, and the thresholds can be set in the units surfers already think in. `swell_wave_peak_period` is null in both
models here, and ECMWF WAM returned nothing for Bali. GFS's grid is coarser (16 km): Uluwatu and Green Bowl read the
same cell, -8.83, 115.17. The weather model's wind is the same story: both spots came back from one point, -8.82,
115.16. So on the Bukit the spots really differ only by how they face, and by the tide they need.
`sea_level_height_msl` includes the tide (Open-Meteo: it "accounts for ocean tides, the inverted barometer
effect…", from MeteoFrance SMOC at 0.08°) and swung from −0.5 m to +0.98 m at Uluwatu over 2 November, and from
−1.18 m to +1.70 m on 28 October (springs), which looks like
Bali's tide. Its datum is mean sea level, not chart datum, so the pack only uses it to say low, mid or high
relative to that day's own range.

Licence: CC BY 4.0, attribution "Weather and marine data by Open-Meteo.com (CC BY 4.0); Copernicus Marine /
MeteoFrance". The free tier is for non-commercial use, under 10,000 calls a day per public IP. A call counts once
per location, so twelve spots cost 36 calls a poll (swell, tide, wind), under 300 a day at one poll every 3 hours. Node #1 shares its IP with the
rest of the house, and its forecast pack once ran into this cap (13 October, fixed since), so the 3-hour throttle
is a requirement, not a nicety.

## 4. Spots

A `spots.yml` in the pack. Each spot has a name, its coordinates (on the break, used for the wind call and the
Windy link; the marine call snaps to the nearest sea cell by itself), the directions of swell it is open to, the
wind directions that blow offshore there, a size range for the primary swell in metres, and the tides it works on
(`low`, `mid`, `high`, any subset).

**The table below is a first draft from general knowledge, not from anyone who surfs these breaks.** Tomas corrects
it before it is built; it is the part of the pack most likely to be wrong. Sizes are in GFS Wave's terms, which read
about three quarters of MFWAM's heights on both of Tomas's good days (1.54 against 2.06 m, 0.80 against 1.04 m), and
so likely lower than what a surfer would call the size from the beach. Uluwatu's 0.7 m floor is set from 1 November
(§5); the others are the draft scaled by 0.75.

| id | name | lat, lon | swell from | offshore wind from | swell m | tide |
|---|---|---|---|---|---|---|
| uluwatu | Uluwatu | -8.8150, 115.0870 | 180–250 | 60–150 | 0.7–3.0 | low, mid, high |
| padang-padang | Padang Padang | -8.8110, 115.1000 | 190–250 | 60–150 | 1.4–3.0 | mid, high |
| bingin | Bingin | -8.8055, 115.1125 | 190–250 | 60–150 | 0.8–1.9 | mid, high |
| balangan | Balangan | -8.7905, 115.1220 | 190–250 | 60–150 | 0.8–1.9 | mid, high |
| kuta-reef | Kuta Reef | -8.7400, 115.1550 | 180–250 | 45–135 | 0.8–2.2 | mid, high |
| canggu | Canggu (Batu Bolong) | -8.6595, 115.1300 | 190–250 | 20–110 | 0.6–1.9 | mid, high |
| medewi | Medewi | -8.4170, 114.8040 | 190–250 | 0–90 | 0.8–2.2 | mid |
| nusa-dua | Nusa Dua | -8.8050, 115.2370 | 150–220 | 240–320 | 1.1–3.0 | low, mid, high |
| serangan | Serangan | -8.7300, 115.2400 | 150–210 | 240–320 | 0.6–1.5 | mid, high |
| sanur | Sanur Reef | -8.6900, 115.2700 | 150–210 | 240–330 | 0.9–2.2 | mid, high |
| keramas | Keramas | -8.5550, 115.4310 | 150–220 | 240–340 | 0.8–1.9 | mid, high |
| green-bowl | Green Bowl | -8.8475, 115.1700 | 170–230 | 300–30 | 0.8–2.2 | mid, high |

`SURF_SPOTS` (setting, comma-separated ids) picks the spots the keeper cares about. Blank means the pack idles and
writes nothing, so it never calls Open-Meteo for a node that installed it by accident. Node #1 would set all of
them.

## 5. The rule, hour by hour

For each watched spot and each hour of tomorrow from 05:00 to 18:00 local, the hour **passes** when all four hold:

1. **Swell.** Of the primary and secondary swell, take those that come from inside the spot's window with a period
   of at least `SURF_MIN_PERIOD` seconds (default 10); if both do, the one with the larger height² × period. That
   swell's height must be inside the spot's range, and its height, period and direction are the ones the window's
   weight and the message use. A big swell from outside the window never counts.
2. **Wind.** Either it blows from inside the spot's offshore arc at no more than 25 km/h, or it is under 8 km/h from
   anywhere (glassy).
3. **Tide.** The sea level that hour, placed within that local day's lowest and highest, falls in a third the spot
   accepts (bottom third low, middle mid, top third high).
4. **Not junk.** `wind_wave_height` is less than half the height of the swell chosen in 1, so a wind-blown sea does not pass as a
   swell.

A spot is **good tomorrow** when at least two hours in a row pass. Its window is the longest such run, and its
weight is swell height² × period averaged over that run (a rough measure of swell energy), which orders the spots
in the message.

Every number here (10 s, 25 km/h, 8 km/h, the thirds, two hours) is a first guess. Tomas gave three days to check
them against: Uluwatu good on Wednesday 28 October and on Sunday 1 November, and Green Bowl "not so good" on
1 November. A throwaway run of this rule over 27 October to 2 November (Open-Meteo's archive of its own forecasts)
gave, with the longest passing run in hours:

| model, floor, Uluwatu min | Uluwatu 27 28 29 30 31 · 1 2 | Green Bowl 1 Nov | all three right |
|---|---|---|---|
| MFWAM 10 s, 1.0 m | – – – – – · 3 7 | – | no, misses 28 Oct (8.8 s) |
| MFWAM 9 s, 1.0 m | 8 2 – – – · 5 8 | – | yes, but 28 Oct by two hours |
| MFWAM 8 s, 1.0 m | 14 8 – – – · 8 9 | – | yes; also calls Green Bowl good on 2 Nov |
| GFS 10 s, 1.0 m | 14 8 11 7 – · – – | – | no, misses 1 Nov (0.80 m at 13.8 s) |
| **GFS 10 s, 0.7 m** | **14 8 11 8 – · 8 9** | **–** | **yes, with long windows** |
| GFS 12 s, 0.7 m | 14 5 – – – · 8 9 | – | yes |

The design takes GFS Wave at 10 s with Uluwatu from 0.7 m. It is right on all three days with long windows, and its
numbers are the kind Windy shows. Its weakness is that Uluwatu passes six days of seven, because there is no day
yet that Tomas calls bad at Uluwatu. Three days are a sanity check, not a calibration: the first weeks of messages
are the calibration, and a day Uluwatu was not worth it is the next most useful fact (§9).

Green Bowl failed on 1 November for two reasons: the tide was low until 11:00, and the south-east trade, which is
onshore on that south-facing coast, reached 14–20 km/h from mid-morning.

A known gap: the weather model does not see the morning land breeze that often makes Bali glassy at dawn before the
trade wind fills in. The pack will under-call early sessions on some days.

## 6. How it runs in the node

- **adapter.py**, `fetch(hc) -> (sensors, readings)` like every pack. It fetches at most every 3 hours. The node
  re-imports every adapter on every poll (`app/packs.py`, `adapters()`), so module-level state does not survive; the
  throttle is a stamp file in `PACK_OUT` (default `/app/out`; `/app/data` is mounted read-only) checked by its mtime,
  the way `packs/forecast/adapter.py` does it. Settings are read with `os.getenv`. As a wild code pack it loads only
  with `PACKS_ALLOW_CODE=1`.
- **What it stores.** One sensor per watched spot, `surf-<id>`, `kind: model`, `scale: bioregion`, `local: false`,
  with the spot's own coordinates and name. Each fetch writes one row per spot per metric, **timestamped at the fetch**,
  each describing the next local day: `surf_good` (1 or 0), `surf_from_h` and `surf_to_h` (the window, local hours),
  `surf_swell_m`, `surf_period_s`, `surf_swell_dir`, `surf_wind_kmh`, `surf_wind_dir`, `surf_tide` (0, 1, 2 for low,
  mid, high at the window's start) and `surf_weight`. Fetch time, not tomorrow's midnight, because `readings` is
  unique on (sensor, metric, ts) and the insert is `ON CONFLICT DO NOTHING`: a row stamped at a fixed future time
  would keep the first forecast of the day and never take a later one. Hourly detail is not stored: the message needs
  the window, and Windy shows the hours.
- **channels.yml.** Every metric `role: derived`, `comparable: false`. Not `private`: the values are a public model
  read at public coordinates, and `private` would also hide them from the node's agent, so the bot could not answer
  "tell me more about Keramas". The cost is that the rows travel in the daily export like `coast`'s already do.
- **rules.yml, one rule.** `surf_tomorrow`, `level: warn`, `cooldown_minutes: 720`. Its SQL returns one row
  (`sensor_id: 'surf'`) only when the local hour is 17 (the rule session runs in the node's timezone, `app/db.py`;
  the hour is fixed in the SQL because rules run as `planetai_ro`, which cannot read `settings`) and at least one
  spot's newest rows, written today, have `surf_good = 1`. The row carries the top three spots by `surf_weight`
  already joined into one text column, newlines included (the template is filled with `str.format` and Telegram gets
  plain text), each line with the name, window, swell, wind, tide and a Windy link built from the sensor's
  coordinates. Quiet hours do not touch 17:00.
- **Message**, en, es and id, roughly:

  > 🌊 Surf could be good tomorrow:
  > • Keramas 6–9: 1.6 m at 12 s from the S, wind 6 km/h W (offshore), mid tide → windy.com/-8.555/115.431?swell1,…
  > • Nusa Dua 7–10: 2.1 m at 12 s, wind 9 km/h NW, high tide → …
  >
  > A model screen at 8 km, not a surf report. Check them before you go.

- **No section, no issue, no readout** in v1. The message is the surface, because that is where Tomas said he wants
  it. A section on Now can come later if the message turns out not to be enough.

## 7. Not doing

- Windy data, or any paid or scraped surf service.
- Surf cams, crowds, or anything about other people at a break.
- Publishing anything to the network or the registry beyond the `sources:` line.
- Tide tables from a harbour authority. The model's tide is coarse but it is the same everywhere the pack runs.
- Learning from feedback in v1. Later, Tomas's 👍 or 👎 on the message could tune the thresholds per spot; the node's
  acted/measured loop is the natural home for that, and it needs nothing built now.

## 8. Tests

Offline, in `packs/surf/tests/`, from fixtures for 27 October to 2 November (the GFS swell, MeteoFrance tide and
wind responses for the spots, captured 2 November; the spike and its data are in the FAB CITY folder under `Claude outputs/surf-spike-2026-11-02/`, outside any repository, and are
re-fetched at build time with `start_date`/`end_date`):

- an onshore hour fails and the same hour with the wind turned offshore passes;
- a low-tide hour fails at a mid-and-high spot and passes at Uluwatu;
- a 12 s swell inside the window passes, an 8 s one does not, one from outside the window does not;
- one passing hour alone is not a window, two in a row are;
- 28 October and 1 November: Uluwatu is good, with a window that includes the morning; 1 November: Green Bowl is
  not;
- when only the secondary swell is in a spot's window, its height and period are the ones stored;
- the rule's SQL, run on duckdb or the node's test database as the other packs do, returns no row at 16:00, one row
  at 17:00 with at most three spots, and none when no spot is good.

## 9. Open

- **Spots and their numbers (Tomas).** The §4 table is a draft. Which breaks, and what each really needs.
- **A bad day at Uluwatu (Tomas).** Not needed to build, but it is the first thing that would tighten the rule:
  every known day so far is a good one there.
- **17:00 (my call).** Late enough that tomorrow's forecast has settled, early enough to plan the evening. Fixed in
  the rule's SQL; moving it is a one-line edit.
- **GFS Wave at 10 s, Uluwatu from 0.7 m, other sizes × 0.75 (my call),** right on all three of Tomas's days (§5).
- **Secondary swell (my call):** the in-window swell with more energy is the one that counts (§5.1).
- **`derived`, not `private` (my call),** so the bot can talk about it (§6).

## 10. Done means

1. `packs/surf/` with `pack.yaml`, `adapter.py`, `spots.yml`, `channels.yml`, `rules.yml`, `README.md` and tests;
   `tools/check.py` green; a `packs.json` entry; CODEOWNERS.
2. Node #1 runs it (standing rule: CI green, then node #1, then a real cycle, then merge): `SURF_SPOTS` set, one
   real 17:00 message on Telegram, or a logged evening where nothing passed and the stored rows say why.
3. Tomas opens a Windy link from that message and it shows the spot.
4. `tested: node 1` on the PR.
