# Cameras — Browser Webcam, NVR/DVR, HLS, MJPEG and RTSP

This document describes every way a video source reaches the VISION AI - SRM TRP
console, and why raw RTSP is never loaded directly by a browser.

---

## 1. The short version

| Source | Where it runs | How the browser gets it | Status |
| --- | --- | --- | --- |
| **Operator webcam** | The operator's own laptop/phone | `navigator.mediaDevices.getUserMedia` | ✅ Working today |
| **HLS** | NVR/DVR or a transcoder gateway | `.m3u8` over HTTP(S) via `hls.js` | ✅ Supported |
| **MJPEG** | NVR/DVR or the backend proxy | `multipart/x-mixed-replace` over HTTP(S) | ✅ Supported |
| **Raw RTSP** | The IP camera | *impossible directly* — needs a gateway | ⚠️ Gateway required |

> **Setting up a real NVR/DVR or IP camera?** The step-by-step gateway
> configuration (MediaMTX, FFmpeg for MJPEG, the four camera IDs, verification
> commands and the mixed-content trap) is in
> [`IP_CAMERA_GATEWAY.md`](IP_CAMERA_GATEWAY.md).

> **RTSP is not a browser protocol.** A browser cannot open a TCP/UDP RTSP
> session, cannot negotiate RTSP's SDP/OPTIONS/DESCRIBE flow and cannot embed
> `rtsp://…` in a `<video>` tag. Attempting it produces a media error, not a
> picture. Any RTSP camera must be bridged by a **gateway / transcoder** that
> republishes the video as **HLS** or **MJPEG** over HTTP, and the console
> then consumes that HTTP URL.

---

## 2. Browser camera ("live camera now")

This path needs no server, no NVR and no extra hardware — it uses the
operator's own webcam. It is implemented in `frontend/js/cameras.js`.

```js
const stream = await navigator.mediaDevices.getUserMedia({
  video: { facingMode: 'environment', width: { ideal: 1280 }, height: { ideal: 720 } },
  audio: false,
});
video.srcObject = stream;
```

Behaviour:

- The console shows an **"Operator camera (this device)"** tile at the top of
  the camera grid on the dashboard whenever `navigator.mediaDevices.getUserMedia`
  exists.
- A **"Scan plate"** button grabs the current frame to a canvas, encodes it as
  JPEG and posts it to `POST /api/detection/scan`. The detected number and
  its confidence are shown in the "Last detected" panel and the table refreshes.
- The tile is removed automatically when it leaves the DOM, and all tracks are
  stopped so the camera light goes out.
- Permission failures are reported in plain language ("Camera permission was
  denied", "The camera is already in use by another application").

### Browser requirements

| Requirement | Detail |
| --- | --- |
| Secure context | `https://` or `http://localhost`. A plain-HTTP LAN IP will **not** expose the camera. |
| Permission | The user must grant camera access when prompted. |
| Camera | Any `videoinput` device. `facingMode: 'environment'` prefers the rear camera on phones. |

> On a LAN deployment served over plain HTTP (for example `http://192.168.1.50:5000`),
> the browser camera will be blocked. Terminate TLS in front of the app, or use
> the NVR/DVR path below.

---

## 3. HLS — NVR/DVR and transcoder gateways

HLS is the recommended transport for NVR/DVR cameras because it works through
ordinary HTTP, is cacheable, and survives flaky links.

The console plays HLS with the vendored `hls.js` (already in
`frontend/vendor/hls.min.js`) and falls back to native
`application/vnd.apple.mpegurl` playback on Safari/iOS.

### Configure a camera

Set `CAMERA_STREAM_URLS` to a JSON object:

```bash
export CAMERA_STREAM_URLS='{
  "gate-1-entry": {
    "type": "hls",
    "url": "https://nvr.campus.local/hls/gate1/index.m3u8",
    "label": "Gate 1 Entry"
  },
  "gate-1-exit": {
    "type": "hls",
    "url": "https://nvr.campus.local/hls/gate2/index.m3u8",
    "label": "Gate 1 Exit"
  }
}'
```

Rules enforced by `backend/config.py`:

- `type` must be `hls`, `mjpeg` or `rtsp`.
- The URL scheme must be `http`, `https` or `rtsp`, and must not embed
  credentials (no `user:pass@`).
- `label` must be 1–80 characters.

### Producing HLS from an RTSP camera

**Option A — MediaMTX (recommended).** A single static binary that reads RTSP
and republishes it as HLS.

```bash
docker run --rm -it \
  -p 8888:8888 -p 8889:8889 -p 8554:8554 \
  bluenviron/mediamtx:latest
```

Then publish and consume:

```bash
# publish the camera into MediaMTX
ffmpeg -rtsp_transport tcp -i rtsp://user:pass@192.168.1.64:554/Streaming/Channels/101 \
       -c copy -f rtsp -rtsp_transport tcp rtsp://localhost:8554/gate1

# the HLS playlist is then at
#   http://<mediamtx-host>:8888/gate1/index.m3u8
```

**Option B — FFmpeg only.**

```bash
ffmpeg -rtsp_transport tcp -i rtsp://user:pass@192.168.1.64:554/stream \
       -c:v libx264 -preset veryfast -tune zerolatency -g 50 \
       -c:a aac -f hls -hls_time 2 -hls_list_size 6 -hls_flags delete_segments \
       -hls_segment_filename 'gate1_%03d.ts' gate1.m3u8
```

**Option C — the NVR's own HLS output.** Most NVR/DVR web interfaces expose an
HLS or RTMP link per channel. Use the vendor's HLS URL directly and skip the
gateway entirely.

---

## 4. MJPEG — NVR/DVR direct output and the backend proxy

Many NVRs and DVRs expose an MJPEG snapshot/stream endpoint. If that endpoint
is on a private LAN, or the browser would otherwise be blocked by CORS or
mixed-content rules, the backend proxies it.

```bash
export CAMERA_STREAM_URLS='{
  "gate-2-entry": {
    "type": "mjpeg",
    "url": "http://192.168.1.64:8080/mjpeg/stream.cgi?channel=1",
    "label": "Gate 2 Entry"
  }
}'
```

The console then plays it from `GET /api/stream/gate-2-entry`, which relays
the `multipart/x-mixed-replace` body from the camera. The proxy:

- requires a `head_admin` session (it is an authenticated internal route);
- sets `Cache-Control: no-store` and `X-Accel-Buffering: no`;
- returns `415` for non-MJPEG cameras, with a message pointing at the HLS or
  MJPEG gateway URL.

If the camera is reachable from the browser directly, the console plays the
configured URL directly and the proxy is not involved.

---

## 5. RTSP — what to do about it

If a camera only speaks RTSP, you have exactly three sane options:

1. **Use an NVR/DVR that republishes.** Point the console at the recorder's
   HLS or MJPEG output. The recorder handles RTSP natively.
2. **Run a gateway.** MediaMTX or FFmpeg (see §3) republishes RTSP as HLS or
   MJPEG over HTTP. This is the recommended approach for a campus
   deployment.
3. **Capture and detect server-side.** For unattended detection you do not
   need the browser to watch the video at all — run a small agent on the
   camera host that pulls RTSP with FFmpeg/OpenCV, calls
   `POST /api/detection/scan` and lets the console show the *results*. This
   avoids transcoding video to the browser entirely and is the most
   bandwidth-efficient design.

The console does not accept `rtsp://` URLs as playable streams. When
`CAMERA_STREAM_URLS` contains a camera of type `rtsp`, the tile renders an
explicit **"RTSP gateway required"** notice explaining the above, instead of
silently showing a broken player.

---

## 6. Recommended campus architecture

```
 ┌──────────────┐  RTSP   ┌──────────────────┐  HLS/MJPEG  ┌──────────────────┐
 │  IP camera   │────────▶│ MediaMTX / NVR   │────────────▶│ Flask backend    │
 │ (gate 1)     │         │ (on the LAN)     │             │  + detection     │
 └──────────────┘         └──────────────────┘             └────────┬─────────┘
                                                                    │ HTTPS API
                                                                    ▼
                                                          ┌──────────────────┐
                                                          │ Browser console  │
                                                          │ (Firebase Hosting)│
                                                          └──────────────────┘
```

- The **browser** shows the video (HLS/MJPEG) and the detection results.
- An **edge agent** may push detections directly with `X-Device-Key`, so the
  console does not need to poll.
- The **operator webcam** path works with no infrastructure at all, which
  makes it ideal for testing and for a single-gate deployment.

---

## 7. Verifying a configuration

```bash
# 1. Does the backend see the cameras?
curl -s -b cookies.txt http://localhost:5000/api/config | jq '.cameras, .camera_support'

# 2. Is the detection stack alive?
curl -s -b cookies.txt http://localhost:5000/api/detection/status | jq

# 3. Can the gateway serve HLS? (from the browser's network, not the server)
curl -I http://mediamtx-host:8888/gate1/index.m3u8
```
