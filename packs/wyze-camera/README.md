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

Run docker-wyze-bridge on your network, with its motion API on. You need a Wyze API ID and key from
https://developer-api-console.wyze.com. A minimal `docker-compose.yml`:

```yaml
services:
  wyze-bridge:
    image: mrlt8/wyze-bridge:latest
    restart: unless-stopped
    ports: ["5000:5000"]
    environment:
      - WYZE_EMAIL=you@example.com
      - WYZE_PASSWORD=your-wyze-password
      - API_ID=your-wyze-api-id
      - API_KEY=your-wyze-api-key
      - MOTION_API=True
```

Its log prints `WB_API=…`: that is the key for `WYZE_BRIDGE_TOKEN`. Its web page at `http://<bridge>:5000` shows each
camera's name (for `WYZE_CAMERAS`) and a live view.

## Adding it to your node

```
planetai packs add wyze-camera
```

Then in Set up, Packs, Wyze cameras (or in `.env`): `WYZE_BRIDGE_URL`, `WYZE_BRIDGE_TOKEN`, `WYZE_CAMERAS`, and
optionally `WYZE_ROLES` (`motion`, `snapshots`), `WYZE_SNAPSHOT_ON_MOTION`, `WYZE_SNAPSHOT_EVERY` (minutes),
`WYZE_KEEP_DAYS` (30) and `WYZE_SNAPSHOT_MAX_MB` (500). It is a code pack, so the node needs `PACKS_ALLOW_CODE=1`.

```
planetai run wyze-camera status
planetai run wyze-camera events --hours 24
planetai run wyze-camera snapshot [camera]
```

## What it does not know

- Motion within one poll is one event. Wyze's free plan already spaces events about five minutes apart.
- A camera that has never reported motion reads "never": the bridge cannot say whether its `MOTION_API` is on.
- It depends on Wyze's cloud and on docker-wyze-bridge, whose last release is v2.10.3 (September 2024).
- **On node v0.76 the bridge token is not masked.** The pack lists it as a secret, but v0.76 does not know that
  field yet: Set up shows the token to anyone holding the admin token, and a connected AI agent can read it through
  its settings tool. The first release after v0.76 masks it, with no change to the pack. Until you update, keep
  agents disconnected, or protect the bridge another way.
- The design, and why: `docs/superpowers/specs/2026-10-03-wyze-camera-pack-design.md` in fabcity/planetai-wild-packs.
