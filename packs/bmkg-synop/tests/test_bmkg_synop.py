"""bmkg-synop against a real report: Ngurah Rai, 26 Oct 2026 07:00 UTC, as WIS2 delivered it.

Run from a node's folder: python3 packs/bmkg-synop/tests/test_bmkg_synop.py
The fixture carries the notification and its BUFR already decoded, so CI needs no pybufrkit. Where pybufrkit is
installed (a node that ran `planetai packs install`), the inline BUFR is decoded too and must give the same values.
"""
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("bmkg_synop_adapter", HERE.parent / "adapter.py")
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)
FIX = json.loads((HERE / "report-97230-2026-10-26T07.json").read_text())
STATION = "0-20000-0-97230"

# What BMKG reported, read off the decoded BUFR by hand: 304.95 K, 296.75 K, 62 %, 100970 Pa, 130° at 4.1 m/s,
# 10000 m, 88 % cloud, and no rain group filled in.
EXPECTED = {"temp": 31.8, "dewpoint": 23.6, "humidity": 62.0, "pressure": 100.97, "wind_direction": 130.0,
            "wind_speed": 14.8, "visibility": 10.0, "cloud": 88.0}

# the notification: this station's, with its time, place and inline BUFR
got = A.notification(FIX["notification"], STATION)
assert got is not None
data_id, ts, lat, lon, raw = got
assert data_id == "id-bmkg:surface-based-observations/WIGOS_0-20000-0-97230_20261026T070000", data_id
assert ts.isoformat() == "2026-10-26T07:00:00+00:00", ts
assert (lat, lon) == (-8.7498871, 115.1765627), (lat, lon)
assert raw[:4] == b"BUFR" and raw[-4:] == b"7777", raw[:8]

# another station's report, and one without the message inline, are not ours
assert A.notification(FIX["notification"], "0-20000-0-96935") is None
bare = json.loads(json.dumps(FIX["notification"]))
del bare["properties"]["content"]
assert A.notification(bare, STATION) is None

# the values, in the node's units
vals = A.values(FIX["decoded"])
assert vals == EXPECTED, vals
assert "rainfall_1h" not in vals and "rainfall_24h" not in vals   # a missing group is no reading, never a zero

# rain belongs to the period before it; trace (-0.1) is 0; a 3-hour total is not mistaken for 1 or 24 hours
assert A.values([(4024, -1), (13011, 2.4), (4024, -24), (13011, 11.0)]) == {"rainfall_1h": 2.4, "rainfall_24h": 11.0}
assert A.values([(4024, -1), (13011, -0.1)]) == {"rainfall_1h": 0.0}
assert A.values([(4024, -3), (13011, 5.0)]) == {}

# the first wind is the observation; a later one (a gust group's direction) never overwrites it
assert A.values([(11001, 130), (11002, 4.1), (11001, 200), (11002, 9.0)]) == {"wind_direction": 130.0, "wind_speed": 14.8}

if importlib.util.find_spec("pybufrkit"):
    assert A.values(A.decode(raw)) == EXPECTED
    print("decoded the inline BUFR with pybufrkit too")

    # fetch drains what the listener left on its thread. A stand-in thread of the same name keeps this off the network.
    import collections
    import threading
    stop = threading.Event()
    t = threading.Thread(target=stop.wait, daemon=True, name=A.THREAD)
    t.station, t.reports = STATION, collections.deque([(ts, lat, lon, data_id, A.values(A.decode(raw)))] * 2)
    t.start()
    sensors, readings = A.fetch(None)
    stop.set()
    # a weather service's station is not a device at the address: the node's readouts only read non-`sensor` kinds
    assert sensors[0]["kind"] == "portal" and sensors[0]["scale"] == "region" and not sensors[0]["local"], sensors
    assert ("temp", 31.8) in {(m, v) for _, _, m, v in readings} and not t.reports
    print("fetch hands the node a portal sensor at region scale")

print("bmkg-synop: ok")
