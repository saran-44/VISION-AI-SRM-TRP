# SRM TRP Transport — Campus Bus Gate Monitoring

A web application for the SRM Transport department that turns camera/OCR gate
detections into live, auditable bus movement records: how many buses are inside
the campus right now, who entered today, which vehicles looked suspicious, and
a searchable history of drivers, buses and changes.

> **Status:** the application is fully implemented and tested in this repository.
> Two things are still missing from *this* repo and must be supplied by the
> operator: the OCR/detection service (it lives in a separate GitHub repository
> whose URL has not been provided yet) and the real camera stream URLs. See
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

The OCR/ANPR service is **not** part of this repository. It posts normalized
events to this API:

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

The full contract, flag rules and wiring instructions are in
[`docs/EVENT_CONTRACT.md`](docs/EVENT_CONTRACT.md).

**Flag rules** (computed server-side, shown with their reason in the UI):

| Reason | Rule |
| --- | --- |
| `unregistered_plate` | The plate is not in the bus register. |
| `low_ocr_confidence` | OCR confidence is below `OCR_CONFIDENCE_THRESHOLD`. |
| `long_overstay` | The bus's last unmatched entry is older than `OVERSTAY_HOURS`. |

“Currently inside” is derived from the latest event per bus: a bus whose most
recent event is `IN` is inside.

## API reference

All endpoints are same-origin JSON APIs. Authentication is a short-lived JWT in
an HttpOnly, SameSite=Lax cookie (`transport_token`).

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/health` | – | Liveness probe |
| `POST` | `/api/auth/login` | – | Sign in (rate limited) |
| `GET` | `/api/auth/me` | session | Current user |
| `POST` | `/api/auth/logout` | session | Sign out (audited) |
| `GET` | `/api/config` | head_admin | Camera tiles, flag labels, thresholds |
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
python -m pytest              # 60 backend tests (auth, roles, validation, ingestion, exports, audit)
node scripts/check_frontend.mjs  # frontend imports, assets and element references
python scripts/scan_secrets.py   # fails if a credential pattern is committed
```

The test suite uses `mongomock://`, so no database or secrets are required.
GitHub Actions (`.github/workflows/ci.yml`) runs all three checks on every push
and pull request.

## Deployment

1. **Provision MongoDB** — a dedicated database with a least-privilege user.
   Indexes are created automatically on startup.
2. **Set the environment** — at minimum `ENVIRONMENT=production`, `MONGO_URI`,
   `JWT_SECRET` (≥ 32 chars), `DEVICE_API_KEYS`, `CORS_ALLOWED_ORIGINS` and
   `COOKIE_SECURE=true`. Keep them in your platform's secret manager, never in
   the repository.
3. **Serve with a WSGI server** behind TLS:

   ```bash
   gunicorn --workers 3 --bind 0.0.0.0:8000 --timeout 120 backend.wsgi:app
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

- No credentials are stored in the repository. `MONGO_URI`, `JWT_SECRET`,
  `DEVICE_API_KEYS` and the CORS allowlist are read from the environment;
  `.env` is git-ignored and `.env.example` contains placeholders only.
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

- **The OCR / detection service.** It lives in a separate GitHub repository
  whose URL has not been provided. This repository defines the event contract
  and ships a client; it does not contain any detector code.
- **Official SRM TRP logo artwork.** The repository ships a locally drawn SVG
  wordmark (`frontend/assets/logo.svg`). Replace it with the approved official
  asset when available — do not commit personal photographs.
- **Real camera streams.** Tiles show “Demo footage” until `CAMERA_STREAM_URLS`
  is configured with HLS or MJPEG URLs.

## Repository layout

```
backend/            Flask API, auth, validation, services, seed + device client
  tests/            pytest suite (auth, validation, event ingestion, exports)
frontend/           Static frontend (no build step)
  assets/           styles.css, login.css, logo.svg, favicon.svg
  js/               ES modules (api, ui, layout, charts, tables, streams, pages)
  pages/            dashboard, logs, analytics, drivers, buses, driver-details, audit, manage
  vendor/           Chart.js, hls.js, SheetJS (+ licences)
docs/               architecture, event contract, privacy note
scripts/            frontend checks and secret scanner
.github/workflows/  CI
```
