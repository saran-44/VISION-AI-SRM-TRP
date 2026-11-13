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

## 4. Hosting → Render (free plan)

`firebase.json` publishes `deploy/firebase/public`, a one-file placeholder, and
redirects **every** path to the Render deployment with a `302`:

```json
"redirects": [
  { "source": "/:path*", "destination": "https://srm-trp-transport.onrender.com/:path*", "type": 302 },
  { "source": "**",     "destination": "https://srm-trp-transport.onrender.com",        "type": 302 }
]
```

The first rule keeps the path **and** the query string; the second catches
anything the capture misses. `302` rather than `301` so the target stays
changeable — see [DEPLOY_FIREBASE_REDIRECT.md](DEPLOY_FIREBASE_REDIRECT.md).

Why a redirect: Hosting rewrites can only target Cloud Run or Cloud Functions,
and both require the Blaze plan. The app runs on Render Free, so Hosting
contributes the branded HTTPS address (`vision-ai-srmtrp.web.app`) and the
browser talks to Render directly. Nothing is served from Firebase: the Flask
app still owns authentication, roles and every page template, so publishing
`frontend/pages/` to a static host cannot bypass the role checks.

Consequences worth knowing:

- The `__session` forwarding rule of the Hosting→Cloud Run boundary no longer
  applies — the cookie is set and read on the Render origin. The app keeps the
  reserved name, `HttpOnly`, `SameSite=Lax` and production `Secure`, and
  `test_hosting_deployment.py` still guards that shape.
- Sign-in happens on `srm-trp-transport.onrender.com`, so that host must be in
  **Authentication → Settings → Authorized domains**. `web.app` in that list is
  harmless but unused.
- Firebase's 60-second backend limit, VPC egress and Cloud Run cold starts are
  out of the picture; Render's own limits apply
  ([DEPLOY_RENDER_FREE.md](DEPLOY_RENDER_FREE.md) §10).
- The local Hosting emulator verifies the rules offline
  (`firebase emulators:start --only hosting`); it does not prove the live
  deployment's DNS, certificate or Firebase project bindings.

## 5. Deploy and production gates (paid Cloud Run path, optional)

The checked-in `firebase.json` targets the free redirect path above. Switching
back to a Hosting→Cloud Run rewrite means restoring the `rewrites` block in
`firebase.json` (CLI: `firebase init hosting` is still the wrong tool — edit the
file) **and** upgrading the project to Blaze.

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
