"""Where surf could be good tomorrow, from Open-Meteo's hourly swell, tide and wind (design: docs/superpowers/specs/
2026-11-02-surf-pack-design.md, §5). Pure Python, no network: adapter.py fetches and stores, review.py journals, and
both judge with this.

An hour passes when four things hold: a swell from the spot's window, at SURF_MIN_PERIOD seconds or more, with its
power inside the spot's range; the wind offshore and at most 25 km/h, or under 8 km/h from anywhere; the tide in a
third of the day's range the spot accepts; and a wind sea under half the swell's height. Two passing hours in a row
between 05:00 and 18:00 make a good run, and a spot with one is good. Its window is the best SURF_SESSION_H hours
inside SURF_HOURS, or the first run when none fit. Every number is a first guess.
"""
from __future__ import annotations

import math
from pathlib import Path

import yaml

KW_PER = 1025 * 9.81 ** 2 / (64 * math.pi) / 1000      # kW per metre of crest, per m² s: P = ρg²/(64π) H² T
FIRST_H, LAST_H = 5, 18
OFFSHORE_MAX_KMH, GLASSY_KMH = 25, 8
MIX_SHARE, MIX_APART = 0.25, 20

COMPASS = "N NNE NE ENE E ESE SE SSE S SSW SW WSW W WNW NW NNW".split()
WORDS = {
    "en": {"swell": "{h} m at {t} s from the {d}", "mix": ", mixed with {h} m at {t} s from the {d}",
           "wind": "wind {w} km/h {d} ({how})", "offshore": "offshore", "light": "light",
           "tide": "{x} tide", "low": "low", "mid": "mid", "high": "high"},
    "es": {"swell": "{h} m a {t} s del {d}", "mix": ", mezclado con {h} m a {t} s del {d}",
           "wind": "viento {w} km/h {d} ({how})", "offshore": "terral", "light": "flojo",
           "tide": "marea {x}", "low": "baja", "mid": "media", "high": "alta"},
    "id": {"swell": "{h} m, {t} s dari {d}", "mix": ", bercampur {h} m, {t} s dari {d}",
           "wind": "angin {w} km/h {d} ({how})", "offshore": "dari darat", "light": "lemah",
           "tide": "air {x}", "low": "surut", "mid": "sedang", "high": "pasang"},
}


def power(h: float, t: float) -> float:
    return KW_PER * h * h * t


def load_spots(path) -> dict[str, dict]:
    out = {}
    for s in yaml.safe_load(Path(path).read_text()):
        out[s["id"]] = {"id": s["id"], "name": s["name"], "lat": float(s["at"][0]), "lon": float(s["at"][1]),
                        "swell": tuple(s["swell"]), "offshore": tuple(s["offshore"]), "kw": tuple(s["kw"]),
                        "tide": set(s["tide"]), "aliases": list(s.get("aliases") or [])}
    return out


def within(deg: float, arc: tuple[float, float]) -> bool:
    lo, hi = arc
    return lo <= deg <= hi if lo <= hi else deg >= lo or deg <= hi


def _apart(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


def tide_class(level: float | None, lo: float, hi: float) -> str | None:
    if level is None or lo is None:
        return None
    if hi == lo:
        return "mid"
    f = (level - lo) / (hi - lo)
    return "low" if f < 1 / 3 else "mid" if f < 2 / 3 else "high"


def day_rows(swell: dict, tide: dict, wind: dict, date: str) -> list[dict]:
    """One location's three Open-Meteo responses, as the 24 local hours of `date`. A value missing anywhere is None."""
    def by_time(resp, keys):
        h = resp.get("hourly") or {}
        return {t: {k: (h.get(k) or [None] * len(h["time"]))[i] for k in keys} for i, t in enumerate(h.get("time", []))}
    sw = by_time(swell, ["swell_wave_height", "swell_wave_period", "swell_wave_direction", "secondary_swell_wave_height",
                         "secondary_swell_wave_period", "secondary_swell_wave_direction", "wind_wave_height"])
    td = by_time(tide, ["sea_level_height_msl"])
    wd = by_time(wind, ["wind_speed_10m", "wind_direction_10m"])
    rows = []
    for hr in range(24):
        t = f"{date}T{hr:02d}:00"
        s, x, w = sw.get(t, {}), td.get(t, {}), wd.get(t, {})
        rows.append({"hr": hr, "h1": s.get("swell_wave_height"), "t1": s.get("swell_wave_period"),
                     "d1": s.get("swell_wave_direction"), "h2": s.get("secondary_swell_wave_height"),
                     "t2": s.get("secondary_swell_wave_period"), "d2": s.get("secondary_swell_wave_direction"),
                     "ww": s.get("wind_wave_height"), "wind": w.get("wind_speed_10m"),
                     "wdir": w.get("wind_direction_10m"), "sea": x.get("sea_level_height_msl")})
    return rows


def _swells(r: dict, spot: dict, min_period: float) -> tuple[dict | None, dict | None]:
    """The in-window swell that counts (more power), and the second one when the sea is mixed."""
    c = []
    for h, t, d in ((r["h1"], r["t1"], r["d1"]), (r["h2"], r["t2"], r["d2"])):
        if None not in (h, t, d) and h > 0 and within(d, spot["swell"]) and t >= min_period:
            c.append({"h": h, "t": t, "dir": d, "kw": power(h, t)})
    c.sort(key=lambda s: -s["kw"])
    if not c:
        return None, None
    if len(c) == 2 and c[1]["kw"] >= MIX_SHARE * c[0]["kw"] and _apart(c[0]["dir"], c[1]["dir"]) >= MIX_APART:
        return c[0], c[1]
    return c[0], None


def _passes(r: dict, spot: dict, min_period: float, lo, hi) -> bool:
    s, _ = _swells(r, spot, min_period)
    if not s or not spot["kw"][0] <= s["kw"] <= spot["kw"][1]:
        return False
    w, wd = r["wind"], r["wdir"]
    if w is None or not (w < GLASSY_KMH or (wd is not None and within(wd, spot["offshore"]) and w <= OFFSHORE_MAX_KMH)):
        return False
    if tide_class(r["sea"], lo, hi) not in spot["tide"]:
        return False
    return r["ww"] is not None and r["ww"] < 0.5 * s["h"]


DEFAULT_HOURS = "08:30-12:00,16:00-18:30"


def _hours(s: str) -> list[int]:
    out = set()
    for part in s.split(","):
        a, b = part.strip().split("-")
        (ah, am), (bh, bm) = (map(int, x.split(":")) for x in (a, b))
        out |= {h for h in range(24) if ah * 60 + am <= h * 60 and h * 60 + 60 <= bh * 60 + bm}
    if not out:
        raise ValueError(s)
    return sorted(out)


def parse_hours(s: str) -> list[int]:
    """"08:30-12:00,16:00-18:30" -> [9, 10, 11, 16, 17]: the hourly rows h with start <= h:00 and h:00 + 1 h <= end.
    Anything malformed gives the default's hours; the adapter warns."""
    try:
        return _hours(s)
    except (AttributeError, ValueError):
        return _hours(DEFAULT_HOURS)


def _tide_range(rows):
    seas = [r["sea"] for r in rows if r["sea"] is not None]
    return (min(seas), max(seas)) if seas else (None, None)


def good_runs(spot: dict, rows: list[dict], min_period: float = 10.0) -> list[tuple[int, int]]:
    """Inclusive runs of at least two passing hours between 05 and 18."""
    lo, hi = _tide_range(rows)
    by_hr = {r["hr"]: r for r in rows}
    runs, run = [], []
    for hr in range(FIRST_H, LAST_H + 2):
        if hr <= LAST_H and hr in by_hr and _passes(by_hr[hr], spot, min_period, lo, hi):
            run.append(hr)
            continue
        if len(run) >= 2:
            runs.append((run[0], run[-1]))
        run = []
    return runs


def _mean(xs):
    return sum(xs) / len(xs)


def assess(spot: dict, rows: list[dict], min_period: float = 10.0, hours: str | None = None, session_h: int = 2) -> dict:
    """Every good hour as `runs`; `window` is the session_h hours inside `hours` with the lowest mean wind (earlier on a
    tie), `inside` True. With none, `window` is the first run and `inside` False. The numbers are means over the window's
    hours, the direction, second swell and tide from its first hour."""
    runs = good_runs(spot, rows, min_period)
    out = {"good": bool(runs), "runs": runs, "window": None, "inside": False, "from_h": None, "to_h": None,
           "swell": None, "second": None, "kw": 0.0, "wind": None, "wdir": None, "tide": None}
    if not runs:
        return out
    by_hr = {r["hr"]: r for r in rows}
    mine = set(parse_hours(hours or DEFAULT_HOURS))
    best = None
    for a, b in runs:
        for f in range(a, b - session_h + 2):
            span = range(f, f + session_h)
            if all(h in mine for h in span):
                w = _mean([by_hr[h]["wind"] for h in span])
                if best is None or w < best[0]:
                    best = (w, f, f + session_h - 1)
    out["inside"] = best is not None
    f, t = best[1:] if best else runs[0]
    span = range(f, t + 1)
    lo, hi = _tide_range(rows)
    sw = [_swells(by_hr[h], spot, min_period) for h in span]
    first, second = sw[0]
    out.update(window=(f, t), from_h=f, to_h=t, second=second,
               swell={"h": _mean([s["h"] for s, _ in sw]), "t": _mean([s["t"] for s, _ in sw]), "dir": first["dir"],
                      "kw": _mean([s["kw"] for s, _ in sw])},
               kw=_mean([s["kw"] for s, _ in sw]), wind=_mean([by_hr[h]["wind"] for h in span]),
               wdir=by_hr[f]["wdir"], tide=tide_class(by_hr[f]["sea"], lo, hi))
    return out


def _compass(deg: float, locale: str) -> str:
    c = COMPASS[round(deg / 22.5) % 16]
    return c.replace("W", "O") if locale == "es" else c


def windy(spot: dict) -> str:
    lat, lon = f"{spot['lat']:.3f}", f"{spot['lon']:.3f}"
    return f"https://www.windy.com/{lat}/{lon}?swell1,{lat},{lon},12"


def line(spot: dict, a: dict, locale: str) -> str:
    W = WORDS.get(locale, WORDS["en"])
    s = a["swell"]
    out = f"• {spot['name']} {a['from_h']}–{a['to_h']}: "
    out += W["swell"].format(h=f"{s['h']:.1f}", t=f"{s['t']:.0f}", d=_compass(s["dir"], locale))
    out += f", {a['kw']:.0f} kW/m"
    if a.get("second"):
        x = a["second"]
        out += W["mix"].format(h=f"{x['h']:.1f}", t=f"{x['t']:.0f}", d=_compass(x["dir"], locale))
    off = a["wdir"] is not None and within(a["wdir"], spot["offshore"])
    out += ", " + W["wind"].format(w=f"{a['wind']:.0f}", d=_compass(a["wdir"], locale) if a["wdir"] is not None else "",
                                   how=W["offshore" if off else "light"])
    if a.get("tide"):
        out += ", " + W["tide"].format(x=W[a["tide"]])
    return out + " → " + windy(spot)
