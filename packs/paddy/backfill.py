"""Read the keeper's whole 25 months now, instead of PADDY_READS scenes a day.  planetai run paddy backfill

A 3 km square on node #1 took 18 minutes: 95 scenes, about 0.35 GB. A 10 km square is about ten times that. It can be stopped and run again:
every scene read is remembered, and the poll carries on from where it stopped. The hectares appear at the next poll.
"""
import logging
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
import httpx                                                                     # noqa: E402

import adapter as A                                                              # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)       # one line per range request, token and all
g, flood, why = A.settings()
if g is None:
    print(f"paddy: {why}")
    sys.exit(1)
t0 = time.time()
with httpx.Client(timeout=120, headers={"User-Agent": "planetai-node paddy"}) as hc:
    state, _ = A.step(hc, A.root(), g, flood, datetime.now(timezone.utc), per_day=float("inf"), per_call=float("inf"))
(A.root() / "backfill.lock").unlink(missing_ok=True)
months = sum(1 for k in A.month_keys(datetime.now(timezone.utc)) if (A.root() / "months" / f"{k}.bin").exists())
print(f"paddy: {months} of {A.MONTHS} months hold a clear look, {len(state['todo'])} scenes still waiting, "
      f"{(time.time() - t0) / 60:.0f} min")
