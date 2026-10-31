"""Re-run a published test on a box, from nothing, and compare.  planetai run paddy reproduce --box W,S,E,N ...

    planetai run paddy reproduce --box 115.09,-8.71,115.23,-8.61 --flood off --end 2026-10 \\
        --expect-rice 1420 --expect-lost 25-40

That is the Canggu to Pemogan strip of 30 Oct 2026, where 1,420 ha cycled as rice and 25 to 40 ha went from green to
bare or built. It reads every scene of 25 months over the box, several GB, into out/paddy-reproduce/, and leaves
the node's own square alone. Not open to agents, for that reason.
"""
import argparse
import logging
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
import httpx                                                                     # noqa: E402

import adapter as A                                                              # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--box", required=True, help="west,south,east,north")
ap.add_argument("--flood", choices=("on", "off"), required=True)
ap.add_argument("--end", help="the last month, YYYY-MM; default this month")
ap.add_argument("--expect-rice", type=float, help="hectares of rice; passes within 10 %%")
ap.add_argument("--expect-lost", help="lo-hi hectares lost")
a = ap.parse_args()
logging.basicConfig(level=logging.INFO, format="%(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)       # one line per range request, token and all

g = A.box(*(float(v) for v in a.box.split(",")))
flood = a.flood == "on"
now = datetime.now(timezone.utc)
if a.end:
    y, m = (int(v) for v in a.end.split("-"))
    now = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=timezone.utc).replace(microsecond=0) - A.timedelta(seconds=1)
r = A.Path(os.getenv("PACK_OUT", "/app/out")) / "paddy-reproduce" / a.box.replace(",", "_")
with httpx.Client(timeout=120, headers={"User-Agent": "planetai-node paddy"}) as hc:
    state, _ = A.step(hc, r, g, flood, now, per_day=float("inf"), per_call=float("inf"))
(r / "backfill.lock").unlink(missing_ok=True)
s, cell = A.compute(r, g, flood, now)
print(", ".join(f"{k} {s[f'{k}_ha']:,.1f} ha" for k in A.STATES), f"| months {s['months_read']}, scenes waiting {len(state['todo'])}")
fails = []
if a.expect_rice is not None and abs(s["rice_ha"] - a.expect_rice) > 0.1 * a.expect_rice:
    fails.append(f"rice {s['rice_ha']:,.0f} ha, expected {a.expect_rice:,.0f} within 10 %")
if a.expect_lost:
    lo, hi = (float(v) for v in a.expect_lost.split("-"))
    if not lo <= s["lost_ha"] <= hi:
        fails.append(f"lost {s['lost_ha']:,.1f} ha, expected {lo:g} to {hi:g}")
print("\n".join(f"  ✗ {f}" for f in fails) or "  ✓ as published")
sys.exit(1 if fails else 0)
