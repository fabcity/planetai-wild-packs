# fire-smoke

**What it adds:** how many satellite-detected fires burned in the last 24 hours within a few hundred kilometres of
the node, and in which compass direction they lie. It exists for places downwind of somebody else's burning: Singapore
under Sumatran and Kalimantan smoke, Chiang Mai, Bali's dry season.

**It fetches. It does not predict.** A fire hotspot is not a plume. Smoke travels on winds well above the ground, for
hours to days, and can miss a place the ground wind points at. This pack says where fires are and, through its rules,
whether they are on the side the wind is coming from. What the air will do about it is the node's own PM2.5 and the
country's official PSI.

## Source and key

NASA FIRMS (Fire Information for Resource Management System), VIIRS 375 m near-real-time detections from Suomi NPP and
NOAA-20. Free. Get a `MAP_KEY` at <https://firms.modaps.eosdis.nasa.gov/api/map_key/> and put it in `.env`:

    FIRMS_MAP_KEY=your-key
    FIRE_RADIUS_KM=500
    FIRE_SOURCES=VIIRS_SNPP_NRT,VIIRS_NOAA20_NRT

Without a key the pack logs one line and idles. **The key rides in the URL path**, so the adapter strips the URL from
every error it raises: an exception from an HTTP client quotes the URL, and a log is a place keys should not be. If
you change this file, keep that property (`packs/fire-smoke/tests/test_fire_smoke.py` fails if the key appears in an error).

FIRMS allows 5,000 requests per 10 minutes. This makes two, every three hours, which is how often near-real-time
detections refresh.

## What it stores

One sensor, `firms-hotspots`, `kind='model'`, `scale='city'`, every metric `derived` and not comparable:
`fires_24h`, `fires_prev_24h` (the 24 hours before that, for the day-on-day change), `fires_250km_24h`, `fires_frp_mw_24h` (summed fire radiative power), `fires_nearest_km`, and
`fires_n`, `fires_ne`, `fires_e`, `fires_se`, `fires_s`, `fires_sw`, `fires_w`, `fires_nw`: the count in each 45-degree
compass sector **as seen from the node**. Low-confidence detections are dropped (VIIRS `l`, MODIS under 30).

## The two rules

Both compare the fires in the **upwind arc** with a threshold. The wind comes from NEA's station feed when the
`singapore-nea` pack is present, else from the forecast pack's `fc_wind_direction`. Upwind is the sector the wind
blows *from* and its two neighbours: 135 degrees, because a single reading of wind bearing wanders by more than 45.

| rule | fires upwind, last 24 h | level |
|---|---|---|
| `fire_smoke_upwind` | 50 to 199 | warn |
| `fire_smoke_upwind_heavy` | 200 or more | act |

**The thresholds are a first guess, not a calibration.** They were chosen so a quiet week is silent and a burning
season is not. Nothing here has been checked against a season of PSI. If you tune them, say what you tuned them
against.

## What it does not know

- Altitude winds. Smoke moves where the wind is a kilometre up, which the ground wind only approximates.
- Whether a hotspot is a cooking fire, a crop burn, a peat fire or an industrial flare. VIIRS sees heat.
- Cloud. A fire under cloud is not detected, so a low count is not a clear sky.
- Anything about the sea. Hotspots over water (gas flares, ships) are counted if they pass the filter.

Not a `live` cell, and no cell at all: the number is a satellite's, not something measured here.

## Tests

`python3 packs/fire-smoke/tests/test_fire_smoke.py`: offline. Parses a saved FIRMS table, checks the bearing to
sector arithmetic, the 24-hour and confidence filters, and that the key never appears in an error.

Data: NASA FIRMS / LANCE, free with attribution.

## Licence

Code: Apache-2.0, as planetai-node. Data: NASA FIRMS / LANCE active-fire detections, free to use with attribution (the text is in `pack.yaml`). A free MAP_KEY from NASA is needed; it is yours and is never logged by this pack.
