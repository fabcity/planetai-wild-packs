"""The singapore-nea pack, offline: no data.gov.sg, no database.

The payloads below have the shape of the live v2 responses as read on 29 September 2026; the VALUES are made up. Before
this merges, replace them with a capture of each real response:
    curl -s https://api-open.data.gov.sg/v2/real-time/api/rainfall > tests/data/singapore-nea/rainfall.json
(and the same for the other feeds), and load those instead. A test written from the shape alone proves the parsing
handles the shape, and nothing about what NEA sends on a bad day.
Run: python3 packs/singapore-nea/tests/test_singapore_nea.py
"""
import importlib.util
import os
import time

os.environ.update(NODE_LAT="1.317", NODE_LON="103.885")
spec = importlib.util.spec_from_file_location("neapack", "packs/singapore-nea/adapter.py")
A = importlib.util.module_from_spec(spec); spec.loader.exec_module(A)
A.GAP_S = 0
A.MAX_PER_POLL = 99

T = "2026-09-29T22:50:00+08:00"


def station(i, n, la, lo):
    return {"id": i, "deviceId": i, "name": n, "location": {"latitude": la, "longitude": lo}}


STN = [station("S109", "Ang Mo Kio Ave 5", 1.3764, 103.8492), station("S107", "East Coast Parkway", 1.3135, 103.9625)]


def by_station(vals):
    return {"stations": STN, "readings": [{"timestamp": T, "data": [{"stationId": k, "value": v} for k, v in vals.items()]}]}


REGIONS = [{"name": n, "labelLocation": {"latitude": la, "longitude": lo}}
           for n, la, lo in (("north", 1.41, 103.82), ("east", 1.35, 103.94), ("central", 1.35, 103.82))]
FEEDS = {
    "pm25": {"regionMetadata": REGIONS, "items": [{"timestamp": T, "readings": {"pm25_one_hourly": {"north": 12, "east": 15, "central": 14}}}]},
    "psi": {"regionMetadata": REGIONS, "items": [{"timestamp": T, "readings": {
        "psi_twenty_four_hourly": {"east": 60, "north": 50, "central": 55}, "pm25_twenty_four_hourly": {"east": 20},
        "no2_one_hour_max": {"east": 10}, "o3_sub_index": {"east": None}}}]},
    "air-temperature": by_station({"S109": 28.1, "S107": 29.0}),
    "relative-humidity": by_station({"S109": None, "S107": 70}),
    "rainfall": by_station({"S109": 0, "S107": 1.2}),
    "wind-speed": by_station({"S107": 5.5}),
    "wind-direction": by_station({"S107": 295}),
    "uv": {"records": [{"timestamp": "2026-09-29T16:00:00+08:00", "index": [
        {"hour": "2026-09-29T16:00:00+08:00", "value": 3}, {"hour": "2026-09-29T15:00:00+08:00", "value": 5}]}]},
    "two-hr-forecast": {"area_metadata": [{"name": "Bedok", "label_location": {"latitude": 1.32, "longitude": 103.93}},
                                          {"name": "Woodlands", "label_location": {"latitude": 1.44, "longitude": 103.78}}],
                        "items": [{"timestamp": T, "valid_period": {"start": "a", "end": "b"},
                                   "forecasts": [{"area": "Bedok", "forecast": "Thundery Showers"},
                                                 {"area": "Woodlands", "forecast": "Partly Cloudy (Night)"}]}]},
    "twenty-four-hr-forecast": {"records": [{"timestamp": T, "general": {
        "validPeriod": {"start": "a", "end": "b"}, "temperature": {"high": 34, "low": 25},
        "relativeHumidity": {"high": 95, "low": 60}, "wind": {"direction": "ESE", "speed": {"low": 10, "high": 20}},
        "forecast": {"code": "TL", "text": "Thundery Showers"}}, "periods": []}]},
    "four-day-outlook": {"records": [{"timestamp": T, "forecasts": [{
        "day": "Wednesday", "timestamp": T, "forecast": {"code": "TL", "text": "Thundery Showers", "summary": "Afternoon"},
        "temperature": {"high": 33, "low": 25}, "relativeHumidity": {"high": 95, "low": 60}, "wind": {"direction": "E"}}]}]},
    "wbgt": {"records": [{"datetime": T, "item": {"type": "observation", "isStationData": True, "readings": [
        {"station": {"id": "S124", "name": "Upper Changi Road North"}, "location": {"latitude": "1.36777", "longitude": "103.982262"}, "wbgt": "31.6", "heatStress": "Moderate"},
        {"station": {"id": "S117", "name": "Banyan Road"}, "location": {"latitude": "1.256", "longitude": "103.679"}, "wbgt": "33.2", "heatStress": "High"}]}}]},
    "flood-alerts": {"records": [{"datetime": T, "item": {"type": "observation", "isStationData": False,
                                                          "readings": [{"location": {"latitude": 1.32, "longitude": 103.886}}]}}]},
}
DENGUE = {"features": [
    {"geometry": {"type": "Polygon", "coordinates": [[[103.88, 1.31], [103.89, 1.31], [103.89, 1.323], [103.88, 1.323], [103.88, 1.31]]]},
     "properties": {"Description": "<table><tr><th>LOCALITY</th><td>Geylang East Ave 1</td></tr><tr><th>CASE_SIZE</th><td>7</td></tr></table>"}},
    {"geometry": {"type": "Polygon", "coordinates": [[[103.7, 1.4], [103.71, 1.4], [103.71, 1.41], [103.7, 1.4]]]},
     "properties": {"LOCALITY": "Woodlands", "CASE_SIZE": 3}}]}


class R:
    def __init__(self, d, code=200, headers=None): self.d, self.status_code, self.headers = d, code, headers or {}
    def json(self): return self.d

    def raise_for_status(self):
        if self.status_code >= 400:
            e = Exception(f"Client error '{self.status_code}'"); e.response = self; raise e


class HC:
    def __init__(self, fail=()): self.fail, self.asked, self.headers = set(fail), [], []

    def get(self, url, timeout=0, params=None, headers=None):
        self.headers.append(headers)
        name = params["api"] if params else url.rsplit("/", 1)[1]
        self.asked.append(name)
        if "poll-download" in url:
            return R({}, 429) if "dengue" in self.fail else R({"data": {"url": "https://s3/x.geojson"}})
        if url.endswith(".geojson"): return R(DENGUE)
        if name in self.fail: return R({}, 429, {"Retry-After": "120"})
        return R({"code": 0, "data": FEEDS[name]})


def fresh():
    A._next.clear(); A._dengue["at"] = 0.0


# ---------------------------------------------------------------- every feed, once, with the right numbers
fresh()
hc = HC()
sensors, readings = A.fetch(hc)
m = {(sid, metric): v for _, sid, metric, v in readings}
ids = {s["sensor_id"] for s in sensors}
assert all(s["kind"] == "model" and s["local"] is False and s["scale"] == "city" for s in sensors)
assert m[("nea-pm25", "pm25")] == 15.0                       # nearest region to Geylang, not the first listed
assert m[("nea-psi", "psi")] == 60.0 and m[("nea-psi", "pm25_24h")] == 20.0
assert ("nea-psi", "o3_sub_index") not in m                  # a null is not a zero
assert m[("nea-temp", "temp")] == 28.1                        # S109 is the nearer station
by_id = {x["sensor_id"]: x for x in sensors}
assert m[("nea-humidity", "humidity")] == 70.0 and by_id["nea-humidity"]["meta"]["station_id"] == "S107"   # nearest has null: next one, never a zero
assert by_id["nea-temp"]["meta"]["station_id"] == "S109"      # one stable id per measure; the station is in the meta and the name
assert m[("nea-rain", "rain")] == 0.0 and m[("nea-rain-island", "rain_max")] == 1.2 and m[("nea-rain-island", "rain_wet_pct")] == 50.0
assert m[("nea-winddir", "wind_dir")] == 295.0 and m[("nea-windspeed", "wind_speed")] == 5.5
assert m[("nea-uv", "uv")] in (3.0, 5.0) and sum(1 for r in readings if r[1] == "nea-uv") == 2   # today's hours, backfilled
assert m[("nea-wbgt", "wbgt")] == 31.6 and m[("nea-wbgt", "heat_stress_level")] == 1.0 and m[("nea-wbgt-island", "wbgt_max")] == 33.2
assert m[("nea-flood", "flood_alerts_active")] == 1.0 and m[("nea-flood", "flood_nearest_km")] < 1
assert m[("nea-dengue", "dengue_in_cluster")] == 1.0 and m[("nea-dengue", "dengue_nearest_cases")] == 7.0
assert m[("nea-fc2h-bedok", "fc_rain_expected")] == 1.0 and m[("nea-fc24h", "fc_temp_high")] == 34.0 and m[("nea-fc4d", "fc_d1_temp_low")] == 25.0
assert len(ids) == 16, sorted(ids)
assert all(len(hc.headers) and h is None for h in hc.headers)     # no key configured: no header sent

# ---------------------------------------------------------------- paced: asking again straight away asks nobody
n = len(hc.asked)
assert A.fetch(hc) == ([], []) and len(hc.asked) == n

# ---------------------------------------------------------------- a 429 backs that feed off and spares the rest
fresh()
hc = HC(fail={"uv"})
sensors, readings = A.fetch(hc)
assert "nea-uv" not in {s["sensor_id"] for s in sensors}
assert A._next["uv"] - time.time() >= A.BACKOFF_S - 5

# ---------------------------------------------------------------- every feed down is an error; a key is sent as a header
fresh()
try:
    A.fetch(HC(fail=set(FEEDS) | {"dengue"})); raise AssertionError("should have raised")
except RuntimeError as e:
    assert "every NEA feed failed" in str(e)
os.environ["NEA_API_KEY"] = "abc"
fresh()
hc = HC(); A.fetch(hc)
assert {"x-api-key": "abc"} in hc.headers

# ---------------------------------------------------------------- the geometry, by hand
ring = [[103.88, 1.31], [103.89, 1.31], [103.89, 1.323], [103.88, 1.323], [103.88, 1.31]]
assert A._ring_contains(ring, 1.317, 103.885) and not A._ring_contains(ring, 1.35, 103.885)
print("singapore-nea: ok")

# ---------------------------------------------------------------- staggered: a small budget per poll, everything served in the end
A.MAX_PER_POLL = 4
fresh()
hc = HC(); A.fetch(hc)
assert len(hc.asked) == 4
seen = set(hc.asked)
for _ in range(6):
    hc2 = HC(); A.fetch(hc2); seen |= set(hc2.asked)
assert len(seen) >= len(A.FEEDS) - 1, (len(seen), len(A.FEEDS))

# a 429 stops the poll: nothing else is requested behind it
fresh()
hc = HC(fail={"pm25"})
try:
    A.fetch(hc)
except RuntimeError:
    pass
assert len(hc.asked) == 1 and A._next["pm25"] - time.time() >= A.BACKOFF_S - 5
A.MAX_PER_POLL = 99
