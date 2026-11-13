# Firebase: browser configuration, authentication and Hosting

This document describes the checked-in integration. For the complete, ordered
Windows installation, project setup, Supabase networking, private administrator
onboarding, Cloud Run/Hosting deploy and verification instructions, use
**[DEPLOY_WINDOWS.md](DEPLOY_WINDOWS.md)**. The architecture and upgrade
context are in [UPGRADE_SPECIFICATION.md](UPGRADE_SPECIFICATION.md), and the
access model is in [AUTHENTICATION.md](AUTHENTICATION.md).

> The supplied project and app identifiers below have **not** been verified
> against the live Firebase project from this workspace. Confirm them in
> Firebase Console → Project settings → General → Your apps, or with
> `firebase apps:sdkconfig`, before deploying. No live Firebase sign-in,
> Cloud Run deployment, Supabase connection, or Hosting rewrite has been tested
> by the author of these changes.

## 1. Project configuration

| Item | Value currently expected by the repository |
| --- | --- |
| Firebase / Google Cloud project ID | `vision-ai-srmtrp` |
| Web app ID | `1:235811571442:web:342e488e0ac2ee75b0f26b` |
| Messaging sender ID | `235811571442` |
| Firebase auth domain | `vision-ai-srmtrp.firebaseapp.com` |
| Storage bucket | `vision-ai-srmtrp.firebasestorage.app` |
| Measurement ID | `G-S4HS9TGV4H` |
| Web API key | Supplied public web identifier in `.env.example`; build reads it from Secret Manager |

Firebase web API keys are **public project identifiers**, not a substitute for
security rules or authentication. The backend publishes the configured browser
values at `/api/config/firebase`; the key will be visible to the browser.
Externalizing it avoids a hard-coded deployment value and supports rotation;
it does not make the key secret. Restrict API usage appropriately without
breaking Firebase Auth and the verification helper.

`backend/config.py` builds the configuration from environment variables.
Cloud Run's checked-in build settings provide the identifiers and load
`FIREBASE_API_KEY` from Secret Manager. The endpoint returns `enabled: true`
when a project ID and app ID are configured; the browser **also requires an
API key** to initialize. Analytics is optional. Firebase Authentication is a
required login dependency in the provided production build because legacy
password login is disabled.

Do not assume the default Hosting site has the same ID as the project. New
Firebase projects can have no default site until it is created. Inspect
`firebase hosting:sites:list --project=vision-ai-srmtrp --json` for `DEFAULT_SITE`
and compare its `defaultUrl` and the web app's actual `authDomain`. If there
is no default site, follow the conditional creation steps in the Windows
runbook; if the existing site or app config differs, review and update the
Cloud Build settings and Firebase authorized domains before deploying.
See [Firebase's default-site documentation](https://firebase.google.com/docs/hosting/default-site).

## 2. Authentication and onboarding

1. Enable **Email/Password** in Firebase Authentication; enable **Google** if
   its login button will be used. Add the actual deployment domains under
   Authentication → Settings → Authorized domains.
2. Privately create or recover the administrator's Firebase account. Use a
   **new** strong password; never repeat a password that was shared in chat.
3. Verify mailbox ownership. The portal does not currently offer a
   verification/reset button. The checked-in helper can privately send a
   Firebase verification email and check the result:

   ```bash
   # Set FIREBASE_WEB_API_KEY and FIREBASE_USER_PASSWORD via hidden prompts;
   # exact Windows commands and the account-ownership checks are in the runbook.
   python scripts/send_firebase_verification.py 814725105014@trp.srmtrichy.edu.in
   python scripts/send_firebase_verification.py 814725105014@trp.srmtrichy.edu.in --check
   ```

   Open the link before `--check`; clear the password from the shell afterward.
   Never put credentials in command arguments or chat. A command-line Firebase
   REST request can fail with browser-referrer-only API-key restrictions.
4. Review the PostgreSQL access entries/UID bindings and add the verified account
   to the intended Supabase database as `head_admin`, as described in the
   runbook. A Firebase user alone does not grant portal access.

The checked-in Cloud Build settings enable both `password` and `google.com`,
set `FIREBASE_AUTO_PROVISION=false`, and set
`LEGACY_PASSWORD_LOGIN_ENABLED=false`. A successful login requires a valid
Firebase ID token, a **verified email**, and an active backend access-list
entry with a compatible Firebase UID. Arbitrary Google or self-registered
password users are denied. The authenticated browser exchanges the Firebase
ID token for a short-lived application session; the Firebase SDK manages its
own browser authentication state until sign-out. Supabase provides PostgreSQL
storage; the application does not use Supabase Auth or expose the private
schema through its browser Data API.

Google sign-in primarily uses a popup. The code also consumes a redirect
result if a blocked popup triggers the redirect fallback. With a `web.app`
origin and the default `firebaseapp.com` auth domain, modern browsers can block
cross-origin storage needed by redirect sign-in. Test the actual browsers and
configure a same-origin auth domain/authorized OAuth redirect URI as described
in [Firebase's redirect best practices](https://firebase.google.com/docs/auth/web/redirect-best-practices),
or allow the popup. Do not claim redirect works until it is tested live.

## 3. Browser SDK

The compat SDK bundles from `firebase@11.10.0` are vendored in
`frontend/vendor/firebase/` with their licence and provenance. The loader in
`frontend/js/firebase.js`:

- fetches and caches `/api/config/firebase`;
- loads the app bundle first and Auth, Analytics, and Firestore separately on
  demand, including when Analytics was loaded before Auth;
- shares concurrent script loads and permits a retry after a bundle fails;
- keeps Analytics best-effort and ends the Firebase session on sign-out.

`scripts/check_firebase_loader.mjs` and `scripts/check_auth_flow.mjs` exercise
these paths with browser/Firebase mocks. They are **not** live integration
or OAuth tests.

## 4. Hosting → Cloud Run

`firebase.json` publishes `frontend/` but **excludes `frontend/pages/`**.
Firebase Hosting gives static files priority over rewrites, so publishing the
page templates would bypass Flask's page-role checks. The login page, assets,
JavaScript and vendor libraries are static. Every unmatched path, including
`/api/**` and `/dashboard`, is rewritten using `run.serviceId` to Cloud Run
service `srm-trp-transport` in `asia-south1`; this is not an SPA fallback.
Flask serves protected templates only after checking the session and role.

The browser uses same-origin relative API URLs. Firebase Hosting forwards only
the reserved `__session` cookie to a dynamic backend; the app uses that name
for its `HttpOnly`, `SameSite=Lax`, production-`Secure` session cookie. Users
of the former cookie must sign in again. Renaming a cookie alone does not
invalidate copied JWTs: rotate `JWT_SECRET` and retire old reachable revisions
when responding to a compromise.

Firebase Hosting and the backend both allow `camera=(self)` through
`Permissions-Policy`. HTTPS and browser camera permission are also required.
`/assets/**` and `/vendor/**` have a one-year immutable cache header; rename or
version asset URLs when changing them to avoid stale browser content. The
backend marks API and HTML responses `no-store`.

Firebase Hosting currently limits backend requests to **60 seconds**, even
though Cloud Run is configured for 300 seconds. A cold start waiting on NAT or
Supabase can time out at the Hosting edge before the backend becomes ready;
retry after inspecting service health. Long-running detection and camera/SSE
streams may be interrupted and require explicit production testing or another
architecture. See [Firebase's serverless limits](https://firebase.google.com/docs/hosting/serverless-overview).

The local Hosting emulator can check basic rewrites, but it does not prove a
real Cloud Run proxy or deployment upload exclusions. Test an actual deployment
with an authorized and unauthorized account before production.

## 5. Deploy and production gates

The Windows runbook creates a dedicated build and runtime identity, five
Secret Manager values, a dedicated PostgreSQL database user, and Direct VPC egress
with a static Cloud NAT IP **before** the first Cloud Run startup. It then
submits `deploy/cloudbuild.yaml` and deploys Hosting. It also covers costs,
IAM, tool installation, safe Git updates, rollback and verification.

Before production, verify both leaked Atlas credentials are revoked, review
previously provisioned Firebase/PostgreSQL accounts and sessions, rotate the JWT
key, coordinate a sensitive Git-history purge **after** credential rotation,
and resolve the provenance/licence of `best.pt`. Do not rely on a mock test,
an ignore file, or a normal new Git commit as proof those tasks are complete.
