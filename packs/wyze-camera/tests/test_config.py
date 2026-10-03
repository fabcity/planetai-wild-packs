"""wyzecam.config: the pack's settings, read from the environment the node gives a pack.
Run from a node's folder: python3 packs/wyze-camera/tests/test_config.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fakes import setup  # noqa: E402
from wyzecam import config  # noqa: E402

out = setup({})
c = config.load()
assert c.url == "" and c.cameras == () and not c.ready
assert c.roles == ("motion",) and c.keep_days == 30 and c.snap_on_motion is False
assert c.snap_every_min == 0 and c.snap_max_mb == 500 and c.token == ""
assert c.out == out / "wyze-camera"
print("  defaults are the spec's: idle, motion only, 30 days, automatic snapshots off, 500 MB")

setup({"WYZE_BRIDGE_URL": "http://192.168.1.20:5000/", "WYZE_CAMERAS": " kitchen , porch,,",
       "WYZE_ROLES": "snapshots, motion", "WYZE_KEEP_DAYS": "7", "WYZE_SNAPSHOT_ON_MOTION": "1",
       "WYZE_SNAPSHOT_EVERY": "15", "WYZE_SNAPSHOT_MAX_MB": "50", "WYZE_BRIDGE_TOKEN": " tok "})
c = config.load()
assert c.ready and c.url == "http://192.168.1.20:5000" and c.cameras == ("kitchen", "porch")
assert c.roles == ("motion", "snapshots"), "roles run in the pack's order, whatever order they are listed in"
assert (c.keep_days, c.snap_on_motion, c.snap_every_min, c.snap_max_mb, c.token) == (7, True, 15, 50, "tok")
print("  settings are trimmed, cameras split, roles in the pack's own order")

said = []
config.log.addHandler(type("H", (__import__("logging").Handler,), {"emit": lambda self, r: said.append(r.getMessage())})())
setup({"WYZE_ROLES": "motion,visibility", "WYZE_KEEP_DAYS": "a month", "WYZE_SNAPSHOT_MAX_MB": "0"})
c = config.load()
assert c.roles == ("motion",) and c.keep_days == 30 and c.snap_max_mb == 1, c
assert any("WYZE_ROLES" in m for m in said) and any("WYZE_KEEP_DAYS" in m for m in said), said
n = len(said)
config.load()
assert len(said) == n, "the same complaint is said once, not at every poll"
print("  an unknown role and a non-number are said once and fall back; a cap of 0 MB becomes 1")

assert config.slug("Kitchen Cam") == "kitchen-cam" and config.slug("../x") == "x" and config.slug("///") == "camera"
print("  a camera name becomes a safe folder name")
print("config: ok")
