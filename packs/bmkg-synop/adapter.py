"""BMKG's hourly SYNOP report for one station, read off WMO's WIS2 global broker. Key-free, no account.

BMKG publishes every synoptic station's report as WMO core data (free and unrestricted, Resolution 1 Cg-Ext(2021)).
There is no HTTP API: a report exists only as an MQTT notification on WIS2, announced once by each of about six
global caches, with the BUFR4 message inline. So this pack keeps one subscription open in a thread of its own and
hands the node whatever arrived since the last poll.

    BMKG_SYNOP_STATION=0-20000-0-97230     # WIGOS id; 97230 is Ngurah Rai, the one Bali station in the feed

The node imports adapter.py afresh on every poll, so nothing kept at module level lasts. The thread does: it is found
again by its name, and the reports wait on the thread object until `fetch` takes them.

Notifications arrive late and out of order. The 07:00 UTC report of 26 Oct 2026 was published at 07:10 and reached
us again from a cache at 10:55. Each report is kept once, by its WIS2 data_id, and stored at its observation time.

A station 8 km from a house is not the house's air: every channel is `comparable: false` (channels.yml), so it never
joins the ring or the room medians. It is shown as itself, in its section and beside Heat.
"""
import base64
import json
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime

log = logging.getLogger("planetai.pack.bmkg-synop")

SOURCE = "bmkg-synop"
SENSOR = "bmkg-synop"
THREAD = "bmkg-synop"
TOPIC = "cache/a/wis2/id-bmkg/data/core/weather/surface-based-observations/synop"
BROKER = "globalbroker.meteo.fr"   # Météo-France's WIS2 global broker; any of the four carries the same feed
LICENCE = "WMO Unified Data Policy, core data (free and unrestricted)"


def notification(body: dict, station: str):
    """(data_id, observed at, lat, lon, BUFR bytes) when a WIS2 notification is `station`'s report, else None."""
    p = body.get("properties") or {}
    if p.get("wigos_station_identifier") != station:
        return None
    c = p.get("content") or {}
    # ponytail: inline only. Every BMKG report seen so far is about 400 bytes and inline; add a download of the
    # `canonical` link if one ever comes without it.
    if c.get("encoding") != "base64" or not c.get("value") or not p.get("datetime"):
        return None
    lon, lat = ((body.get("geometry") or {}).get("coordinates") or [None, None])[:2]
    ts = datetime.fromisoformat(p["datetime"].replace("Z", "+00:00"))
    return p.get("data_id") or p["datetime"], ts, lat, lon, base64.b64decode(c["value"])


def decode(raw: bytes) -> list:
    """(descriptor, value) pairs of the report's first subset. pybufrkit hands values already scaled to SI units."""
    from pybufrkit.decoder import Decoder  # noqa: PLC0415

    tv = Decoder().process(raw).template_data.value
    return list(zip((d.id for d in tv.decoded_descriptors_all_subsets[0]), tv.decoded_values_all_subsets[0]))


def values(pairs) -> dict:
    """metric -> value in the node's units. The first occurrence wins: in WMO template 307080 that is the
    observation itself (the 10-minute mean wind, not a gust). Rain is paired with the period (004024) before it."""
    out, period = {}, None
    for fxy, v in pairs:
        if fxy == 4024:
            period = v
        if v is None or isinstance(v, bytes):
            continue
        if fxy == 12101:
            out.setdefault("temp", round(v - 273.15, 2))
        elif fxy == 12103:
            out.setdefault("dewpoint", round(v - 273.15, 2))
        elif fxy == 13003:
            out.setdefault("humidity", float(v))
        elif fxy == 10004:
            out.setdefault("pressure", round(v / 1000, 3))           # Pa -> kPa, as the node's own sensors report
        elif fxy == 11001:
            out.setdefault("wind_direction", float(v))
        elif fxy == 11002:
            out.setdefault("wind_speed", round(v * 3.6, 1))          # m/s -> km/h, as open-meteo's wind_speed
        elif fxy == 20001:
            out.setdefault("visibility", round(v / 1000, 2))         # m -> km
        elif fxy == 20010:
            out.setdefault("cloud", float(v))
        elif fxy == 13011 and period in (-1, -24):
            out.setdefault(f"rainfall_{-period}h", max(float(v), 0.0))  # -0.1 is "trace" in BUFR
    return out


def _listen(t: threading.Thread) -> None:
    """Hold the subscription for the life of the process. paho reconnects on its own, the first connect included."""
    import paho.mqtt.client as mqtt  # noqa: PLC0415

    def on_connect(c, _u, _f, rc, _p=None):
        if rc == 0:
            c.subscribe(TOPIC, qos=1)
            log.info("bmkg-synop: listening for %s on %s", t.station, t.broker)
        else:
            log.warning("bmkg-synop: %s refused the connection (%s)", t.broker, rc)

    def on_message(_c, _u, m):
        try:
            got = notification(json.loads(m.payload), t.station)
            if not got or got[0] in t.seen:
                return
            t.seen.append(got[0])
            t.reports.append((got[1], got[2], got[3], got[0], values(decode(got[4]))))
            t.last = time.time()
        except Exception as e:  # noqa: BLE001 — one bad message must not end the subscription
            if type(e).__name__ not in t.warned:
                t.warned.add(type(e).__name__)
                log.warning("bmkg-synop: a report did not decode (%s: %s)", type(e).__name__, e)

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"planetai-bmkg-synop-{os.getpid()}-{int(time.time())}")
    c.username_pw_set("everyone", "everyone")   # WIS2's published public login
    c.tls_set()
    c.on_connect, c.on_message = on_connect, on_message
    c.connect_async(t.broker, 8883, 60)
    c.loop_forever(retry_first_connection=True)


def _thread() -> threading.Thread:
    t = next((t for t in threading.enumerate() if t.name == THREAD), None)
    if t is None:
        t = threading.Thread(target=lambda: _listen(t), daemon=True, name=THREAD)
        t.station = os.getenv("BMKG_SYNOP_STATION", "").strip() or "0-20000-0-97230"
        t.broker = os.getenv("BMKG_SYNOP_BROKER", "").strip() or BROKER
        t.reports, t.seen, t.warned, t.last = deque(maxlen=48), deque(maxlen=64), set(), None
        t.start()
    return t


def fetch(hc):
    """Contract: (sensors, readings). Missing libraries log and yield nothing; the pack never takes the node down."""
    import importlib.util  # noqa: PLC0415

    if importlib.util.find_spec("pybufrkit") is None:
        log.warning("bmkg-synop: pybufrkit is not installed. `planetai packs install` installs it.")
        return [], []
    t = _thread()
    got = []
    while t.reports:
        got.append(t.reports.popleft())
    if not got:
        return [], []
    _, lat, lon, data_id, _ = max(got, key=lambda r: r[0])
    sensors = [{
        "sensor_id": SENSOR, "source": SOURCE, "name": f"BMKG station {t.station.rsplit('-', 1)[-1]}",
        "lat": lat, "lon": lon, "indoor": False, "local": False, "cadence": "PT1H",
        "meta": {"wigos": t.station, "network": "BMKG synoptic stations, via WMO WIS2", "licence": LICENCE,
                 "last_report": data_id, "attribution": "BMKG (Badan Meteorologi, Klimatologi, dan Geofisika), WMO WIS2"},
    }]
    readings = [(ts, SENSOR, metric, v) for ts, _, _, _, vals in got for metric, v in vals.items()]
    return sensors, readings
