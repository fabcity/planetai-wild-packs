# Design: the `wyze-camera` wild pack

Agreed with Tomas on 3 October 2026, section by section. This is the design; the implementation plan follows it.

## What it is for

A wild pack that connects Wyze cameras to a PLANETAI node through docker-wyze-bridge. It records motion events and
saves snapshots on request, on motion and on a schedule. What the node does with motion is decided later; for now it
only records. The first camera is a Wyze Cam v3 or v4, indoors.

It is Wyze-only and standalone. Frigate and standard CCTV (RTSP and ONVIF cameras and recorders) are to become core
features of the node, designed separately; this pack does not depend on them and they do not depend on it. Tomas
chose standalone over a provider hook into a core camera feature, accepting that the two will each carry their own
copy of the storage and privacy rules below.

## Decisions taken, and why

- **Motion is recorded in a local event log, never as readings.** The node's daily export publishes hourly means for
  every sensor and metric it stores, as open data under CC BY and on IPFS, and the upstream aggregates push every
  hourly row from the last two hours. Motion at a home is occupancy data: stored as a reading, the household's
  activity pattern would be published hour by hour, permanently. A core "private" role that every outward path leaves
  out was the alternative; it was set aside until a use for motion is decided.
- **Detection is Wyze's own, read through the bridge.** docker-wyze-bridge reads the motion events Wyze's cloud
  records (polling Wyze's web API every 1.5 s when `MOTION_API=True`) and exposes each camera's last motion time on a
  local REST endpoint, `/api/{cam-name}/motion_ts`
  ([wiki](https://github.com/mrlt8/docker-wyze-bridge/wiki/Camera-Motion)). The node polls that. Comparing snapshots
  on the node was rejected because a pack runs once per poll, every five minutes by default, which samples a room
  rather than detecting motion. Having the bridge push events was rejected because a pack has no endpoint to receive a
  webhook or an MQTT message; that is a core change.
- **A wild pack, `wyze-camera`, hosted in fabcity/planetai-wild-packs**, installed with `planetai packs add
  wyze-camera`. Licence Apache-2.0, like the node today.
- **The bridge token is a secret, and the pack works from v0.76.** The token is listed under `secrets:` in `pack.yaml`,
  so a node with fabcity/planetai-node#167 masks it in Set up like its own tokens. Tomas chose to support v0.76
  onwards rather than wait for that release (3 October): a v0.76 node ignores `secrets:`, so there the token is shown
  to anyone holding the admin token and to a connected agent's settings tool, and the README says so. The same pack
  masks it as soon as the node updates.

## 1. The pack

- `packs/wyze-camera/` in this repository: `pack.yaml`, `adapter.py`, the roles, three scripts (`status`, `events`,
  `snapshot`), tests and a README. It is a code pack: it runs only with `PACKS_ALLOW_CODE=1`.
- **A role layer, kept on purpose (Tomas, 3 October).** The pack is Wyze-only, so it has no vendor layer, but what
  it does with the cameras is split into roles, each with one job on the same camera list and the same bridge
  client. The first two are `motion`, which keeps the event log (section 2), and `snapshots`, which saves stills on
  motion and on a schedule (section 5). `WYZE_ROLES` says which run at each poll. A later use (a visibility reading,
  proof that an alert was acted on) is a new role, not a change to these. The core Frigate and CCTV feature is to
  carry the same role layer, so a role means the same thing whichever camera serves it.
- **Settings**, declared as `env:` in `pack.yaml` so `planetai packs install` adds them to `.env`, and shown in the
  pack's card under Set up → Packs:

  | setting | default | what it is |
  |---|---|---|
  | `WYZE_BRIDGE_URL` | blank | the bridge's local address, for example `http://192.168.1.20:5000` |
  | `WYZE_BRIDGE_TOKEN` | blank | only if the bridge's API is protected; listed under `secrets:` |
  | `WYZE_CAMERAS` | blank | the cameras to follow, comma-separated, as the bridge names them |
  | `WYZE_ROLES` | `motion` | which roles run at each poll: `motion`, `snapshots` |
  | `WYZE_KEEP_DAYS` | `30` | how long events and snapshots are kept |
  | `WYZE_SNAPSHOT_ON_MOTION` | `0` | `1` saves an image with each new motion event (section 5) |
  | `WYZE_SNAPSHOT_EVERY` | `0` | minutes between scheduled snapshots; `0` is off |
  | `WYZE_SNAPSHOT_MAX_MB` | `500` | the most the snapshot folder may hold; the oldest go first |

- **The Wyze account never touches the node.** The email, password and Wyze API key go only into the bridge's own
  settings. The node knows the bridge's local address, the camera names and, optionally, the bridge token.
- `requires: { node: ">=0.76" }`, the first release with `planetai packs add`.

## 2. How events flow, and where they live

- This is the `motion` role, on by default. Every node poll, it asks the bridge for each named camera's last motion
  time.
- It remembers the last motion time seen per camera in `out/wyze-camera/state.json`, so a restart never logs an event
  twice. On the first run for a camera it records the bridge's current last motion time as a starting point and logs
  nothing, so installing the pack does not log old motion as new, and the node's clock is never compared with Wyze's.
- A newer motion time is appended to `out/wyze-camera/motion.jsonl`, one JSON object per line: the camera name, the
  time Wyze recorded the motion, and the time the node saw it, both UTC. The log carries the recorded time, not the
  poll time, so events are accurate to the second although the node checks every five minutes. Motion repeated within
  one poll is one event; Wyze's free plan already spaces events about five minutes apart.
- On each write, events older than `WYZE_KEEP_DAYS` are pruned.
- **The pack gives the node nothing.** Its adapter always returns no sensors and no readings, so motion never enters
  the database and never reaches the daily export, the upstream aggregates, the shared API, the ask pane or the agent
  tools. The node's only routes into `out/` serve named PNG files at its top level and in `out/earth`, and
  `backup.sh` does not include `out/`, so the log stays on the node's disk and nowhere else.

## 3. Seeing it work, and when it does not

- `planetai run wyze-camera status`: whether the bridge answers, and per camera its last motion time, its event count
  over the last day and week, and its snapshot count and disk use.
- `planetai run wyze-camera events --hours 24`: the events themselves.
- Both read the local files. They are the only way anyone sees the events: from the node's own terminal, or through the node's `run_pack_script` tool by a connected agent with admin access, which can read their output (camera names, motion history, the bridge address).
- **Missing settings:** with no bridge address or no camera names, the pack idles and says so once in the log.
- **Bridge down:** the pack raises, so it appears as a failing source in `planetai status` and `planetai doctor`. If
  one camera fails the others are still checked; it raises only when every camera fails.
- **Motion API off:** the bridge cannot be asked whether `MOTION_API` is on; with it off, `motion_ts` answers 0
  forever. So this is not an error the pack can raise. The status script says "never" for a camera that has reported
  no motion and suggests checking `MOTION_API=True` in the bridge. (Corrected from the bridge's source, 3 October.)
- **Errors name no camera and no address.** Source errors appear in the node's status, which can be visible beyond
  the machine, and room names never leave it. An error reads like "wyze-camera: 1 of 2 cameras unknown to the
  bridge"; the status script names them locally. The token never appears in any message.

## 4. Testing and shipping

- Offline tests in `packs/wyze-camera/tests/`, run from a node's folder as this repository's check expects, with a
  fake bridge. They cover: the first run setting a starting point without logging; a new motion time logged exactly
  once, including after a restart (run twice over its own state); pruning; one camera failing while the others
  continue, and all failing raising; errors carrying no camera name, address or token; the adapter always returning no
  sensors and no readings; idling when unset; a role not listed in `WYZE_ROLES` not running. For snapshots: a manual snapshot saved per camera; nothing saved
  automatically while the `snapshots` role is off or both automatic settings are off; one image per new motion event when switched on, and none
  twice after a restart; the schedule honoured across runs; pruning by age and by the size cap, oldest first; every
  file in `out/wyze-camera/snapshots/`, as `.jpg`, where no node route serves it.
- A live check against a real bridge on Tomas's network. Tomas runs docker-wyze-bridge and enters the Wyze credentials
  there himself; a minimal compose snippet with `MOTION_API=True` goes in the README. The first things checked live are
  the real response of `/api/{cam}/motion_ts`, the snapshot endpoint and how the bridge expects its API key, before
  the parser is trusted.
- Shipping: a pull request to this repository adding `packs/wyze-camera/`, its `packs.json` entry (hosted here,
  `listed`, `code`, Apache-2.0), and a `CODEOWNERS` line naming Tomas. The repository's CI runs its checks against
  node main.

## 5. Snapshots

Snapshots are the `snapshots` role. All three triggers work as a wild pack, since none needs anything on the page.
The role runs the two automatic triggers at each poll when it is listed in `WYZE_ROLES`; the manual one is a script
anyone at the node's terminal, or a connected agent with admin access through `run_pack_script`, can run whether or not the role is on.

- **One store:** `out/wyze-camera/snapshots/<camera>/<UTC time>-<trigger>.jpg`, the trigger being `manual`, `motion`
  or `schedule`. Like the motion log, nothing in the node serves, backs up or exports this folder. The images are
  opened in Finder, or from the node's terminal.
- **On request:** `planetai run wyze-camera snapshot [camera]` saves one still from each camera, or from the one named,
  using the bridge's current still.
- **On motion:** with the `motion` and `snapshots` roles on and `WYZE_SNAPSHOT_ON_MOTION=1`, each new motion event the
  pack logs also saves an image. The node
  polls every five minutes, so a still taken at poll time can show an empty room minutes after the movement. If the
  bridge supplies the event's own image from Wyze, the pack saves that; if it does not, it saves the current still and
  labels it as taken at poll time.
- **On a schedule:** `WYZE_SNAPSHOT_EVERY` minutes between stills per camera, `0` (off) by default. The node's poll
  interval is the finest it can go.
- **Limits.** The node's database lives on the same disk, and a full disk can stop it. Snapshots older than
  `WYZE_KEEP_DAYS` are deleted, and `WYZE_SNAPSHOT_MAX_MB` (500 by default) caps the folder, deleting the oldest
  first.
- **Automatic capture is off until switched on**, so installing the pack never starts photographing a home by itself.
  The README suggests telling the people who live or stay there that the camera saves stills; in some places that is
  a legal requirement.

## Not in this version

- **Frigate and CCTV.** They are to be core features of the node, designed separately: Frigate for local motion
  detection and snapshots on any RTSP camera with no vendor cloud, and ONVIF for cameras and recorders directly. They
  carry the same role layer as this pack. This pack neither waits for them nor plugs into them.
- **Live streaming on the dashboard: considered and not planned.** It is technically possible (the bridge serves a
  stream a browser can play, and the page sets no rule against loading a player from the network), but not from a wild
  pack, since only core packs add page code. For an indoor camera it does not fit: it serves home monitoring rather
  than air, water and soil, which the Wyze app already does; it widens who can see inside the home, through the
  dashboard's sharing setting and a wall screen in a shared room; and it breaks the wall's rules that the numbers stay
  the loudest thing and that reduced motion leaves one still frame. What would fit, later and as a core feature, is a
  still of an outdoor view beside the air readings, off by default and never shown beyond the home network or without
  the token. Until then, the bridge's own web page shows a live view.
- A dashboard button to save a snapshot: it needs a core change, since a wild pack cannot add controls to the page.
- Other uses of the camera discussed (a visibility or haze reading, proof that an alert was acted on), and anything the
  node does with motion: rules, alerts, dashboard. That waits for a decision, and for a way to keep the data private on
  every outward path if it ever becomes readings.
- A dedicated image and video tab in Set up: worth it once two or three camera packs or features exist; until then
  the pack's card under Packs holds its settings.
- The second pack discussed the same day, posting certain alerts to X, is a separate design.

## Read from the bridge's source (v2.10.x), 3 October

- `GET /api/<cam>/motion_ts` answers `{"status": "success", "response": {"motion": …, "motion_ts": …}, "value": <epoch
  seconds, float>}`; `value` is 0 until the first motion. An unknown camera answers a JSON object with an `error`
  key. (`app/wyzebridge/wyze_stream.py`, `send_cmd`.)
- The API key travels as an `api` header or `?api=` (`app/wyzebridge/web_ui.py`, `verify_password`); a wrong key is
  a 401. The pack sends the header, so the key never sits in a URL.
- `GET /snapshot/<cam>.jpg` is a fresh still from the RTSP stream; `GET /thumb/<cam>.jpg` is the camera's latest
  thumbnail from Wyze's cloud, which is what the pack saves as an event's own image. An image the bridge cannot give
  is a 307 to `/static/notavailable.svg` (`app/frontend.py`).
- The last release is v2.10.3 (September 2024); the repository had commits in September 2026 and is not archived.

## To verify during implementation

- The exact response body of `/api/{cam}/motion_ts` and `/api/{cam}/motion`, and the timestamp's unit and zone.
- How the bridge's REST API expects its key when it is protected.
- That `/thumb/<cam>.jpg` really is the latest motion event's image on a live camera, not just a periodic thumbnail.
- That docker-wyze-bridge is still maintained and still supports the v3 and v4 with `MOTION_API`. If it is not, the
  pack has nothing to read, and that is reported before any code is written.
- Which node release carries `secrets:` (fabcity/planetai-node#167), for the README's "update to mask the token" line.
