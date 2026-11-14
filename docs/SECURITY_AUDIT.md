# Security audit — VISION AI - SRM TRP

_Last reviewed: 2026-11-14. Scope: this repository at `main` plus the demo/Test
Lab work in the same change. A repository review is not a penetration test: the
live Render/Supabase/Firebase deployment still needs the operator checks in
[§6](#6-operator-checklist-things-a-repo-review-cannot-see)._

Reproduce every automated check here with:

```bash
source .venv/Scripts/activate        # Git Bash on Windows; pytest lives here
bash scripts/audit_local.sh --with-tests
```

The script picks `.venv` (or `$VIRTUAL_ENV`) automatically. If pytest is
missing it reports an **environment gap, not a code failure**, and tells you how
to install it — a red “pytest failed” from the system interpreter is not a
finding.

---

## 1. Summary

| # | Severity | Area | Finding | Status |
| --- | --- | --- | --- | --- |
| 1 | **High** | Credential exposure | The browser scan path sent `X-Device-Key: window.__SRM_DEVICE_KEY__`. Any value put there is readable by every script on the page, every extension and anyone with DevTools | **Fixed** — header removed; the session cookie is the credential |
| 2 | Medium | Denial of service | `/api/detection/scan` decoded images with no pixel cap. A few-hundred-KB PNG can decode into a multi-gigabyte bitmap and exhaust the 512 MB instance | **Fixed** — `MAX_IMAGE_PIXELS` (12 MP), `MAX_IMAGE_SIDE` (6000 px), `MAX_IMAGE_BYTES` (8 MB), plus PIL's own bomb guard |
| 3 | Medium | Clickjacking | CSP `frame-ancestors` allowed `https://*.e2b.app` in **every** environment, so production could be framed by any e2b.app host | **Fixed** — production is `frame-ancestors 'self'`; the preview allowance is development-only |
| 4 | Medium | Authentication | `LEGACY_PASSWORD_LOGIN_ENABLED` defaulted to **true**. A deployment that ignored `render.yaml` would ship password sign-in in production | **Fixed** — defaults to false in production; `validate()` refuses it without `ALLOW_LEGACY_LOGIN_IN_PRODUCTION=true` |
| 5 | Low | Demo surface | The requested `admin` / `admin` account is a known credential | **Contained** — `DEMO_MODE` is refused in production, the alias is rejected without it, `/test-lab` and `/api/test-lab/*` 404, and the account exists only in a seeded disposable preview |
| 6 | Low | CSRF | No anti-CSRF token on state-changing requests | **Accepted** — `SameSite=Lax` cookie, JSON-only bodies (a cross-site form cannot send `application/json`), no wildcard CORS |
| 7 | Low | Supply chain | CSP allows `https://unpkg.com` for the boxicons stylesheet and `'unsafe-inline'` styles | **Accepted for now** — vendoring boxicons and dropping `'unsafe-inline'` is the next step |
| 8 | Low | Licensing | `best.pt` (5.5 MB) is tracked; its metadata cites Ultralytics **AGPL-3.0** and the checkpoint's provenance is unverified | **Open (legal, not runtime)** — see `docs/DETECTION.md` |
| 9 | Info | Personal data | Audit log rows contain email addresses and client IPs | **By design** — retention guidance in `docs/PRIVACY.md` |
| 10 | Info | Rate limiting | `memory://` limiter is per instance | **Accepted** — single free instance; use Redis before scaling |

Nothing in the table was exploitable through an anonymous request that the
existing tests exercise; items 2–4 were latent rather than exploited.

---

## 2. What is already correct

Verified by reading the code and by the test suite (192 tests):

- **Secrets** — none in the tracked tree (`scripts/scan_secrets.py` passes in
  CI). `.env`, `*.pem`, `*.key` and `secrets/` are ignored; `.env.example`
  contains placeholders only.
- **Authentication** — Argon2id password hashing (`time_cost=2`,
  `memory_cost=19456`, 32-byte hash), HS256 JWT with `aud`/`iss`/`jti`, 15-minute
  TTL, and the user row re-read on every request so deactivation takes effect
  immediately. Firebase ID tokens are verified against Google's keys and never
  stored.
- **Session cookie** — `__session`, `HttpOnly`, `SameSite=Lax`, `Secure` in
  production, host-only, cleared on logout.
- **Authorisation** — every data route carries `@require_roles(...)`
  (35 of 45 routes guarded; the 10 public ones are the login surface, the health
  probe, the public Firebase identifiers and static files). `scripts/audit_local.sh`
  fails the audit if a new route appears without a guard or an explicit
  exception.
- **Tenant separation** — the app talks to PostgreSQL through a dedicated
  `transport_portal_app` role scoped to the private `transport_portal` schema,
  with `sslmode=verify-full` enforced in production.
- **Injection** — all queries go through SQLAlchemy Core with bound parameters
  and `icontains(..., autoescape=True)`; there is no string-built SQL.
- **Uploads** — `MAX_CONTENT_LENGTH` is 1 MB globally; image decoding is now
  additionally bounded (item 2).
- **Headers** — `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`
  (`camera=(self)`), CSP, HSTS behind TLS, and `no-store` on API and HTML.
- **Login throttling** — `5 per minute; 20 per hour` on both password and
  Firebase sign-in, keyed on the real client IP behind Render's proxy.
- **No browser-side secrets** — the frontend receives only public Firebase
  identifiers; the device API key never leaves the server.

---

## 3. Demo / Test Lab containment

The `admin` / `admin` account exists **only** when `DEMO_MODE` is on:

| Control | Behaviour |
| --- | --- |
| Config guard | `Config.validate()` raises if `demo_mode` and `environment == "production"` |
| Seeding | `scripts/run_preview.py` seeds it into a throwaway in-memory SQLite database; `seed_demo_data(demo_login=True)` is the only caller |
| Login alias | `"admin"` maps to the reserved `admin@demo.local` only inside `DEMO_MODE`; elsewhere it fails validation like any non-address |
| Password policy | `DemoLoginSchema` (min length 1) is used **only** in demo mode; production keeps the 8-character minimum |
| Page | `GET /test-lab` → `404` without demo mode |
| API | `GET /api/test-lab/checks`, `POST /api/test-lab/events` → `404` without demo mode |
| Navigation | The Test Lab link and the `DEMO` chip are rendered only when `/api/auth/config` reports `demo_mode: true` |
| Tests | `backend/tests/test_demo_mode.py` (11 tests) pins every row above |

To be explicit about the risk the operator is accepting: **anyone who can reach
a demo deployment can sign in as head admin.** Run demo mode on a laptop or a
private preview only, never on a public URL, and never against Supabase.

---

## 4. Data exposure review ("hide them all")

| Data | Where it lives now | Exposure |
| --- | --- | --- |
| Driver names, phones, licence numbers | PostgreSQL `transport_portal.drivers`, operator-entered | Authenticated `head_admin` / `transport_office` only; exports are role-guarded |
| Bus register, insurance dates | `transport_portal.buses` | Same |
| Gate events, audit log | `transport_portal.events` / `audit_logs` | `head_admin` only |
| Demo records | Seeded in memory; every row carries `demo: true` / `demo_user: true` | Never touches Supabase |
| CSV/XLSX/PDF/media exports | Removed from the tree; `*.csv`, `*.xlsx`, `*.pdf`, `*.mp4`, `*.png` are git-ignored (branding PNGs re-included) | Not in git |
| `.env` (database URL, JWT secret, device keys, Firebase API key) | Local file only | Ignored; never logged; `Config` errors never echo the URL |
| Firebase web identifiers | Served by `GET /api/config/firebase` | Public by design (they are not secrets) |

Nothing that was previously committed is hidden by this change: file contents
already in Git history stay there until the history is purged. Rotating the
credentials is what neutralises old history — see §6.

---

## 5. Changes shipped with this audit

```
backend/vision.py            image size/pixel caps + PIL bomb guard
backend/config.py            DEMO_MODE, ALLOW_LEGACY_LOGIN_IN_PRODUCTION,
                             fail-closed password login in production
backend/app.py               production-only frame-ancestors, demo login alias,
                             /test-lab page + /api/test-lab/{checks,events}
backend/schemas.py           DemoLoginSchema (demo-only relaxed password rule)
frontend/js/dashboard.js     device API key removed from the browser
frontend/js/layout.js        demo-only nav entry and DEMO chip
scripts/audit_local.sh       read-only local audit (this document's checks)
scripts/run_preview.py       demo seeding + explicit banner
backend/tests/test_demo_mode.py   11 tests pinning the containment
```

---

## 6. Operator checklist (things a repo review cannot see)

1. **Rotate anything that has ever been pasted into a chat or a commit**:
   Supabase database password, `JWT_SECRET`, `DEVICE_API_KEYS`, and the Firebase
   administrator's password. Rotation, not deletion, is what ends exposure.
2. **Render → Environment**: `LEGACY_PASSWORD_LOGIN_ENABLED=false`,
   `FIREBASE_AUTO_PROVISION=false`, and **no** `DEMO_MODE`. Confirm the service
   shows 5 secret values and no plaintext.
3. **Firebase Console**: Email/Password provider on, Google on (optional),
   `srm-trp-transport.onrender.com` in Authorized domains, and only the intended
   accounts in Users.
4. **Supabase**: confirm `transport_portal_app` cannot read other schemas, that
   the Data API (PostgREST) is disabled for this project, and that no other
   key (`sb_publishable_…`, service-role) is stored anywhere in the app.
5. **Exports**: decide a retention period for CSV/XLSX downloads and for the
   `audit_logs` table (emails + IPs), then document it in `docs/PRIVACY.md`.
6. **History purge**: after step 1, purge the old credential from Git history
   (BFG or `git filter-repo`) and force-push with the team's agreement.
7. **Model licence**: obtain written rights for `best.pt` before any public or
   commercial use — AGPL-3.0 has distribution obligations.
8. **Watch the log**: `GET /api/audit` (head admin) shows `login_failed`,
   `login_denied` and `detection_scan_failed`; repeated failures from one
   address are the signal the limiter is doing its job.

---

## 7. Reporting

Open an issue marked **security** or contact the maintainer privately; do not
paste secrets, tokens or database URLs into an issue. The audit script never
prints secret values — if you paste its output, it is safe.
