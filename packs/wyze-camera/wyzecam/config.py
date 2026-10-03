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
        cameras=tuple(dict.fromkeys(c.strip() for c in os.getenv("WYZE_CAMERAS", "").split(",") if c.strip())),
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
