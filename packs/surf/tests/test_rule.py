"""surf_tomorrow's SQL on a synthetic summary row in DuckDB, in Bali time (needs `pip install duckdb`; skipped without
it). The rule's now() is replaced by a fixed instant, so 16:05 and 17:05 can both be asked. DuckDB is not PostgreSQL,
but everything the SQL uses (->>, CAST of a timestamptz to a date and to text, extract) reads the session time zone
the same way in both. Run: python3 packs/surf/tests/test_rule.py
"""
import json
import re
from pathlib import Path

import yaml

try:
    import duckdb
except ImportError:
    print("surf rule: skipped (no duckdb)"); raise SystemExit(0)

HERE = Path(__file__).resolve().parent
rules = {r["id"]: r for r in yaml.safe_load((HERE.parent / "rules.yml").read_text())}
R = rules["surf_tomorrow"]
assert (R["level"], R["cooldown_minutes"]) == ("warn", 720), R

BUTTONS = json.dumps([[{"text": {"en": "I went", "es": "Fui", "id": "Saya pergi"}, "value": "went"}]])


def meta(fetched="2026-11-02", any_="1"):
    t = {loc: f"Tomorrow {loc}.\nSurf could be good at Keramas.\nA model screen, not a surf report. Tell me:" for loc in ("en", "es", "id")}
    return {"fetched": fetched, "any": any_, "buttons": BUTTONS, **{f"text_{k}": v for k, v in t.items()}}


def run(now, m):
    """now: 'YYYY-MM-DD HH:MM' in Bali time (+08). m: the summary sensor's meta."""
    c = duckdb.connect()
    c.execute("SET TimeZone = 'Asia/Makassar'")
    c.execute("CREATE TABLE sensors(sensor_id TEXT, meta JSON)")
    c.execute("INSERT INTO sensors VALUES ('surf', ?)", [json.dumps(m)])
    c.execute("INSERT INTO sensors VALUES ('surf-ulu', ?)", [json.dumps({"fetched": "2026-11-02", "any": "1"})])
    cur = c.execute(R["sql"].replace("now()", f"TIMESTAMPTZ '{now}:00+08'"))
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


out = run("2026-11-02 17:05", meta())
assert len(out) == 1 and out[0]["sensor_id"] == "surf", out
assert out[0]["buttons"] == BUTTONS and out[0]["text_en"] == meta()["text_en"], out
assert out[0]["text_es"] == meta()["text_es"] and out[0]["text_id"] == meta()["text_id"], out
print("  17:05, fetched today: one row, the summary's three texts and its buttons, untouched")

assert run("2026-11-02 16:05", meta()) == [], "only at 17:00"
assert run("2026-11-02 17:05", meta(fetched="2026-11-01")) == [], "the node was down: yesterday's summary is not tomorrow's surf"
assert run("2026-11-02 17:05", meta(any_="0")) == [], "nothing good, nothing sent"
print("  16:05, a summary from yesterday, any = 0: no row")

# The rule fires at 17, where Bali and UTC share a date, so the zone cannot show there. Move the hour test to 0 and
# ask at 00:30 on 3 Nov in Bali, which is still 2 Nov in UTC: "fetched today" must mean 3 Nov.
night = {**R, "sql": R["sql"].replace("= 17", "= 0")}
assert night["sql"] != R["sql"]


def at_night(m):
    c = duckdb.connect()
    c.execute("SET TimeZone = 'Asia/Makassar'")
    c.execute("CREATE TABLE sensors(sensor_id TEXT, meta JSON)")
    c.execute("INSERT INTO sensors VALUES ('surf', ?)", [json.dumps(m)])
    return c.execute(night["sql"].replace("now()", "TIMESTAMPTZ '2026-11-03 00:30:00+08'")).fetchall()


assert len(at_night(meta(fetched="2026-11-03"))) == 1, "3 Nov is today in the session's zone"
assert at_night(meta(fetched="2026-11-02")) == [], "2 Nov is the UTC date, not the session's"
print("  at 00:30 +08 (2 Nov in UTC) 'today' is 3 Nov, the session's zone")

returned = {"sensor_id", "text_en", "text_es", "text_id", "buttons"}
assert set(run("2026-11-02 17:05", meta())[0]) == returned
for loc, tmpl in R["message"].items():
    ph = set(re.findall(r"\{(\w+)", tmpl))
    assert ph == {f"text_{loc}", "act"}, (loc, ph)
    assert tmpl.startswith(f"{{text_{loc}}} {{act}} "), tmpl
print("  each message is its text, then {act}, then a few words, and every placeholder is a column or {act}")
print("surf rule: all checks passed")
