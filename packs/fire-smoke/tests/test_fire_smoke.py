"""The fire-smoke pack, offline: no FIRMS, no key, no database.
Run: python3 packs/fire-smoke/tests/test_fire_smoke.py
"""
import importlib.util
import os
from datetime import datetime, timedelta, timezone

os.environ.update(NODE_LAT="1.317", NODE_LON="103.885", FIRMS_MAP_KEY="KEY-THAT-MUST-NOT-LEAK")
spec = importlib.util.spec_from_file_location("firepack", "packs/fire-smoke/adapter.py")
A = importlib.util.module_from_spec(spec); spec.loader.exec_module(A)

# ---------------------------------------------------------------- bearings and sectors
assert A.sector(0) == "n" and A.sector(359) == "n" and A.sector(44) == "ne" and A.sector(92) == "e"
assert A.sector(226) == "sw" and A.sector(270) == "w" and A.sector(316) == "nw"
assert abs(A._bearing(0, 0, 1, 0) - 0) < 0.5 and abs(A._bearing(0, 0, 0, 1) - 90) < 0.5
assert abs(A._bearing(0, 0, -1, 0) - 180) < 0.5 and abs(A._bearing(0, 0, 0, -1) - 270) < 0.5
w, s, e, n = map(float, A._bbox(1.317, 103.885, 500).split(","))
assert w < 103.885 < e and s < 1.317 < n and abs((n - s) * 111 - 1000) < 2

# ---------------------------------------------------------------- parsing and filters
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
HDR = ("latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,"
       "bright_ti5,frp,daynight")


def row(lat, lon, conf, hours_ago, frp=5):
    t = NOW - timedelta(hours=hours_ago)
    return f"{lat},{lon},330,0.4,0.4,{t:%Y-%m-%d},{t:%H%M},N,VIIRS,{conf},2.0NRT,290,{frp},D"


table = "\n".join([HDR, row(0.5, 101.0, "n", 2), row(0.6, 101.2, "h", 3, 20), row(-1.0, 105.5, "n", 5),
                   row(1.3, 103.9, "l", 1),          # low confidence: dropped
                   row(1.3, 103.9, "n", 30),         # older than 24 h: dropped
                   row(8.0, 95.0, "h", 1),           # beyond 500 km: dropped
                   row(1.40, 103.95, "n", 1)])       # 12 km north-east: kept
spots = A.parse(table, 1.317, 103.885, 500, NOW)
assert len(spots) == 4, spots
assert sorted(s["sector"] for s in spots) == ["ne", "se", "w", "w"], spots
assert min(s["km"] for s in spots) < 15

out = A.summarise(spots, NOW)
m = {name: v for _, _, name, v in out}
assert m["fires_24h"] == 4 and m["fires_250km_24h"] == 1 and m["fires_w"] == 2 and m["fires_frp_mw_24h"] == 35.0
assert m["fires_nearest_km"] < 15
# no fires: counts are zero, and there is no "nearest" to invent
z = {name: v for _, _, name, v in A.summarise([], NOW)}
assert z["fires_24h"] == 0 and "fires_nearest_km" not in z

# the day before, for the day-on-day change: parse asked for 48 h, summarise splits it at 24
table48 = "\n".join([HDR, row(0.5, 101.0, "n", 2), row(0.6, 101.2, "h", 30), row(0.7, 101.3, "n", 40),
                     row(0.8, 101.4, "n", 50)])       # 50 h ago: outside even the 48 h window
sp48 = A.parse(table48, 1.317, 103.885, 500, NOW, hours=48)
assert len(sp48) == 3, sp48
m48 = {name: v for _, _, name, v in A.summarise(sp48, NOW)}
assert m48["fires_24h"] == 1 and m48["fires_prev_24h"] == 2, m48
assert {name: v for _, _, name, v in A.summarise(spots, NOW)}["fires_prev_24h"] == 0   # a 24 h parse has no previous day
# FIRMS's last path segment is calendar days: one would cut the count at 00:00 UTC
assert A.DAY_RANGE >= 3

# a table that is not a table is an error, and says what came back
try:
    A.parse("Invalid MAP_KEY", 1.3, 103.9, 500, NOW); raise AssertionError("should have raised")
except RuntimeError as e:
    assert "not a fire table" in str(e)

# ---------------------------------------------------------------- the key never leaves in an error
class R:
    def __init__(self, text, code=200): self.text, self.status_code = text, code

    def raise_for_status(self):
        if self.status_code >= 400:
            err = Exception(f"Client error '{self.status_code}' for url 'https://x/{os.environ['FIRMS_MAP_KEY']}/V'")
            err.response = self; raise err


class HC:
    def __init__(self, text="", code=200): self.text, self.code = text, code
    def get(self, url, timeout=0): return R(self.text, self.code)


A._state["at"] = 0
try:
    A.fetch(HC("", 403)); raise AssertionError("should have raised")
except RuntimeError as e:
    assert "KEY-THAT-MUST-NOT-LEAK" not in str(e) and "403" in str(e), str(e)

# ---------------------------------------------------------------- idles without a key, and paces itself
os.environ["FIRMS_MAP_KEY"] = ""
A._state["at"] = 0
assert A.fetch(HC(table)) == ([], [])
os.environ["FIRMS_MAP_KEY"] = "KEY-THAT-MUST-NOT-LEAK"
A._state["at"] = 0
s1, r1 = A.fetch(HC(table.replace(NOW.strftime("%Y-%m-%d"), datetime.now(timezone.utc).strftime("%Y-%m-%d"))))
assert len(s1) == 1 and s1[0]["kind"] == "model" and s1[0]["local"] is False
assert A.fetch(HC(table)) == ([], [])      # asked again straight away: nothing new to say

print("fire-smoke: ok")
