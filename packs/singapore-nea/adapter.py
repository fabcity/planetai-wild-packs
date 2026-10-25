"""Singapore NEA real-time feeds from data.gov.sg.

Public reference data for this island, not this household's sensor: kind='model', local=False, scale='city'.
Contract: fetch(hc) -> (sensors, readings), like everything in app/sources.py.

Feeds (all https://api-open.data.gov.sg/v2/real-time/api/<name>, no key):
  measured, nearest station or region to NODE_LAT/NODE_LON
    pm25              regional hourly PM2.5
    psi               regional PSI + the six pollutants + sub-indices (24 h / 8 h / 1 h averages, NEA's own)
    air-temperature   nearest station, 1 min
    relative-humidity nearest station, 1 min
    rainfall          nearest station, 5 min total; plus an island-wide max and wet-station share
    wind-speed        nearest station, 10 min mean, knots
    wind-direction    nearest station, 10 min mean, degrees (a compass bearing: never average these)
    uv                island-wide hourly UV index, daylight hours only
    weather?api=wbgt  NEA's heat-stress WBGT, nearest station, 15 min, plus NEA's own Low/Moderate/High category
    weather?api=flood-alerts  PUB flood alert events, island-wide, 2 min (an empty list is the normal answer)
    dengue clusters   NEA's cluster map (GeoJSON, fetched at most every 6 h): is the node inside one, how near is the
                      nearest, how big
  forecasts, prefixed fc_ (a forecast is nobody's measurement of this place)
    two-hr-forecast          the nearest of 49 areas, plus the share of areas expecting rain
    twenty-four-hr-forecast  the island: temperature, humidity and wind ranges, and whether rain is expected
    four-day-outlook         the same, one set per day ahead

Not here: lightning and PUB's water-level sensors. Neither has an endpoint or response format documented on
data.gov.sg's public dataset pages, and this file only ships what has been read off a live response.

Every feed is independent: one that fails is logged and skipped; the poll only fails when all of them do. Each feed
is also paced (EVERY below) and backs off after a 429. An optional free key, NEA_API_KEY in .env, raises data.gov.sg's
rate limit; leave it blank and the pacing alone should be enough.
"""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime, timezone
from math import asin, cos, radians, sin, sqrt

log = logging.getLogger("planetai.pack.singapore_nea")

BASE = "https://api-open.data.gov.sg/v2/real-time/api"
SOURCE = "singapore-nea"
ATTRIBUTION = "NEA via data.gov.sg"
RAIN_WORDS = re.compile(r"rain|shower|thunder", re.I)

# PSI response keys -> metric names. The suffix says the averaging window NEA uses, so it stays in the name.
PSI_METRICS = {
    "psi_twenty_four_hourly": "psi",
    "pm25_twenty_four_hourly": "pm25_24h",
    "pm10_twenty_four_hourly": "pm10_24h",
    "so2_twenty_four_hourly": "so2_24h",
    "no2_one_hour_max": "no2_1h_max",
    "co_eight_hour_max": "co_8h_max",
    "o3_eight_hour_max": "o3_8h_max",
    "pm25_sub_index": "pm25_sub_index",
    "pm10_sub_index": "pm10_sub_index",
    "so2_sub_index": "so2_sub_index",
    "co_sub_index": "co_sub_index",
    "o3_sub_index": "o3_sub_index",
}


# ---------------------------------------------------------------- helpers

def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2, dl = radians(lat1), radians(lat2), radians(lon2 - lon1)
    return 6371 * 2 * asin(sqrt(sin((p2 - p1) / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2))


def _ts(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(timezone.utc)
    d = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _num(v):
    """A float, or None for a missing value. NEA sends null and occasionally a string."""
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _kw() -> dict:
    """data.gov.sg rate-limits anonymous callers hard. A free key (NEA_API_KEY in .env) raises the limit; without one
    the pacing below keeps us under it."""
    key = os.getenv("NEA_API_KEY", "").strip()
    return {"headers": {"x-api-key": key}} if key else {}


def _get(hc, name: str) -> dict:
    r = hc.get(f"{BASE}/{name}", timeout=30, **_kw())
    r.raise_for_status()
    return r.json().get("data") or {}


def _sensor(sid: str, name: str, lat: float, lon: float, cadence: str, **meta) -> dict:
    return {"sensor_id": sid, "source": SOURCE, "name": name, "lat": lat, "lon": lon,
            "indoor": False, "local": False, "kind": "model", "scale": "city", "cadence": cadence,
            "meta": {"attribution": ATTRIBUTION, **meta}}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _latest(rows: list[dict], key: str = "timestamp") -> dict | None:
    """The newest row. Never assume an order the API does not promise."""
    rows = [r for r in rows if r.get(key)]
    return max(rows, key=lambda r: _ts(r[key])) if rows else None


def _rain_expected(text: str | None) -> float | None:
    return None if not text else (1.0 if RAIN_WORDS.search(text) else 0.0)


# ---------------------------------------------------------------- measured: regions

def _pm25(hc, lat, lon):
    data = _get(hc, "pm25")
    regions = {m["name"]: m.get("labelLocation") or {} for m in data.get("regionMetadata") or []}
    row = _latest(data.get("items") or [])
    if not row or not regions:
        return [], []
    vals = (row.get("readings") or {}).get("pm25_one_hourly") or {}
    ts = _ts(row.get("timestamp") or row.get("updatedTimestamp"))
    best = _nearest_region(regions, vals, lat, lon)
    if not best:
        return [], []
    name, rlat, rlon, v, d = best
    sid = "nea-pm25"
    return ([_sensor(sid, f"NEA PM2.5 ({name} region)", rlat, rlon, "PT1H", region=name, distance_km=round(d, 1))],
            [(ts, sid, "pm25", v)])


def _nearest_region(regions: dict, vals: dict, lat, lon):
    best = None
    for name, v in vals.items():
        loc = regions.get(name) or {}
        la, lo, v = _num(loc.get("latitude")), _num(loc.get("longitude")), _num(v)
        if la is None or lo is None or v is None:
            continue
        d = _km(lat, lon, la, lo)
        if best is None or d < best[4]:
            best = (name, la, lo, v, d)
    return best


def _psi(hc, lat, lon):
    data = _get(hc, "psi")
    regions = {m["name"]: m.get("labelLocation") or {} for m in data.get("regionMetadata") or []}
    row = _latest(data.get("items") or [])
    if not row or not regions:
        return [], []
    ts = _ts(row.get("timestamp") or row.get("updatedTimestamp"))
    readings_by_key = row.get("readings") or {}
    # Pick the region on the PSI itself, then read every pollutant for that same region.
    best = _nearest_region(regions, readings_by_key.get("psi_twenty_four_hourly") or {}, lat, lon)
    if not best:
        return [], []
    name, rlat, rlon, _, d = best
    sid = "nea-psi"
    out = []
    for key, metric in PSI_METRICS.items():
        v = _num((readings_by_key.get(key) or {}).get(name))
        if v is not None:
            out.append((ts, sid, metric, v))
    return ([_sensor(sid, f"NEA PSI ({name} region)", rlat, rlon, "PT1H", region=name, distance_km=round(d, 1))], out)


# ---------------------------------------------------------------- measured: stations

def _stations(data: dict):
    stations = {s["id"]: s for s in data.get("stations") or [] if s.get("id")}
    latest = _latest(data.get("readings") or [])
    return stations, latest


def _station_feed(hc, feed, metric, sid_prefix, label, lat, lon, cadence):
    """Nearest station that has a value right now. Returns (sensors, readings, stations, latest) so a caller can
    also summarise the whole island from the same response."""
    data = _get(hc, feed)
    stations, latest = _stations(data)
    if not stations or not latest:
        return [], [], stations, latest
    ts = _ts(latest.get("timestamp"))
    best = None
    for pt in latest.get("data") or []:
        st, v = stations.get(pt.get("stationId")), _num(pt.get("value"))
        loc = (st or {}).get("location") or {}
        la, lo = _num(loc.get("latitude")), _num(loc.get("longitude"))
        if st is None or v is None or la is None or lo is None:
            continue
        d = _km(lat, lon, la, lo)
        if best is None or d < best[4]:
            best = (st, la, lo, v, d)
    if not best:
        return [], [], stations, latest
    st, la, lo, v, d = best
    sid = sid_prefix
    return ([_sensor(sid, f"{label} ({st.get('name', st['id'])})", la, lo, cadence,
                     station_id=st["id"], distance_km=round(d, 1))],
            [(ts, sid, metric, v)], stations, latest)


def _rain(hc, lat, lon):
    sensors, readings, stations, latest = _station_feed(
        hc, "rainfall", "rain", "nea-rain", "NEA rainfall", lat, lon, "PT5M")
    # Rain is patchy: the nearest gauge can be dry while a cell sits three kilometres away. So also say how much of
    # the island is wet, from the same response.
    vals = [_num(p.get("value")) for p in (latest or {}).get("data") or []]
    vals = [v for v in vals if v is not None]
    if vals:
        ts = _ts(latest.get("timestamp"))
        sid = "nea-rain-island"
        sensors.append(_sensor(sid, "NEA rainfall (island-wide)", lat, lon, "PT5M", stations=len(vals)))
        readings += [(ts, sid, "rain_max", max(vals)),
                     (ts, sid, "rain_wet_pct", round(100.0 * sum(1 for v in vals if v > 0) / len(vals), 1))]
    return sensors, readings


# ---------------------------------------------------------------- measured: UV

def _uv(hc, lat, lon):
    data = _get(hc, "uv")
    records = data.get("records") or []
    rec = _latest(records)
    if not rec:
        return [], []
    sid = "nea-uv"
    out = []
    for e in rec.get("index") or []:          # today's daylight hours so far; older hours are a free backfill
        v = _num(e.get("value"))
        if v is not None and e.get("hour"):
            out.append((_ts(e["hour"]), sid, "uv", v))
    if not out:                               # night: NEA sends an empty list
        return [], []
    return [_sensor(sid, "NEA UV index (Singapore)", lat, lon, "PT1H")], out


# ---------------------------------------------------------------- measured: heat stress (WBGT), floods

HEAT_LEVEL = {"low": 0.0, "moderate": 1.0, "high": 2.0}


def _records(hc, api: str) -> list[dict]:
    r = hc.get(f"{BASE}/weather", params={"api": api}, timeout=30, **_kw())
    r.raise_for_status()
    return (r.json().get("data") or {}).get("records") or []


def _wbgt(hc, lat, lon):
    rec = _latest(_records(hc, "wbgt"), "datetime")
    readings = ((rec or {}).get("item") or {}).get("readings") or []
    if not rec or not readings:
        return [], []
    ts = _ts(rec.get("datetime"))
    best, vals = None, []
    for rd in readings:
        v = _num(rd.get("wbgt"))
        loc = rd.get("location") or {}
        la, lo = _num(loc.get("latitude")), _num(loc.get("longitude"))
        if v is None:
            continue
        vals.append(v)
        if la is None or lo is None:
            continue
        d = _km(lat, lon, la, lo)
        if best is None or d < best[4]:
            best = (rd, la, lo, v, d)
    sensors, out = [], []
    if best:
        rd, la, lo, v, d = best
        st = rd.get("station") or {}
        sid = "nea-wbgt"
        sensors.append(_sensor(sid, f"NEA heat stress ({st.get('name', st.get('id', 'station'))})", la, lo, "PT15M",
                               station_id=st.get("id"), heat_stress=rd.get("heatStress"), distance_km=round(d, 1)))
        out.append((ts, sid, "wbgt", v))
        lvl = HEAT_LEVEL.get(str(rd.get("heatStress") or "").strip().lower())
        if lvl is not None:
            out.append((ts, sid, "heat_stress_level", lvl))
    if vals:
        sid = "nea-wbgt-island"
        sensors.append(_sensor(sid, "NEA heat stress (island-wide)", lat, lon, "PT15M", stations=len(vals)))
        out.append((ts, sid, "wbgt_max", max(vals)))
    return sensors, out


def _find_point(obj):
    """(lat, lon) from a flood-alert reading, wherever the API puts it. NEA's and PUB's records do not share one
    shape, so look for latitude/longitude at the top level and one level down."""
    if not isinstance(obj, dict):
        return None
    for d in (obj, obj.get("location") if isinstance(obj.get("location"), dict) else {}):
        la = _num(d.get("latitude") if "latitude" in d else d.get("lat"))
        lo = _num(d.get("longitude") if "longitude" in d else d.get("lon", d.get("lng")))
        if la is not None and lo is not None:
            return la, lo
    return None


def _flood(hc, lat, lon):
    rec = _latest(_records(hc, "flood-alerts"), "datetime")
    if not rec:
        return [], []
    readings = ((rec.get("item") or {}).get("readings")) or []
    ts = _ts(rec.get("datetime"))
    sid = "nea-flood"
    out = [(ts, sid, "flood_alerts_active", float(len(readings)))]
    pts = [p for p in (_find_point(r) for r in readings) if p]
    if pts:
        out.append((ts, sid, "flood_nearest_km", round(min(_km(lat, lon, p[0], p[1]) for p in pts), 2)))
    return ([_sensor(sid, "PUB flood alerts (Singapore)", lat, lon, "PT2M", attribution="PUB via data.gov.sg",
                     alerts=readings[:20])], out)


# ---------------------------------------------------------------- measured: dengue clusters

DENGUE_DATASET = "d_dbfabf16158d1b0e1c420627c0819168"
DENGUE_EVERY_S = 6 * 3600
_dengue = {"at": 0.0}


def _ring_contains(ring, lat, lon) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi, xj, yj = ring[i][0], ring[i][1], ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def _rings(geom) -> list:
    """Outer rings of a Polygon or MultiPolygon, as lists of [lon, lat]."""
    t, c = (geom or {}).get("type"), (geom or {}).get("coordinates") or []
    if t == "Polygon":
        return [c[0]] if c else []
    if t == "MultiPolygon":
        return [p[0] for p in c if p]
    return []


def _cluster_facts(props: dict) -> tuple[str | None, float | None]:
    """Locality and case count. NEA puts them in properties, or in an HTML table inside `Description`."""
    text = " ".join(str(v) for v in props.values() if isinstance(v, str))
    loc = props.get("LOCALITY") or props.get("locality")
    m = re.search(r"LOCALITY</th>\s*<td>(.*?)</td>", text, re.I | re.S)
    loc = loc or (m.group(1).strip() if m else None)
    cases = _num(props.get("CASE_SIZE") or props.get("case_size"))
    if cases is None:
        m = re.search(r"CASE_SIZE</th>\s*<td>\s*([\d.]+)", text, re.I | re.S)
        cases = _num(m.group(1)) if m else None
    return loc, cases


def _dengue_feed(hc, lat, lon):
    import time
    if time.time() - _dengue["at"] < DENGUE_EVERY_S:
        return [], []                                        # nothing new to say between refreshes
    r = hc.get(f"https://api-open.data.gov.sg/v1/public/api/datasets/{DENGUE_DATASET}/poll-download", timeout=30, **_kw())
    r.raise_for_status()
    url = ((r.json().get("data") or {}).get("url"))
    if not url:
        return [], []
    g = hc.get(url, timeout=60)
    g.raise_for_status()
    feats = g.json().get("features") or []
    _dengue["at"] = time.time()
    ts = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    inside, nearest, cases_total = False, None, 0.0
    for f in feats:
        loc, cases = _cluster_facts(f.get("properties") or {})
        cases_total += cases or 0.0
        best = float("inf")
        for ring in _rings(f.get("geometry")):
            if _ring_contains(ring, lat, lon):
                inside, best = True, 0.0
                break
            best = min(best, min((_km(lat, lon, p[1], p[0]) for p in ring), default=float("inf")))
        if best < float("inf") and (nearest is None or best < nearest[0]):
            nearest = (best, loc, cases)
    sid = "nea-dengue"
    out = [(ts, sid, "dengue_clusters", float(len(feats))), (ts, sid, "dengue_cases_in_clusters", cases_total),
           (ts, sid, "dengue_in_cluster", 1.0 if inside else 0.0)]
    meta = {"attribution": "NEA via data.gov.sg", "clusters": len(feats)}
    if nearest:
        out.append((ts, sid, "dengue_nearest_km", round(nearest[0], 2)))
        if nearest[2] is not None:
            out.append((ts, sid, "dengue_nearest_cases", nearest[2]))
        meta.update(nearest_locality=nearest[1])
    return [_sensor(sid, "NEA dengue clusters (Singapore)", lat, lon, "P1D", **meta)], out


# ---------------------------------------------------------------- forecasts

def _range(sid, ts, prefix, block, out, key_lo="low", key_hi="high", name=None):
    for k, kk in (("high", key_hi), ("low", key_lo)):
        v = _num((block or {}).get(kk))
        if v is not None:
            out.append((ts, sid, f"{prefix}_{k}", v))


def _fc_2h(hc, lat, lon):
    data = _get(hc, "two-hr-forecast")
    areas = {a["name"]: a.get("label_location") or {} for a in data.get("area_metadata") or [] if a.get("name")}
    items = data.get("items") or []
    item = _latest(items, "timestamp") if items else None
    if not item or not areas:
        return [], []
    fcs = {f["area"]: f.get("forecast") for f in item.get("forecasts") or [] if f.get("area")}
    best = None
    for name, loc in areas.items():
        la, lo = _num(loc.get("latitude")), _num(loc.get("longitude"))
        if la is None or lo is None or name not in fcs:
            continue
        d = _km(lat, lon, la, lo)
        if best is None or d < best[3]:
            best = (name, la, lo, d)
    if not best:
        return [], []
    name, la, lo, d = best
    ts = _ts(item.get("timestamp") or item.get("update_timestamp"))
    vp = item.get("valid_period") or {}
    sid = f"nea-fc2h-{_slug(name)}"
    out = []
    r = _rain_expected(fcs[name])
    if r is not None:
        out.append((ts, sid, "fc_rain_expected", r))
    wet = [_rain_expected(t) for t in fcs.values()]
    wet = [w for w in wet if w is not None]
    if wet:
        out.append((ts, sid, "fc_rain_areas_pct", round(100.0 * sum(wet) / len(wet), 1)))
    return ([_sensor(sid, f"NEA 2-hour forecast ({name})", la, lo, "PT30M", area=name, forecast=fcs[name],
                     valid_from=vp.get("start"), valid_to=vp.get("end"), distance_km=round(d, 1))], out)


def _fc_24h(hc, lat, lon):
    data = _get(hc, "twenty-four-hr-forecast")
    rec = _latest(data.get("records") or [])
    g = (rec or {}).get("general")
    if not g:
        return [], []
    ts = _ts(rec.get("timestamp") or rec.get("updatedTimestamp"))
    sid = "nea-fc24h"
    out: list[tuple] = []
    _range(sid, ts, "fc_temp", g.get("temperature"), out)
    _range(sid, ts, "fc_humidity", g.get("relativeHumidity"), out)
    _range(sid, ts, "fc_wind_speed", (g.get("wind") or {}).get("speed"), out)
    fc = g.get("forecast") or {}
    r = _rain_expected(fc.get("text"))
    if r is not None:
        out.append((ts, sid, "fc_rain_expected", r))
    vp = g.get("validPeriod") or {}
    periods = [{"when": (p.get("timePeriod") or {}).get("text"),
                "regions": {k: (v or {}).get("text") for k, v in (p.get("regions") or {}).items()}}
               for p in rec.get("periods") or []]
    return ([_sensor(sid, "NEA 24-hour forecast (Singapore)", lat, lon, "PT6H", forecast=fc.get("text"),
                     code=fc.get("code"), wind_direction=(g.get("wind") or {}).get("direction"),
                     valid_from=vp.get("start"), valid_to=vp.get("end"), periods=periods)], out)


def _fc_4d(hc, lat, lon):
    data = _get(hc, "four-day-outlook")
    rec = _latest(data.get("records") or [])
    days = (rec or {}).get("forecasts") or []
    if not days:
        return [], []
    ts = _ts(rec.get("timestamp") or rec.get("updatedTimestamp"))
    sid = "nea-fc4d"
    out: list[tuple] = []
    summary = []
    for i, day in enumerate(days[:4], start=1):
        _range(sid, ts, f"fc_d{i}_temp", day.get("temperature"), out)
        _range(sid, ts, f"fc_d{i}_humidity", day.get("relativeHumidity"), out)
        f = day.get("forecast") or {}
        r = _rain_expected(f.get("text"))
        if r is not None:
            out.append((ts, sid, f"fc_d{i}_rain_expected", r))
        summary.append({"day": day.get("day"), "date": day.get("timestamp"), "forecast": f.get("text"),
                        "summary": f.get("summary"), "wind_direction": (day.get("wind") or {}).get("direction")})
    return [_sensor(sid, "NEA 4-day outlook (Singapore)", lat, lon, "PT6H", days=summary)], out


# ---------------------------------------------------------------- entry point

FEEDS = (
    ("pm25", _pm25),
    ("psi", _psi),
    ("air-temperature", lambda hc, la, lo: _one(hc, "air-temperature", "temp", "nea-temp", "NEA air temperature", la, lo, "PT1M")),
    ("relative-humidity", lambda hc, la, lo: _one(hc, "relative-humidity", "humidity", "nea-humidity", "NEA relative humidity", la, lo, "PT1M")),
    ("rainfall", _rain),
    ("wind-speed", lambda hc, la, lo: _one(hc, "wind-speed", "wind_speed", "nea-windspeed", "NEA wind speed", la, lo, "PT1M")),
    ("wind-direction", lambda hc, la, lo: _one(hc, "wind-direction", "wind_dir", "nea-winddir", "NEA wind direction", la, lo, "PT1M")),
    ("uv", _uv),
    ("wbgt", _wbgt),
    ("flood-alerts", _flood),
    ("dengue-clusters", _dengue_feed),
    ("two-hr-forecast", _fc_2h),
    ("twenty-four-hr-forecast", _fc_24h),
    ("four-day-outlook", _fc_4d),
)


def _one(hc, feed, metric, prefix, label, lat, lon, cadence):
    s, r, _, _ = _station_feed(hc, feed, metric, prefix, label, lat, lon, cadence)
    return s, r


# Seconds between requests to each feed. The node polls every POLL_SECONDS (300); fourteen requests every five minutes
# was enough to be answered 429 by data.gov.sg, and most of these move far slower than that. A feed that is not due
# returns nothing, which is right: the readings it produced are already stored.
EVERY = {
    "pm25": 1800, "psi": 3600, "air-temperature": 300, "relative-humidity": 600, "rainfall": 300,
    "wind-speed": 600, "wind-direction": 600, "uv": 1800, "wbgt": 900, "flood-alerts": 300, "dengue-clusters": 300,
    "two-hr-forecast": 1800, "twenty-four-hr-forecast": 10800, "four-day-outlook": 21600,
}
GAP_S = 2.5            # between requests, so a cold start is a trickle and not a burst
MAX_PER_POLL = 4       # feeds requested per poll; the rest wait for the next one (most overdue first)
BACKOFF_S = 900        # after a 429, leave that feed alone this long (or as long as Retry-After says)
_next: dict[str, float] = {}


def _is_429(e: Exception) -> tuple[bool, float]:
    resp = getattr(e, "response", None)
    if getattr(resp, "status_code", None) == 429 or "429" in str(e).split("\n")[0]:
        try:
            return True, float(resp.headers.get("Retry-After"))
        except (AttributeError, TypeError, ValueError):
            return True, 0.0
    return False, 0.0


def fetch(hc):
    lat, lon = float(os.environ["NODE_LAT"]), float(os.environ["NODE_LON"])
    sensors: list[dict] = []
    readings: list[tuple] = []
    failed: list[str] = []
    tried = 0
    now = time.time()
    due = [(n, fn) for n, fn in FEEDS if now >= _next.get(n, 0.0)]
    due.sort(key=lambda x: _next.get(x[0], 0.0))  # never-fetched (0.0) first, then most overdue; stable = FEEDS priority order
    for name, fn in due[:MAX_PER_POLL]:
        if tried:
            time.sleep(GAP_S)
        tried += 1
        try:
            s, r = fn(hc, lat, lon)
        except Exception as e:  # noqa: BLE001 - one feed down must not take the others with it
            limited, wait = _is_429(e)
            if limited:
                _next[name] = time.time() + max(wait, BACKOFF_S)
            failed.append(f"{name}: {str(e).splitlines()[0] if str(e) else type(e).__name__}")
            log.warning("NEA feed %s failed: %s%s", name, str(e).splitlines()[0] if str(e) else type(e).__name__,
                        " (rate limited; backing off)" if limited else "")
            if limited:
                break  # the API is telling us to slow down: stop this poll, the rest wait their turn
            continue
        _next[name] = time.time() + EVERY.get(name, 300)
        log.info("NEA feed %s: %d sensors, %d readings", name, len(s), len(r))
        sensors += s
        readings += r
    if tried and len(failed) == tried:
        raise RuntimeError("every NEA feed failed: " + " | ".join(failed[:3]))
    return sensors, readings

# Metrics this pack writes that tools/check_docs.py cannot see in the code above (names built from prefixes and loops).
PRODUCES = (
    "rain",
    "wind_dir",
    "uv",
    "fc_rain_expected",
    "fc_temp_high",
    "fc_temp_low",
    "fc_humidity_high",
    "fc_humidity_low",
    "fc_wind_speed_high",
    "fc_wind_speed_low",
    "fc_d1_temp_high",
    "fc_d1_temp_low",
    "fc_d1_humidity_high",
    "fc_d1_humidity_low",
    "fc_d1_rain_expected",
    "fc_d2_temp_high",
    "fc_d2_temp_low",
    "fc_d2_humidity_high",
    "fc_d2_humidity_low",
    "fc_d2_rain_expected",
    "fc_d3_temp_high",
    "fc_d3_temp_low",
    "fc_d3_humidity_high",
    "fc_d3_humidity_low",
    "fc_d3_rain_expected",
    "fc_d4_temp_high",
    "fc_d4_temp_low",
    "fc_d4_humidity_high",
    "fc_d4_humidity_low",
    "fc_d4_rain_expected",
    "wbgt",
    "heat_stress_level",
    "dengue_cases_in_clusters",
    "dengue_in_cluster",
    "dengue_nearest_cases",
)
