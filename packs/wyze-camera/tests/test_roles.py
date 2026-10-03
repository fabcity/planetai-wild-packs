"""wyzecam.roles: what the pack does with the cameras, one role per job.
Run from a node's folder: python3 packs/wyze-camera/tests/test_roles.py"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fakes import FakeBridge, setup  # noqa: E402
from wyzecam import config  # noqa: E402
from wyzecam.bridge import NO_IMAGE, UNKNOWN, Bridge  # noqa: E402
from wyzecam.roles import ROLES, new_context  # noqa: E402
from wyzecam.store import Store, iso  # noqa: E402

T = 1759475565.0


def poll(fb, env, now, state=None):
    """One poll through the roles WYZE_ROLES lists, the way the adapter runs them, sharing one store."""
    os.environ.update(env)
    cfg = config.load()
    store = Store(cfg.out)
    ctx = new_context(cfg, Bridge(fb, cfg.url, cfg.token), store, now)
    if state is not None:
        ctx["state"] = state
    for name in cfg.roles:
        ROLES[name](ctx)
    store.save_state(ctx["state"])
    return ctx, store


BASE = {"WYZE_BRIDGE_URL": "http://10.0.0.2:5000", "WYZE_CAMERAS": "kitchen,porch"}
setup(dict(BASE))
fb = FakeBridge({"kitchen": T - 3600, "porch": 0})
ctx, store = poll(fb, {}, T)
assert store.events() == [] and ctx["state"]["motion"] == {"kitchen": T - 3600, "porch": 0.0}, ctx["state"]
assert ctx["answered"] == 2 and ctx["failures"] == []
print("  the first look at each camera is a starting point, never an event")

fb.motion["kitchen"] = T + 10
ctx, store = poll(fb, {}, T + 300)
assert store.events() == [{"camera": "kitchen", "motion_at": iso(T + 10), "seen_at": iso(T + 300)}], store.events()
assert ctx["new_motion"] == store.events()
ctx, store = poll(fb, {}, T + 600)
assert len(store.events()) == 1 and ctx["new_motion"] == []
print("  newer motion is logged once, with Wyze's time and the node's, and not again on the next poll")

fb.motion["porch"] = T + 500
ctx, store = poll(fb, {}, T + 900)
assert [e["camera"] for e in store.events()] == ["kitchen", "porch"]
print("  each camera keeps its own last time")

del fb.motion["porch"]
ctx, store = poll(fb, {}, T + 1200)
assert ctx["failures"] == [UNKNOWN] and ctx["answered"] == 1
print("  a camera the bridge does not know is a failure for that camera only")

# snapshots: off by default, on motion with Wyze's thumbnail, falling back to a still labelled as taken at poll time
setup(dict(BASE, WYZE_ROLES="motion,snapshots"))
fb = FakeBridge({"kitchen": 0, "porch": 0})
poll(fb, {}, T)
fb.motion["kitchen"] = T + 5
ctx, store = poll(fb, {}, T + 300)
assert store.images() == [], "WYZE_SNAPSHOT_ON_MOTION is 0: nothing saved"
os.environ["WYZE_SNAPSHOT_ON_MOTION"] = "1"
fb.motion["kitchen"] = T + 400
ctx, store = poll(fb, {}, T + 600)
assert [p.name.split("-", 1)[1] for p in store.images()] == ["motion.jpg"] and store.images()[0].read_bytes() == b"JPEG thumb kitchen"
fb.thumb = False
fb.motion["kitchen"] = T + 700
ctx, store = poll(fb, {}, T + 900)
assert sorted(p.name.split("-", 1)[1] for p in store.images()) == ["motion-at-poll.jpg", "motion.jpg"]
print("  on motion it saves Wyze's own event image, or a still labelled as taken at poll time")

fb.snapshot = False
fb.motion["kitchen"] = T + 1000
ctx, store = poll(fb, {}, T + 1200)
assert ctx["failures"] == [NO_IMAGE] and len(store.images()) == 2
print("  with no image at all, that is a failure, and nothing is written")

# the schedule, honoured across polls through state
setup(dict(BASE, WYZE_ROLES="snapshots", WYZE_SNAPSHOT_EVERY="15"))
fb = FakeBridge({"kitchen": 0, "porch": 0})
ctx, store = poll(fb, {}, T)
assert len(store.images()) == 2 and ctx["state"]["schedule"] == {"kitchen": T, "porch": T}
ctx, store = poll(fb, {}, T + 600)
assert len(store.images()) == 2, "ten minutes is not fifteen"
ctx, store = poll(fb, {}, T + 900)
assert len(store.images()) == 4 and ctx["state"]["motion"] == {}, "the motion role was not listed, so it did not run"
print("  scheduled stills honour the interval across polls; a role not listed does not run")

setup(dict(BASE, WYZE_ROLES="motion", WYZE_SNAPSHOT_EVERY="15", WYZE_SNAPSHOT_ON_MOTION="1"))
fb = FakeBridge({"kitchen": 0, "porch": 0})
poll(fb, {}, T)
fb.motion["kitchen"] = T + 5
ctx, store = poll(fb, {}, T + 1000)
assert store.images() == [] and len(store.events()) == 1
print("  with the snapshots role off, no image is saved automatically, whatever the settings say")
print("roles: ok")
