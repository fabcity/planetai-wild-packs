# surf

I wanted my node to tell me, the evening before, where the surf could be good over the next two days, so I could check
those spots properly and decide whether to get up early. I don't have much time, so the hard part is choosing. Is it
worth going? Where? When?

At 17:00 the bot sends tomorrow and the day after. Each day has up to three spots, and every number in a spot's lines
is named. The line says when the best window is and which hours are good. Then come the waves (height, period and
direction, plus a second swell when the sea is mixed), the power in kW per metre of crest, the wind and whether it is
offshore or glassy, the tide, and a Windy link that opens the spot's forecast. A day where nothing passes says "nothing
looks good", and when both days are empty it sends nothing.

It was written for Bali, from my house in Ungasan, with fourteen spots in `spots.yml`: Uluwatu, Padang Padang,
Impossibles, Bingin, Balangan, Kuta Reef, Canggu, Medewi, Nusa Dua, Serangan, Sanur, Keramas, Green Bowl and Nyang
Nyang. My node watches ten of them. Bingin, Medewi, Sanur and Keramas stay in the file and are not watched, and Bingin is
the one I only want when I ask for it (`ask`, below). Another coast needs its own spots file.

## My hours

`SURF_HOURS` holds the hours I can usually get away, 08:30-12:00 and 16:00-18:30 by default. The best window is the
`SURF_SESSION_H` hours inside them (two by default) where it is good and the wind is lightest. When a good run only
overlaps my hours in part and no full session fits, it tries one hour less, and so on down to a single hour, so a run
at 11:00 to 13:00 still gives me "best 11:00–12:00". Spots with a window inside my hours come first, then the others,
and each group goes by power. A day shows at most three spots, so a spot that is good only outside my hours, with "good
05:00–08:00, outside your hours", shows only when fewer than three fit inside them. I can try to make time if the surf
is good.

"Big for you right now" is a label. When a line's power is over `SURF_COMFORT_KW` (15 kW/m by default, about 1.5 m at
13 s), the line says so. It never hides a spot. If a big day is good I want to know, and I will decide myself.

## Answering

Under the message, each spot named for tomorrow gets a row with 👍, 👌 and 👎, and a last row says "Didn't go" or
"Surfed somewhere else". On the dashboard they sit under What to do on Now, on a screen that holds the token, and in
Telegram they show up when the bot has turned them on (see below). A rating or "somewhere else" asks for one optional
line afterwards, and whatever I write becomes that answer's note. The values the journal reads are
`<spot-id>:good`, `<spot-id>:ok` and `<spot-id>:poor`, `didnt-go` and `elsewhere`.

A tap closes only that spot's row, so a morning at Uluwatu and an evening at Nyang Nyang can both be rated, and "Didn't
go" closes the keyboard. Two people in the house can each answer. The buttons are for tomorrow only, since the day after
comes back as tomorrow in the next evening's message. If tomorrow has nothing good, the message goes without buttons.

The message always ends with "How was it? Write:" and the rule adds `/act 812 <your words>` after it, so I can answer
in words with the number in the message, for example `/act 812 Ulu good, head high 6 to 8, Impossibles closing out`.
The buttons come under it where the node sends them: in Telegram only when the bot has turned them on
(`TELEGRAM_BUTTONS=1`, which the bot sets when it starts), and on Now with the token. Typing works with the buttons
too.

## The journal

`planetai run surf review` builds a journal for each spot, with what I answered next to that morning's numbers. A
button files under its spot with its rating. A typed note files under every spot it names, by id, name or alias, even
if the message did not suggest it. "Surfed somewhere else" files under "elsewhere" unless the note names a spot, and
"Didn't go" answers the call and files nothing. The hours shown are the window the message gave that spot for
tomorrow, or 06:00 to 10:00 when it gave none.

## Asking about any spot

`planetai run surf ask bingin` prints that spot's two days in the message's own format, whether or not it is watched.
The name can be an id, a name or an alias, so `ulu` and `padang padang` work, and an unknown one lists the spots. It
fetches now with the same three requests, reads the same settings and `ALERT_LOCALE`, stores nothing, and leaves the
three-hour timer alone. The bot can run it when I ask it how Bingin looks tomorrow.

## Settings

- `SURF_SPOTS`: the ids from `spots.yml` to watch, comma-separated. Blank keeps the pack idle, with no network.
- `SURF_MIN_PERIOD`: the shortest swell period that counts, 10 seconds by default.
- `SURF_HOURS`: the hours I can surf, local time, as `start-end` pairs separated by commas. An hour counts when it fits
  whole inside one pair.
- `SURF_SESSION_H`: the length of a session in hours, 2 by default. It sets the window the message names.
- `SURF_COMFORT_KW`: the power in kW/m above which a line says "big for you right now", 15 by default.
- The message is a `warn` alert, so it reaches Telegram only where `ALERT_LEVEL` is `warn` or `info`. On the default
  `act` it is recorded and shown on the page, and not sent.
- It is a code pack, so the node runs it only with `PACKS_ALLOW_CODE=1`. It needs node 0.91.0 or later, which fills
  `{act}` in a rule's message and shows a rule's buttons.

## Where the numbers come from

An hour passes when a swell comes from the spot's window with a long enough period and its power is inside the
spot's range, the wind is offshore (and not over 25 km/h) or under 8 km/h from anywhere, the tide is in a third of
the day's range the spot works on, and the wind sea is under half the swell. Every passing hour between 05:00 and
18:30 is a good hour, in runs of at least two, and a spot with a run is good. The hour from 18:00 stops at 18:30,
since the sun sets in Bali at about 18:00 to 18:40 all year. Times in the message are written HH:00–HH:00, the hour
something starts and the hour it ends, so "good 16:00–18:00" is the hours 16 and 17, and a run that reaches the last
hour reads "good 17:00–18:30". When two swells come from the window at different angles, the line says "mixed".

The numbers in a spot's lines are means over its best window. The direction, the second swell and the tide come from
the window's first hour. When no window fits inside my hours, they are the first good run's. The power that decides
"big for you right now" is the power the line prints.

Every one of those numbers is a first guess, and so is every row of `spots.yml`. I wrote the table from general
knowledge, I haven't surfed all of these breaks, and I checked the rule on a week of Open-Meteo's own archive against
three days other people told me about. The design is in `docs/superpowers/specs/2026-11-02-surf-pack-design.md`, and
what v1.1 changed is in `docs/superpowers/specs/2026-11-03-surf-v1.1-and-pack-buttons-design.md`. The journal is how
the numbers get better, so read it after a few weeks and fix `spots.yml`.

Measuring a swell by its power and keeping a journal for each spot come from the forecasting guide Grant (Surfing
with Grant) wrote for Swell Scope's backers, and so does the line that flags a second swell. None of Swell Scope's
data is used.

## What it does not know

- The models are coarse. GFS Wave's grid is 16 km, so Uluwatu and Green Bowl read the same cell, and the wind for
  the whole Bukit comes from one point. Open-Meteo says itself that accuracy near the coast is limited.
- The weather model does not see the land breeze that often makes the Bukit glassy at dawn, so some early sessions
  will be missed.
- The tide is a model's sea level, read as low, mid or high against that day's own range. It is not a tide table.
- A good day the pack did not call can only be noted by answering a message from that week, or with "Surfed somewhere
  else".

## Data and licence

Swell from NOAA's GFS Wave and sea level from Copernicus Marine / MeteoFrance, both through Open-Meteo's marine API,
and wind from Open-Meteo's forecast API. The data is CC BY 4.0, free for non-commercial use under 10,000 calls a
day per IP. The pack makes three requests every three hours, about 30 calls for my ten spots, and `ask` makes three
more each time it runs. The code is Apache-2.0.
