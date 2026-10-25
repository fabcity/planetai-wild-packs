"""Xiaomi / Mi Home air purifiers, read on the LAN over miio/MIoT — never the vendor cloud.

One poll per node cycle per purifier, plain UDP to port 54321. The miio handshake on current firmware
does not expose device tokens, so tokens come from xiaomi-cloud-tokens-extractor (one Mi Home login,
run once on any machine); after that nothing here talks to Xiaomi.

    XIAOMI_PURIFIERS=Living Room@192.168.4.98=0123...cdef,Bedroom@192.168.4.109=fedc...3210

Protocol shape varies by generation: 2019-era units (1, 2, 2S, early Pro) speak the legacy miio
properties, newer ones (3H, 4, 4 Pro, Pro H, Elite, za1/vb4/vb2 families) speak MIoT. The adapter
tries MIoT first and falls back to legacy; both expose aqi (PM2.5 density, µg/m³), temperature,
humidity and filter life. pm10 is emitted only where the model reports it.

Correction: NONE. The node's EPA 2021 humidity correction is derived for Plantower lasers; Xiaomi's
optical PM sensor is not a Plantower and the correction was not derived for it, so pm25 here is the
raw density, marked as such in meta. If a Xiaomi-specific correction is ever derived, store raw as
pm25_raw and the corrected value as pm25 — never overwrite raw.

A purifier measures a room: indoor=True, so it joins the indoor rules (air-quality's
indoor_pm25_high) and stays out of ambient outdoor averages by design.
"""
import logging
import os
from datetime import datetime, timezone

log = logging.getLogger("planetai.pack.xiaomi-air")
_state = {"warned": set(), "meta": {}}

# MIoT mappings for models python-miio does not bundle, transcribed from miot-spec.org (fetch the
# model's spec instance and take siid/piid per property). `_get_mapping()` prefers the class-level
# `_mappings` registry over the instance `mapping=` kwarg, so these are registered there at poll time.
# Verified live on node #1's units, 2026-09-17.
_MODEL_MAPPINGS = {
    # Xiaomi Smart Air Purifier Elite: full sensor suite (pm2.5, pm10, temp, RH, motor rpm)
    "zhimi.airp.meb1": {
        "power": {"siid": 2, "piid": 1}, "mode": {"siid": 2, "piid": 4},
        "fan_level": {"siid": 2, "piid": 5},
        "humidity": {"siid": 3, "piid": 1}, "aqi": {"siid": 3, "piid": 4},
        "temperature": {"siid": 3, "piid": 7}, "pm10_density": {"siid": 3, "piid": 8},
        "filter_life_remaining": {"siid": 4, "piid": 1}, "filter_hours_used": {"siid": 4, "piid": 3},
        "motor_speed": {"siid": 9, "piid": 1},
    },
    # Xiaomi Smart Air Purifier 4 Compact: pm2.5 + filter only — no temp/RH hardware
    "xiaomi.airp.cpa4": {
        "power": {"siid": 2, "piid": 1}, "mode": {"siid": 2, "piid": 4},
        "aqi": {"siid": 3, "piid": 4},
        "filter_life_remaining": {"siid": 4, "piid": 1}, "filter_hours_used": {"siid": 4, "piid": 3},
    },
}

# Metric name -> candidate attributes on the miio status object, MIoT naming first, legacy after.
_PROPS = {
    "pm25": ("aqi", "pm25_density", "pm2_5_density"),
    "pm10": ("pm10_density", "pm10"),
    "temp": ("temperature",),
    "humidity": ("humidity", "relative_humidity"),
    "filter_life": ("filter_life_remaining", "filter_life"),
}


def _parse_devices() -> list[dict]:
    """`name@ip=token` entries, comma-separated; name (and `name@`) optional."""
    raw = os.getenv("XIAOMI_PURIFIERS", "").strip()
    devices = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry or "=" not in entry:
            continue
        left, token = entry.rsplit("=", 1)
        name, _, ip = left.partition("@")
        if not ip:  # no name given, left IS the ip
            name, ip = "", name
        token = token.strip().lower()
        if len(token) != 32 or not all(c in "0123456789abcdef" for c in token):
            _warn_once(f"token-{ip}", "xiaomi-air: skipping %s — token must be 32 hex chars" % left)
            continue
        devices.append({"name": name.strip(), "ip": ip.strip(), "token": token})
    return devices


def _warn_once(key: str, msg: str) -> None:
    if key not in _state["warned"]:
        log.warning(msg)
        _state["warned"].add(key)


def _status(ip: str, token: str):
    """MIoT first (current models), legacy miio after (1/2/2S/early Pro). Raises the last error."""
    from miio import AirPurifier, AirPurifierMiot  # noqa: PLC0415

    AirPurifierMiot._mappings.update(_MODEL_MAPPINGS)
    try:
        return AirPurifierMiot(ip, token).status(), "miot"
    except Exception as miot_err:  # noqa: BLE001
        try:
            return AirPurifier(ip, token).status(), "legacy"
        except Exception:  # noqa: BLE001
            raise miot_err


def _device_meta(ip: str, token: str, proto: str) -> dict:
    """Model + MAC for a stable sensor_id, cached per process; one extra UDP round trip."""
    if ip in _state["meta"]:
        return _state["meta"][ip]
    meta = {"model": None, "mac": None, "firmware": None, "proto": proto}
    try:
        from miio import Device  # noqa: PLC0415

        info = Device(ip, token).info()
        meta.update({"model": getattr(info, "model", None), "mac": getattr(info, "mac_address", None),
                     "firmware": getattr(info, "firmware_version", None)})
    except Exception:  # noqa: BLE001
        pass
    _state["meta"][ip] = meta
    return meta


def fetch(hc):
    """Contract: (sensors, readings). Missing config, library or an unreachable unit logs once and
    yields nothing for that unit — the pack must never take the node down."""
    devices = _parse_devices()
    if not devices:
        _warn_once("config", "xiaomi-air: XIAOMI_PURIFIERS is empty — set name@ip=token per purifier "
                             "(tokens via xiaomi-cloud-tokens-extractor)")
        return [], []
    import importlib.util  # noqa: PLC0415

    if importlib.util.find_spec("miio") is None:
        _warn_once("pip", "xiaomi-air: python-miio is not installed. "
                          "`planetai packs install` installs code-pack dependencies.")
        return [], []

    sensors, readings = [], []
    ts = datetime.now(timezone.utc)
    for dev in devices:
        ip, token = dev["ip"], dev["token"]
        try:
            status, proto = _status(ip, token)
        except Exception as e:  # noqa: BLE001
            _warn_once(f"poll-{ip}", "xiaomi-air: %s unreachable (%s: %s)" % (ip, type(e).__name__, e))
            continue
        meta = _device_meta(ip, token, proto)
        sid = "xm-" + (meta["mac"].replace(":", "")[-6:].lower() if meta["mac"]
                       else ip.replace(".", "-"))
        name = dev["name"] or ("Xiaomi purifier " + ip)
        sensors.append({
            "sensor_id": sid, "source": "xiaomi-air", "name": name,
            "lat": None, "lon": None, "indoor": True, "local": True,
            "meta": {"host": ip, "model": meta["model"], "firmware": meta["firmware"],
                     "protocol": proto,
                     "correction": "none — Xiaomi optical PM is not a Plantower; pm25 is raw density"},
        })
        for metric, attrs in _PROPS.items():
            value = next((getattr(status, a) for a in attrs
                          if getattr(status, a, None) is not None), None)
            if value is None:
                continue
            try:
                readings.append((ts, sid, metric, float(value)))
            except (TypeError, ValueError):
                _warn_once(f"value-{sid}-{metric}", "xiaomi-air: %s %s not numeric: %r"
                           % (sid, metric, value))
    return sensors, readings
