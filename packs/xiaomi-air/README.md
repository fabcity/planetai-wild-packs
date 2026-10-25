# Xiaomi air purifiers (LAN)

Xiaomi / Mi Home air purifiers read directly on the LAN — PM2.5, temperature, humidity and filter
life, indoors. Written for a household in Kuta Selatan, Bali, with two units (a living-room and a
bedroom purifier); the thresholds and wording travel anywhere a Mi Home purifier does.

## What it does

- Polls every purifier in `XIAOMI_PURIFIERS` once per node cycle over UDP (miio/MIoT, port 54321).
- Registers each unit as `local` + `indoor`, so the readings join the **air-quality** pack's indoor
  rules (`indoor_pm25_high` — "purifier on, windows shut" — now measures the room the purifier is
  actually in) and the **trust** pack's liveness checks, and stay out of outdoor ambient averages.
- Emits `pm25`, `temp`, `humidity` (ambient) and `filter_life` (device_health); `pm10` where the
  model reports it.
- One rule of its own: `purifier_filter_low` (warn, weekly cooldown) at 10% filter remaining —
  Xiaomi's own ~5% warning is late when a replacement filter takes a week to arrive.

## Adding it to a node

xiaomi-air was a core pack until the release after v0.76, and is wild from then on. On that release or later:

```
planetai packs add xiaomi-air
```

A node that ran it as core keeps its `XIAOMI_PURIFIERS` line. If the node was updated from a tarball, the old
core folder is still there, and `packs add` will not replace a folder it did not fetch: delete `packs/xiaomi-air`
first. A node that updates with git loses the folder on update, and the purifiers go quiet until the pack is
added again.

`XIAOMI_PURIFIERS` is listed under `secrets:`, so a node that carries pack secrets (planetai-node#167, after
v0.76) masks the tokens once saved, even to the admin token. An older node shows them to anyone holding the admin
token and to connected agents.

## Setup

1. Extract each unit's 32-hex device token once, with
   [`xiaomi-cloud-tokens-extractor`](https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor)
   (one Mi Home login, any machine). Current firmware does NOT expose tokens in the LAN handshake —
   verified on node #1's units (September 2026). After extraction nothing talks to the Xiaomi cloud.
2. Give each purifier a fixed IP (DHCP reservation).
3. `XIAOMI_PURIFIERS=Living Room@192.168.4.98=token,Bedroom@192.168.4.109=token` in `.env`
   (`planetai packs install` adds the line; names are free text, `@name` optional).
4. `planetai packs install` (installs python-miio into the image), then watch `planetai logs` for the
   first poll. `planetai sensors --json` should list the units as `xm-<mac6>`.

## Protocol coverage

MIoT is tried first, legacy miio after; both are handled by python-miio.

- **MIoT (most 2019+ units):** 3H, 4, 4 Lite, 4 Pro, Pro H, Elite, Smart Air Purifier 5/5 Pro, the
  `za1`/`vb2`/`vb4`/`ma4` model families.
- **Legacy:** 1, 2, 2S, early Pro.
- Dehumidifiers, humidifiers and fans are NOT covered — same protocol family, different properties;
  a sibling pack when somebody owns one.

## What this pack does not know

- **No EPA humidity correction.** The node's EPA 2021 correction is derived for Plantower lasers
  (PurpleAir, AirGradient, DIY PMS5003). Xiaomi's optical PM sensor is not a Plantower; applying that
  regression would invent accuracy it doesn't have. `pm25` here is the raw density and `meta` says so.
- **The vendor AQI composite is ignored.** Xiaomi's "AQI" property on these models IS the PM2.5
  density, not a separate index; there is nothing extra to store.
- **Fan speed, mode and motor RPM are not emitted.** They are device health, and the only
  consumable a household acts on is the filter. Add them to `_PROPS` if a use appears.
- **No control.** This pack reads. Turning the purifier on when the room is dirty is a rule +
  actuation problem, deliberately not bundled with sensing (the node's alert already says what to do).

## Licence

Apache-2.0, as written in the planetai-node repository. It installs python-miio, which is GPL-3.0-only.
