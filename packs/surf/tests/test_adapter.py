"""The surf adapter with a fake http client serving Open-Meteo's archive for Uluwatu and Green Bowl (tests/fixtures):
idle when SURF_SPOTS is blank, three calls a fetch, one fetch per three hours even after a failure, an unknown spot
skipped, and every metric it writes declared in channels.yml. Run: python3 packs/surf/tests/test_adapter.py
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
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def get(self, url, params=None, **kw):
        self.calls.append((url, dict(params or {})))
        if self.fail:
            raise RuntimeError("429 Daily API request limit exceeded")
        n = len(str(params["latitude"]).split(","))
        kind = "wind" if url.startswith("https://api.open-meteo.com") else "swell" if params.get("models") else "tide"
        data = FX[kind][:n]
        return Resp(data if n > 1 else data[0])       # Open-Meteo answers one location as an object, not a list


def env(**kv):
    for k in ("SURF_SPOTS", "SURF_MIN_PERIOD"):
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
assert set(by) == {"surf-uluwatu", "surf-green-bowl"}, by
u = by["surf-uluwatu"]
assert (u["kind"], u["scale"], u["local"], u["indoor"], u["source"]) == ("model", "bioregion", False, False, "surf"), u
assert (u["lat"], u["lon"]) == (-8.815, 115.087) and u["meta"]["date"] == "2026-10-28", u
assert u["meta"]["line_en"].startswith("• Uluwatu ") and "windy.com" in u["meta"]["line_es"] and u["meta"]["line_id"], u["meta"]
val = {(s, m): v for ts, s, m, v in readings}
assert val[("surf-uluwatu", "surf_good")] == 1 and val[("surf-uluwatu", "surf_kw")] > 4, val
assert val[("surf-green-bowl", "surf_good")] in (0, 1)
assert all(ts == NOW for ts, *_ in readings), "rows are stamped at the fetch, never at tomorrow"
assert all(v is not None for *_, v in readings)
print("  two spots: three calls (GFS swell, tide, wind), two sensors with their lines, rows at fetch time")

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
assert [s["sensor_id"] for s in sensors] == ["surf-uluwatu"], sensors
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

print("surf adapter: all checks passed")
