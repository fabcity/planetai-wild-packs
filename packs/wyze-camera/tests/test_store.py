"""wyzecam.store: state, the motion log and the snapshots, all under out/wyze-camera on the node's disk.
Run from a node's folder: python3 packs/wyze-camera/tests/test_store.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fakes import setup  # noqa: E402
from wyzecam.store import Store, iso, stamp  # noqa: E402

T = 1759475565.0                                   # 2025-10-03T07:12:45Z
DAY = 86400
assert iso(T) == "2025-10-03T07:12:45Z" and stamp(T) == "20251003T071245Z"
print("  times are UTC, ISO in the log and compact in file names")

s = Store(setup({}) / "wyze-camera")
assert s.load_state() == {"motion": {}, "schedule": {}} and s.events() == [] and s.images() == []
s.save_state({"motion": {"kitchen": T}, "schedule": {"kitchen": T - 60}})
assert Store(s.root).load_state() == {"motion": {"kitchen": T}, "schedule": {"kitchen": T - 60}}
assert not list(s.root.glob("*.tmp")), "a state write leaves no temporary file behind"
s.state_file.write_text("{half a fi")
assert s.load_state() == {"motion": {}, "schedule": {}}, "an unreadable state starts over rather than crashing"
print("  state round-trips through a rename, and a broken file starts over")


def ev(cam, ts):
    return {"camera": cam, "motion_at": iso(ts), "seen_at": iso(ts + 120)}


s.add_events([ev("kitchen", T - 40 * DAY), ev("kitchen", T - 10 * DAY)], keep_days=60, now=T)
s.add_events([ev("porch", T - 60)], keep_days=30, now=T)
assert [e["motion_at"] for e in s.events()] == [iso(T - 10 * DAY), iso(T - 60)], "events past 30 days are pruned on write"
assert [e["camera"] for e in s.events(since=T - DAY)] == ["porch"]
with s.log_file.open("a") as f:
    f.write("not json\n")
assert len(s.events()) == 2, "a broken line is skipped, not fatal"
assert all(json.loads(line)["camera"] for line in s.log_file.read_text().splitlines()[:2])
print("  the log appends, prunes past keep_days, filters by time and skips a broken line")

p1 = s.save_image("Kitchen Cam", b"x" * 400_000, "manual", T - 40 * DAY)
p2 = s.save_image("Kitchen Cam", b"y" * 700_000, "schedule", T - 2 * DAY)
p3 = s.save_image("porch", b"z" * 600_000, "motion", T - DAY)
assert p1 == s.root / "snapshots" / "kitchen-cam" / f"{stamp(T - 40 * DAY)}-manual.jpg", p1
assert s.images() == [p1, p2, p3], "images sort oldest first, across cameras"
p4 = s.save_image("porch", b"w", "motion", T - DAY)
assert p4.name == f"{stamp(T - DAY)}-motion-2.jpg" and p3.read_bytes() == b"z" * 600_000, "the same second keeps both"
p4.unlink()
assert s.prune_images(keep_days=30, max_mb=1, now=T) == 2 and s.images() == [p3]
print("  snapshots go past keep_days, then oldest first until under the cap")
assert s.prune_images(keep_days=30, max_mb=1, now=T) == 0 and s.images() == [p3]
print("  a second prune over its own result removes nothing")
print("store: ok")
