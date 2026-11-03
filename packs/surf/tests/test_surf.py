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

# ---------------------------------------------------------------- the window
a = S.assess(ulu, day([6]))
assert not a["good"], "one passing hour is not a window"
a = S.assess(ulu, day([6, 7]))
assert a["good"] and (a["from_h"], a["to_h"]) == (6, 7), a
a = S.assess(ulu, day([4, 5, 6, 9, 10, 11, 12, 19, 20]))
assert (a["from_h"], a["to_h"]) == (9, 12), "the longest run inside 05-18; hours outside it do not count"
a = S.assess(ulu, day([6, 7, 9, 10]))
assert (a["from_h"], a["to_h"]) == (6, 7), "a tie goes to the earlier run"
assert round(a["kw"], 1) == round(S.power(1.5, 12.0), 1), a
print("  window: two hours in a row, longest run, earlier on a tie, mean power")

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
assert a["good"] and a["from_h"] <= 5 and a["to_h"] >= 12, a
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
