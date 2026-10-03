"""wyzecam.bridge: docker-wyze-bridge's REST API, against a fake that answers the way the bridge's source does.
Run from a node's folder: python3 packs/wyze-camera/tests/test_bridge.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fakes import FakeBridge, Resp  # noqa: E402
from wyzecam.bridge import (BAD_ANSWER, NO_IMAGE, REFUSED, UNKNOWN, UNREACHABLE, Bridge,  # noqa: E402
                            BridgeError)

URL, KEY, CAM = "http://10.9.8.7:5000", "tok-SECRET", "kitchen-secret-room"


def raises(fn, reason):
    try:
        fn()
    except BridgeError as e:
        assert str(e) == reason, (str(e), reason)
        for leak in (URL, "10.9.8.7", KEY, CAM):
            assert leak not in str(e), f"a bridge error carries {leak!r}"
        return
    raise AssertionError(f"expected BridgeError({reason!r})")


fb = FakeBridge({CAM: 1759475565.5}, key=KEY)
b = Bridge(fb, URL + "/", KEY)
assert b.motion_ts(CAM) == 1759475565.5
url, headers, timeout = fb.calls[-1]
assert url == f"{URL}/api/{CAM}/motion_ts" and headers == {"api": KEY} and timeout == 10
assert KEY not in url, "the key never travels in a URL"
print("  the last motion time, in epoch seconds, with the key in the `api` header and a timeout")

fb0 = FakeBridge({CAM: 0})
assert Bridge(fb0, URL).motion_ts(CAM) == 0.0 and fb0.calls[-1][1] == {}
print("  0 means no motion yet, and no key means no header")

raises(lambda: Bridge(FakeBridge({CAM: 1}, key=KEY), URL, "wrong").motion_ts(CAM), REFUSED)
raises(lambda: Bridge(FakeBridge({}), URL).motion_ts(CAM), UNKNOWN)
raises(lambda: Bridge(FakeBridge({CAM: 1}, down=True), URL).motion_ts(CAM), UNREACHABLE)
print("  a wrong key, an unknown camera and a bridge that is down each say so, and name nothing")


class Odd:
    def __init__(self, resp):
        self.resp = resp

    def get(self, *a, **k):
        return self.resp


for resp in (Resp(200, None, b"<html>", "text/html"), Resp(200, {"status": "success", "value": "soon"}),
             Resp(200, {"status": "success", "value": True}), Resp(200, {"status": "success", "value": -5}),
             Resp(200, ["not", "a", "dict"])):
    raises(lambda: Bridge(Odd(resp), URL).motion_ts(CAM), BAD_ANSWER)
raises(lambda: Bridge(Odd(Resp(500, None)), URL).motion_ts(CAM), UNREACHABLE)
print("  an answer that is not a motion time is refused, never turned into one")

fb = FakeBridge({CAM: 1}, key=KEY)
assert Bridge(fb, URL, KEY).image(CAM) == f"JPEG snapshot {CAM}".encode() and fb.calls[-1][0] == f"{URL}/snapshot/{CAM}.jpg"
assert Bridge(fb, URL, KEY).image(CAM, "thumb") == f"JPEG thumb {CAM}".encode() and fb.calls[-1][0] == f"{URL}/thumb/{CAM}.jpg"
raises(lambda: Bridge(FakeBridge({CAM: 1}, snapshot=False), URL).image(CAM), NO_IMAGE)
raises(lambda: Bridge(FakeBridge({CAM: 1}, key=KEY), URL, "wrong").image(CAM), REFUSED)
raises(lambda: Bridge(FakeBridge({CAM: 1}, down=True), URL).image(CAM, "thumb"), UNREACHABLE)
print("  a fresh still and Wyze's thumbnail come back as JPEG bytes; a redirect to 'not available' is no image")
print("bridge: ok")
