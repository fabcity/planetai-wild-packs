"""`planetai run surf ask <name>`: one spot, watched or not, fetched now with the adapter's three calls and printed as
the message's own two day blocks. Never touches the stamp file. Run: python3 packs/surf/tests/test_ask.py
"""
import contextlib
import io
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import adapter as A  # noqa: E402
import ask  # noqa: E402

FX = {k: json.loads((HERE / "fixtures" / f"{k}.json").read_text()) for k in ("swell", "tide", "wind")}
A._now = lambda: datetime(2026, 10, 27, 9, 0, tzinfo=timezone.utc)     # 17:00 in Bali: 28 and 29 October follow
calls = []


def fake_get(url, params=None):
    calls.append((url, dict(params or {})))
    kind = "wind" if url.startswith("https://api.open-meteo.com") else "swell" if params.get("models") else "tide"
    return FX[kind][0]                                   # one location comes back as an object


ask._get = fake_get
for k in ("SURF_SPOTS", "SURF_MIN_PERIOD", "SURF_HOURS", "SURF_SESSION_H", "SURF_COMFORT_KW", "ALERT_LOCALE"):
    os.environ.pop(k, None)
os.environ["PACK_OUT"] = tempfile.mkdtemp()
stamp = Path(os.environ["PACK_OUT"]) / "surf.stamp"
stamp.touch()
os.utime(stamp, (1000, 1000))


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = ask.main(list(argv))
    return rc, out.getvalue(), err.getvalue()


rc, out, _ = run("ulu")                                  # an alias, not watched (SURF_SPOTS is blank)
assert rc == 0 and "Uluwatu" in out and "Wednesday 28 Oct" in out and "Thursday 29 Oct" in out, out
assert "How was it" not in out and "Tap below" not in out, "the two day blocks, not the evening message"
assert len(calls) == 3 and all(p["forecast_days"] == 3 and p["timezone"] == "auto" for _, p in calls), calls
assert sum(1 for _, p in calls if p.get("models") == "ncep_gfswave016") == 1
assert all(p["latitude"] == -8.815 and p["longitude"] == 115.087 for _, p in calls), calls
assert stamp.stat().st_mtime == 1000, "the stamp is the adapter's"
print("  ask ulu: both days in the message's format, three calls for one location, stamp untouched")

os.environ["ALERT_LOCALE"] = "es"
rc, out, _ = run("Padang", "Padang")                     # several words, found by name; nothing good there is fine
assert rc == 0 and "miércoles 28 oct" in out and "jueves 29 oct" in out, out
print("  ALERT_LOCALE picks the language; a name of two words works")

os.environ["ALERT_LOCALE"] = "en"
os.environ["SURF_COMFORT_KW"] = "0.1"                    # the same settings the adapter reads
rc, out, _ = run("uluwatu")
assert "big for you right now" in out, out
print("  SURF_COMFORT_KW is read from the environment")

calls.clear()
rc, out, _ = run("nowhere")
assert rc == 2 and calls == [], (rc, calls)
assert "Uluwatu" in out and "Nyang Nyang" in out, "an unknown name lists the spots"
rc, _, _ = run()
assert rc == 2, "no name is the same"
print("  an unknown name prints the spot names and returns 2, with no request")
print("surf ask: all checks passed")
