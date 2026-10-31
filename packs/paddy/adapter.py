"""Rice still farmed, and rice land lost, in a square the keeper chooses. Sentinel-2 L2A, read once a day.

Read anonymously from Microsoft Planetary Computer (collection `sentinel-2-l2a`): red (B04) and near infrared (B08)
at 10 m, the scene classification (SCL) at 20 m, and with the flood check on, green (B03) at 10 m and short-wave
infrared (B11) at 20 m. Copernicus data, free and open with attribution; Microsoft is the host, not the publisher.

Every clear pixel of every scene lands in the month it was seen: its lowest and highest greenness (NDVI) that
month and its highest water index (MNDWI). 25 months are kept, one small file a month in out/paddy/. The rule then
puts every pixel of the square in exactly one of six states (see `classify`), and the pack stores the hectares.
Where the thresholds come from is in the README.

No new library. The app image has no numpy or rasterio, and this pack adds neither: `Cog` is surface-heat's
reader (same project, Apache-2.0) with one addition, because Planetary Computer packs Sentinel-2's bands into 15
bits a sample. The rule works on Python integers as rows of one-byte lanes, one lane per pixel, so a 10 km square's
25 months take seconds, not minutes.

Polite: one STAC search a day, at most one scene read per poll and PADDY_READS a day, each scene read once and
remembered in out/paddy/state.json. Nothing at all happens until the keeper sets PADDY_RADIUS_KM and
PADDY_FLOOD_CHECK in Set up.
"""
from __future__ import annotations

import json
import logging
import math
import os
import struct
import sys
import time
import zlib
from array import array
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("planetai.pack.paddy")

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
SAS = "https://planetarycomputer.microsoft.com/api/sas/v1/token"
COLLECTION = "sentinel-2-l2a"
ATTRIBUTION = "Contains modified Copernicus Sentinel data, read through Microsoft Planetary Computer."


def attribution(keys: list[str]) -> str:
    """The notice the Commission's legal notice asks of modified data, with the years it came from."""
    y = sorted({k[:4] for k in keys})
    years = f" {y[0]}" if len(y) == 1 else f" {y[0]}-{y[-1]}" if y else ""
    return f"Contains modified Copernicus Sentinel data{years}, read through Microsoft Planetary Computer."
SENSOR = "paddy-square"
DAY = 86400
MONTHS = 25            # two seasons of a one-crop place, four or five of a two-crop place
CLOUD_MAX = 50         # scene-level cloud cover the test on 30 Oct 2026 used
MIN_CLEAR = 0.2        # below this share of clear pixels in the square, B04 and B08 are not read at all
MAX_RADIUS_KM = 10
HEAD = 65536
CLEAR_SCL = (4, 5, 6)  # vegetation, bare soil, water

# Stored bytes. NDVI as NDVI x 100 + 100 (0..200); the monthly high is kept as 200 minus that, so that both NDVI
# arrays update with min() and 255 means "no clear look this month" in both. MNDWI as MNDWI x 100 + 101 (1..201),
# updated with max(), 0 meaning no look.
NONE = 255
GREEN, BARE, RECENT = 0.65, 0.35, 0.60       # a swing is a fall from above GREEN to below BARE, and back
LOST_GREEN, LOST_BARE = 0.55, 0.15           # lost: green the first year, nothing above LOST_BARE for 4 months
GREENISH, WATER_NDVI = 0.40, 0.0
FLOOD = 0.2                                  # MNDWI above this is standing water (Ebro and Segria, 30 Oct 2026)
RECENT_MONTHS, LAST_MONTHS, FIRST_MONTHS, MIN_MONTHS, CANOPY_WITHIN = 7, 4, 12, 8, 4
STATES = ("rice", "lost", "green", "bare_or_built", "water", "unclear")


# ---------------------------------------------------------------- projections, without pyproj (from surface-heat)

def utm(lat: float, lon: float, zone: int, south: bool) -> tuple[float, float]:
    """WGS84 to UTM metres, Snyder's series (USGS Professional Paper 1395). Good to millimetres inside a zone."""
    a, f, k0 = 6378137.0, 1 / 298.257223563, 0.9996
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    phi, lam = math.radians(lat), math.radians(lon - (zone * 6 - 183))
    s, c = math.sin(phi), math.cos(phi)
    n = a / math.sqrt(1 - e2 * s * s)
    t, cc, aa = math.tan(phi) ** 2, ep2 * c * c, lam * c
    m = a * ((1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256) * phi
             - (3 * e2 / 8 + 3 * e2 ** 2 / 32 + 45 * e2 ** 3 / 1024) * math.sin(2 * phi)
             + (15 * e2 ** 2 / 256 + 45 * e2 ** 3 / 1024) * math.sin(4 * phi)
             - (35 * e2 ** 3 / 3072) * math.sin(6 * phi))
    x = k0 * n * (aa + (1 - t + cc) * aa ** 3 / 6 + (5 - 18 * t + t * t + 72 * cc - 58 * ep2) * aa ** 5 / 120) + 500000
    y = k0 * (m + n * math.tan(phi) * (aa * aa / 2 + (5 - t + 9 * cc + 4 * cc * cc) * aa ** 4 / 24
                                       + (61 - 58 * t + t * t + 600 * cc - 330 * ep2) * aa ** 6 / 720))
    return x, y + (10000000.0 if south else 0.0)


def zone_epsg(lat: float, lon: float) -> int:
    return (32700 if lat < 0 else 32600) + int((lon + 180) // 6) % 60 + 1


def forward(epsg: int):
    return lambda la, lo: utm(la, lo, epsg % 100, epsg > 32700)


def local_inverse(fwd, lat: float, lon: float):
    """Projected metres back to lat/lon near one point, by the forward projection's Jacobian there. Within a few
    km it is off by well under a metre, and an H3 res-8 cell is hundreds of metres across."""
    d = 1e-4
    x0, y0 = fwd(lat, lon)
    xa, ya = fwd(lat + d, lon)
    xb, yb = fwd(lat, lon + d)
    a, b, c, e = (xa - x0) / d, (xb - x0) / d, (ya - y0) / d, (yb - y0) / d
    det = a * e - b * c
    return lambda x, y: (lat + (e * (x - x0) - b * (y - y0)) / det, lon + (a * (y - y0) - c * (x - x0)) / det)


# ---------------------------------------------------------------- the square

def grid(lat: float, lon: float, radius_km: float) -> dict:
    """The keeper's square on a 10 m grid in its UTM zone. The corner sits on a multiple of 20 m, as every
    Sentinel-2 tile's does, so a 10 m and a 20 m band both land on whole pixels."""
    epsg = zone_epsg(lat, lon)
    x, y = forward(epsg)(lat, lon)
    r = radius_km * 1000
    x0, y0 = math.floor((x - r) / 20) * 20, math.ceil((y + r) / 20) * 20
    side = math.ceil(2 * r / 20) * 2
    return {"epsg": epsg, "x0": x0, "y0": y0, "w": side, "h": side, "lat": lat, "lon": lon, "radius_km": radius_km}


def box(west: float, south: float, east: float, north: float) -> dict:
    """A box instead of a square, for `verify` to re-run a published test exactly."""
    lat, lon = (south + north) / 2, (west + east) / 2
    epsg = zone_epsg(lat, lon)
    fwd = forward(epsg)
    xs, ys = zip(*(fwd(la, lo) for la in (south, north) for lo in (west, east)))
    x0, y0 = math.floor(min(xs) / 20) * 20, math.ceil(max(ys) / 20) * 20
    w, h = math.ceil((max(xs) - x0) / 20) * 2, math.ceil((y0 - min(ys)) / 20) * 2
    return {"epsg": epsg, "x0": x0, "y0": y0, "w": w, "h": h, "lat": lat, "lon": lon, "box": [west, south, east, north]}


# ---------------------------------------------------------------- a COG over HTTP ranges (surface-heat's, plus 15 bits)

TYPES = {1: ("B", 1), 2: ("s", 1), 3: ("H", 2), 4: ("I", 4), 5: ("II", 8), 11: ("f", 4), 12: ("d", 8), 16: ("Q", 8)}


def unpack15(data: bytes, tw: int, th: int) -> array:
    """A tile of 15-bit samples, most significant bit first, each row padded to a whole byte. That is how
    Planetary Computer stores Sentinel-2's reflectance bands (NBITS=15). Matched rasterio on every one of a
    512 x 512 tile's pixels on 30 Oct 2026."""
    rowbytes = (tw * 15 + 7) // 8
    total, mask = rowbytes * 8, (1 << 15) - 1
    out = array("H")
    for row in range(th):
        v = int.from_bytes(data[row * rowbytes:(row + 1) * rowbytes], "big")
        out.extend((v >> (total - 15 * (j + 1))) & mask for j in range(tw))
    return out


class Cog:
    """Just enough of a Cloud-Optimized GeoTIFF to read a window of its full-resolution image: little-endian
    classic TIFF, one band, tiled, deflate or none, no predictor, 8, 15 or 16 bits. Anything else is refused by name
    rather than misread."""

    def __init__(self, get, url: str):
        self.get, self.url = get, url
        self.head = get(url, 0, HEAD - 1)
        if self.head[:4] != b"II*\x00":
            raise ValueError(f"{url.rsplit('/', 1)[-1]}: not a little-endian classic TIFF")
        off = struct.unpack_from("<I", self.head, 4)[0]
        self.tags = {}
        for i in range(struct.unpack_from("<H", self._bytes(off, 2), 0)[0]):
            tag, typ, n, val = struct.unpack_from("<HHII", self._bytes(off + 2 + 12 * i, 12), 0)
            fmt, size = TYPES.get(typ, ("B", 1))
            spec = f"<{n}s" if typ == 2 else "<" + fmt * n
            raw = self._bytes(off + 10 + 12 * i, 4) if size * n <= 4 else self._bytes(val, size * n)
            self.tags[tag] = struct.unpack_from(spec, raw)
        t = self.tags
        self.w, self.h = t[256][0], t[257][0]
        self.bits, comp, pred = t[258][0], t[259][0], t.get(317, (1,))[0]
        if 322 not in t or comp not in (1, 8, 32946) or pred != 1 or t.get(277, (1,))[0] != 1 or self.bits not in (8, 15, 16):
            raise ValueError(f"{url.rsplit('/', 1)[-1]}: a layout this reader does not handle "
                             f"(tiled={322 in t}, compression={comp}, predictor={pred}, bits={self.bits})")
        self.deflate = comp != 1
        self.tw, self.th = t[322][0], t[323][0]
        self.offsets, self.counts = t[324], t[325]
        self.sx, self.sy = t[33550][0], t[33550][1]
        i, j, _, x, y, _ = t[33922][:6]
        self.x0, self.y0 = x - i * self.sx, y + j * self.sy
        keys = t.get(34735, ())
        geo = {keys[k]: keys[k + 3] for k in range(4, len(keys) - 3, 4)}
        if geo.get(1025) == 2:                     # PixelIsPoint: the tie point is a pixel's centre
            self.x0, self.y0 = self.x0 - self.sx / 2, self.y0 + self.sy / 2
        self.epsg = geo.get(3072)

    def _bytes(self, start: int, n: int) -> bytes:
        if start + n <= len(self.head):
            return self.head[start:start + n]
        return self.get(self.url, start, start + n - 1)

    def tile(self, raw: bytes):
        data = zlib.decompress(raw) if self.deflate else raw
        if self.bits == 15:
            return unpack15(data, self.tw, self.th)
        t = array("H" if self.bits == 16 else "B", data)
        if self.bits == 16 and sys.byteorder == "big":
            t.byteswap()
        return t

    def window(self, x0: float, y0: float, w: int, h: int) -> list[int]:
        """w x h pixels whose top-left corner is the projected point (x0, y0), row by row. Pixels outside the image,
        and tiles stored with no bytes, are 0, which Sentinel-2 uses for no data."""
        c, r = (x0 - self.x0) / self.sx, (self.y0 - y0) / self.sy
        if abs(c - round(c)) > 1e-6 or abs(r - round(r)) > 1e-6:
            raise ValueError(f"{self.url.rsplit('/', 1)[-1]}: the square does not sit on this image's pixel grid")
        c, r = round(c), round(r)
        out = [0] * (w * h)
        r0, c0, r1, c1 = max(0, r), max(0, c), min(self.h, r + h), min(self.w, c + w)
        if r1 <= r0 or c1 <= c0:
            return out
        across = (self.w + self.tw - 1) // self.tw
        for tr in range(r0 // self.th, (r1 - 1) // self.th + 1):
            for tc in range(c0 // self.tw, (c1 - 1) // self.tw + 1):
                k = tr * across + tc
                if not self.counts[k]:
                    continue
                tile = self.tile(self.get(self.url, self.offsets[k], self.offsets[k] + self.counts[k] - 1))
                a, b = max(c0, tc * self.tw), min(c1, (tc + 1) * self.tw)
                for row in range(max(r0, tr * self.th), min(r1, (tr + 1) * self.th)):
                    s = (row - tr * self.th) * self.tw + (a - tc * self.tw)
                    d = (row - r) * w + (a - c)
                    out[d:d + (b - a)] = tile[s:s + (b - a)]
        return out


# ---------------------------------------------------------------- one scene

def offset(item: dict) -> int:
    """Since processing baseline 04.00 (January 2022) every reflectance carries +1000. The STAC items do not
    publish it (raster:bands was empty on baseline 05.13), so it comes from the baseline. Without it, greenness reads
    near zero everywhere and the square has no rice."""
    b = str(item["properties"].get("s2:processing_baseline") or "0")
    return 1000 if float(b) >= 4.0 else 0


def code_ndvi(red: int, nir: int, off: int) -> int:
    a, b = red - off, nir - off
    if not red or not nir or a + b <= 0:
        return NONE
    return max(0, min(200, round((b - a) / (a + b) * 100) + 100))


def code_mndwi(green: int, swir: int, off: int) -> int:
    a, b = green - off, swir - off
    if not green or not swir or a + b <= 0:
        return 0
    return max(1, min(201, round((a - b) / (a + b) * 100) + 101))


def look(scl: list[int], red, nir, green, swir, g: dict, off: int, flood: bool) -> tuple[bytes, bytes, bytes]:
    """One scene's pixels on the square, as the three stored bytes: lowest NDVI, 200 minus highest NDVI (the same
    value for one look), highest MNDWI. A pixel SCL does not call clear gets no look."""
    w, n = g["w"], g["w"] * g["h"]
    w2 = w // 2
    lo, hi, wet = bytearray(b"\xff" * n), bytearray(b"\xff" * n), bytearray(n)
    for i in range(n):
        r, c = divmod(i, w)
        j = (r // 2) * w2 + c // 2
        if scl[j] not in CLEAR_SCL:
            continue
        v = code_ndvi(red[i], nir[i], off)
        if v == NONE:
            continue
        lo[i], hi[i] = v, 200 - v
        if flood:
            wet[i] = code_mndwi(green[i], swir[j], off)
    return bytes(lo), bytes(hi), bytes(wet)


def read_scene(get, item: dict, g: dict, flood: bool):
    """(lo, hi, wet, clear share) for one scene, or (None, None, None, clear share) when too little is clear."""
    a = item["assets"]
    w, h = g["w"], g["h"]
    scl = Cog(get, a["SCL"]["href"]).window(g["x0"], g["y0"], w // 2, h // 2)
    share = sum(v in CLEAR_SCL for v in scl) / len(scl)
    if share < MIN_CLEAR:
        return None, None, None, share
    band = lambda k, f=1: Cog(get, a[k]["href"]).window(g["x0"], g["y0"], w // f, h // f)  # noqa: E731
    red, nir = band("B04"), band("B08")
    green, swir = (band("B03"), band("B11", 2)) if flood else (None, None)
    return (*look(scl, red, nir, green, swir, g, offset(item), flood), share)


# ---------------------------------------------------------------- months on disk

def blank(n: int) -> list[bytes]:
    return [b"\xff" * n, b"\xff" * n, bytes(n)]


def merge(month: list[bytes], lo: bytes, hi: bytes, wet: bytes) -> list[bytes]:
    return [bytes(map(min, month[0], lo)), bytes(map(min, month[1], hi)), bytes(map(max, month[2], wet))]


def month_keys(now: datetime, n: int = MONTHS) -> list[str]:
    y, m = now.year, now.month
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return out[::-1]


class Store:
    """One file a month, out/paddy/months/YYYY-MM.bin: the three arrays back to back, n bytes each."""

    def __init__(self, root: Path, n: int):
        self.dir, self.n = root / "months", n
        self.dir.mkdir(parents=True, exist_ok=True)

    def load(self, key: str) -> list[bytes] | None:
        try:
            b = (self.dir / f"{key}.bin").read_bytes()
        except OSError:
            return None
        if len(b) != 3 * self.n:
            return None
        return [b[:self.n], b[self.n:2 * self.n], b[2 * self.n:]]

    def save(self, key: str, month: list[bytes]) -> None:
        p = self.dir / f"{key}.bin"
        p.with_suffix(".tmp").write_bytes(b"".join(month))
        p.with_suffix(".tmp").replace(p)

    def prune(self, keep: list[str]) -> None:
        for p in self.dir.glob("*.bin"):
            if p.stem not in keep:
                p.unlink()

    def wipe(self) -> None:
        self.prune([])


# ---------------------------------------------------------------- the rule, on rows of one-byte lanes

def table(test) -> bytes:
    return bytes(1 if test(v) else 0 for v in range(256))


def lanes(b: bytes) -> int:
    return int.from_bytes(b, "big")


def unlanes(x: int, n: int) -> bytes:
    return x.to_bytes(n, "big")


T_HAS = table(lambda v: v != NONE)
T_LO = table(lambda v: v < round(BARE * 100) + 100)
T_HI = table(lambda v: v < 200 - (round(GREEN * 100) + 100))               # on 200 - code: highest above GREEN
T_RECENT = table(lambda v: v < 200 - (round(RECENT * 100) + 100))
T_FIRST = table(lambda v: v < 200 - (round(LOST_GREEN * 100) + 100))
T_ABOVE_BARE = table(lambda v: v < 200 - (round(LOST_BARE * 100) + 100))
T_GREENISH = table(lambda v: v < 200 - (round(GREENISH * 100) + 100))
T_WATER = table(lambda v: v != NONE and v >= 200 - (round(WATER_NDVI * 100) + 100))
T_WET = table(lambda v: v > round(FLOOD * 100) + 101)
T_MIN_MONTHS = table(lambda v: v >= MIN_MONTHS)
T_OVER_128 = table(lambda v: v > 128)


def more_than(a: int, ka: int, b: int, kb: int, n: int) -> int:
    """Lanes where ka x a > kb x b, for counts of at most MONTHS. 128 + ka.a - kb.b stays inside a byte for the
    factors used here (at most 5 x 25 and 3 x 25), so no lane borrows from its neighbour."""
    ones = lanes(b"\x01" * n)
    return lanes(unlanes(128 * ones + ka * a - kb * b, n).translate(T_OVER_128))


def classify(months: list[list[bytes] | None], n: int, flood: bool) -> dict[str, int]:
    """Every pixel in exactly one state, as lane masks, oldest month first. In order of precedence:

    unclear        fewer than MIN_MONTHS months with a clear look: too cloudy to say anything
    water          most months' highest greenness at or below 0 (or, with the flood check, wet in more than 60 %
                   of its clear months)
    lost           most first-year months green above LOST_GREEN, and nothing above LOST_BARE in the last four
                   months, with at least one look in them. A fallow field grows weeds within weeks; cleared ground
                   and a roof do not
    rice           at least two falls from above GREEN to below BARE and two rises back, and green above RECENT in
                   the last seven months; with the flood check on, also a month with MNDWI above FLOOD followed
                   within four months by green above GREEN
    green          most months above GREENISH: trees, gardens, other crops
    bare_or_built  the rest
    """
    zero, ones = 0, lanes(b"\x01" * n)
    green_now = bare_now = f1 = f2 = r1 = r2 = recent = 0
    n_has = n_first = has_first = n_water = n_green = n_wet = 0
    last_any = last_has = last_lo = flood_ok = 0
    wets = deque(maxlen=CANOPY_WITHIN)
    m = len(months)
    for k, month in enumerate(months):
        month = month or blank(n)
        lo_b, hi_b, wet_b = month
        has = lanes(lo_b.translate(T_HAS))
        lo, hi = lanes(lo_b.translate(T_LO)), lanes(hi_b.translate(T_HI))
        fall = green_now & lo
        f2 |= f1 & fall
        f1 |= fall
        bare_now, green_now = bare_now | lo, green_now & ~lo
        rise = bare_now & hi
        r2 |= r1 & rise
        r1 |= rise
        green_now, bare_now = green_now | hi, bare_now & ~hi
        n_has += has
        last_lo = (last_lo & ~has) | lo
        n_water += lanes(hi_b.translate(T_WATER))
        n_green += lanes(hi_b.translate(T_GREENISH))
        if k >= m - RECENT_MONTHS:
            recent |= lanes(hi_b.translate(T_RECENT))
        if k < FIRST_MONTHS:
            n_first += lanes(hi_b.translate(T_FIRST))
            has_first += has
        if k >= m - LAST_MONTHS:
            last_any |= lanes(hi_b.translate(T_ABOVE_BARE))
            last_has |= has
        if flood:
            for w in wets:
                flood_ok |= w & hi
            wet = lanes(wet_b.translate(T_WET))
            wets.append(wet)
            n_wet += wet
    unclear = lanes(unlanes(n_has, n).translate(T_MIN_MONTHS)) ^ ones
    water = more_than(n_water, 2, n_has, 1, n)
    if flood:
        water |= more_than(n_wet, 5, n_has, 3, n)
    lost = more_than(n_first, 2, has_first, 1, n) & last_has & (last_any ^ ones)
    rice = f2 & r2 & recent & (flood_ok if flood else ones)
    green = more_than(n_green, 2, n_has, 1, n)
    out, taken = {}, zero
    for name, mask in (("unclear", unclear), ("water", water), ("lost", lost), ("rice", rice), ("green", green),
                       ("bare_or_built", ones)):
        out[name] = mask & ~taken & ones
        taken |= out[name]
    out["_bare_at_last_look"] = last_lo
    out["_months_read"] = sum(1 for mo in months if mo)
    return out


def summary(states: dict, n: int) -> dict:
    """Hectares per state (a pixel is 0.01 ha), and the share of the rice bare or flooded at its last clear look.
    Raises when the six states do not add up to the square: a cloudy pixel must never pass for "no rice"."""
    px = {s: states[s].bit_count() for s in STATES}
    if sum(px.values()) != n:
        raise AssertionError(f"the six states hold {sum(px.values())} pixels of {n}")
    rice = px["rice"]
    bare = (states["rice"] & states["_bare_at_last_look"]).bit_count()
    return {**{f"{s}_ha": round(v * 0.01, 2) for s, v in px.items()},
            "rice_bare_pct": round(100 * bare / rice, 1) if rice else None, "months_read": states["_months_read"]}


def lost_cell(states: dict, g: dict, n: int) -> str | None:
    """The H3 res-8 cell holding the most lost pixels. Never a parcel and never an owner."""
    mask = unlanes(states["lost"], n)
    try:
        import h3
    except ImportError:
        return None
    fwd = forward(g["epsg"])
    inv = local_inverse(fwd, g["lat"], g["lon"])
    count = Counter()
    i = mask.find(1)
    step = max(1, mask.count(1) // 20000)      # ponytail: a sample past 20,000 pixels; the mode does not move
    k = 0
    while i != -1:
        if k % step == 0:
            r, c = divmod(i, g["w"])
            count[h3.latlng_to_cell(*inv(g["x0"] + (c + 0.5) * 10, g["y0"] - (r + 0.5) * 10), 8)] += 1
        k += 1
        i = mask.find(1, i + 1)
    return count.most_common(1)[0][0] if count else None


# ---------------------------------------------------------------- Planetary Computer

def search(hc, g: dict, since: datetime, until: datetime) -> list[dict]:
    """Every scene over the square since `since`, following the STAC `next` links. Kept small: what reading a
    scene needs, nothing else."""
    lat, lon = g["lat"], g["lon"]
    d = 0.5 * max(g["w"], g["h"]) * 10 / 111320 + 0.01
    body = {"collections": [COLLECTION], "bbox": [lon - d / math.cos(math.radians(lat)), lat - d,
                                                  lon + d / math.cos(math.radians(lat)), lat + d],
            "datetime": f"{since.strftime('%Y-%m-%dT%H:%M:%SZ')}/{until.strftime('%Y-%m-%dT%H:%M:%SZ')}",
            "query": {"eo:cloud_cover": {"lt": CLOUD_MAX}}, "limit": 200}
    out = []
    while body:
        r = hc.post(STAC, json=body)
        r.raise_for_status()
        page = r.json()
        for i in page.get("features") or []:
            p, a = i["properties"], i.get("assets") or {}
            if {"SCL", "B04", "B08", "B03", "B11"} <= set(a):
                out.append({"id": i["id"], "datetime": p["datetime"],
                            "properties": {"s2:processing_baseline": p.get("s2:processing_baseline"),
                                           "proj:epsg": p.get("proj:epsg") or p.get("proj:code")},
                            "assets": {k: {"href": a[k]["href"]} for k in ("SCL", "B04", "B08", "B03", "B11")}})
        nxt = next((ln for ln in page.get("links") or [] if ln.get("rel") == "next"), None)
        body = {**body, **nxt["body"]} if nxt and nxt.get("body") and nxt.get("method", "POST") == "POST" else None
    return out


def reader(hc):
    """get(url, start, end) with a SAS token per storage container, asked for again when it is refused: a long
    backfill outlived its token on 30 Oct 2026 (7 of 222 scenes failed with 403)."""
    tokens: dict[str, str] = {}

    def token(key: str, fresh: bool = False) -> str:
        if fresh or key not in tokens:
            t = hc.get(f"{SAS}/{key}")
            t.raise_for_status()
            tokens[key] = t.json()["token"]
        return tokens[key]

    def get(url: str, start: int, end: int) -> bytes:
        account, container = url.split("//", 1)[1].split(".", 1)[0], url.split("/")[3]
        key = f"{account}/{container}"
        for fresh in (False, True):
            r = hc.get(f"{url}?{token(key, fresh)}", headers={"Range": f"bytes={start}-{end}"})
            if r.status_code != 403:
                break
        r.raise_for_status()
        if r.status_code != 206 and len(r.content) > end - start + 1:
            raise RuntimeError("the host ignored the range request; refusing to read whole files")
        return r.content[: end - start + 1]
    return get


# ---------------------------------------------------------------- settings and state

def settings() -> tuple[dict | None, bool | None, str | None]:
    """(square, flood check, why not). The square is the keeper's: there is no default size and no default answer to
    the flood question, because most places have no rice and the right answer depends on how the fields are farmed."""
    at = (os.getenv("PADDY_AT") or "").strip()
    rad = (os.getenv("PADDY_RADIUS_KM") or "").strip()
    fl = (os.getenv("PADDY_FLOOD_CHECK") or "").strip().lower()
    if not rad:
        return None, None, "PADDY_RADIUS_KM is not set: the keeper chooses the square in Set up"
    if fl not in ("on", "off"):
        return None, None, "PADDY_FLOOD_CHECK is not set to on or off: say in Set up whether the fields stand flooded"
    radius = float(rad)
    if not 0 < radius <= MAX_RADIUS_KM:
        return None, None, f"PADDY_RADIUS_KM must be more than 0 and at most {MAX_RADIUS_KM}"
    if at:
        lat, lon = (float(v) for v in at.split(","))
    else:
        lat, lon = float(os.environ["NODE_LAT"]), float(os.environ["NODE_LON"])
    return grid(lat, lon, radius), fl == "on", None


def root() -> Path:
    return Path(os.getenv("PACK_OUT", "/app/out")) / "paddy"


def load_state(r: Path) -> dict:
    try:
        return json.loads((r / "state.json").read_text())
    except (OSError, ValueError):
        return {}


def save_state(r: Path, state: dict) -> None:
    r.mkdir(parents=True, exist_ok=True)
    (r / "state.tmp").write_text(json.dumps(state, indent=1, sort_keys=True))
    (r / "state.tmp").replace(r / "state.json")


def step(hc, r: Path, g: dict, flood: bool, now: datetime, per_day: float, per_call: float, get=None) -> tuple[dict, bool]:
    """Search if a day has passed, read scenes not read yet (newest first), and return (state, did anything). The poll
    reads one scene a call and PADDY_READS a day; `backfill` reads everything."""
    state, did = load_state(r), False
    key = {k: g.get(k) for k in ("epsg", "x0", "y0", "w", "h")} | {"flood": flood}
    store = Store(r, g["w"] * g["h"])
    if state.get("square") != key:                 # a new square or a new answer: what is kept describes another one
        store.wipe()
        state = {"square": key, "seen": [], "todo": [], "reads": {}}
    keep = month_keys(now)
    start = datetime.fromisoformat(keep[0] + "-01T00:00:00+00:00")
    if now.timestamp() - float(state.get("searched") or 0) >= DAY:
        since = datetime.fromtimestamp(state["searched"], timezone.utc) - timedelta(days=3) if state.get("searched") else start
        seen = set(state["seen"]) | {i["id"] for i in state["todo"]}
        state["todo"] += [i for i in search(hc, g, since, now) if i["id"] not in seen]
        state["searched"] = now.timestamp()
        did = True
    state["todo"] = sorted((i for i in state["todo"] if i["datetime"] >= keep[0]), key=lambda i: i["datetime"], reverse=True)
    day = now.strftime("%Y-%m-%d")
    done = state["reads"].get(day, 0)
    get = get or reader(hc)
    calls, lock = 0, r / "backfill.lock"
    while state["todo"] and done < per_day and calls < per_call:
        if per_call == float("inf"):
            lock.touch()                           # the poll stands aside while this is fresh
        item = state["todo"].pop(0)
        epsg = int(str(item["properties"].get("proj:epsg") or 0).split(":")[-1])
        state["seen"] = (state["seen"] + [item["id"]])[-2000:]
        done, calls, did = done + 1, calls + 1, True
        if epsg != g["epsg"]:
            continue    # ponytail: a square on a zone edge reads its own zone's tiles only; reproject if one ever needs both
        lo, hi, wet, share = read_scene(get, item, g, flood)
        if lo is None:
            log.info("paddy: %s, %.0f%% of the square clear, not read", item["id"], 100 * share)
            continue
        mk = item["datetime"][:7]
        log.info("paddy: %s, %.0f%% clear, into %s (%d waiting)", item["id"], 100 * share, mk, len(state["todo"]))
        store.save(mk, merge(store.load(mk) or blank(store.n), lo, hi, wet))
        if share >= 0.5 and item["datetime"] > (state.get("clear_look") or ""):
            state["clear_look"] = item["datetime"]
        state["newest"] = max(state.get("newest") or "", item["datetime"])
        state["changed"] = True
    state["reads"] = {day: done}
    store.prune(keep)
    save_state(r, state)
    return state, did


def compute(r: Path, g: dict, flood: bool, now: datetime) -> tuple[dict, str | None]:
    store = Store(r, g["w"] * g["h"])
    states = classify([store.load(k) for k in month_keys(now)], store.n, flood)
    s = summary(states, store.n)
    return s, (lost_cell(states, g, store.n) if s["lost_ha"] else None)


# ---------------------------------------------------------------- the poll

def fetch(hc):
    """Contract: (sensors, readings). Idle and silent but for one log line until the keeper sets the square."""
    g, flood, why = settings()
    if g is None:
        log.info("paddy: %s", why)
        return [], []
    r, now = root(), datetime.now(timezone.utc)
    try:
        if time.time() - (r / "backfill.lock").stat().st_mtime < 600:
            return [], []                          # `planetai run paddy backfill` is writing the same files
    except OSError:
        pass
    state, did = step(hc, r, g, flood, now, per_day=int(os.getenv("PADDY_READS") or 4), per_call=1)
    if not did and not state.get("changed"):
        return [], []
    kept = [k for k in month_keys(now) if (r / "months" / f"{k}.bin").exists()]
    months = len(kept)
    clear = state.get("clear_look")
    days = (now - datetime.fromisoformat(clear.replace("Z", "+00:00"))).days if clear else None
    meta = {"collection": COLLECTION, "provenance": "satellite", "host": "Microsoft Planetary Computer",
            "attribution": attribution(kept), "radius_km": g.get("radius_km"), "flood_check": flood,
            "newest_look": state.get("newest"), "months_read": months}
    readings = [(now, SENSOR, "months_read", float(months))]
    if days is not None:
        readings.append((now, SENSOR, "clear_days", float(days)))
    # Hectares only once the history is read: with months still to come, the first year is empty, so lost reads
    # zero and rice reads low, and both would look like answers.
    if state.get("changed") and not state["todo"] and months >= FIRST_MONTHS + 1:
        s, cell = compute(r, g, flood, now)
        # ponytail: a scene published late but older than the newest look changes the figures at the same stamp,
        # and readings keep the first row per stamp; the next new scene corrects it. Stamp by compute time if it matters.
        ts = datetime.fromisoformat(state["newest"].replace("Z", "+00:00"))
        readings += [(ts, SENSOR, "rice_ha", s["rice_ha"]), (ts, SENSOR, "rice_lost_ha", s["lost_ha"])]
        if s["rice_bare_pct"] is not None:
            readings.append((ts, SENSOR, "rice_bare_pct", s["rice_bare_pct"]))
        meta |= {"states_ha": {k: s[f"{k}_ha"] for k in STATES}, "lost_cell": cell}
        state["changed"] = False
        state["last"] = meta
        save_state(r, state)
        log.info("paddy: %.1f ha rice, %.1f ha lost, from %d months", s["rice_ha"], s["lost_ha"], months)
    else:
        meta |= {k: v for k, v in (state.get("last") or {}).items() if k in ("states_ha", "lost_cell")}
    sensor = {"sensor_id": SENSOR, "source": "paddy", "name": "Rice in the keeper's square (Sentinel-2)",
              "lat": g["lat"], "lon": g["lon"], "indoor": False, "local": False, "kind": "model", "scale": "city",
              "cadence": "P5D", "meta": meta}
    return [sensor], readings
