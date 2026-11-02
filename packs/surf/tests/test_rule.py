"""surf_tomorrow's SQL on synthetic rows in DuckDB, in Bali time (needs `pip install duckdb`; skipped without it). The
rule's now() is replaced by a fixed instant, so 16:05 and 17:05 can both be asked. DuckDB is not PostgreSQL, but
everything the SQL uses (row_number, FILTER, date_trunc on a timestamptz, ->>, chr, string_agg ... ORDER BY) means
the same in both. Run: python3 packs/surf/tests/test_rule.py
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


def run(now, rows):
    """now: local 'YYYY-MM-DD HH:MM'. rows: (local ts, spot, good, kw)."""
    c = duckdb.connect()
    c.execute("SET TimeZone = 'Asia/Makassar'")
    c.execute("CREATE TABLE readings(ts TIMESTAMPTZ, sensor_id TEXT, metric TEXT, value DOUBLE)")
    c.execute("CREATE TABLE sensors(sensor_id TEXT, meta JSON)")
    for spot in {r[1] for r in rows}:
        c.execute("INSERT INTO sensors VALUES (?, ?)", [f"surf-{spot}", json.dumps(
            {k: f"• {spot} ({k})" for k in ("line_en", "line_es", "line_id")})])
    for ts, spot, good, kw in rows:
        for m, v in (("surf_good", good), ("surf_kw", kw)):
            c.execute("INSERT INTO readings VALUES (CAST(? AS TIMESTAMPTZ), ?, ?, ?)", [ts + ":00+08", f"surf-{spot}", m, v])
    sql = R["sql"].replace("now()", f"TIMESTAMPTZ '{now}:00+08'")
    cur = c.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


FOUR = [("2026-11-02 15:00", s, 1, kw) for s, kw in (("ulu", 14), ("keramas", 22), ("bingin", 6), ("sanur", 9))]
out = run("2026-11-02 17:05", FOUR)
assert len(out) == 1 and out[0]["sensor_id"] == "surf", out
assert out[0]["lines_en"].split("\n") == ["• keramas (line_en)", "• ulu (line_en)", "• sanur (line_en)"], out
assert out[0]["lines_es"].startswith("• keramas (line_es)") and out[0]["lines_id"].startswith("• keramas (line_id)")
print("  17:05: one row, the top three by power, each locale's lines")

assert run("2026-11-02 16:05", FOUR) == [], "only at 17:00"
assert run("2026-11-02 17:05", [("2026-11-02 15:00", "ulu", 0, 0)]) == [], "nothing good, nothing sent"
assert run("2026-11-02 17:05", [("2026-11-01 15:00", "ulu", 1, 14)]) == [], "yesterday's rows are not tomorrow's surf"
out = run("2026-11-02 17:05", [("2026-11-02 12:00", "ulu", 1, 14), ("2026-11-02 15:00", "ulu", 0, 0),
                               ("2026-11-02 15:00", "keramas", 1, 9)])
assert out and out[0]["lines_en"] == "• keramas (line_en)", "the newest fetch wins"
assert run("2026-11-02 17:05", [("2026-11-02 18:00", "ulu", 1, 14)]) == [], "nothing from after now"
print("  16:05, nothing good, yesterday's rows, a later fetch that is not good, rows from the future: no row")

returned = {"sensor_id", "lines_en", "lines_es", "lines_id"}
for loc, tmpl in R["message"].items():
    ph = set(re.findall(r"\{(\w+)", tmpl))
    assert ph <= returned | {"act"} and "act" in ph and f"lines_{loc}" in ph, (loc, ph)
print("  every placeholder is a column or {act}, and each locale asks for an answer")
print("surf rule: all checks passed")
