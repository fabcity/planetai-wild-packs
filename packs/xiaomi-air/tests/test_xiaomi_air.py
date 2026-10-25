"""The xiaomi-air pack against fakes of node #1's two real purifiers.

Run from a node's folder: python3 packs/xiaomi-air/tests/test_xiaomi_air.py
The fakes reproduce the property surface of the two units as they answered on 2026-09-17 (zhimi.airp.meb1
"Elite": pm2.5 12, 29.0 C, 67% RH, pm10 1, filter 99%; xiaomi.airp.cpa4 "4 Compact": pm2.5 21, filter 97%,
and NO temperature/humidity — that model has no such hardware). What is checked is what fails silently: a
reading emitted for a sensor the model does not have (a None or a 0 in stats is a lie), an unstable
sensor_id, and an unreachable unit taking the others down with it.
"""
import importlib.machinery
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeStatus:
    def __init__(self, **kw):
        self.is_on = kw.pop("is_on", True)
        self.mode = kw.pop("mode", "auto")
        for k, v in kw.items():
            setattr(self, k, v)


class FakeInfo:
    def __init__(self, model, mac, fw):
        self.model, self.mac_address, self.firmware_version = model, mac, fw


# The two units as they answered on node #1's LAN. cpa4's status has no temperature/humidity ATTRIBUTES
# at all — on the real model the mapping has no such properties, so anything that reads them gets None.
DEVICES = {
    "192.168.4.98": {
        "model": "zhimi.airp.meb1", "mac": "1C:EA:AC:38:6F:13", "fw": "2.2.10",
        "status": FakeStatus(aqi=12, temperature=29.0, humidity=67, pm10_density=1,
                             filter_life_remaining=99, filter_hours_used=12, motor_speed=770),
    },
    "192.168.4.109": {
        "model": "xiaomi.airp.cpa4", "mac": "E4:FE:43:88:5F:DF", "fw": "2.2.10_0021",
        "status": FakeStatus(aqi=21, filter_life_remaining=97, filter_hours_used=88),
    },
}


class DeviceException(Exception):
    pass


class AirPurifierMiot:
    _mappings = {}

    def __init__(self, ip, token, *a, **kw):
        if ip not in DEVICES:
            raise DeviceException(f"Unable to discover the device {ip}")
        self.ip = ip

    def status(self):
        return DEVICES[self.ip]["status"]


class AirPurifier:  # legacy path: present so the fallback exists, never answers here
    def __init__(self, ip, token, *a, **kw):
        raise DeviceException("not a legacy device")


class Device:
    def __init__(self, ip, token, *a, **kw):
        if ip not in DEVICES:
            raise DeviceException(f"Unable to discover the device {ip}")
        self.ip = ip

    def info(self):
        d = DEVICES[self.ip]
        return FakeInfo(d["model"], d["mac"], d["fw"])


fake_miio = types.ModuleType("miio")
fake_miio.AirPurifierMiot = AirPurifierMiot
fake_miio.AirPurifier = AirPurifier
fake_miio.Device = Device
fake_miio.DeviceException = DeviceException
fake_miio.__spec__ = importlib.machinery.ModuleSpec("miio", None)
sys.modules["miio"] = fake_miio

import adapter as A  # noqa: E402

TOKENS = {"192.168.4.98": "ce969d32867ac6db028f69ef8cfa9309",
          "192.168.4.109": "e0876812bf6a2681e87d8d69d8a6cc8c"}


def reset(env):
    os.environ["XIAOMI_PURIFIERS"] = env
    A._state["warned"].clear()
    A._state["meta"].clear()
    AirPurifierMiot._mappings = {}


# ---- env parsing: the canonical form, the bare-ip form, and a malformed token skipped without a word
reset("Purifier Elite@192.168.4.98={t1},192.168.4.109={t2},Broken@10.0.0.9=xyz".format(**{"t1": TOKENS["192.168.4.98"], "t2": TOKENS["192.168.4.109"]}))
devs = A._parse_devices()
assert len(devs) == 2, f"bad token entry must be skipped, got {devs}"
assert devs[0]["name"] == "Purifier Elite" and devs[1]["name"] == ""

# ---- the full fetch against both units
sensors, readings = A.fetch(None)
assert len(sensors) == 2
by_id = {s["sensor_id"]: s for s in sensors}
assert set(by_id) == {"xm-386f13", "xm-885fdf"}, "sensor ids derive from MACs, stable across polls"
for s in sensors:
    assert s["indoor"] is True and s["local"] is True, "every rule depends on these two flags"
    assert s["source"] == "xiaomi-air"
assert by_id["xm-386f13"]["name"] == "Purifier Elite"
assert by_id["xm-885fdf"]["name"] == "Xiaomi purifier 192.168.4.109", "nameless units get a name, not a blank"
assert by_id["xm-386f13"]["meta"]["model"] == "zhimi.airp.meb1"
assert by_id["xm-386f13"]["meta"]["protocol"] == "miot"

got = {}
for ts, sid, metric, value in readings:
    got.setdefault(sid, {})[metric] = value
elite, compact = got["xm-386f13"], got["xm-885fdf"]
assert elite == {"pm25": 12.0, "pm10": 1.0, "temp": 29.0, "humidity": 67.0, "filter_life": 99.0}, elite
assert compact == {"pm25": 21.0, "filter_life": 97.0}, compact
assert "temp" not in compact and "humidity" not in compact, \
    "a 4 Compact has no temp/RH hardware — a reading for one would be invented data"

# ---- the custom MIoT mappings must land in the class registry (the kwarg path is ignored upstream)
assert "zhimi.airp.meb1" in AirPurifierMiot._mappings and "xiaomi.airp.cpa4" in AirPurifierMiot._mappings
assert AirPurifierMiot._mappings["zhimi.airp.meb1"]["aqi"] == {"siid": 3, "piid": 4}

# ---- an unreachable unit loses only itself
reset("Purifier Elite@192.168.4.98={t1},Ghost@192.168.4.250={t2}".format(**{"t1": TOKENS["192.168.4.98"], "t2": "0" * 32}))
sensors, readings = A.fetch(None)
assert [s["sensor_id"] for s in sensors] == ["xm-386f13"], "one dead unit must not take the other down"

# ---- empty config idles
reset("")
assert A.fetch(None) == ([], [])

print("xiaomi-air: two real units, one compact's missing sensors, one ghost unit, one empty config")
