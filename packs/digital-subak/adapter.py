"""Digital Subak's own weather stations in Bali, from its key-free API (digitalsubak.id/developers).

Digital Subak is Radek Oborny's network. Of the stations its API lists, only the Ecowitt units are his: Kedungu,
Sarinbuana and Island Organics, hosted by partners. The rest are Weather Underground stations it fetches hourly, and
those belong to IBM, so this pack never reads them, and never a station marked `duplicate_of` one of his.

Radek agreed on 25 Nov 2026 that a node may use his stations. Nothing was said about passing the data on, so every
channel is `private` (channels.yml): the node's page, readouts and sections use it, and the daily export, a parent's
aggregates, the report bundle and agents never see it.

Two calls, each throttled by a stamp file in PACK_OUT, because the node re-imports this module on every poll:
/api/stations every 5 minutes (its stations publish every 5; the API asks for no more), and /api/daily every hour,
for yesterday's ET0 and the 7-day water balance. The API allows 60 calls a minute.

A station tens of kilometres away is not the house's weather. Its sensors are `kind: portal`, `scale: region`, so
they stay out of the room, yard and ring medians and show as themselves (see packs/bmkg-synop).
"""
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("planetai.pack.digital-subak")

API = "https://digitalsubak.id/api"
SOURCE = "digital-subak"
PREFIX = "dsubak-"
UA = {"user-agent": "planetai-node/digital-subak (+https://planetai.fab.city)"}
WITA = timezone(timedelta(hours=8))
EVERY = {"stations": 300, "daily": 3600}
RETRY_S = 900
ATTRIBUTION = "Data: Digital Subak (digitalsubak.id)"
LICENCE = "Radek Oborny's permission to use on the node, 25 Nov 2026; not for export"

# API field -> (node metric, factor). Pressure goes to kPa and wind to km/h, as bmkg-synop and the node's own sensors.
LATEST = {"temp_c": ("temp", 1), "humidity_pct": ("humidity", 1), "dew_point_c": ("dewpoint", 1),
          "pressure_rel_hpa": ("pressure", 0.1), "wind_speed_ms": ("wind_speed", 3.6),
          "wind_gust_ms": ("wind_gust", 3.6), "wind_dir_deg": ("wind_direction", 1),
          "solar_wm2": ("solar", 1), "uv_index": ("uv", 1)}
RAIN = {"rain_1h_mm": "rainfall_1h", "rain_24h_mm": "rainfall_24h"}


def own(stations: list) -> list:
    """Radek's stations: his Ecowitt units, active, not a copy of another row. Never Weather Underground's."""
    # ponytail: provider == "ecowitt" is the whole test. The one `push` station (Sumber Kima) is not named as his on
    # the site; add it once he says it is.
    return [s for s in stations if s.get("provider") == "ecowitt" and s.get("active", True)
            and not s.get("planned") and not s.get("duplicate_of") and s.get("code")]


def station_rows(stations: list):
    """(sensors, readings) from /api/stations. One reading per metric, at the station's last_seen."""
    sensors, readings = [], []
    for s in own(stations):
        sid = PREFIX + s["code"]
        sensors.append({
            "sensor_id": sid, "source": SOURCE, "name": f"Digital Subak {s.get('name') or s['code']}",
            "lat": s.get("latitude"), "lon": s.get("longitude"), "indoor": False, "local": False,
            "kind": "portal", "scale": "region", "cadence": "PT5M",
            "meta": {"station": s["code"], "network": "Digital Subak", "model": s.get("model"),
                     "elevation_m": s.get("elevation_m"), "url": f"https://digitalsubak.id{s.get('url') or ''}",
                     "flags": s.get("latest_flags") or [], "licence": LICENCE, "attribution": ATTRIBUTION},
        })
        if not s.get("last_seen"):
            continue
        ts = datetime.fromisoformat(s["last_seen"].replace("Z", "+00:00"))
        flagged = {f.split("_", 1)[1] for f in s.get("latest_flags") or [] if "_" in f}   # "stuck_temp_c" -> "temp_c"
        latest = s.get("latest") or {}
        for field, (metric, k) in LATEST.items():
            v = latest.get(field)
            if v is not None and field not in flagged:
                readings.append((ts, sid, metric, round(v * k, 3)))
        for field, metric in RAIN.items():
            if s.get(field) is not None:
                readings.append((ts, sid, metric, float(s[field])))
    return sensors, readings


def daily_rows(body: dict, now: datetime):
    """Readings from /api/daily: each complete day's ET0 and rain, stamped at the end of that day in Bali, and the
    7-day water balance (rain minus ET0) stamped at the hour it was read."""
    out = []
    hour = now.replace(minute=0, second=0, microsecond=0)
    for code, st in (body.get("stations") or {}).items():
        sid = PREFIX + code
        for d in st.get("days") or []:
            if (d.get("completeness_pct") or 0) < 90 or d.get("et0_mm") is None:
                continue
            end = datetime.fromisoformat(d["date"]).replace(tzinfo=WITA) + timedelta(days=1)
            out.append((end.astimezone(timezone.utc), sid, "et0", float(d["et0_mm"])))
            if d.get("rain_total_mm") is not None:
                out.append((end.astimezone(timezone.utc), sid, "rainfall_day", float(d["rain_total_mm"])))
        wb = st.get("water_balance") or {}
        if wb.get("balance_mm") is not None:
            out.append((hour, sid, "water_balance_7d", float(wb["balance_mm"])))
    return out


def _stamp(name: str) -> Path:
    return Path(os.getenv("PACK_OUT", "/app/out")) / f"digital-subak.{name}.last"


def _due(name: str) -> bool:
    f = _stamp(name)
    return not f.is_file() or time.time() >= f.stat().st_mtime


def _next(name: str, seconds: float) -> None:
    """The stamp's mtime is when the call is next due."""
    f = _stamp(name)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.touch()
    t = time.time() + seconds
    os.utime(f, (t, t))


def _get(hc, name: str, path: str, params: dict):
    """One throttled call. Stamped before asking, so a slow or failing API is asked again after RETRY_S, not next poll.
    A failure logs and returns None: someone else's API being down is never an alert."""
    if not _due(name):
        return None
    _next(name, RETRY_S)
    try:
        r = hc.get(f"{API}{path}", params=params, headers=UA, timeout=20)
        r.raise_for_status()
        body = r.json()
    except Exception as e:  # noqa: BLE001
        log.warning("digital-subak: %s failed (%s: %s)", path, type(e).__name__, e)
        return None
    _next(name, EVERY[name])
    return body


def fetch(hc):
    """Contract: (sensors, readings)."""
    sensors, readings = [], []
    stations = _get(hc, "stations", "/stations", {})
    if stations:
        sensors, readings = station_rows(stations)
        codes = ",".join(s["code"] for s in own(stations))
        if codes:
            daily = _get(hc, "daily", "/daily", {"station": codes, "days": 3})
            if daily:
                readings += daily_rows(daily, datetime.now(timezone.utc))
    return sensors, readings
