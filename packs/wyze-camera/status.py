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
