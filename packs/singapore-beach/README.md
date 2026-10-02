# singapore-beach

NEA's weekly beach water quality banding for the beaches you follow, on the Coast card. It reports NEA's number; it
does not sample or predict the water.

**What it adds**
- One sensor per followed beach: `nea-beach-east-coast`, `nea-beach-changi` and so on (`BEACH_AREAS`, default
  `East Coast,Changi`; any of Changi, East Coast, Pasir Ris, Punggol, Seletar, Sembawang, Palawan, Siloso, Tanjong).
- Metrics: `beach_band` (worst stretch, 1 to 3), `beach_band_nearest` (the stretch nearest this node),
  `beach_stretches_elevated`, `beach_advisory`. The stretch names, their bands and the week are in the sensor's meta.
- Four rules, all in the coast issue and none paging: `beach_water_elevated` (Band 2), `beach_water_high` (Band 3),
  `beach_bacteria_advisory` (NEA's map advisory) and `beach_after_heavy_rain` (NEA's advice to stay out of the sea
  right after heavy rain).
- The Coast card shows each followed beach's band as a readout (`app/issues/coast.yml` names the two default beaches).

**Bands** are NEA's: Band 1 Normal (Enterococcus <= 200 per 100 mL), Band 2 Elevated (<= 500), Band 3 High (> 500, or two
weeks running in Band 2). Results take about a week in the lab, so a banding describes the week before it was published.

**Where the numbers come from.** There is no data.gov.sg dataset. The pack reads the JSON that nea.gov.sg's own beach page
loads, `/api/BeachWaterQuality/GetNeaData/<t>`, where `<t>` is the Unix time rounded down to five minutes. NEA's data is
reusable under the Singapore Open Data Licence v1.0 (attribution; no implied endorsement). **The endpoint is not a
documented API**: it can change or start refusing automated callers. When it does the pack logs one warning, raises, and
retries in half an hour, and the last real banding stays on the card with its real age.

**Assumes** the node can reach www.nea.gov.sg. Polls every six hours, one request.

**Does not know** which stretch you swim at, tides, or anything after NEA's last sample. Only the two default beaches have a
readout; another beach in `BEACH_AREAS` gets a sensor, rules and Figures rows only.

**Tests:** `python3 packs/singapore-beach/tests/test_singapore_beach.py` (offline; payload shape read from a live response, invented bands for the
Band 2, Band 3 and advisory branches).

## Licence

Code: Apache-2.0, as planetai-node. Data: National Environment Agency beach water-quality information (nea.gov.sg), under the [Singapore Open Data Licence v1.0](https://data.gov.sg/open-data-licence): attribution is required and NEA does not endorse this pack. The attribution text is in `pack.yaml`.
