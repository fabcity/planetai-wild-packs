"""Check the kept square, the rule and the node, and say which line failed.  planetai run paddy verify

Reads nothing from the network. Four checks: the keeper's settings, what is kept on disk describes that square, the
six states add up to every pixel of it, and the readings reached the database.
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
import adapter as A                                                              # noqa: E402

fails = []


def step(n, ok, msg):
    print(f"  {'✓' if ok else '✗'} {n}: {msg}")
    if not ok:
        fails.append(f"{n}: {msg}")


g, flood, why = A.settings()
step(1, g is not None, why or f"a {2 * g['radius_km']:g} km square around {g['lat']:.4f},{g['lon']:.4f}, "
                              f"flood check {'on' if flood else 'off'}")
if g is None:
    sys.exit(1)

r, now = A.root(), datetime.now(timezone.utc)
state = A.load_state(r)
key = {k: g[k] for k in ("epsg", "x0", "y0", "w", "h")} | {"flood": flood}
months = [k for k in A.month_keys(now) if (r / "months" / f"{k}.bin").exists()]
step(2, state.get("square") == key and bool(months),
     f"{len(months)} of {A.MONTHS} months kept, {len(state.get('todo') or [])} scenes waiting"
     if state.get("square") == key else "nothing kept for this square yet: wait for a poll, or planetai run paddy backfill")

if months and state.get("square") == key:
    try:
        s, cell = A.compute(r, g, flood, now)
        step(3, True, ", ".join(f"{k} {s[f'{k}_ha']:,.1f} ha" for k in A.STATES) + (f"; most lost land in {cell}" if cell else ""))
    except AssertionError as e:
        step(3, False, str(e))

try:
    import psycopg
    with psycopg.connect(os.environ["DATABASE_URL"]) as con, con.cursor() as cur:
        cur.execute("SELECT DISTINCT ON (metric) metric, value, ts FROM readings WHERE sensor_id = %s "
                    "ORDER BY metric, ts DESC", (A.SENSOR,))
        rows = cur.fetchall()
    step(4, bool(rows), ", ".join(f"{m} {v:g} ({ts:%Y-%m-%d})" for m, v, ts in rows) if rows else
         "no paddy-square rows yet: is paddy in PACKS_ENABLED, PACKS_ALLOW_CODE=1, and has the node polled since?")
except Exception as e:  # noqa: BLE001
    step(4, False, f"the database did not answer ({type(e).__name__})")

print(f"\n{A.attribution(months)}")
sys.exit(1 if fails else 0)
