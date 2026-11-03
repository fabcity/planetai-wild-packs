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
from datetime import date as _date
from pathlib import Path

import yaml

KW_PER = 1025 * 9.81 ** 2 / (64 * math.pi) / 1000      # kW per metre of crest, per m² s: P = ρg²/(64π) H² T
FIRST_H, LAST_H = 5, 17          # the hours 05:00-06:00 to 17:00-18:00: sunset in Bali is about 18:00-18:40 all year
OFFSHORE_MAX_KMH, GLASSY_KMH = 25, 8
MIX_SHARE, MIX_APART = 0.25, 20

COMPASS = "N NNE NE ENE E ESE SE SSE S SSW SW WSW W WNW NW NNW".split()
WORDS = {
    "en": {"low": "low", "mid": "mid", "high": "high",
           "b_head": "🌊 Surf in the next two days", "b_best": "• {name}, best {f}:00–{t}:00 (good {runs})",
           "b_out": "• {name}, good {runs}, outside your hours", "b_big": " · big for you right now",
           "b_waves": "  waves {h} m every {t} s, from the {d}", "b_mix": ", mixed with {h} m every {t} s from the {d}",
           "b_power": "  power {kw} kW/m · wind {w} km/h", "b_from": " from the {d}", "b_off": ", offshore",
           "b_glassy": ", glassy", "b_tide": " · tide {x}", "b_none": "nothing looks good",
           "b_foot": "This comes from a 16 km model. Check before you go.\nHow was it? Write:",
           "days": "Monday Tuesday Wednesday Thursday Friday Saturday Sunday".split(),
           "months": "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(),
           "didnt": "Didn't go", "elsewhere": "Surfed somewhere else",
           "ask": "Anything to add? Size, crowd, how you felt. One line, or ignore me.",
           "ask_else": "Where, and how was it? One line, or ignore me."},
    "es": {"low": "baja", "mid": "media", "high": "alta",
           "b_head": "🌊 Olas en los próximos dos días", "b_best": "• {name}, mejor {f}:00–{t}:00 (bueno {runs})",
           "b_out": "• {name}, bueno {runs}, fuera de tu horario", "b_big": " · grande para ti ahora",
           "b_waves": "  olas {h} m cada {t} s, del {d}", "b_mix": ", mezcladas con {h} m cada {t} s del {d}",
           "b_power": "  potencia {kw} kW/m · viento {w} km/h", "b_from": " del {d}", "b_off": ", terral",
           "b_glassy": ", como un espejo", "b_tide": " · marea {x}", "b_none": "nada parece bueno",
           "b_foot": "Esto sale de un modelo de 16 km. Compruébalo antes de ir.\n¿Cómo estuvo? Escribe:",
           "days": "lunes martes miércoles jueves viernes sábado domingo".split(),
           "months": "ene feb mar abr may jun jul ago sep oct nov dic".split(),
           "didnt": "No fui", "elsewhere": "Surfeé en otro sitio",
           "ask": "¿Algo que añadir? Tamaño, gente, cómo te sentiste. Una línea, o ignórame.",
           "ask_else": "¿Dónde, y cómo estuvo? Una línea, o ignórame."},
    "id": {"low": "surut", "mid": "sedang", "high": "pasang",
           "b_head": "🌊 Ombak dua hari ke depan", "b_best": "• {name}, terbaik {f}:00–{t}:00 (bagus {runs})",
           "b_out": "• {name}, bagus {runs}, di luar jam bebasmu", "b_big": " · besar untukmu sekarang",
           "b_waves": "  ombak {h} m tiap {t} s, dari {d}", "b_mix": ", bercampur {h} m tiap {t} s dari {d}",
           "b_power": "  tenaga {kw} kW/m · angin {w} km/h", "b_from": " dari {d}", "b_off": ", dari darat",
           "b_glassy": ", mulus", "b_tide": " · air {x}", "b_none": "sepertinya tidak ada yang bagus",
           "b_foot": "Ini berasal dari model 16 km. Cek dulu sebelum berangkat.\nBagaimana ombaknya? Tulis:",
           "days": "Senin Selasa Rabu Kamis Jumat Sabtu Minggu".split(),
           "months": "Jan Feb Mar Apr Mei Jun Jul Agu Sep Okt Nov Des".split(),
           "didnt": "Tidak jadi pergi", "elsewhere": "Berselancar di tempat lain",
           "ask": "Ada yang mau ditambahkan? Ukuran, keramaian, perasaanmu. Satu baris, atau abaikan saja.",
           "ask_else": "Di mana, dan bagaimana ombaknya? Satu baris, atau abaikan saja."},
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
    """Inclusive runs of at least two passing hours, the first hour 05 and the last 17 (17:00-18:00)."""
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
    """Every good hour as `runs`; `window` is the session_h hours inside `hours` and inside a run with the lowest mean
    wind (earlier on a tie), `inside` True. When no full session fits, the same with session_h - 1 hours, down to one:
    the first length that fits wins. With none, `window` is the first run and `inside` False. The numbers are means over
    the window's hours, the direction, second swell and tide from its first hour."""
    session_h = max(1, int(session_h))
    runs = good_runs(spot, rows, min_period)
    out = {"good": bool(runs), "runs": runs, "window": None, "inside": False,
           "swell": None, "second": None, "kw": 0.0, "wind": None, "wdir": None, "tide": None}
    if not runs:
        return out
    by_hr = {r["hr"]: r for r in rows}
    mine = set(parse_hours(hours or DEFAULT_HOURS))
    best = None
    for n in range(session_h, 0, -1):               # a full session first, then shorter blocks down to one hour
        for a, b in runs:
            for f in range(a, b - n + 2):
                span = range(f, f + n)
                if all(h in mine for h in span):
                    w = _mean([by_hr[h]["wind"] for h in span])
                    if best is None or w < best[0]:
                        best = (w, f, f + n - 1)
        if best:
            break
    out["inside"] = best is not None
    f, t = best[1:] if best else runs[0]
    span = range(f, t + 1)
    lo, hi = _tide_range(rows)
    sw = [_swells(by_hr[h], spot, min_period) for h in span]
    first, second = sw[0]
    out.update(window=(f, t), second=second,
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


def pick(results: list[tuple[dict, dict]], n: int = 3) -> list[tuple[dict, dict]]:
    """Good spots only: his hours first, then by power, most first. At most n."""
    good = [r for r in results if r[1]["good"]]
    return sorted(good, key=lambda r: (not r[1]["inside"], -r[1]["kw"]))[:n]


def spot_block(spot: dict, a: dict, locale: str, comfort_kw: float) -> str:
    """The four lines of one spot: when, waves, power and wind and tide, the Windy link."""
    W = WORDS.get(locale, WORDS["en"])
    runs = ", ".join(f"{f:02d}:00–{t + 1:02d}:00" for f, t in a["runs"])     # end-exclusive, like the window
    if a["inside"]:
        f, t = a["window"]
        l1 = W["b_best"].format(name=spot["name"], f=f"{f:02d}", t=f"{t + 1:02d}", runs=runs)
    else:
        l1 = W["b_out"].format(name=spot["name"], runs=runs)
    if round(a["kw"]) > comfort_kw:  # the power the line prints
        l1 += W["b_big"]
    s = a["swell"]
    l2 = W["b_waves"].format(h=f"{s['h']:.1f}", t=f"{s['t']:.0f}", d=_compass(s["dir"], locale))
    if a.get("second"):
        x = a["second"]
        l2 += W["b_mix"].format(h=f"{x['h']:.1f}", t=f"{x['t']:.0f}", d=_compass(x["dir"], locale))
    off = a["wdir"] is not None and within(a["wdir"], spot["offshore"])
    glassy = round(a["wind"]) < GLASSY_KMH and not off  # the wind the line prints
    l3 = W["b_power"].format(kw=f"{a['kw']:.0f}", w=f"{a['wind']:.0f}")
    if a["wdir"] is not None and not glassy:
        l3 += W["b_from"].format(d=_compass(a["wdir"], locale))
    l3 += W["b_off"] if off else W["b_glassy"] if glassy else ""
    if a.get("tide"):
        l3 += W["b_tide"].format(x=W[a["tide"]])
    return "\n".join((l1, l2, l3, "  " + windy(spot)))


def day_text(date: str, picked: list[tuple[dict, dict]], locale: str, comfort_kw: float) -> str:
    """"Wednesday 4 Nov" and the blocks, or the heading and that nothing looks good."""
    W = WORDS.get(locale, WORDS["en"])
    d = _date.fromisoformat(date)
    head = f"{W['days'][d.weekday()]} {d.day} {W['months'][d.month - 1]}"
    if not picked:
        return f"{head}: {W['b_none']}"
    return "\n".join([head] + [spot_block(sp, a, locale, comfort_kw) for sp, a in picked])


def message(days: list[tuple[str, list]], locale: str, comfort_kw: float) -> str:
    """The evening message. The rule appends ` {act} <your words>` to it; buttons come under it when the node sends them."""
    W = WORDS.get(locale, WORDS["en"])
    body = "\n\n".join(day_text(d, p, locale, comfort_kw) for d, p in days)
    return f"{W['b_head']}\n\n{body}\n\n{W['b_foot']}"


def keyboard(spots: list[dict]) -> list[list[dict]]:
    """Rating row per spot, then the two catch-alls. The shape is the node's `buttons` contract."""
    if not spots:
        return []
    L = ("en", "es", "id")
    ask = {loc: WORDS[loc]["ask"] for loc in L}
    rows = []
    for sp in spots:
        rows.append([{"text": {loc: f"{sp['name']} {e}" if e == "👍" else e for loc in L}, "value": f"{sp['id']}:{r}",
                      "stage": "acted", "ask": dict(ask)} for e, r in (("👍", "good"), ("👌", "ok"), ("👎", "poor"))])
    rows.append([{"text": {loc: WORDS[loc]["didnt"] for loc in L}, "value": "didnt-go", "stage": "acknowledged"},
                 {"text": {loc: WORDS[loc]["elsewhere"] for loc in L}, "value": "elsewhere", "stage": "acted",
                  "ask": {loc: WORDS[loc]["ask_else"] for loc in L}}])
    return rows
