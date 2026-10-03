"""Shared by the tests: a stand-in for httpx.Client talking to docker-wyze-bridge, and a clean environment.

The bridge's answers follow its source (v2.10.x): GET /api/<cam>/motion_ts returns
{"status": "success", "response": {...}, "value": <epoch seconds>}, an unknown camera returns {"error": ...},
a wrong key is a 401, and an image it cannot give is a 307 that is not a JPEG."""
import os
import sys
import tempfile
from pathlib import Path

PACK = Path(__file__).resolve().parent.parent
if str(PACK) not in sys.path:
    sys.path.insert(0, str(PACK))


class Resp:
    def __init__(self, status=200, body=None, content=b"", ctype="application/json"):
        self.status_code, self._body, self.content = status, body, content
        self.headers = {"content-type": ctype}

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


class FakeBridge:
    """motion[cam] = epoch seconds (0 = no motion yet). A camera not in `motion` is unknown to the bridge.
    down=True raises the way httpx does, with the URL in the message. key, if set, must arrive as the `api` header."""

    def __init__(self, motion=None, key="", down=False, snapshot=True, thumb=True):
        self.motion, self.key, self.down = dict(motion or {}), key, down
        self.snapshot, self.thumb = snapshot, thumb
        self.calls = []

    def get(self, url, headers=None, timeout=None, follow_redirects=None):
        self.calls.append((url, dict(headers or {}), timeout))
        if self.down:
            raise ConnectionError(f"[Errno 61] Connection refused: {url}")
        if self.key and (headers or {}).get("api") != self.key:
            return Resp(401, {"error": "unauthorized"})
        parts = url.split("/", 3)[3].split("/")
        if parts[0] == "api" and len(parts) == 3 and parts[2] == "motion_ts":
            cam = parts[1]
            if cam not in self.motion:
                return Resp(200, {"error": f"Could not find camera [{cam}]"})
            v = self.motion[cam]
            return Resp(200, {"status": "success", "response": {"motion": False, "motion_ts": v}, "value": v})
        if parts[0] in ("snapshot", "thumb") and len(parts) == 2 and parts[1].endswith(".jpg"):
            cam = parts[1][:-4]
            if cam in self.motion and getattr(self, parts[0]):
                return Resp(200, None, f"JPEG {parts[0]} {cam}".encode(), "image/jpeg")
            return Resp(307, None, b"", "text/html; charset=utf-8")
        if parts == ["api"]:
            return Resp(200, {c: {"name_uri": c} for c in self.motion})
        return Resp(404, None, b"", "text/html")


def setup(env):
    """A fresh PACK_OUT, env applied, every other WYZE_* setting removed. Returns the PACK_OUT folder."""
    for k in [k for k in os.environ if k.startswith("WYZE_")]:
        del os.environ[k]
    out = Path(tempfile.mkdtemp())
    os.environ["PACK_OUT"] = str(out)
    os.environ.update(env)
    return out
