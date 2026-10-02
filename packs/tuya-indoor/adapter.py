"""Indoor temperature and humidity from Tuya / Smart Life sensors, through the Tuya Cloud API.

Polls each listed device's status and records `temp` (deg C) and `humidity` (%) as one local, indoor sensor per
device, named by you ("Warm room", "Aircon room"). The readings join the indoor rules like any other room sensor
(the heat pack's indoor heat index, for one).

THE CREDENTIALS. TUYA_ACCESS_ID and TUYA_ACCESS_SECRET are secrets, and the secret signs every request. Nothing this
file logs or raises may contain either, a request header, or a device's local key. Errors carry Tuya's own numeric
`code` and `msg`, which say what is wrong ("sign invalid", "permission deny") and nothing that identifies you.

THE SIGNATURE (Tuya OpenAPI, HMAC-SHA256). sign = HMAC_SHA256(secret, client_id + [access_token] + t + nonce +
stringToSign).upper(), where stringToSign = METHOD \\n sha256(body) \\n signature-headers \\n path?query. The token
request has no access_token in the message; every business request does. `t` is the time in milliseconds.

CLOUD, NOT LOCAL. Battery and many Wi-Fi Tuya sensors answer only the cloud. A device's cloud status carries no time,
so a sensor that has dropped off Wi-Fi keeps reporting its last value; the pack skips a device Tuya says is offline.

The `contract` is `fetch(hc) -> (sensors, readings)`, like everything in app/sources.py.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timezone

log = logging.getLogger("planetai.pack.tuya_indoor")

SOURCE = "tuya-indoor"
ENDPOINTS = {                      # one per Tuya data centre; the account lives in exactly one of them
    "eu": "https://openapi.tuyaeu.com",      # Central Europe
    "us": "https://openapi.tuyaus.com",      # Western America
    "sg": "https://openapi.tuyasg.com",      # Singapore
    "in": "https://openapi.tuyain.com",      # India
    "cn": "https://openapi.tuyacn.com",      # China
}
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
# Status codes seen on Tuya temperature / humidity devices, most specific first.
TEMP_CODES = ("va_temperature", "temp_current", "temperature", "temp_value")
HUMIDITY_CODES = ("va_humidity", "humidity_value", "humidity_current", "humidity")
# Where a device's current values live differs by product: most answer the classic status call, and some (an infrared
# remote with a built-in sensor, for one) refuse it with "function not support" and answer one of the newer calls. They
# are tried in this order and the first that answers is remembered for the device.
STATUS_PATHS = ("/v1.0/devices/{id}/status", "/v1.0/iot-03/devices/{id}/status", "/v2.0/cloud/thing/{id}/shadow/properties")
_state = {"token": "", "token_until": 0.0, "at": 0.0, "specs": {}, "paths": {}, "warned": set()}


def _warn_once(key: str, msg: str, *a) -> None:
    if key not in _state["warned"]:
        _state["warned"].add(key)
        log.warning(msg, *a)


def sign(client_id: str, secret: str, t: str, method: str, path_query: str,
         access_token: str = "", nonce: str = "", body: str = "") -> str:
    """Tuya OpenAPI HMAC-SHA256 signature, upper-case hex."""
    string_to_sign = "\n".join([method.upper(), hashlib.sha256(body.encode()).hexdigest(), "", path_query])
    msg = client_id + access_token + t + nonce + string_to_sign
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest().upper()


class TuyaError(RuntimeError):
    """What Tuya said, and nothing that could carry a credential."""

    def __init__(self, what: str, code=None):
        super().__init__(what)
        self.code = code


def _config():
    cid = os.getenv("TUYA_ACCESS_ID", "").strip()
    secret = os.getenv("TUYA_ACCESS_SECRET", "").strip()
    base = (os.getenv("TUYA_ENDPOINT", "").strip()
            or ENDPOINTS.get((os.getenv("TUYA_REGION", "eu") or "eu").strip().lower(), ENDPOINTS["eu"])).rstrip("/")
    return cid, secret, base


def parse_devices(raw: str) -> list[tuple[str, str]]:
    """`id=Name,id=Name` -> [(id, name)]. A bare id gets a name made from it."""
    out = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        did, _, name = part.partition("=")
        did, name = did.strip(), name.strip()
        if did:
            out.append((did, name or f"Tuya {did[-6:]}"))
    return out


def _call(hc, cid: str, secret: str, base: str, path_query: str, token: str = ""):
    t = str(int(time.time() * 1000))
    headers = {"client_id": cid, "t": t, "sign_method": "HMAC-SHA256",
               "sign": sign(cid, secret, t, "GET", path_query, access_token=token)}
    if token:
        headers["access_token"] = token
    try:
        r = hc.get(base + path_query, headers=headers, timeout=30)
        body = r.json()
    except Exception as e:  # noqa: BLE001 - the exception text can hold the request, so name its type only
        raise TuyaError(f"Tuya request failed ({type(e).__name__})") from None
    if not body.get("success"):
        raise TuyaError(f"Tuya refused it: {body.get('msg') or 'no message'} (code {body.get('code')})", body.get("code"))
    return body.get("result")


def _token(hc, cid: str, secret: str, base: str) -> str:
    if _state["token"] and time.time() < _state["token_until"]:
        return _state["token"]
    res = _call(hc, cid, secret, base, "/v1.0/token?grant_type=1") or {}
    tok = res.get("access_token")
    if not tok:
        raise TuyaError("Tuya gave no access token")
    # Refresh a few minutes early; Tuya's token lives about two hours.
    _state["token"], _state["token_until"] = tok, time.time() + max(60, int(res.get("expire_time") or 7200) - 300)
    return tok


def _spec(hc, cid, secret, base, token, did) -> dict:
    """{code: {"scale": n, "unit": "..."}} from the device's own specification, once per process.
    Without it the value's scale is guessed (see _number), which is why it is asked for."""
    if did in _state["specs"]:
        return _state["specs"][did]
    out = {}
    try:
        res = _call(hc, cid, secret, base, f"/v1.0/devices/{did}/specifications", token) or {}
        for item in (res.get("status") or []) + (res.get("functions") or []):
            vals = item.get("values")
            vals = json.loads(vals) if isinstance(vals, str) and vals.strip().startswith("{") else (vals or {})
            out[item.get("code")] = {"scale": int(vals.get("scale", 0) or 0), "unit": str(vals.get("unit") or "")}
    except TuyaError as e:
        _warn_once(f"spec-{did}", "tuya-indoor: no specification for %s (%s); scaling by a guess", did[-6:], e)
        return out                 # not cached: asked again next time
    _state["specs"][did] = out
    return out


def _status(hc, cid, secret, base, token, did) -> list:
    """The device's [{code, value}, ...], from the first status call it answers. An expired token is never swallowed."""
    order = list(STATUS_PATHS)
    if did in _state["paths"]:
        order.remove(_state["paths"][did])
        order.insert(0, _state["paths"][did])
    last, answered = None, None
    for path in order:
        try:
            res = _call(hc, cid, secret, base, path.format(id=did), token)
        except TuyaError as e:
            if e.code in (1010, 1011):
                raise
            last = e
            continue
        # the thing-shadow call wraps the list: {"properties": [{code, value, ...}]}
        if isinstance(res, dict):
            res = res.get("properties") or res.get("status") or []
        if not read_status(res, {}):       # answered, but with nothing we can use: try the next call
            answered = answered if answered is not None else res
            continue
        _state["paths"][did] = path
        return res
    if answered is not None:
        return answered
    raise last or TuyaError("Tuya answered no status call")


def _number(code: str, raw, spec: dict, kind: str):
    """A status value as degrees C or per cent, or None if it cannot be trusted."""
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    info = spec.get(code)
    if info is not None:
        v = v / (10 ** info["scale"])
    elif kind == "temp" and abs(v) > 80:
        v = v / 10.0               # no specification: Tuya temperatures are usually tenths of a degree
    if kind == "temp":
        u = (info or {}).get("unit", "")
        if "\u2109" in u or ("F" in u.upper() and "C" not in u.upper() and "\u2103" not in u):   # the one-character F and C signs
            v = (v - 32) * 5 / 9
        return round(v, 2) if -30 <= v <= 70 else None
    return round(v, 2) if 0 <= v <= 100 else None


def read_status(status: list, spec: dict) -> dict:
    """{'temp': C, 'humidity': %} from a Tuya status list [{code, value}, ...]."""
    by = {s.get("code"): s.get("value") for s in (status or []) if isinstance(s, dict)}
    out = {}
    for kind, codes in (("temp", TEMP_CODES), ("humidity", HUMIDITY_CODES)):
        for c in codes:
            if c in by:
                v = _number(c, by[c], spec, kind)
                if v is not None:
                    out[kind] = v
                    break
    return out


def fetch(hc):
    cid, secret, base = _config()
    devices = parse_devices(os.getenv("TUYA_DEVICES", ""))
    if not (cid and secret and devices):
        _warn_once("config", "tuya-indoor: set TUYA_ACCESS_ID, TUYA_ACCESS_SECRET and TUYA_DEVICES (id=Name,...) — the pack is idle")
        return [], []
    every = max(5, int(float(os.getenv("TUYA_EVERY_MIN", "10") or 10))) * 60
    if time.time() - _state["at"] < every:
        return [], []
    secondary = {x.strip() for x in os.getenv("TUYA_SECONDARY", "").split(",") if x.strip()}
    ts = datetime.now(timezone.utc).replace(microsecond=0)
    sensors, readings, failed = [], [], []
    for attempt in (1, 2):         # a second pass only if the token was refused as expired
        try:
            token = _token(hc, cid, secret, base)
            sensors, readings, failed = [], [], []
            for did, name in devices:
                try:
                    st = _status(hc, cid, secret, base, token, did)
                    got = read_status(st, _spec(hc, cid, secret, base, token, did))
                except TuyaError as e:
                    if e.code in (1010, 1011):          # token invalid or expired
                        raise
                    failed.append(f"{did[-6:]}: {e}")
                    log.warning("tuya-indoor: %s: %s", did[-6:], e)
                    continue
                if not got:
                    _warn_once(f"empty-{did}", "tuya-indoor: %s reported no temperature or humidity (codes: %s)",
                               did[-6:], ", ".join(str(s.get("code")) for s in (st or [])) or "none")
                    continue
                sid = f"tuya-{did}"
                sensors.append({"sensor_id": sid, "source": SOURCE, "name": name, "lat": None, "lon": None,
                                "indoor": True, "local": True, "kind": "sensor", "scale": "community",
                                "cadence": f"PT{every // 60}M",
                                "meta": {"vendor": "tuya", "device": did[-6:], "region": base.split("openapi")[-1],
                                         # `secondary`: read and drawn, but not the house's number and no heat pages
                                         "role": "secondary" if did in secondary else "reference"}})
                readings += [(ts, sid, m, v) for m, v in got.items()]
            break
        except TuyaError as e:
            if e.code in (1010, 1011) and attempt == 1:
                _state["token"] = ""
                continue
            _warn_once(f"auth-{e.code}", "tuya-indoor: %s", e)
            raise RuntimeError(str(e)) from None
    if devices and failed and len(failed) == len(devices):
        raise RuntimeError(failed[0])
    _state["at"] = time.time()
    return sensors, readings


# Metrics this pack writes that tools/check_docs.py cannot see in the code above (names built from a mapping).
PRODUCES = (
    "temp",
    "humidity",
)
