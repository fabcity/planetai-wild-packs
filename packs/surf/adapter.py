"""Tomorrow's and the day after's surf at the spots in SURF_SPOTS, judged by surf.py from three Open-Meteo calls: GFS
Wave swell, the default marine model's sea level (the tide), and the forecast API's wind. At most one fetch every three
hours.

The node re-imports this file on every poll, so nothing survives in the module: the three-hour gate is a stamp file
in PACK_OUT, touched before the first call, so a 429 waits three hours too (packs/forecast does the same; on 13 Oct
the forecast pack spent the whole IP's free tier by mid-morning by asking every poll). Rows are stamped at the fetch,
not at tomorrow: readings are ON CONFLICT DO NOTHING, and a row at a fixed future time would keep the day's first
forecast forever. The whole two-day message, in en, es and id, and its keyboard go into the meta of one summary
sensor, `surf`, which the node replaces on every poll; rules.yml only reads it.

Contract: fetch(hc) -> (sensors, readings), like everything in app/sources.py.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import surf as S  # noqa: E402

log = logging.getLogger("planetai.surf")

MARINE = "https://marine-api.open-meteo.com/v1/marine"
WEATHER = "https://api.open-meteo.com/v1/forecast"
SWELL_VARS = ("swell_wave_height,swell_wave_period,swell_wave_direction,secondary_swell_wave_height,"
              "secondary_swell_wave_period,secondary_swell_wave_direction,wind_wave_height")
EVERY_S = 3 * 3600
ATTRIBUTION = "Weather and marine data by Open-Meteo.com (CC BY 4.0); NOAA GFS Wave; Copernicus Marine / MeteoFrance"
TIDE_CODE = {"low": 0, "mid": 1, "high": 2}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _due() -> bool:
    stamp = Path(os.getenv("PACK_OUT", "/app/out")) / "surf.stamp"
    if stamp.is_file() and time.time() - stamp.stat().st_mtime < EVERY_S:
        return False
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.touch()
    return True


def _get(hc, url: str, params: dict) -> list[dict]:
    r = hc.get(url, params=params, timeout=30)
    r.raise_for_status()
    d = r.json()
    return d if isinstance(d, list) else [d]          # one location comes back as an object


def _setting(name: str, cast, default):
    raw = os.getenv(name, "")
    if not raw.strip():
        return default
    try:
        return cast(raw)
    except ValueError:
        log.warning("surf: %s=%r is not a number; using %s", name, raw, default)
        return default


def fetch(hc):
    wanted = [s.strip() for s in os.getenv("SURF_SPOTS", "").split(",") if s.strip()]
    if not wanted:
        return [], []
    if not _due():
        return [], []
    spots = S.load_spots(Path(_HERE) / "spots.yml")
    for sid in [s for s in wanted if s not in spots]:
        log.warning("surf: %s is not in spots.yml; skipped", sid)      # once a fetch, not once a poll
    watch = [spots[s] for s in wanted if s in spots]
    if not watch:
        return [], []
    base = {"latitude": ",".join(str(s["lat"]) for s in watch), "longitude": ",".join(str(s["lon"]) for s in watch),
            "timezone": "auto", "forecast_days": 3}
    swell = _get(hc, MARINE, {**base, "hourly": SWELL_VARS, "models": "ncep_gfswave016"})
    tide = _get(hc, MARINE, {**base, "hourly": "sea_level_height_msl"})
    wind = _get(hc, WEATHER, {**base, "hourly": "wind_speed_10m,wind_direction_10m,wind_gusts_10m"})
    now = _now()
    local = (now + timedelta(seconds=swell[0].get("utc_offset_seconds", 0))).date()
    today, d1, d2 = local.isoformat(), (local + timedelta(days=1)).isoformat(), (local + timedelta(days=2)).isoformat()
    minp = float(os.getenv("SURF_MIN_PERIOD", "10") or 10)
    hours = os.getenv("SURF_HOURS", "")
    if hours.strip():
        try:
            S._hours(hours)
        except (AttributeError, ValueError):
            log.warning("surf: SURF_HOURS=%r gives no hours; using %s", hours, S.DEFAULT_HOURS)
    session_h = _setting("SURF_SESSION_H", int, 2)
    comfort = _setting("SURF_COMFORT_KW", float, 15)
    sensors, readings, days = [], [], ([], [])
    for sp, sw, td, wd in zip(watch, swell, tide, wind):
        sid = f"surf-{sp['id']}"
        sensors.append({"sensor_id": sid, "source": "surf", "name": sp["name"], "lat": sp["lat"], "lon": sp["lon"],
                        "indoor": False, "local": False, "kind": "model", "scale": "bioregion", "cadence": "PT3H",
                        "meta": {"attribution": ATTRIBUTION, "dates": [d1, d2]}})
        for n, (day, suffix) in enumerate(((d1, ""), (d2, "_d2"))):
            a = S.assess(sp, S.day_rows(sw, td, wd, day), minp, hours or None, session_h)
            days[n].append((sp, a))
            s, x = a["swell"] or {}, a["second"] or {}
            f, t = a["window"] or (None, None)
            values = {"surf_good": 1 if a["good"] else 0, "surf_kw": round(a["kw"], 2), "surf_from_h": f, "surf_to_h": t,
                      "surf_swell_m": s.get("h"), "surf_period_s": s.get("t"), "surf_swell_dir": s.get("dir"),
                      "surf_mixed": (1 if a["second"] else 0) if a["good"] else None,
                      "surf_swell2_m": x.get("h"), "surf_period2_s": x.get("t"), "surf_swell2_dir": x.get("dir"),
                      "surf_wind_kmh": a["wind"], "surf_wind_dir": a["wdir"], "surf_tide": TIDE_CODE.get(a["tide"])}
            readings += [(now, sid, m + suffix, float(v)) for m, v in values.items() if v is not None]
    picked = [S.pick(d) for d in days]
    buttons = S.keyboard([sp for sp, _ in picked[0]])
    text = {loc: S.message([(d1, picked[0]), (d2, picked[1])], loc, comfort, bool(picked[0])) for loc in ("en", "es", "id")}
    first = watch[0]       # the pack has no position of its own, so the summary sits at the first watched spot
    sensors.append({"sensor_id": "surf", "source": "surf", "name": "Surf", "lat": first["lat"], "lon": first["lon"],
                    "indoor": False, "local": False, "kind": "model", "scale": "bioregion", "cadence": "PT3H",
                    "meta": {"attribution": ATTRIBUTION, "fetched": today, "any": "1" if any(picked) else "0",
                             **{f"text_{loc}": t for loc, t in text.items()}, "buttons": json.dumps(buttons)}})
    readings.append((now, "surf", "surf_spots_good", float(sum(a["good"] for d in days for _, a in d))))
    return sensors, readings
