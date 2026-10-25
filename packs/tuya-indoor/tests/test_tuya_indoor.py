"""The tuya-indoor pack, offline: no Tuya, no keys, no database.
Run: python3 packs/tuya-indoor/tests/test_tuya_indoor.py
"""
import hashlib
import hmac
import importlib.util
import json
import os

SECRET = "SECRET-THAT-MUST-NOT-LEAK"
os.environ.update(TUYA_ACCESS_ID="ID123", TUYA_ACCESS_SECRET=SECRET, TUYA_REGION="eu",
                  TUYA_DEVICES="devA00001=Warm room,devB00002=Aircon room", TUYA_EVERY_MIN="10")
spec = importlib.util.spec_from_file_location("tuyapack", "packs/tuya-indoor/adapter.py")
A = importlib.util.module_from_spec(spec); spec.loader.exec_module(A)

# ---------------------------------------------------------------- the signature
t = "1790000000000"
want = hmac.new(SECRET.encode(), ("ID123" + "TOK" + t + "" + "GET\n" + hashlib.sha256(b"").hexdigest() + "\n\n/v1.0/x").encode(),
                hashlib.sha256).hexdigest().upper()
assert A.sign("ID123", SECRET, t, "get", "/v1.0/x", access_token="TOK") == want
assert A.sign("ID123", SECRET, t, "GET", "/v1.0/x") != want            # the token is part of the message
assert A.EMPTY_SHA256 == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

# ---------------------------------------------------------------- devices
assert A.parse_devices("a=Warm room, b=Aircon room,c") == [("a", "Warm room"), ("b", "Aircon room"), ("c", "Tuya c")]
assert A.parse_devices("") == []

# ---------------------------------------------------------------- status values
tenths = {"va_temperature": {"scale": 1, "unit": "℃"}, "va_humidity": {"scale": 0, "unit": "%"}}
assert A.read_status([{"code": "va_temperature", "value": 276}, {"code": "va_humidity", "value": 58}], tenths) == {"temp": 27.6, "humidity": 58.0}
# no specification: a temperature this big is tenths, a small one is already degrees
assert A.read_status([{"code": "temp_current", "value": 245}], {})["temp"] == 24.5
assert A.read_status([{"code": "temp_current", "value": 24}], {})["temp"] == 24.0
# Fahrenheit is converted
assert A.read_status([{"code": "va_temperature", "value": 770}], {"va_temperature": {"scale": 1, "unit": "℉"}})["temp"] == 25.0
# nonsense is dropped, not recorded
assert A.read_status([{"code": "va_temperature", "value": 9999}, {"code": "va_humidity", "value": 140}], tenths) == {}
assert A.read_status([{"code": "battery", "value": 80}], {}) == {}


# ---------------------------------------------------------------- a fake Tuya
class R:
    def __init__(self, body): self._b = body
    def json(self): return self._b


class Fake:
    def __init__(self, offline=(), token_fails_once=False, no_classic=(), only_shadow=False, empty_classic=()):
        self.empty_classic = set(empty_classic)
        self.calls, self.offline, self.tf = [], set(offline), token_fails_once
        self.no_classic, self.only_shadow = set(no_classic), only_shadow
    def get(self, url, headers=None, timeout=None):
        path = url.split("tuyaeu.com")[1]
        self.calls.append((path, dict(headers or {})))
        if path.startswith("/v1.0/token"):
            return R({"success": True, "result": {"access_token": "TOK", "expire_time": 7200}})
        if self.tf and "/status" in path:
            self.tf = False
            return R({"success": False, "code": 1010, "msg": "token invalid"})
        did = path.split("/")[3] if not path.startswith(("/v1.0/iot-03", "/v2.0")) else path.split("/")[-2 if path.endswith("/status") else -3]
        if did in self.offline:
            return R({"success": False, "code": 1106, "msg": "permission deny"})
        if path.endswith("/specifications"):
            return R({"success": True, "result": {"status": [
                {"code": "va_temperature", "values": json.dumps({"unit": "℃", "scale": 1})},
                {"code": "va_humidity", "values": json.dumps({"unit": "%", "scale": 0})}]}})
        v = {"devA00001": (301, 71), "devB00002": (234, 52)}[did]
        rows = [{"code": "va_temperature", "value": v[0]}, {"code": "va_humidity", "value": v[1]}]
        if did in self.empty_classic and not path.startswith("/v2.0"):
            return R({"success": True, "result": []})
        if did in self.no_classic and path.startswith("/v1.0/devices/"):
            return R({"success": False, "code": 2003, "msg": "function not support"})
        if did in self.no_classic and path.startswith("/v1.0/iot-03") and self.only_shadow:
            return R({"success": False, "code": 1108, "msg": "uri path invalid"})
        if path.startswith("/v2.0/cloud/thing"):
            return R({"success": True, "result": {"properties": rows}})
        return R({"success": True, "result": rows})


def fresh():
    A._state.update(token="", token_until=0.0, at=0.0, specs={}, paths={}, warned=set())


fresh(); hc = Fake()
sensors, readings = A.fetch(hc)
assert [s["sensor_id"] for s in sensors] == ["tuya-devA00001", "tuya-devB00002"]
assert [s["name"] for s in sensors] == ["Warm room", "Aircon room"]
assert all(s["indoor"] and s["local"] and s["kind"] == "sensor" and s["lat"] is None for s in sensors)
got = {(r[1], r[2]): r[3] for r in readings}
assert got[("tuya-devA00001", "temp")] == 30.1 and got[("tuya-devA00001", "humidity")] == 71.0
assert got[("tuya-devB00002", "temp")] == 23.4 and got[("tuya-devB00002", "humidity")] == 52.0
# every request carries the id, a signature and the timestamp; business requests carry the token; no secret anywhere
for path, h in hc.calls:
    assert h["client_id"] == "ID123" and h["sign"] == h["sign"].upper() and h["t"].isdigit() and h["sign_method"] == "HMAC-SHA256"
    assert ("access_token" in h) == (not path.startswith("/v1.0/token")), path
    assert SECRET not in json.dumps(h)
# `TUYA_SECONDARY` marks a room as secondary; the others are the reference
assert {x["name"]: x["meta"]["role"] for x in sensors} == {"Warm room": "reference", "Aircon room": "reference"}
os.environ["TUYA_SECONDARY"] = "devA00001"; A._state["at"] = 0.0
sensors2, _ = A.fetch(hc)
assert {x["name"]: x["meta"]["role"] for x in sensors2} == {"Warm room": "secondary", "Aircon room": "reference"}
del os.environ["TUYA_SECONDARY"]
A._state["at"] = __import__("time").time()
# polled again at once: nothing, because the interval has not passed
assert A.fetch(hc) == ([], [])
# the token and the specification are fetched once per process
A._state["at"] = 0.0
n = len(hc.calls); A.fetch(hc)
assert not any(p.startswith("/v1.0/token") or p.endswith("/specification") for p, _ in hc.calls[n:])

# an expired token is refreshed and the pass retried
fresh(); hc = Fake(token_fails_once=True)
sensors, readings = A.fetch(hc)
assert len(sensors) == 2 and sum(1 for p, _ in hc.calls if p.startswith("/v1.0/token")) == 2

# one device refused: the other still reads; both refused: it raises with Tuya's words and no secret
fresh(); sensors, readings = A.fetch(Fake(offline={"devA00001"}))
assert [s["name"] for s in sensors] == ["Aircon room"]
fresh()
try:
    A.fetch(Fake(offline={"devA00001", "devB00002"}))
    raise AssertionError("both refused should raise")
except RuntimeError as e:
    assert "permission deny" in str(e) and SECRET not in str(e)

# a transport failure names its type and nothing else
class Boom:
    def get(self, url, headers=None, timeout=None):
        raise OSError(f"connection to {url} with {headers}")
fresh()
try:
    A.fetch(Boom())
    raise AssertionError("should raise")
except RuntimeError as e:
    assert "OSError" in str(e) and SECRET not in str(e) and "client_id" not in str(e)

# a device that refuses the classic status call ("function not support", 2003) is read through a newer one,
# and the one that answered is remembered so the next poll goes straight to it
for only_shadow in (False, True):
    fresh(); hc = Fake(no_classic={"devB00002"}, only_shadow=only_shadow)
    sensors, readings = A.fetch(hc)
    got = {(r[1], r[2]): r[3] for r in readings}
    assert got[("tuya-devB00002", "temp")] == 23.4 and got[("tuya-devA00001", "temp")] == 30.1, got
    want = "/v2.0/cloud/thing/devB00002/shadow/properties" if only_shadow else "/v1.0/iot-03/devices/devB00002/status"
    assert A._state["paths"]["devB00002"].format(id="devB00002") == want and A._state["paths"]["devA00001"].format(id="devA00001") == "/v1.0/devices/devA00001/status"
    n = len(hc.calls); A._state["at"] = 0.0; A.fetch(hc)
    again = [p for p, _ in hc.calls[n:] if "devB00002" in p]
    assert again == [want], again

# a call that answers with an empty list (an IR/LCD remote) is not the end: the shadow call is tried next
fresh(); hc = Fake(empty_classic={"devB00002"})
sensors, readings = A.fetch(hc)
assert {(r[1], r[2]): r[3] for r in readings}[("tuya-devB00002", "temp")] == 23.4
assert A._state["paths"]["devB00002"].startswith("/v2.0/cloud/thing")

# not configured: idle and quiet
fresh(); os.environ["TUYA_ACCESS_SECRET"] = ""
assert A.fetch(Fake()) == ([], [])
print("tuya-indoor: ok")
