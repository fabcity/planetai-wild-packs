# digital-subak

The weather stations of [Digital Subak](https://digitalsubak.id), Radek Oborny's network in Bali, read from its
key-free API. I wrote it for the Bali nodes, and it reads three stations, all in Tabanan: Kedungu by the sea, Sarinbuana on
the slopes of Batukaru, and Island Organics higher up. Kedungu Garden Homes, Sarinbuana Eco Lodge and Island Organics
host them.

Digital Subak's map also shows around twenty Weather Underground stations. Those are IBM's data, so the pack never
reads them, and it skips a station listed as a copy of one of Radek's.

## What it reads

Every 5 minutes, from `/api/stations`: air temperature, humidity, dew point, pressure, wind (speed, gust, direction),
solar radiation, UV index, and rain over the last hour and the last 24 hours. A value Digital Subak flags as stuck or
out of range is not stored.

Every hour, from `/api/daily`: each finished day's rain and ET0, and the 7-day water balance. ET0 is how much water a
reference crop loses to the air in a day (FAO-56, computed by Digital Subak). The water balance is the last 7 days of
rain minus the last 7 days of ET0. Digital Subak gives it as a guide for irrigation, it says nothing about any one
field.

One sensor per station, `dsubak-<code>`, at the station's coordinates, as `kind: portal` and `scale: region`. They are
tens of kilometres from a house in Ungasan, so they stay out of the room, yard and ring medians. They show as their own
section on Now, and Kedungu's rain and water balance sit as readouts under Water.

## Where the data goes

Radek said yes to a node using his stations on 25 Nov 2026. He did not say the data could travel further, so every
channel is `role: private`. The node's page, its readouts and sections use the readings, and the daily export, the
aggregates a parent receives, the report bundle and agents never see them. If he gives a licence that covers sharing,
only `channels.yml` changes, from `private` to `ambient`.

## Settings

None. There is no key, and the station list comes from the API, so a new Ecowitt station of his shows up by itself,
with a sensor and readings but no readout until someone adds one to `pack.yaml`.

It needs `PACKS_ALLOW_CODE=1` and node v0.82 or later (for `role: private`).

## What it does not know

- Three stations, all in Tabanan. Nothing about the Bukit, Denpasar, Ubud or the north. For a node in Ungasan, Kedungu
  is the closest, about 28 km away.
- No thresholds of its own, and it raises no alert. Digital Subak runs its own rain alerts, and other people's
  stations never drive an alert on a node.
- No history. It starts storing when it is turned on.
- Digital Subak's own extras (soil moisture, well level, the Pigstone wave buoy, flood reports, BMKG warnings) are
  not read. Some are still a pilot there.

## Licence

The code is Apache-2.0. The data is Digital Subak's, used on this node with Radek Oborny's permission, and credited as
"Data: Digital Subak (digitalsubak.id)". It is not open data, so it stays on the node.
