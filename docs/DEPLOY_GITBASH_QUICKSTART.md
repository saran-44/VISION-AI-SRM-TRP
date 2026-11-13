# Git Bash quickstart: Firebase Hosting + Cloud Run + Supabase

The shortest ordered path from a fresh Git Bash install to a working deployment
of this repository on:

| Piece | Runs on | What it does |
| --- | --- | --- |
| Frontend + routing | **Firebase Hosting** | Serves `frontend/`, rewrites everything else to the API |
| Flask API (`backend/`) | **Cloud Run** (`asia-south1`) | Auth, RBAC, validation, exports, detection |
| Database | **Supabase PostgreSQL** | Private `transport_portal` schema |
| Sign-in | **Firebase Authentication** | Email/password + Google |

> **No billing card?** Cloud Run requires billing to be enabled even inside the
> free tier. Use [`DEPLOY_RENDER_FREE.md`](DEPLOY_RENDER_FREE.md) instead: one
> free Render Docker service serves both the API and the frontend, Supabase
> stays the database, Firebase stays the sign-in provider.

> **Supabase cannot run this backend.** Supabase hosts PostgreSQL, Storage, Auth
> and Deno-based Edge Functions — it does not run Flask/gunicorn or a Python
> `Dockerfile`. This repository keeps Flask on Cloud Run (a Google service next
> to Firebase) and uses Supabase only as the Postgres database. A
> " backend in Supabase" deployment would require rewriting `backend/` for Edge
> Functions. Do not attempt it before the app is live.

For the fully hardened variant (dedicated build identity, Direct VPC egress,
Cloud NAT, Secret Manager rotation, rollback) use
[`DEPLOY_WINDOWS.md`](DEPLOY_WINDOWS.md). This page is the fast path; it skips
the VPC because Supabase network restrictions are off by default. Turn those
restrictions on later and then switch to the hardened runbook.

**Rules that never change**

- Never commit `.env`, paste a database URL, password, ID token, device key or
  service-account key into chat, a command argument, or Git.
- The Firebase **web** API key is a public browser identifier, not a secret.
- `.env` must stay git-ignored; `.env.example` keeps placeholders only.
- Run every block in order and stop at the first error.

---

## 0. Conventions

Every block is meant to be pasted into **Git Bash** (not PowerShell, not CMD).
Shell variables do not survive a closed window — after reopening Git Bash,
re-run the `export` block below.

```bash
export PROJECT_ID=vision-ai-srmtrp
export REGION=asia-south1
export SERVICE=srm-trp-transport
export REPO=srm-trp
export RUN_SA="srm-trp-run@${PROJECT_ID}.iam.gserviceaccount.com"
```

The repository already pins these in `.firebaserc`, `firebase.json` and
`deploy/cloudbuild.yaml`. Change them **only** if you deliberately use another
Google Cloud project, and change all three files together.

---

## 1. Install and verify the tools

```bash
WINGET=winget.exe
if ! command -v "$WINGET" >/dev/null 2>&1; then
  WINGET="$(cygpath -u "$LOCALAPPDATA")/Microsoft/WindowsApps/winget.exe"
fi
"$WINGET" install --exact --id OpenJS.NodeJS.LTS --source winget
"$WINGET" install --exact --id Python.Python.3.11 --source winget
"$WINGET" install --exact --id Google.CloudSDK --source winget
```

Close **all** Git Bash windows, open a new one, then:

```bash
git --version && node --version && npm --version && py -3.11 --version && gcloud --version
npm install -g firebase-tools
firebase --version
```

If a command is "not found" right after installing, refresh `PATH`:

```bash
export PATH="/c/Program Files/nodejs:$PATH"
export PATH="$(cygpath -u "$LOCALAPPDATA")/Google/Cloud SDK/google-cloud-sdk/bin:$PATH"
export PATH="$(cygpath -u "$(npm config get prefix)"):$PATH"
hash -r
```

Never use the Windows Store `python` alias (it opens the Store). Use `py -3.11`
or the real executable inside `.venv`.

---

## 2. Get the code and a working local environment

```bash
cd ~
git clone https://github.com/saran-44/VISION-AI-SRM-TRP.git
cd VISION-AI-SRM-TRP
git status --short && git log -1 --oneline
git grep -n 'CREATE SCHEMA transport_portal' -- backend/sql/001_initial.sql
```

If you already have a checkout, `cd` into it and `git pull --ff-only` instead of
cloning over it. If the second command prints nothing, stop — the branch you are
on does not contain the Supabase schema.

```bash
if [ ! -f .venv/Scripts/activate ]; then py -3.11 -m venv .venv; fi
source .venv/Scripts/activate
python --version
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
unset TEST_DATABASE_URL ALLOW_TEST_DATABASE_RESET
python -m pytest -q
```

Expect `178 passed, 4 skipped` (or similar). These tests use disposable
in-memory SQLite and never touch Supabase. If they fail, fix that first.

---

## 3. Create the Supabase database

All of this is in the Supabase **dashboard** — there is no CLI step.

1. **New project.** Name it, and choose region **South Asia (Mumbai)**
   (`ap-south-1`) — lowest latency from Tamil Nadu. Save the database password
   in a password manager. Never paste it into chat.
2. **SQL Editor → New query.** Open the migration locally so you can read it:

   ```bash
   notepad.exe "$(cygpath -w "$PWD/backend/sql/001_initial.sql")"
   ```

   Paste the **entire** file into the editor and press **Run** exactly once. It
   creates `transport_portal` in one transaction and fails loudly if the schema
   already exists. Do not add `transport_portal` to the exposed Data API schema.
3. **Project Settings → Database → SSL Configuration → Download certificate.**
   Save it somewhere stable and private, e.g. `C:/Users/<you>/srm-trp-private/prod-ca-2021.crt`.
   The app connects with `sslmode=verify-full`, so this file is mandatory.
4. **Connect (top bar) → Session pooler.** Copy the **host** only, e.g.
   `aws-1-ap-south-1.pooler.supabase.com`, and note the **project reference**
   (the subdomain of your project URL, e.g. `abcdefghijklmnop`).
5. Leave **Network Restrictions** disabled for this fast path. If you enable
   them, you must also allow your workstation IP **and** a Cloud NAT IP, which
   means switching to `DEPLOY_WINDOWS.md`.

Now create the least-privilege application login and a private `.env`:

```bash
source .venv/Scripts/activate
[ -e .env ] && echo 'STOP: .env exists — back it up and move it aside first.' || \
  winpty python scripts/configure_supabase.py
```

`winpty` is required: it lets Git Bash show the hidden password prompt. When
asked, enter the **session-pooler host**, the **project reference**, the
**Windows path** of the downloaded CA certificate, and the Supabase database
password (hidden), then type `CREATE`.

The script creates role `transport_portal_app`, grants it only the application
tables (audit logs are append/read only), writes a git-ignored `.env` with fresh
`JWT_SECRET` and `DEVICE_API_KEYS`, and then **verifies** that the new login can
actually read every table. It never overwrites an existing `.env` or role.

Sanity check without printing secrets:

```bash
python -c 'from dotenv import dotenv_values; v=dotenv_values(".env"); print("db host set:", "pooler.supabase.com" in v["DATABASE_URL"]); print("ca:", v["PGSSLROOTCERT"]); print("jwt length:", len(v["JWT_SECRET"]))'
python -m backend.manage_access list
```

`list` should succeed and print an empty table — that proves TLS, DNS, the CA
certificate and the grants all work from your machine.

---

## 4. Point Google Cloud at the project

```bash
gcloud auth login
firebase login
gcloud config set project "$PROJECT_ID"
gcloud config set run/region "$REGION"
gcloud projects describe "$PROJECT_ID" --format='value(projectId,lifecycleState)'
gcloud billing projects describe "$PROJECT_ID" --format='value(billingEnabled)'
firebase projects:list
```

Billing must be **enabled** — Cloud Run, Cloud Build and Artifact Registry do not
work on an unbilled project (they still fit inside the free tier for this app).
Verify the Firebase web app, do **not** create a duplicate:

```bash
firebase apps:list WEB --project="$PROJECT_ID"
firebase hosting:sites:list --project="$PROJECT_ID" --json
```

`DEFAULT_SITE` should be `vision-ai-srmtrp`; the web app ID should be
`1:235811571442:web:342e488e0ac2ee75b0f26b`. If no default Hosting site exists:

```bash
firebase hosting:sites:create "$PROJECT_ID" --project="$PROJECT_ID"
```

Enable the APIs and create the image repository and runtime identity:

```bash
gcloud services enable \
  run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com iam.googleapis.com \
  --project="$PROJECT_ID"

gcloud artifacts repositories create "$REPO" --repository-format=docker \
  --location="$REGION" --description='SRM TRP Transport backend images' \
  --project="$PROJECT_ID"

gcloud iam service-accounts create srm-trp-run \
  --display-name='SRM TRP Cloud Run runtime' --project="$PROJECT_ID"
```

If a resource already exists, inspect it instead of recreating or deleting it:

```bash
gcloud artifacts repositories describe "$REPO" --location="$REGION" --project="$PROJECT_ID"
gcloud iam service-accounts describe "$RUN_SA" --project="$PROJECT_ID"
```

---

## 5. Put the runtime values in Secret Manager

Five secrets, matching `deploy/cloudbuild.yaml`:

| Secret | Becomes |
| --- | --- |
| `database-url` | `DATABASE_URL` |
| `supabase-ca` | file `/secrets/supabase-ca.crt` used by `PGSSLROOTCERT` |
| `jwt-secret` | `JWT_SECRET` |
| `device-keys` | `DEVICE_API_KEYS` |
| `firebase-api-key` | `FIREBASE_API_KEY` |

```bash
gcloud secrets list --project="$PROJECT_ID" --format='table(name,createTime)'

gcloud secrets create database-url      --replication-policy=automatic --project="$PROJECT_ID"
gcloud secrets create supabase-ca       --replication-policy=automatic --project="$PROJECT_ID"
gcloud secrets create jwt-secret        --replication-policy=automatic --project="$PROJECT_ID"
gcloud secrets create device-keys       --replication-policy=automatic --project="$PROJECT_ID"
gcloud secrets create firebase-api-key  --replication-policy=automatic --project="$PROJECT_ID"
```

Upload the values **from `.env` without printing them**:

```bash
source .venv/Scripts/activate
set +x
set -o pipefail
FAILED=0
for PAIR in DATABASE_URL:database-url JWT_SECRET:jwt-secret DEVICE_API_KEYS:device-keys FIREBASE_API_KEY:firebase-api-key; do
  ENV_NAME="${PAIR%%:*}"; SECRET_NAME="${PAIR#*:}"
  if ! python -c 'import sys; from dotenv import dotenv_values; v=dotenv_values(".env").get(sys.argv[1]); assert v, "missing"; sys.stdout.write(v)' "$ENV_NAME" \
       | gcloud secrets versions add "$SECRET_NAME" --data-file=- --project="$PROJECT_ID"; then
    FAILED=1; break
  fi
done
CA_PATH="$(python -c 'from dotenv import dotenv_values; print(dotenv_values(".env")["PGSSLROOTCERT"])')"
[ "$FAILED" -eq 0 ] && [ -n "$CA_PATH" ] && \
  gcloud secrets versions add supabase-ca --data-file="$CA_PATH" --project="$PROJECT_ID" && \
  echo 'All secrets uploaded.'
```

If the final line is missing, stop and inspect which versions were created
before retrying. Then let the runtime identity read exactly those secrets:

```bash
FAILED=0
for SECRET in database-url supabase-ca jwt-secret device-keys firebase-api-key; do
  gcloud secrets add-iam-policy-binding "$SECRET" --project="$PROJECT_ID" \
    --member="serviceAccount:$RUN_SA" \
    --role=roles/secretmanager.secretAccessor --condition=None || FAILED=1
done
[ "$FAILED" -eq 0 ] && echo 'Secret grants OK.'
```

---

## 6. Build the container image

```bash
cd ~/VISION-AI-SRM-TRP
source .venv/Scripts/activate
git status --short
export TAG="v$(date +%Y%m%d-%H%M%S)"
export IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${SERVICE}:${TAG}"

gcloud builds submit . --project="$PROJECT_ID" \
  --config=deploy/cloudbuild.quick.yaml \
  --substitutions=_REGION="$REGION",_REPOSITORY="$REPO",_SERVICE="$SERVICE",_TAG="$TAG"
```

`cloudbuild.quick.yaml` builds the same `deploy/Dockerfile` but, unlike
`cloudbuild.yaml`, does **not** create VPC/NAT resources or deploy for you.

Expect **10–25 minutes**: the image installs CPU torch, torchvision,
ultralytics and RapidOCR (~2–3 GB). Do not interrupt it.

To get a first deployment live quickly, skip the vision stack and rebuild later:

```bash
gcloud builds submit . --project="$PROJECT_ID" \
  --config=deploy/cloudbuild.quick.yaml \
  --substitutions=_REGION="$REGION",_REPOSITORY="$REPO",_SERVICE="$SERVICE",_TAG="$TAG",_INSTALL_VISION="0"
```

---

## 7. Deploy the API to Cloud Run

```bash
gcloud run deploy "$SERVICE" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --platform=managed \
  --image="$IMAGE" \
  --allow-unauthenticated \
  --port=8080 \
  --cpu=1 \
  --memory=2Gi \
  --timeout=300 \
  --min-instances=0 \
  --max-instances=4 \
  --service-account="$RUN_SA" \
  --set-env-vars="^|^ENVIRONMENT=production|PGSSLROOTCERT=/secrets/supabase-ca.crt|APP_TIMEZONE=Asia/Kolkata|FIREBASE_PROJECT_ID=${PROJECT_ID}|FIREBASE_AUTH_DOMAIN=${PROJECT_ID}.firebaseapp.com|FIREBASE_STORAGE_BUCKET=${PROJECT_ID}.firebasestorage.app|FIREBASE_MESSAGING_SENDER_ID=235811571442|FIREBASE_APP_ID=1:235811571442:web:342e488e0ac2ee75b0f26b|FIREBASE_MEASUREMENT_ID=G-S4HS9TGV4H|FIREBASE_ALLOWED_PROVIDERS=password,google.com|FIREBASE_AUTO_PROVISION=false|LEGACY_PASSWORD_LOGIN_ENABLED=false" \
  --set-secrets="DATABASE_URL=database-url:latest,JWT_SECRET=jwt-secret:latest,DEVICE_API_KEYS=device-keys:latest,FIREBASE_API_KEY=firebase-api-key:latest,/secrets/supabase-ca.crt=supabase-ca:latest" \
  --startup-probe="httpGet.path=/api/health,httpGet.port=8080,initialDelaySeconds=0,timeoutSeconds=5,periodSeconds=10,failureThreshold=24" \
  --quiet
```

- The `^|^` prefix is required because `FIREBASE_ALLOWED_PROVIDERS` contains a
  comma; it changes the delimiter for the whole flag. Keep it.
- The startup probe tolerates ~4 minutes of PostgreSQL retries, which covers a
  paused Supabase project and cold starts.
- `--allow-unauthenticated` is mandatory: Firebase Hosting forwards `/api/**`
  to this service without Google IAM credentials. The app still enforces its
  own session and device-key authorization.

Wait for the revision to become ready, then smoke-test:

```bash
RUN_URL="$(gcloud run services describe "$SERVICE" --region="$REGION" --project="$PROJECT_ID" --format='value(status.url)')"
echo "$RUN_URL"
curl -fsS "$RUN_URL/api/health" && echo
curl -fsS "$RUN_URL/api/auth/config" && echo
curl -sS -o /dev/null -w 'unauthenticated me: %{http_code}\n' "$RUN_URL/api/auth/me"
```

Expect health `ok` and `401` for `/api/auth/me`. If the service fails to start:

```bash
gcloud run services logs read "$SERVICE" --region="$REGION" --project="$PROJECT_ID" --limit=100
```

---

## 8. Turn on sign-in and grant the first administrator

Firebase Console → **Authentication**:

1. **Sign-in method** → enable **Email/Password** (and **Google** if you will
   use it, with a support email).
2. **Settings → Authorized domains** → make sure `vision-ai-srmtrp.web.app` and
   `vision-ai-srmtrp.firebaseapp.com` are listed.
3. **Users → Add user** → create the administrator, e.g.
   `814725105014@trp.srmtrichy.edu.in`, with a new strong password.

Verify that mailbox, then grant portal access **in Postgres** — a Firebase user
alone has no access because `FIREBASE_AUTO_PROVISION=false`:

```bash
source .venv/Scripts/activate
set +x
FIREBASE_WEB_API_KEY="$(python -c 'from dotenv import dotenv_values; print(dotenv_values(".env")["FIREBASE_API_KEY"])')"
read -r -s -p 'Firebase password for that account (hidden): ' FIREBASE_USER_PASSWORD
printf '\n'
export FIREBASE_WEB_API_KEY FIREBASE_USER_PASSWORD
python scripts/send_firebase_verification.py 814725105014@trp.srmtrichy.edu.in
```

Open the email, click the link, then:

```bash
python scripts/send_firebase_verification.py 814725105014@trp.srmtrichy.edu.in --check
unset FIREBASE_USER_PASSWORD FIREBASE_WEB_API_KEY
```

Then add the access entry:

```bash
python -m backend.manage_access add 814725105014@trp.srmtrichy.edu.in --role head_admin
python -m backend.manage_access list
```

Every other user also needs an explicit entry (`--role transport_office` for the
least-privilege office role). `frontend/pages/manage.html` can manage the list
from the browser once you are signed in as `head_admin`.

---

## 9. Publish Firebase Hosting

```bash
cd ~/VISION-AI-SRM-TRP
firebase deploy --only hosting --project="$PROJECT_ID"
firebase hosting:sites:list --project="$PROJECT_ID" --json
```

`frontend/pages/**` is excluded on purpose: those templates are rendered by
Flask, and a static copy would bypass page authorization.

---

## 10. Verify the live site

```bash
HOSTING_URL="https://${PROJECT_ID}.web.app"   # replace with the real defaultUrl

curl -fsS "$HOSTING_URL/api/health"; echo
curl -fsS "$HOSTING_URL/api/auth/config"; echo
curl -fsS "$HOSTING_URL/api/config/firebase" | \
  python -c 'import json,sys; d=json.load(sys.stdin); print("enabled:", d.get("enabled"), "project:", d.get("projectId"), "has key:", bool(d.get("config",{}).get("apiKey")))'
curl -sS -o /dev/null -w 'unauthenticated /api/auth/me: %{http_code}\n' "$HOSTING_URL/api/auth/me"
curl -sS -o /dev/null -w 'unauthenticated /dashboard: %{http_code}\n'     "$HOSTING_URL/dashboard"
curl -sS -L -o /dev/null -w 'direct template URL: %{http_code}\n'         "$HOSTING_URL/pages/dashboard.html"
```

Expected: health `ok`, Firebase `enabled: true` for `vision-ai-srmtrp` with a
key present, `401` for `me`, a redirect for `/dashboard`, and **404** for the
direct template URL.

Then, in a private browser window:

1. Sign in as the verified administrator and load `/dashboard`.
2. Sign out and confirm protected routes are refused.
3. Confirm the cookie is `__session`, `Secure`, `HttpOnly`, `SameSite=Lax`
   (DevTools → Application → Cookies; never copy its value).
4. Test an unapproved, unverified and inactive account — all must be denied.

---

## 11. Costs, limits and gotchas

| Item | Note |
| --- | --- |
| Cloud Run | Scales to zero; this workload usually stays inside the free tier |
| Artifact Registry | Stored image is ~2–3 GB ⇒ ~₹25–40/month; prune old tags |
| Supabase free tier | Project **pauses after ~7 days idle**; first request then takes up to ~4 minutes (the startup probe covers it) |
| Firebase Hosting | Backend requests are cut off at **60 s**, even though Cloud Run allows 300 s — long SSE/camera/detection calls can fail |
| Login throttling | `memory://` is per instance; set `RATELIMIT_STORAGE_URI` to Redis before running many instances |
| Detection | `best.pt` needs the torch/OCR layer; if you built with `_INSTALL_VISION=0`, `/api/detection/status` reports unavailable |
| Model licence | `best.pt` metadata cites Ultralytics **AGPL-3.0**; get written model/dataset rights before any public or commercial use |

Troubleshooting:

| Symptom | Cause / fix |
| --- | --- |
| Hosting returns 404 for everything | The Cloud Run service name/region does not match `firebase.json` (`srm-trp-transport`, `asia-south1`), or it is not public |
| `PostgreSQL initialization failed after retries` | Wrong CA path, missing `supabase-ca` secret, network restrictions, or a paused project |
| `schema version is missing or incompatible` | Step 3.2 migration was never run (or ran against another database) |
| Login fails for a valid Firebase user | No active row in the access list (`python -m backend.manage_access list`) |
| `firebase: command not found` | `npm install -g firebase-tools`, then refresh `PATH` and `hash -r` |
| `firebase login` hangs | Use `firebase login --no-localhost` and paste the code |
| Git Bash hides the password prompt / hangs | Prefix the command with `winpty` |
| `python` opens the Microsoft Store | Use `py -3.11` or `source .venv/Scripts/activate` |
| Build fails on torch install | Keep `machineType: E2_HIGHCPU_8`, or build with `_INSTALL_VISION=0` first |

Rollback:

```bash
gcloud run revisions list --service="$SERVICE" --region="$REGION" --project="$PROJECT_ID"
# after reviewing the old revision's secrets and config:
gcloud run services update-traffic "$SERVICE" --region="$REGION" --project="$PROJECT_ID" \
  --to-revisions=REVISION_ID=100
```

Hosting rollback is Firebase Console → Hosting → release history. Database
changes are never rolled back automatically.

---

## 12. Before you call it production

- [ ] Rotate every credential that was ever shared in chat or committed: the
      README notes an earlier credential still present in Git history. Rotating
      comes **first**; history rewriting comes after, and it does not clean
      forks, PRs or caches.
- [ ] Change the Supabase database password used at setup at least once, then
      update the `database-url` secret and redeploy.
- [ ] Enable Supabase backups and rehearse a restore; decide retention for
      driver and vehicle personal data (see `PRIVACY.md`).
- [ ] Move to the hardened runbook (`DEPLOY_WINDOWS.md`): dedicated build
      identity, Cloud NAT so Supabase network restrictions can be switched on,
      Redis-backed rate limiting, and `sslmode=verify-full` enforced in CI.
- [ ] Rehearse a device key rotation before real cameras post events.
