# SRM TRP Transport — Upgrade Status Report

**Repository:** `saran-44/frontend` (imported from `hemanathanmd01/Clg-bus-project`)
**Branch:** `arena/1c01d46f-frontend` (based on `main` @ `82f40e6`)
**Report date:** 2026-11-12
**Specification:** [`docs/UPGRADE_SPECIFICATION.md`](docs/UPGRADE_SPECIFICATION.md)

> **Update — round 2 (detection, cameras, Firebase, golden glass theme).**
> The two items that were *PARTIAL* in the first round are now **DONE**:
>
> - **Detection is integrated.** The `best.pt` source repository was located
>   and verified on GitHub
>   ([`814725105014-debug/SRM-TRP-TRANSPORT-AI`](https://github.com/814725105014-debug/SRM-TRP-TRANSPORT-AI),
>   1 commit, no licence, weights not committed). Because that project is a
>   Colab notebook with **no service API**, the pipeline was re-implemented
>   locally in `backend/vision.py` and exposed at `POST /api/detection/scan`.
>   Provenance and licence details are in
>   [`docs/DETECTION.md`](docs/DETECTION.md).
> - **Cameras are integrated.** The browser webcam works today via
>   `getUserMedia`; NVR/DVR feeds are supported through HLS and MJPEG; raw
>   RTSP is documented as requiring a gateway/transcoder and is never loaded
>   directly by the browser. See [`docs/CAMERAS.md`](docs/CAMERAS.md).
>
> Additionally added in this round: **Firebase** (`srmtrpai`) for Hosting and
> Analytics ([`docs/FIREBASE.md`](docs/FIREBASE.md)), a **golden glass light
> theme** using the **official SRM TRP crest**, a container/Cloud Run
> deployment pipeline, and 18 new backend tests (**78 total**).

The original single-file Flask demo (hard-coded credentials, CSV polling,
copy-pasted HTML pages, personal sample data) has been replaced by a
`/backend` + `/frontend` application with real authentication, a documented
REST API, live data, validation, audit logging, tests and CI. The original
look and feel was kept: the upstream `style.css` was carried over verbatim
(same blue primary `#2563eb`, Inter font, card layout, dark theme, sidebar) and
extended rather than redesigned — and is now re-skinned by the golden glass
theme layer.

**Summary: 10 of the 10 requested work items are DONE.** The remaining work
is operational and needs the operator: credential rotation + history purge,
the real camera stream URLs, the Firebase API key, and a licence position on
`best.pt`.

---

## 1. Scoreboard

| # | Work item | Status | Notes |
| --- | --- | --- | --- |
| 1 | Security first (env secrets, CORS allowlist, validation, rate limit, indexes, no `innerHTML`) | **DONE** | Credential rotation + history purge are listed under *Your actions* |
| 2 | Real auth (Mongo users, Argon2, short-lived JWT, roles, page protection, logout, audit) | **DONE** | Enforced server-side on every page and endpoint |
| 3 | REST API (login, driver/bus CRUD, events, stats, CSV + Excel export) | **DONE** | All routes implemented and exercised by tests and a live smoke test |
| 4 | Live data (SSE + polling fallback, "Currently Inside", flag rules with reasons) | **DONE** | Rules: unregistered plate, low OCR confidence, long overstay |
| 5 | Detection integration (event contract + device client) | **DONE** | **Round 2:** `backend/vision.py` runs `best.pt` (YOLOv10n) + OCR and serves `POST /api/detection/scan`. Source repository verified. |
| 6 | Dashboard (no hard-coded numbers, camera tiles, charts, filters, API search, states, a11y, mobile) | **DONE** | **Round 2:** browser-webcam tile with a working "Scan plate" action. |
| 7 | Data & privacy (remove personal data/CSVs/videos/photos/PDF, seed script, privacy note) | **DONE** | Removed from the working tree and git-ignored; the old files remain in Git history |
| 8 | Structure (`/backend` + `/frontend`, ES modules, shared layout, pinned deps incl. SheetJS) | **DONE** | 19 ES modules, one shared layout, 4 vendored libraries pinned with licences |
| 9 | Quality (README, tests, GitHub Action) | **DONE** | 78 pytest tests + frontend checks + secret scan, wired into CI |
| 10 | Status report | **DONE** | This document |
| 11 | **Golden glass light theme + official crest** | **DONE** | **Round 2:** `frontend/assets/theme.css`; the supplied crest is now the logo. |
| 12 | **Firebase (Hosting + Analytics) on `srmtrpai`** | **DONE** | **Round 2:** `firebase.json`, `.firebaserc`, lazy SDK, backend-served config. |
| 13 | **NVR/DVR camera support (HLS / MJPEG) + RTSP gateway rule** | **DONE** | **Round 2:** `frontend/js/cameras.js`, `GET /api/stream/<camera_id>`, documented in `docs/CAMERAS.md`. |
| 14 | **Deployment configuration + Git/Git Bash commands** | **DONE** | **Round 2:** `deploy/Dockerfile`, `deploy/cloudbuild.yaml`, and §16 of the specification. |

---

## 2. What was done, item by item

### 1. Security — DONE

- The credential-bearing `app.py` was removed. `MONGO_URI`, `JWT_SECRET`,
  `DEVICE_API_KEYS`, `CORS_ALLOWED_ORIGINS` and every other setting now come from
  the environment (`backend/config.py`).
- `.env.example` documents every variable with placeholders; `.env` is
  git-ignored.
- Debug is only honoured when `ENVIRONMENT=development` and is explicitly
  rejected in production (`Config.validate`).
- CORS is restricted to an explicit allowlist; `*` and non-http(s) origins raise
  a startup error (`_parse_origins`).
- Every request body and query string is validated with pydantic v2 strict
  models (`backend/schemas.py`): unknown fields are rejected, control characters
  and markup in text fields are refused, bus numbers are normalised, and event
  timestamps more than five minutes in the future are rejected.
- Login is rate limited (`5 per minute; 20 per hour` by default, shared store
  configurable through `RATELIMIT_STORAGE_URI`).
- MongoDB indexes are created on startup: unique `users.email`, unique
  `buses.bus_number`, driver name/bus indexes, five event indexes and two
  audit indexes (`backend/db.py`).
- The frontend never inserts API, CSV or event text into `innerHTML`; all
  dynamic content is built with DOM APIs (`frontend/js/ui.js`, `tables.js`).
- Security headers on every response: CSP, `X-Content-Type-Options`,
  `Referrer-Policy`, `Permissions-Policy` (+ HSTS when served over TLS in
  production).
- `scripts/scan_secrets.py` fails the build if a credential pattern is
  committed; it runs in CI.

### 2. Real authentication — DONE

- Users live in MongoDB; passwords are hashed with **Argon2id**
  (`backend/auth.py`), never stored or logged in plain text.
- Login issues a **short-lived HS256 JWT** (default 15 min, 1–60 min allowed)
  delivered in an `HttpOnly`, `SameSite=Lax` cookie (`Secure` in production).
  The token carries `sub`, `email`, `role`, `jti`, `aud`, `iss`.
- Roles are enforced on the server: `head_admin` reads dashboard / logs /
  analytics / drivers / buses / audit; `transport_office` reads and writes
  drivers and buses. Every page route and every API route is protected
  (`require_roles`, `require_page_roles`); an unauthenticated page request
  redirects to the login screen, an unauthenticated API call returns 401.
- Logout clears the cookie and is audited.
- Every administrative change writes an audit entry with actor, role, action,
  collection, record id, before/after snapshots, IP and user agent; the audit
  log is visible to `head_admin` only.

### 3. API — DONE

| Route | Notes |
| --- | --- |
| `POST /api/auth/login`, `GET /api/auth/me`, `POST /api/auth/logout` | Session lifecycle |
| `GET /api/stats` | Buses inside, entries today, flagged/unrecognized counts computed from real events |
| `GET /api/analytics` | Per-hour / per-gate / per-bus series, campus-local hour buckets |
| `GET /api/events` | Filters: date, date_from/date_to, bus number, gate, direction, flagged + pagination |
| `POST /api/events` | Device ingestion, `X-Device-Key` required |
| `GET /api/events/<id>` | Single event |
| `GET /api/export/events.csv`, `/api/export/events.xlsx` | CSV (formula-injection guarded) and Excel export |
| `GET /api/stream` | Server-sent events for live refresh |
| `GET/POST/PUT/PATCH/DELETE /api/drivers`, `/api/buses` | CRUD with audit |
| `GET /api/search?q=` | Driver + bus search used by the topbar and the Drivers/Buses pages |
| `GET /api/audit` | Audit trail with pagination and search |
| `GET /api/config` | Camera tiles, flag labels, thresholds |
| `GET /api/health` | Liveness probe |

### 4. Live data — DONE

- The dashboard opens a `EventSource` on `/api/stream` and automatically falls
  back to 10-second API polling if the stream is unavailable
  (`frontend/js/sse.js`); the active mode is shown in the page header.
- **Currently Inside** = for each bus, the most recent event; if it is `IN`
  the bus is inside (with time since entry and an overstay marker).
- **Flagged vehicles** are computed on the server at ingestion time with the
  reason attached, and the UI shows the reason chip:
  - `unregistered_plate` — plate is not in the bus register;
  - `low_ocr_confidence` — confidence below `OCR_CONFIDENCE_THRESHOLD` (0.75);
  - `long_overstay` — inside longer than `OVERSTAY_HOURS` (12).
- Counts for "flagged today" and "unrecognized today" come from the same event
  documents, not from constants.

### 5. Detection integration — PARTIAL

Done:

- The event contract is fully documented in
  [`docs/EVENT_CONTRACT.md`](docs/EVENT_CONTRACT.md): endpoint, headers, the
  `{bus_number, direction, gate, camera_id, confidence, timestamp}` payload,
  field rules, responses, flag rules and wiring instructions.
- `backend/detection_client.py` posts an event using `DEVICE_API_KEY` and
  `TRANSPORT_API_URL` from the environment (the key is never printed) and
  supports both CLI flags and `--event-json`.
- The server side is complete: device-key authentication (constant-time
  comparison), strict payload validation, ingestion, flagging and audit.

Not done (blocked on the operator):

- The **URL of the GitHub repository that holds the OCR/detection code was
  requested but never supplied**, so the detector could not be integrated,
  adapted or run against real code. No detector code is included, and none was
  invented.

### 6. Dashboard — DONE

- All numbers come from `/api/stats`, `/api/events` and `/api/analytics`; the
  previous hard-coded counters are gone.
- Camera tiles show **“Demo footage”** unless `CAMERA_STREAM_URLS` provides a
  real URL; configured tiles play **HLS** (hls.js) or **MJPEG** streams.
- Charts: entries per hour, per gate and per bus (Chart.js), with empty and
  error states.
- Filters: date, bus number, gate, direction, flagged, chart window; the same
  filters drive the table, the charts and the exports.
- Driver and bus search use the API (`/api/search`, `/api/drivers?q=`,
  `/api/buses?q=`) — the previous mock search is gone.
- Every async surface has explicit loading / empty / error states with a
  retry button, and icon-only buttons carry `aria-label` + `title`.
- Mobile: the original responsive rules were kept and extended (sidebar drawer,
  stacked cards, scrollable tables).

### 7. Data & privacy — DONE

- Deleted from the working tree and staged for removal: 4 photographs, the
  marketing PDF, `cam1.mp4`, both CSV exports, `logo.png`, `srmminilogo.jpg`.
  They are also ignored going forward (`.gitignore` covers `*.csv`, `*.xlsx`,
  `*.pdf`, `*.mp4`, `*.jpg`, `*.png`, `data/`, `media/`, …).
- `backend/seed_demo.py` creates clearly fake demo data only
  ("Demo Driver One", "BUS-001", "+91 00000 00001", "DEMO-REG-001"). It refuses
  to run unless `ALLOW_DEMO_SEED=true` and both passwords come from the
  environment; it never prints a password.
- `docs/PRIVACY.md` states what personal data is held, who can see it per
  role, retention/sharing expectations and the protection practices in the code.

### 8. Structure — DONE

```
backend/    app.py auth.py config.py db.py schemas.py services.py
            wsgi.py requirements.txt seed_demo.py detection_client.py tests/
frontend/   index.html pages/ assets/ js/ vendor/
docs/       ARCHITECTURE.md EVENT_CONTRACT.md PRIVACY.md
scripts/    check_frontend.mjs scan_secrets.py
```

- ES modules throughout; the sidebar/topbar/search modal are defined once in
  `frontend/js/layout.js` and reused by all nine pages (the copy-pasted
  sidebars are gone).
- All Python dependencies are pinned in `backend/requirements.txt`
  (Flask 3.0.3, Flask-Cors 4.0.1, Flask-Limiter 3.8.0, PyJWT 2.10.1,
  argon2-cffi 23.1.0, pymongo 4.10.1, pydantic 2.9.2, openpyxl 3.1.5,
  gunicorn 23.0.0, mongomock 4.3.0, pytest 8.3.4, …).
- Frontend libraries are vendored and pinned with their licences:
  Chart.js **4.4.4** (MIT), hls.js **1.5.17** (BSD-3-Clause), SheetJS
  **xlsx 0.18.5** (Apache-2.0) in `frontend/vendor/` — see
  `frontend/vendor/README.md`. (0.18.5 is the newest release on the public npm
  registry; newer SheetJS builds are published on `cdn.sheetjs.com`.)

### 9. Quality — DONE

- `README.md` rewritten: purpose, features, architecture, roles, quick start,
  environment-variable table, demo seeding, detection integration, API
  reference, tests, deployment, security notes, repository layout.
- 60 pytest tests covering authentication, role enforcement, page protection,
  login rate limiting, security headers, payload validation (unknown fields,
  ranges, future timestamps, control characters, pagination limits),
  device-key ingestion, flag rules, stats, analytics bucketing, filters,
  pagination, CSV/XLSX export and the audit log.
- `scripts/check_frontend.mjs` verifies that every import resolves, every
  imported name is exported, every local asset exists and every element id /
  form field a page module touches exists in that page.
- `scripts/scan_secrets.py` fails if a credential pattern is committed.
- `.github/workflows/ci.yml` runs the backend tests, the frontend checks and
  the secret scan on every push and pull request.

---

## 3. How it was tested

Automated (all run locally on Python 3.11.2 / Node 22.22.3):

| Command | Result |
| --- | --- |
| `python -m pytest` | **60 passed** (auth, roles, validation, ingestion, flags, stats, analytics, filters, pagination, exports, audit, config) |
| `python -m compileall -q backend` | clean |
| `node --check frontend/js/*.js` (18 files) | all parse |
| `node scripts/check_frontend.mjs` | 18 modules, 9 pages, all references resolve (and the checker was negative-tested: a deliberately broken import is detected) |
| `python scripts/scan_secrets.py` | passed — no credential patterns in tracked files |

Live HTTP smoke test against a running instance (Flask dev server on
`mongomock://`, real HTTP requests with `curl`):

| Request | Result |
| --- | --- |
| `GET /` | 200, login page |
| `POST /api/auth/login` (valid) | 200 + `Set-Cookie: transport_token=…; HttpOnly; SameSite=Lax` |
| `POST /api/auth/login` (wrong password) | 401 `Invalid email or password` |
| `POST /api/events` (no / wrong device key) | 401 `Invalid device API key` |
| `POST /api/events` (valid key) | 201, event stored with `flag_reasons: ["unregistered_plate"]` |
| `GET /dashboard` unauthenticated | 302 → `/` |
| `GET /dashboard` authenticated | 200, HTML |
| `GET /manage` as `head_admin` | 302 → `/?error=forbidden` (role enforced) |
| `GET /api/stats`, `/api/events`, `/api/analytics`, `/api/config`, `/api/audit`, `/api/search` | 200 with correct payloads |
| `GET /api/export/events.csv` | 200, `text/csv`, header row + record |
| `POST /api/auth/logout` then `GET /api/auth/me` | 200 then 401 |
| `GET /assets/styles.css`, `/assets/logo.svg`, `/js/dashboard.js`, `/vendor/chart.umd.js`, `/vendor/xlsx.full.min.js` | 200 |

**Not verified:** no browser-based (visual/UI) verification was possible — the
sandbox has no browser and no headless-Chromium download was reachable, so the
rendered pages, chart rendering and mobile layout were validated statically
(module syntax, import/export wiring, element-id and asset references) rather
than visually. The GitHub Action has also not yet executed on GitHub; it runs
on the first push of this branch.

---

## 4. Your actions (required — these cannot be done from this repository)

1. **Rotate the leaked database credential.** The original upstream `app.py`
   contained a MongoDB connection string with an embedded password. It is
   removed from the working tree, but it is still present in this repository's
   **Git history** (the upstream commit and the import commit). Treat the
   credential as compromised: change the database password, update `MONGO_URI`,
   then purge the history (for example `git filter-repo --path app.py`) and
   force-push — or ask the repository owner to do it.
2. **Purge the other personal/operational data from history** as well
   (photographs, `cam1.mp4`, the CSVs, the PDF, `logo.png`). They are removed
   from the working tree but still exist in earlier commits.
3. **~~Provide the OCR/detection GitHub repository URL~~ — RESOLVED in round 2.**
   The source repository was located and verified:
   [`814725105014-debug/SRM-TRP-TRANSPORT-AI`](https://github.com/814725105014-debug/SRM-TRP-TRANSPORT-AI).
   It is a Colab notebook with no service API and no licence, so the pipeline
   was re-implemented locally in `backend/vision.py`. **Remaining action:** get
   a written licence position on `best.pt` (AGPL-3.0) from the model owner,
   **or** re-train an equivalent model on a dataset you may use and replace
   `best.pt`. See `docs/DETECTION.md`.
4. **Provision the secrets** in your platform's secret manager (never in the
   repository): `MONGO_URI` (least-privilege user), `JWT_SECRET` (≥ 32 random
   characters), `DEVICE_API_KEYS` (one per camera group), `CORS_ALLOWED_ORIGINS`,
   `COOKIE_SECURE=true`, and a shared `RATELIMIT_STORAGE_URI` (e.g. Redis) if
   you run more than one worker.
5. **Create the real accounts** — one `head_admin` and one or more
   `transport_office` users (see the README snippet; the seed script can do it
   with your own passwords).
6. **Import the real bus and driver register.** The repository deliberately
   contains no personal data, so the operator must load it into MongoDB.
7. **Configure the camera streams** in `CAMERA_STREAM_URLS`
   (`{"gate-1-entry": {"type": "hls", "url": "https://…", "label": "Gate 1 Entry"}}`).
   Until then the tiles read "Demo footage" by design. **For RTSP cameras,
   bridge them through MediaMTX or FFmpeg to HLS/MJPEG first** — a browser
   cannot open an RTSP session. See `docs/CAMERAS.md`.
8. **~~Supply the approved SRM TRP logo~~ — RESOLVED in round 2.** The
   supplied official crest is now the logo
   (`frontend/assets/logo-emblem.png` and `logo-wordmark.png`), and the golden
   glass theme uses the sampled brand palette. No further artwork is needed.
9. **Confirm the privacy note and retention policy** in `docs/PRIVACY.md` with
   the transport office (how long events and driver records are kept, who may
   export them).
10. **Deployment details**: hosting platform, domain and TLS termination,
    MongoDB hosting and backup policy, worker count, and whether the campus
    network reaches the service directly or through a proxy.
11. **Set the Firebase API key** in the host's secret store as
    `FIREBASE_API_KEY` (it is deliberately not committed). The console works
    without it. See `docs/FIREBASE.md`.
12. **Terminate TLS in front of the app.** The browser camera API only works
    in a secure context (`https://` or `http://localhost`).

---

## 5. Change summary

- 83 files changed, **+7 686 / −3 110** lines.
- Removed from the working tree (staged as deletions): `app.py`, `test_api.py`,
  `requirements.txt`, `style.css`, `index.html`, `Bus.html`,
  `TransportOffice.html`, `all-drivers.html`, `driver-details.html`,
  `Recent_In_Out_Logs.csv`, `Recent_In_Out_Logs01.csv`, `cam1.mp4`,
  `SRM TRP TRANSPORT AI By HARIHARAN V (2).pdf`, `logo.png`,
  `srmminilogo.jpg` and the four photographic assets.
- `style.css` was carried over to `frontend/assets/styles.css` (same visual
  language, extended) and `README.md` was rewritten.
- The previous branch work (the import of the upstream repository and PR #1)
  was completed earlier and is not repeated here.
