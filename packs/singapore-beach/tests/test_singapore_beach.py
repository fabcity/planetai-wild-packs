"""The singapore-beach pack, offline: no NEA, no database.
The payload has the shape (and the polygons and week label format) of a live response from
/api/BeachWaterQuality/GetNeaData/<t>, read on 30 Sep 2026; the BANDS in the variants below are invented, to reach the
branches a live week of all Band 1 does not.
Run: python3 packs/singapore-beach/tests/test_singapore_beach.py
"""
import importlib.util
import os
import re
import time
from datetime import datetime, timezone

os.environ.update(NODE_LAT="1.317", NODE_LON="103.885")
spec = importlib.util.spec_from_file_location("beachpack", "packs/singapore-beach/adapter.py")
A = importlib.util.module_from_spec(spec); spec.loader.exec_module(A)


def poly(name, lat, lon):
    return {"Area": name, "Points": [{"Lat": str(lat), "Lng": str(lon)}, {"Lat": str(lat + .002), "Lng": str(lon + .002)}]}


AREAS = [poly("Changi Beach 1", 1.3917, 103.9911), poly("Changi Beach 2", 1.3800, 104.0030),
         poly("East Coast Beach 1", 1.2950, 103.8990), poly("East Coast Beach 2", 1.2990, 103.9130),
         poly("East Coast Beach 3", 1.3035, 103.9250), poly("Palawan Beach", 1.2480, 103.8220)]


def week(label, bands, adv=()):
    return {"Week": label, "Areas": [{"Area": a["Area"], "Description": "A &ndash; B", "AdvisoryOnMap":
                                      ("Bacteria" if a["Area"] in adv else ""), "Banding": str(bands.get(a["Area"], 1))}
                                     for a in AREAS]}


NEWEST = "14/09/2026 - 20/09/2026"
DOC = {"areas": AREAS, "data": [week("31/08/2026 - 06/09/2026", {}), week(NEWEST, {}), week("07/09/2026 - 13/09/2026", {})]}

# ---------------------------------------------------------------- a quiet week: newest week wins, whatever the order
sensors, readings = A.parse(DOC, ["East Coast", "Changi"], 1.317, 103.885)
assert [s["sensor_id"] for s in sensors] == ["nea-beach-east-coast", "nea-beach-changi"], sensors
assert all(s["kind"] == "model" and s["local"] is False and s["scale"] == "city" and s["source"] == "singapore-beach" for s in sensors)
m = {(sid, k): v for _, sid, k, v in readings}
assert m[("nea-beach-east-coast", "beach_band")] == 1.0 and m[("nea-beach-east-coast", "beach_stretches_elevated")] == 0.0
assert m[("nea-beach-east-coast", "beach_advisory")] == 0.0
ts = {t for t, *_ in readings}
assert ts == {datetime(2026, 9, 20, 15, 59, tzinfo=timezone.utc)}, ts       # Sunday 20 Sep 23:59 Singapore time
ec = sensors[0]["meta"]
assert ec["stretches_total"] == 3 and ec["nearest_stretch"] == "East Coast Beach 1" and ec["week"] == NEWEST, ec
assert 1 < ec["nearest_km"] < 4, ec                                          # the closest stretch is a few km from Geylang East
assert "Palawan" not in str(ec["stretches"]), "a beach that was not asked for stays out"

# ---------------------------------------------------------------- worst band, nearest band, advisory
bad = dict(DOC, data=[week(NEWEST, {"East Coast Beach 2": 2, "East Coast Beach 3": 3, "Changi Beach 1": 2}, adv={"East Coast Beach 3"})])
sensors, readings = A.parse(bad, ["East Coast", "Changi"], 1.317, 103.885)
m = {(sid, k): v for _, sid, k, v in readings}
assert m[("nea-beach-east-coast", "beach_band")] == 3.0                     # worst of its stretches
assert m[("nea-beach-east-coast", "beach_band_nearest")] == 1.0             # East Coast Beach 1 is fine
assert m[("nea-beach-east-coast", "beach_stretches_elevated")] == 2.0
assert m[("nea-beach-east-coast", "beach_advisory")] == 1.0 and m[("nea-beach-changi", "beach_advisory")] == 0.0
assert m[("nea-beach-changi", "beach_band")] == 2.0 and m[("nea-beach-changi", "beach_stretches_elevated")] == 1.0

# ---------------------------------------------------------------- junk is dropped, never turned into a band
junk = dict(DOC, data=[{"Week": NEWEST, "Areas": [{"Area": "East Coast Beach 1", "Banding": ""},
                                                  {"Area": "East Coast Beach 2", "Banding": "7"},
                                                  {"Area": "East Coast Beach 3", "Banding": "2"}]}])
sensors, readings = A.parse(junk, ["East Coast"], 1.317, 103.885)
assert sensors[0]["meta"]["stretches_total"] == 1 and {k: v for _, _, k, v in readings}["beach_band"] == 2.0
assert A.parse({"areas": [], "data": []}, ["East Coast"], 1.3, 103.8) == ([], [])
assert A.parse({"data": [{"Week": "not a week", "Areas": [{"Area": "East Coast Beach 1", "Banding": "1"}]}]}, ["East Coast"], 1.3, 103.8) == ([], [])
assert A.parse(DOC, ["Nowhere"], 1.3, 103.8) == ([], [])
assert A._week_end("31/02/2026 - 31/02/2026") is None

# ---------------------------------------------------------------- the request: rounded time, polite, cached, fails soft
class R:
    def __init__(self, doc, code=200): self.doc, self.code = doc, code
    def raise_for_status(self):
        if self.code >= 400: raise RuntimeError(f"Client error '{self.code}'")
    def json(self): return self.doc


class HC:
    def __init__(self, doc=DOC, code=200): self.doc, self.code, self.urls, self.headers = doc, code, [], []
    def get(self, url, timeout=None, headers=None):
        self.urls.append(url); self.headers.append(headers or {}); return R(self.doc, self.code)


A._state["at"] = 0.0
hc = HC(); s, r = A.fetch(hc)
t = int(re.search(r"GetNeaData/(\d+)$", hc.urls[0]).group(1))
assert t % 300 == 0 and abs(t - time.time()) < 400, t                       # NEA answers 400 to anything else
assert "planetai" in hc.headers[0]["User-Agent"] and len(s) == 2 and len(r) == 8
n = len(hc.urls)
assert A.fetch(hc) == ([], []) and len(hc.urls) == n                        # a weekly banding is not asked for every poll

A._state["at"] = 0.0
try:
    A.fetch(HC(code=403)); raise AssertionError("a refused request must raise, not return old numbers")
except RuntimeError as e:
    assert "NEA beach feed failed" in str(e)
assert time.time() - A._state["at"] < A.EVERY_S - 1000                     # ...and it retries within half an hour

os.environ["BEACH_AREAS"] = "Changi"
A._state["at"] = 0.0
s, r = A.fetch(HC()); assert [x["sensor_id"] for x in s] == ["nea-beach-changi"]
print("singapore-beach: ok")
