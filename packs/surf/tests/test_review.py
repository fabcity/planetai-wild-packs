"""The journal: spots found in a keeper's words (by id, name or alias), the window read back from the alert's own
text, and that morning's numbers from Open-Meteo's archive (here, tests/fixtures), grouped by spot. An alert nobody
answered is listed as unanswered. Run: python3 packs/surf/tests/test_review.py
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import review as R  # noqa: E402
import surf as S  # noqa: E402

spots = S.load_spots(HERE.parent / "spots.yml")
FX = {k: json.loads((HERE / "fixtures" / f"{k}.json").read_text()) for k in ("swell", "tide", "wind")}
WHERE = {"uluwatu": 0, "green-bowl": 1, "keramas": 1}
asked = []


def fetch_day(spot, date):
    asked.append((spot["id"], date))
    i = WHERE[spot["id"]]
    return S.day_rows(FX["swell"][i], FX["tide"][i], FX["wind"][i], date)


assert R.find_spots("Ulu good, Bingin closing out", spots) == ["uluwatu", "bingin"]
assert R.find_spots("padang padang firing", spots) == ["padang-padang"]
assert R.find_spots("impossible was firing", spots) == ["impossibles"]
assert R.find_spots("Batu Bolong mushy, then Uluwatu", spots) == ["canggu", "uluwatu"]
assert R.find_spots("nothing here, not even a kutapang", spots) == [], "kuta inside another word is not Kuta"
print("  find_spots: ids, names and aliases, whole words, in the order said")

text = "🌊 Surf could be good tomorrow:\n• Uluwatu 5–12: 1.5 m at 12 s …\n• Keramas 6–9: 1.6 m …\n\nIf you go…"
assert R.windows_in(text, spots) == {"uluwatu": (5, 12), "keramas": (6, 9)}
print("  windows_in: each named spot's window, from the alert text")

alerts = [{"id": 812, "ts": "2026-10-27T17:00:03+08:00", "rule_id": "surf/surf_tomorrow", "text": text},
          {"id": 813, "ts": "2026-10-28T17:00:02+08:00", "rule_id": "surf/surf_tomorrow", "text": "• Uluwatu 6–8: …"},
          {"id": 700, "ts": "2026-10-27T09:00:00+08:00", "rule_id": "heat/hot_night", "text": "hot"}]
actions = [{"ts": "2026-10-28T11:00:00+08:00", "alert_id": 812, "stage": "acted", "actor": "tomas/telegram",
            "note": "Ulu good, Green Bowl flat"},
           {"ts": "2026-10-27T10:00:00+08:00", "alert_id": 700, "stage": "acted", "actor": "x", "note": "fan on"}]
j = R.journal(alerts, actions, spots, fetch_day)
assert set(j) == {"uluwatu", "green-bowl", "unanswered"}, set(j)
(u,) = j["uluwatu"]
assert u["date"] == "2026-10-28" and u["note"] == "Ulu good, Green Bowl flat" and u["alert_id"] == 812, u
assert [h["hr"] for h in u["hours"]] == list(range(5, 13)), "the window the message named"
day = fetch_day(spots["uluwatu"], "2026-10-28")
for h in u["hours"]:
    raw = day[h["hr"]]
    assert abs(h["kw"] - S.power(raw["h1"], raw["t1"])) < 1e-9, (h, raw)
    assert h["tide"] in ("low", "mid", "high")
(g,) = j["green-bowl"]
assert [h["hr"] for h in g["hours"]] == list(range(6, 11)), "a spot the message did not name: 06 to 10"
assert [a["alert_id"] for a in j["unanswered"]] == [813], j["unanswered"]
assert ("uluwatu", "2026-10-28") in asked and all(d == "2026-10-28" for _, d in asked), asked
print("  journal: the morning after the alert, the named window or 06-10, power per hour, the unanswered call")

out = R.render(j, spots)
assert out.index("Uluwatu") < out.index("Green Bowl") and "Ulu good, Green Bowl flat" in out and "#813" in out, out


def flaky(spot, date):
    if spot["id"] == "green-bowl":
        raise TimeoutError("archive timed out")
    return fetch_day(spot, date)


j = R.journal(alerts, actions, spots, flaky)
assert [h["hr"] for h in j["uluwatu"][0]["hours"]] == list(range(5, 13)), "one failed fetch does not take the others"
assert j["green-bowl"][0]["hours"] == [] and "timed out" in j["green-bowl"][0]["error"], j["green-bowl"]
assert "numbers not fetched" in R.render(j, spots)
print("  a failed archive fetch is shown on its own spot, the rest of the journal stands")

import contextlib  # noqa: E402
import io  # noqa: E402

R._get = lambda url, params=None: ([{"id": i, "ts": "2026-10-27T17:00:00+08:00", "rule_id": "heat/x", "text": ""}
                                    for i in range(1000)] if url.endswith("/alerts") else [])
err = io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
    R.main(["--days", "60"])
assert "1000" in err.getvalue() and "--days" in err.getvalue(), err.getvalue()
print("  a full page of alerts says older calls may be missing")
# --- v1.1: the two-day message, and button answers ---
def _a(window, runs, inside=True, kw=20):
    return {"good": True, "runs": runs, "window": window, "inside": inside, "second": None, "kw": kw, "wind": 5.0,
            "wdir": None, "tide": "mid", "swell": {"h": 1.5, "t": 12.0, "dir": 180.0, "kw": kw}}


def v11(locale="en", comfort=15):
    day1 = [(spots["uluwatu"], _a((9, 10), [(5, 11)])), (spots["keramas"], _a((5, 8), [(5, 8)], inside=False, kw=30))]
    day2 = [(spots["uluwatu"], _a((14, 15), [(13, 16)]))]
    return S.message([("2026-10-28", day1), ("2026-10-29", day2)], locale, comfort, True) + " /act 812 <your words>"


for loc in ("en", "es", "id"):
    t = v11(loc)
    assert R.windows_in(t, spots) == {"uluwatu": (9, 10), "keramas": (5, 8)}, (loc, R.windows_in(t, spots), t)
# the text as the pack prints it: runs end-exclusive, "HH:00–HH:00", like the best window
T11 = ("🌊 Surf in the next two days\n\nWednesday 4 Nov\n"
       "• Uluwatu, best 09:00–11:00 (good 05:00–12:00)\n  waves 1.0 m every 13 s, from the SSW\n"
       "• Keramas, good 05:00–09:00, 16:00–18:00, outside your hours\n  waves 1.0 m every 13 s, from the S\n\n"
       "Thursday 5 Nov\n• Uluwatu, best 14:00–16:00 (good 13:00–17:00)")
assert R.windows_in(T11, spots) == {"uluwatu": (9, 10), "keramas": (5, 8)}, R.windows_in(T11, spots)
none = S.message([("2026-10-28", []), ("2026-10-29", [(spots["uluwatu"], _a((9, 10), [(5, 11)]))])], "en", 15, True)
assert R.windows_in(none, spots) == {}, "day 2 is not tomorrow"
print("  windows_in: v1.1 first day block only, en/es/id, best and outside-hours lines")

T = v11()
al = [{"id": 900, "ts": "2026-10-27T17:00:00+08:00", "rule_id": "surf/surf_tomorrow", "text": T},
      {"id": 901, "ts": "2026-10-28T17:00:00+08:00", "rule_id": "surf/surf_tomorrow", "text": T},
       {"id": 902, "ts": "2026-10-29T17:00:00+08:00", "rule_id": "surf/surf_tomorrow", "text": T},
       {"id": 903, "ts": "2026-10-30T17:00:00+08:00", "rule_id": "surf/surf_tomorrow", "text": T}]
ac = [{"alert_id": 900, "stage": "acted", "actor": "t/tg", "note": "head high, crowded", "choice": "uluwatu:good"},
      {"alert_id": 901, "stage": "acknowledged", "actor": "t/tg", "note": None, "choice": "didnt-go"},
      {"alert_id": 902, "stage": "acted", "actor": "t/tg", "note": "went to Green Bowl, fun", "choice": "elsewhere"},
      {"alert_id": 903, "stage": "acted", "actor": "t/tg", "note": None, "choice": "keramas:poor"}]
j = R.journal(al, ac, spots, fetch_day)
assert set(j) == {"uluwatu", "green-bowl", "keramas"}, set(j)
(u,) = j["uluwatu"]
assert u["rating"] == "good" and u["note"] == "head high, crowded" and u["alert_id"] == 900, u
assert [h["hr"] for h in u["hours"]] == [9, 10], "tomorrow's window, not day 2's 14-15"
assert j["green-bowl"][0]["note"] == "went to Green Bowl, fun" and j["green-bowl"][0]["alert_id"] == 902
(k,) = j["keramas"]
assert k["rating"] == "poor" and k["note"] == "" and [h["hr"] for h in k["hours"]] == list(range(5, 9)), k
assert "unanswered" not in j and not any(e["alert_id"] == 901 for v in j.values() for e in v), "didnt-go: answered, no spot"
out = R.render(j, spots)
assert "2026-10-28 👍" in out and "2026-10-31 👎" in out, out
print("  journal: button answers file under their spot with a rating; didnt-go answers the call, files nothing")

j = R.journal(al[:1], [{"alert_id": 900, "stage": "acted", "actor": "t", "note": "somewhere nobody knows", "choice": "elsewhere"}],
              spots, fetch_day)
assert list(j) == ["elsewhere"] and j["elsewhere"][0]["hours"] == [], j
assert "Elsewhere" in R.render(j, spots) and "somewhere nobody knows" in R.render(j, spots)
j = R.journal(al[:1], [{"alert_id": 900, "stage": "acted", "actor": "t", "note": "Ulu fun", "choice": None}], spots, fetch_day)
assert j["uluwatu"][0]["rating"] is None and [h["hr"] for h in j["uluwatu"][0]["hours"]] == [9, 10], "v1.1 text, typed /act note"
print("  elsewhere with no spot named files under elsewhere; a typed note on v1.1 text still works")

R._get = lambda url, params=None: (seen.append((url, params)) or ([] if url.endswith("/alerts") else []))
seen = []
with contextlib.redirect_stdout(io.StringIO()):
    R.main(["--days", "5"])
assert [p for u, p in seen if u.endswith("/actions")] == [{"limit": 5000}], seen
print("  main asks /actions without a stage filter")
print("surf review: all checks passed")
