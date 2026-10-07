# wyze-camera

Wyze cameras on a PLANETAI node, through [docker-wyze-bridge](https://github.com/mrlt8/docker-wyze-bridge). It records
motion events and saves snapshots on the node's own disk, in `out/wyze-camera/`. A wild pack, Apache-2.0.

## What it does, and what it never does

- **Motion.** Every poll (five minutes by default) it asks the bridge when each camera last saw motion, and logs any
  newer time to `out/wyze-camera/motion.jsonl`, with the time Wyze recorded it. Detection is Wyze's own, read from
  Wyze's cloud by the bridge.
- **Snapshots.** On request, on motion (Wyze's own event image when the bridge has it), and on a schedule, saved to
  `out/wyze-camera/snapshots/<camera>/`. Automatic capture is off until you turn it on.
- **It gives the node nothing.** No sensors and no readings, so nothing reaches the database, the daily export (which
  is published as open data), the upstream aggregates or any API. Nothing in the node serves, backs up or exports
  `out/wyze-camera/`. Error messages in the node's status never name a camera.
- **Your Wyze account never touches the node.** Your email, password and Wyze API key go only into the bridge.

Tell the people who live or stay with you that the camera saves stills. In some places that is a legal requirement.

## Setting up the bridge

Run docker-wyze-bridge on your network, with its motion API on. It signs in to Wyze with an email and a password,
so an account you open with Google or Apple will not do: make a second Wyze account with a password, share your
cameras to it in the Wyze app (Account, Device Sharing), and use that one. You also need a Wyze API ID and key, made
at https://developer-api-console.wyze.com while signed in as the same account.

A `docker-compose.yml`, with your credentials in a `.env` beside it that only you can read (`chmod 600 .env`):

```yaml
services:
  wyze-bridge:
    image: mrlt8/wyze-bridge:2.10.3   # the version this pack was checked against
    restart: unless-stopped
    ports: ["5050:5000"]              # a Mac's AirPlay Receiver already holds port 5000
    env_file: .env
    environment:
      - MOTION_API=True
```

```
WYZE_EMAIL=you@example.com
WYZE_PASSWORD='your-wyze-password'
API_ID=your-wyze-api-id
API_KEY=your-wyze-api-key
WB_API=a-long-random-string
WB_PASSWORD=another-long-random-string
```

Put a value in single quotes if it contains `$`: Compose reads `$` as the start of a variable and drops the rest.
Set `WB_API` and `WB_PASSWORD` yourself (`openssl rand -hex 24` makes one). Left out, the bridge derives its API key
from your Wyze email and sets its web page's password to the part of the email before the `@`, so anyone on your
network who knows the email gets in. `WB_API` is the value for `WYZE_BRIDGE_TOKEN`. The bridge's web page at
`http://<bridge>:5050` (user `wbadmin`) shows each camera's name: `WYZE_CAMERAS` takes it as it appears in the
stream's address, lowercase with hyphens, such as `office-cam-01`. A node on the same machine reaches the bridge at
`http://host.docker.internal:5050`.

## Adding it to your node

```
planetai packs add wyze-camera
planetai restart
```

A node that sets `PACKS_ENABLED` must also add `wyze-camera` to it. Then in Set up, Packs, Wyze cameras (or in `.env`):
`WYZE_BRIDGE_URL`, `WYZE_BRIDGE_TOKEN`, `WYZE_CAMERAS`, and optionally `WYZE_ROLES` (`motion`, `snapshots`),
`WYZE_SNAPSHOT_ON_MOTION`, `WYZE_SNAPSHOT_EVERY` (minutes), `WYZE_KEEP_DAYS` (30) and `WYZE_SNAPSHOT_MAX_MB` (500).
The two snapshot settings only act when `WYZE_ROLES` includes `snapshots`, for example `WYZE_ROLES=motion,snapshots`.
It is a code pack, so the node needs `PACKS_ALLOW_CODE=1`.

```
planetai run wyze-camera status
planetai run wyze-camera events --hours 24
planetai run wyze-camera snapshot [camera]
```

## What it does not know

- Motion within one poll is one event. Wyze's free plan already spaces events about five minutes apart.
- A camera that has never reported motion reads "never": the bridge cannot say whether its `MOTION_API` is on.
- It depends on Wyze's cloud and on docker-wyze-bridge, whose last release is v2.10.3 (September 2024).
- **Snapshots need more than motion does.** Motion comes from Wyze's cloud and works wherever the bridge can reach
  the internet. A fresh still comes from the camera's own stream, which the bridge must reach directly on your
  network: in Docker on a Mac (Docker Desktop or Colima) it timed out, because the container sits behind the
  virtual machine's own network. Run the bridge where Docker uses the host's network (Linux, `network_mode: host`).
  Wyze's event image, the other source, was refused by Wyze's cloud to v2.10.3 when this pack was checked
  (3 October 2026). With neither, `snapshot` says the bridge had no image, and the motion log carries on.
- **On node v0.76 the bridge token is not masked.** The pack lists it as a secret, but v0.76 does not know that
  field yet: Set up shows the token to anyone holding the admin token, and a connected AI agent can read it through
  its settings tool. v0.77 (6 October 2026) masks it, with no change to the pack. Until you update, keep
  agents disconnected, or protect the bridge another way.
- **On node v0.76 a connected agent with admin access can run the three scripts.** Through the node's
  `run_pack_script` tool it can run `status`, `events` and `snapshot`, and read what they print: camera names, motion
  history and the bridge address. `snapshot` takes a photo. v0.77 runs a wild pack's scripts
  for an agent only when its pack.yaml lists them under `agent_scripts:`, and this pack lists none. Until you update,
  keep agents disconnected, or give them no admin access.
- The design, and why: `docs/superpowers/specs/2026-10-03-wyze-camera-pack-design.md` in fabcity/planetai-wild-packs.
