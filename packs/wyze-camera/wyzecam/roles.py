"""What the pack does with the cameras: one role per job, on the same camera list and bridge client (spec section 1).
A later use (a visibility reading, proof that an alert was acted on) is a new role here, not a change to these. The
core Frigate and CCTV feature is to carry the same roles, so a role means the same thing whichever camera serves it.

Each role takes the poll's context and returns nothing. `motion` leaves the poll's new events in ctx["new_motion"]
for the roles after it. A role changes ctx["state"]; the adapter saves it once, after every role has run."""
from __future__ import annotations

from .bridge import BridgeError
from .store import iso


def new_context(cfg, bridge, store, now: float) -> dict:
    return {"cfg": cfg, "bridge": bridge, "store": store, "state": store.load_state(), "now": now,
            "failures": [], "answered": 0, "new_motion": []}


def motion(ctx: dict) -> None:
    cfg, state, now = ctx["cfg"], ctx["state"], ctx["now"]
    new, seen = [], {}
    for cam in cfg.cameras:
        try:
            ts = ctx["bridge"].motion_ts(cam)
        except BridgeError as e:
            ctx["failures"].append(str(e))
            continue
        ctx["answered"] += 1
        last = state["motion"].get(cam)
        if last is None:
            state["motion"][cam] = ts             # the first look is a starting point, never an event
        elif ts > last:
            new.append({"camera": cam, "motion_at": iso(ts), "seen_at": iso(now)})
            seen[cam] = ts
    if new:
        ctx["store"].add_events(new, cfg.keep_days, now)
    state["motion"].update(seen)              # only once the log has them: a failed write is retried, not lost
    ctx["new_motion"] = new


def _save(ctx: dict, cam: str, kind: str, trigger: str, fallback: tuple[str, str] | None = None) -> bool:
    try:
        data = ctx["bridge"].image(cam, kind)
    except BridgeError as e:
        if fallback:
            return _save(ctx, cam, fallback[0], fallback[1])
        ctx["failures"].append(str(e))
        return False
    ctx["answered"] += 1
    ctx["store"].save_image(cam, data, trigger, ctx["now"])
    return True


def snapshots(ctx: dict) -> None:
    cfg, state, now = ctx["cfg"], ctx["state"], ctx["now"]
    moved = {e["camera"] for e in ctx.get("new_motion", [])}
    for cam in cfg.cameras:
        if cfg.snap_on_motion and cam in moved:
            _save(ctx, cam, "thumb", "motion", fallback=("snapshot", "motion-at-poll"))
        if cfg.snap_every_min and now - state["schedule"].get(cam, 0) >= cfg.snap_every_min * 60:
            if _save(ctx, cam, "snapshot", "schedule"):
                state["schedule"][cam] = now


ROLES = {"motion": motion, "snapshots": snapshots}
