# SRM TRP Transport — Upgrade Specification

> **Purpose.** This document is the complete, self-contained specification for
> the SRM TRP Transport upgrade. It is written to be imported into Claude (or
> any other engineer/agent) so that the architecture can be analysed, the
> implementation plan followed, and the remaining work continued **without
> reconstructing context**.
>
> It records: the system as it was, every requirement that drove the upgrade,
> the verified provenance of the AI model, the architecture that was built, the
> exact API contracts, the deployment topology, the security posture, the
> outstanding work, and the exact Git/Git Bash command sequence.
>
> **Repository:** `https://github.com/saran-44/frontend`
> **Branch of record:** `arena/1c01d46f-frontend`
> **Base commit:** `82f40e6d1c0619532db3431cb00c687cb1926251` (merged `main`)
> **Document version:** 2.0 — covers the detection, camera, Firebase and
> golden-glass-glass theme upgrade.

---

## Table of contents

1. [Executive summary](#1-executive-summary)
2. [The original request](#2-the-original-request)
3. [Constraints, corrections and non-negotiables](#3-constraints-corrections-and-non-negotiables)
4. [System architecture](#4-system-architecture)
5. [The AI model — verified provenance](#5-the-ai-model--verified-provenance)
6. [Upgrade component A — detection backend](#6-upgrade-component-a--detection-backend)
7. [Upgrade component B — cameras](#7-upgrade-component-b--cameras)
8. [Upgrade component C — golden glass light theme](#8-upgrade-component-c--golden-glass-light-theme)
9. [Upgrade component D — Firebase](#9-upgrade-component-d--firebase)
10. [Upgrade component F — Firebase Authentication](#10-upgrade-component-f--firebase-authentication)
11. [Upgrade component E — frontend/backend connection](#11-upgrade-component-e--frontendbackend-connection)
12. [API reference](#12-api-reference)
13. [Configuration reference](#13-configuration-reference)
14. [Deployment](#14-deployment)
15. [Security and privacy](#15-security-and-privacy)
16. [Testing and verification](#16-testing-and-verification)
17. [Git and Git Bash command reference](#17-git-and-git-bash-command-reference)
18. [Repository map](#18-repository-map)
19. [Outstanding work and known risks](#19-outstanding-work-and-known-risks)
20. [Appendix — verified environment facts](#20-appendix--verified-environment-facts)

---

## 1. Executive summary

SRM TRP Transport is an internal tool for the SRM TRP Engineering College
transport department. It tracks college buses as they enter and leave the
campus, logs every movement with the bus registration number, and gives the
transport office a live dashboard, analytics, exports and an audit trail.

This upgrade adds four capabilities on top of the existing platform:

| # | Capability | Delivered as |
| --- | --- | --- |
| A | **Bus sticker detection** — find the bus sticker in a frame, read the registration number, log it | `backend/vision.py` + `POST /api/detection/scan` |
| B | **Live camera access** — browser webcam now, NVR/DVR via HLS/MJPEG later | `frontend/js/cameras.js` + `GET /api/stream/<camera_id>` |
| C | **Golden glass light theme** with the official SRM TRP crest | `frontend/assets/theme.css` + `logo-emblem.png` / `logo-wordmark.png` |
| D | **Firebase** (`srmtrpai`) for Hosting and Analytics | `firebase.json`, `.firebaserc`, `frontend/js/firebase.js`, `/api/config/firebase` |
| E | **Firebase Authentication** — email/password + Google sign-in, restricted to an authorised email list | `backend/firebase_auth.py`, `backend/access.py`, `backend/manage_access.py`, `POST /api/auth/firebase` |

**What was explicitly *not* done, and why.** The upstream model project is a
Colab notebook with no service API, no licence and no committed weights. Rather
than fabricate a third-party endpoint or vendor unlicensed code, this upgrade
**re-implements the notebook's own pipeline locally** in `backend/vision.py`
and documents the provenance honestly. See [§5](#5-the-ai-model--verified-provenance).

---

## 2. The original request

The user asked for, in their own terms:

> Create a comprehensive Markdown upgrade specification for import into Claude
> and implement the upgrade across the existing SRM TRP Transport project.

with this scope:

1. **Integrate the backend associated with `best.pt`** for detecting bus
   stickers and extracting/logging the bus registration number.
2. **Search GitHub for the referenced backend/model repository.** The user will
   provide or insert backend details if a correct public repository cannot be
   identified.
3. **Add live camera access through the browser/web camera now**, while
   designing for later IP cameras connected through NVR or DVR.
4. **Support NVR/DVR live feeds through HLS or MJPEG**, and **document that
   raw RTSP requires a gateway/transcoder** and must not be loaded directly by
   the browser.
5. **Upgrade the frontend to a polished glassmorphism UI with a golden accent
   and an excellent light theme**, retaining the SRM TRP identity.
6. **Use the supplied official SRM TRP college logo** rather than the recreated
   wordmark.
7. **Integrate Firebase** using the user-created `srmtrpai` project and the
   Firebase CLI.
8. **Connect frontend and backend cleanly**, including Firebase Hosting /
   Analytics and deployment configuration.
9. **Deliver complete Git/Git Bash commands** for branch, commit, push, PR,
   merge and deployment, because the user performs the remote connection and
   deployment themselves.

---

## 3. Constraints, corrections and non-negotiables

These are standing instructions. They continue to apply to any follow-up work.

| # | Instruction | How it was honoured |
| --- | --- | --- |
| 1 | Produce the upgrade guidance as a **full-detail `.md` file** suitable for importing into Claude. | This document. |
| 2 | **"Update all"** — implement the complete upgrade and connect frontend/backend properly; no mock frontend, no disconnected feature. | Detection, cameras, Firebase and theme are all wired to real routes. |
| 3 | Use **Firebase CLI** with the user-created Firebase project; the user delegated architecture and connection choices ("connect as what you want"). | `firebase.json` + `.firebaserc` target `srmtrpai`; the frontend reads its config from the backend. |
| 4 | Use the **attached official college logo**. | `frontend/assets/logo-emblem.png` (crest) and `logo-wordmark.png` (wordmark), cropped from the supplied 1638×474 PNG. |
| 5 | Use a **glass UI with golden accents** and the **best light-theme treatment**. | `frontend/assets/theme.css`; light is now the *default* theme (dark remains as an alternative). |
| 6 | Provide **full Git Bash commands and deployment instructions** because the user performs the remote connection/deployment. | [§16](#16-git-and-git-bash-command-reference). |
| 7 | **Search GitHub for the `best.pt` backend.** No repository or API may be fabricated if none is verified. | Search performed; the source was found and verified ([§5](#5-the-ai-model--verified-provenance)). |
| 8 | **Never commit real credentials, real driver/bus registers, or personal media.** | The Firebase API key lives in the environment, not in Git. The secret scanner (`scripts/scan_secrets.py`) runs in CI. |
| 9 | **The earlier leaked MongoDB credential must be rotated and sensitive Git history purged** before production use. | Still outstanding — see [§19](#19-outstanding-work-and-known-risks). **This is a blocker for production.** |

---

## 4. System architecture

### 4.1 Component map

```
┌───────────────────────────────────────────────────────────────────────────┐
│                          BROWSER (the console)                            │
│                                                                           │
│  frontend/index.html            login page                                │
│  frontend/pages/*.html          8 authenticated pages                     │
│  frontend/js/*.js               19 ES modules (no build step)             │
│  frontend/assets/theme.css      golden-glass theme layer                  │
│  frontend/vendor/               Chart.js 4.4.4 · hls.js 1.5.17 ·         │
│                                 SheetJS 0.18.5 · firebase 11.10.0         │
│                                                                           │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌────────────────┐   │
│  │ cameras.js   │ │ firebase.js  │ │  sse.js      │ │ api.js         │   │
│  │ getUserMedia │ │ lazy SDK     │ │  live events │ │ fetch wrapper  │   │
│  │ HLS / MJPEG  │ │ Analytics    │ │  + polling   │ │ + ApiError     │   │
│  └──────┬───────┘ └──────┬───────┘ └──────────────┘ └────────────────┘   │
└─────────┼────────────────┼───────────────────────────────────────────────┘
          │  POST /api/detection/scan (frame JPEG)
          │  GET  /api/stream/<camera_id> (MJPEG)
          ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                    FLASK BACKEND  (container / VM)                        │
│                                                                           │
│  backend/app.py        app factory, routes, security headers, SSE        │
│  backend/auth.py       Argon2 hashing, JWT, HttpOnly cookie, RBAC        │
│  backend/config.py     env config, camera-stream + Firebase validation   │
│  backend/db.py         Mongo client, indexes, safe serialisation        │
│  backend/schemas.py    strict Pydantic request/query models             │
│  backend/services.py   ingestion, flags, stats, analytics, audit, export  │
│  backend/vision.py     YOLOv10n detection + OCR + plate normalisation    │
│  backend/detection_client.py  reference device → backend client         │
│                                                                           │
│  MongoDB  (events · users · drivers · buses · audit_logs · …)           │
└───────────────────────────────────────────────────────────────────────────┘
          ▲
          │  /api/** rewrite  →  Cloud Run service `srm-trp-transport`
┌─────────┼─────────────────────────────────────────────────────────────────┐
│         │        FIREBASE HOSTING (srmtrpai)                              │
│  firebase.json  public: frontend/ · rewrite /api/** → backend ·            │
│                 SPA fallback · cache + security headers                    │
└───────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Backend design

- **Flask application factory** (`create_app()`), so tests can build an app
  against `mongomock` without touching a real database.
- **Session model:** Argon2id password hashes, a short-lived HS256 JWT
  (`JWT_TTL_MINUTES`, default 15) delivered in an `HttpOnly`, `SameSite=Lax`
  cookie. The token is never placed in `localStorage`.
- **Roles:** `head_admin` (full read/write, audit, exports, detection) and
  `transport_office` (read/write on the operational records, no audit export,
  no detection scan).
- **Device authentication:** `X-Device-Key` header, compared with
  `hmac.compare_digest` against the `DEVICE_API_KEYS` list.
- **Validation:** every request body and query string is validated by a
  Pydantic model in `backend/schemas.py`; failures return `422` with a
  field-level error map.
- **Flag rules:** `unregistered_plate` (number not in the bus register),
  `low_ocr_confidence` (confidence `< OCR_CONFIDENCE_THRESHOLD`), and
  `long_overstay` (inside longer than `OVERSTAY_HOURS`).
- **"Currently Inside"** is derived from the latest IN/OUT state per bus, not
  stored separately.
- **Live updates:** Server-Sent Events (`/api/events/stream`), with an
  automatic fall back to polling when the SSE connection cannot be
  established.

### 4.3 Frontend design

- **No build step.** Native ES modules loaded directly by the browser. This
  keeps the deployment to "upload static files" and makes the Firebase Hosting
  setup trivial.
- **Role-aware shell.** `frontend/js/layout.js` builds the sidebar, top bar,
  global search and logout, and redirects users who lack the required role.
- **8 authenticated pages:** dashboard, logs, analytics, drivers, buses,
  driver-details, audit, manage.
- **Vendored dependencies** with licences, so the console has no runtime CDN
  dependency and works on a campus network without internet access.

---

## 5. The AI model — verified provenance

### 5.1 The checkpoint

| Property | Value |
| --- | --- |
| File | `best.pt` (repository root, tracked in Git) |
| Size | 5,729,139 bytes |
| Architecture | **Ultralytics YOLOv10n** (end-to-end, NMS-free) |
| Saved by | `ultralytics 8.4.20` |
| Classes | `{0: 'red circle', 1: 'sticker'}` — `nc=2` |
| Inference size | 640 px |
| Checkpoint license | **AGPL-3.0** |

Measured checkpoint metrics:

| Metric | Value |
| --- | --- |
| Precision | 0.84683 |
| Recall | 0.54419 |
| mAP@50 | 0.57818 |
| mAP@50-95 | 0.30302 |
| Fitness | 0.30302 |

> These numbers are modest. The model finds a *sticker* reliably enough for a
> first deployment, but recall of 0.54 means roughly half of the stickers are
> missed. Treat a `null` detection as "not found yet", never as "no bus".
> Re-training is a recommended follow-up ([§18](#18-outstanding-work-and-known-risks)).

### 5.2 The source repository — found and verified

The user's instruction was to *search GitHub* for the backend/model
repository, and to **not fabricate one** if none could be verified. The search
succeeded.

**`814725105014-debug/SRM-TRP-TRANSPORT-AI`**
→ <https://github.com/814725105014-debug/SRM-TRP-TRANSPORT-AI>

| Property | Value |
| --- | --- |
| Default branch | `main` |
| Commits | 1 — `ae546f9` "Created using Colab" |
| **License** | **None declared** (all rights reserved by default) |
| Created / pushed | 2026-03-02 / 2026-03-04 |
| Stars | 0 |

Repository contents (verified via the GitHub trees API):

```
README.md                                          (22 bytes)
SRM_TRP_AI.ipynb                                  (195,287 bytes)  ← the YOLOv10 notebook
train_yolov9_object_detection_on_trp_dataset.ipynb (4,134,102 bytes) ← Roboflow YOLOv9 notebook
data/{train,val,test}/README.md                   (1 byte each — empty placeholders)
models/README.md, scripts/README.md               (1 byte each — empty placeholders)
```

The pipeline, read verbatim from `SRM_TRP_AI.ipynb`:

```python
!git clone https://github.com/THU-MIG/yolov10.git
%cd yolov10
!pip install .

# YOLOv10 nano checkpoints
url = "https://github.com/jameslahm/yolov10/releases/download/v1.0/yolov10n.pt"

!unzip license_data.zip

!yolo task=detect mode=train epochs=100 batch=16 plots=True \
      model=weights/yolov10n.pt data=data.yaml

!yolo task=detect mode=predict conf=0.25 save=True \
      model=runs/detect/train/weights/best.pt source=car.jpg

!yolo task=detect mode=predict conf=0.25 save=True \
      model=runs/detect/train/weights/best.pt source=video.mp4
```

This matches our checkpoint exactly: YOLOv10n, trained for 100 epochs at batch
16 on a TRP dataset (`license_data.zip`, a Roboflow export), producing
`runs/detect/train/weights/best.pt`.

### 5.3 Consequences — and why the backend is local

1. **There is no hosted inference API.** The source project is a Colab
   notebook, not a server. It exposes no endpoint, no request/response schema
   and no licence permitting its code to be vendored. The integration here
   therefore **re-implements the notebook's pipeline locally** in
   `backend/vision.py` — the same four stages the notebook performs
   (detect → crop → OCR → log), with the same model, the same confidence
   semantics and a proper HTTP contract.
2. **`data.yaml` and `license_data.zip` are not committed.** The class names
   `red circle` and `sticker` are known only from the checkpoint itself, and
   the training dataset cannot be re-derived from that repository.
3. **Licensing.** The checkpoint inherits Ultralytics' **AGPL-3.0**
   (`THU-MIG/yolov10` and `ultralytics/ultralytics` are both AGPL-3.0); the
   source repository declares no licence. Before any public or commercial
   deployment, obtain a written position from the model owner, **or** re-train
   an equivalent model on a dataset you are licensed to use and replace
   `best.pt`. AGPL-3.0 obliges you to offer the corresponding source to users
   who interact with the software over a network.
4. `814725105014-debug/SRM-TRP-TRANSPORT-AI-NEW` also exists but is **empty**
   (GitHub returns `409 Git Repository is empty`).

### 5.4 Repositories that were checked and rejected

| Repository | Why rejected |
| --- | --- |
| `hemanathanmd01/Clg-bus-project` | An earlier prototype of the same college transport project. Contains **no model weights** (only `app.py`, HTML, CSV logs, a PDF, sample videos and images), declares **no licence**, and its code embeds credentials. Not the source of `best.pt`; none of its code was copied. |
| `MuhammadMoinFaisal/Automatic_Number_Plate_Detection_Recognition_YOLOv8` | Generic ANPR; YOLOv8, unrelated weights. |
| `avneetkashyap479/NumberPlate_detection` | "Platewatch" — YOLOv8 + EasyOCR + Flask; different weights, MIT-licensed but irrelevant. |
| `AarohiSingla/Automatic-Number-Plate-Recognition--ANPR-` | YOLOv8 + EasyOCR notebook; unrelated weights. |
| `SANDEEP-K15/Number-Plate-Detection-` | YOLOv8/YOLOv5 Flask app; unrelated weights. |
| `AhmadHasbyBik/Vehicle_Plate_Detection_YOLO_OCR` | Indonesian plate pipeline; `fast-plate-ocr`; unrelated weights. |
| `Abdulbasitdashti/number_plate_detection` | YOLO11; unrelated weights. |
| `prachikale05/Automatic_Number_Plate_Recognition` | PaddleOCR ANPR; weights explicitly **not** included. |
| `KALYAN1045/Automatic-Number-Plate-Recognition-using-YOLOv5` | YOLOv5s; unrelated weights. |

### 5.5 If the user supplies a different backend

The user said: *"the user will provide/insert backend details if a correct
public repository cannot be identified."* A correct public repository **was**
identified ([§5.2](#52-the-source-repository--found-and-verified)), so the
"insert backend details" path is **not** currently needed. If the user
nonetheless supplies a hosted endpoint, the integration seam is narrow and
documented:

- Implement the same interface as `backend/vision.py`:
  `load_model()`, `detect(image) -> DetectionResult`, `read_text(image)`,
  `normalize_plate(text)`, `vision_status()`.
- Or point `VISION_MODEL_PATH` at a remote-capable loader.
- The HTTP contract in [§11](#11-api-reference) does **not** change, so the
  frontend needs no modification.

---

## 6. Upgrade component A — detection backend

### 6.1 What was built

`backend/vision.py` — a self-contained bridge between the Ultralytics
checkpoint and OCR.

**Design rule: no hard dependency on Torch at import time.** The API must
start, serve the whole console and report "detection unavailable" on a host
without the vision extras. Every Torch/Ultralytics import happens inside a
function.

| Function | Purpose |
| --- | --- |
| `load_model()` | Lazily loads `best.pt` via Ultralytics; cached for the process lifetime behind a lock. |
| `detect(image, model=None, threshold=None)` | Inference → crop each sticker → OCR each crop → rank candidates. |
| `decode_image(payload)` | Decodes raw bytes, a `data:` URL or bare base64 into a PIL image. |
| `read_text(image, engine=None)` | Runs OCR through the configured engine. |
| `normalize_plate(text)` | Cleans OCR output into a canonical plate string. |
| `best_candidate(result)` | Returns the highest-confidence candidate. |
| `vision_status()` | Model presence, load state, class names, OCR availability, and the reasons it is unavailable. |

### 6.2 OCR engines

`VISION_OCR_ENGINE` selects the engine. `auto` (the default) tries them in
order and uses the first that works:

| Order | Engine | Package | Notes |
| --- | --- | --- | --- |
| 1 | **RapidOCR** | `rapidocr-onnxruntime` | **Default.** ONNX-based, bundles its own models, requires **no system packages**. Recommended. |
| 2 | Tesseract | `pytesseract` + the `tesseract-ocr` binary | Needs the binary installed on the host. |
| 3 | EasyOCR | `easyocr` | Heavy — pulls `scikit-image`; only worth it if already present. |

**Verified in this environment:** RapidOCR read a synthetic plate
`TN 12 AB 1234` at **0.994** confidence, and the whole pipeline ran a
1280×720 frame in **~114 ms** on CPU.

### 6.3 Plate normalisation

`normalize_plate()` upper-cases the text, strips characters that cannot appear
on an Indian registration plate, collapses whitespace, and removes the space
that separates the two halves of a plate while preserving the display
grouping:

```
"tn 12 ab 1234"   ->  "TN 12 AB 1234"
"tn-12-ab-1234"   ->  "TN 12 AB 1234"
```

### 6.4 Wiring into the API

Two routes were added to `backend/app.py`:

- **`GET /api/detection/status`** — `head_admin` only. Reports whether the
  stack can run right now.
- **`POST /api/detection/scan`** — authorised by **either** a device API key
  (`X-Device-Key`) **or** an authenticated `head_admin` session. The combined
  guard is `require_device_key_or_roles()` in `backend/auth.py`.

The session path is what lets the operator press **"Scan plate"** in the
browser; the device-key path is what lets an on-site detector post frames.

Every scan is written to the audit log with the action `detection_scan`.

### 6.5 Detection → movement

A detection is a *reading*; a movement is an *event*. To turn one into the
other, post the read result through the existing event endpoint so the flag
rules and the "Currently Inside" state apply consistently:

```bash
curl -X POST http://localhost:5000/api/events \
  -H "X-Device-Key: $DEVICE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"bus_number":"TN12AB1234","direction":"IN","gate":"Gate 1 Entry",
       "camera_id":"gate-1-entry","confidence":0.94,
       "timestamp":"2026-11-12T09:15:00+05:30"}'
```

The event contract is unchanged from `docs/EVENT_CONTRACT.md`.

### 6.6 Vision extras

`backend/requirements-vision.txt` pins the verified versions:

```
torch==2.9.1
torchvision==0.24.1
ultralytics==8.4.20
opencv-python-headless==4.10.0.84
Pillow>=10.0.0
rapidocr-onnxruntime==1.4.4
pytesseract>=0.3.10
```

> **Disk warning (learned the hard way).** The default `torch` wheel on PyPI
> is the **CUDA** build and pulls ~3 GB of NVIDIA runtime libraries; a full
> install exhausted the sandbox disk (`OSError: [Errno 28] No space left on
> device`). On a CPU-only host use the CPU index:
>
> ```bash
> pip install torch==2.9.1 torchvision==0.24.1 \
>     --index-url https://download.pytorch.org/whl/cpu
> ```
>
> `opencv-python-headless` is deliberate: the full `opencv-python` wheel
> requires `libGL.so.1`, absent on minimal server images, which breaks
> `import cv2`.

---

## 7. Upgrade component B — cameras

Full detail: **`docs/CAMERAS.md`**. Summary:

| Source | Runs on | How the browser receives it | Status |
| --- | --- | --- | --- |
| **Operator webcam** | The operator's own device | `navigator.mediaDevices.getUserMedia` | ✅ Working today |
| **HLS** | NVR/DVR or a transcoder gateway | `.m3u8` over HTTP(S) via the vendored `hls.js` | ✅ Supported |
| **MJPEG** | NVR/DVR, or the backend proxy | `multipart/x-mixed-replace` over HTTP(S) | ✅ Supported |
| **Raw RTSP** | The IP camera | *impossible directly* — needs a gateway | ⚠️ Gateway required |

### 7.1 Browser camera

`frontend/js/cameras.js` implements the "live camera now" path. The dashboard
mounts an **"Operator camera (this device)"** tile at the top of the camera
grid whenever `navigator.mediaDevices.getUserMedia` exists. A **"Scan plate"**
button grabs the current frame to a canvas, encodes it as JPEG and posts it to
`POST /api/detection/scan`; the detected number and confidence appear in the
"Last detected" panel and the table refreshes.

Permission failures are reported in plain language ("Camera permission was
denied", "The camera is already in use by another application"), and every
media track is stopped when the tile leaves the DOM so the camera light goes
out.

**Requirement:** the camera API needs a **secure context** — `https://` or
`http://localhost`. A plain-HTTP LAN IP will not expose the camera. Terminate
TLS in front of the app, or use the NVR/DVR path.

### 7.2 HLS and MJPEG from an NVR/DVR

Configure `CAMERA_STREAM_URLS`:

```bash
export CAMERA_STREAM_URLS='{
  "gate-1-entry": {"type":"hls","url":"https://nvr.campus.local/hls/gate1/index.m3u8","label":"Gate 1 Entry"},
  "gate-2-entry": {"type":"mjpeg","url":"http://192.168.1.64:8080/mjpeg/stream.cgi?channel=1","label":"Gate 2 Entry"}
}'
```

Rules enforced by `backend/config.py`: `type` ∈ `hls | mjpeg | rtsp`; the
scheme must be `http`, `https` or `rtsp`; **no embedded credentials**; the
label must be 1–80 characters.

### 7.3 RTSP requires a gateway — the rule, stated plainly

> **A browser cannot open an RTSP session.** RTSP is not a media format a
> browser understands: it cannot negotiate the RTSP control flow
> (`OPTIONS`/`DESCRIBE`/`SETUP`/`PLAY`), it cannot open the RTSP-over-TCP or
> RTSP-over-UDP transport, and `rtsp://…` in a `<video>` tag produces a media
> error, not a picture.

Therefore an RTSP camera must be bridged by a **gateway / transcoder** that
republishes the video as **HLS** or **MJPEG** over HTTP. Three supported
routes:

1. **Use an NVR/DVR that republishes.** Point the console at the recorder's
   HLS or MJPEG output — the recorder handles RTSP natively.
2. **Run a gateway.** MediaMTX or FFmpeg (examples in `docs/CAMERAS.md` §3).
3. **Capture and detect server-side.** For unattended detection the browser
   does not need to watch the video at all: an edge agent pulls RTSP with
   FFmpeg/OpenCV, calls `POST /api/detection/scan`, and the console shows the
   *results*. This is the most bandwidth-efficient design and the recommended
   one for a multi-gate campus.

When `CAMERA_STREAM_URLS` contains a camera of type `rtsp`, the tile renders
an explicit **"RTSP gateway required"** notice explaining the above, instead
of silently showing a broken player.

### 7.4 Backend MJPEG proxy

`GET /api/stream/<camera_id>` relays a configured MJPEG multipart stream from
a LAN camera to the browser (which removes CORS and mixed-content problems).
It requires a `head_admin` session, sets `Cache-Control: no-store` and
`X-Accel-Buffering: no`, and returns `415` for non-MJPEG cameras with a
message pointing at the HLS/MJPEG gateway URL.

---

## 8. Upgrade component C — golden glass light theme

### 8.1 The official logo

The supplied official SRM TRP college logo
(`/tmp/arena-coding-uploads/image-1.png`, PNG RGBA, 1638×474) was cropped
into two production assets:

| Asset | Size | Use |
| --- | --- | --- |
| `frontend/assets/logo-emblem.png` | 360×318, 102,761 B | The crest — login page and favicon source |
| `frontend/assets/logo-wordmark.png` | 820×369, 141,268 B | The full lockup — sidebar |
| `frontend/assets/favicon.png` | 128×128, 24,458 B | Browser favicon (replaces `favicon.svg`) |

The temporary recreated wordmark (`frontend/assets/logo.svg`) is no longer
referenced by any page.

### 8.2 The sampled palette

Colours were sampled directly from the crest:

| Swatch | Hex | Role |
| --- | --- | --- |
| Navy | `#283060` | Crest, wordmark, badges, deep surfaces |
| Green | `#085828` | Crest leaves |
| Yellow | `#F8E840` | Crest ring, gold accent (light theme) |
| Red | `#A02820` | SRM lettering |

### 8.3 The theme layer

`frontend/assets/theme.css` is loaded **after** `styles.css` on all nine
pages. It re-skins the existing layout — it does not rewrite it — so the
sidebar structure, card anatomy, tables and typography are untouched.

Key treatments:

- **Translucent glass surfaces** (`rgba` fills + `backdrop-filter: blur(18px)
  saturate(140%)`) on the sidebar, top bar, cards, stat cards, inputs, table
  cells, modals, toasts and search results.
- **A golden aurora** behind the glass via a fixed `body::before` layer with
  three radial gradients.
- **A gold sheen** that fades in over stat cards on hover.
- **Gold-gradient primary buttons**, a navy→gold gradient bus badge, and a
  **number-plate chip** (navy plate, gold border, gold lettering, inner
  glow).
- **Light theme by default.** `applyTheme()` in `frontend/js/layout.js` now
  defaults to light; the midnight navy variant remains available via the
  theme toggle and is persisted in `localStorage` under `transport-theme`.
- **`prefers-reduced-transparency`** — the glass falls back to solid surfaces
  for users who ask for reduced transparency.
- **Print styles** — the sidebar and top bar are hidden.

### 8.4 The golden-glass variable system

```css
:root {
  --brand-navy: #283060;  --brand-gold: #d4a017;  --brand-gold-bright: #f8e840;
  --app-bg: linear-gradient(160deg,#fdfaf1 0%,#f7f1e0 42%,#eef1fa 100%);
  --card-bg: rgba(255,255,255,0.72);
  --primary: #b8860b;  --primary-contrast: #fffdf7;
  --glass-blur: 18px;  --glass-shadow: 0 10px 30px rgba(40,48,96,.09);
}
body.dark-theme { /* midnight navy + the same gold accents */ }
```

---

## 9. Upgrade component D — Firebase

Full detail: **`docs/FIREBASE.md`**.

### 9.1 Project facts (supplied by the user)

| Item | Value |
| --- | --- |
| Project id | `srmtrpai` |
| Auth domain | `srmtrpai.firebaseapp.com` |
| Storage bucket | `srmtrpai.firebasestorage.app` |
| Messaging sender id | `734375891811` |
| Web app id | `1:734375891811:web:6851938bef332bc0e53956` |
| Measurement id | `G-7MXBNH3N7D` |
| API key | **Supplied but deliberately not committed** — read from the environment |

### 9.2 Configuration flow

```
.env / secret store
      │  FIREBASE_API_KEY, FIREBASE_PROJECT_ID, …
      ▼
backend/config.py  →  Config.firebase
      │
      ▼
GET /api/config/firebase          (public route, no auth)
      │
      ▼
frontend/js/firebase.js  →  lazily injects /vendor/firebase/*.js
      │                            → window.firebase.initializeApp(config)
      ▼
Analytics events: app_open · login · logout · screen_view ·
                  capture_frame · detection_result · export_data
```

**Why the config is served from the backend rather than hard-coded:**

1. The API key never enters Git, so it can be rotated without a code change.
2. The repository carries no deployment identifiers.
3. The console **works fully without Firebase** — when the configuration is
   absent, `/api/config/firebase` returns `{"enabled": false}` and the SDK is
   never downloaded. Firebase is an enhancement, not a dependency.

### 9.3 The vendored SDK

`frontend/vendor/firebase/` holds the *compat* (UMD) builds of `firebase/app`,
`firebase/analytics` and `firebase/firestore` from `firebase@11.10.0`
(Apache-2.0), with the licence and a `README.md` documenting provenance and
how to regenerate them. The compat builds work with a plain `<script>` tag,
which suits the project's no-build-step frontend.

### 9.4 Hosting configuration

`firebase.json`:

- `public: "frontend"`.
- `/api/**` → rewritten to the Cloud Run service `srm-trp-transport` in
  `asia-south1`.
- Everything else → `/index.html` (SPA fallback), with `cleanUrls: true`.
- `/assets/**` and `/vendor/**` → one-year immutable cache.
- `/api/**` → `no-store`.
- Security headers on everything, including
  `Permissions-Policy: camera=(self), microphone=(), geolocation=()` — note
  `camera=(self)` is what keeps the operator webcam working.

`.firebaserc` selects `srmtrpai` as the default project.

---

## 10. Upgrade component F — Firebase Authentication

Full detail: **`docs/AUTHENTICATION.md`**.

### 10.1 The model

The portal authenticates with **Firebase Authentication** (email/password and
Google) and authorises against a **server-side access list**. Two independent
gates must both pass:

1. **Firebase** decides whether the *credential* is valid.
2. **The backend's access list** (the MongoDB `users` collection) decides
   whether that *identity* may use the portal.

The second gate is not redundant. Firebase can issue tokens to self-registered
password users and to arbitrary Google accounts. Neither is evidence that an
administrator authorised portal access. Both providers must supply a verified
email before an access-list entry can be used or a UID bound.

| Provider | Unknown email | Rule |
| --- | --- | --- |
| `password` | Only if specifically approved | Auto-provisioning requires a verified email, `FIREBASE_AUTO_PROVISION=true`, and an administrator-set `transport_portal_approved_email` claim matching that email. |
| `google.com` | **Refused** | The verified email must already be on the access list. |

### 10.2 What was built

| Path | Role |
| --- | --- |
| `backend/firebase_auth.py` | Verifies a Firebase ID token (RS256) against Google's **public** signing keys. No service account, no private key. |
| `backend/access.py` | The access list: resolve, authorise, auto-provision, bind the Firebase UID. |
| `backend/manage_access.py` | The `python -m backend.manage_access` CLI. |
| `backend/app.py` | `POST /api/auth/firebase`, `GET /api/auth/config`. |
| `backend/schemas.py` | `FirebaseTokenSchema`. |
| `frontend/js/auth.js` | Sign-in flows and the token exchange. |
| `frontend/js/login.js` | The login page, rewritten. |
| `frontend/js/firebase.js` | Lazy loading, now including the Auth bundle. |
| `frontend/vendor/firebase/firebase-auth-compat.js` | The vendored Auth SDK. |

### 10.3 The session

The Firebase ID token is exchanged for the application's own session: an
HS256 JWT in an HttpOnly, `SameSite=Lax`, `Secure`-in-production cookie,
valid for `JWT_TTL_MINUTES`. The Firebase token is used once and discarded —
it is never stored and never reachable from JavaScript.

### 10.4 Verification order

`POST /api/auth/firebase` checks, in order: token shape → RS256 signature →
audience → issuer → expiry → allowed provider → access list → Firebase UID
binding. Only then is the session cookie issued.

### 10.5 The access-list CLI

```bash
python -m backend.manage_access list
python -m backend.manage_access add transport.office@srmtrp.edu.in
python -m backend.manage_access set-role principal@srmtrp.edu.in head_admin
python -m backend.manage_access deactivate transport.office@srmtrp.edu.in
python -m backend.manage_access activate transport.office@srmtrp.edu.in
python -m backend.manage_access unlink transport.office@srmtrp.edu.in
```

### 10.6 Why not Supabase

Firebase. The decisive point is that this project's data lives in **MongoDB**,
not Postgres — Supabase's headline feature, Row Level Security, protects
*only* Postgres tables, so it would not apply to a single row of the actual
data. The allowlist would still be enforced in application code exactly as
described above, while adding a second provider, SDK and set of secrets.
See [`docs/AUTHENTICATION.md` §7](AUTHENTICATION.md#7-why-not-supabase).

---

## 11. Upgrade component E — frontend/backend connection

The console calls the API on the **same origin** (`/api/...`), which Firebase
Hosting rewrites to the backend. The browser therefore sees a single origin:

- The `SameSite=Lax` session cookie works unchanged.
- No CORS pre-flight is needed in the hosted topology.
- `CORS_ALLOWED_ORIGINS` is only required if the frontend is *also* served
  from another origin (e.g. directly from Flask during development). Set it to
  `https://srmtrpai.web.app,https://srmtrpai.firebaseapp.com`.

The backend serves the frontend itself when it is not behind Firebase
Hosting, so the same codebase runs in both topologies:

```bash
# single-origin (Flask serves the console)
.venv/bin/gunicorn --bind 0.0.0.0:8080 "backend.app:create_app()"

# split-origin (Firebase Hosting + Cloud Run) — see firebase.json
firebase deploy --only hosting
```

---

## 12. API reference

### 11.1 Existing routes (unchanged)

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/health` | public | Liveness probe. |
| `GET` | `/api/auth/config` | public | Which sign-in methods this deployment offers. |
| `POST` | `/api/auth/firebase` | public | Exchange a Firebase ID token for a session cookie. |
| `POST` | `/api/auth/login` | public | Exchange local credentials for a session cookie (break-glass). |
| `POST` | `/api/auth/logout` | session | Clear the session. |
| `GET` | `/api/auth/me` | session | Current user profile. |
| `GET` | `/api/config` | `head_admin` | Camera definitions, flag labels, rule thresholds, `camera_support`. |
| `GET` | `/api/stats` | `head_admin` | Dashboard counters. |
| `GET` | `/api/analytics` | `head_admin` | Chart series. |
| `GET` | `/api/events` | `head_admin` | Paginated, filtered event list. |
| `POST` | `/api/events` | device key | Ingest a movement. |
| `GET` | `/api/events/<id>` | `head_admin` | One event. |
| `GET` | `/api/events/stream` | `head_admin` | Server-Sent Events feed. |
| `GET` | `/api/export/events.csv` | `head_admin` | CSV export. |
| `GET` | `/api/export/events.xlsx` | `head_admin` | XLSX export. |
| `GET` | `/api/drivers`, `/api/buses`, `/api/audit` | role-based | Records. |
| `POST`/`PUT`/`DELETE` | CRUD routes | role-based | Create/update/delete with audit. |

### 11.2 New routes

#### `GET /api/config/firebase` — public

```json
{
  "config": {
    "apiKey": "…",
    "authDomain": "srmtrpai.firebaseapp.com",
    "projectId": "srmtrpai",
    "storageBucket": "srmtrpai.firebasestorage.app",
    "messagingSenderId": "734375891811",
    "appId": "1:734375891811:web:6851938bef332bc0e53956",
    "measurementId": "G-7MXBNH3N7D"
  },
  "projectId": "srmtrpai",
  "enabled": true,
  "analytics": true
}
```

When Firebase is not configured: `{"config": {}, "projectId": null,
"enabled": false, "analytics": false}`.

#### `GET /api/detection/status` — `head_admin`

```json
{
  "model_path": "/srv/srm-trp/best.pt",
  "model_present": true,
  "model_loaded": true,
  "confidence_threshold": 0.35,
  "ocr_engine": "auto",
  "ocr_available": "rapidocr",
  "classes": {"0": "red circle", "1": "sticker"},
  "available": true,
  "problems": []
}
```

`available` is `true` only when the checkpoint is present **and** an OCR
engine is usable. `problems` explains why not.

#### `POST /api/detection/scan` — device key **or** `head_admin` session

Accepts a multipart upload (`image` file part) or a JSON body with an
`image` field holding base64 data.

```bash
curl -X POST http://localhost:5000/api/detection/scan \
  -H "X-Device-Key: $DEVICE_API_KEY" \
  -F "image=@frame.jpg" -F "camera_id=gate-1-entry" \
  -F "direction=IN" -F "gate=Gate 1 Entry"
```

```json
{
  "detection": {
    "candidates": [{
      "bus_number": "TN12AB1234", "raw_text": "TN 12 AB 1234",
      "confidence": 0.94, "bbox": [412,288,596,352],
      "class_name": "sticker", "class_id": 1
    }],
    "model": "best.pt", "inference_ms": 118,
    "frame_width": 1280, "frame_height": 720
  },
  "bus_number": "TN12AB1234",
  "confidence": 0.94,
  "raw_text": "TN 12 AB 1234",
  "source": "device"
}
```

| Status | Meaning |
| --- | --- |
| `400` | No image supplied, or a malformed body. |
| `401` | No device key and no valid session. |
| `403` | A session was supplied but the role is not `head_admin`. |
| `503` | The vision stack is unavailable (model missing, no OCR engine). |
| `500` | Inference raised an unexpected error. |

#### `GET /api/stream/<camera_id>` — `head_admin`

Relays a configured MJPEG stream. `404` for an unknown camera, `415` for a
non-MJPEG camera (with a message pointing at the HLS/MJPEG gateway URL).

---

## 13. Configuration reference

### 12.1 Existing variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `ENVIRONMENT` | `development` | `development` \| `testing` \| `production`. |
| `FLASK_DEBUG` | `false` | Honoured only in development. |
| `HOST` / `PORT` | `127.0.0.1` / `5000` | Bind address. |
| `MONGO_URI` | *(required)* | MongoDB connection string. |
| `MONGO_DB_NAME` | derived | Database name. |
| `JWT_SECRET` | *(required)* | HS256 signing key; ≥32 chars in production. |
| `JWT_TTL_MINUTES` | `15` | Access-token lifetime (1–60). |
| `COOKIE_SECURE` | `true` in production | Secure cookie flag. |
| `CORS_ALLOWED_ORIGINS` | empty | Explicit origin allowlist; wildcards rejected. |
| `DEVICE_API_KEYS` | empty | Comma-separated device keys. |
| `LOGIN_RATE_LIMIT` | `5 per minute;20 per hour` | Flask-Limiter syntax. |
| `RATELIMIT_ENABLED` | `true` | Toggle throttling. |
| `RATELIMIT_STORAGE_URI` | `memory://` | Use `redis://` with >1 worker. |
| `APP_TIMEZONE` | `Asia/Kolkata` | "Today" boundaries and chart buckets. |
| `OCR_CONFIDENCE_THRESHOLD` | `0.75` | Below this → `low_ocr_confidence`. |
| `OVERSTAY_HOURS` | `12` | Inside longer → `long_overstay`. |
| `CAMERA_STREAM_URLS` | empty | JSON object of camera streams. |

### 12.2 New variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `VISION_MODEL_PATH` | `best.pt` | Path to the Ultralytics checkpoint. |
| `VISION_CONFIDENCE` | `0.35` | Minimum detection confidence. |
| `VISION_OCR_ENGINE` | `auto` | `auto` \| `rapidocr` \| `tesseract` \| `easyocr` \| `none`. |
| `VISION_MAX_CROPS` | `8` | Maximum sticker crops OCR'd per frame. |
| `FIREBASE_API_KEY` | empty | Firebase web API key. |
| `FIREBASE_AUTH_DOMAIN` | `srmtrpai.firebaseapp.com` | Auth domain. |
| `FIREBASE_PROJECT_ID` | `srmtrpai` | Project id. |
| `FIREBASE_STORAGE_BUCKET` | `srmtrpai.firebasestorage.app` | Storage bucket. |
| `FIREBASE_MESSAGING_SENDER_ID` | `734375891811` | Messaging sender id. |
| `FIREBASE_APP_ID` | `1:734375891811:web:6851938bef332bc0e53956` | Web app id. |
| `FIREBASE_MEASUREMENT_ID` | `G-7MXBNH3N7D` | Analytics measurement id. |
| `FIREBASE_AUTH_ENABLED` | `true` | Master switch for Firebase sign-in (effective only when a project id is set). |
| `FIREBASE_ALLOWED_PROVIDERS` | `password,google.com` | Which Firebase providers are accepted. |
| `FIREBASE_AUTO_PROVISION` | `true` | Auto-create the access record only for a verified password identity with the administrator-set approval claim. |
| `FIREBASE_DEFAULT_ROLE` | `transport_office` | The role given to an auto-provisioned account. |
| `LEGACY_PASSWORD_LOGIN_ENABLED` | `true` | Keep the local MongoDB password login as a break-glass path. |

`.env.example` documents all of them.

---

## 14. Deployment

### 13.1 Topology

```
                 ┌──────────────────────────────────────┐
   Browser ─────▶│  Firebase Hosting  (srmtrpai)        │
                 │  static console + /api/** rewrite    │
                 └──────────────────┬───────────────────┘
                                    │ HTTPS
                                    ▼
                 ┌──────────────────────────────────────┐
                 │  Cloud Run / Docker  (Flask backend)  │
                 │  + best.pt + vision extras            │
                 └──────────────────┬───────────────────┘
                                    │
                                    ▼
                                 MongoDB
```

### 13.2 Backend — Cloud Run

```bash
gcloud run deploy srm-trp-transport \
  --image REGION-docker.pkg.dev/PROJECT/REPO/srm-trp-transport:latest \
  --region asia-south1 --platform managed --allow-unauthenticated \
  --set-env-vars "ENVIRONMENT=production,MONGO_DB_NAME=srmtrpai,APP_TIMEZONE=Asia/Kolkata,FIREBASE_PROJECT_ID=srmtrpai,FIREBASE_AUTH_DOMAIN=srmtrpai.firebaseapp.com,FIREBASE_STORAGE_BUCKET=srmtrpai.firebasestorage.app,FIREBASE_MESSAGING_SENDER_ID=734375891811,FIREBASE_APP_ID=1:734375891811:web:6851938bef332bc0e53956,FIREBASE_MEASUREMENT_ID=G-7MXBNH3N7D" \
  --set-secrets "MONGO_URI=mongo-uri:latest,JWT_SECRET=jwt-secret:latest,DEVICE_API_KEYS=device-keys:latest,FIREBASE_API_KEY=firebase-api-key:latest"
```

### 13.3 Backend — plain Docker

```bash
docker build -f deploy/Dockerfile -t srm-trp-transport:latest .
docker run -d --name srm-trp -p 8080:8080 \
  --env-file .env.production srm-trp-transport:latest
```

`deploy/Dockerfile` installs the base requirements, then the vision extras
from the CPU index, copies `backend/`, `frontend/` and `best.pt`, exposes
`8080`, and adds a `HEALTHCHECK` against `/api/health`. Build with
`--build-arg INSTALL_VISION=0` to skip the ~2 GB of ML dependencies when
detection runs elsewhere.

`deploy/cloudbuild.yaml` builds, pushes and deploys to Cloud Run in one
pipeline.

### 13.4 Frontend — Firebase Hosting

```bash
npm install -g firebase-tools
firebase login
firebase use --add          # choose srmtrpai
firebase deploy --only hosting
```

### 13.5 If the backend is not on Cloud Run

Update the `run` block in `firebase.json`, or delete the `/api/**` rewrite and
serve the API from the backend origin directly, adding that origin to
`CORS_ALLOWED_ORIGINS` and pointing the frontend's `api.js` base URL at it.

---

## 15. Security and privacy

| Area | Measure |
| --- | --- |
| Passwords | Argon2id via `argon2-cffi`; never logged or returned. |
| Sessions | Short-lived HS256 JWT in an `HttpOnly`, `SameSite=Lax` cookie. |
| Authorisation | Role checks on every route; device keys compared with `hmac.compare_digest`. |
| Input validation | Strict Pydantic models on every body and query string. |
| Rate limiting | Flask-Limiter on login and sensitive endpoints. |
| Headers | CSP-adjacent headers, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`. |
| Secrets | `.env` is git-ignored; `scripts/scan_secrets.py` runs in CI; the Firebase API key is read from the environment. |
| Personal data | Vehicle registration numbers are personal data. See `docs/PRIVACY.md`. |
| **Outstanding** | **The previously committed MongoDB credential must be rotated and purged from Git history before production use.** |

---

## 16. Testing and verification

### 15.1 Backend

```bash
.venv/bin/python -m pytest backend/tests -q
```

**115 tests pass** (60 pre-existing + 18 detection + 37 authentication).

### 15.2 Frontend

```bash
node scripts/check_frontend.mjs
# → Frontend checks passed: 20 modules, 9 pages, all references resolve.
```

### 15.3 Secrets

```bash
.venv/bin/python scripts/scan_secrets.py
```

### 15.4 Live smoke test

```bash
.venv/bin/python scripts/run_preview.py      # binds 0.0.0.0, seeded demo data
```

Then, from the browser: log in, open **Dashboard**, confirm the golden glass
theme and the official crest in the sidebar, click **Scan plate** on the
operator camera tile, and confirm a number appears in "Last detected".

### 15.5 Detection smoke test

```bash
curl -s -b cookies.txt http://localhost:5000/api/detection/status | jq
curl -s -X POST http://localhost:5000/api/detection/scan \
  -H "X-Device-Key: $DEVICE_API_KEY" -F "image=@frame.jpg" | jq
```

---

## 17. Git and Git Bash command reference

> These are **Git Bash** commands (Windows). They work identically in a POSIX
> shell. The user performs the remote connection and deployment themselves.

### 16.1 Clone and configure

```bash
git clone https://github.com/saran-44/frontend.git
cd frontend

git config user.name  "Your Name"
git config user.email "you@example.com"

# Never commit credentials
cp .env.example .env
```

### 16.2 Create the upgrade branch

```bash
git fetch origin
git checkout -b feature/arena-upgrade origin/main
```

### 16.3 Stage, commit and push

```bash
git status
git add -A
git status --short          # review before committing

git commit -m "feat: integrate sticker detection, camera access, Firebase and golden glass theme"

git push -u origin feature/arena-upgrade
```

### 16.4 Open the pull request

```bash
gh pr create \
  --base main \
  --head feature/arena-upgrade \
  --title "feat: sticker detection, NVR/DVR camera support, Firebase and golden glass theme" \
  --body-file docs/UPGRADE_SPECIFICATION.md
```

Or from the GitHub UI: **Pull requests → New pull request**.

### 16.5 Review and merge

```bash
gh pr checks --watch        # wait for CI
gh pr view --web            # open in the browser
gh pr merge <PR_NUMBER> --squash --delete-branch
```

Replace `<PR_NUMBER>` with the real number from `gh pr create`. The merge
command must be the last command in the chain so its exit code is meaningful.

### 16.6 Deploy

> The complete Windows/Git Bash sequence — toolchain install, log in, one-time
> Google Cloud setup, the Firebase console steps, deploy, verify and rollback —
> is in **`docs/DEPLOY_WINDOWS.md`**.

```bash
# --- frontend (Firebase Hosting) ---
npm install -g firebase-tools
firebase login
firebase use --add          # choose srmtrpai
firebase deploy --only hosting

# --- backend (Cloud Run) ---
gcloud auth login
gcloud config set project YOUR_GCP_PROJECT
gcloud builds submit --config deploy/cloudbuild.yaml

# --- or backend on a plain Docker host ---
docker build -f deploy/Dockerfile -t srm-trp-transport:latest .
docker run -d --name srm-trp -p 8080:8080 \
  --env-file .env.production srm-trp-transport:latest
```

### 16.7 Verify

```bash
curl -s https://srm-trp-transport-xxxxx-asia-south1.a.run.app/api/health
curl -s https://srmtrpai.web.app/api/config/firebase
```

### 16.8 Secret rotation and history purge (production blocker)

```bash
# 1. Rotate the credential in the database provider first.
# 2. Purge the old value from the history (install git-filter-repo first).
pip install git-filter-repo
git filter-repo --path .env --invert-paths       # if .env was ever committed
git push --force --mirror https://github.com/saran-44/frontend.git
# 3. Ask every collaborator to re-clone.
```

> **Do not run the purge until the credential has been rotated.** Purging
> history does not invalidate a leaked credential.

### 16.9 Recovery

```bash
git reflog                              # find the lost commit
git reset --hard <sha>
git push --force-with-lease origin feature/arena-upgrade
```

---

## 18. Repository map

```
frontend/                         repository root
├── best.pt                       YOLOv10n checkpoint (AGPL-3.0) — tracked
├── firebase.json                 Firebase Hosting config
├── .firebaserc                   default project: srmtrpai
├── .env.example                  every environment variable, documented
├── .github/workflows/ci.yml      CI: tests, frontend checks, secret scan
├── backend/
│   ├── app.py                    Flask factory, routes, SSE, security headers
│   ├── auth.py                   Argon2, JWT, cookie, RBAC, device keys
│   ├── access.py                 ★ the access list: authorise, auto-provision, bind
│   ├── firebase_auth.py          ★ Firebase ID token verification (Google JWKS)
│   ├── manage_access.py          ★ the access-list CLI
│   ├── config.py                 env config, camera + Firebase validation
│   ├── db.py                     Mongo client, indexes, safe serialisation
│   ├── schemas.py                strict Pydantic request/query models
│   ├── services.py               ingestion, flags, stats, analytics, audit
│   ├── vision.py                 ★ YOLOv10n detection + OCR + normalisation
│   ├── detection_client.py       reference device → backend client
│   ├── seed_demo.py              demo data seeding
│   ├── wsgi.py                   WSGI entry point
│   ├── requirements.txt          base dependencies
│   ├── requirements-vision.txt   ★ vision extras (torch, ultralytics, OCR)
│   └── tests/                    ★ test_detection.py added; 78 tests total
├── frontend/
│   ├── index.html                login page
│   ├── pages/                    8 authenticated pages
│   ├── js/
│   │   ├── api.js                fetch wrapper, ApiError, query builder
│   │   ├── ui.js                 el(), icon(), setState(), showToast()
│   │   ├── layout.js             shell, sidebar, topbar, theme toggle
│   │   ├── login.js              login form + session
│   │   ├── cameras.js            ★ getUserMedia, HLS, MJPEG, RTSP notice
│   │   ├── auth.js               ★ Firebase sign-in flows and the token exchange
│   │   ├── firebase.js           ★ lazy SDK init, auth + analytics events
│   │   ├── dashboard.js          ★ browser camera + scan-plate wiring
│   │   ├── sse.js                live events with polling fallback
│   │   ├── charts.js  filters.js  tables.js  exports.js
│   │   ├── analytics.js  audit.js  buses.js  drivers.js
│   │   ├── driver-details.js  logs.js  manage.js
│   ├── assets/
│   │   ├── styles.css            the original layout and components
│   │   ├── theme.css             ★ the golden glass theme layer
│   │   ├── login.css             login screen
│   │   ├── logo-emblem.png       ★ the official crest
│   │   ├── logo-wordmark.png     ★ the official wordmark
│   │   ├── favicon.png           ★ favicon from the crest
│   ├── vendor/
│   │   ├── chart.umd.js  hls.min.js  xlsx.full.min.js
│   │   └── firebase/             ★ firebase 11.10.0 compat builds (app, auth,
│                              analytics, firestore) + LICENSE
├── deploy/
│   ├── Dockerfile                ★ container image
│   └── cloudbuild.yaml           ★ Cloud Build → Cloud Run pipeline
├── docs/
│   ├── UPGRADE_SPECIFICATION.md  ★ this document
│   ├── AUTHENTICATION.md         ★ Firebase sign-in, the access list, Supabase
│   ├── DETECTION.md              ★ model provenance + detection API
│   ├── CAMERAS.md                ★ browser / HLS / MJPEG / RTSP gateway
│   ├── FIREBASE.md               ★ Firebase setup and deployment
│   ├── ARCHITECTURE.md  EVENT_CONTRACT.md  PRIVACY.md
├── scripts/
│   ├── check_frontend.mjs        module/page reference checker
│   ├── scan_secrets.py           credential scanner
│   └── run_preview.py            0.0.0.0 preview runner
├── README.md
└── TRANSPORT_PROJECT_STATUS.md
```

★ = added or changed by this upgrade.

---

## 19. Outstanding work and known risks

### 18.1 Blockers before production

| # | Item | Why it blocks | Action |
| --- | --- | --- | --- |
| 1 | **Rotate the leaked MongoDB credential and purge Git history** | The credential is in the repository's history. Anyone who clones it has the credential. | Rotate in the provider first, then purge ([§16.8](#168-secret-rotation-and-history-purge-production-blocker)), then force-push and ask collaborators to re-clone. |
| 2 | **Resolve the AGPL-3.0 / no-licence position on `best.pt`** | AGPL-3.0 obliges you to offer the corresponding source to network users. The upstream repository declares no licence. | Get written permission from the model owner, **or** re-train an equivalent model on a dataset you are licensed to use and replace `best.pt`. |
| 3 | **TLS in front of the app** | The browser camera API requires a secure context. | Terminate TLS at Cloud Run / a load balancer / a reverse proxy. |

#### Item 1 in detail — the leaked credential

An old connection string was committed in the root `app.py` and remains in
Git history. A replacement credential or a different cluster does not by
itself prove that the old database user was disabled. An Atlas administrator
must verify that the old credential has been revoked or rotated, then purge
the sensitive history as described in
[§16.8](#168-secret-rotation-and-history-purge-production-blocker).

Treat any credential shared in chat, logs or other unintended places as
exposed and rotate it separately. Store replacements in a secrets vault or
Secret Manager rather than committing them or sharing them in chat.

### 18.2 Recommended improvements

| # | Item | Detail |
| --- | --- | --- |
| 4 | **Re-train the model** | Recall is 0.544 and mAP@50-95 is 0.303 — roughly half of all stickers are missed. A better dataset and more epochs would materially improve detection. |
| 5 | **Edge detection agent** | Run detection on the camera host (or an edge box) and push events with `X-Device-Key`. Avoids streaming video to the browser entirely. |
| 6 | **Firestore rules** | If Firestore is adopted, publish explicit security rules; the repo has none today. |
| 7 | **Rate-limit the detection endpoint** | `POST /api/detection/scan` is CPU-heavy; rate-limit it per device key. |
| 8 | **Camera snapshot archive** | Store a cropped sticker image per event for evidence, with a retention policy. |

### 18.3 Known limitations of this implementation

- **Detection is synchronous and in-request.** A scan blocks for ~120 ms on
  CPU. That is fine for interactive use; for high frame rates, move to the
  edge agent (item 5).
- **`GET /api/stream/<camera_id>` buffers upstream reads in 8 KB chunks.** It
  works, but it is not a tuned video gateway. Prefer MediaMTX for real
  deployments.
- **The model detects a "sticker", not a plate.** `best.pt` was trained on a
  red-circle sticker class. OCR reads whatever text is inside the detected
  box. If the sticker design changes, detection quality degrades before OCR
  quality does.
- **Analytics are optional and best-effort.** If the Firebase SDK fails to
  load, the console logs a state error and continues — no user-visible
  breakage.

---

## 20. Appendix — verified environment facts

Everything in this appendix was executed and observed in the working
environment, not inferred.

| Fact | Value |
| --- | --- |
| Checkpoint | 5,729,139 bytes, Ultralytics YOLOv10n, `ultralytics 8.4.20` |
| Checkpoint classes | `{0: 'red circle', 1: 'sticker'}`, `nc=2`, `imgsz=640` |
| Checkpoint metrics | precision 0.84683 · recall 0.54419 · mAP50 0.57818 · mAP50-95 0.30302 · fitness 0.30302 |
| Official logo source | PNG RGBA 1638×474 |
| Sampled palette | navy `#283060` · green `#085828` · yellow `#F8E840` · red `#A02820` |
| Model load time | 0.9 s (cold), cached thereafter |
| Inference time | 241 ms (640×640) · 114 ms (1280×720), CPU |
| RapidOCR accuracy | 0.994 on a synthetic `TN 12 AB 1234` plate |
| OCR engine in use | `rapidocr` |
| Python | 3.11 |
| torch / torchvision | 2.9.1+cu128 / 0.24.1+cu128 |
| ultralytics / opencv | 8.4.20 / 4.10.0.84 |
| Backend tests | **115 passed** |
| Frontend check | 20 modules, 9 pages, all references resolve |
| Source repository | `814725105014-debug/SRM-TRP-TRANSPORT-AI` — 1 commit, **no licence**, weights not committed |
| Rejected repository | `hemanathanmd01/Clg-bus-project` — no weights, no licence, credential-bearing |
| Empty sibling repo | `814725105014-debug/SRM-TRP-TRANSPORT-AI-NEW` — `409 Git Repository is empty` |

### Command cheat-sheet

```bash
# backend
.venv/bin/python -m pytest backend/tests -q
.venv/bin/python -m py_compile backend/*.py

# frontend
node scripts/check_frontend.mjs
for f in frontend/js/*.js; do node --check "$f"; done

# secrets
.venv/bin/python scripts/scan_secrets.py

# preview
.venv/bin/python scripts/run_preview.py

# detection
.venv/bin/python -c "from backend.vision import vision_status; print(vision_status())"
```

---

*End of specification. Import this document into Claude to continue the work
without reconstructing context.*
