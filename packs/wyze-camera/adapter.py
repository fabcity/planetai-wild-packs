"""wyze-camera: Wyze cameras through docker-wyze-bridge. Records motion events and saves snapshots in out/wyze-camera,
and gives the node nothing: no sensors and no readings, so none of it reaches the database, the daily export, the
upstream aggregates or any API (see README.md and docs/superpowers/specs/2026-10-03-wyze-camera-pack-design.md).

Contract: fetch(hc) -> (sensors, readings), like everything in app/sources.py. The node runs this file afresh at every
poll, so nothing is kept in memory between polls: what must last is in out/wyze-camera/state.json."""
from __future__ import annotations

import sys
import time
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from wyzecam import config  # noqa: E402
from wyzecam.bridge import Bridge  # noqa: E402
from wyzecam.roles import ROLES, new_context  # noqa: E402
from wyzecam.store import Store  # noqa: E402


def fetch(hc):
    cfg = config.load()
    if not cfg.ready:
        config.say_once("wyze-camera: idle until WYZE_BRIDGE_URL and WYZE_CAMERAS are set")
        return [], []
    store = Store(cfg.out)
    ctx = None
    try:
        ctx = new_context(cfg, Bridge(hc, cfg.url, cfg.token), store, time.time())
        for name in cfg.roles:
            ROLES[name](ctx)
        # Every poll, whichever roles ran: keep_days and the size cap hold even when nothing new is written.
        store.prune_events(cfg.keep_days, ctx["now"])
        store.prune_images(cfg.keep_days, cfg.snap_max_mb, ctx["now"])
    except OSError:
        raise RuntimeError("wyze-camera: could not write to its output folder") from None
    finally:
        if ctx:
            try:
                store.save_state(ctx["state"])
            except OSError:
                raise RuntimeError("wyze-camera: could not write to its output folder") from None
    failures = ctx["failures"]
    if failures and not ctx["answered"]:
        # A message the node's status shows, which can be seen beyond this machine: reasons only, never a name.
        raise RuntimeError(f"wyze-camera: {len(failures)} of {len(failures)} request(s) failed: {failures[0]}")
    if failures:
        config.log.warning("wyze-camera: %d request(s) failed this poll: %s", len(failures),
                           "; ".join(sorted(set(failures))))
    return [], []
