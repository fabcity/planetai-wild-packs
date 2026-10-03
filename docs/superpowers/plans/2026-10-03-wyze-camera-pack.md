# wyze-camera wild pack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A wild pack, `wyze-camera`, that records Wyze motion events and saves snapshots on a PLANETAI node through docker-wyze-bridge, keeping everything in `out/wyze-camera/` and giving the node no sensors and no readings.

**Architecture:** `adapter.py` is the node's entry point; the node runs it afresh at every poll and calls `fetch(hc)`. It loads settings (`wyzecam/config.py`), talks to the bridge (`wyzecam/bridge.py`), keeps files (`wyzecam/store.py`) and runs the roles listed in `WYZE_ROLES` (`wyzecam/roles.py`: `motion`, `snapshots`). Three scripts at the pack's top level (`status.py`, `events.py`, `snapshot.py`) are run by `planetai run wyze-camera <script>`. Helper code lives in the `wyzecam/` subfolder because `planetai run` lists every `.py` file directly inside a pack as a runnable script.

**Tech Stack:** Python 3.12 (the node's app container), standard library only in the pack, plus `httpx` (already in the node's image) in the scripts. Tests are plain `assert` scripts with no framework, run from a node's folder as fabcity/planetai-wild-packs' check runs them, with the standard library and PyYAML.

**Spec:** `docs/superpowers/specs/2026-10-03-wyze-camera-pack-design.md` in this repository. Read it first; this plan argues from it.

## Global Constraints

- Pack id and folder: `wyze-camera`; hosted in this repository at `packs/wyze-camera/`. `pack.yaml`'s `id:` is exactly `wyze-camera`.
- Licence Apache-2.0, stated in the pack's README.
- Settings, exact names and defaults: `WYZE_BRIDGE_URL` (blank), `WYZE_BRIDGE_TOKEN` (blank, listed under `secrets:`), `WYZE_CAMERAS` (blank), `WYZE_ROLES` (`motion`), `WYZE_KEEP_DAYS` (`30`), `WYZE_SNAPSHOT_ON_MOTION` (`0`), `WYZE_SNAPSHOT_EVERY` (`0`, minutes), `WYZE_SNAPSHOT_MAX_MB` (`500`).
- Roles: `motion` and `snapshots`, run in that order, only those listed in `WYZE_ROLES`.
- Files only under `Path(os.getenv("PACK_OUT", "/app/out")) / "wyze-camera"`: `state.json`, `motion.jsonl`, `snapshots/<camera>/<UTC yyyymmddThhmmssZ>-<trigger>.jpg`, trigger one of `manual`, `motion`, `motion-at-poll`, `schedule`.
- `fetch(hc)` always returns `([], [])`. No sensor row, no reading, ever.
- No exception message and no log line names a camera, the bridge address or the token. Only the three scripts, run on the node's terminal, print camera names.
- The bridge's API key is sent as the `api` header, never in a URL.
- Every HTTP call has a timeout (10 s).
- `requires:` names the first node release that contains planetai-node commit `f8fcc81` (pack `secrets:`).
- Python 3.12 syntax is fine (it runs in the node's container), but no third-party import in `wyzecam/` or `adapter.py`.

---

### Task 1: Pack skeleton, manifest and settings

**Files:**
- Create: `packs/wyze-camera/pack.yaml`
- Create: `packs/wyze-camera/wyzecam/__init__.py`
- Create: `packs/wyze-camera/wyzecam/config.py`
- Create: `packs/wyze-camera/tests/fakes.py`
- Test: `packs/wyze-camera/tests/test_config.py`

**Interfaces:**
- Produces: `wyzecam.config.load() -> Config`; `Config` fields `url: str, token: str, cameras: tuple[str, ...], roles: tuple[str, ...], keep_days: int, snap_on_motion: bool, snap_every_min: int, snap_max_mb: int, out: pathlib.Path` and property `ready -> bool`; `wyzecam.config.ROLES = ("motion", "snapshots")`; `wyzecam.config.say_once(msg: str) -> None`; `wyzecam.config.slug(cam: str) -> str`; `wyzecam.config.log` (a `logging.Logger` named `planetai.pack.wyze_camera`).
- Produces (tests): `tests/fakes.py` with `Resp`, `FakeBridge`, `setup(env: dict) -> pathlib.Path` (a fresh temporary `PACK_OUT`, with `env` applied and every `WYZE_*` key not in `env` removed).

- [ ] **Step 1: Write the test helper and the failing test**

`packs/wyze-camera/tests/fakes.py`:

```python
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
```

`packs/wyze-camera/tests/test_config.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run, from this repository's root (the tests need nothing from a node; each sets its own temporary `PACK_OUT`):
`python3 packs/wyze-camera/tests/test_config.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'wyzecam'`.

- [ ] **Step 3: Write the manifest and the settings module**

`packs/wyze-camera/pack.yaml` (the `requires:` value is settled in Task 7, Step 4; `>=0.76` is the placeholder floor until then and must not ship):

```yaml
id: wyze-camera
name: Wyze cameras
description: >-
  Wyze cameras through docker-wyze-bridge: records motion events and saves snapshots on this node's own disk, in
  out/wyze-camera. It gives the node no sensors and no readings, so none of it reaches the database, the daily export,
  the upstream aggregates or any API.
author: Tomas Diez (Fab City Foundation)
version: 0.1.0
requires: { node: ">=0.76" }
kind: code
env:
  - "# wyze-camera: the bridge's local address, e.g. http://192.168.1.20:5000"
  - "WYZE_BRIDGE_URL="
  - "# wyze-camera: the bridge's API key (WB_API in its log), if its API is protected"
  - "WYZE_BRIDGE_TOKEN="
  - "# wyze-camera: the cameras to follow, comma-separated, as the bridge names them"
  - "WYZE_CAMERAS="
  - "# wyze-camera: which roles run at each poll: motion, snapshots"
  - "WYZE_ROLES=motion"
  - "# wyze-camera: days to keep motion events and snapshots"
  - "WYZE_KEEP_DAYS=30"
  - "# wyze-camera: 1 saves an image with each new motion event (needs the motion and snapshots roles)"
  - "WYZE_SNAPSHOT_ON_MOTION=0"
  - "# wyze-camera: minutes between scheduled snapshots, 0 is off (needs the snapshots role)"
  - "WYZE_SNAPSHOT_EVERY=0"
  - "# wyze-camera: the most the snapshot folder may hold, in MB; the oldest go first"
  - "WYZE_SNAPSHOT_MAX_MB=500"
secrets: [WYZE_BRIDGE_TOKEN]
attribution: >-
  Motion detection is Wyze's own, read through docker-wyze-bridge (github.com/mrlt8/docker-wyze-bridge). Not endorsed
  by Wyze.
```

`packs/wyze-camera/wyzecam/__init__.py`:

```python
"""The wyze-camera pack's own code. A subfolder so `planetai run` lists only the pack's three scripts."""
```

`packs/wyze-camera/wyzecam/config.py`:

```python
"""The pack's settings, read from the environment the node gives a pack (Set up writes a saved value into it)."""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("planetai.pack.wyze_camera")
ROLES = ("motion", "snapshots")

# The node runs adapter.py afresh at every poll, but this module stays in sys.modules, so this set lasts the process.
_said: set[str] = set()


def say_once(msg: str) -> None:
    """A warning said once per process. Never put a camera name, an address or a key in `msg`."""
    if msg not in _said:
        _said.add(msg)
        log.warning(msg)


def _int(name: str, default: int, floor: int = 0) -> int:
    raw = str(os.getenv(name, "")).strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        say_once(f"wyze-camera: {name} is not a whole number; using {default}")
        value = default
    return max(floor, value)


@dataclass(frozen=True)
class Config:
    url: str
    token: str
    cameras: tuple[str, ...]
    roles: tuple[str, ...]
    keep_days: int
    snap_on_motion: bool
    snap_every_min: int
    snap_max_mb: int
    out: Path

    @property
    def ready(self) -> bool:
        return bool(self.url and self.cameras)


def load() -> Config:
    listed = [r.strip() for r in (os.getenv("WYZE_ROLES") or "motion").split(",") if r.strip()]
    unknown = [r for r in listed if r not in ROLES]
    if unknown:
        say_once(f"wyze-camera: WYZE_ROLES names {len(unknown)} role(s) this pack does not have; "
                 f"it has {', '.join(ROLES)}")
    return Config(
        url=os.getenv("WYZE_BRIDGE_URL", "").strip().rstrip("/"),
        token=os.getenv("WYZE_BRIDGE_TOKEN", "").strip(),
        cameras=tuple(c.strip() for c in os.getenv("WYZE_CAMERAS", "").split(",") if c.strip()),
        roles=tuple(r for r in ROLES if r in listed),
        keep_days=_int("WYZE_KEEP_DAYS", 30, 1),
        snap_on_motion=os.getenv("WYZE_SNAPSHOT_ON_MOTION", "0").strip() == "1",
        snap_every_min=_int("WYZE_SNAPSHOT_EVERY", 0),
        snap_max_mb=_int("WYZE_SNAPSHOT_MAX_MB", 500, 1),
        out=Path(os.getenv("PACK_OUT", "/app/out")) / "wyze-camera",
    )


def slug(cam: str) -> str:
    """A camera name as a folder name. The bridge's names are already this shape; this only makes sure."""
    return re.sub(r"[^a-z0-9_-]+", "-", cam.lower()).strip("-.") or "camera"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 packs/wyze-camera/tests/test_config.py`
Expected: four `  …` lines, then `config: ok`.

- [ ] **Step 5: Commit**

```bash
git add packs/wyze-camera/pack.yaml packs/wyze-camera/wyzecam packs/wyze-camera/tests
git commit -m "wyze-camera: pack.yaml, settings, test helpers"
```

---

### Task 2: The bridge client

**Files:**
- Create: `packs/wyze-camera/wyzecam/bridge.py`
- Test: `packs/wyze-camera/tests/test_bridge.py`

**Interfaces:**
- Consumes: `tests/fakes.py` (`FakeBridge`, `Resp`).
- Produces: `wyzecam.bridge.Bridge(hc, url: str, token: str = "", timeout: float = 10)` with `motion_ts(cam: str) -> float` and `image(cam: str, kind: str = "snapshot") -> bytes` (`kind` is `"snapshot"` or `"thumb"`); `wyzecam.bridge.BridgeError(Exception)`, whose `str()` is one of the module constants `UNREACHABLE`, `REFUSED`, `UNKNOWN`, `BAD_ANSWER`, `NO_IMAGE`.

- [ ] **Step 1: Write the failing test**

`packs/wyze-camera/tests/test_bridge.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 packs/wyze-camera/tests/test_bridge.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'wyzecam.bridge'`.

- [ ] **Step 3: Write the bridge client**

`packs/wyze-camera/wyzecam/bridge.py`:

```python
"""docker-wyze-bridge's local REST API, as read from its source (v2.10.x: app/frontend.py,
app/wyzebridge/web_ui.py, app/wyzebridge/wyze_stream.py):

  GET /api/<cam>/motion_ts  {"status": "success", "response": {...}, "value": <epoch seconds; 0 = none yet>}
                            an unknown camera answers a JSON object with an "error" key
  GET /snapshot/<cam>.jpg   a fresh still from the RTSP stream
  GET /thumb/<cam>.jpg      the camera's latest thumbnail from Wyze's cloud: the event's own image
  the API key travels as an `api` header; a wrong one is a 401
  an image the bridge cannot give is a 307 to /static/notavailable.svg, which is not a JPEG

Every BridgeError message is one of the constants below: safe to show beyond the machine, because it names no camera,
no address and no key. httpx puts the URL in its own errors, so they are never passed on."""
from __future__ import annotations

UNREACHABLE = "the bridge did not answer"
REFUSED = "the bridge refused the API key"
UNKNOWN = "a camera is unknown to the bridge"
BAD_ANSWER = "the bridge answered something that is not a motion time"
NO_IMAGE = "the bridge had no image"


class BridgeError(Exception):
    pass


class Bridge:
    def __init__(self, hc, url: str, token: str = "", timeout: float = 10):
        self.hc, self.url, self.timeout = hc, url.rstrip("/"), timeout
        self.headers = {"api": token} if token else {}

    def _get(self, path: str):
        try:
            return self.hc.get(self.url + path, headers=self.headers, timeout=self.timeout, follow_redirects=False)
        except Exception:  # noqa: BLE001
            raise BridgeError(UNREACHABLE) from None

    def motion_ts(self, cam: str) -> float:
        r = self._get(f"/api/{cam}/motion_ts")
        if r.status_code in (401, 403):
            raise BridgeError(REFUSED)
        if r.status_code != 200:
            raise BridgeError(UNREACHABLE)
        try:
            body = r.json()
        except ValueError:
            raise BridgeError(BAD_ANSWER) from None
        if not isinstance(body, dict):
            raise BridgeError(BAD_ANSWER)
        if "error" in body:
            raise BridgeError(UNKNOWN)
        value = body.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise BridgeError(BAD_ANSWER)
        return float(value)

    def image(self, cam: str, kind: str = "snapshot") -> bytes:
        r = self._get(f"/{kind}/{cam}.jpg")
        if r.status_code in (401, 403):
            raise BridgeError(REFUSED)
        ctype = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
        if r.status_code != 200 or ctype != "image/jpeg" or not r.content:
            raise BridgeError(NO_IMAGE)
        return r.content
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 packs/wyze-camera/tests/test_bridge.py`
Expected: five `  …` lines, then `bridge: ok`.

- [ ] **Step 5: Commit**

```bash
git add packs/wyze-camera/wyzecam/bridge.py packs/wyze-camera/tests/test_bridge.py
git commit -m "wyze-camera: the bridge client, with errors that name nothing"
```

---

### Task 3: The store

**Files:**
- Create: `packs/wyze-camera/wyzecam/store.py`
- Test: `packs/wyze-camera/tests/test_store.py`

**Interfaces:**
- Consumes: `wyzecam.config.slug`.
- Produces: `wyzecam.store.iso(ts: float) -> str` (`"2026-10-03T07:12:45Z"`); `wyzecam.store.stamp(ts: float) -> str` (`"20261003T071245Z"`); `wyzecam.store.Store(root: Path)` with `load_state() -> dict` (`{"motion": {cam: float}, "schedule": {cam: float}}`), `save_state(state: dict) -> None`, `add_events(events: list[dict], keep_days: int, now: float) -> None`, `events(since: float | None = None) -> list[dict]`, `save_image(cam: str, data: bytes, trigger: str, now: float) -> Path`, `images() -> list[Path]` (oldest first), `prune_images(keep_days: int, max_mb: int, now: float) -> int`. An event is `{"camera": str, "motion_at": iso, "seen_at": iso}`.

- [ ] **Step 1: Write the failing test**

`packs/wyze-camera/tests/test_store.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 packs/wyze-camera/tests/test_store.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'wyzecam.store'`.

- [ ] **Step 3: Write the store**

`packs/wyze-camera/wyzecam/store.py`:

```python
"""Everything this pack keeps, all under out/wyze-camera/ on the node's disk, which nothing in the node serves, backs
up or exports: state.json (what was last seen), motion.jsonl (the events) and snapshots/<camera>/*.jpg."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .config import slug


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _write(path: Path, text: str) -> None:
    """Write beside, then rename: a crash mid-write leaves the old file, never half of a new one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.state_file = self.root / "state.json"
        self.log_file = self.root / "motion.jsonl"
        self.snaps = self.root / "snapshots"

    def load_state(self) -> dict:
        try:
            s = json.loads(self.state_file.read_text())
        except (FileNotFoundError, ValueError):
            s = {}
        if not isinstance(s, dict):
            s = {}
        return {"motion": dict(s.get("motion") or {}), "schedule": dict(s.get("schedule") or {})}

    def save_state(self, state: dict) -> None:
        _write(self.state_file, json.dumps(state, sort_keys=True))

    def events(self, since: float | None = None) -> list[dict]:
        try:
            lines = self.log_file.read_text().splitlines()
        except FileNotFoundError:
            return []
        cut = iso(since) if since is not None else ""
        out = []
        for line in lines:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if isinstance(e, dict) and e.get("motion_at", "") >= cut:
                out.append(e)
        return out

    def add_events(self, events: list[dict], keep_days: int, now: float) -> None:
        kept = self.events(since=now - keep_days * 86400) + list(events)
        _write(self.log_file, "".join(json.dumps(e, sort_keys=True) + "\n" for e in kept))

    def save_image(self, cam: str, data: bytes, trigger: str, now: float) -> Path:
        d = self.snaps / slug(cam)
        d.mkdir(parents=True, exist_ok=True)
        p, n = d / f"{stamp(now)}-{trigger}.jpg", 2
        while p.exists():                         # two stills in one second keep both
            p, n = d / f"{stamp(now)}-{trigger}-{n}.jpg", n + 1
        p.write_bytes(data)
        return p

    def images(self) -> list[Path]:
        if not self.snaps.is_dir():
            return []
        return sorted(self.snaps.glob("*/*.jpg"), key=lambda p: (p.name, str(p)))

    def prune_images(self, keep_days: int, max_mb: int, now: float) -> int:
        """Past keep_days go first; then the oldest, until the folder is under max_mb. The node's database is on the
        same disk, and a full disk can stop it."""
        gone = 0
        cutoff = stamp(now - keep_days * 86400)
        for p in self.images():
            if p.name[:16] < cutoff:
                p.unlink(missing_ok=True)
                gone += 1
        imgs = self.images()
        total = sum(p.stat().st_size for p in imgs)
        for p in imgs:
            if total <= max_mb * 1024 * 1024:
                break
            total -= p.stat().st_size
            p.unlink(missing_ok=True)
            gone += 1
        return gone
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 packs/wyze-camera/tests/test_store.py`
Expected: five `  …` lines, then `store: ok`.

- [ ] **Step 5: Commit**

```bash
git add packs/wyze-camera/wyzecam/store.py packs/wyze-camera/tests/test_store.py
git commit -m "wyze-camera: state, the motion log and snapshots, with pruning"
```

---

### Task 4: The roles

**Files:**
- Create: `packs/wyze-camera/wyzecam/roles.py`
- Test: `packs/wyze-camera/tests/test_roles.py`

**Interfaces:**
- Consumes: `Config` (Task 1), `Bridge`, `BridgeError` (Task 2), `Store`, `iso` (Task 3).
- Produces: `wyzecam.roles.ROLES: dict[str, Callable[[dict], None]]` with keys `"motion"` and `"snapshots"`. A role takes the poll's context dict `ctx` with keys `cfg` (Config), `bridge` (Bridge), `store` (Store), `state` (dict from `Store.load_state()`), `now` (float), `failures` (list of BridgeError reason strings, appended to), `answered` (int, incremented per successful bridge answer) and `new_motion` (list of events; the `motion` role sets it, `snapshots` reads it). A role mutates `ctx["state"]`; it never saves state (the adapter does).
- Produces: `wyzecam.roles.new_context(cfg, bridge, store, now: float) -> dict` building that dict.

- [ ] **Step 1: Write the failing test**

`packs/wyze-camera/tests/test_roles.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 packs/wyze-camera/tests/test_roles.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'wyzecam.roles'`.

- [ ] **Step 3: Write the roles**

`packs/wyze-camera/wyzecam/roles.py`:

```python
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
    new = []
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
            state["motion"][cam] = ts
    if new:
        ctx["store"].add_events(new, cfg.keep_days, now)
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
    saved = False
    for cam in cfg.cameras:
        if cfg.snap_on_motion and cam in moved:
            saved |= _save(ctx, cam, "thumb", "motion", fallback=("snapshot", "motion-at-poll"))
        if cfg.snap_every_min and now - state["schedule"].get(cam, 0) >= cfg.snap_every_min * 60:
            if _save(ctx, cam, "snapshot", "schedule"):
                state["schedule"][cam] = now
                saved = True
    if saved:
        ctx["store"].prune_images(cfg.keep_days, cfg.snap_max_mb, now)


ROLES = {"motion": motion, "snapshots": snapshots}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 packs/wyze-camera/tests/test_roles.py`
Expected: eight `  …` lines, then `roles: ok`.

- [ ] **Step 5: Commit**

```bash
git add packs/wyze-camera/wyzecam/roles.py packs/wyze-camera/tests/test_roles.py
git commit -m "wyze-camera: the motion and snapshots roles"
```

---

### Task 5: The adapter

**Files:**
- Create: `packs/wyze-camera/adapter.py`
- Test: `packs/wyze-camera/tests/test_adapter.py`

**Interfaces:**
- Consumes: `config.load`, `config.say_once`, `config.log`, `Bridge`, `Store`, `ROLES`, `new_context`.
- Produces: `fetch(hc) -> tuple[list, list]`, always `([], [])`; raises `RuntimeError` whose message starts `wyze-camera: ` when every bridge request in the poll failed.

- [ ] **Step 1: Write the failing test**

`packs/wyze-camera/tests/test_adapter.py`:

```python
"""adapter.py, loaded the way the node loads it: afresh, by path, at every poll.
Run from a node's folder: python3 packs/wyze-camera/tests/test_adapter.py"""
import importlib.util
import logging
import sys
from pathlib import Path

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
print("adapter: ok")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 packs/wyze-camera/tests/test_adapter.py`
Expected: FAIL with `FileNotFoundError` (no `adapter.py`).

- [ ] **Step 3: Write the adapter**

`packs/wyze-camera/adapter.py`:

```python
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
    ctx = new_context(cfg, Bridge(hc, cfg.url, cfg.token), store, time.time())
    for name in cfg.roles:
        ROLES[name](ctx)
    store.save_state(ctx["state"])
    failures = ctx["failures"]
    if failures and not ctx["answered"]:
        # A message the node's status shows, which can be seen beyond this machine: reasons only, never a name.
        raise RuntimeError(f"wyze-camera: {len(failures)} of {len(failures)} request(s) failed: {failures[0]}")
    if failures:
        config.log.warning("wyze-camera: %d request(s) failed this poll: %s", len(failures),
                           "; ".join(sorted(set(failures))))
    return [], []
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 packs/wyze-camera/tests/test_adapter.py`
Expected: four `  …` lines, then `adapter: ok`.

- [ ] **Step 5: Commit**

```bash
git add packs/wyze-camera/adapter.py packs/wyze-camera/tests/test_adapter.py
git commit -m "wyze-camera: the adapter, which gives the node nothing"
```

---

### Task 6: The three scripts

**Files:**
- Create: `packs/wyze-camera/status.py`
- Create: `packs/wyze-camera/events.py`
- Create: `packs/wyze-camera/snapshot.py`
- Test: `packs/wyze-camera/tests/test_scripts.py`

**Interfaces:**
- Consumes: `config.load`, `config.slug`, `Bridge`, `BridgeError`, `Store`, `iso`.
- Produces: in each script, `main(argv: list[str], hc=None, out=print) -> int`. With `hc=None` the script builds `httpx.Client(timeout=10)`. `planetai run wyze-camera <script> [args]` runs `if __name__ == "__main__": sys.exit(main(sys.argv[1:]))`.

- [ ] **Step 1: Write the failing test**

`packs/wyze-camera/tests/test_scripts.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 packs/wyze-camera/tests/test_scripts.py`
Expected: FAIL with `FileNotFoundError` (no `status.py`).

- [ ] **Step 3: Write the scripts**

`packs/wyze-camera/status.py`:

```python
"""planetai run wyze-camera status: whether the bridge answers, and per camera its last motion, its events over the
last day and week, and its snapshots. Run at the node's own terminal; this is one of the places camera names print."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wyzecam import config  # noqa: E402
from wyzecam.bridge import Bridge, BridgeError  # noqa: E402
from wyzecam.store import Store, iso  # noqa: E402


def main(argv, hc=None, out=print) -> int:
    cfg = config.load()
    if not cfg.ready:
        out("wyze-camera is idle: set WYZE_BRIDGE_URL and WYZE_CAMERAS (Set up, Packs, or .env).")
        return 1
    if hc is None:
        import httpx
        hc = httpx.Client(timeout=10)
    bridge, store, now = Bridge(hc, cfg.url, cfg.token), Store(cfg.out), time.time()
    day, week, imgs = store.events(now - 86400), store.events(now - 7 * 86400), store.images()
    out(f"bridge {cfg.url} · roles {', '.join(cfg.roles) or 'none'} · keeping {cfg.keep_days} days")
    for cam in cfg.cameras:
        try:
            ts = bridge.motion_ts(cam)
            seen = iso(ts) if ts else "never (is MOTION_API=True set in the bridge?)"
            line = f"last motion {seen}"
        except BridgeError as e:
            line = f"no answer: {e}"
        mine = [p for p in imgs if p.parent.name == config.slug(cam)]
        mb = sum(p.stat().st_size for p in mine) / 1048576
        out(f"  {cam}: {line} · events {sum(e['camera'] == cam for e in day)} in 24 h, "
            f"{sum(e['camera'] == cam for e in week)} in 7 days · {len(mine)} snapshots, {mb:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

`packs/wyze-camera/events.py`:

```python
"""planetai run wyze-camera events [--hours N]: the motion events from the local log, the last 24 hours by default."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wyzecam import config  # noqa: E402
from wyzecam.store import Store  # noqa: E402


def main(argv, hc=None, out=print) -> int:
    hours = 24
    if argv[:1] == ["--hours"]:
        try:
            hours = float(argv[1])
        except (IndexError, ValueError):
            out("usage: planetai run wyze-camera events [--hours N]")
            return 2
    events = Store(config.load().out).events(since=time.time() - hours * 3600)
    for e in events:
        out(f"{e['motion_at']}  {e['camera']}  (seen by the node {e['seen_at']})")
    out(f"{len(events)} event(s) in the last {hours:g} h")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

`packs/wyze-camera/snapshot.py`:

```python
"""planetai run wyze-camera snapshot [camera]: one still now from each camera, or from the one named, saved in
out/wyze-camera/snapshots on this node's disk. It works whether or not the snapshots role is on."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wyzecam import config  # noqa: E402
from wyzecam.bridge import Bridge, BridgeError  # noqa: E402
from wyzecam.store import Store  # noqa: E402


def main(argv, hc=None, out=print) -> int:
    cfg = config.load()
    if not cfg.ready:
        out("wyze-camera is idle: set WYZE_BRIDGE_URL and WYZE_CAMERAS (Set up, Packs, or .env).")
        return 1
    cams = cfg.cameras
    if argv:
        if argv[0] not in cfg.cameras:
            out(f"{argv[0]} is not in WYZE_CAMERAS ({', '.join(cfg.cameras)})")
            return 2
        cams = (argv[0],)
    if hc is None:
        import httpx
        hc = httpx.Client(timeout=10)
    bridge, store, now, failed = Bridge(hc, cfg.url, cfg.token), Store(cfg.out), time.time(), 0
    for cam in cams:
        try:
            out(f"{cam}: saved {store.save_image(cam, bridge.image(cam), 'manual', now)}")
        except BridgeError as e:
            out(f"{cam}: {e}")
            failed += 1
    store.prune_images(cfg.keep_days, cfg.snap_max_mb, now)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 packs/wyze-camera/tests/test_scripts.py`
Expected: four `  …` lines, then `scripts: ok`.

- [ ] **Step 5: Run every test in the pack**

Run: `for t in packs/wyze-camera/tests/test_*.py; do python3 "$t" | tail -1; done`
Expected: `config: ok`, `bridge: ok`, `store: ok`, `roles: ok`, `adapter: ok`, `scripts: ok`.

- [ ] **Step 6: Commit**

```bash
git add packs/wyze-camera/status.py packs/wyze-camera/events.py packs/wyze-camera/snapshot.py packs/wyze-camera/tests/test_scripts.py
git commit -m "wyze-camera: status, events and snapshot scripts"
```

---

### Task 7: README, the list entry, and the repository's own check

**Files:**
- Create: `packs/wyze-camera/README.md`
- Modify: `packs.json`
- Modify: `.github/CODEOWNERS`
- Modify: `packs/wyze-camera/pack.yaml` (the `requires:` line only)

**Interfaces:**
- Consumes: everything above; `tools/check.py` and `tools/test_check.py` in this repository; a checkout of fabcity/planetai-node's `main`.

- [ ] **Step 1: Write the README**

`packs/wyze-camera/README.md`:

````markdown
# wyze-camera

Wyze cameras on a PLANETAI node, through [docker-wyze-bridge](https://github.com/mrlt8/docker-wyze-bridge). It records
motion events and saves snapshots on the node's own disk, in `out/wyze-camera/`. A wild pack, Apache-2.0.

## What it does, and what it never does

- **Motion.** Every poll (five minutes by default) it asks the bridge when each camera last saw motion, and logs any
  newer time to `out/wyze-camera/motion.jsonl`, with the time Wyze recorded it. Detection is Wyze's own, read from
  Wyze's cloud by the bridge.
- **Snapshots.** On request, on motion (Wyze's own event image when the bridge has it), and on a schedule, saved to
  `out/wyze-camera/snapshots/<camera>/`. Automatic capture is off until you turn it on.
- **It gives the node nothing.** No sensors and no readings, so nothing reaches the database, the daily export (which
  is published as open data), the upstream aggregates or any API. Nothing in the node serves, backs up or exports
  `out/wyze-camera/`. Error messages in the node's status never name a camera.
- **Your Wyze account never touches the node.** Your email, password and Wyze API key go only into the bridge.

Tell the people who live or stay with you that the camera saves stills. In some places that is a legal requirement.

## Setting up the bridge

Run docker-wyze-bridge on your network, with its motion API on. You need a Wyze API ID and key from
https://developer-api-console.wyze.com. A minimal `docker-compose.yml`:

```yaml
services:
  wyze-bridge:
    image: mrlt8/wyze-bridge:latest
    restart: unless-stopped
    ports: ["5000:5000"]
    environment:
      - WYZE_EMAIL=you@example.com
      - WYZE_PASSWORD=your-wyze-password
      - API_ID=your-wyze-api-id
      - API_KEY=your-wyze-api-key
      - MOTION_API=True
```

Its log prints `WB_API=…`: that is the key for `WYZE_BRIDGE_TOKEN`. Its web page at `http://<bridge>:5000` shows each
camera's name (for `WYZE_CAMERAS`) and a live view.

## Adding it to your node

```
planetai packs add wyze-camera
```

Then in Set up, Packs, Wyze cameras (or in `.env`): `WYZE_BRIDGE_URL`, `WYZE_BRIDGE_TOKEN`, `WYZE_CAMERAS`, and
optionally `WYZE_ROLES` (`motion`, `snapshots`), `WYZE_SNAPSHOT_ON_MOTION`, `WYZE_SNAPSHOT_EVERY` (minutes),
`WYZE_KEEP_DAYS` (30) and `WYZE_SNAPSHOT_MAX_MB` (500). It is a code pack, so the node needs `PACKS_ALLOW_CODE=1`.

```
planetai run wyze-camera status
planetai run wyze-camera events --hours 24
planetai run wyze-camera snapshot [camera]
```

## What it does not know

- Motion within one poll is one event. Wyze's free plan already spaces events about five minutes apart.
- A camera that has never reported motion reads "never": the bridge cannot say whether its `MOTION_API` is on.
- It depends on Wyze's cloud and on docker-wyze-bridge, whose last release is v2.10.3 (September 2024).
- The design, and why: `docs/superpowers/specs/2026-10-03-wyze-camera-pack-design.md` in fabcity/planetai-wild-packs.
````

- [ ] **Step 2: Add the list entry and the code owner**

`packs.json` becomes (it was `[]`):

```json
[
  {
    "id": "wyze-camera",
    "name": "Wyze cameras",
    "source": "fabcity/planetai-wild-packs/packs/wyze-camera",
    "author": "Tomas Diez (Fab City Foundation)",
    "reads": "Wyze motion times and stills from docker-wyze-bridge on the local network",
    "kind": "code",
    "licence": "Apache-2.0",
    "tested_with": "v0.76",
    "status": "listed"
  }
]
```

Append to `.github/CODEOWNERS`:

```
/packs/wyze-camera/     @tomasdiez
```

- [ ] **Step 3: Run this repository's check against node main**

`check.py` copies each listed pack into the `packs/` folder of the node checkout it is given, so give it a throwaway
export of node main, never a real checkout, and a fresh one each run (a second run over the same export refuses,
because the pack's folder is already there):

```bash
python3 tools/test_check.py
NODE="$(mktemp -d)"
git -C "/Users/tomasdiez/Documents/Claude/Projects/FAB CITY/planetai-node-main" fetch -q origin main
git -C "/Users/tomasdiez/Documents/Claude/Projects/FAB CITY/planetai-node-main" archive origin/main | tar x -C "$NODE"
python3 tools/check.py --node "$NODE"
```

Expected: `check.py: the index rules hold`, then each step of `check.py` printed with two spaces, the last two
`6 pack test file(s) pass` and `ok`.

- [ ] **Step 4: Set `requires:` to the release that carries pack secrets**

Run: `git -C "/Users/tomasdiez/Documents/Claude/Projects/FAB CITY/planetai-node-main" fetch -q --tags origin && git -C "/Users/tomasdiez/Documents/Claude/Projects/FAB CITY/planetai-node-main" tag --contains f8fcc81 | sort -V | head -1`

- If it prints a tag (say `v0.77`), set `requires: { node: ">=0.77" }` in `pack.yaml`, and `tested_with` in
  `packs.json` to that tag, then rerun Step 3.
- If it prints nothing, no release carries pack secrets yet. Stop here and tell Tomas: the pack must not ship before
  that release, or its token would show in plain text in Set up on every node running it. Everything else may be
  committed; the pull request waits.

- [ ] **Step 5: Commit**

```bash
git add packs/wyze-camera/README.md packs.json .github/CODEOWNERS packs/wyze-camera/pack.yaml
git commit -m "wyze-camera: README, the list entry, its code owner"
```

---

### Task 8: Live check against a real bridge, then the pull request

This task needs Tomas: he runs the bridge and enters his Wyze credentials there. Never ask for them, type them or read them back.

**Files:**
- Modify (only if the live answers differ from the source reading): `packs/wyze-camera/wyzecam/bridge.py`, `packs/wyze-camera/tests/fakes.py`, `packs/wyze-camera/tests/test_bridge.py`, the spec's "Read from the bridge's source" section.

- [ ] **Step 1: Ask Tomas to start the bridge** with the compose snippet from the README, and to give the bridge's address, its `WB_API` key and one camera name. The key is a secret: he types it into the commands himself, or into `.env`.

- [ ] **Step 2: Check the three answers the client depends on**

Tomas runs, with his own values:

```bash
curl -s -H "api: $WB_API" "http://<bridge>:5000/api/<cam>/motion_ts"
curl -s -o /tmp/s.jpg -w "%{http_code} %{content_type}\n" -H "api: $WB_API" "http://<bridge>:5000/snapshot/<cam>.jpg"
curl -s -o /tmp/t.jpg -w "%{http_code} %{content_type}\n" -H "api: $WB_API" "http://<bridge>:5000/thumb/<cam>.jpg"
```

Expected: a JSON object with `"status": "success"` and a numeric `"value"`; `200 image/jpeg` twice. Then walk in front of
the camera, wait a minute, and run the first command again: `value` must have grown, and the new `/thumb` image must
show the motion, not an older scene. If any answer differs, change `bridge.py` and `fakes.py` to match what the bridge
really sends, add a test for it, record it in the spec, and commit.

- [ ] **Step 3: Install on the node on the same network** (from the branch, before it is listed):

```bash
planetai packs add fabcity/planetai-wild-packs/packs/wyze-camera@wyze-camera-pack-2026-10-03
```

Set the settings in Set up, Packs, Wyze cameras, with `PACKS_ALLOW_CODE=1`, then `planetai restart`. Confirm:
`planetai run wyze-camera status` names the camera and its last motion; after a movement and one poll,
`planetai run wyze-camera events` shows it; `planetai run wyze-camera snapshot` saves a JPEG that opens; Set up shows
`WYZE_BRIDGE_TOKEN` masked; `planetai status` shows no failing source; the node's `/sensors` has no `wyze` sensor.

- [ ] **Step 4: Push and open the pull request**

```bash
git push -u origin wyze-camera-pack-2026-10-03
gh pr create --repo fabcity/planetai-wild-packs --base main --title "wyze-camera: Wyze motion and snapshots, kept on the node" --body "Adds the wyze-camera wild pack (spec: docs/superpowers/specs/2026-10-03-wyze-camera-pack-design.md; plan: docs/superpowers/plans/2026-10-03-wyze-camera-pack.md), its list entry and its code owner. Live-checked against a bridge on Tomas's network."
```

Then wait for this repository's check to pass on the pull request before asking Tomas to merge.
