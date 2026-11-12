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
python -m pytest backend/tests -q    # expect: 115 passed
python -m backend.manage_access list
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
  secretmanager.googleapis.com
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
# --- the rotated MongoDB credential ---
printf '%s' "mongodb+srv://USER:PASSWORD@cluster.mongodb.net/?retryWrites=true&w=majority" \
  | gcloud secrets create mongo-uri --data-file=- --replication-policy=automatic

# --- a strong session-signing key (generated, never typed by hand) ---
printf '%s' "$(python -c 'import secrets; print(secrets.token_urlsafe(48))')" \
  | gcloud secrets create jwt-secret --data-file=- --replication-policy=automatic

# --- detector device keys ---
printf '%s' "detector-key-one,detector-key-two" \
  | gcloud secrets create device-keys --data-file=- --replication-policy=automatic

# --- the Firebase web API key (Firebase console > Project settings > Web API Key) ---
printf '%s' "AIzaSy...your-key..." \
  | gcloud secrets create firebase-api-key --data-file=- --replication-policy=automatic
```

> `printf '%s'` (not `echo`) writes the value **without a trailing newline** —
> a stray newline in `MONGO_URI` or `JWT_SECRET` is a classic source of
> "authentication failed" errors that are hard to see.
>
> To rotate a secret later, add a new version rather than recreating it:
>
> ```bash
> printf '%s' "new-value" | gcloud secrets add-version jwt-secret --data-file=-
> ```

Give the Cloud Build service account permission to read those secrets:

```bash
PROJECT_NUMBER=$(gcloud projects describe srmtrpai --format='value(projectNumber)')
PROJECT_EMAIL="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"

gcloud projects add-iam-policy-binding srmtrpai \
  --member "serviceAccount:${PROJECT_EMAIL}" \
  --role "roles/secretmanager.secretAccessor"

gcloud projects add-iam-policy-binding srmtrpai \
  --member "serviceAccount:${PROJECT_EMAIL}" \
  --role "roles/run.admin"
```

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
3. **Authentication → Users → Add user** — for every person who signs in with
   a password: enter the email, set a password, and tick
   **"Add email verified"**.
4. **Project settings → General → Your apps → Web API Key** — copy the API
   key for the `firebase-api-key` secret above.

Google accounts cannot be curated in the Firebase console, so every
authorised Google email must be added to the **access list** by hand
([§3.3](#33-seed-the-access-list)).

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

The access list lives in MongoDB and decides who may sign in. It is managed
with the CLI, from your machine, against the same database the backend uses:

```bash
cd /c/Users/you/frontend
source .venv/Scripts/activate

export MONGO_URI="mongodb+srv://USER:PASSWORD@cluster.mongodb.net/?retryWrites=true&w=majority"
export JWT_SECRET="local-only-secret-not-used-by-the-cli"

# See who is allowed
python -m backend.manage_access list

# Allow a Google account (must exist before the person first signs in)
python -m backend.manage_access add principal@srmtrp.edu.in

# Give someone a different role
python -m backend.manage_access set-role transport.office@srmtrp.edu.in head_admin

# Suspend and restore
python -m backend.manage_access deactivate someone@srmtrp.edu.in
python -m backend.manage_access activate   someone@srmtrp.edu.in

# Forget a Firebase identity without deleting the person
python -m backend.manage_access unlink someone@srmtrp.edu.in
```

> Password accounts created in the Firebase console are **auto-provisioned**
> on first sign-in with the default role (`transport_office`). Google
> accounts are **never** auto-provisioned — if the email is not on the access
> list, Google sign-in is refused even though Firebase accepted the
> credential.

### 3.4 Alternative: deploy the backend to a plain Docker host

If you are not using Cloud Run:

```bash
cd /c/Users/you/frontend

docker build -f deploy/Dockerfile -t srm-trp-transport:latest .

docker run -d --name srm-trp -p 8080:8080 --env-file .env.production \
  srm-trp-transport:latest
```

`.env.production` must contain at least:

```bash
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
{"mode":"firebase","firebase":{"enabled":true,"providers":["password","google.com"],"auto_provision":true},"legacy_password_login":false}
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
gcloud run revisions activate REVISION_ID --service srm-trp-transport --region asia-south1
```

**Roll back the frontend:**

```bash
firebase hosting:rollback
```

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
| `gcloud builds submit` fails on secrets | the build service account cannot read them | see [§2.3](#23-one-time-google-cloud-setup) |
| `MONGO_URI` fails to authenticate | the secret has a trailing newline | recreate with `printf '%s'`, not `echo` |
| Google sign-in says *unauthorized domain* | the hosting domain is not authorised | [§2.4](#24-firebase-console-setup-the-sign-in-part) |
| A Google account is refused | it is not on the access list | [§3.3](#33-seed-the-access-list) |

---

## 7. Before you go live

- [ ] **Rotate the leaked MongoDB credential** that was previously committed
      to Git history, and purge the old credential from the history. This is
      a production blocker — see
      [§19 of the upgrade specification](UPGRADE_SPECIFICATION.md#19-outstanding-work-and-known-risks).
- [ ] `JWT_SECRET` is 32+ random characters.
- [ ] `COOKIE_SECURE=true` (the default when `ENVIRONMENT=production`).
- [ ] `DEVICE_API_KEYS` holds the real detector keys.
- [ ] The Firebase API key is in Secret Manager, **not** in the repository.
- [ ] MongoDB network access rules are restricted.
- [ ] `LEGACY_PASSWORD_LOGIN_ENABLED=false` once everybody uses Firebase.
- [ ] The authorised domains list matches the domains you actually serve.
- [ ] The operator webcam works over HTTPS (the camera API needs a secure
      context).
