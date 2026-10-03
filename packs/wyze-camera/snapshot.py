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
