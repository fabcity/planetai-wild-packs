"""digital-subak against API-shaped answers. The values are made up: Digital Subak's data is used on the node only,
so none of it is copied into this public repository. Field names are the API's as of 25 Nov 2026 (OpenAPI 2.0.0).

Run from a node's folder: python3 packs/digital-subak/tests/test_digital_subak.py
"""
import importlib.util
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("digital_subak_adapter", HERE.parent / "adapter.py")
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)

LATEST = {"temp_c": 28.0, "humidity_pct": 80.0, "dew_point_c": 24.0, "feels_like_c": 33.0, "pressure_rel_hpa": 1008.0,
          "pressure_abs_hpa": 1006.0, "wind_speed_ms": 2.0, "wind_gust_ms": 5.0, "wind_dir_deg": 200.0,
          "rain_rate_mmh": 0.0, "rain_daily_mm": 3.0, "rain_interval_mm": 0.0, "solar_wm2": 500.0, "uv_index": 5.0}


def station(code, provider, **kw):
    return {"code": code, "name": code.title(), "provider": provider, "latitude": -8.6, "longitude": 115.1,
            "elevation_m": 20.0, "url": f"/s/{code}", "model": "GW1200A", "active": True, "planned": False,
            "duplicate_of": None, "last_seen": "2026-11-25T03:55:00Z", "latest": dict(LATEST), "latest_flags": [],
            "rain_1h_mm": 1.5, "rain_24h_mm": 12.0, **kw}


STATIONS = [
    station("kedungu", "ecowitt", latest_flags=["stuck_pressure_rel_hpa"]),
    station("sarinbuana", "ecowitt", last_seen=None),
    station("ibadun12", "wunderground"),                                  # IBM's, never ours
    station("itaban14", "wunderground", duplicate_of="kedungu"),          # his station again, through WU
    station("copy", "ecowitt", duplicate_of="kedungu"),
    station("sumberkima", "push"),                                       # not named as his: left out for now
    station("later", "ecowitt", planned=True),
    station("off", "ecowitt", active=False),
]

# only his Ecowitt stations, once each
assert [s["code"] for s in A.own(STATIONS)] == ["kedungu", "sarinbuana"], A.own(STATIONS)

sensors, readings = A.station_rows(STATIONS)
assert [s["sensor_id"] for s in sensors] == ["dsubak-kedungu", "dsubak-sarinbuana"]
k = sensors[0]
# someone else's station: kept out of the house's medians, shown as itself
assert (k["kind"], k["scale"], k["local"], k["indoor"]) == ("portal", "region", False, False), k
assert k["meta"]["attribution"] == "Data: Digital Subak (digitalsubak.id)"
assert k["meta"]["url"] == "https://digitalsubak.id/s/kedungu"

got = {(sid, m): v for _, sid, m, v in readings}
ts = {t for t, *_ in readings}
assert ts == {datetime(2026, 11, 25, 3, 55, tzinfo=timezone.utc)}, ts
# the node's units: kPa, km/h
assert got[("dsubak-kedungu", "temp")] == 28.0
assert got[("dsubak-kedungu", "wind_speed")] == 7.2 and got[("dsubak-kedungu", "wind_gust")] == 18.0
assert got[("dsubak-kedungu", "rainfall_1h")] == 1.5 and got[("dsubak-kedungu", "rainfall_24h")] == 12.0
# a flagged value is not stored; the others are
assert ("dsubak-kedungu", "pressure") not in got
assert got[("dsubak-kedungu", "uv")] == 5.0
# a station with no last_seen keeps its sensor row and gives no readings
assert not any(sid == "dsubak-sarinbuana" for _, sid, _, _ in readings)
assert not any(sid.startswith("dsubak-ibadun") or sid.startswith("dsubak-itaban") for _, sid, _, _ in readings)

# pressure goes to kPa when it is not flagged
_, r2 = A.station_rows([station("kedungu", "ecowitt")])
assert {m: v for _, _, m, v in r2}["pressure"] == 100.8

DAILY = {"stations": {"kedungu": {
    "days": [{"date": "2026-11-24", "rain_total_mm": 16.0, "et0_mm": 2.7, "completeness_pct": 100.0},
             {"date": "2026-11-25", "rain_total_mm": 0.0, "et0_mm": None, "completeness_pct": 50.0}],
    "water_balance": {"rain_mm": 100.0, "et0_mm": 20.0, "balance_mm": 80.0, "status": "surplus", "days": 6}}}}
now = datetime(2026, 11, 25, 4, 17, 9, tzinfo=timezone.utc)
d = {(t, sid, m): v for t, sid, m, v in A.daily_rows(DAILY, now)}
end_24 = datetime(2026, 11, 24, 16, 0, tzinfo=timezone.utc)     # midnight 25 Nov in Bali (WITA, UTC+8)
assert d == {(end_24, "dsubak-kedungu", "et0"): 2.7, (end_24, "dsubak-kedungu", "rainfall_day"): 16.0,
             (datetime(2026, 11, 25, 4, tzinfo=timezone.utc), "dsubak-kedungu", "water_balance_7d"): 80.0}, d


# fetch: one call to each endpoint, then nothing until they are due again; a failure is retried later, not next poll
class Resp:
    def __init__(self, body, status=200):
        self.body, self.status = body, status

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    def json(self):
        return self.body


class HC:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(url.rsplit("/", 1)[1])
        assert "planetai-node" in headers["user-agent"]
        if self.fail:
            return Resp({}, 503)
        return Resp(STATIONS if url.endswith("/stations") else DAILY)


with tempfile.TemporaryDirectory() as out:
    os.environ["PACK_OUT"] = out
    hc = HC()
    s, r = A.fetch(hc)
    assert hc.calls == ["stations", "daily"], hc.calls
    assert len(s) == 2 and any(m == "water_balance_7d" for _, _, m, _ in r)
    assert A.fetch(hc) == ([], []) and hc.calls == ["stations", "daily"], hc.calls

with tempfile.TemporaryDirectory() as out:
    os.environ["PACK_OUT"] = out
    hc = HC(fail=True)
    assert A.fetch(hc) == ([], [])
    assert A.fetch(hc) == ([], []) and hc.calls == ["stations"], hc.calls

print("digital-subak: ok")
