"""paddy, offline: the 15-bit reader, the offset, the rule on made-up pixels, and the poll's pacing.

Run from a node's folder: python3 packs/paddy/tests/test_paddy.py
Standard library only. The real scenes were checked against rasterio on 31 Oct 2026, pixel for pixel; see README.
"""
import importlib.util
import os
import struct
import tempfile
import zlib
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("paddy_adapter", HERE.parent / "adapter.py")
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)


# ---------------------------------------------------------------- 15 bits, packed the way Planetary Computer packs them

def pack15(values, tw, th):
    out = b""
    for row in range(th):
        v, bits = 0, 0
        for x in values[row * tw:(row + 1) * tw]:
            v, bits = (v << 15) | x, bits + 15
        pad = (-bits) % 8
        out += (v << pad).to_bytes((bits + pad) // 8, "big")
    return out


vals = [(i * 2654435761) % 32768 for i in range(7 * 3)]
assert list(A.unpack15(pack15(vals, 7, 3), 7, 3)) == vals       # 7 x 15 = 105 bits: every row padded to 112


# ---------------------------------------------------------------- a tiled 15-bit COG, written here, read back

def cog(w, h, tw, th, pixel, x0, y0, epsg=32750, bits=15):
    across, down = -(-w // tw), -(-h // th)
    tiles = []
    for tr in range(down):
        for tc in range(across):
            t = [pixel(tr * th + r, tc * tw + c) if tr * th + r < h and tc * tw + c < w else 0
                 for r in range(th) for c in range(tw)]
            tiles.append(zlib.compress(pack15(t, tw, th) if bits == 15 else struct.pack(f"<{len(t)}B", *t)))
    tags = {256: (4, [w]), 257: (4, [h]), 258: (3, [bits]), 259: (3, [8]), 277: (3, [1]), 322: (4, [tw]), 323: (4, [th]),
            324: (4, None), 325: (4, [len(t) for t in tiles]), 33550: (12, [10.0, 10.0, 0.0]),
            33922: (12, [0.0, 0.0, 0.0, float(x0), float(y0), 0.0]),
            34735: (3, [1, 1, 0, 2, 1025, 0, 1, 1, 3072, 0, 1, epsg])}
    fmt = {3: "H", 4: "I", 12: "d"}
    ifd_at, n = 8, len(tags)
    extra_at = ifd_at + 2 + 12 * n + 4
    data_at = extra_at + sum(len(v or tiles) * struct.calcsize(fmt[t]) for t, v in tags.values()) + 64
    offs, o = [], data_at
    for t in tiles:
        offs.append(o)
        o += len(t)
    tags[324] = (4, offs)
    head, extra = struct.pack("<2sHI", b"II", 42, ifd_at) + struct.pack("<H", n), b""
    for tag in sorted(tags):
        typ, v = tags[tag]
        raw = struct.pack("<" + fmt[typ] * len(v), *v)
        if len(raw) <= 4:
            head += struct.pack("<HHI", tag, typ, len(v)) + raw.ljust(4, b"\0")
        else:
            head += struct.pack("<HHII", tag, typ, len(v), extra_at + len(extra))
            extra += raw
    body = (head + struct.pack("<I", 0) + extra).ljust(data_at, b"\0")
    return body + b"".join(tiles)


pix = lambda r, c: 1000 + 100 * r + c                                            # noqa: E731
blob = cog(10, 7, 4, 4, pix, x0=300000, y0=9100000)
get = lambda url, a, b: blob[a:b + 1]                                            # noqa: E731
c = A.Cog(get, "mem://B04.tif")
assert (c.w, c.h, c.bits, c.epsg) == (10, 7, 15, 32750)
# a window that starts inside and runs off the right and the bottom: the outside is 0, the inside is the image
win = c.window(300000 + 7 * 10, 9100000 - 5 * 10, 5, 4)
want = [pix(r, cc) if r < 7 and cc < 10 else 0 for r in range(5, 9) for cc in range(7, 12)]
assert win == want, (win, want)
# a window wholly outside is all zeros, and one off the pixel grid is refused rather than shifted
assert c.window(400000, 9100000, 3, 3) == [0] * 9
try:
    c.window(300005, 9100000, 2, 2)
    raise SystemExit("a window 5 m off the grid was read")
except ValueError:
    pass
# an 8-bit band (SCL) through the same reader
s8 = A.Cog(lambda u, a, b, blob=cog(4, 4, 4, 4, lambda r, cc: r * 4 + cc, 0, 0, bits=8): blob[a:b + 1], "mem://SCL.tif")
assert s8.window(0, 0, 4, 4) == list(range(16))


# ---------------------------------------------------------------- the offset and the codes

assert A.offset({"properties": {"s2:processing_baseline": "03.01"}}) == 0
assert A.offset({"properties": {"s2:processing_baseline": "04.00"}}) == 1000
assert A.offset({"properties": {"s2:processing_baseline": "05.13"}}) == 1000
assert A.code_ndvi(1300, 4300, 1000) == 100 + 83                                # (3300 - 300) / 3600 = 0.83
assert A.code_ndvi(1300, 4300, 0) == 100 + 54                                   # the same pixel read without the offset
assert A.code_ndvi(0, 4300, 1000) == A.NONE and A.code_ndvi(900, 900, 1000) == A.NONE
assert A.code_mndwi(1500, 1100, 1000) == 101 + 67 and A.code_mndwi(0, 1100, 1000) == 0


# ---------------------------------------------------------------- the rule on made-up pixels

def month(*px):
    """One month from per-pixel (low NDVI, high NDVI, MNDWI) or None."""
    lo, hi, wet = bytearray(), bytearray(), bytearray()
    for p in px:
        if p is None:
            lo.append(255), hi.append(255), wet.append(0)
        else:
            lo.append(round(p[0] * 100) + 100), hi.append(200 - (round(p[1] * 100) + 100)), wet.append(round(p[2] * 100) + 101)
    return [bytes(lo), bytes(hi), bytes(wet)]


FLOODED, BARE, YOUNG, GREEN, RIPE = (0.10, 0.25, 0.35), (0.15, 0.30, -0.20), (0.30, 0.55, -0.30), (0.60, 0.80, -0.50), (0.40, 0.70, -0.40)
two_crops = [FLOODED, YOUNG, GREEN, GREEN, RIPE, BARE] * 5                       # sawah, two seasons a year
one_crop = ([FLOODED] * 4 + [GREEN] * 5 + [BARE] * 3) * 3                       # the Ebro: flooded basins once a year
barley = ([BARE] * 4 + [GREEN] * 5 + [BARE] * 3) * 3                            # sown and cut, never flooded
cleared = [GREEN] * 15 + [(0.05, 0.10, -0.1)] * 10                              # green, then scraped bare
lawn = [(0.60, 0.75, -0.5)] * 25
pond = [(-0.20, -0.10, 0.50)] * 25
never = [None] * 25
sparse = [GREEN if k % 5 == 0 else None for k in range(25)]                     # five clear months in 25
PIX = (two_crops, one_crop, barley, cleared, lawn, pond, never, sparse)
months = [month(*(p[k] for p in PIX)) for k in range(25)]
n = len(PIX)


def states(flood):
    st = A.classify(months, n, flood)
    s = A.summary(st, n)                                                         # raises unless the six add up
    assert sum(s[f"{k}_ha"] for k in A.STATES) == round(n * 0.01, 2)
    lanes = {k: A.unlanes(st[k], n) for k in A.STATES}
    return [next(k for k in A.STATES if lanes[k][i]) for i in range(n)], s


on, s_on = states(True)
off, _ = states(False)
assert on == ["rice", "rice", "bare_or_built", "lost", "green", "water", "unclear", "unclear"], on
assert off == ["rice", "rice", "rice", "lost", "green", "water", "unclear", "unclear"], off   # barley passes without the flood check
assert s_on["rice_ha"] == 0.02 and s_on["lost_ha"] == 0.01 and s_on["months_read"] == 25
assert s_on["rice_bare_pct"] == 100.0, s_on                                      # both rice pixels end on a flooded month
st = A.classify(months, n, True)
broken = dict(st, water=st["water"] | st["rice"])
try:
    A.summary(broken, n)
    raise SystemExit("a pixel counted twice passed the partition")
except AssertionError:
    pass

# merge: lowest low, highest high (stored as 200 minus), highest water
m = A.merge(A.blank(2), *month((0.3, 0.6, 0.1), None))
m = A.merge(m, *month((0.2, 0.5, 0.4), (0.1, 0.2, -0.1)))
assert m == month((0.2, 0.6, 0.4), (0.1, 0.2, -0.1)), m

assert len(A.month_keys(datetime(2026, 10, 31, tzinfo=timezone.utc))) == 25
assert A.month_keys(datetime(2026, 10, 31, tzinfo=timezone.utc))[0] == "2024-10"


# ---------------------------------------------------------------- settings: idle until the keeper answers

def env(**kv):
    for k in ("PADDY_AT", "PADDY_RADIUS_KM", "PADDY_FLOOD_CHECK"):
        os.environ.pop(k, None)
    os.environ.update({"NODE_LAT": "-8.8", "NODE_LON": "115.17", **kv})
    return A.settings()


assert env()[0] is None and "PADDY_RADIUS_KM" in env()[2]
assert env(PADDY_RADIUS_KM="3")[0] is None                                       # no answer to the flood question yet
assert env(PADDY_RADIUS_KM="12", PADDY_FLOOD_CHECK="off")[0] is None
g, flood, why = env(PADDY_RADIUS_KM="3", PADDY_FLOOD_CHECK="off")
assert why is None and flood is False and (g["lat"], g["lon"]) == (-8.8, 115.17) and g["w"] == g["h"] == 600
assert g["x0"] % 20 == 0 and g["y0"] % 20 == 0 and g["epsg"] == 32750
g, _, _ = env(PADDY_AT="-8.6388,115.1212", PADDY_RADIUS_KM="1", PADDY_FLOOD_CHECK="on")
assert (g["lat"], g["lon"], g["w"]) == (-8.6388, 115.1212, 200)
assert A.zone_epsg(40.7, 0.6) == 32631
assert A.attribution(["2024-10", "2026-10"]).startswith("Contains modified Copernicus Sentinel data 2024-2026,")


# ---------------------------------------------------------------- the poll's pace, without the network

g = A.grid(-8.6388, 115.1212, 0.05)                                              # 10 x 10 pixels
items = [{"id": f"S2_{d:02d}", "datetime": f"2026-10-{d:02d}T02:17:00Z",
          "properties": {"s2:processing_baseline": "05.13", "proj:epsg": 32750}, "assets": {}} for d in (3, 8, 13, 18, 23)]
A.search = lambda hc, g, since, until: list(items)
A.read_scene = lambda get, item, g, flood: (bytes([180] * 100), bytes([20] * 100), bytes(100), 0.9)
now = datetime(2026, 10, 31, 6, tzinfo=timezone.utc)
with tempfile.TemporaryDirectory() as d:
    r = Path(d)
    st, did = A.step(None, r, g, False, now, per_day=2, per_call=1, get=object())
    assert did and len(st["seen"]) == 1 and st["seen"] == ["S2_23"]             # newest first, one per poll
    st, did = A.step(None, r, g, False, now, per_day=2, per_call=1, get=object())
    assert did and st["seen"] == ["S2_23", "S2_18"]
    st, did = A.step(None, r, g, False, now, per_day=2, per_call=1, get=object())
    assert not did and len(st["todo"]) == 3                                      # the day's two are read; no new search
    assert (r / "months" / "2026-10.bin").stat().st_size == 300
    st, _ = A.step(None, r, g, True, now, per_day=2, per_call=1, get=object())
    assert st["seen"] == ["S2_23"]                                               # a new answer wiped the old square
    st, _ = A.step(None, r, g, True, now, per_day=float("inf"), per_call=float("inf"), get=object())
    assert not st["todo"] and len(st["seen"]) == 5                               # backfill reads everything

print("paddy: all checks passed")
