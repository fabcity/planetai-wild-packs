"""One spot's next two days, whether or not it is watched: the message's own day blocks for tomorrow and the day after,
fetched now with the adapter's three calls for that one location.

    planetai run surf ask <name>        name: an id, a name or an alias from spots.yml, e.g. bingin, ulu, "padang padang"

It stores nothing and never touches PACK_OUT/surf.stamp, so it cannot delay the adapter's next fetch. It reads the
adapter's settings (SURF_MIN_PERIOD, SURF_HOURS, SURF_SESSION_H, SURF_COMFORT_KW) and the language from ALERT_LOCALE.
An unknown name prints the spot names and exits 2.
"""
from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import adapter as A  # noqa: E402
import review as R  # noqa: E402
import surf as S  # noqa: E402

_get = R._get                                           # a script has no http client; the tests replace this


def main(argv=None) -> int:
    spots = S.load_spots(Path(_HERE) / "spots.yml")
    found = R.find_spots(" ".join(argv if argv is not None else sys.argv[1:]), spots)
    if not found:
        print("Which spot? " + ", ".join(sp["name"] for sp in spots.values()))
        return 2
    sp = spots[found[0]]
    base = {"latitude": sp["lat"], "longitude": sp["lon"], "timezone": "auto", "forecast_days": 3}
    swell = _get(A.MARINE, {**base, "hourly": A.SWELL_VARS, "models": "ncep_gfswave016"})
    tide = _get(A.MARINE, {**base, "hourly": "sea_level_height_msl"})
    wind = _get(A.WEATHER, {**base, "hourly": "wind_speed_10m,wind_direction_10m,wind_gusts_10m"})
    local = (A._now() + timedelta(seconds=swell.get("utc_offset_seconds", 0))).date()
    minp = float(os.getenv("SURF_MIN_PERIOD", "10") or 10)
    hours = os.getenv("SURF_HOURS", "") or None
    session_h = A._setting("SURF_SESSION_H", int, 2)
    comfort = A._setting("SURF_COMFORT_KW", float, 15)
    locale = os.getenv("ALERT_LOCALE", "en") or "en"
    days = []
    for n in (1, 2):
        day = (local + timedelta(days=n)).isoformat()
        a = S.assess(sp, S.day_rows(swell, tide, wind, day), minp, hours, session_h)
        days.append(S.day_text(day, S.pick([(sp, a)]), locale, comfort))
    print("\n\n".join(days))
    return 0


if __name__ == "__main__":
    sys.exit(main())
