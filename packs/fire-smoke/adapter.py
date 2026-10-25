"""Satellite fire detections near the node, from NASA FIRMS.

Counts hotspots seen in the last 24 hours within FIRE_RADIUS_KM, in total and by the compass sector they lie in as
seen FROM the node (n, ne, e, ...). The sector split is what makes them useful: a rule can then ask how many fires
lie in the direction the wind is coming from. The pack states where the fires are. It does not say the haze will
arrive: smoke travels on winds at altitude, over hours to days, and a hotspot is not a plume.

kind='model', scale='city', never a `live` cell: this is somebody else's satellite, not something measured here.
Contract: fetch(hc) -> (sensors, readings), like everything in app/sources.py.

The MAP_KEY is a credential and it rides in the URL path. So no message this file raises or logs may contain the URL:
httpx puts it in the text of its errors, and `_get` strips it. Read the exception, never print the request.

FIRMS's limit is 5000 transactions in 10 minutes. This asks two, every three hours.
"""
from __future__ import annotations

import csv
import io
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from math import asin, atan2, cos, degrees, radians, sin, sqrt

log = logging.getLogger("planetai.pack.fire_smoke")

API = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
SOURCE = "nasa-firms"
SENSOR = "firms-hotspots"
EVERY_S = 3 * 3600          # FIRMS near-real-time data refreshes roughly every three hours
# FIRMS's last path segment is a number of UTC calendar DAYS, not hours: "1" returns only today's date (UTC), so a
# rolling "last 24 h" fell to zero at 00:00 UTC (08:00 in Singapore) and rebuilt through the day. Three days reaches
# back over the 48 hours the count and the change against the day before both need.
DAY_RANGE = 3
SECTORS = ("n", "ne", "e", "se", "s", "sw", "w", "nw")
_state = {"at": 0.0, "warned": False}


def _km(lat1, lon1, lat2, lon2) -> float:
    p1, p2, dl = radians(lat1), radians(lat2), radians(lon2 - lon1)
    return 6371 * 2 * asin(sqrt(sin((p2 - p1) / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2))


def _bearing(lat1, lon1, lat2, lon2) -> float:
    """Compass bearing from point 1 to point 2, 0-360, north = 0."""
    p1, p2, dl = radians(lat1), radians(lat2), radians(lon2 - lon1)
    y = sin(dl) * cos(p2)
    x = cos(p1) * sin(p2) - sin(p1) * cos(p2) * cos(dl)
    return (degrees(atan2(y, x)) + 360) % 360


def sector(bearing: float) -> str:
    return SECTORS[int(round(bearing / 45.0)) % 8]


def _bbox(lat: float, lon: float, radius_km: float) -> str:
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(cos(radians(lat)), 0.01))
    return f"{lon - dlon:.3f},{lat - dlat:.3f},{lon + dlon:.3f},{lat + dlat:.3f}"


def _get(hc, key: str, src: str, area: str) -> str:
    """One FIRMS request. Raises with the key removed from anything it says."""
    try:
        r = hc.get(f"{API}/{key}/{src}/{area}/{DAY_RANGE}", timeout=60)
        r.raise_for_status()
        return r.text
    except Exception as e:  # noqa: BLE001
        status = getattr(getattr(e, "response", None), "status_code", None)
        raise RuntimeError(f"FIRMS {src} request failed ({type(e).__name__}"
                           + (f", HTTP {status}" if status else "") + ")") from None


def parse(text: str, lat: float, lon: float, radius_km: float, now: datetime, hours: float = 24) -> list[dict]:
    """Hotspots from the last `hours` (24 unless asked for more), within radius, not low-confidence. Columns are read by name: FIRMS's column set
    differs by instrument and has grown before."""
    if "latitude" not in text[:400]:
        raise RuntimeError("FIRMS answered something that is not a fire table: " + text.strip()[:60].replace("\n", " "))
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            la, lo = float(row["latitude"]), float(row["longitude"])
            t = str(row.get("acq_time") or "0").zfill(4)
            when = datetime.strptime(f"{row['acq_date']} {t}", "%Y-%m-%d %H%M").replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        if now - when > timedelta(hours=hours) or when > now + timedelta(hours=1):
            continue
        conf = str(row.get("confidence") or "").strip().lower()
        if conf == "l" or (conf.isdigit() and int(conf) < 30):      # VIIRS: l/n/h. MODIS: 0-100.
            continue
        d = _km(lat, lon, la, lo)
        if d > radius_km:
            continue
        try:
            frp = float(row.get("frp") or 0)
        except ValueError:
            frp = 0.0
        out.append({"km": d, "sector": sector(_bearing(lat, lon, la, lo)), "frp": frp,
                    "age_h": max(0.0, (now - when).total_seconds() / 3600)})
    return out


def summarise(spots: list[dict], ts: datetime) -> list[tuple]:
    """The last 24 h in every metric but one: `fires_prev_24h` counts the day before that (24 to 48 h ago), so a
    reader has the change without needing yesterday's own reading, which the count above does not preserve."""
    prev = float(sum(1 for s in spots if 24 < s.get("age_h", 0) <= 48))
    spots = [s for s in spots if s.get("age_h", 0) <= 24]
    out = [(ts, SENSOR, "fires_24h", float(len(spots))), (ts, SENSOR, "fires_prev_24h", prev),
           (ts, SENSOR, "fires_250km_24h", float(sum(1 for s in spots if s["km"] <= 250))),
           (ts, SENSOR, "fires_frp_mw_24h", round(sum(s["frp"] for s in spots), 1))]
    for name in SECTORS:
        out.append((ts, SENSOR, f"fires_{name}", float(sum(1 for s in spots if s["sector"] == name))))
    if spots:
        out.append((ts, SENSOR, "fires_nearest_km", round(min(s["km"] for s in spots), 1)))
    return out


def fetch(hc):
    key = os.getenv("FIRMS_MAP_KEY", "").strip()
    if not key:
        if not _state["warned"]:
            log.warning("fire-smoke: FIRMS_MAP_KEY is empty — the pack is idle (free key: firms.modaps.eosdis.nasa.gov/api/map_key)")
            _state["warned"] = True
        return [], []
    if time.time() - _state["at"] < EVERY_S:
        return [], []
    lat, lon = float(os.environ["NODE_LAT"]), float(os.environ["NODE_LON"])
    radius = float(os.getenv("FIRE_RADIUS_KM", "500") or 500)
    area = _bbox(lat, lon, radius)
    now = datetime.now(timezone.utc)
    spots: list[dict] = []
    sources = [s.strip() for s in (os.getenv("FIRE_SOURCES") or "VIIRS_SNPP_NRT,VIIRS_NOAA20_NRT").split(",") if s.strip()]
    failed = []
    for src in sources:
        try:
            spots += parse(_get(hc, key, src, area), lat, lon, radius, now, hours=48)
        except Exception as e:  # noqa: BLE001 - one satellite down must not blank the other
            failed.append(str(e))
            log.warning("fire-smoke: %s", e)
    if failed and len(failed) == len(sources):
        raise RuntimeError(failed[0])
    _state["at"] = time.time()
    ts = now.replace(minute=0, second=0, microsecond=0)
    sensor = {"sensor_id": SENSOR, "source": SOURCE, "name": f"Fires within {radius:.0f} km (NASA FIRMS, 24 h)",
              "lat": lat, "lon": lon, "indoor": False, "local": False, "kind": "model", "scale": "city",
              "cadence": "PT3H", "meta": {"attribution": "NASA FIRMS / LANCE, VIIRS 375 m", "radius_km": radius,
                                          "sources": sources, "sources_failed": len(failed)}}
    return [sensor], summarise(spots, ts)

# Metrics this pack writes that tools/check_docs.py cannot see in the code above (names built from prefixes and loops).
PRODUCES = (
    "fires_prev_24h",
    "fires_n",
    "fires_ne",
    "fires_e",
    "fires_se",
    "fires_s",
    "fires_sw",
    "fires_w",
    "fires_nw",
)
