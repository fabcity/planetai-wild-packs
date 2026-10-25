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
