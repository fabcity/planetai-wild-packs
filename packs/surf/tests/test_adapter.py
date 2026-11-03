"""The surf adapter with a fake http client serving Open-Meteo's archive for Uluwatu and Green Bowl (tests/fixtures):
idle when SURF_SPOTS is blank, three calls a fetch, one fetch per three hours even after a failure, an unknown spot
skipped, every metric it writes declared in channels.yml, and the summary sensor `surf` with the two-day message and
its buttons. Run: python3 packs/surf/tests/test_adapter.py
"""
import json
import logging
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import adapter as A  # noqa: E402

FX = {k: json.loads((HERE / "fixtures" / f"{k}.json").read_text()) for k in ("swell", "tide", "wind")}
NOW = datetime(2026, 10, 27, 9, 0, tzinfo=timezone.utc)          # 17:00 in Bali: tomorrow is 28 October
A._now = lambda: NOW


class Resp:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class HC:
    def __init__(self, fail=False, fx=FX):
        self.calls, self.fail, self.fx = [], fail, fx

    def get(self, url, params=None, **kw):
        self.calls.append((url, dict(params or {})))
        if self.fail:
            raise RuntimeError("429 Daily API request limit exceeded")
        n = len(str(params["latitude"]).split(","))
        kind = "wind" if url.startswith("https://api.open-meteo.com") else "swell" if params.get("models") else "tide"
        data = self.fx[kind][:n]
        return Resp(data if n > 1 else data[0])       # Open-Meteo answers one location as an object, not a list


def env(**kv):
    for k in ("SURF_SPOTS", "SURF_MIN_PERIOD", "SURF_HOURS", "SURF_SESSION_H", "SURF_COMFORT_KW"):
        os.environ.pop(k, None)
    os.environ.update(kv)
    os.environ["PACK_OUT"] = tempfile.mkdtemp()


env(SURF_SPOTS="")
hc = HC()
assert A.fetch(hc) == ([], []) and hc.calls == [], "blank SURF_SPOTS: idle, no network"
print("  idle when no spots are set")

env(SURF_SPOTS="uluwatu,green-bowl")
hc = HC()
sensors, readings = A.fetch(hc)
assert len(hc.calls) == 3, hc.calls
swell = [p for u, p in hc.calls if p.get("models")]
assert len(swell) == 1 and swell[0]["models"] == "ncep_gfswave016" and "marine-api" in [u for u, p in hc.calls if p.get("models")][0]
assert all(p["timezone"] == "auto" for _, p in hc.calls), hc.calls
assert all(p["latitude"] == "-8.815,-8.8475" for _, p in hc.calls), hc.calls
by = {s["sensor_id"]: s for s in sensors}
assert set(by) == {"surf-uluwatu", "surf-green-bowl", "surf"}, by
u = by["surf-uluwatu"]
assert (u["kind"], u["scale"], u["local"], u["indoor"], u["source"]) == ("model", "bioregion", False, False, "surf"), u
assert (u["lat"], u["lon"]) == (-8.815, 115.087) and u["meta"]["dates"] == ["2026-10-28", "2026-10-29"], u
assert u["meta"]["attribution"] == A.ATTRIBUTION and not any(k.startswith("line_") for k in u["meta"]), u["meta"]
val = {(s, m): v for ts, s, m, v in readings}
assert val[("surf-uluwatu", "surf_good")] == 1 and val[("surf-uluwatu", "surf_kw")] > 4, val
assert val[("surf-green-bowl", "surf_good")] in (0, 1)
assert all(ts == NOW for ts, *_ in readings), "rows are stamped at the fetch, never at tomorrow"
assert all(v is not None for *_, v in readings)
print("  two spots: three calls (GFS swell, tide, wind), two spot sensors and the summary, rows at fetch time")

declared = {c["metric"] for c in yaml.safe_load((HERE.parent / "channels.yml").read_text())}
assert {m for _, _, m, _ in readings} <= declared, {m for _, _, m, _ in readings} - declared
assert yaml.safe_load((HERE.parent / "pack.yaml").read_text())["id"] == "surf"
print("  every metric written is declared in channels.yml")

hc2 = HC()
assert A.fetch(hc2) == ([], []) and hc2.calls == [], "inside three hours: no call"
stamp = Path(os.environ["PACK_OUT"]) / "surf.stamp"
old = time.time() - 3 * 3600 - 1
os.utime(stamp, (old, old))
assert A.fetch(hc2)[0] and len(hc2.calls) == 3, "after three hours it asks again"
print("  one fetch per three hours")

env(SURF_SPOTS="uluwatu,nowhere")
seen = []
h = logging.Handler(); h.emit = lambda rec: seen.append(rec.getMessage())
logging.getLogger().addHandler(h); logging.getLogger().setLevel(logging.INFO)
hc = HC()
sensors, _ = A.fetch(hc)
assert [s["sensor_id"] for s in sensors] == ["surf-uluwatu", "surf"], sensors
assert sum("nowhere" in m for m in seen) == 1, seen
print("  an unknown spot is skipped with one warning")

env(SURF_SPOTS="uluwatu")
hc = HC(fail=True)
try:
    A.fetch(hc)
    raise AssertionError("a failed request must raise, so the node logs it")
except RuntimeError:
    pass
hc = HC()
assert A.fetch(hc) == ([], []) and hc.calls == [], "the stamp was written before the failed call: no retry for 3 hours"
print("  a 429 raises and is not retried on the next poll")

env(SURF_SPOTS="uluwatu,green-bowl")
sensors, readings = A.fetch(HC())
by = {s["sensor_id"]: s for s in sensors}
val = {(s, m): v for ts, s, m, v in readings}
S = by["surf"]
assert (S["source"], S["kind"], S["scale"], S["cadence"], S["local"], S["indoor"]) == \
    ("surf", "model", "bioregion", "PT3H", False, False), S
assert (S["lat"], S["lon"]) == (-8.815, 115.087), "the first watched spot's position"
m = S["meta"]
assert set(m) == {"attribution", "fetched", "any", "text_en", "text_es", "text_id", "buttons"}, set(m)
assert m["fetched"] == "2026-10-27" and m["any"] == "1", m
assert m["text_en"].startswith("🌊 Surf in the next two days") and "Wednesday 28 Oct" in m["text_en"], m["text_en"]
assert m["text_es"].startswith("🌊 Olas en los próximos dos días") and m["text_id"].startswith("🌊 Ombak dua hari"), m
assert m["text_en"].endswith("Check before you go.\nHow was it? Write:"), "one footer, buttons or not"
rows = json.loads(m["buttons"])
assert [r[0]["value"] for r in rows[:-1]] == ["uluwatu:good"] and rows[-1][0]["value"] == "didnt-go", rows
assert "Tap below" not in m["text_en"] and "green-bowl" not in m["buttons"] and len(rows) <= 8 and all(len(r) <= 4 for r in rows)
assert val[("surf", "surf_spots_good")] == 2.0, "Uluwatu, tomorrow and the day after"
d2 = {m for _, s, m, _ in readings if s == "surf-uluwatu" and m.endswith("_d2")}
assert d2 == {k + "_d2" for k in ("surf_good", "surf_kw", "surf_from_h", "surf_to_h", "surf_swell_m", "surf_period_s",
                                  "surf_swell_dir", "surf_mixed", "surf_wind_kmh", "surf_wind_dir", "surf_tide")}, d2
assert (val[("surf-uluwatu", "surf_from_h")], val[("surf-uluwatu", "surf_to_h")]) == (9, 10), val
assert val[("surf-uluwatu", "surf_good_d2")] == 1 and val[("surf-uluwatu", "surf_kw_d2")] > 4, val
assert val[("surf-green-bowl", "surf_good_d2")] == 0, val
declared = {c["metric"] for c in yaml.safe_load((HERE.parent / "channels.yml").read_text())}
assert {m for _, _, m, _ in readings} <= declared and len(declared) == 29, {m for _, _, m, _ in readings} - declared
print("  the summary sensor: dates, three texts, the buttons of tomorrow's picks, the _d2 readings, 29 metrics declared")

env(SURF_SPOTS="green-bowl")
S = {s["sensor_id"]: s for s in A.fetch(HC())[0]}["surf"]["meta"]
assert S["any"] == "0" and S["buttons"] == "[]" and "nothing looks good" in S["text_en"], S
assert S["text_en"].endswith("How was it? Write:"), S["text_en"]
print("  nothing good: any 0, no buttons")

cut = {k: [{**d, "hourly": {n: v[:36] for n, v in d["hourly"].items()}} for d in v] for k, v in FX.items()}
env(SURF_SPOTS="uluwatu")
sensors, readings = A.fetch(HC(fx=cut))
S = {s["sensor_id"]: s for s in sensors}["surf"]["meta"]
day2 = S["text_en"].split("\n\n")[2]
assert day2 == "Thursday 29 Oct: nothing looks good" and S["any"] == "1", S["text_en"]
val = {(s, m): v for ts, s, m, v in readings}
assert val[("surf-uluwatu", "surf_good_d2")] == 0 and ("surf-uluwatu", "surf_swell_m_d2") not in val, val
assert val[("surf", "surf_spots_good")] == 1.0, val
print("  a series cut short: day 2 reads nothing looks good, no exception")

env(SURF_SPOTS="uluwatu", SURF_HOURS="nonsense", SURF_SESSION_H="two", SURF_COMFORT_KW="big")
seen.clear()
sensors, _ = A.fetch(HC())
assert [sum(k in m for m in seen) for k in ("SURF_HOURS", "SURF_SESSION_H", "SURF_COMFORT_KW")] == [1, 1, 1], seen
assert {s["sensor_id"]: s for s in sensors}["surf"]["meta"]["any"] == "1"
env(SURF_SPOTS="uluwatu", SURF_HOURS="09:00-09:30")
seen.clear(); A.fetch(HC())
assert sum("SURF_HOURS" in m for m in seen) == 1, "hours that parse to nothing warn too"
env(SURF_SPOTS="uluwatu", SURF_HOURS="", SURF_SESSION_H="3", SURF_COMFORT_KW="2")
seen.clear()
m = {s["sensor_id"]: s for s in A.fetch(HC())[0]}["surf"]["meta"]
assert not [x for x in seen if "SURF_" in x] and "big for you right now" in m["text_en"], (seen, m["text_en"])
print("  a bad SURF_HOURS, SURF_SESSION_H or SURF_COMFORT_KW warns once and falls back; a blank one does not")

print("surf adapter: all checks passed")
