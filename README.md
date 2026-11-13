# SRM TRP Transport — Campus Bus Gate Monitoring

A web application for the SRM Transport department that turns camera/OCR gate
detections into live, auditable bus movement records: how many buses are inside
the campus right now, who entered today, which vehicles looked suspicious, and
a searchable history of drivers, buses and changes.

> **Status:** the application is fully implemented and tested in this repository.
> The bus-sticker detector (`best.pt` + `backend/vision.py`), the browser
> webcam and the NVR/DVR camera hooks are all integrated. Two things must
> still be supplied by the operator: the **real camera stream URLs** and the
> **Firebase API key** (both are read from the environment). See
> [Not included](#not-included) and `TRANSPORT_PROJECT_STATUS.md`.

---

## Contents

- [What it does](#what-it-does)
- [Architecture](#architecture)
- [Roles](#roles)
- [Quick start](#quick-start)
- [Environment variables](#environment-variables)
- [Demo data](#demo-data)
- [Detection / OCR integration](#detection--ocr-integration)
- [API reference](#api-reference)
- [Tests and CI](#tests-and-ci)
- [Deployment](#deployment)
- [Security notes](#security-notes)
- [Not included](#not-included)
- [Repository layout](#repository-layout)

---

## What it does

- **Live dashboard** — entries today, buses currently inside, flagged vehicles,
  per-hour / per-gate / per-bus charts, camera tiles and the most recent
  detection. All numbers come from the API; nothing is hard-coded.
- **Live logs** — every gate event with filters (date, bus, gate, direction,
  flagged) and pagination, plus CSV and Excel export.
- **Analytics** — hourly, per-gate and per-bus movement charts over a
  selectable window.
- **Drivers and buses** — searchable records; the transport office can add,
  edit and delete them, and every change is written to the audit log.
- **Audit log** — who changed what, when, from which IP address.
- **Camera tiles** — HLS or MJPEG streams when a URL is configured; otherwise the
  tile is explicitly labelled **“Demo footage”**.

## Architecture

```
browser ──HTTP(S)──▶ Flask API (backend/)  ──▶ MongoDB
 detection device ──POST /api/events (device key)──▶
```

| Layer | Location | Notes |
| --- | --- | --- |
| API + page serving | `backend/` | Flask 3 application factory, JWT/cookie auth, RBAC, pydantic validation, rate limiting, security headers |
| Frontend | `frontend/` | Vanilla ES modules, no build step, one shared layout module, vendored Chart.js / hls.js / SheetJS |
| Data | MongoDB | Indexes are created on startup (`backend/db.py`) |

Detailed module-by-module notes live in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Roles

| Role | Can read | Can write |
| --- | --- | --- |
| `head_admin` | dashboard, logs, analytics, drivers, buses, audit log, exports | – |
| `transport_office` | drivers, buses | drivers and buses (create / update / delete) |
| detection device | – | posts events to `POST /api/events` with a device API key |

Roles are enforced on the server for every page and every endpoint.

## Quick start

Requirements: Python 3.11+, Node 18+ (only for the frontend checks), MongoDB 6+
(or `mongomock://` for a local, in-memory run).

```bash
# 1. install dependencies
python3 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt

# 2. create your environment file (never commit it)
cp .env.example .env
$EDITOR .env          # set MONGO_URI, JWT_SECRET, DEVICE_API_KEYS

# 3. run the app
python -m backend.wsgi            # http://127.0.0.1:5000
```

Then open <http://127.0.0.1:5000/> and sign in with an account from MongoDB.

To create your first accounts, insert them directly (passwords are hashed with
Argon2id):

```python
from backend.auth import hash_password
from backend.db import get_database
from backend.config import Config

db = get_database(Config.from_env())
db.users.insert_one({
    "email": "head.admin@example.edu",
    "password_hash": hash_password("a-long-passphrase"),
    "role": "head_admin",
    "active": True,
})
```

Or seed the fake demo dataset (see [Demo data](#demo-data)).

## Environment variables

All configuration comes from the environment (a local `.env` file is loaded
automatically). `.env.example` lists every variable with safe placeholder
values; `.env` is git-ignored.

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `ENVIRONMENT` | yes | `development` | `development` / `testing` / `production` |
| `MONGO_URI` | yes | – | MongoDB connection string (`mongodb://`, `mongodb+srv://`, `mongomock://`) |
| `MONGO_DB_NAME` | no | database from URI | Database name |
| `JWT_SECRET` | yes | – | HS256 signing key; ≥ 32 characters in production |
| `JWT_TTL_MINUTES` | no | `15` | Access-token lifetime (1–60) |
| `COOKIE_SECURE` | no | `true` in production | `Secure` flag on the session cookie |
| `CORS_ALLOWED_ORIGINS` | no | empty | Comma-separated **explicit** origins; wildcards are rejected |
| `DEVICE_API_KEYS` | for ingestion | empty | Comma-separated keys accepted by `POST /api/events` |
| `LOGIN_RATE_LIMIT` | no | `5 per minute;20 per hour` | Flask-Limiter rule for `/api/auth/login` |
| `RATELIMIT_ENABLED` | no | `true` | Toggle login throttling |
| `RATELIMIT_STORAGE_URI` | no | `memory://` | Shared store (e.g. `redis://…`) when running multiple workers |
| `APP_TIMEZONE` | no | `Asia/Kolkata` | Timezone for “today” and chart buckets |
| `OCR_CONFIDENCE_THRESHOLD` | no | `0.75` | Below this, a vehicle is flagged as low confidence |
| `OVERSTAY_HOURS` | no | `12` | Hours inside before a bus is flagged as overstaying |
| `CAMERA_STREAM_URLS` | no | empty | JSON map of camera → `{type, url, label}` (`hls` or `mjpeg`) |
| `FLASK_DEBUG` | no | `false` | Debug mode; ignored outside `development`, rejected in production |
| `HOST` / `PORT` | no | `0.0.0.0` / `5000` | Dev server bind address |
| `ALLOW_DEMO_SEED`, `SEED_*` | no | – | Demo seeding switch and passwords (see below) |

Generate secrets with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Demo data

The seed script inserts **clearly fake** records (no real names, plates or
contact numbers). It refuses to run unless it is explicitly enabled and both
passwords are supplied through the environment — nothing is printed.

```bash
export ALLOW_DEMO_SEED=true
export SEED_HEAD_ADMIN_EMAIL=head.admin@example.invalid
export SEED_HEAD_ADMIN_PASSWORD='choose-a-demo-password'
export SEED_TRANSPORT_EMAIL=transport.office@example.invalid
export SEED_TRANSPORT_PASSWORD='choose-a-demo-password'
python -m backend.seed_demo
```

It creates 4 buses, 3 drivers, 8 events (including one unregistered plate and
one low-confidence read) and 2 users. Demo records are tagged `demo: true` and
can be removed with `db.buses.deleteMany({demo: true})` and friends.

## Detection / OCR integration

The bus-sticker detector **is** part of this repository. `best.pt` (Ultralytics
YOLOv10n, classes `red circle` and `sticker`) is loaded by `backend/vision.py`,
which crops each detected sticker, runs OCR over the crop and normalises the
result into a registration number.

```bash
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/pip install -r backend/requirements-vision.txt
```

> On a CPU-only host, install Torch from the CPU index — the default PyPI
> wheel is the ~3 GB CUDA build:
>
> ```bash
> pip install torch==2.9.1 torchvision==0.24.1 \
>     --index-url https://download.pytorch.org/whl/cpu
> ```

Scan a frame (device key **or** an administrator session):

```http
POST /api/detection/scan
X-Device-Key: <device key>
Content-Type: multipart/form-data

image=@frame.jpg
```

```json
{
  "detection": {
    "candidates": [{"bus_number": "TN12AB1234", "raw_text": "TN 12 AB 1234",
                    "confidence": 0.94, "bbox": [412, 288, 596, 352]}],
    "model": "best.pt", "inference_ms": 118
  },
  "bus_number": "TN12AB1234", "confidence": 0.94
}
```

`GET /api/detection/status` reports whether the stack can run right now.

A detection is a *reading*; to record a *movement*, post it as an event:

```http
POST /api/events
Content-Type: application/json
X-Device-Key: <device key>

{"bus_number":"BUS-001","direction":"IN","gate":"Gate 1",
 "camera_id":"gate-1-entry","confidence":0.96,"timestamp":"2026-11-12T09:15:00Z"}
```

A reference client is included:

```bash
export TRANSPORT_API_URL=https://transport.example.edu
export DEVICE_API_KEY='<key listed in DEVICE_API_KEYS>'
python -m backend.detection_client \
  --bus-number BUS-001 --direction IN --gate "Gate 1" \
  --camera-id gate-1-entry --confidence 0.96
```

The model investigation (a related public notebook was found, but the exact
checkpoint provenance remains unverified), the full
contract, the flag rules and the OCR engine options are in
[`docs/DETECTION.md`](docs/DETECTION.md) and
[`docs/EVENT_CONTRACT.md`](docs/EVENT_CONTRACT.md).

**Flag rules** (computed server-side, shown with their reason in the UI):

| Reason | Rule |
| --- | --- |
| `unregistered_plate` | The plate is not in the bus register. |
| `low_ocr_confidence` | OCR confidence is below `OCR_CONFIDENCE_THRESHOLD`. |
| `long_overstay` | The bus's last unmatched entry is older than `OVERSTAY_HOURS`. |

“Currently inside” is derived from the latest event per bus: a bus whose most
recent event is `IN` is inside.

## Cameras

Three sources are supported, all from `frontend/js/cameras.js`:

| Source | How it reaches the browser |
| --- | --- |
| **Operator webcam** | `getUserMedia` — works today, no hardware needed. A **Scan plate** button posts the frame to the detection API. |
| **HLS** | An NVR/DVR or a MediaMTX/FFmpeg gateway, played with the vendored `hls.js`. |
| **MJPEG** | An NVR/DVR endpoint, or the backend proxy at `GET /api/stream/<camera_id>`. |

> **Raw RTSP cannot be loaded by a browser.** An RTSP camera must be bridged
> by a gateway/transcoder (MediaMTX, FFmpeg, or the NVR's own HLS output) and
> then consumed as HLS or MJPEG. See [`docs/CAMERAS.md`](docs/CAMERAS.md).

The browser camera API requires a **secure context** (`https://` or
`http://localhost`).

## Firebase

Firebase Hosting serves the static login/assets and rewrites unmatched paths,
including protected pages and `/api/**`, to Cloud Run. Protected templates are
not uploaded to Hosting. Analytics is optional; the production build requires
Firebase Authentication and an active MongoDB access entry. The browser's
Firebase configuration is served by `GET /api/config/firebase`; the public web
API key is externalized from the repository.

See [`docs/FIREBASE.md`](docs/FIREBASE.md).

## Authentication

Sign-in is handled by **Firebase Authentication** — email/password and Google —
with access restricted to a list of authorised email addresses.

Two independent gates must both pass:

1. **Firebase** decides whether the credential is valid. Firebase password
   accounts may also be created through client sign-up, so a valid token is
   not proof of administrator approval.
2. **The backend** requires a verified email and an active access-list entry.
   An unknown password user can be auto-provisioned only with an
   administrator-set Firebase approval claim; unknown Google users are denied.

The browser exchanges the Firebase ID token for the application's own
short-lived HttpOnly session cookie at `POST /api/auth/firebase`. The backend
verifies the token against Google's **public** signing keys and does not
persist it. No service-account private key is needed for that verification;
setting approval claims is a separate trusted-administrator operation.

Manage the access list with the bundled CLI:

```bash
python -m backend.manage_access list
python -m backend.manage_access add transport.office@srmtrp.edu.in
python -m backend.manage_access set-role principal@srmtrp.edu.in head_admin
python -m backend.manage_access deactivate transport.office@srmtrp.edu.in
```

The Firebase console setup, the auto-provisioning rules and the reasoning
behind **not** adding Supabase are in
[`docs/AUTHENTICATION.md`](docs/AUTHENTICATION.md).

## API reference

All endpoints are same-origin JSON APIs. Authentication is a short-lived JWT in
an HttpOnly, SameSite=Lax cookie (`__session`, the name Firebase Hosting forwards).

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/health` | – | Liveness probe |
| `GET` | `/api/auth/config` | – | Which sign-in methods this deployment offers |
| `POST` | `/api/auth/firebase` | – | Exchange a Firebase ID token for a session cookie |
| `POST` | `/api/auth/login` | – | Sign in with a local account (rate limited) |
| `GET` | `/api/auth/me` | session | Current user |
| `POST` | `/api/auth/logout` | session | Sign out (audited) |
| `GET` | `/api/config` | head_admin | Camera tiles, flag labels, thresholds |
| `GET` | `/api/config/firebase` | – | Public Firebase web configuration (empty when unconfigured) |
| `GET` | `/api/detection/status` | head_admin | Detector/OCR availability and model classes |
| `POST` | `/api/detection/scan` | device key or head_admin | Detect a sticker in an image and read its number |
| `GET` | `/api/stream/<camera_id>` | head_admin | MJPEG proxy for a configured camera |
| `GET` | `/api/stats` | head_admin | Live counters, inside list, flagged counts |
| `GET` | `/api/analytics` | head_admin | Hourly / gate / bus series |
| `GET` | `/api/events` | head_admin | Event list with filters + pagination |
| `POST` | `/api/events` | device key | Event ingestion |
| `GET` | `/api/events/<id>` | head_admin | One event |
| `GET` | `/api/export/events.csv` | head_admin | CSV export |
| `GET` | `/api/export/events.xlsx` | head_admin | Excel export |
| `GET` | `/api/stream` | head_admin | Server-sent events (live refresh) |
| `GET`/`POST`/`PUT`/`DELETE` | `/api/drivers`, `/api/drivers/<id>` | head_admin (read), transport_office (write) | Driver CRUD |
| `GET`/`POST`/`PUT`/`DELETE` | `/api/buses`, `/api/buses/<id>` | head_admin (read), transport_office (write) | Bus CRUD |
| `GET` | `/api/search?q=` | head_admin, transport_office | Driver + bus search |
| `GET` | `/api/audit` | head_admin | Audit entries |

## Tests and CI

```bash
python -m pytest                    # backend tests (mock database, no live cloud)
node scripts/check_frontend.mjs      # imports, assets and element references
node scripts/check_auth_flow.mjs     # mocked sign-out and Google redirect
node scripts/check_firebase_loader.mjs  # lazy SDK loading and retry
python scripts/scan_secrets.py       # selective high-confidence pattern scan
```

The test suite uses `mongomock://`, so no database or secrets are required.
GitHub Actions (`.github/workflows/ci.yml`) runs these checks on pushes and
pull requests. The selective secret scan skips documents, tests and Git
history; passing it is not proof that the repository or history is clean.

## Deployment

> Deploying from Windows with Git Bash? Follow
> [`docs/DEPLOY_WINDOWS.md`](docs/DEPLOY_WINDOWS.md) — the full chain
> (toolchain install → log in → Cloud Run → Firebase Hosting) with
> Windows-specific notes.

1. **Provision MongoDB** — a dedicated database with a least-privilege user.
   Indexes are created automatically on startup.
2. **Set the environment** — at minimum `ENVIRONMENT=production`, `MONGO_URI`,
   `JWT_SECRET` (≥ 32 chars), `DEVICE_API_KEYS`, `COOKIE_SECURE=true` and the
   verified Firebase configuration. Configure `CORS_ALLOWED_ORIGINS` only for
   explicit cross-origin callers. Use your platform's secret manager and never
   commit credentials. The runbook configures restrictive Firebase defaults
   and static Cloud NAT egress before the first Cloud Run deployment.
3. **Serve with a WSGI server** behind TLS:

   ```bash
   gunicorn --workers 3 --bind 0.0.0.0:8000 --timeout 180 backend.wsgi:app
   ```

   Use a shared `RATELIMIT_STORAGE_URI` (for example Redis) when running more
   than one worker, otherwise each worker keeps its own login counter.
4. **Proxy** — terminate TLS in front of gunicorn and forward
   `X-Forwarded-Proto`; set `PREFERRED_URL_SCHEME=https` behaviour by running
   with `ENVIRONMENT=production`. Server-sent events need buffering disabled
   (`proxy_buffering off;` for nginx).
5. **Static files** — `frontend/` is served by the Flask app itself
   (`/assets`, `/js`, `/vendor`), so no separate web server is required. For
   higher throughput, serve `/assets`, `/js` and `/vendor` from nginx and proxy
   only `/api` and the page routes to gunicorn.
6. **Create accounts** and seed or import buses, then hand out device keys to
   the detection service.

## Security notes

- `MONGO_URI`, `JWT_SECRET` and `DEVICE_API_KEYS` are read from the
  environment; `.env` is git-ignored and `.env.example` contains placeholders.
  An earlier credential remains in Git history: rotate exposed credentials,
  verify revocation and coordinate a sensitive-history purge before production.
- Passwords are hashed with **Argon2id**; access tokens are short-lived HS256
  JWTs delivered in an HttpOnly cookie.
- Every request body and query string is validated with pydantic; unknown
  fields are rejected; control characters and markup in text fields are
  refused.
- The frontend never writes API, CSV or event text into `innerHTML` — all
  dynamic content is created with DOM APIs.
- Responses carry `Content-Security-Policy`, `X-Content-Type-Options`,
  `Referrer-Policy` and `Permissions-Policy` headers.
- Login attempts are rate limited; administrative changes are audited with
  actor, role, timestamp and IP address.

See [`docs/PRIVACY.md`](docs/PRIVACY.md) for who can see driver and vehicle
data.

## Not included

- **The Firebase API key.** It is read from the environment
  (`FIREBASE_API_KEY`) and deliberately not committed. See
  [`docs/FIREBASE.md`](docs/FIREBASE.md).
- **Real camera streams.** Tiles show “Demo footage” until `CAMERA_STREAM_URLS`
  is configured with HLS or MJPEG URLs.
- **Real bus/driver register data.** Only demo data is seeded; the register
  contains personal data and is never committed.
- **Confirmed model provenance and rights.** Checkpoint metadata cites an
  Ultralytics AGPL-3.0 licence; the related notebook declares no licence and
  does not publish the weights. Obtain written model/dataset rights and a
  software-licence review before production or distribution. See
  [`docs/DETECTION.md`](docs/DETECTION.md).

## Repository layout

```
backend/            Flask API, auth, validation, services, vision, seed + device client
  tests/            pytest suite (auth, validation, events, detection, exports)
frontend/           Static frontend (no build step)
  assets/           styles.css, theme.css, login.css, the official crest + wordmark
  js/               ES modules (api, ui, layout, cameras, firebase, charts, tables, pages)
  pages/            dashboard, logs, analytics, drivers, buses, driver-details, audit, manage
  vendor/           Chart.js, hls.js, SheetJS, Firebase SDK (+ licences)
deploy/             Dockerfile and Cloud Build pipeline
docs/               upgrade specification, detection, cameras, Firebase, architecture,
                    event contract, privacy note
scripts/            frontend checks and secret scanner
.github/workflows/  CI
```
