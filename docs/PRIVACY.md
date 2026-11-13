# Privacy note — SRM TRP Transport

_Last reviewed: 2026-11-12. Applies to the SRM TRP Transport campus bus gate
monitoring web application (dashboard, live logs, analytics, driver and bus
records)._

## What personal data this system holds

The application stores operational records about campus bus movements:

| Data | Examples | Why it is held |
| --- | --- | --- |
| Driver records | Name, contact number, licence number, assigned bus | Route staffing and accountability |
| Bus records | Bus number, registration number, route, capacity, insurance expiry | Fleet compliance |
| Gate events | Plate/bus number, direction, gate, camera id, OCR confidence, timestamp | Gate security and movement auditing |
| Audit entries | Who changed which record, when, from which IP | Traceability of administrative changes |

Passwords are never stored in plain text: they are hashed with **Argon2id**
before being written to the database.

## Who can see what

| Role | Access |
| --- | --- |
| `head_admin` | Dashboard, live logs, analytics, driver and bus records, audit log, exports |
| `transport_office` | Driver and bus records, and the ability to add/edit/delete them |
| Detection device | May only submit events through `POST /api/events` using a device API key |
| Everyone else | Nothing — every page and API endpoint requires an authenticated session |

Access is enforced on the server for every page and every API route. Hiding a
menu item in the browser is never the protection; the server checks the signed
session token and the role on each request.

## Retention and sharing

- Event, driver, bus, access-list and audit data is stored in the configured
  Supabase PostgreSQL project. Supabase hosts that data, Firebase handles
  authentication, and Google Cloud hosts the application; review provider
  regions, contracts, access controls and retention with the data owner.
- Exports (CSV/Excel) are generated on demand and are downloaded to the
  requesting administrator's device. Treat them as personal data: store them
  securely and delete them when no longer needed.
- Camera tiles display footage only when an operator configures a stream URL
  (`CAMERA_STREAM_URLS`). No video is stored by this application.
- Retention periods should be set by the transport department's data-protection
  policy; the application itself keeps records until they are deleted.

## Data protection practices applied in the code

- Secrets are read from environment variables only; `.env` is git-ignored and
  `.env.example` documents the variable names without values.
- Security headers (CSP, `X-Content-Type-Options`, `Referrer-Policy`,
  `Permissions-Policy`) are attached to every response.
- API responses are JSON; the frontend never inserts API or CSV text into
  `innerHTML`.
- Logins are rate limited and every administrative change is written to the
  audit log with actor, role, timestamp and IP address.

## Contact

Questions about access to or deletion of this data should go to the SRM TRP
transport office administrator who provisions accounts for this deployment.
