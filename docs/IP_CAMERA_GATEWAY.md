# IP cameras — the RTSP gateway, end to end

Webcam works today with no server. This page is the other half: a real NVR/DVR
or IP camera on the campus LAN, shown in the console at `/dashboard`.

It is a deployment guide, not new code. The console already plays **HLS** and
**MJPEG**; what it cannot do — and no browser can — is open a raw `rtsp://` URL.
A small gateway on the LAN does the translation.

---

## 1. Why a gateway is unavoidable

| Layer | Can it read `rtsp://`? | Why |
| --- | --- | --- |
| Browser (`<video>`, hls.js) | **No** | RTSP is not a browser protocol: no `<video src="rtsp://…">`, no SDP/OPTIONS/DESCRIBE handshake, no CORS story. |
| `backend/app.py` `/api/stream/<id>` | **No** | The proxy relays `multipart/x-mixed-replace` only. It answers `415` for anything that is not MJPEG, on purpose. |
| A gateway on the LAN (MediaMTX, FFmpeg, the NVR's own web server) | **Yes** | It speaks RTSP to the camera and republishes HTTP that a browser understands. |

```
camera ──RTSP──► gateway (LAN) ──HLS / MJPEG over HTTP──► browser ──► console
```

## 2. Which output to pick

| Output | Latency | Bandwidth | Use when |
| --- | --- | --- | --- |
| **HLS** (`.m3u8`) | 4–10 s | low | default for a 4-camera grid on a phone; plays through the vendored `hls.js` |
| **MJPEG** (`multipart/x-mixed-replace`) | < 1 s | high (each frame is a JPEG) | one camera at a time, when the operator needs to react to the gate |
| WebRTC | ~0.3 s | low | **not supported by this console** — do not configure it |

Start with HLS. Switch one gate to MJPEG only if a human has to judge a frame in
real time.

## 3. MediaMTX — one container, RTSP in, HLS out

`docker-compose.yml` on the gate PC or a small always-on box:

```yaml
services:
  mediamtx:
    image: bluenviron/mediamtx:1.9.3
    restart: unless-stopped
    network_mode: host          # simplest way to reach cameras on the LAN
    volumes:
      - ./mediamtx.yml:/mediamtx.yml:ro
    environment:
      GATE1_USER: ${GATE1_USER}
      GATE1_PASS: ${GATE1_PASS}
      GATE2_USER: ${GATE2_USER}
      GATE2_PASS: ${GATE2_PASS}
```

`mediamtx.yml`:

```yaml
logLevel: info
api: no
rtsp: yes
rtspAddress: :8554
hls: yes
hlsAddress: :8888
hlsVariant: lowLatency
hlsSegmentDuration: 1s
hlsPartDuration: 200ms
hlsAlwaysRemux: yes
webrtc: no
srt: no

paths:
  gate1:
    source: rtsp://$GATE1_USER:$GATE1_PASS@192.168.1.64:554/Streaming/Channels/101
    sourceOnDemand: yes
    sourceOnDemandCloseAfter: 10s
  gate2:
    source: rtsp://$GATE2_USER:$GATE2_PASS@192.168.1.65:554/Streaming/Channels/101
    sourceOnDemand: yes
```

```bash
docker compose up -d
docker compose logs -f mediamtx      # "path gate1 is ready" is the line you want
```

`sourceOnDemand` matters: with four cameras the box does not decode anything
until somebody actually watches. That keeps a Raspberry-Pi-class gateway viable.

### Camera RTSP URL shapes

| Make | Typical URL |
| --- | --- |
| Hikvision | `rtsp://user:pass@IP:554/Streaming/Channels/101` |
| Dahua / CP Plus | `rtsp://user:pass@IP:554/cam/realmonitor?channel=1&subtype=0` |
| Axis | `rtsp://user:pass@IP/axis-media/media.amp` |
| Generic ONVIF | `rtsp://user:pass@IP:554/stream1` |

Use the **sub-stream** (`Channels/102`, `subtype=1`) when the console only needs
to see a bus arrive. It is a quarter of the bitrate and the difference is
invisible at tile size.

## 4. MJPEG, when you need it

MediaMTX does not speak MJPEG. One `ffmpeg` per camera does:

```bash
ffmpeg -nostdin -rtsp_transport tcp \
  -i "rtsp://user:pass@192.168.1.64:554/Streaming/Channels/102" \
  -vf "fps=8,scale=960:-2" -q:v 6 \
  -f mpjpeg -listen 1 http://0.0.0.0:8090/gate1
```

- `fps=8` is enough for a gate and a third of the CPU of 25.
- `scale=960:-2` matches the detector's letterbox, so what the operator sees is
  what the model sees.
- `-listen 1` serves one client at a time; the backend proxy counts as one.

## 5. Point the portal at it

The console has **four fixed camera IDs** — `gate-1-entry`, `gate-1-exit`,
`gate-2-entry`, `gate-2-exit`. Any other key is ignored by `/api/config`.

`.env` (never committed):

```bash
CAMERA_STREAM_URLS={"gate-1-entry":{"type":"hls","url":"http://192.168.1.10:8888/gate1/index.m3u8","label":"Gate 1 Entry"},"gate-2-entry":{"type":"mjpeg","url":"http://192.168.1.10:8090/gate2","label":"Gate 2 Entry"}}
```

Rules the config enforces at startup (`backend/config.py`):

| Rule | Failure message |
| --- | --- |
| `type` ∈ `hls`, `mjpeg`, `rtsp` | "Camera stream type must be hls, mjpeg or rtsp" |
| scheme ∈ `http`, `https`, `rtsp` and a host is present | "Camera stream URLs must use http, https or rtsp" |
| **no `user:pass@` in the URL** | "Camera stream URLs must not embed credentials" |
| `label` 1–80 characters | "Camera labels must be 1-80 characters" |

That third rule is why credentials live **only** in the gateway. The console
keeps no camera password and cannot leak one; the gateway holds them and stays on
the LAN.

Anything not configured is labelled **Demo footage** rather than breaking the
grid.

## 6. Prove it before the browser sees it

Run these on the gateway host, in order. Each one isolates a layer.

```bash
# 1. the camera answers RTSP at all
ffprobe -v error -rtsp_transport tcp -select_streams v:0 \
  -show_entries stream=codec_name,width,height,avg_frame_rate \
  -of default=nw=1 "rtsp://user:pass@192.168.1.64:554/Streaming/Channels/102"

# 2. the gateway is republishing HLS
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8888/gate1/index.m3u8   # 200

# 3. the playlist has segments in it, not just a header
curl -sS http://127.0.0.1:8888/gate1/index.m3u8 | head -8

# 4. MJPEG, if you set it up
ffmpeg -v error -i http://127.0.0.1:8090/gate1 -frames:v 1 -f null -
```

Then, from the machine running the portal:

```bash
curl -sS http://127.0.0.1:5000/api/config | python -m json.tool | grep -A4 gate-1-entry
```

## 7. Mixed content — the one that bites on HTTPS

An HTTPS console **cannot** load `http://…/index.m3u8`; the browser blocks it
silently and the tile shows "The HLS stream could not be played."

Three honest options:

1. **Serve the gateway over HTTPS** behind the same certificate (Caddy in front
   of MediaMTX: `caddy reverse-proxy --from :8443 --to 127.0.0.1:8888`).
2. **Keep the console on HTTP inside the campus LAN**, and never expose it.
3. **Proxy MJPEG through the app**: `/api/stream/gate-1-entry` — works only for
   `type: mjpeg`, and only while the Flask worker can reach the gateway.

## 8. Where it runs

| Host | Verdict |
| --- | --- |
| Gate PC / office desktop on the camera LAN | ✅ simplest, no cloud egress |
| Raspberry Pi 4 + PoE switch | ✅ fine for 4 sub-streams with `sourceOnDemand` |
| Render free tier | ❌ 512 MB, no route to your LAN, and mixed content on HTTPS |
| Any cloud VM | ⚠️ works only with a VPN/tunnel back to campus; the video of a gate is not something to route through the internet casually |

## 9. Troubleshooting

| Symptom | Likely cause | Check |
| --- | --- | --- |
| Tile says "Bridge this camera through MediaMTX or FFmpeg" | `type` is `rtsp` | use the gateway's HTTP URL instead |
| "The HLS stream could not be played" | mixed content, or gateway down | step 2 and step 7 above |
| `/api/stream/…` returns `415` | the camera is `hls` | proxy is MJPEG-only; point the tile at the HLS URL |
| Playlist loads, video is black | camera keyframe interval too long | set the camera's I-frame interval to 1 s |
| 5–10 s behind live | that is HLS | use MJPEG for the gate a human watches |
| Portal starts, camera shows Demo footage | ID not one of the four | use `gate-1-entry` … `gate-2-exit` |

## 10. Order of work

1. `docker compose up -d`, `docker compose logs -f` → the path is ready.
2. Steps 1–3 of §6 → RTSP and HLS both answer.
3. Add one camera to `CAMERA_STREAM_URLS`, restart the portal, `/api/config`.
4. Open `/dashboard` — one live tile, three Demo footage.
5. Only then add the second camera, and only then consider MJPEG.

One camera at a time. A four-camera cutover with no working baseline cannot be
debugged.
