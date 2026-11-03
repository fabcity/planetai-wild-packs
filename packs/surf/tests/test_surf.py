"""The surf rule in pure Python: power, arcs, tide thirds, the four gates, the window, the mixed flag and the message
line, on hand-built hours and on Open-Meteo's own archive for Uluwatu and Green Bowl, 27 October to 2 November 2026
(GFS Wave swell, MeteoFrance tide, the forecast API's wind; tests/fixtures). Run: python3 packs/surf/tests/test_surf.py
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import surf as S  # noqa: E402

spots = S.load_spots(HERE.parent / "spots.yml")
FX = {k: json.loads((HERE / "fixtures" / f"{k}.json").read_text()) for k in ("swell", "tide", "wind")}


def fixture_day(i, date):
    return S.day_rows(FX["swell"][i], FX["tide"][i], FX["wind"][i], date)


def row(hr, h1=1.5, t1=12.0, d1=210.0, h2=None, t2=None, d2=None, ww=0.0, wind=3.0, wdir=90.0, sea=0.0):
    return {"hr": hr, "h1": h1, "t1": t1, "d1": d1, "h2": h2, "t2": t2, "d2": d2, "ww": ww, "wind": wind,
            "wdir": wdir, "sea": sea}


def day(passing, **kw):
    """24 hours, tide flat at mid (sea 0 between -1 and 1), the hours in `passing` with a good swell, the rest flat."""
    rows = [row(h, h1=0.1) for h in range(24)]
    rows[0]["sea"], rows[1]["sea"] = -1.0, 1.0
    for h in passing:
        rows[h] = row(h, **kw)
    return rows


ulu = spots["uluwatu"]

# ---------------------------------------------------------------- power, arcs, tide
assert round(S.power(0.80, 13.8), 1) == 4.3, S.power(0.80, 13.8)
assert round(S.power(1.54, 12.1)) == 14, S.power(1.54, 12.1)
assert S.within(0, (300, 30)) and S.within(30, (300, 30)) and not S.within(31, (300, 30)), "an arc wraps through north"
assert S.within(180, (180, 250)) and S.within(250, (180, 250)) and not S.within(251, (180, 250)), "inclusive"
assert S.tide_class(0.0, -1, 1) == "mid" and S.tide_class(-0.9, -1, 1) == "low" and S.tide_class(0.9, -1, 1) == "high"
assert S.tide_class(0.5, 0.5, 0.5) == "mid", "a flat day is mid, not a division by zero"
assert S.tide_class(None, -1, 1) is None
print("  power, arcs, tide thirds")

# ---------------------------------------------------------------- spots.yml
assert len(spots) == 14, sorted(spots)
assert (spots["impossibles"]["lat"], spots["impossibles"]["lon"]) == (-8.8085, 115.1075), spots["impossibles"]
assert spots["impossibles"]["aliases"] == ["impossible"], spots["impossibles"]
assert (spots["nyang-nyang"]["lat"], spots["nyang-nyang"]["lon"]) == (-8.8400, 115.0945), spots["nyang-nyang"]
assert spots["nyang-nyang"]["aliases"] == ["nyang"], spots["nyang-nyang"]
for sid, sp in spots.items():
    assert sid == sp["id"] and all(c.isalnum() or c == "-" for c in sid) and sid == sid.lower(), sid
    assert sp["kw"][0] < sp["kw"][1], sp
    assert sp["tide"] <= {"low", "mid", "high"} and sp["tide"], sp
print("  spots.yml: 14 spots, ranges ordered, tides named")

# ---------------------------------------------------------------- his hours
assert S.parse_hours("08:30-12:00,16:00-18:30") == [9, 10, 11, 16, 17]
assert S.parse_hours("16:00-18:30") == [16, 17]
assert S.parse_hours("nonsense") == S.parse_hours("") == S.parse_hours(None) == [9, 10, 11, 16, 17], "malformed: the default"
print("  parse_hours: the hours that fit whole inside a range")

# ---------------------------------------------------------------- good hours, runs, the window
a = S.assess(ulu, day([6]))
assert not a["good"] and a["runs"] == [] and a["window"] is None and not a["inside"], "one passing hour is not a run"
assert a["swell"] is None and a["kw"] == 0.0 and a["wind"] is None and a["tide"] is None, a
a = S.assess(ulu, day([6, 7]))
assert a["good"] and a["runs"] == [(6, 7)] and a["window"] == (6, 7) and not a["inside"], a
assert (a["from_h"], a["to_h"]) == (6, 7), "v1's keys follow the window until the adapter drops them"
a = S.assess(ulu, day([4, 5, 6, 9, 10, 11, 12, 19, 20]))
assert a["runs"] == [(5, 6), (9, 12)], "hours outside 05-18 do not count"
assert a["window"] == (9, 10) and a["inside"], "equal wind: the earlier window"
a = S.assess(ulu, day([5, 6, 7, 8, 16, 17]))
assert a["runs"] == [(5, 8), (16, 17)] and a["window"] == (16, 17) and a["inside"], a
a = S.assess(ulu, day([5, 6, 7]))
assert a["runs"] == [(5, 7)] and a["window"] == (5, 7) and not a["inside"], "good, but outside his hours: the first run"
assert round(a["kw"], 1) == round(S.power(1.5, 12.0), 1), a

d = day(range(5, 19), wind=6.0)
d[9]["wind"] = d[10]["wind"] = 2.0
d[9]["h1"], d[10]["h1"] = 1.0, 2.0
a = S.assess(ulu, d)
assert a["runs"] == [(5, 18)] and a["window"] == (9, 10) and a["inside"], a
assert a["wind"] == 2.0 and a["wdir"] == 90.0 and a["tide"] == "mid", a
assert abs(a["kw"] - (S.power(1.0, 12.0) + S.power(2.0, 12.0)) / 2) < 1e-9, "kw is the mean of power at 09 and 10"
assert abs(a["swell"]["h"] - 1.5) < 1e-9 and a["swell"]["t"] == 12.0 and a["swell"]["dir"] == 210.0, a["swell"]
d[9]["sea"], d[10]["sea"] = -0.9, 0.9
assert S.assess(ulu, d)["tide"] == "low", "the tide is the first hour's"

d = day(range(5, 19), wind=6.0)
d[10]["wind"] = d[11]["wind"] = 2.0
assert S.assess(ulu, d)["window"] == (10, 11), "a window can start anywhere in a run"
d = day(range(5, 19), wind=6.0)
assert S.assess(ulu, d, hours="16:00-18:30")["window"] == (16, 17), "his hours are a setting"
assert S.assess(ulu, d, hours="09:00-12:00", session_h=3)["window"] == (9, 11), "so is the length of a session"
# the window is picked by the mean wind over its hours, not the first hour's: 09-10 starts calmer and averages 3.0,
# 16-17 starts at 3.0 and averages 2.3
d = day(range(5, 19), wind=6.0)
d[9]["wind"], d[10]["wind"], d[16]["wind"], d[17]["wind"] = 2.0, 4.0, 3.0, 1.6
a = S.assess(ulu, d)
assert a["window"] == (16, 17) and a["inside"], a
assert abs(a["wind"] - 2.3) < 1e-9, "wind is the mean over the window"

# the numbers over a window: means for t, kw and wind; direction, swell dir and the second swell from its first hour
d = day([9, 10])
d[9].update(wdir=80.0, d1=200.0, t1=12.0, h2=0.9, t2=13.0, d2=240.0)
d[10].update(wdir=100.0, d1=220.0, t1=14.0, h2=None, t2=None, d2=None, wind=5.0)
a = S.assess(ulu, d)
assert a["window"] == (9, 10) and a["inside"], a
assert a["wdir"] == 80.0 and a["swell"]["dir"] == 200.0, "direction comes from the first hour"
assert a["second"] and a["second"]["dir"] == 240.0 and a["second"]["h"] == 0.9, "so does the second swell"
assert a["swell"]["t"] == 13.0 and a["wind"] == 4.0, "t and wind are means"
assert abs(a["kw"] - (S.power(1.5, 12.0) + S.power(1.5, 14.0)) / 2) < 1e-9, a["kw"]

# no window inside his hours: the first run gives the numbers, not the last
d = day([5, 6, 13, 14])
a = S.assess(ulu, d)
assert a["runs"] == [(5, 6), (13, 14)] and a["window"] == a["runs"][0] and not a["inside"], a

# a window stays inside its run: 09-11 is his, but only 09-10 is good, so a three-hour session is not inside
a = S.assess(ulu, day([9, 10]), hours="09:00-12:00", session_h=3)
assert a["window"] == (9, 10) and not a["inside"], a

# a session of zero hours is a session of one, not a division by zero
assert S.assess(ulu, day([9, 10]), session_h=0) == S.assess(ulu, day([9, 10]), session_h=1)
assert S.assess(ulu, day([9, 10]), session_h=0)["window"] == (9, 9)
print("  window: every good hour, runs of two, lowest mean wind inside his hours, earlier on a tie, means over it")

# ---------------------------------------------------------------- the gates
assert not S.assess(ulu, day([6, 7], wdir=270, wind=15))["good"], "15 km/h onshore fails"
assert S.assess(ulu, day([6, 7], wdir=270, wind=5))["good"], "under 8 km/h from anywhere is glassy"
assert not S.assess(ulu, day([6, 7], wdir=90, wind=30))["good"], "offshore over 25 km/h fails"
assert not S.assess(ulu, day([6, 7], t1=8.0))["good"], "an 8 s swell is under the 10 s floor"
assert S.assess(ulu, day([6, 7], t1=8.0), min_period=8)["good"], "the floor is a setting"
assert not S.assess(ulu, day([6, 7], d1=100))["good"], "a swell from outside the window never counts"
assert not S.assess(ulu, day([6, 7], h1=4.0, t1=12))["good"], "78 kW/m is over Uluwatu's 50"
assert not S.assess(ulu, day([6, 7], ww=1.0))["good"], "a wind sea over half the swell's height is junk"
bingin = spots["bingin"]
low = day([6, 7]); low[6]["sea"] = low[7]["sea"] = -0.9
assert not S.assess(bingin, low)["good"] and S.assess(ulu, low)["good"], "low tide fails a mid-and-high spot, not Uluwatu"
nulls = day([6, 7]); nulls[7]["wind"] = None
assert not S.assess(ulu, nulls)["good"], "an hour with no wind fails, and does not raise"
nulls = day([6, 7]); nulls[6]["sea"] = None
assert not S.assess(ulu, nulls)["good"], "an hour with no sea level fails the tide gate"
assert S.assess(ulu, [dict(r, sea=None) for r in day([6, 7])])["tide"] is None
print("  gates: wind, period, window, power, junk, tide, and a null in any of them")

# ---------------------------------------------------------------- the swell that counts, and the mixed flag
a = S.assess(ulu, day([6, 7], d1=90, h2=1.2, t2=13.0, d2=200))
assert a["good"] and a["swell"]["h"] == 1.2 and a["swell"]["dir"] == 200, "only the secondary is in the window"
a = S.assess(ulu, day([6, 7], h2=0.9, t2=13.0, d2=240))
assert a["good"] and a["second"] and a["second"]["h"] == 0.9, "30 degrees apart, over a quarter of the power: mixed"
a = S.assess(ulu, day([6, 7], h2=0.9, t2=13.0, d2=220))
assert a["good"] and a["second"] is None, "10 degrees apart is one swell"
a = S.assess(ulu, day([6, 7], h2=0.3, t2=13.0, d2=240))
assert a["second"] is None, "a secondary under a quarter of the power is not a mix"
print("  the in-window swell counts; mixed is a flag, never a gate")

# ---------------------------------------------------------------- Open-Meteo's archive, 27 Oct - 2 Nov
ULU, GB = 0, 1
r = fixture_day(ULU, "2026-10-28")
assert len(r) == 24 and r[0]["hr"] == 0 and r[23]["hr"] == 23, r[:1]
a = S.assess(ulu, r)
assert a["good"] and a["runs"][0] == (5, 12), a
assert S.assess(ulu, fixture_day(ULU, "2026-11-01"))["good"]
assert not S.assess(ulu, fixture_day(ULU, "2026-10-31"))["good"]
assert not S.assess(spots["green-bowl"], fixture_day(GB, "2026-11-01"))["good"]
assert S.assess(spots["green-bowl"], fixture_day(GB, "2026-11-02"))["good"]
print("  archive: Uluwatu good 28 Oct and 1 Nov, not 31 Oct; Green Bowl not 1 Nov, good 2 Nov (spec §5)")

# ---------------------------------------------------------------- the line
a = {"good": True, "from_h": 5, "to_h": 12, "swell": {"h": 1.54, "t": 12.1, "dir": 203.0, "kw": S.power(1.54, 12.1)},
     "second": None, "kw": 14.2, "wind": 3.6, "wdir": 84.0, "tide": "low"}
en = S.line(ulu, a, "en")
assert en.startswith("• Uluwatu 5–12: "), en
assert "1.5 m at 12 s from the SSW" in en and "14 kW/m" in en and "wind 4 km/h E (offshore)" in en and "low tide" in en, en
assert en.endswith("https://www.windy.com/-8.815/115.087?swell1,-8.815,115.087,12"), en
for loc in ("es", "id"):
    t = S.line(ulu, a, loc)
    assert t.startswith("• Uluwatu 5–12: ") and "1.5 m" in t and "12 s" in t and "14 kW/m" in t and "4 km/h" in t, t
    assert t.endswith("swell1,-8.815,115.087,12"), t
mixed = S.line(ulu, dict(a, second={"h": 0.9, "t": 15.0, "dir": 225.0, "kw": S.power(0.9, 15)}), "en")
assert "14 kW/m, mixed with 0.9 m at 15 s from the SW" in mixed, mixed
assert "(light)" in S.line(ulu, dict(a, wdir=270.0), "en"), "a glassy wind from elsewhere is not called offshore"
print("  line: en, es, id with the same numbers and the Windy link")

print("surf: all checks passed")
