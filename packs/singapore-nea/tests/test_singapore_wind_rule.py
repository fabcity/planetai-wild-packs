"""The wind_southeast_rising rule's SQL, run against synthetic readings in DuckDB (needs `pip install duckdb`; skipped
without it). DuckDB is not PostgreSQL, but the constructs used here (FILTER, interval, coalesce, scalar subqueries) mean
the same in both. Run: python3 packs/singapore-nea/tests/test_singapore_wind_rule.py
"""
import datetime as dt

import yaml

try:
    import duckdb
except ImportError:
    print("singapore wind rule: skipped (no duckdb)"); raise SystemExit(0)

rules = {r["id"]: r for r in yaml.safe_load(open("packs/singapore-nea/rules.yml", encoding="utf-8"))}
SQL = rules["wind_southeast_rising"]["sql"]


def run(dirs, spds, minutes=10):
    c = duckdb.connect()
    c.execute("create table readings(ts timestamptz, sensor_id text, metric text, value double)")
    c.execute("create table observations(sensor_id text, metric text, value double)")
    c.execute("insert into observations values ('nea-pm25','pm25',31),('nea-psi','psi',82)")
    now = dt.datetime.now(dt.timezone.utc)
    for i, (d, s) in enumerate(zip(dirs, spds)):            # i = 0 is the newest reading
        t = now - dt.timedelta(minutes=minutes * i + 2)
        c.execute("insert into readings values (?,?,?,?)", [t, "nea-winddir", "wind_dir", d])
        c.execute("insert into readings values (?,?,?,?)", [t, "nea-windspeed", "wind_speed", s])
    return c.execute(SQL).fetchall()


N = 18
UP = [10 if i < 9 else 6 for i in range(N)]      # newest 90 min at 10 kt, the 90 before at 6 kt
DOWN = [6 if i < 9 else 10 for i in range(N)]
assert run([135] * N, UP) == [("nea-winddir", 10.0, 6.0, 31.0, 82.0)], "south-east, sustained and rising, fires"
assert run([135] * N, DOWN) == [], "a falling south-east wind is not the pattern"
assert run([135] * N, [8] * N) == [], "steady is not rising"
assert run([135] * 12 + [300] * 6, UP) == [], "only 2/3 of the readings in the sector: not sustained"
assert run([135] * 16 + [300] * 2, UP) != [], "16 of 18 (89%) is sustained"
assert run([168] * N, UP) != [] and run([169] * N, UP) == [] and run([101] * N, UP) == [] and run([102] * N, UP) != [], "ESE to SSE is 101.25 to 168.75"
assert run([112] * N, UP) != [] and run([158] * N, UP) != [], "east-south-east and south-south-east count"
assert run([90] * N, UP) == [] and run([180] * N, UP) == [], "due east and due south do not"
assert run([135] * 8, UP[:8]) == [], "fewer than 12 readings: too little to call it sustained"
assert run([225] * N, UP) == [], "south-west is a different pattern"

# ---------------------------------------------------------------- wind_pm25_correlated: PM2.5 moving with the south-east wind
import math

CORR = rules["wind_pm25_correlated"]["sql"]


def run_corr(wind_at, pm_at, hours=6, local=True, indoor=False, kind="sensor", now_offset_min=2):
    """wind_at(h) and pm_at(h): the value h hours ago (0 = now). Wind every 10 minutes, PM2.5 every 5."""
    c = duckdb.connect()
    c.execute("create table sensors(sensor_id text, kind text, local boolean, indoor boolean)")
    c.execute("create table readings(ts timestamptz, sensor_id text, metric text, value double)")
    c.execute("insert into sensors values ('sc-1', ?, ?, ?), ('nea-winddir','model',false,false)", [kind, local, indoor])
    now = dt.datetime.now(dt.timezone.utc)
    for m in range(now_offset_min, int(hours * 60), 5):
        t = now - dt.timedelta(minutes=m)
        c.execute("insert into readings values (?,?,?,?)", [t, "sc-1", "pm25", pm_at(m / 60)])
        if m % 10 in (now_offset_min % 10, (now_offset_min + 5) % 10) and (m - now_offset_min) % 10 == 0:
            c.execute("insert into readings values (?,?,?,?)", [t, "nea-winddir", "wind_dir", wind_at(m / 60)])
    return c.execute(CORR).fetchall()


def swing(h):        # wind backs from the north-west (315) to the south-east (135) across six hours
    return 135 + 180 * min(1.0, max(0.0, (h - 0.0) / 6.0))


def climb(h):        # PM2.5 climbs from 15 to 50 as the wind arrives
    return 15 + 35 * (1 - min(1.0, h / 6.0))


hit = run_corr(swing, climb)
assert len(hit) == 1 and hit[0][1] > 0.9 and hit[0][2] >= 10 and hit[0][3] > hit[0][4] + 3, hit
assert run_corr(swing, lambda h: 40) == [], "PM2.5 flat: nothing rising, nothing to say"
assert run_corr(lambda h: 135, climb) == [], "a steady wind has nothing to correlate with"
assert run_corr(lambda h: 135 + 4 * math.sin(h * 40), climb) == [], "a wobble of a few degrees is not a swing, whatever r says"
assert run_corr(lambda h: 135 + 180 * (1 - min(1.0, h / 6.0)), climb) == [], "PM2.5 rising as the wind leaves the south-east: negative"
assert run_corr(swing, lambda h: 15 + 35 * min(1.0, h / 6.0)) == [], "PM2.5 falling as the wind arrives: no"
assert run_corr(swing, lambda h: 8 + 5 * (1 - min(1.0, h / 6.0))) == [], "rising but under 15 ug/m3 (the WHO line): no"
assert run_corr(swing, climb, hours=2) == [], "two hours is too few half-hour buckets"
assert run_corr(swing, climb, local=False) == [] and run_corr(swing, climb, indoor=True) == [] and run_corr(swing, climb, kind="model") == [], \
    "only this node's own outdoor sensor counts"
assert math.isclose(math.cos(math.radians(135 - 135)), 1.0) and math.cos(math.radians(315 - 135)) < -0.99
print("singapore wind rule: ok")
