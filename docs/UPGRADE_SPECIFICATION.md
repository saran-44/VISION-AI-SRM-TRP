# SRM TRP Transport — Upgrade Specification

> **Purpose.** This document is the complete, self-contained specification for
> the SRM TRP Transport upgrade. It is written to be imported into Claude (or
> any other engineer/agent) so that the architecture can be analysed, the
> implementation plan followed, and the remaining work continued **without
> reconstructing context**.
>
> It records the requirements, model investigation and limits on provenance,
> implementation, API contracts, deployment topology and outstanding risks.
> The companion [Windows runbook](DEPLOY_WINDOWS.md) contains the detailed,
> ordered operational commands; import both files for the complete context.
>
> **Repository:** `https://github.com/saran-44/frontend`
>
> **Document version:** 3.0 — detection, cameras, golden-glass theme,
> Firebase authentication, Hosting and first-deployment safeguards. Verify the
> current Git branch and commit locally rather than relying on a dated branch
> name in a document. No live cloud deployment is claimed.

---

## Table of contents

1. [Executive summary](#1-executive-summary)
2. [The original request](#2-the-original-request)
3. [Constraints, corrections and non-negotiables](#3-constraints-corrections-and-non-negotiables)
4. [System architecture](#4-system-architecture)
5. [The AI model — provenance investigation](#5-the-ai-model--provenance-investigation)
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

**What was explicitly *not* done, and why.** A related GitHub project is a
Colab notebook with no service API, no licence and no committed weights. The
exact origin of the supplied checkpoint cannot be established from that
repository alone. Rather than invent a third-party endpoint, the upgrade
implements a local detection/OCR integration in `backend/vision.py`.
See [§5](#5-the-ai-model--provenance-investigation).

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
| 6 | Provide **full Git Bash commands and deployment instructions** because the user performs the remote connection/deployment. | [Windows runbook](DEPLOY_WINDOWS.md). |
| 7 | **Search GitHub for the `best.pt` backend.** No repository or API may be fabricated if none is verified. | A related notebook was found; the exact checkpoint provenance remains unverified ([§5](#5-the-ai-model--provenance-investigation)). |
| 8 | **Never commit real credentials, real driver/bus registers, or personal media.** | `.env` and personal-data patterns are ignored; the selective CI scanner is not a full history audit. Existing sensitive history still requires cleanup. |
| 9 | **Rotate exposed MongoDB credentials and purge sensitive Git history** before production use. | Still outstanding — see [§19](#19-outstanding-work-and-known-risks). **This is a production blocker.** |

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
- **Vendored JavaScript dependencies** with licences. Google Fonts and
  Boxicons styles still use external CDNs, and the configured Firebase/Atlas
  topology requires network access; offline operation is not guaranteed.

---

## 5. The AI model — provenance investigation

### 5.1 The checkpoint

| Property | Value |
| --- | --- |
| File | `best.pt` (repository root, tracked in Git) |
| Size | 5,729,139 bytes |
| Architecture | **Ultralytics YOLOv10n** (end-to-end, NMS-free) |
| Saved by | `ultralytics 8.4.20` |
| Classes | `{0: 'red circle', 1: 'sticker'}` — `nc=2` |
| Inference size | 640 px |
| Checkpoint metadata | Identifies an AGPL-3.0 Ultralytics license; rights for the actual model and dataset still require review |

Measured checkpoint metrics:

| Metric | Value |
| --- | --- |
| Precision | 0.84683 |
| Recall | 0.54419 |
| mAP@50 | 0.57818 |
| mAP@50-95 | 0.30302 |
| Fitness | 0.30302 |

> These are checkpoint-reported validation metrics, not measured production
> performance; the validation set and real camera conditions need independent
> review. A `null` detection means "not found", not "no bus". Real-world
> validation and model/data rights are required before production.

### 5.2 The related notebook repository — found, exact weights unverified

The user's instruction was to *search GitHub* for the backend/model
repository, and to **not fabricate one** if none could be verified. A related notebook was found; exact checkpoint provenance remains unverified.

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

The notebook describes a similar YOLOv10n training workflow and produces a
file called `best.pt`, but the weights and training data are not published
there. Matching architecture, settings or filename does **not** establish that
the supplied checkpoint was produced by this exact run. Obtain provenance
and permission from the model owner before production or distribution.

### 5.3 Consequences — and why the backend is local

1. **No hosted inference API was found in that repository.** It contains a
   Colab notebook, not a server or an endpoint contract. This project implements
   its own detection → crop → OCR → logging integration in `backend/vision.py`;
   it does not call an invented third-party API.
2. **`data.yaml` and `license_data.zip` are not committed.** The class names
   `red circle` and `sticker` are known from the supplied checkpoint; the
   dataset and identity of the exact training run remain unverified.
3. **Licensing.** Checkpoint metadata identifies an Ultralytics AGPL-3.0
   license, while the related notebook repository declares no license. Model,
   dataset and software rights must be established separately. Obtain written
   permission and a qualified licence review, or replace the model and its
   dependencies with appropriately licensed alternatives. Do not assume
   retraining alone resolves all software-licence obligations.
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

A related notebook was identified ([§5.2](#52-the-related-notebook-repository--found-exact-weights-unverified)),
not a verified hosted backend or the exact published weights. If the user
provides a different service or authoritative provenance, validate it before
changing the integration. A remote endpoint would require new, reviewed
backend adapter code; `VISION_MODEL_PATH` currently names a local model file,
not a ready-made remote loader. Preserve the detection API contract or update
the frontend deliberately if that contract changes.

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

1. The API key is externalized, so it can be rotated without a code change.
   It is a public Firebase web identifier and is sent to browsers; it is not a
   secret authorization mechanism.
2. App, project and measurement identifiers are present in the deployment
   configuration and must be verified against the real Firebase web app.
3. Analytics is optional. Local deployments can use legacy password sign-in,
   but the checked-in production build disables legacy login and therefore
   depends on Firebase Authentication. The browser also needs an API key.

### 9.3 The vendored SDK

`frontend/vendor/firebase/` holds the *compat* (UMD) builds of `firebase/app`,
`firebase/auth`, `firebase/analytics` and `firebase/firestore` from
`firebase@11.10.0` (Apache-2.0), with the licence and provenance. The app
bundle loads first, then extras are shared per bundle and loaded on demand;
a failed bundle can be retried. Analytics-first pages can load Auth later for
sign-out. The Google popup redirect fallback consumes its return result, but
must be tested with the actual domains and browser storage restrictions.

### 9.4 Hosting configuration

`firebase.json`:

- `public: "frontend"`; protected `frontend/pages/` templates are excluded
  from Hosting uploads because static files are served before rewrites.
- All unmatched paths (including `/api/**` and `/dashboard`) → Cloud Run
  `run.serviceId: srm-trp-transport` in `asia-south1`. Flask handles protected
  page routes; this is **not** an `/index.html` SPA fallback.
- `/assets/**` and `/vendor/**` → one-year immutable cache. The backend sends
  `no-store` on dynamic HTML and API responses.
- Hosting and Flask both allow `camera=(self)` through Permissions-Policy.
- Firebase Hosting forwards the reserved `__session` cookie to Cloud Run.

`.firebaserc` selects `srmtrpai` as the default project. Confirm the actual
Firebase default site and auth domain before deployment; a default site may
need on-demand creation and its ID need not equal the project ID.

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
HS256 JWT in the `__session` HttpOnly, `SameSite=Lax`,
`Secure`-in-production cookie, valid for `JWT_TTL_MINUTES`. The backend does
not persist the exchanged Firebase token. The Firebase SDK manages its own
browser authentication state, accessible to the browser until sign-out.

### 10.4 Verification order

`POST /api/auth/firebase` checks, in order: token shape → RS256 signature →
audience → issuer → expiry → allowed provider → **verified email** → active
access entry (or approved password auto-provisioning, if enabled) → Firebase
UID binding. Only then is the session cookie issued. The production build
requires explicit access entries and disables auto-provisioning.

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

- The `__session` cookie is forwarded by Hosting to Cloud Run.
- No CORS pre-flight is needed in the same-origin hosted topology.
- `CORS_ALLOWED_ORIGINS` is only needed when a different origin directly
  calls the backend; this frontend currently uses relative URLs, so such a
  topology also needs a reviewed reverse proxy or client changes.

The backend serves the frontend itself when it is not behind Firebase
Hosting, so the same codebase runs in both topologies:

```bash
# single-origin (Flask serves the console)
.venv/bin/gunicorn --bind 0.0.0.0:8080 "backend.app:create_app()"

# Same browser origin via Firebase Hosting + Cloud Run — see the runbook.
firebase deploy --only hosting --project=srmtrpai
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
| `FIREBASE_AUTH_DOMAIN` | empty | Auth domain; confirm against the actual Firebase app/site. |
| `FIREBASE_PROJECT_ID` | empty | Project ID; `srmtrpai` in the checked-in build. |
| `FIREBASE_STORAGE_BUCKET` | empty | Storage bucket. |
| `FIREBASE_MESSAGING_SENDER_ID` | empty | Messaging sender ID. |
| `FIREBASE_APP_ID` | empty | Web app ID; required for the browser configuration. |
| `FIREBASE_MEASUREMENT_ID` | empty | Analytics measurement ID. |
| `FIREBASE_AUTH_ENABLED` | `true` | Master switch for Firebase sign-in (effective only when a project id is set). |
| `FIREBASE_ALLOWED_PROVIDERS` | `password,google.com` | Which Firebase providers are accepted. |
| `FIREBASE_AUTO_PROVISION` | `true` | Auto-create the access record only for a verified password identity with the administrator-set approval claim. |
| `FIREBASE_DEFAULT_ROLE` | `transport_office` | The role given to an auto-provisioned account. |
| `LEGACY_PASSWORD_LOGIN_ENABLED` | `true` | Keep the local MongoDB password login as a break-glass path. |

`.env.example` documents all of them. The checked-in Cloud Build settings
explicitly set `FIREBASE_AUTO_PROVISION=false` and
`LEGACY_PASSWORD_LOGIN_ENABLED=false`, overriding the application defaults.

---

## 14. Deployment

### 14.1 Topology

```text
Browser → Firebase Hosting (static login/assets; unmatched paths → Cloud Run)
                                      ↓
         Cloud Run srm-trp-transport, asia-south1 (Flask + best.pt)
                                      ↓ all outbound traffic
         Direct VPC → Cloud NAT with reserved public IP → MongoDB Atlas
```

`frontend/pages/` is not uploaded to Hosting; Flask enforces page roles. The
session cookie is `__session`, the cookie Hosting forwards. The service also
needs outbound HTTPS for Firebase's public signing keys. The static NAT IP and
the operator workstation IP must both be allowed by Atlas before deploying.

### 14.2 Ordered first deployment

Use the complete **[Windows Git Bash runbook](DEPLOY_WINDOWS.md)**. It covers
safe updating of the existing clone, installation before login, actual Firebase
app/default-site discovery, Firebase account creation and verified-email
onboarding, Atlas credential rotation and scoped access, IAM, Direct VPC,
Cloud NAT, Secret Manager, Cloud Build, Hosting, live verification and
rollback. These operations have not been performed from this workspace and may
incur charges. Do not run a shortened `gcloud run deploy` command that omits
networking or the restrictive authentication settings.

The checked-in `deploy/cloudbuild.yaml` builds and pushes the container with
`BUILD_ID`, then deploys using dedicated build/runtime service accounts,
all-traffic Direct VPC egress, a startup probe, explicit Firebase providers,
disabled self-provisioning and disabled local-password login. Confirm the real
project and web app settings and inspect `gcloud meta list-files-for-upload`
before submitting it. The 120-second MongoDB retry window is a target: SRV/TXT
DNS during client construction is separately timed and can exceed it under
resolver/OS delays. The live deployment must be tested.

### 14.3 Other hosts and platform limits

`deploy/Dockerfile` bundles `backend/`, `frontend/`, `best.pt` and the optional
vision dependencies. A different Docker host needs its own TLS, secrets,
network access, identity and proxy configuration. Do not publish protected
page templates as static assets.

Firebase Hosting limits dynamic requests to 60 seconds even if Cloud Run's
request timeout is longer. Cold starts can exceed the edge timeout; real
camera/SSE streams and detection operations must be tested for interruption
or moved to an appropriate streaming/processing architecture.

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

Run the suite on the checked-out revision; mock-based tests do not verify live cloud services.

### 15.2 Frontend

```bash
node scripts/check_frontend.mjs
node scripts/check_auth_flow.mjs
node scripts/check_firebase_loader.mjs
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

The complete, ordered commands are in **[DEPLOY_WINDOWS.md](DEPLOY_WINDOWS.md)**.
Do not clone on top of an existing `~/frontend`, overwrite `.env`, or run a
hard reset to repair it. Inspect `git status` and back up or commit valuable
work before switching to the local `main` and using `git pull --ff-only`.
Wait until the Hosting/network fixes are actually merged before pulling and
deploying them. Install Node, Firebase CLI, Google Cloud CLI and Python
requirements before the login and deployment steps.

### 17.1 Credential rotation and history purge

Rotate **both** exposed Atlas credentials first and verify the old passwords
no longer work. Reset the password shared in chat if it was configured. Then
coordinate a sensitive-history rewrite with the repository owner, all
collaborators and GitHub Support, following
[GitHub's sensitive-data removal guidance](https://docs.github.com/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).
The original credential was found in historical `app.py`; removing only an
untracked `.env` would not fix that exposure. A mirror force-push or hard
reset is destructive and is deliberately **not** a copy-paste recovery step.
A rewrite also does not erase forks, PR references or caches automatically.

Review existing Firebase users, MongoDB access entries and UID bindings, and
rotate the JWT signing key/retire old reachable revisions to invalidate old
sessions. Resolve the model licence and test real Firebase/Atlas/Hosting
connections before production. None of these operations has been verified.

---

## 18. Repository map

```
frontend/                         repository root
├── best.pt                       YOLOv10n checkpoint — provenance/licence pending
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
| 1 | **Rotate exposed MongoDB credentials and purge sensitive history** | An earlier credential and personal data remain in Git history. | Rotate and verify both credentials first; coordinate the history rewrite and cleanup with the repository owner and GitHub Support. |
| 2 | **Resolve model and software licensing** | Checkpoint metadata cites AGPL-3.0; the related notebook declares no license and exact model/data provenance is unverified. | Obtain written rights and qualified licence review, or replace the model and dependencies with appropriately licensed alternatives. |
| 3 | **TLS in front of the app** | The browser camera API requires a secure context. | Terminate TLS at Cloud Run / a load balancer / a reverse proxy. |

#### Item 1 in detail — the leaked credential

An old connection string was committed in the root `app.py` and remains in
Git history. A replacement credential or a different cluster does not by
itself prove that the old database user was disabled. An Atlas administrator
must verify that the old credential has been revoked or rotated, then purge
the sensitive history as described in
[§17.1](#171-credential-rotation-and-history-purge).

Treat any credential shared in chat, logs or other unintended places as
exposed and rotate it separately. Store replacements in a secrets vault or
Secret Manager rather than committing them or sharing them in chat.

### 18.2 Recommended improvements

| # | Item | Detail |
| --- | --- | --- |
| 4 | **Validate or re-train the model** | Checkpoint-reported recall is 0.544 and mAP@50-95 is 0.303 on an unverified validation set. Measure real-world performance and resolve data/software rights. |
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
- **Analytics are optional and best-effort.** Firebase Authentication is not
  optional for the checked-in production build; an SDK or Auth outage can
  prevent sign-in or Firebase sign-out and must be tested live.

---

## 20. Appendix — verified environment facts

These are historical observations from an earlier test environment, not a
current production readiness assessment. Timings, package versions and test
counts vary by machine and revision; no live cloud integration was verified.

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
| Related notebook | `814725105014-debug/SRM-TRP-TRANSPORT-AI` — 1 commit, **no licence**, weights not committed; exact checkpoint provenance unverified |
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
