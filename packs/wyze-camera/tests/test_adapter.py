"""adapter.py, loaded the way the node loads it: afresh, by path, at every poll.
Run from a node's folder: python3 packs/wyze-camera/tests/test_adapter.py"""
import importlib.util
import logging
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fakes import PACK, FakeBridge, setup  # noqa: E402

URL, KEY, CAMS = "http://10.9.8.7:5000", "tok-SECRET", ("kitchen-secret-room", "bedroom-two")
T = 1759475565.0
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
original_save_image = StoreClass.save_image

def mock_save_image(self, cam, data, trigger, now):
    raise OSError(f"Permission denied: /app/out/wyze-camera/snapshots/{cam}/12345.jpg")

setup({"WYZE_BRIDGE_URL": URL, "WYZE_BRIDGE_TOKEN": KEY, "WYZE_CAMERAS": ",".join(CAMS),
       "WYZE_ROLES": "motion,snapshots", "WYZE_SNAPSHOT_ON_MOTION": "1"})
fb = FakeBridge({CAMS[0]: 0, CAMS[1]: 0}, key=KEY)
adapter().fetch(fb)
fb.motion[CAMS[0]] = T
with patch.object(StoreClass, 'save_image', mock_save_image):
    try:
        adapter().fetch(fb)
        raise AssertionError("OSError should be caught and re-raised as RuntimeError")
    except RuntimeError as e:
        assert str(e) == "wyze-camera: could not write to its output folder", f"got: {str(e)}"
        clean(str(e))
# Restore and poll again with same motion time, verify no duplicate
fb.motion[CAMS[0]] = T
assert adapter().fetch(fb) == ([], [])
events_text = (out / "wyze-camera" / "motion.jsonl").read_text()
assert events_text.count(CAMS[0]) == 1, "motion appended then save_state failed, but next poll should not duplicate"
print("  a write failure names nothing and does not duplicate events on retry")
print("adapter: ok")
