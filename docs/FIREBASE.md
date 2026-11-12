# Firebase — Hosting, Analytics and Configuration

This project uses the Firebase project **`srmtrpai`** for static hosting of the
console and for optional Google Analytics. The Flask backend is **not** hosted
on Firebase Hosting — it runs on a container/VM — and the two are connected
through the `/api/**` rewrite in `firebase.json` and the `CORS_ALLOWED_ORIGINS`
setting on the backend.

---

## 1. Project facts

| Item | Value |
| --- | --- |
| Firebase project id | `srmtrpai` |
| Auth domain | `srmtrpai.firebaseapp.com` |
| Storage bucket | `srmtrpai.firebasestorage.app` |
| Messaging sender id | `734375891811` |
| Web app id | `1:734375891811:web:6851938bef332bc0e53956` |
| Analytics measurement id | `G-7MXBNH3N7D` |

> **The API key is deliberately not committed.** Firebase web API keys are
> public identifiers (they identify the project, they do not authorise access
> to data — access is governed by Firestore/Storage security rules), but
> keeping them out of Git makes rotation a configuration change rather than a
> code change, and stops the repository from carrying deployment identifiers.
> The key is read from the environment at runtime.

---

## 2. Where the configuration lives

| Where | What |
| --- | --- |
| `.env` (local, git-ignored) | `FIREBASE_API_KEY`, `FIREBASE_PROJECT_ID`, … |
| The host's secret store (production) | The same variables |
| `GET /api/config/firebase` | The public subset the browser receives |

`backend/config.py` reads the variables, and `backend/app.py` exposes them at
`/api/config/firebase`:

```json
{
  "config": {
    "apiKey": "…",
    "authDomain": "srmtrpai.firebaseapp.com",
    "projectId": "srmtrpai",
    "storageBucket": "srmtrpai.firebasestorage.app",
    "messagingSenderId": "734375891811",
    "appId": "1:734375891811:web:6851938bef332bc0e53956",
    "measurementId": "G-7MXBNH3N7D"
  },
  "projectId": "srmtrpai",
  "enabled": true,
  "analytics": true
}
```

When the variables are absent the endpoint returns `"enabled": false` and the
frontend never downloads the Firebase SDK. **The console works fully without
Firebase** — it is an optional enhancement, not a dependency.

---

## 3. Frontend integration

The SDK is vendored under `frontend/vendor/firebase/` (the `compat` UMD
builds of `firebase/app`, `firebase/analytics` and `firebase/firestore` from
`firebase@11.10.0`, Apache-2.0) and loaded **lazily** by
`frontend/js/firebase.js`:

1. `initFirebase()` fetches `/api/config/firebase`.
2. If `enabled` is false it returns immediately — nothing is downloaded.
3. Otherwise it injects the `<script>` tags for the vendored bundles.
4. `window.firebase.initializeApp(config)` is called once.
5. Analytics is started only when a `measurementId` is present.

Events recorded: `app_open`, `login`, `logout`, `screen_view`,
`capture_frame`, `detection_result`, `export_data`.

Nothing in the console throws if Firebase is unavailable — every Firebase call
is wrapped so an outage can never break the transport UI.

---

## 4. Firebase CLI

```bash
# One-time setup
npm install -g firebase-tools
firebase login

# Point the CLI at the project (the repo already contains .firebaserc)
firebase use --add          # choose "srmtrpai"

# Preview locally
firebase emulators:start --only hosting

# Deploy the static console
firebase deploy --only hosting
```

`firebase.json` publishes the `frontend/` directory:

- `/api/**` is rewritten to the Cloud Run / Cloud Functions service
  `srmtrpai` in `asia-south1`.
- Everything else falls back to `/index.html` for client-side routing.
- `/assets/**` and `/vendor/**` get a one-year immutable cache header.
- `/api/**` is explicitly `no-store`.
- A `Permissions-Policy` header allows `camera=(self)` (needed for the
  operator webcam) and denies microphone and geolocation.

> If the backend is hosted somewhere other than a Google Cloud service in
> `asia-south1`, update the `run` block in `firebase.json`, or replace the
> `/api/**` rewrite with a `redirect`/proxy and point the frontend at the
> backend origin directly through `CORS_ALLOWED_ORIGINS`.

---

## 5. Connecting the frontend to the backend

The console calls the API on the **same origin** (`/api/...`), which
Firebase Hosting rewrites to the backend service. Two consequences:

1. The session cookie is `SameSite=Lax` and works because the browser sees a
   single origin.
2. `CORS_ALLOWED_ORIGINS` on the backend is only needed if you *also* serve the
   frontend from somewhere else (for example the Flask server itself during
   development). Set it to the Firebase Hosting URL:

```bash
export CORS_ALLOWED_ORIGINS="https://srmtrpai.web.app,https://srmtrpai.firebaseapp.com"
```

---

## 6. Deploying the backend

The Flask backend runs on a container or VM. A minimal `Dockerfile` and a
`cloudbuild.yaml` are provided under `deploy/`.

### Cloud Run

```bash
gcloud run deploy srm-trp-transport \
  --image REGION-docker.pkg.dev/PROJECT/REPO/srm-trp-transport:latest \
  --region asia-south1 \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars "ENVIRONMENT=production,MONGO_DB_NAME=srmtrpai" \
  --set-secrets "MONGO_URI=mongo-uri:latest,JWT_SECRET=jwt-secret:latest,DEVICE_API_KEYS=device-keys:latest" \
  --set-env-vars "FIREBASE_PROJECT_ID=srmtrpai,FIREBASE_AUTH_DOMAIN=srmtrpai.firebaseapp.com,FIREBASE_APP_ID=1:734375891811:web:6851938bef332bc0e53956,FIREBASE_MEASUREMENT_ID=G-7MXBNH3N7D"
```

### Any Docker host

```bash
docker build -f deploy/Dockerfile -t srm-trp-transport:latest .
docker run -d --name srm-trp -p 8080:8080 --env-file .env.production srm-trp-transport:latest
```

---

## 7. Before going live — checklist

- [ ] Rotate the compromised MongoDB credential that was previously committed
      to Git history, and purge the old credential from history.
- [ ] Set a strong `JWT_SECRET` (32+ characters).
- [ ] Set `COOKIE_SECURE=true` (the default when `ENVIRONMENT=production`).
- [ ] Set `DEVICE_API_KEYS` to the real detector keys.
- [ ] Put the API key in the host's secret store, not in the repo.
- [ ] Restrict the MongoDB network access rules.
- [ ] Confirm the analytics events arrive in the Firebase console.
- [ ] Verify the operator webcam works over HTTPS (the camera API requires a
      secure context).
