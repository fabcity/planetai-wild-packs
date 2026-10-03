# Design: the `camera` wild pack (first vendor Wyze, first role motion)

Agreed with Tomas on 3 October 2026, section by section. This is the design; the implementation plan follows it.

## What it is for

A general camera pack for a PLANETAI node. Vendor support is one layer and roles are another, so a camera from
another vendor is a small connector and a new use is a new role on the same camera list. The first version supports
one vendor, Wyze through docker-wyze-bridge, and one role, recording motion events, plus saving snapshots on request,
on motion and on a schedule. What the node does with motion is decided later; for now it only records.

The first camera is a Wyze Cam v3 or v4, indoors.

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
- **The pack is a wild pack, `camera`, hosted in fabcity/planetai-wild-packs**, installed with `planetai packs add
  camera`. Licence Apache-2.0, like the node today.

## 1. The pack

- `packs/camera/` in this repository: `pack.yaml`, `adapter.py`, the vendor and role code, three scripts (`status`,
  `events`, `snapshot`), tests and a README. It is a code pack: it runs only with `PACKS_ALLOW_CODE=1`.
- **Vendor layer.** One question per vendor: "when did this camera last see motion?" The first vendor, `wyze-bridge`,
  answers it from the bridge's REST endpoint. A later vendor (a camera with its own HTTP or ONVIF events) is one more
  small module answering the same question.
- **Role layer.** What to do with the answer. The first role, `motion`, appends new motion times to the event log.
  A later role reuses the same camera list and vendor.
- **Settings**, declared as `env:` in `pack.yaml` so `planetai packs install` adds them to `.env`:

  | setting | default | what it is |
  |---|---|---|
  | `CAMERA_VENDOR` | `wyze-bridge` | which vendor module answers |
  | `CAMERA_BRIDGE_URL` | blank | the bridge's local address, for example `http://192.168.1.20:5000` |
  | `CAMERA_BRIDGE_TOKEN` | blank | only if the bridge's API is protected |
  | `CAMERA_NAMES` | blank | the cameras to follow, comma-separated, as the bridge names them |
  | `CAMERA_ROLES` | `motion` | which roles run |
  | `CAMERA_KEEP_DAYS` | `30` | how long the event log keeps events, and snapshots their images |
  | `CAMERA_SNAPSHOT_ON_MOTION` | `0` | `1` saves an image with each new motion event (section 5) |
  | `CAMERA_SNAPSHOT_EVERY` | `0` | minutes between scheduled snapshots; `0` is off |
  | `CAMERA_SNAPSHOT_MAX_MB` | `500` | the most the snapshot folder may hold; the oldest go first |

- **The Wyze account never touches the node.** The email, password and Wyze API key go only into the bridge's own
  settings. The node knows the bridge's local address, the camera names and, optionally, the bridge token.
- `requires: { node: ">=0.76" }`, the first release with `planetai packs add`.

## 2. How events flow, and where they live

- Every node poll, the pack asks the bridge for each named camera's last motion time.
- It remembers the last motion time seen per camera in `out/camera/state.json`, so a restart never logs an event
  twice. On the first run for a camera it records the bridge's current last motion time as a starting point and logs
  nothing, so installing the pack does not log old motion as new, and the node's clock is never compared with Wyze's.
- A newer motion time is appended to `out/camera/motion.jsonl`, one JSON object per line: the camera name, the time
  Wyze recorded the motion, and the time the node saw it, both UTC. The log carries the recorded time, not the poll
  time, so events are accurate to the second although the node checks every five minutes. Motion repeated within one
  poll is one event; Wyze's free plan already spaces events about five minutes apart.
- On each write, events older than `CAMERA_KEEP_DAYS` are pruned.
- **The pack gives the node nothing.** Its adapter always returns no sensors and no readings, so motion never enters
  the database and never reaches the daily export, the upstream aggregates, the shared API, the ask pane or the agent
  tools. The node serves only named image patterns from `out/`, never arbitrary files, and `backup.sh` does not include
  `out/`, so the log stays on the node's disk and nowhere else.

## 3. Seeing it work, and when it does not

- `planetai run camera status`: whether the bridge answers, and per camera its last motion time, its event count
  over the last day and week, and its snapshot count and disk use.
- `planetai run camera events --hours 24`: the events themselves.
- Both read the local log. They are the only way anyone sees the events, and only from the node's own terminal.
- **Missing settings:** with no bridge address or no camera names, the pack idles and says so once in the log.
- **Bridge down:** the pack raises, so it appears as a failing source in `planetai status` and `planetai doctor`. If
  one camera fails the others are still checked; it raises only when every camera fails.
- **Motion API off:** if the bridge answers but its motion API is disabled, the error says to set `MOTION_API=True`
  in the bridge.
- **Errors name no camera and no address.** Source errors appear in the node's status, which can be visible beyond
  the machine, and room names never leave it. An error reads like "camera: 1 of 2 cameras unknown to the bridge"; the
  status script names them locally. The token never appears in any message.

## 4. Testing and shipping

- Offline tests in `packs/camera/tests/`, run from a node's folder as this repository's check expects, with a fake
  bridge. They cover: the first run setting a starting point without logging; a new motion time logged exactly once,
  including after a restart (run twice over its own state); pruning; one camera failing while the others continue,
  and all failing raising; errors carrying no camera name, address or token; the adapter always returning no sensors
  and no readings; idling when unset. For snapshots: a manual snapshot saved per camera; nothing saved automatically
  while both automatic settings are off; one image per new motion event when switched on, and none twice after a
  restart; the schedule honoured across runs; pruning by age and by the size cap, oldest first; every file in
  `out/camera/snapshots/`, as `.jpg`, where no node route serves it.
- A live check against a real bridge on Tomas's network. Tomas runs docker-wyze-bridge and enters the Wyze credentials
  there himself; a minimal compose snippet with `MOTION_API=True` goes in the README. The first thing checked live is
  the real response of `/api/{cam}/motion_ts`, the snapshot endpoint and how the bridge expects its API key, before
  the parser is trusted.
- Shipping: a pull request to this repository adding `packs/camera/`, its `packs.json` entry (hosted here, `listed`,
  `code`, Apache-2.0), and a `CODEOWNERS` line naming Tomas. The repository's CI runs its checks against node main.

## 5. Snapshots

Agreed later the same day. All three triggers work as a wild pack, since none needs anything on the page.

- **One store:** `out/camera/snapshots/<camera>/<UTC time>-<trigger>.jpg`, the trigger being `manual`, `motion` or
  `schedule`. Like the motion log, nothing in the node serves, backs up or exports this folder: the node's only routes
  into `out/` match named PNG patterns at its top level and in `out/earth`. The images are opened in Finder, or from
  the node's terminal.
- **On request:** `planetai run camera snapshot [camera]` saves one still from each camera, or from the one named,
  using the bridge's current still.
- **On motion:** with `CAMERA_SNAPSHOT_ON_MOTION=1`, each new motion event the pack logs also saves an image. The node
  polls every five minutes, so a still taken at poll time can show an empty room minutes after the movement. If the
  bridge supplies the event's own image from Wyze, the pack saves that; if it does not, it saves the current still and
  labels it as taken at poll time.
- **On a schedule:** `CAMERA_SNAPSHOT_EVERY` minutes between stills per camera, `0` (off) by default. The node's poll
  interval is the finest it can go.
- **Limits.** The node's database lives on the same disk, and a full disk can stop it. Snapshots older than
  `CAMERA_KEEP_DAYS` are deleted, and `CAMERA_SNAPSHOT_MAX_MB` (500 by default) caps the folder, deleting the oldest
  first.
- **Automatic capture is off until switched on**, so installing the pack never starts photographing a home by itself.
  The README suggests telling the people who live or stay there that the camera saves stills; in some places that is
  a legal requirement.

## Not in this version

- Other vendors, and the other roles discussed (a visibility or haze reading, proof that an alert was acted on, a
  picture on the dashboard; the last needs a core change, since a wild pack cannot draw an image on the page).
- **Live streaming on the dashboard: considered and not planned.** It is technically possible (the bridge serves a
  stream a browser can play, and the page sets no rule against loading a player from the network), but not from a wild
  pack, since only core packs add page code. For an indoor camera it does not fit: it serves home monitoring rather
  than air, water and soil, which the Wyze app already does; it widens who can see inside the home, through the
  dashboard's sharing setting and a wall screen in a shared room; and it breaks the wall's rules that the numbers stay
  the loudest thing and that reduced motion leaves one still frame. What would fit, later and as a core feature, is a
  still of an outdoor view beside the air readings, off by default and never shown beyond the home network or without
  the token. Until then, the bridge's own web page shows a live view.
- A dashboard button to save a snapshot: it needs a core change, since a wild pack cannot add controls to the page.
- Anything the node does with motion: rules, alerts, dashboard. That waits for a decision, and for a way to keep the
  data private on every outward path if it ever becomes readings.
- The second pack discussed the same day, posting certain alerts to X, is a separate design.

## To verify during implementation

- The exact response body of `/api/{cam}/motion_ts` and `/api/{cam}/motion`, and the timestamp's unit and zone.
- How the bridge's REST API expects its key when it is protected.
- The bridge's snapshot endpoint, and whether its motion events carry Wyze's own event image the pack can save.
- That docker-wyze-bridge is still maintained and still supports the v3 and v4 with `MOTION_API`. If it is not, the
  vendor layer is where a replacement goes, and this design stands.
