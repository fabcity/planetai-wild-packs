# singapore-nea

**What it adds:** Singapore's own official numbers for the point the node stands on, from data.gov.sg, so the node's
sensor is read against what NEA and PUB say about the same island. Air (PM2.5, PSI and the six pollutants), heat (air
temperature, humidity, WBGT), rain, wind, UV, flood alerts, dengue clusters and NEA's forecasts. No key needed.

Every reading is `kind='model'`, `local=False`, `scale='city'`: a station or a region kilometres away, never this house.
None of it is comparable with, or pooled into, the node's own sensors (`channels.yml` says so per metric).

## Feeds

| feed (`https://api-open.data.gov.sg/v2/real-time/api/...`) | what | nearest to the node? | asked every |
|---|---|---|---|
| `pm25` | hourly PM2.5, by region | region | 30 min |
| `psi` | 24 h PSI, six pollutants, sub-indices | region | 1 h |
| `air-temperature`, `relative-humidity` | 1-minute station readings | station | 5 / 10 min |
| `rainfall` | 5-minute total; also island-wide max and % of stations wet | station | 5 min |
| `wind-speed`, `wind-direction` | 10-minute mean, knots, degrees | station | 10 min |
| `uv` | hourly UV index, daylight only | island | 30 min |
| `weather?api=wbgt` | WBGT and NEA's Low/Moderate/High category | station | 15 min |
| `weather?api=flood-alerts` | PUB flood alert events; an empty list is the usual answer | island | 5 min |
| dataset `d_dbfabf16158d1b0e1c420627c0819168` | NEA dengue clusters (GeoJSON): inside one? how near? how big? | cluster | 6 h |
| `two-hr-forecast`, `twenty-four-hr-forecast`, `four-day-outlook` | NEA forecasts, stored as `fc_*` | area / island | 30 min / 3 h / 6 h |

Not here: lightning, and PUB's water-level sensors. Neither has an endpoint or a response format documented on
data.gov.sg's dataset pages, and this pack ships only what has been read off a live response.

## Rate limits

data.gov.sg answers `429` to an anonymous caller who asks fourteen feeds in one breath every poll, which is what this
pack first did. So each feed has its own interval (above), requests are spaced 0.7 s apart, and a feed that gets a 429
is left alone for 15 minutes. A free key in `NEA_API_KEY` raises the limit further and is optional. One feed failing
never takes another down; the poll only errors if every feed asked did.

## Rules

Fourteen, each in English, Indonesian and Spanish, in `rules.yml`. The thresholds are published bands: NEA's PSI bands,
NEA's own WBGT category, the WHO UV scale, PUB's flood alerts. Two are worth reading before you rely on them:

- **`heat_index_danger`** uses the US National Weather Service heat index, not WBGT, and says so. It stays silent
  whenever a WBGT reading under an hour old exists, because `heat_stress_high` and `heat_stress_moderate` are NEA's own
  category and are the better rule.
- **`rain_expected_soon`** is a forecast that speaks, at `info` level (a briefing, never a phone at the default
  `ALERT_LEVEL=act`). `packs/forecast` argues that forecasts should not speak at all; if you agree, change it to
  `contributes: report`.
- **`dengue_cluster_here` / `_near`** parse NEA's GeoJSON defensively (locality and case count are read from
  properties or from the HTML table NEA puts in `Description`) and test the node's point against the polygons itself,
  with no geometry library. Check them against a real payload before trusting the wording.

## What it does not know

The nearest station is the nearest by distance, not by what the weather is doing: rain is patchy, which is why the
island-wide maximum and wet-station share are stored beside it. WBGT is measured at a handful of stations. A dengue
cluster is where cases were notified, not where mosquitoes are. PSI is a 24-hour average and lags the air outside.

## Tests

`python3 packs/singapore-nea/tests/test_singapore_nea.py`: offline, against payloads shaped exactly like the live
responses (see the test's header for how to replace them with captures).

Data: NEA and PUB via data.gov.sg, Singapore Open Data Licence.

## Licence

Code: Apache-2.0, as planetai-node. Data: National Environment Agency and PUB datasets on data.gov.sg, under the [Singapore Open Data Licence v1.0](https://data.gov.sg/open-data-licence): attribution is required and NEA does not endorse this pack. The attribution text is in `pack.yaml`.
