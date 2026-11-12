# Firebase browser SDK (vendored)

| File | Package | Version | Source | License |
| --- | --- | --- | --- | --- |
| `firebase-app-compat.js` | `firebase/app` (compat build) | 11.10.0 | npm `firebase@11.10.0` | Apache-2.0 — see `LICENSE` |
| `firebase-auth-compat.js` | `firebase/auth` (compat build) | 11.10.0 | npm `firebase@11.10.0` | Apache-2.0 — see `LICENSE` |
| `firebase-analytics-compat.js` | `firebase/analytics` (compat build) | 11.10.0 | npm `firebase@11.10.0` | Apache-2.0 — see `LICENSE` |
| `firebase-firestore-compat.js` | `firebase/firestore` (compat build) | 11.10.0 | npm `firebase@11.10.0` | Apache-2.0 — see `LICENSE` |

These are the *compat* (UMD) builds so they can be loaded with a plain
`<script>` tag and used from `window.firebase`, without a bundler or import
map. The application loads them lazily and only when Firebase is actually
configured, so no Firebase code is downloaded on deployments that do not use it.

> **Load order matters.** `firebase-auth-compat.js` and
> `firebase-analytics-compat.js` depend on `firebase-app-compat.js` having
> already run (they read `firebase.INTERNAL.modularAPIs`). `frontend/js/firebase.js`
> always loads the `app` bundle first and only then the extras.

## Configuration

The Firebase web configuration is **not** stored in this repository. The
backend reads it from the environment and exposes the (public, client-side)
subset at `GET /api/config/firebase`:

| Variable | Purpose |
| --- | --- |
| `FIREBASE_API_KEY` | Web API key |
| `FIREBASE_AUTH_DOMAIN` | Auth domain |
| `FIREBASE_PROJECT_ID` | Project id |
| `FIREBASE_STORAGE_BUCKET` | Storage bucket |
| `FIREBASE_MESSAGING_SENDER_ID` | Messaging sender id |
| `FIREBASE_APP_ID` | Web app id |
| `FIREBASE_MEASUREMENT_ID` | Analytics measurement id (optional) |

Set them in your deployment's secret store (or `.env` locally) — never commit
them. The same project can also be configured with the Firebase CLI:

```bash
firebase use --add          # register / select the project
firebase login
firebase deploy --only hosting
```

## Regenerating

```bash
npm pack firebase@11.10.0
tar -xzf firebase-11.10.0.tgz
cp package/firebase-app-compat.js package/firebase-auth-compat.js \
   package/firebase-analytics-compat.js package/firebase-firestore-compat.js \
   frontend/vendor/firebase/
cp package/LICENSE frontend/vendor/firebase/LICENSE
```

## Authentication

The Authentication bundle backs the portal's sign-in. See
`docs/AUTHENTICATION.md` for the full model, the access-list rules and the
Firebase console setup.

The browser authenticates with Firebase and posts the resulting **ID token**
to `POST /api/auth/firebase`. The backend verifies it against Google's
*public* signing keys — no service account and no private key are needed —
checks the email against the access list, and then issues the application's
own short-lived HttpOnly session cookie. The Firebase ID token is used once
and discarded.
