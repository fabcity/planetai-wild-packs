"""NEA's weekly beach water quality banding, for the beaches this node follows.

NEA samples seven popular beaches every week and publishes an Enterococcus banding per stretch of beach:
Band 1 Normal (EC <= 200), Band 2 Elevated (200 < EC <= 500), Band 3 High (EC > 500, or two weeks running at
200-500). Laboratory results take about a week, so the banding is for the week BEFORE it is published.

There is no data.gov.sg dataset for this. The numbers come from the JSON that NEA's own page
(nea.gov.sg/beach-water-quality) loads: /api/BeachWaterQuality/GetNeaData/<t>. NEA's data is reusable under the
Singapore Open Data Licence v1.0 (attribution, no implied endorsement), but this endpoint is NOT a documented API and
can change or start refusing automated callers. When it does, the pack logs one clear line and reports nothing rather
than a stale number dressed as a fresh one.

Two facts about the endpoint, read off a live response:
  * <t> is a Unix time rounded DOWN to a five-minute boundary; any other value is answered 400.
  * the answer holds `areas` (polygons), `data` (the last three weeks, one entry per stretch) and advisory text.

One sensor per followed beach (BEACH_AREAS, default "East Coast,Changi"), kind='model', local=False, scale='city':
  beach_band                worst band across the beach's stretches (1-3)
  beach_band_nearest        band of the stretch nearest this node
  beach_stretches_elevated  how many stretches are Band 2 or 3
  beach_advisory            1 when NEA has flagged a bacteria advisory on the map for any stretch
Contract: fetch(hc) -> (sensors, readings), like everything in app/sources.py.
"""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from math import asin, cos, radians, sin, sqrt

log = logging.getLogger("planetai.pack.singapore_beach")

URL = "https://www.nea.gov.sg/api/BeachWaterQuality/GetNeaData/{t}"
SOURCE = "singapore-beach"
ATTRIBUTION = "NEA (Beach Short-Term Water Quality Information), Singapore Open Data Licence v1.0"
EVERY_S = 6 * 3600          # a weekly banding: four looks a day is more than enough
SGT = timezone(timedelta(hours=8))
_state = {"at": 0.0}


def _km(lat1, lon1, lat2, lon2) -> float:
    p1, p2, dl = radians(lat1), radians(lat2), radians(lon2 - lon1)
    return 6371 * 2 * asin(sqrt(sin((p2 - p1) / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2))


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _band(v):
    try:
        b = int(str(v).strip())
    except (TypeError, ValueError):
        return None
    return b if b in (1, 2, 3) else None


def _week_end(label: str) -> datetime | None:
    """'14/09/2026 - 20/09/2026' -> the end of that Sunday, Singapore time, as UTC."""
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})\s*$", label or "")
    if not m:
        return None
    d, mo, y = map(int, m.groups())
    try:
        return datetime(y, mo, d, 23, 59, tzinfo=SGT).astimezone(timezone.utc)
    except ValueError:
        return None


def _centroids(areas: list[dict]) -> dict[str, tuple[float, float]]:
    out = {}
    for a in areas or []:
        pts = [(float(p["Lat"]), float(p["Lng"])) for p in a.get("Points") or []
               if p.get("Lat") not in (None, "") and p.get("Lng") not in (None, "")]
        if pts:
            out[a.get("Area", "")] = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
    return out


def parse(doc: dict, beaches: list[str], lat: float, lon: float):
    """(sensors, readings) for the newest published week; empty when the response has nothing usable."""
    weeks = [(w, _week_end(w.get("Week"))) for w in doc.get("data") or []]
    weeks = [(w, e) for w, e in weeks if e is not None and w.get("Areas")]
    if not weeks:
        return [], []
    week, ts = max(weeks, key=lambda x: x[1])
    centres = _centroids(doc.get("areas") or [])
    sensors, readings = [], []
    for beach in beaches:
        stretches = []
        for a in week["Areas"]:
            name = a.get("Area") or ""
            b = _band(a.get("Banding"))
            if b is None or not name.lower().startswith(beach.lower()):
                continue
            c = centres.get(name)
            stretches.append({"name": name, "band": b, "desc": re.sub(r"&ndash;", "-", a.get("Description") or ""),
                              "advisory": bool(a.get("AdvisoryOnMap")), "centre": c,
                              "km": _km(lat, lon, *c) if c else 1e9})
        if not stretches:
            continue
        near = min(stretches, key=lambda s: s["km"])
        sid = f"nea-beach-{_slug(beach)}"
        c = near["centre"] or (lat, lon)
        sensors.append({
            "sensor_id": sid, "source": SOURCE, "name": f"NEA beach water quality ({beach})", "lat": c[0], "lon": c[1],
            "indoor": False, "local": False, "kind": "model", "scale": "city", "cadence": "P7D",
            "meta": {"attribution": ATTRIBUTION, "beach": beach, "week": week.get("Week"),
                     "stretches_total": len(stretches), "nearest_stretch": near["name"],
                     "nearest_description": near["desc"],
                     "nearest_km": round(near["km"], 1) if near["km"] < 1e8 else None,
                     "stretches": {s["name"]: s["band"] for s in stretches}}})
        readings += [(ts, sid, "beach_band", float(max(s["band"] for s in stretches))),
                     (ts, sid, "beach_band_nearest", float(near["band"])),
                     (ts, sid, "beach_stretches_elevated", float(sum(1 for s in stretches if s["band"] >= 2))),
                     (ts, sid, "beach_advisory", 1.0 if any(s["advisory"] for s in stretches) else 0.0)]
    return sensors, readings


def _get(hc) -> dict:
    t = int(time.time() // 300 * 300)            # NEA answers 400 to anything not on a five-minute boundary
    r = hc.get(URL.format(t=t), timeout=30,
               headers={"User-Agent": "planetai-node/singapore-beach (open-data reuse)", "Accept": "application/json"})
    r.raise_for_status()
    return r.json()


def fetch(hc):
    if time.time() - _state["at"] < EVERY_S:
        return [], []
    lat, lon = float(os.environ["NODE_LAT"]), float(os.environ["NODE_LON"])
    beaches = [b.strip() for b in (os.getenv("BEACH_AREAS") or "East Coast,Changi").split(",") if b.strip()]
    try:
        doc = _get(hc)
    except Exception as e:  # noqa: BLE001
        _state["at"] = time.time() - EVERY_S + 1800     # try again in half an hour, not at once
        log.warning("singapore-beach: NEA beach feed failed (%s). The endpoint is undocumented and may have changed.",
                    str(e).splitlines()[0] if str(e) else type(e).__name__)
        raise RuntimeError("NEA beach feed failed") from e
    sensors, readings = parse(doc, beaches, lat, lon)
    _state["at"] = time.time()
    if not sensors:
        log.warning("singapore-beach: the NEA response had no stretch matching %s", beaches)
    return sensors, readings

# Metrics this pack writes that tools/check_docs.py cannot see in the code above (names built from prefixes and loops).
PRODUCES = (
    "beach_advisory",
)
