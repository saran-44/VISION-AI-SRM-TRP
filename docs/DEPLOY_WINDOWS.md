# Deploying from Windows with Git Bash

Everything below is a **Git Bash** command. Git Bash ships with Git for
Windows, so it is already a POSIX shell — but it is a *terminal*, not a
toolchain. It does not contain Node.js, Python, the Firebase CLI or the Google
Cloud CLI. This guide installs those, logs in, and deploys.

The order matters: **install → log in → deploy**.

| Phase | What happens | Section |
| --- | --- | --- |
| 1. Install | Node.js, Python, Firebase CLI, Google Cloud CLI | [§1](#1-install-the-toolchain) |
| 2. Log in | Firebase + Google Cloud + one-time GCP setup | [§2](#2-log-in) |
| 3. Deploy | Backend to Cloud Run, frontend to Firebase Hosting | [§3](#3-deploy) |

---

## 0. Before you start

**What the deployment consists of:**

| Piece | Goes to | Deployed by |
| --- | --- | --- |
| `frontend/` — the console (static files) | Firebase Hosting | `firebase deploy --only hosting` |
| `backend/` — the Flask API | Google Cloud Run | `gcloud builds submit` (Cloud Build) |
| `best.pt` — the YOLO checkpoint | inside the backend image | same build |
| Access list (who may sign in) | MongoDB | `backend/manage_access.py` |

The two halves meet through the `/api/**` rewrite in `firebase.json`, so the
browser sees one origin and the session cookie works as `SameSite=Lax`.

**You need:**

- A Firebase project — the repo is already wired for **`srmtrpai`**
- A Google Cloud project for Cloud Run/Build, and permission to deploy
- A MongoDB database (Atlas or self-hosted) with a **rotated** credential
- Node.js and the Firebase CLI
- The Google Cloud CLI (`gcloud`)

> **Docker Desktop is *not* required** if you deploy the backend with
> `gcloud builds submit` — Cloud Build builds the image on Google's own
> Docker builder. Install Docker only if you plan to run the backend on a
> plain Docker host (see [§3.4](#34-alternative-deploy-the-backend-to-a-plain-docker-host)).

---

## 1. Install the toolchain

### 1.1 Check what you already have

```bash
node --version      # need >= 18 for firebase-tools
npm --version
python --version    # need 3.11
firebase --version
gcloud --version
docker --version    # optional
```

Anything that prints "command not found" has to be installed below.

### 1.2 Install Node.js (for the Firebase CLI)

`winget` is the Windows package manager. If it is not found in Git Bash, call
it by its full path:

```bash
winget install --id OpenJS.NodeJS.LTS --source winget
# If that fails with "command not found":
"/c/Users/$USERNAME/AppData/Local/Microsoft/WindowsApps/winget.exe" install --id OpenJS.NodeJS.LTS --source winget
```

> **Close and reopen Git Bash afterwards.** A new `PATH` entry added by the
> installer is not visible in the shell you already have open.

```bash
node --version
npm --version
```

### 1.3 Install Python 3.11

```bash
winget install --id Python.Python.3.11 --source winget
```

Reopen Git Bash, then:

```bash
python --version          # Python 3.11.x
# If "python" is not found but the launcher is:
py -3.11 --version
```

> The Python installer must tick **"Add python.exe to PATH"**. If you skipped
> it, run the installer again with *Modify* and enable it.

### 1.4 Install the Firebase CLI

```bash
npm install -g firebase-tools
firebase --version
```

If `firebase` is not found, npm installed it somewhere that is not on `PATH`:

```bash
npm config get prefix
# e.g. C:\Users\you\AppData\Roaming\npm   ->   /c/Users/you/AppData/Roaming/npm

# Use it for this session:
export PATH="$(npm config get prefix)":$PATH
# ...and permanently, for every future Git Bash window:
echo 'export PATH="$(npm config get prefix)":$PATH' >> ~/.bashrc
```

Then re-open Git Bash and confirm:

```bash
firebase --version
```

### 1.5 Install the Google Cloud CLI

`gcloud` is **not** available through `winget` on every machine. Use the
official installer:

```bash
# Download and run the Windows installer, or use winget if it has the package:
winget install --id Google.CloudSDK --source winget
```

If `winget` does not carry it, download the archive from
<https://cloud.google.com/sdk/docs/install> — unzip it and run
`./google-cloud-sdk/install.bat`, keeping the default location
(`C:\Users\you\AppData\Local\Google\Cloud SDK`). Then in Git Bash:

```bash
export PATH="$PATH:/c/Users/$USERNAME/AppData/Local/Google/Cloud SDK/bin"
echo 'export PATH="$PATH:/c/Users/$USERNAME/AppData/Local/Google/Cloud SDK/bin"' >> ~/.bashrc
```

Reopen Git Bash and confirm:

```bash
gcloud --version
gcloud init    # sets defaults; opens a browser
```

### 1.6 (Optional) Docker Desktop

Only needed for [§3.4](#34-alternative-deploy-the-backend-to-a-plain-docker-host):

```bash
winget install --id Docker.DockerDesktop --source winget
docker --version
```

### 1.7 (Optional) GitHub CLI

Useful for the branch/PR workflow in
[§17 of the upgrade specification](UPGRADE_SPECIFICATION.md#17-git-and-git-bash-command-reference):

```bash
winget install --id GitHub.cli --source winget
gh --version
gh auth login
```

### 1.8 Clone the repository and build the Python environment

```bash
cd /c/Users/you        # or wherever you keep projects
git clone https://github.com/saran-44/frontend.git
cd frontend

git config user.name  "Your Name"
git config user.email "you@example.com"

# Never commit credentials — .env is already git-ignored.
cp .env.example .env
```

> **`.env` is loaded automatically.** The application and access-list CLI
> read the repository-root `.env`; values already exported in the shell take
> precedence. Edit `.env` privately, rather than putting credentials into a
> shell command or chat. The app requires `MONGO_URI` (not `MONGODB_URI`)
> and the value must be the raw Atlas connection string, not a Markdown link:
>
> ```text
> MONGO_URI=mongodb+srv://USER:URL_ENCODED_PASSWORD@ATLAS_HOST/?retryWrites=true&w=majority
> MONGO_DB_NAME=srmtrpai
> ```
>
> Use the rotated credential, percent-encoding reserved characters in the
> username and password. `.env` is Git-ignored but is still a plaintext local
> file; protect it and never share it. Use Secret Manager for Cloud Run.
>
> **Use the same database everywhere.** The unmodified Cloud Build config
> sets `MONGO_DB_NAME=srmtrpai`; `.env.example` uses a different local default,
> so change the local value before managing the production access list. If
> `MONGO_DB_NAME` is unset, the app uses the URI path or `transport_db`.
>
> **Keep previews isolated.** If `.env` points to Atlas, the preview runner
> refuses to connect to it by default. After activating the virtual
> environment, force an in-memory preview with:
>
> ```bash
> MONGO_URI=mongomock://transport_preview python scripts/run_preview.py
> ```

Create the virtual environment. **On Windows the scripts live in `Scripts/`,
not `bin/`** — this is the single most common Git Bash mistake:

```bash
python -m venv .venv
source .venv/Scripts/activate      # NOT .venv/bin/activate
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
```

Verify:

```bash
python -m pytest backend/tests -q    # all tests should pass
python -m backend.manage_access --help   # checks the CLI without connecting to MongoDB
```

> The detector (Torch, Ultralytics, OpenCV) is an **optional extra**. Install
> it only if you need `/api/detection/*` on your own machine:
>
> ```bash
> pip install -r backend/requirements-vision.txt \
>   --extra-index-url https://download.pytorch.org/whl/cpu
> ```

---

## 2. Log in

### 2.1 Firebase CLI

```bash
firebase login          # opens a browser, paste the code back
firebase projects:list # confirm "srmtrpai" appears
```

The repo already contains `.firebaserc` with `srmtrpai` as the default
project, so this is usually enough:

```bash
firebase use             # prints: Now using project srmtrpai
# or, to choose explicitly:
firebase use --add       # pick "srmtrpai"
```

### 2.2 Google Cloud CLI

```bash
gcloud auth login                      # opens a browser
gcloud config set project srmtrpai
gcloud config set compute/region asia-south1
gcloud config set artifact/region asia-south1
gcloud config list
```

> If the Google Cloud project is **not** `srmtrpai`, set the real project id
> here and update the `_FIREBASE_PROJECT` substitution in
> `deploy/cloudbuild.yaml` to match.

### 2.3 One-time Google Cloud setup

Enable the APIs the build needs:

```bash
gcloud services enable \
  cloudbuild.googleapis.com \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  cloudresourcemanager.googleapis.com \
  iam.googleapis.com
```

Create the container repository the build pushes to:

```bash
gcloud artifacts repositories create srm-trp \
  --repository-format=docker \
  --location=asia-south1 \
  --description "SRM TRP Transport backend images"
```

If it already exists, that command is harmless — it reports the failure and
you carry on.

Create the four secrets the Cloud Run service reads. `deploy/cloudbuild.yaml`
maps them like this:

| Secret Manager name | Environment variable on Cloud Run | Value |
| --- | --- | --- |
| `mongo-uri` | `MONGO_URI` | the MongoDB connection string |
| `jwt-secret` | `JWT_SECRET` | ≥ 32 random characters |
| `device-keys` | `DEVICE_API_KEYS` | comma-separated detector keys |
| `firebase-api-key` | `FIREBASE_API_KEY` | the Firebase web API key |

```bash
# Disable command tracing so pasted values do not appear in the terminal.
set +x

# --- rotated MongoDB credential: paste at the hidden prompt, not in the command ---
read -r -s -p "Rotated Atlas connection string (hidden): " MONGO_URI
printf '\n'
if [ -n "$MONGO_URI" ]; then
  printf '%s' "$MONGO_URI" | gcloud secrets create mongo-uri --data-file=- --replication-policy=automatic
else
  echo "No URI entered; mongo-uri was not created." >&2
fi
unset MONGO_URI

# --- a strong session-signing key (generated, never typed by hand) ---
printf '%s' "$(python -c 'import secrets; print(secrets.token_urlsafe(48))')" \
  | gcloud secrets create jwt-secret --data-file=- --replication-policy=automatic

# --- comma-separated detector device keys ---
read -r -s -p "Detector device keys (hidden): " DEVICE_API_KEYS
printf '\n'
if [ -n "$DEVICE_API_KEYS" ]; then
  printf '%s' "$DEVICE_API_KEYS" | gcloud secrets create device-keys --data-file=- --replication-policy=automatic
else
  echo "No device keys entered; device-keys was not created." >&2
fi
unset DEVICE_API_KEYS

# --- Firebase web API key (Project settings > General > Your apps) ---
read -r -s -p "Firebase web API key (hidden): " FIREBASE_API_KEY
printf '\n'
if [ -n "$FIREBASE_API_KEY" ]; then
  printf '%s' "$FIREBASE_API_KEY" | gcloud secrets create firebase-api-key --data-file=- --replication-policy=automatic
else
  echo "No key entered; firebase-api-key was not created." >&2
fi
unset FIREBASE_API_KEY
```

> The hidden prompts keep values out of shell history. `printf '%s'` (not
> `echo`) writes them without a trailing newline. If `mongo-uri` already
> exists, rotate the Atlas user first and add a new version instead:
>
> ```bash
> set +x
> read -r -s -p "New Atlas connection string (hidden): " MONGO_URI
> printf '\n'
> if [ -n "$MONGO_URI" ]; then
>   printf '%s' "$MONGO_URI" | gcloud secrets versions add mongo-uri --data-file=-
> else
>   echo "No URI entered; no version was added." >&2
> fi
> unset MONGO_URI
> ```
>
> Redeploy the backend afterward so Cloud Run instances pick up the new
> secret version.

**Set up both service identities.** Cloud Build deploys the service, but the
Cloud Run **runtime service account** reads the secrets. They may be different
accounts. New projects do not necessarily use the legacy Cloud Build account.

1. Run `gcloud builds get-default-service-account` and note the account email.
   If a custom build account is configured, use that account instead. For an
   existing Cloud Run service, find its runtime account with:

   ```bash
   gcloud run services describe srm-trp-transport --region asia-south1 \
     --format='value(spec.template.spec.serviceAccountName)'
   ```

   A new service normally uses the project's Compute Engine default account
   unless another service identity is selected. Confirm the actual runtime
   identity in the Google Cloud console; do not guess if the account is absent
   or a custom identity is configured.

2. Substitute those **account emails** below (these are not database
   credentials), then grant the runtime identity access to only the four
   required secrets:

   ```bash
   BUILD_SA="BUILD_SERVICE_ACCOUNT_EMAIL"
   RUN_SA="CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT_EMAIL"

   for secret in mongo-uri jwt-secret device-keys firebase-api-key; do
     gcloud secrets add-iam-policy-binding "$secret" \
       --member="serviceAccount:$RUN_SA" \
       --role="roles/secretmanager.secretAccessor"
   done

   gcloud projects add-iam-policy-binding srmtrpai \
     --member="serviceAccount:$BUILD_SA" --role="roles/run.admin"
   gcloud artifacts repositories add-iam-policy-binding srm-trp \
     --location=asia-south1 --member="serviceAccount:$BUILD_SA" \
     --role="roles/artifactregistry.writer"
   gcloud projects add-iam-policy-binding srmtrpai \
     --member="serviceAccount:$BUILD_SA" --role="roles/logging.logWriter"
   gcloud iam service-accounts add-iam-policy-binding "$RUN_SA" \
     --member="serviceAccount:$BUILD_SA" --role="roles/iam.serviceAccountUser"
   ```

The person submitting the build also needs the appropriate Cloud Build and
service-account permissions. See Google's guides for
[Cloud Build deployment permissions](https://cloud.google.com/build/docs/deploying-builds/deploy-cloud-run#grant-permissions)
and [Cloud Run secret access](https://cloud.google.com/run/docs/configuring/services/secrets#make-secret-accessible).

### 2.4 Firebase console setup (the sign-in part)

This is the part that decides **who may use the portal**, and it is done in
the Firebase console, not in Git.

1. **Authentication → Sign-in method**
   - enable **Email/Password**
   - enable **Google**
2. **Authentication → Settings → Authorised domains** — add:
   - `srmtrpai.web.app`
   - `srmtrpai.firebaseapp.com`
   - `localhost` (for local development)
   - your own domain, if you have one
3. **Authentication → Users → Add user** — create each password account.
   Arrange email verification through Firebase, or have a trusted admin mark
   the address verified through the Firebase Admin SDK only after confirming
   mailbox ownership **and control of that Firebase account**. An attacker
   could have registered the address first. The backend rejects unverified
   emails.
4. **Project settings → General → Your apps → Web API Key** — copy the API
   key for the `firebase-api-key` secret above.

Add authorised Google and password emails to the **access list** by hand
([§3.3](#33-seed-the-access-list)). Alternatively, an administrator can
approve a verified password account for auto-provisioning using the custom
claim described in [`docs/AUTHENTICATION.md`](AUTHENTICATION.md#auto-provisioning).
A password sign-up by itself never grants portal access.

Full explanation: [`docs/AUTHENTICATION.md`](AUTHENTICATION.md).

---

## 3. Deploy

### 3.1 Backend → Cloud Run

```bash
cd /c/Users/you/frontend

# Deploy the commit that is on main
git fetch origin
git checkout main
git pull origin main

# Build the image and deploy it in one step
gcloud builds submit --config deploy/cloudbuild.yaml
```

The image is tagged with Cloud Build's unique `BUILD_ID` (and `latest`), so a
manual submission does not depend on the trigger-only `COMMIT_SHA` value.

Watch it in the browser (or follow the log in the terminal):

```bash
gcloud builds list --limit 5
gcloud builds log $(gcloud builds list --limit 1 --format='value(id)')
```

> `gcloud builds submit` uploads the working directory as the build context.
> There is no `.gcloudignore`, so gcloud falls back to `.gitignore` — which
> means `.env` and other secrets are **not** uploaded, and the three brand
> PNGs are explicitly un-ignored so they do get uploaded. The context is
> about 9 MB, so the upload is quick.

> **CRLF warning.** `deploy/Dockerfile` must have Unix line endings. A
> Windows checkout that rewrites LF as CRLF makes the build fail with
> `/bin/sh^M: not found`. The repository ships a `.gitattributes` that keeps
> text files LF — make sure your clone has it:
>
> ```bash
> git config core.autocrlf false
> git rm --cached -r . && git reset --hard   # re-apply the line-ending rules
> ```

### 3.2 Frontend → Firebase Hosting

```bash
cd /c/Users/you/frontend
firebase deploy --only hosting
```

This publishes `frontend/` and installs the `/api/**` rewrite to the Cloud Run
service `srm-trp-transport` in `asia-south1`.

### 3.3 Seed the access list

The access list lives in MongoDB and decides who may sign in. The CLI loads
`.env` automatically, so first ensure that file contains the **rotated**
`MONGO_URI`, a nonempty `JWT_SECRET`, and the same `MONGO_DB_NAME` as Cloud
Run (`srmtrpai` in the unmodified build configuration). Exported shell values
will override `.env` values. Then:

```bash
cd /c/Users/you/frontend
source .venv/Scripts/activate

# See who is allowed (the CLI also creates any missing application indexes)
python -m backend.manage_access list

# Allow a verified Google or password account
python -m backend.manage_access add principal@srmtrp.edu.in

# Give someone a different role
python -m backend.manage_access set-role transport.office@srmtrp.edu.in head_admin

# Suspend and restore
python -m backend.manage_access deactivate someone@srmtrp.edu.in
python -m backend.manage_access activate   someone@srmtrp.edu.in

# Forget a Firebase identity without deleting the person
python -m backend.manage_access unlink someone@srmtrp.edu.in
```

To avoid storing the URI in a local plaintext file, you can instead use a
session-only environment value. Run this before the CLI commands above, then
clear it afterward:

```bash
set +x
read -r -s -p "Rotated Atlas connection string (hidden): " MONGO_URI
printf '\n'
export MONGO_URI
export MONGO_DB_NAME=srmtrpai
# The CLI requires a nonempty JWT_SECRET but does not sign sessions.
export JWT_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"

# Run the needed python -m backend.manage_access commands here.

unset MONGO_URI JWT_SECRET
```

Atlas must permit your workstation's public IP for the CLI connection. Cloud
Run has a separate outbound network path: for production, arrange a fixed
Cloud Run egress IP or private connectivity and allow that path in Atlas as
well. Do not assume that allowing your workstation also allows Cloud Run. See
[Cloud Run's static outbound IP guide](https://cloud.google.com/run/docs/configuring/static-outbound-ip).

> All Firebase users must have verified email addresses. An unknown password
> account is auto-provisioned only when a Firebase administrator has set its
> `transport_portal_approved_email` custom claim to that verified address and
> auto-provisioning is enabled. Google accounts are **never** auto-provisioned;
> their verified email must already be on the access list.

### 3.4 Alternative: deploy the backend to a plain Docker host

If you are not using Cloud Run:

```bash
cd /c/Users/you/frontend

docker build -f deploy/Dockerfile -t srm-trp-transport:latest .

docker run -d --name srm-trp -p 8080:8080 --env-file .env.production \
  srm-trp-transport:latest
```

`.env.production` must contain at least:

```text
ENVIRONMENT=production
MONGO_URI=mongodb+srv://...
MONGO_DB_NAME=srmtrpai
JWT_SECRET=<32+ random characters>
DEVICE_API_KEYS=detector-key-one,detector-key-two
COOKIE_SECURE=true
APP_TIMEZONE=Asia/Kolkata
FIREBASE_PROJECT_ID=srmtrpai
FIREBASE_AUTH_DOMAIN=srmtrpai.firebaseapp.com
FIREBASE_STORAGE_BUCKET=srmtrpai.firebasestorage.app
FIREBASE_MESSAGING_SENDER_ID=734375891811
FIREBASE_APP_ID=1:734375891811:web:6851938bef332bc0e53956
FIREBASE_MEASUREMENT_ID=G-7MXBNH3N7D
FIREBASE_API_KEY=AIzaSy...
FIREBASE_AUTH_ENABLED=true
FIREBASE_ALLOWED_PROVIDERS=password,google.com
FIREBASE_AUTO_PROVISION=true
FIREBASE_DEFAULT_ROLE=transport_office
LEGACY_PASSWORD_LOGIN_ENABLED=false
```

> If the backend is **not** behind Firebase Hosting, set
> `CORS_ALLOWED_ORIGINS` to the exact origin that serves the frontend —
> never a wildcard; the backend rejects wildcards at startup.

---

## 4. Verify

```bash
# Backend health
curl -s https://srm-trp-transport-xxxxxxxx-asia-south1.a.run.app/api/health

# The hosted console
curl -s -o /dev/null -w "%{http_code}\n" https://srmtrpai.web.app/

# The public Firebase configuration the browser will receive
curl -s https://srmtrpai.web.app/api/config/firebase

# Which sign-in methods the deployment offers
curl -s https://srmtrpai.web.app/api/auth/config
```

Expected:

```json
{"mode":"firebase","firebase":{"enabled":true,"providers":["password","google.com"],"auto_provision":true},"legacy_password_login":true}
```

Then sign in at **https://srmtrpai.web.app/** with an account you created in
the Firebase console.

---

## 5. Update and roll back

**Update:**

```bash
cd /c/Users/you/frontend
git pull origin main
gcloud builds submit --config deploy/cloudbuild.yaml
firebase deploy --only hosting
```

**Roll back the backend to a previous revision:**

```bash
gcloud run revisions list --service srm-trp-transport --region asia-south1
# Replace REVISION_ID with the full name of a known-good revision.
gcloud run services update-traffic srm-trp-transport --region asia-south1 \
  --to-revisions=REVISION_ID=100
```

**Roll back the frontend:** In Firebase console → **Hosting & Serverless →
Hosting → Release history**, open the menu for the known-good release and
select **Roll back**. See
[Firebase's rollback instructions](https://firebase.google.com/docs/hosting/manage-hosting-resources#roll-back).
This repository's Hosting rewrite is not pinned to a Cloud Run revision, so
rolling back Hosting does not roll back the backend.

---

## 6. Windows-specific troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `command not found: node` after installing | the shell has the old `PATH` | close and reopen Git Bash |
| `command not found: firebase` | npm's global prefix is not on `PATH` | see [§1.4](#14-install-the-firebase-cli) |
| `command not found: gcloud` | the SDK is not on `PATH` | see [§1.5](#15-install-the-google-cloud-cli) |
| `source .venv/bin/activate: No such file` | Windows puts the venv scripts in `Scripts/` | `source .venv/Scripts/activate` |
| `python: command not found` | the Python installer did not add it to `PATH` | re-run the installer with *Modify* |
| Docker build fails with `/bin/sh^M: not found` | CRLF line endings | see the CRLF warning in [§3.1](#31-backend--cloud-run) |
| `firebase deploy` asks for a project | `.firebaserc` was not cloned | `firebase use --add` |
| Deployment fails on secrets | the Cloud Run runtime identity lacks secret access | see [§2.3](#23-one-time-google-cloud-setup) |
| `MONGO_URI` fails to authenticate | the secret has a trailing newline | recreate with `printf '%s'`, not `echo` |
| Google sign-in says *unauthorized domain* | the hosting domain is not authorised | [§2.4](#24-firebase-console-setup-the-sign-in-part) |
| A Google account is refused | it is not on the access list | [§3.3](#33-seed-the-access-list) |

---

## 7. Before you go live

- [ ] **Revoke or rotate the MongoDB credential leaked in Git history** and
      purge the history. A new credential does not prove that an old one was
      revoked. Rotate any other credential exposed in chat or logs separately.
      See [§19 of the upgrade specification](UPGRADE_SPECIFICATION.md#19-outstanding-work-and-known-risks).
- [ ] `JWT_SECRET` is 32+ random characters.
- [ ] `COOKIE_SECURE=true` (the default when `ENVIRONMENT=production`).
- [ ] `DEVICE_API_KEYS` holds the real detector keys.
- [ ] The Firebase API key is in Secret Manager, **not** in the repository.
- [ ] MongoDB network access rules are restricted.
- [ ] `LEGACY_PASSWORD_LOGIN_ENABLED=false` once everybody uses Firebase.
- [ ] The authorised domains list matches the domains you actually serve.
- [ ] The operator webcam works over HTTPS (the camera API needs a secure
      context).
