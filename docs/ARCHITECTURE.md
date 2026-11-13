# Architecture

```
                    ┌──────────────────────────────────────────┐
 detection device ──▶ POST /api/events  (X-Device-Key)      │
                    │                                          │
 browser  ────────▶ Flask app (backend/app.py)             │
                    │   ├── auth: JWT cookie + Argon2 + RBAC  │
                    │   ├── REST: /api/drivers /buses /events │
                    │   ├── analytics: /api/stats /analytics  │
                    │   ├── exports: CSV + XLSX               │
                    │   └── live: /api/stream (SSE)            │
                    │                                          │
                    │            Supabase PostgreSQL (private schema)  │
                    └──────────────────────────────────────────┘
```

## Backend (`/backend`)

| Module | Responsibility |
| --- | --- |
| `config.py` | Reads every setting from the environment; validates CORS/CSRF origins, camera stream URLs, timezone, numeric bounds and production secret strength. |
| `db.py` | PostgreSQL engine, typed table access (`users`, `buses`, `drivers`, `events`, `audit_logs`, `bus_states`, `revoked_tokens`), schema-version check, SQL analytics aggregation, readiness ping, UTC helpers and `_id` → `id` serializer. |
| `schemas.py` | Pydantic models for every request/response body and query filter, plus `plate_key()` canonicalization. |
| `auth.py` | Argon2 hashing, JWT issue/verify/revocation, HttpOnly cookie helpers, role and device-key decorators. |
| `firebase_auth.py` | Verifies Firebase ID tokens against Google's JWKS keys (`timeout=5`, issuer, audience, non-empty `sub`). |
| `access.py` | Access-list authorization, verified email enforcement, atomic UID binding and admin-approved provisioning. |
| `services.py` | Event deduplication/ingestion, `bus_states` sync, flag rules, cached stats/SQL analytics, streaming CSV/XLSX writers, audit records and camera configuration. |
| `vision.py` | Lazy YOLOv10n sticker detection (`best.pt`), strict image validation, crop OCR (`rapidocr`/`tesseract`/`easyocr`) and `normalize_plate()`. |
| `app.py` | Application factory: routes (`/api/auth/*`, `/api/ready`, `/api/stream*`, `/api/detection/*`, CRUD, exports), security headers, CORS/CSRF, proxy-aware rate limiting, error handlers. |
| `wsgi.py` | WSGI entry point (`gunicorn backend.wsgi:app`). |
| `manage_access.py` | CLI for managing the portal access list and Firebase UID unlinking. |
| `manage_states.py` | CLI for rebuilding `bus_states` and running optional retention purges. |
| `seed_demo.py` | Opt-in fake demo data (requires `ALLOW_DEMO_SEED=true` and explicit passwords). |
| `detection_client.py` | Reference client for posting detection events with `X-Idempotency-Key` and bounded retries. |

## Frontend (`/frontend`)

Vanilla ES modules, no build step. `js/layout.js` renders one shared shell
(sidebar, topbar, search modal, theme toggle, clock) for every page, so the
navigation is defined once instead of being copy-pasted into each HTML file.

| Module | Responsibility |
| --- | --- |
| `api.js` | `fetch` wrapper, `ApiError`, query builder, file downloads. Never uses `innerHTML`. |
| `ui.js` | DOM builders, loading/empty/error states, badges, toasts, formatters. |
| `layout.js` | Shared shell, role-aware navigation, global search, logout. |
| `charts.js` | Chart.js wrappers for per-hour / per-gate / per-bus charts. |
| `tables.js` | Table renderers and pagination. |
| `streams.js` | Camera tiles: HLS, MJPEG or "Demo footage" placeholder. |
| `sse.js` | Server-sent events with automatic API-polling fallback. |
| `exports.js` | CSV/Excel export with a client-side fallback. |
| `filters.js` | Shared filter parsing for the page modules. |
| `dashboard.js`, `logs.js`, `analytics.js`, `drivers.js`, `buses.js`, `driver-details.js`, `audit.js`, `manage.js`, `login.js` | Page controllers. |

Vendored browser bundles (Chart.js, hls.js, SheetJS) live in `frontend/vendor`
with their licences, so the Content-Security-Policy can stay on `script-src 'self'`.

## Roles

| Role | Pages | API |
| --- | --- | --- |
| `head_admin` | dashboard, logs, analytics, drivers, buses, driver details, audit | read everything, export, read audit |
| `transport_office` | manage, drivers, buses, driver details | read + write drivers and buses |

Both roles are enforced server-side by `require_roles` / `require_page_roles`.

## Database and security boundary

The private `transport_portal` PostgreSQL schema is installed once from
`backend/sql/001_initial.sql` (plus incremental migrations such as
`002_backend_hardening.sql`); startup only checks the schema version and read
access. A dedicated server-side role has DML permissions for the six
application tables (`users`, `buses`, `drivers`, `events`, `bus_states`,
`revoked_tokens`) and append/read access to audit logs. Review ambient
`PUBLIC` privileges in the Supabase project separately. The schema must not
be exposed through the Supabase Data API: Firebase tokens are verified by
Flask, and Flask enforces verified-email/access-list/role checks. Supabase RLS
is not relied upon as a substitute for those checks. Each connection uses
bound SQL parameters, a small pool and disabled prepared statements. SQLite
in memory is supported only for disposable previews and tests. Existing MongoDB
data requires a separate, reviewed import and is not silently copied.
