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

    def _rewrite_log(self, events: list[dict]) -> None:
        _write(self.log_file, "".join(json.dumps(e, sort_keys=True) + "\n" for e in events))

    def add_events(self, events: list[dict], keep_days: int, now: float) -> None:
        self._rewrite_log(self.events(since=now - keep_days * 86400) + list(events))

    def prune_events(self, keep_days: int, now: float) -> None:
        """Drop events past keep_days. The file is only rewritten when something in it is old (or not an event)."""
        try:
            n = len(self.log_file.read_text().splitlines())
        except FileNotFoundError:
            return
        kept = self.events(since=now - keep_days * 86400)
        if len(kept) < n:
            self._rewrite_log(kept)

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
