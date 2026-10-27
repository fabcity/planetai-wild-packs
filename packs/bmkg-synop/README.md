# bmkg-synop

The hourly report of BMKG's weather station at Ngurah Rai airport (WIGOS `0-20000-0-97230`), on Bali's southern
coast, read off WMO's WIS2 network. I wrote it for Bali, and it is the only Bali station in the feed.

It reads that one station and nothing else. There is no setting to pick another one: the readings keep one sensor id
and the labels on the page name the airport, so pointing it at another station would file that station's weather
under Ngurah Rai. A node elsewhere in Indonesia needs its own pack, with its own labels.

Until now the node's outdoor weather in Bali came from models, Open-Meteo and BMKG's own forecast. This is a
measurement, made by Indonesia's weather service, so the node can check its own sensors and the forecast against it.

## What it reads

Air temperature, dew point, humidity, station pressure, wind (the 10-minute mean), total cloud, visibility, and rain
over the last hour and the last 24 hours when the report carries them. One sensor, `bmkg-synop`, at the station's
coordinates. It shows as its own section on Now, and as two readouts beside Heat.

The station is kilometres from the house and reports once an hour, so the pack hands it to the node as `kind: portal`,
a published measurement and not a device at the address. That keeps it out of the room, yard and ring medians, which
read only the node's own kind of sensor, and its channels are `comparable: false` as well. It never stands in for the
region column either, which stays Open-Meteo.

## How it gets there

WIS2 has no HTTP API. Each report is an MQTT notification on the global brokers, with the BUFR message inline, and
six global caches announce the same report. The pack keeps one subscription open to Météo-France's broker
(`globalbroker.meteo.fr:8883`, the public login `everyone`/`everyone`), keeps each report once by its data id, and
decodes it with [pybufrkit](https://github.com/ywangd/pybufrkit).

Reports come late. On 26 Oct 2026 the 07:00 UTC report was published at 07:10 and reached the broker again from all
six caches around 10:55. The pack stores each reading at its observation time, so a late report lands in the right
hour. When the node starts, it waits for the next notification; it does not go back for what it missed.

## Settings

```
BMKG_SYNOP_BROKER=      # blank for globalbroker.meteo.fr
```

It needs `PACKS_ALLOW_CODE=1`, and `planetai packs install` to add pybufrkit (and bitstring 4, which pybufrkit
0.2.25 needs: bitstring 5 breaks it).

## What it does not know

- One station, at an airport by the sea. It says nothing about Ubud, the highlands or the north.
- It has no thresholds of its own and raises no alert. Heat's line is still the house's.
- Rain is only there when BMKG fills in the group. When a report leaves it empty, the pack stores no rain at all.
- Only BMKG's feed. Another country's WIS2 topic would need its own `TOPIC`, and that is the step to take before
  this becomes core.

## Licence

The code is Apache-2.0. The data is BMKG's, published as WMO core data under the WMO Unified Data Policy
(Resolution 1, Cg-Ext(2021)): free and unrestricted. Credit BMKG when you show it.
