# tuya-indoor

Indoor temperature and humidity from your Tuya / Smart Life sensors, one named room per device. It reads Tuya's cloud
for you; it does not control anything.

**What it adds**
- One local, indoor sensor per device in `TUYA_DEVICES` (`tuya-<device id>`), with the name you give it.
- Metrics `temp` (°C) and `humidity` (%). The values are scaled from the device's own specification, so a status of
  `276` on a tenths-of-a-degree sensor is 27.6 °C; Fahrenheit sensors are converted.
- Nothing else: the existing indoor rules (the heat pack's indoor heat index, for one) pick the sensors up by themselves.
- A reference room and secondary rooms. List a device's id in `TUYA_SECONDARY` (an empty workshop that bakes behind big
  windows, say) and it is still read and drawn among the sensors, but it is left out of the house's room number on the
  Heat and Air cards and it never raises the indoor heat alerts. Every other device is the reference, and with one
  reference the card shows exactly that room. The role is written to the sensor's `meta.role` on every poll.

**Set up**
1. A cloud project on platform.tuya.com in the data centre your Smart Life account lives in, with *IoT Core* and
   *Authorization Token Management* authorised, and your app account linked (Devices → Link App Account).
2. In `.env`: `TUYA_ACCESS_ID` and `TUYA_ACCESS_SECRET` (the project's Authorization Key), `TUYA_REGION` (`eu`, `us`, `sg`,
   `in` or `cn`; `TUYA_ENDPOINT` overrides it), and `TUYA_DEVICES=<id>=Warm room,<id>=Aircon room`.
3. Restart the app. `docker compose logs app` says `tuya-indoor: ...` once if something is wrong, with Tuya's own words.

**Limits.** It polls every `TUYA_EVERY_MIN` minutes (10 by default, never under 5) because the free tier limits the
calls a month, and its IoT Core trial has to be renewed on Tuya's site now and then; an expired trial shows as a
"permission deny" or "not subscribed" message. A cloud status has no timestamp, so a sensor that has lost Wi-Fi keeps its
last value until Tuya reports it offline. The Access Secret and any device's local key are credentials and are never logged.

**Tests:** `python3 packs/tuya-indoor/tests/test_tuya_indoor.py` (offline; a fake Tuya, the signature, scaling, token refresh, and that no
error carries a secret).

## Devices that refuse the classic status call

Some devices (for example IR/LCD remotes that carry a sensor) answer `function not support` (code 2003) on `/v1.0/devices/{id}/status`. The pack then tries `/v1.0/iot-03/devices/{id}/status` and the thing-shadow properties call, and remembers the one that answered. If all three are refused, the log line names the Tuya code; try "Query Properties" in the Tuya API Explorer for that device to see what it exposes.

## What it needs from the node

A room marked secondary (`TUYA_SECONDARY`) is drawn but is not the house's number, and raises no heat alert. That needs
the node's secondary-room support (in planetai-node after v0.75.8). On a node without it the pack still reads and draws
every room; every room then counts toward the house's heat.
