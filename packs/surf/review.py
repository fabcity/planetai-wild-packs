"""The surf journal: every evening's call that somebody answered, grouped by the spots they named, with that
morning's swell, power, wind and tide read back from Open-Meteo's archive. It is the note a surfer keeps of what each
spot liked (Grant's "Surf Info", from Swell Scope's guide), built from real sessions. Nothing extra is stored: the
alerts and their answers are the node's, the numbers are fetched again when asked for.

    planetai run surf review [--days 60]

A spot counts when the note names it, by id, name or alias (spots.yml), even if the message did not suggest it. The
hours shown are the window the message gave that spot, or 06:00 to 10:00. The thresholds are never changed from
here: a note is free text, and the people reading this are better at it than a parser.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import adapter as A  # noqa: E402
import surf as S  # noqa: E402

RULE = "surf/surf_tomorrow"
DEFAULT_HOURS = (6, 10)


def _names(spot: dict) -> list[str]:
    return [spot["id"], spot["name"], *spot["aliases"]]


def find_spots(note: str, spots: dict) -> list[str]:
    low, found = note.lower(), []
    for sid, sp in spots.items():
        at = [m.start() for n in _names(sp)
              for m in re.finditer(r"(?<![\w-])" + re.escape(n.lower()) + r"(?![\w-])", low)]
        if at:
            found.append((min(at), sid))
    return [sid for _, sid in sorted(found)]


def windows_in(text: str, spots: dict) -> dict[str, tuple[int, int]]:
    out = {}
    for sid, sp in spots.items():
        m = re.search(re.escape(sp["name"]) + r" (\d+)–(\d+):", text)
        if m:
            out[sid] = (int(m.group(1)), int(m.group(2)))
    return out


def _hours(rows: list[dict], spot: dict, span: tuple[int, int]) -> list[dict]:
    seas = [r["sea"] for r in rows if r["sea"] is not None]
    lo, hi = (min(seas), max(seas)) if seas else (None, None)
    out = []
    for r in rows:
        if span[0] <= r["hr"] <= span[1]:
            kw = lambda h, t: S.power(h, t) if None not in (h, t) else None  # noqa: E731
            out.append({**r, "kw": kw(r["h1"], r["t1"]), "kw2": kw(r["h2"], r["t2"]), "tide": S.tide_class(r["sea"], lo, hi)})
    return out


def journal(alerts: list[dict], actions: list[dict], spots: dict, fetch_day) -> dict[str, list[dict]]:
    notes = {}
    for a in actions:
        if a.get("stage") == "acted" and a.get("note"):
            notes.setdefault(a["alert_id"], []).append(a)
    out: dict[str, list[dict]] = {}
    for al in sorted((a for a in alerts if a.get("rule_id") == RULE), key=lambda a: a["ts"], reverse=True):
        day = (datetime.fromisoformat(al["ts"]).date() + timedelta(days=1)).isoformat()
        if al["id"] not in notes:
            out.setdefault("unanswered", []).append({"alert_id": al["id"], "date": day, "text": al.get("text", "")})
            continue
        win = windows_in(al.get("text", ""), spots)
        for n in notes[al["id"]]:
            for sid in find_spots(n["note"], spots):
                rows = fetch_day(spots[sid], day)
                out.setdefault(sid, []).append({"alert_id": al["id"], "date": day, "note": n["note"],
                                                "actor": n.get("actor", ""),
                                                "hours": _hours(rows, spots[sid], win.get(sid, DEFAULT_HOURS))})
    return out


def _f(v, fmt):
    return "–" if v is None else format(v, fmt)


def render(j: dict, spots: dict) -> str:
    lines = []
    for sid, sp in spots.items():
        if sid not in j:
            continue
        lines.append(sp["name"])
        for e in j[sid]:
            lines.append(f"  {e['date']}  \"{e['note']}\"  ({e['actor']}, #{e['alert_id']})")
            for h in e["hours"]:
                lines.append(f"    {h['hr']:02d}h  {_f(h['h1'], '.1f')} m {_f(h['t1'], '.0f')} s {_f(h['d1'], '.0f')}° "
                             f"{_f(h['kw'], '.0f')} kW/m | 2nd {_f(h['h2'], '.1f')} m {_f(h['t2'], '.0f')} s "
                             f"{_f(h['d2'], '.0f')}° | wind {_f(h['wind'], '.0f')} km/h {_f(h['wdir'], '.0f')}° | "
                             f"{h['tide'] or '–'}")
        lines.append("")
    if j.get("unanswered"):
        lines.append("Unanswered")
        lines += [f"  {e['date']}  #{e['alert_id']}" for e in j["unanswered"]]
    return "\n".join(lines) or "No surf messages in that time."


def _get(url: str, params: dict | None = None):
    with urllib.request.urlopen(url + ("?" + urllib.parse.urlencode(params) if params else ""), timeout=30) as r:
        return json.loads(r.read())


def archive_day(spot: dict, day: str) -> list[dict]:
    base = {"latitude": spot["lat"], "longitude": spot["lon"], "timezone": "auto", "start_date": day, "end_date": day}
    swell = _get(A.MARINE, {**base, "hourly": A.SWELL_VARS, "models": "ncep_gfswave016"})
    tide = _get(A.MARINE, {**base, "hourly": "sea_level_height_msl"})
    wind = _get(A.WEATHER, {**base, "hourly": "wind_speed_10m,wind_direction_10m"})
    return S.day_rows(swell, tide, wind, day)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="The surf journal: answered calls, by spot, with that morning's numbers.")
    p.add_argument("--days", type=int, default=60)
    days = p.parse_args(argv).days
    node = f"http://127.0.0.1:{os.getenv('PORT', '8080')}"
    alerts = _get(node + "/alerts", {"limit": 1000, "since_hours": min(days * 24, 2160)})
    actions = _get(node + "/actions", {"limit": 5000, "stage": "acted"})
    spots = S.load_spots(Path(_HERE) / "spots.yml")
    print(render(journal(alerts, actions, spots, archive_day), spots))
    return 0


if __name__ == "__main__":
    sys.exit(main())
