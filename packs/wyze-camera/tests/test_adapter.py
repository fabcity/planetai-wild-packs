"""adapter.py, loaded the way the node loads it: afresh, by path, at every poll.
Run from a node's folder: python3 packs/wyze-camera/tests/test_adapter.py"""
import importlib.util
import json
import logging
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fakes import PACK, FakeBridge, setup  # noqa: E402

URL, KEY, CAMS = "http://10.9.8.7:5000", "tok-SECRET", ("kitchen-secret-room", "bedroom-two")
T = time.time() - 600  # inside the keep window: every poll prunes
said = []
logging.getLogger("planetai.pack.wyze_camera").addHandler(
    type("H", (logging.Handler,), {"emit": lambda self, r: said.append(r.getMessage())})())


def adapter():
    """A fresh module each time, as app/packs.py does with spec_from_file_location at every poll."""
    spec = importlib.util.spec_from_file_location("planetai_pack_wyze-camera", PACK / "adapter.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def clean(text):
    for leak in (URL, "10.9.8.7", KEY, *CAMS):
        assert leak not in text, f"{leak!r} leaked into: {text}"


setup({})
assert adapter().fetch(FakeBridge()) == ([], [])
assert any("idle" in m for m in said), said
print("  unset, it idles and says so")

out = setup({"WYZE_BRIDGE_URL": URL, "WYZE_BRIDGE_TOKEN": KEY, "WYZE_CAMERAS": ",".join(CAMS),
             "WYZE_ROLES": "motion,snapshots", "WYZE_SNAPSHOT_ON_MOTION": "1"})
fb = FakeBridge({CAMS[0]: 0, CAMS[1]: 0}, key=KEY)
assert adapter().fetch(fb) == ([], [])
fb.motion[CAMS[0]] = T
assert adapter().fetch(fb) == ([], []), "it never gives the node a sensor or a reading"
assert (out / "wyze-camera" / "motion.jsonl").read_text().count(CAMS[0]) == 1
assert len(list((out / "wyze-camera" / "snapshots").glob("*/*.jpg"))) == 1
assert adapter().fetch(fb) == ([], []) and (out / "wyze-camera" / "motion.jsonl").read_text().count(CAMS[0]) == 1
print("  across fresh loads, state lasts on disk: one event, one image, nothing twice")

del fb.motion[CAMS[1]]
said.clear()
assert adapter().fetch(fb) == ([], [])
assert any("1 request(s) failed" in m for m in said), said
for m in said:
    clean(m)
print("  one camera failing is logged, without its name, and the poll goes on")

said.clear()
for bad in (FakeBridge({}, key=KEY), FakeBridge({CAMS[0]: T}, key="other"), FakeBridge({CAMS[0]: T}, down=True)):
    try:
        adapter().fetch(bad)
        raise AssertionError("every request failed, so the poll must fail")
    except RuntimeError as e:
        assert str(e).startswith("wyze-camera: ") and "failed" in str(e), str(e)
        clean(str(e))
for m in said:
    clean(m)
print("  every request failing raises, so the node shows a failing source; nothing names a camera, the address or the key")

# Test OSError handling: write failure names nothing and loses no state
from wyzecam.store import Store as StoreClass

def mock_save_image(self, cam, data, trigger, now):
    raise OSError(f"Permission denied: /app/out/wyze-camera/snapshots/{cam}/12345.jpg")

out = setup({"WYZE_BRIDGE_URL": URL, "WYZE_BRIDGE_TOKEN": KEY, "WYZE_CAMERAS": ",".join(CAMS),
             "WYZE_ROLES": "motion,snapshots", "WYZE_SNAPSHOT_ON_MOTION": "1"})
fb = FakeBridge({CAMS[0]: 0, CAMS[1]: 0}, key=KEY)
adapter().fetch(fb)
T2 = time.time() - 60
fb.motion[CAMS[0]] = T2
with patch.object(StoreClass, 'save_image', mock_save_image):
    try:
        adapter().fetch(fb)
        raise AssertionError("OSError should be caught and re-raised as RuntimeError")
    except RuntimeError as e:
        assert str(e) == "wyze-camera: could not write to its output folder", f"got: {str(e)}"
        clean(str(e))
# Verify state was saved even though the poll failed
state_after_fail = json.loads((out / "wyze-camera" / "state.json").read_text())
assert state_after_fail["motion"][CAMS[0]] == T2, f"state not saved during failed poll: {state_after_fail}"
# Restore and poll again with same motion time, verify no duplicate
fb.motion[CAMS[0]] = T2
assert adapter().fetch(fb) == ([], [])
events_text = (out / "wyze-camera" / "motion.jsonl").read_text()
assert events_text.count(CAMS[0]) == 1, "motion appended then save_state failed, but next poll should not duplicate"
print("  a write failure names nothing and does not duplicate events on retry")

# a failed log write loses no event: the poll fails, the next one logs it
from wyzecam.store import Store as S2, iso as iso2, stamp as stamp2

def mock_add_events(self, events, keep_days, now):
    raise OSError(f"Permission denied: /app/out/wyze-camera/motion.jsonl ({events[0]['camera']})")

out = setup({"WYZE_BRIDGE_URL": URL, "WYZE_BRIDGE_TOKEN": KEY, "WYZE_CAMERAS": ",".join(CAMS)})
fb = FakeBridge({CAMS[0]: 0, CAMS[1]: 0}, key=KEY)
adapter().fetch(fb)
fb.motion[CAMS[0]] = time.time() - 60
with patch.object(S2, "add_events", mock_add_events):
    try:
        adapter().fetch(fb)
        raise AssertionError("a failed log write must fail the poll")
    except RuntimeError as e:
        assert str(e) == "wyze-camera: could not write to its output folder", str(e)
        clean(str(e))
assert adapter().fetch(fb) == ([], [])
lines = (out / "wyze-camera" / "motion.jsonl").read_text().splitlines()
assert len(lines) == 1 and CAMS[0] in lines[0], lines
print("  a failed log write is not saved as seen: the next poll logs the event, once")

# keep_days holds on every poll, even with the motion role on and nothing new
out = setup({"WYZE_BRIDGE_URL": URL, "WYZE_CAMERAS": ",".join(CAMS), "WYZE_ROLES": "motion"})
st, now = S2(out / "wyze-camera"), time.time()
st.add_events([{"camera": "x", "motion_at": iso2(now - 90 * 86400), "seen_at": iso2(now - 90 * 86400)},
               {"camera": "x", "motion_at": iso2(now - 3600), "seen_at": iso2(now - 3600)}], 365, now)
old = st.save_image("x", b"old", "manual", now - 90 * 86400)
new = st.save_image("x", b"new", "manual", now - 3600)
fb = FakeBridge({CAMS[0]: 0, CAMS[1]: 0})
assert adapter().fetch(fb) == ([], [])
assert [e["motion_at"] for e in st.events()] == [iso2(now - 3600)] and st.images() == [new] and not old.exists()
print("  one quiet poll prunes the old log line and the old image")

# a state file that cannot be read fails the poll the same way, naming no path
def no_state(self):
    raise PermissionError(13, "Permission denied", str(self.state_file))
with patch.object(S2, "load_state", no_state):
    try:
        adapter().fetch(fb)
        raise AssertionError("an unreadable state file must fail the poll")
    except RuntimeError as e:
        assert str(e) == "wyze-camera: could not write to its output folder" and "/" not in str(e).split(":", 1)[1], str(e)
print("  an unreadable state file gives the same constant message")
print("adapter: ok")
