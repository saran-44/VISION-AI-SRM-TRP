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
| `config.py` | Reads every setting from the environment; validates CORS origins, camera stream URLs and production secret strength. |
| `db.py` | PostgreSQL engine, typed table access, schema-version check, UTC helpers and `_id` → `id` serializer. |
| `schemas.py` | Pydantic models for every request/response body and query filter. |
| `auth.py` | Argon2 hashing, JWT issue/verify, HttpOnly cookie helpers, role and device-key decorators. |
| `services.py` | Event ingestion and flag rules, stats/analytics computation, CSV/XLSX writers, audit records, camera configuration. |
| `app.py` | Application factory: routes, security headers, CORS, rate limiting, error handlers. |
| `wsgi.py` | WSGI entry point (`gunicorn backend.wsgi:app`). |
| `seed_demo.py` | Opt-in fake demo data (requires `ALLOW_DEMO_SEED=true` and explicit passwords). |
| `detection_client.py` | Reference client for posting one detection event. |

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
`backend/sql/001_initial.sql`; startup only checks the schema version and
read access. A dedicated server-side role has DML permissions for the four
application tables and append/read access to audit logs. Review ambient
`PUBLIC` privileges in the Supabase project separately. The schema must not
be exposed through the Supabase Data API: Firebase tokens are verified by
Flask, and Flask enforces verified-email/access-list/role checks. Supabase RLS
is not relied upon as a substitute for those checks. Each connection uses
bound SQL parameters, a small pool and disabled prepared statements. SQLite
in memory is supported only for disposable previews and tests. Existing MongoDB
data requires a separate, reviewed import and is not silently copied.
