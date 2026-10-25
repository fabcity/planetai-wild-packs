"""status, events and snapshot: what someone at the node's terminal runs. These are the one place camera names print.
Run from a node's folder: python3 packs/wyze-camera/tests/test_scripts.py"""
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fakes import PACK, FakeBridge, setup  # noqa: E402
from wyzecam.store import Store, iso  # noqa: E402

import time  # noqa: E402

NOW = time.time()


def script(name):
    spec = importlib.util.spec_from_file_location(f"wyzecam_script_{name}", PACK / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def run(name, argv, fb):
    lines = []
    rc = script(name).main(argv, hc=fb, out=lines.append)
    return rc, "\n".join(lines)


setup({})
rc, text = run("status", [], FakeBridge())
assert rc == 1 and "idle" in text and "WYZE_BRIDGE_URL" in text
print("  status, unset, says what to set")

out = setup({"WYZE_BRIDGE_URL": "http://10.0.0.2:5000", "WYZE_CAMERAS": "kitchen,porch"})
store = Store(out / "wyze-camera")
store.add_events([{"camera": "kitchen", "motion_at": iso(NOW - 3600), "seen_at": iso(NOW - 3500)},
                  {"camera": "kitchen", "motion_at": iso(NOW - 3 * 86400), "seen_at": iso(NOW - 3 * 86400)}], 30, NOW)
store.save_image("kitchen", b"x" * 2048, "manual", NOW - 60)
fb = FakeBridge({"kitchen": NOW - 3600, "porch": 0})
rc, text = run("status", [], fb)
assert rc == 0
assert "kitchen: last motion " + iso(NOW - 3600) in text and "1 in 24 h, 2 in 7 days" in text and "1 snapshots" in text, text
assert "porch: last motion never (is MOTION_API=True set in the bridge?)" in text, text
del fb.motion["porch"]
assert "porch: no answer: a camera is unknown to the bridge" in run("status", [], fb)[1]
print("  status names each camera, its last motion, its counts and snapshots, and hints at MOTION_API")

rc, text = run("events", [], fb)
assert rc == 0 and text.count("kitchen") == 1 and iso(NOW - 3600) in text, text
rc, text = run("events", ["--hours", "100"], fb)
assert text.count("kitchen") == 2
rc, text = run("events", ["--hours", "x"], fb)
assert rc == 2 and "--hours" in text
print("  events prints the last day by default, or as many hours as asked")

rc, text = run("snapshot", ["porch"], FakeBridge({"kitchen": 0, "porch": 0}))
assert rc == 0 and "porch" in text and len([p for p in store.images() if p.parent.name == "porch"]) == 1
assert [p for p in store.images() if p.parent.name == "porch"][0].name.endswith("-manual.jpg")
rc, text = run("snapshot", [], FakeBridge({"kitchen": 0, "porch": 0}))
assert rc == 0 and len(store.images()) == 4
rc, text = run("snapshot", ["garage"], FakeBridge({"kitchen": 0, "porch": 0}))
assert rc == 2 and "garage" in text and "WYZE_CAMERAS" in text
rc, text = run("snapshot", [], FakeBridge({"kitchen": 0}))
assert rc == 1 and "porch: the bridge had no image" in text
print("  snapshot saves a still per camera or for the one named, refuses a name not followed, and says which failed")
print("scripts: ok")
