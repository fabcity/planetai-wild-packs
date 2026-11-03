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
a = S.assess(ulu, day([4, 5, 6, 9, 10, 11, 12, 19, 20]))
assert a["runs"] == [(5, 6), (9, 12)], "hours outside 05:00-18:00 do not count"
assert S.assess(ulu, day(range(24)))["runs"] == [(5, 17)], "the last good hour is 17 (17:00-18:00), the first is 05"
assert S.assess(ulu, day([17, 18]))["runs"] == [], "17 alone is not a run: the hour 18:00-19:00 is after sunset"
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
assert a["runs"] == [(5, 17)] and a["window"] == (9, 10) and a["inside"], a
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

# a window stays inside its run: 09-11 is his, but only 09-10 is good, so a three-hour session does not fit and the
# two-hour block that does is the window
a = S.assess(ulu, day([9, 10]), hours="09:00-12:00", session_h=3)
assert a["window"] == (9, 10) and a["inside"], a

# when no full session fits, shorter blocks are tried, session_h - 1 down to 1, and the first length that fits wins:
# a run 10-12, his hours 09-11, a three-hour session: 10-11 (two hours, mean wind 3.5) beats 11 alone (wind 1.0)
d = day([10, 11, 12], wind=6.0)
d[11]["wind"] = 1.0
a = S.assess(ulu, d, hours="08:30-12:00", session_h=3)
assert a["window"] == (10, 11) and a["inside"] and a["wind"] == 3.5, a
# no two-hour block fits (the hour 12 is not his): the one-hour block with the lowest wind
a = S.assess(ulu, day([11, 12], wind=6.0), hours="08:30-12:00", session_h=2)
assert a["window"] == (11, 11) and a["inside"] and a["wind"] == 6.0, "11:00-12:00 is inside 08:30-12:00: " + str(a)
# a block that starts inside his hours and runs past them is not inside: 11-12 starts at 11 but 12 is not his
a = S.assess(ulu, day([11, 12, 13]), hours="09:00-12:00", session_h=2)
assert a["window"] == (11, 11) and a["inside"], "the one hour that fits, not 11-12: " + str(a)
a = S.assess(ulu, day([12, 13]), hours="09:00-12:00", session_h=2)
assert a["window"] == (12, 13) and not a["inside"], "nothing of the run is his: the run, outside: " + str(a)
# equal wind among one-hour blocks: the earlier
a = S.assess(ulu, day([10, 11, 12]), hours="10:00-11:00,16:00-17:00", session_h=2)
assert a["window"] == (10, 10) and a["inside"], a

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
# a good run that partly overlaps his hours is inside them, as a shorter block (the real 1 and 2 Nov messages said
# "outside your hours" for both: 11-12 is inside 08:30-12:00 and 17-18 inside 16:00-18:30)
bal = S.assess(spots["balangan"], fixture_day(ULU, "2026-11-01"))
assert bal["runs"] == [(11, 12)] and bal["window"] == (11, 11) and bal["inside"], bal
a2 = S.assess(ulu, fixture_day(ULU, "2026-11-02"))
assert a2["runs"] == [] and not a2["good"], "17-18 was good only with the hour 18, which is past sunset: " + str(a2)
assert S.assess(spots["green-bowl"], fixture_day(GB, "2026-11-02"))["runs"] == [], "good 17-18 before; 18 is past sunset"
assert S.assess(ulu, fixture_day(ULU, "2026-10-28"))["runs"] == [(5, 12), (15, 17)], "15-18 before"
print("  archive: Uluwatu good 28 Oct and 1 Nov, not 31 Oct; Green Bowl not 1 Nov; 2 Nov was good only at 17-18 (spec §5)")

# ---------------------------------------------------------------- the message and the buttons
import re  # noqa: E402

nyang = spots["nyang-nyang"]
A_ULU = {"good": True, "runs": [(5, 17)], "window": (9, 10), "inside": True,
         "swell": {"h": 1.0, "t": 13.0, "dir": 203.0, "kw": 8.0}, "second": None, "kw": 8.0, "wind": 9.0, "wdir": 90.0,
         "tide": "high"}
assert S.spot_block(ulu, A_ULU, "en", 15) == "\n".join((
    "• Uluwatu, best 09:00–11:00 (good 05:00–18:00)",
    "  waves 1.0 m every 13 s, from the SSW",
    "  power 8 kW/m · wind 9 km/h from the E, offshore · tide high",
    "  https://www.windy.com/-8.815/115.087?swell1,-8.815,115.087,12")), S.spot_block(ulu, A_ULU, "en", 15)
big = dict(A_ULU, runs=[(16, 17)], window=(16, 17), kw=21.4, wind=4.0, wdir=200.0, tide="mid")
b = S.spot_block(nyang, big, "en", 15).split("\n")
assert b[0] == "• Nyang Nyang, best 16:00–18:00 (good 16:00–18:00) · big for you right now", b[0]
assert b[2] == "  power 21 kW/m · wind 4 km/h, glassy · tide mid", "glassy drops the direction: " + b[2]
assert "big for you" not in S.spot_block(nyang, dict(big, kw=15.0), "en", 15), "kw must be over the comfort, not at it"
b = S.spot_block(ulu, dict(A_ULU, wind=4.0), "en", 15).split("\n")
assert b[2].startswith("  power 8 kW/m · wind 4 km/h from the E, offshore"), "light and offshore stays offshore: " + b[2]
mx = S.spot_block(ulu, dict(A_ULU, second={"h": 0.6, "t": 9.0, "dir": 180.0, "kw": 1.0}), "en", 15).split("\n")
assert mx[1] == "  waves 1.0 m every 13 s, from the SSW, mixed with 0.6 m every 9 s from the S", mx[1]
out = S.spot_block(ulu, dict(A_ULU, runs=[(5, 7)], window=(5, 7), inside=False, tide=None), "en", 15).split("\n")
assert out[0] == "• Uluwatu, good 05:00–08:00, outside your hours", out[0]
assert out[2] == "  power 8 kW/m · wind 9 km/h from the E, offshore", "no tide, no tide words: " + out[2]
assert S.spot_block(ulu, dict(A_ULU, runs=[(5, 8), (16, 17)], window=(16, 17)), "en", 15).split("\n")[0] == \
    "• Uluwatu, best 16:00–18:00 (good 05:00–09:00, 16:00–18:00)", "every run is listed, end-exclusive like the window"
for loc in ("es", "id"):
    t3 = S.spot_block(ulu, A_ULU, loc, 15)
    assert "09:00–11:00" in t3 and "05:00–18:00" in t3 and "13 s" in t3 and "8 kW/m" in t3 and "9 km/h" in t3, t3
    assert t3.endswith("swell1,-8.815,115.087,12") and len(t3.split("\n")) == 4, t3
assert "grande para ti ahora" in S.spot_block(nyang, big, "es", 15) and "besar untukmu sekarang" in S.spot_block(nyang, big, "id", 15)
assert "del SSO" in S.spot_block(ulu, A_ULU, "es", 15), "es writes west as O"

assert S.day_text("2026-11-04", [(ulu, A_ULU)], "en", 15).startswith("Wednesday 4 Nov\n• Uluwatu")
assert S.day_text("2026-11-04", [], "en", 15) == "Wednesday 4 Nov: nothing looks good"
assert S.day_text("2026-11-05", [], "es", 15) == "jueves 5 nov: nada parece bueno"
assert S.day_text("2026-11-04", [], "id", 15) == "Rabu 4 Nov: sepertinya tidak ada yang bagus"
assert S.day_text("2026-11-04", [(ulu, A_ULU)], "es", 15).startswith("miércoles 4 nov\n")

msg = S.message([("2026-11-04", [(ulu, A_ULU)]), ("2026-11-05", [])], "en", 15)
assert msg.startswith("🌊 Surf in the next two days\n\nWednesday 4 Nov\n• Uluwatu"), msg
assert "\n\nThursday 5 Nov: nothing looks good\n\n" in msg and msg.endswith("Check before you go.\nHow was it? Write:"), msg
assert "Tap below" not in msg, "the pack cannot know whether the node sends buttons: one footer, the rule's {act} follows it"
assert S.message([("2026-11-04", [])], "es", 15).startswith("🌊 Olas en los próximos dos días\n\n")
assert S.message([("2026-11-04", [])], "id", 15).startswith("🌊 Ombak dua hari ke depan\n\n")
assert msg.endswith("\n\nThis comes from a 16 km model. Check before you go.\nHow was it? Write:"), msg
assert S.message([("2026-11-04", [])], "es", 15).endswith(
    "\n\nEsto sale de un modelo de 16 km. Compruébalo antes de ir.\n¿Cómo estuvo? Escribe:")
assert S.message([("2026-11-04", [])], "id", 15).endswith(
    "\n\nIni berasal dari model 16 km. Cek dulu sebelum berangkat.\nBagaimana ombaknya? Tulis:")
for loc in ("en", "es", "id"):         # Tomas's voice: no "a model, not a surf report" pair, in the footer or the listing
    assert "not a surf report" not in S.message([("2026-11-04", [])], loc, 15) and "no un parte" not in S.WORDS[loc]["b_foot"]
    assert "bukan laporan" not in S.WORDS[loc]["b_foot"], loc
import yaml  # noqa: E402
desc = yaml.safe_load((HERE.parent / "pack.yaml").read_text())["description"]
assert "not a surf report" not in desc and "16 km" in desc, desc
import inspect  # noqa: E402
assert list(inspect.signature(S.message).parameters) == ["days", "locale", "comfort_kw"], "no with_buttons"

# pick: his hours first, then power, at most three, good only
def res(sid, kw, inside=True, good=True):
    return ({"id": sid}, {"good": good, "inside": inside, "kw": kw})
got = S.pick([res("a", 5), res("b", 20, inside=False), res("c", 9), res("d", 30, good=False), res("e", 12), res("f", 3)])
assert [r[0]["id"] for r in got] == ["e", "c", "a"], "inside first by kw, three at most: " + str(got)
assert [r[0]["id"] for r in S.pick([res("a", 5), res("b", 20, inside=False)])] == ["a", "b"]
assert [r[0]["id"] for r in S.pick([res("a", 5), res("b", 6), res("c", 7)], n=2)] == ["c", "b"]
assert S.pick([res("d", 30, good=False)]) == [] and S.pick([]) == []

# keyboard: the node's contract (spec B1), checked here because pack tests run without a node checkout
assert S.keyboard([]) == []
kb = S.keyboard([ulu, nyang])
assert len(kb) == 3 and [len(r) for r in kb] == [3, 3, 2] and len(kb) <= 8 and all(len(r) <= 4 for r in kb)
assert [x["value"] for x in kb[0]] == ["uluwatu:good", "uluwatu:ok", "uluwatu:poor"]
assert [x["value"] for x in kb[1]] == ["nyang-nyang:good", "nyang-nyang:ok", "nyang-nyang:poor"]
assert [x["value"] for x in kb[2]] == ["didnt-go", "elsewhere"]
for x in (y for r in kb for y in r):
    assert re.fullmatch(r"[a-z0-9:_-]{1,40}", x["value"]), x
    assert x["stage"] in ("acted", "acknowledged") and set(x["text"]) == {"en", "es", "id"}, x
    assert all(isinstance(v, str) and v for v in x["text"].values()), x
    assert set(x) == {"text", "value", "stage"} | ({"ask"} if "ask" in x else set()), x
    if "ask" in x:
        assert set(x["ask"]) == {"en", "es", "id"} and all(x["ask"].values()), x
assert kb[0][0]["text"]["en"] == "Uluwatu 👍" and kb[0][1]["text"]["en"] == "👌" and kb[0][2]["text"]["en"] == "👎"
assert all(x["stage"] == "acted" and "ask" in x for x in kb[0] + kb[1])
assert kb[2][0]["stage"] == "acknowledged" and "ask" not in kb[2][0] and kb[2][0]["text"]["en"] == "Didn't go"
assert kb[2][1]["stage"] == "acted" and "ask" in kb[2][1] and kb[2][1]["text"]["en"] == "Surfed somewhere else"
assert kb[0][0]["ask"]["en"] == "Anything to add? Size, crowd, how you felt. One line, or ignore me."
assert kb[2][1]["ask"]["en"] == "Where, and how was it? One line, or ignore me."
for sid in spots:
    assert all(re.fullmatch(r"[a-z0-9:_-]{1,40}", f"{sid}:{r}") for r in ("good", "ok", "poor")), sid
# fix round 1: the label and the glassy word read the numbers the line prints, not the raw ones
assert "big for you" not in S.spot_block(ulu, dict(A_ULU, kw=15.4), "en", 15), "kw 15.4 prints 15, not over 15"
ob = S.spot_block(ulu, dict(A_ULU, kw=15.6), "en", 15).split("\n")
assert "power 16 kW/m" in ob[2] and ob[0].endswith("big for you right now"), "kw 15.6 prints 16, over 15"
rw = S.spot_block(ulu, dict(A_ULU, wind=7.6, wdir=200.0), "en", 15).split("\n")
assert rw[2] == "  power 8 kW/m · wind 8 km/h from the SSW · tide high", "7.6 prints 8: not glassy, direction, no suffix: " + rw[2]
rw = S.spot_block(ulu, dict(A_ULU, wind=7.4, wdir=200.0), "en", 15).split("\n")
assert rw[2] == "  power 8 kW/m · wind 7 km/h, glassy · tide high", "7.4 prints 7: glassy: " + rw[2]
rw = S.spot_block(ulu, dict(A_ULU, wind=8.0, wdir=200.0), "en", 15).split("\n")
assert rw[2] == "  power 8 kW/m · wind 8 km/h from the SSW · tide high", "8 is not glassy, and not offshore: " + rw[2]

# the label also shows on a block outside his hours
o = S.spot_block(ulu, dict(A_ULU, runs=[(5, 7)], window=(5, 7), inside=False, kw=21.0), "en", 15).split("\n")
assert o[0] == "• Uluwatu, good 05:00–08:00, outside your hours · big for you right now", o[0]
assert "big for you" not in S.spot_block(ulu, dict(A_ULU, runs=[(5, 7)], window=(5, 7), inside=False), "en", 15)

# every month heading, all three locales (2026-m-15 is the 15th)
MONTHS = {"en": "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec", "es": "ene feb mar abr may jun jul ago sep oct nov dic",
          "id": "Jan Feb Mar Apr Mei Jun Jul Agu Sep Okt Nov Des"}
for loc, names in MONTHS.items():
    for m, name in enumerate(names.split(), 1):
        h = S.day_text(f"2026-{m:02d}-15", [], loc, 15).split(":")[0]
        assert h.endswith(f" 15 {name}"), (loc, m, h)
# 15 Mar 2026 is a Sunday: the weekday is the date's, in each language
assert [S.day_text("2026-03-15", [], loc, 15).split(" ")[0] for loc in ("en", "es", "id")] == ["Sunday", "domingo", "Minggu"]

# es and id: the mixed line, the offshore word, the glassy word
mxd = dict(A_ULU, second={"h": 0.6, "t": 9.0, "dir": 180.0, "kw": 1.0})
assert S.spot_block(ulu, mxd, "es", 15).split("\n")[1] == "  olas 1.0 m cada 13 s, del SSO, mezcladas con 0.6 m cada 9 s del S"
assert S.spot_block(ulu, mxd, "id", 15).split("\n")[1] == "  ombak 1.0 m tiap 13 s, dari SSW, bercampur 0.6 m tiap 9 s dari S"
assert S.spot_block(ulu, A_ULU, "es", 15).split("\n")[2] == "  potencia 8 kW/m · viento 9 km/h del E, terral · marea alta"
assert S.spot_block(ulu, A_ULU, "id", 15).split("\n")[2] == "  tenaga 8 kW/m · angin 9 km/h dari E, dari darat · air pasang"
gl = dict(A_ULU, wind=4.0, wdir=200.0)
assert S.spot_block(ulu, gl, "es", 15).split("\n")[2] == "  potencia 8 kW/m · viento 4 km/h, como un espejo · marea alta"
assert S.spot_block(ulu, gl, "id", 15).split("\n")[2] == "  tenaga 8 kW/m · angin 4 km/h, mulus · air pasang"

# copy
assert kb[2][1]["text"]["id"] == "Berselancar di tempat lain", kb[2][1]["text"]
assert kb[2][1]["ask"]["id"] == "Di mana, dan bagaimana ombaknya? Satu baris, atau abaikan saja.", kb[2][1]["ask"]

# no two buttons share an ask object: one edited in place must not change the others
asks = [x["ask"] for r in kb for x in r if "ask" in x]
assert len({id(a) for a in asks}) == len(asks) == 7, "each button owns its ask map"
kb[0][0]["ask"]["en"] = "edited"
assert kb[0][1]["ask"]["en"] != "edited" and S.keyboard([ulu])[0][0]["ask"]["en"] != "edited"

print("  message: every number named, two days, one block per spot; keyboard: node's button contract")

print("surf: all checks passed")
