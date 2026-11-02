# surf

I wanted my node to tell me, the evening before, where the surf could be good tomorrow, so I could check those spots
properly and decide whether to get up early.

At 17:00 the bot sends up to three spots, each with a time window, the swell (height, period, direction), its power in
kW per metre of crest, the wind, the tide, and a Windy link that opens the spot's forecast. On a day where nothing
passes, it sends nothing. If you go, answer with the number in the message and your own words, for example
`/act 812 Ulu good, head high 6 to 8, Bingin closing out`, and `planetai run surf review` builds a journal for each
spot, with what you said next to that morning's numbers.

It was written for Bali, from my house in Ungasan, with twelve spots in `spots.yml`: Uluwatu, Padang Padang, Bingin,
Balangan, Kuta Reef, Canggu, Medewi, Nusa Dua, Serangan, Sanur, Keramas and Green Bowl. Another coast needs its own
spots file.

## Settings

- `SURF_SPOTS`: the ids from `spots.yml` to watch, comma-separated. Blank keeps the pack idle, with no network.
- `SURF_MIN_PERIOD`: the shortest swell period that counts, 10 seconds by default.
- The message is a `warn` alert, so it reaches Telegram only where `ALERT_LEVEL` is `warn` or `info`. On the default
  `act` it is recorded and shown on the page, and not sent.
- It is a code pack, so the node runs it only with `PACKS_ALLOW_CODE=1`, and it needs a node that fills `{act}` in a
  rule's message.

## Where the numbers come from

An hour passes when a swell comes from the spot's window with a long enough period and its power is inside the
spot's range, the wind is offshore (and not over 25 km/h) or under 8 km/h from anywhere, the tide is in a third of
the day's range the spot works on, and the wind sea is under half the swell. Two such hours in a row make the spot
good. When two swells come from the window at different angles, the line says "mixed".

Every one of those numbers is a first guess, and so is every row of `spots.yml`. I wrote the table from general
knowledge, I haven't surfed all of these breaks, and I checked the rule on a week of Open-Meteo's own archive against
three days other people told me about. The design, with that week's table, is in
`docs/superpowers/specs/2026-11-02-surf-pack-design.md`. The journal is how the numbers get better, so read it after
a few weeks and fix `spots.yml`.

Measuring a swell by its power and keeping a journal for each spot come from the forecasting guide Grant (Surfing
with Grant) wrote for Swell Scope's backers, and so does the line that flags a second swell. None of Swell Scope's
data is used.

## What it does not know

- The models are coarse. GFS Wave's grid is 16 km, so Uluwatu and Green Bowl read the same cell, and the wind for
  the whole Bukit comes from one point. Open-Meteo says itself that accuracy near the coast is limited.
- The weather model does not see the land breeze that often makes the Bukit glassy at dawn, so some early sessions
  will be missed.
- The tide is a model's sea level, read as low, mid or high against that day's own range. It is not a tide table.
- A good day the pack did not call can only be noted by answering a message from that week.

## Data and licence

Swell from NOAA's GFS Wave and sea level from Copernicus Marine / MeteoFrance, both through Open-Meteo's marine API,
and wind from Open-Meteo's forecast API. The data is CC BY 4.0, free for non-commercial use under 10,000 calls a
day per IP. The
pack makes three requests every three hours, about 36 calls for twelve spots. The code is Apache-2.0.
