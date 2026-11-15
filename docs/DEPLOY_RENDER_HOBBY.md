# Render free / hobby: can it host the whole backend?

Short answer: **yes for the portal, no for the detector.** Render's free and
hobby plans give you 512 MB of RAM, and the vision stack (CPU torch +
Ultralytics + ONNX OCR) needs roughly 1.5–2.5 GB before the first frame is
decoded. The portal — Flask API, every page, SSE live updates, exports, the
Supabase queries — fits comfortably. The camera work belongs on the gate PC.

This page is the decision record for moving from the college LAN box
("InstaBox", `172.16.0.2:8080`) to Render, and the list of things that had to be
fixed before a free container could serve a real shift.

- Setup from zero: [`DEPLOY_RENDER_FREE.md`](DEPLOY_RENDER_FREE.md) — Supabase,
  Render, Firebase, in order.
- The gate PC: [`DEPLOY_GATE_PC.md`](DEPLOY_GATE_PC.md).

---

## 1. The honest architecture

```
   gate PC (Windows)                     Render (1 container, 512 MB)
   ┌──────────────────────────┐          ┌──────────────────────────────┐
   │ VisionAI.exe             │  HTTPS   │ Flask: frontend/ + /api/*    │
   │  camera → detect → OCR   │ ───────▶ │  login, events, exports, SSE │
   │  POST /api/detection/scan│  device  │  no torch, no camera access  │
   │  (X-Device-Key)          │   key    └──────────────┬───────────────┘
   └──────────────────────────┘                         │ sslmode=verify-full
                                                        ▼
                                              Supabase PostgreSQL
                                              schema transport_portal
```

Two consequences worth stating plainly:

- `CAMERA_SOURCE` / `CAMERA_STREAM_URLS` are **not used on Render**. Nothing in
  the free container can open an RTSP stream, a USB webcam or a phone camera.
  Those variables belong in `C:\ProgramData\VisionAI\gate.env` on the gate PC.
- `/api/detection/scan` on Render answers **503 `vision_local_agent_required`**
  by design, and the message now names the real executable (`VisionAI.exe`) and
  says where to run it (`backend/app.py:796`). Before this branch it told
  operators to run `VisionAI-GateAgent.exe`, a binary no build in this repository
  produces — the worst kind of error message, because it looks actionable.

The gate PC keeps working when the internet is down: it writes events locally and
the portal catches up later. The portal without the gate PC shows an empty
dashboard, not a broken one.

---

## 2. What a free instance can and cannot do

| Resource | Render Free | Render Hobby ("Starter", $7/mo) | What it means here |
| --- | --- | --- | --- |
| RAM | 512 MB | 512 MB | portal only; **no** torch in either |
| CPU | 0.1 | 0.5 | a `/api/events` page over 10k rows takes ~1 s; acceptable |
| Sleep | after ~15 min idle | never | first request after a pause is 30–60 s |
| Instances | 1 | 1 (scale manually) | rate limits and the SSE cache live in memory |
| Disk | ephemeral | ephemeral (persistent disk is a paid add-on) | all state is in Supabase; see §3.3 |
| Bandwidth | 100 GB/mo | 100 GB/mo | an export of 10k rows is ~2 MB |
| Custom domain | yes | yes | TLS is automatic |
| Build minutes | 500/mo shared | 500/mo shared | a Docker build here is ~2–4 min |

Paying $7 does **not** buy you the detector. Nothing on Render runs the detector
unless you go to a plan with ≥2 GB and add the vision extras to the image, and
even then you would need a network path from Render to a camera inside the
college LAN — which is a VPN, not a plan upgrade. Keep detection on the gate PC.

---

## 3. What this branch changed so the portal survives there

Each item below was a real failure mode on a free instance, not a precaution.

### 3.1 `/api/stream` no longer holds a thread forever

`while True` with a 10 s `sleep` meant every open dashboard held one gunicorn
thread for as long as the tab existed, and a closed tab is invisible to a server
that is only writing once every ten seconds. With **four** threads, four idle
admin tabs starved the service: static pages still loaded (they need no worker
long enough to notice) but every API call queued.

Now (`backend/app.py:88-107`, route at `:994`):

| Setting | Default | Meaning |
| --- | --- | --- |
| `API_SSE_SECONDS` | `210` | the response ends by itself after 3.5 min |
| `API_SSE_REFRESH_SECONDS` | `10` | one `tick` payload every 10 s |
| `API_SSE_HEARTBEAT_SECONDS` | `5` | `: keep-alive` comment between ticks |
| `API_STATS_CACHE_SECONDS` | `5` | `compute_stats()` is shared by every open tab |

The stream ends with `event: end`; `EventSource` reconnects on its own
immediately, so the dashboard never shows a gap. On the browser side
`frontend/js/sse.js` used to treat that close as "the server is down" and drop to
10-second polling — three API calls per tab per 10 s, forever. It now reconnects
(with linear backoff) and only falls back to polling after five consecutive
failures. Pinned by `scripts/check_live_stream.mjs` and
`backend/tests/test_live_stream_and_free_host.py`.

### 3.2 Eight threads, and a worker that is recycled

`deploy/render/entrypoint.sh` now runs
`--threads ${GUNICORN_THREADS:-8}` (was 4), `--graceful-timeout 30` and
`--max-requests 800 --max-requests-jitter 80`. The last two matter because a
free instance is never restarted by anyone: recycling the worker caps slow
memory growth instead of waiting for the OOM killer. One worker stays — 512 MB
cannot hold two. `render.yaml:51,56` sets `GUNICORN_THREADS=8` and
`API_SSE_SECONDS=210` explicitly so the values are visible in the dashboard.

### 3.3 The error log now also goes to the platform log stream

`backend/diagnostics.py` writes to `<data>/logs/errors.log` and `--report` reads
it back. On Render the disk is thrown away on every deploy, so that file is
useless there. Every block is now mirrored to the Python logger
(`backend/diagnostics.py:160`), which Render keeps and shows under **Logs**.
Warnings at `WARNING`, scan diagnostics at `INFO`.

### 3.4 One detector executable

`desktop/build_windows.ps1` built a second, older agent
(`VisionAI-GateAgent.exe` from `desktop/detector_agent.py`, different
`%APPDATA%` folder, no setup wizard, no `--check`, no `--report`). It is now a
one-line forwarder to `desktop/gate/build_gate.ps1`, which builds the supported
`VisionAI.exe`. Nothing in the repository or the docs says "GateAgent" any more.

---

## 4. InstaBox: keep it, or switch it off?

InstaBox is the college LAN host (`172.16.0.2:8080`) running
`deploy/instabox/docker-compose.yml` — the **full** image with
`INSTALL_VISION=1`, so it does camera capture *and* detection *and* the portal.
It is a different product from Render + gate PC, not a duplicate of it.

| If you … | InstaBox | Render + `VisionAI.exe` | Verdict |
| --- | --- | --- | --- |
| want the portal reachable from outside the campus | needs a public IP, DNS and TLS you maintain | free, automatic TLS, custom domain | **Render** |
| need server-side detection of a camera on the college LAN | works (it is on the LAN) | cannot reach the camera | **InstaBox** |
| already run `VisionAI.exe` on a Windows PC at the gate | not needed | it *is* the detector | **Render only** |
| want one machine to look after | one LAN server, no cloud | cloud portal + one Windows PC | tie |
| worry about a 512 MB limit | the LAN box has real RAM | portal only | **InstaBox** for pure vision |

Decision rule:

1. **Retire InstaBox** if the gate camera is plugged into (or reachable from) the
   gate PC and `VisionAI.exe` is working. You lose nothing: the portal is the
   same code, the database is the same Supabase project, and you stop
   maintaining a campus server, its Docker daemon, its CA mount
   (`./supabase-ca.crt`) and its `TRUST_PROXY_HEADERS=false` exception.
2. **Keep InstaBox** if detection must run against RTSP URLs on the college
   network that the gate PC cannot reach, or if you want the portal to keep
   working when the college uplink is down.
3. **Never run both as the portal.** Two portals against one database will both
   accept logins and both write audit rows; the SSE cache and the in-memory rate
   limits are per-process, so behaviour differs between them. If you keep
   InstaBox for detection, point its `VisionAI`/detector at the Render portal
   (`API_BASE_URL=https://srm-trp-transport.onrender.com`) and stop serving its
   frontend, or leave it on its own Supabase project.

Migration checklist when switching InstaBox off:

- [ ] `VisionAI.exe` on the gate PC posts to the Render URL (device key set in
      `gate.env`); `/api/detection/status` on the gate PC reports OK.
- [ ] The last event written by InstaBox and the first written by Render are both
      visible in `/logs` — same database, no gap.
- [ ] `CORS_ALLOWED_ORIGINS` on Render lists only the Render and `…web.app`
      hosts; the old `172.16.0.2` origin is removed.
- [ ] The InstaBox VM is powered off for a week before you delete anything.
- [ ] Its `.env`, `supabase-ca.crt` and any `best.pt` copy are archived with the
      rest of the deployment secrets, not deleted with the VM.

---

## 5. Deploy it (the short version)

The full runbook is [`DEPLOY_RENDER_FREE.md`](DEPLOY_RENDER_FREE.md). If the
repository is already connected to Render:

1. **Blueprint** — Render → **New → Blueprint** → this repo. `render.yaml`
   creates one Docker web service named `srm-trp-transport`, plan `free`, region
   `singapore`, health check `/api/health`.
2. **Environment** — fill the five `sync: false` keys:
   `DATABASE_URL` (Supabase **session pooler**, password URL-encoded),
   `PGSSLROOTCERT_B64` (`base64 -w0 supabase-ca.crt`, one line),
   `JWT_SECRET` (`python -c "import secrets;print(secrets.token_urlsafe(48))"`),
   `DEVICE_API_KEYS` (one random 32-char key per gate PC),
   `FIREBASE_API_KEY` (public web key).
3. **Deploy** and watch the log for
   `PostgreSQL initialization complete` and `Listening at: http://0.0.0.0:10000`.
4. **Firebase** — add `srm-trp-transport.onrender.com` to **Authorized domains**,
   or sign-in fails with `auth/unauthorized-domain`.
5. **First admin** — verify the mailbox, then
   `python -m backend.manage_access add <email> --role head_admin`.
6. **Gate PC** — `VisionAI.exe --setup`, then `--check`, then start it. It needs
   the Render URL and the device key, nothing else.

Health check the deployment from anywhere:

```bash
curl -fsS https://srm-trp-transport.onrender.com/api/health
```

---

## 6. What to watch after a week

| Signal | Where | Healthy | Act when |
| --- | --- | --- | --- |
| 502/503 on first request | your own browser | one slow load after idle | every load slow → the instance is OOM-restarting |
| memory | Render → **Metrics** | < 400 MB | > 450 MB steadily → an export or a large page is leaking |
| stream errors in the browser console | DevTools | none, or one per 3.5 min | repeated → a proxy in front of Render is cutting the stream early |
| `vision_local_agent_required` count | Render → **Logs** | 0 | > 0 → someone is scanning on the portal instead of the gate PC |
| worker restarts | Render → **Logs** (`--max-requests`) | a few per day | many per hour → memory growth is real, file a bug |
| Supabase connection errors | Render → **Logs** | none | any → the session pooler URL is wrong or the password changed |

---

## 7. Troubleshooting specific to this move

| Symptom | Cause | Fix |
| --- | --- | --- |
| Dashboard stops updating after ~3.5 min, then recovers | the stream ended and the page fell back to polling | check `frontend/js/sse.js` was deployed; `node scripts/check_live_stream.mjs` |
| Every page slow at the same moment | all threads busy in `/api/stream` | confirm `API_SSE_SECONDS` is set; `GUNICORN_THREADS` ≥ 8 |
| 503 on `/api/detection/scan` | expected on Render | run `VisionAI.exe` on the gate PC |
| `--report` finds nothing on Render | the disk was replaced | read **Logs**, they carry the same blocks |
| Health check fails but the container is running | gunicorn bound to `127.0.0.1` | it must bind `0.0.0.0:$PORT` — `deploy/render/entrypoint.sh` does |
| Login works, `/api/events` returns 401 | cookie is `Secure` and you are on `http://` | use the HTTPS Render URL, never the IP |
| Two portals show different numbers | InstaBox still running against the same database | see §4 |

Cost of the honest setup: **₹0** on the free plan (one Render service + one
Supabase project + Firebase Spark). A paid Render instance at $7/mo removes the
cold start; it does not enable detection.
