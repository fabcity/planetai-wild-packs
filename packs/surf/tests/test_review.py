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
WHERE = {"uluwatu": 0, "green-bowl": 1}
asked = []


def fetch_day(spot, date):
    asked.append((spot["id"], date))
    i = WHERE[spot["id"]]
    return S.day_rows(FX["swell"][i], FX["tide"][i], FX["wind"][i], date)


assert R.find_spots("Ulu good, Bingin closing out", spots) == ["uluwatu", "bingin"]
assert R.find_spots("padang padang firing", spots) == ["padang-padang"]
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
print("surf review: all checks passed")
