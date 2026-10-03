"""docker-wyze-bridge's local REST API, as read from its source (v2.10.x: app/frontend.py,
app/wyzebridge/web_ui.py, app/wyzebridge/wyze_stream.py):

  GET /api/<cam>/motion_ts  {"status": "success", "response": {...}, "value": <epoch seconds; 0 = none yet>}
                            an unknown camera answers {"status": "error", "response": "Camera not found"}
                            (seen live on v2.10.3); older code paths answer with an "error" key
  GET /snapshot/<cam>.jpg   a fresh still from the RTSP stream
  GET /thumb/<cam>.jpg      the camera's latest thumbnail from Wyze's cloud: the event's own image
  the API key travels as an `api` header; a wrong one is a 401
  an image the bridge cannot give is a 307 to /static/notavailable.svg, which is not a JPEG

Every BridgeError message is one of the constants below: safe to show beyond the machine, because it names no camera,
no address and no key. httpx puts the URL in its own errors, so they are never passed on."""
from __future__ import annotations

UNREACHABLE = "the bridge did not answer"
REFUSED = "the bridge refused the API key"
UNKNOWN = "a camera is unknown to the bridge"
BAD_ANSWER = "the bridge answered something that is not a motion time"
NO_IMAGE = "the bridge had no image"


class BridgeError(Exception):
    pass


class Bridge:
    def __init__(self, hc, url: str, token: str = "", timeout: float = 10):
        self.hc, self.url, self.timeout = hc, url.rstrip("/"), timeout
        self.headers = {"api": token} if token else {}

    def _get(self, path: str):
        try:
            return self.hc.get(self.url + path, headers=self.headers, timeout=self.timeout, follow_redirects=False)
        except Exception:  # noqa: BLE001
            raise BridgeError(UNREACHABLE) from None

    def motion_ts(self, cam: str) -> float:
        r = self._get(f"/api/{cam}/motion_ts")
        if r.status_code in (401, 403):
            raise BridgeError(REFUSED)
        if r.status_code != 200:
            raise BridgeError(UNREACHABLE)
        try:
            body = r.json()
        except ValueError:
            raise BridgeError(BAD_ANSWER) from None
        if not isinstance(body, dict):
            raise BridgeError(BAD_ANSWER)
        if "error" in body or body.get("status") == "error":
            raise BridgeError(UNKNOWN)
        value = body.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise BridgeError(BAD_ANSWER)
        return float(value)

    def image(self, cam: str, kind: str = "snapshot") -> bytes:
        r = self._get(f"/{kind}/{cam}.jpg")
        if r.status_code in (401, 403):
            raise BridgeError(REFUSED)
        ctype = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
        if r.status_code != 200 or ctype != "image/jpeg" or not r.content:
            raise BridgeError(NO_IMAGE)
        return r.content
