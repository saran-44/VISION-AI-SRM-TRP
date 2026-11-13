# Windows Git Bash: Supabase, Firebase and Cloud Run

This runbook targets repository `saran-44/VISION-AI-SRM-TRP`, Firebase/Google
Cloud project **`vision-ai-srmtrp`**, region **`asia-south1`**, Cloud Run
service **`srm-trp-transport`**, and initial administrator
**`814725105014@trp.srmtrichy.edu.in`**. It uses **Supabase PostgreSQL for
data** and **Firebase Authentication for sign-in**. It does not use Supabase
Auth or a Supabase service-role key.

> **Before starting**
>
> - No actual Supabase project, Firebase sign-in, Hosting rewrite or Cloud Run
>   deployment has been verified by the author. Confirm project ownership,
>   billing, permissions, backups and privacy requirements first.
> - **Old MongoDB data is not imported.** The new schema starts empty. If old
>   users, buses, drivers, events or audits are needed, stop and plan a tested
>   migration with the data owner before cutover. Back up the source; preserve
>   IDs, timestamps and audit history, reconcile row counts and verify every
>   access entry/UID. Switching Firebase projects changes identity context;
>   do not automatically trust or unlink old Firebase UID bindings.
> - Do not reuse a password previously shared in chat. Rotate/revoke both
>   exposed Atlas credentials and verify revocation, even if Atlas is no longer
>   used. Rotate any compromised app JWT secret; retire old reachable revisions.
> - Never paste database passwords, database URLs, ID tokens, service-account
>   keys, device keys or session cookies into chat, command arguments, logs or
>   Git. The Firebase **web** API key is a public browser identifier, not a
>   database password or a Supabase service-role key.
> - Cloud Run, Cloud Build, Artifact Registry, Secret Manager, VPC, reserved IP
>   and Cloud NAT may incur charges. The commands below change real resources.
>   Run each block in order and **stop on any error**; inspect an existing
>   resource before reusing it rather than deleting or replacing it.

## 1. Install tools and update the existing checkout

Install Git for Windows, Python 3.11, Node 20+, Google Cloud CLI and the
Firebase CLI. If missing, Git Bash on Windows can use `winget.exe`:

```bash
WINGET=winget.exe
if ! command -v "$WINGET" >/dev/null 2>&1; then
  WINGET="$(cygpath -u "$LOCALAPPDATA")/Microsoft/WindowsApps/winget.exe"
fi
"$WINGET" --version
# Run only the installers for tools you do not already have:
"$WINGET" install --exact --id OpenJS.NodeJS.LTS --source winget
"$WINGET" install --exact --id Python.Python.3.11 --source winget
"$WINGET" install --exact --id Google.CloudSDK --source winget
```

Close all Git Bash windows and reopen one after installing. Check the tools and
install the Firebase CLI:

```bash
git --version && node --version && npm --version && py -3.11 --version && gcloud --version
npm install -g firebase-tools@15.36.0
firebase --version
```

If a freshly installed command is not found, locate its actual installation;
common fallbacks are below (only use the ones that exist):

```bash
export PATH="/c/Program Files/nodejs:$PATH"
export PATH="$(cygpath -u "$LOCALAPPDATA")/Google/Cloud SDK/google-cloud-sdk/bin:$PATH"
NPM_PREFIX="$(npm config get prefix)"
export PATH="$(cygpath -u "$NPM_PREFIX"):$PATH"
hash -r
node --version && npm --version && gcloud --version && firebase --version
```

If the Windows Store Python alias opens the Store, use `py -3.11` or the real
Python executable, not the alias. Docker Desktop is not required for Cloud
Build. Reopen a shell after installation rather than assuming old PATH values.

Inspect the **existing** clone; replace `~/frontend` with its real path if
necessary. Never clone over it, hard-reset work, or overwrite `.env`:

```bash
cd ~/frontend
git rev-parse --show-toplevel && git remote -v && git status --short && git branch --show-current
```

Back up or commit your local changes first. The Git status does **not** show
ignored `.env` files. **After these Supabase changes have been reviewed and
merged to `main`**, fast-forward your clean checkout:

```bash
git fetch origin && git switch main && git pull --ff-only origin main && git log -1 --oneline
git grep -n 'CREATE SCHEMA transport_portal' -- backend/sql/001_initial.sql
git grep -n 'vision-ai-srmtrp' -- .firebaserc
```

If they have not been merged, use a reviewed checkout of the branch containing
these changes instead; do not assume `main` already contains them. If Git
refuses the fast-forward or a verification command finds nothing, stop.

```bash
if [ ! -f .venv/Scripts/activate ]; then py -3.11 -m venv .venv; fi
source .venv/Scripts/activate
python --version && python -m pip install --upgrade pip && python -m pip install -r backend/requirements.txt
unset TEST_DATABASE_URL ALLOW_TEST_DATABASE_RESET
python -m pytest -q
python -m backend.manage_access --help
```

These default tests use disposable in-memory SQLite; they do not connect to
Supabase. GitHub CI also exercises a local PostgreSQL service. If a different
Python version appears inside the venv, stop and repair the venv.

## 2. Sign in and verify Firebase/Google Cloud

```bash
firebase login && firebase projects:list
gcloud auth login && gcloud auth list
gcloud config set project vision-ai-srmtrp && gcloud config set compute/region asia-south1
export PROJECT_ID=vision-ai-srmtrp REGION=asia-south1
export PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
export RUN_SA="srm-trp-run@${PROJECT_ID}.iam.gserviceaccount.com"
export BUILD_SA="srm-trp-build@${PROJECT_ID}.iam.gserviceaccount.com"
export BUILD_BUCKET="${PROJECT_ID}-build-src-${PROJECT_NUMBER}"
printf 'Project: %s; number: %s; region: %s\n' "$PROJECT_ID" "$PROJECT_NUMBER" "$REGION"
gcloud billing projects describe "$PROJECT_ID" --format='value(billingEnabled)'
```

Stop if the account, project, project number or billing is wrong. The operator
needs permission to enable APIs, create IAM/network/secrets resources, submit
builds, deploy Cloud Run and administer Firebase. If opening a new shell,
reactivate the venv and re-export the variables above.

Check the actual web app and Hosting site instead of assuming a default site:

```bash
firebase hosting:sites:list --project="$PROJECT_ID" --json
firebase apps:list WEB --project="$PROJECT_ID"
firebase apps:sdkconfig WEB 1:235811571442:web:342e488e0ac2ee75b0f26b --project="$PROJECT_ID"
```

Compare with Firebase Console → Project settings → General → Your apps:
project `vision-ai-srmtrp`, auth domain `vision-ai-srmtrp.firebaseapp.com`,
storage bucket `vision-ai-srmtrp.firebasestorage.app`, sender `235811571442`,
app ID above and measurement ID `G-S4HS9TGV4H`. `.env.example` contains the
supplied public web API key. If the real values differ, stop and review the
configuration before deployment. Do not create a duplicate web app.

If **no default Hosting site exists**, create one only after confirming the
site ID is available and approved:

```bash
firebase hosting:sites:create vision-ai-srmtrp --project="$PROJECT_ID"
firebase hosting:sites:get vision-ai-srmtrp --project="$PROJECT_ID" --json
```

If an existing default site has a different ID, use its real URL and review
Firebase auth-domain settings rather than assuming `vision-ai-srmtrp.web.app`.
Do not run `firebase init` over the checked-in `firebase.json`.

In Firebase Console → **Authentication**:

1. Enable **Email/Password**, and optionally **Google** with a support email.
2. Under **Settings → Authorized domains**, add the actual Hosting domain and
   confirm the configured auth domain. Domains are not a user allowlist.
3. Under **Users**, find `814725105014@trp.srmtrichy.edu.in`. If absent, create
   it with a new strong private password. If present, independently establish
   control of both the mailbox and that specific account/UID before recovery;
   do not assume that an existing account is yours.
4. Review the email-verification and password-reset templates. A Firebase user
   alone does not grant portal access. Section 5 verifies the email privately.

## 3. Google Cloud networking, identities and IAM

The checked-in build deliberately uses Direct VPC egress and Cloud NAT to
provide a stable outbound IPv4 address. This is useful if Supabase network
restrictions are enabled, but it costs money even if those restrictions are off.
The following assumes a new standalone VPC in this project; for an existing
network, Shared VPC or overlapping CIDRs, consult your network administrator.
Do not delete or silently replace existing resources.

```bash
gcloud services enable cloudbuild.googleapis.com run.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com compute.googleapis.com iam.googleapis.com logging.googleapis.com \
  storage.googleapis.com cloudresourcemanager.googleapis.com --project="$PROJECT_ID"
```

Run each creation only if the resource is absent; if it exists, inspect its
owner, project, location and settings before explicitly reusing it:

```bash
gcloud artifacts repositories create srm-trp --repository-format=docker --location="$REGION" \
  --description='SRM TRP Transport backend images' --project="$PROJECT_ID"
gcloud iam service-accounts create srm-trp-run --display-name='SRM TRP Cloud Run runtime' --project="$PROJECT_ID"
gcloud iam service-accounts create srm-trp-build --display-name='SRM TRP Cloud Build deployer' --project="$PROJECT_ID"
gcloud storage buckets create "gs://$BUILD_BUCKET" --project="$PROJECT_ID" --location="$REGION" \
  --uniform-bucket-level-access --public-access-prevention
```

```bash
gcloud artifacts repositories describe srm-trp --location="$REGION" --project="$PROJECT_ID"
gcloud iam service-accounts describe "$RUN_SA" --project="$PROJECT_ID"
gcloud iam service-accounts describe "$BUILD_SA" --project="$PROJECT_ID"
gcloud storage buckets describe "gs://$BUILD_BUCKET" --raw --format='value(name,projectNumber,location)'
```

The bucket's project number must match `$PROJECT_NUMBER`. Source archives can
persist there; restrict access and configure an appropriate lifecycle.

Create the network only after confirming `10.42.0.0/24` does not conflict:

```bash
gcloud compute networks create srm-trp-vpc --subnet-mode=custom --bgp-routing-mode=regional --project="$PROJECT_ID" &&
gcloud compute networks subnets create srm-trp-subnet --network=srm-trp-vpc --region="$REGION" \
  --range=10.42.0.0/24 --enable-private-ip-google-access --project="$PROJECT_ID" &&
gcloud compute routers create srm-trp-router --network=srm-trp-vpc --region="$REGION" --project="$PROJECT_ID" &&
gcloud compute addresses create srm-trp-nat-ip --region="$REGION" --project="$PROJECT_ID" &&
gcloud compute routers nats create srm-trp-nat --router=srm-trp-router --region="$REGION" \
  --nat-custom-subnet-ip-ranges=srm-trp-subnet --nat-external-ip-pool=srm-trp-nat-ip --project="$PROJECT_ID"
```

```bash
NAT_IP="$(gcloud compute addresses describe srm-trp-nat-ip --region="$REGION" --project="$PROJECT_ID" --format='value(address)')"
[ -n "$NAT_IP" ] && printf 'Cloud Run outbound IPv4: %s/32\n' "$NAT_IP"
gcloud compute routers nats describe srm-trp-nat --router=srm-trp-router --region="$REGION" --project="$PROJECT_ID"
```

The NAT IP is different from your Windows workstation's public IP. Both paths
must be allowed if the Supabase database has network restrictions.

Grant the build identity the access needed for initial creation/deployment:

```bash
gcloud artifacts repositories add-iam-policy-binding srm-trp --location="$REGION" --project="$PROJECT_ID" \
  --member="serviceAccount:$BUILD_SA" --role=roles/artifactregistry.writer --condition=None &&
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$BUILD_SA" --role=roles/run.admin --condition=None &&
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$BUILD_SA" --role=roles/logging.logWriter --condition=None &&
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$BUILD_SA" --role=roles/compute.networkViewer --condition=None &&
gcloud compute networks subnets add-iam-policy-binding srm-trp-subnet --region="$REGION" --project="$PROJECT_ID" \
  --member="serviceAccount:$BUILD_SA" --role=roles/compute.networkUser &&
gcloud storage buckets add-iam-policy-binding "gs://$BUILD_BUCKET" --member="serviceAccount:$BUILD_SA" --role=roles/storage.objectViewer &&
gcloud iam service-accounts add-iam-policy-binding "$RUN_SA" --project="$PROJECT_ID" \
  --member="serviceAccount:$BUILD_SA" --role=roles/iam.serviceAccountUser
```

The project-level `run.admin` grant is powerful; restrict who may submit builds
as this identity and narrow it after initial setup. Confirm that the following
account is the intended **human user** before granting it act-as permission:

```bash
DEPLOYER_EMAIL="$(gcloud config get-value account 2>/dev/null)"
printf 'Build-submitting Google user: %s\n' "$DEPLOYER_EMAIL"
gcloud iam service-accounts add-iam-policy-binding "$BUILD_SA" --project="$PROJECT_ID" \
  --member="user:$DEPLOYER_EMAIL" --role=roles/iam.serviceAccountUser
```

The submitter also needs Cloud Build create/read, Service Usage consumer and
source-bucket upload permissions. Google normally grants the Cloud Run service
agent the network permissions for a same-project VPC. IAM changes may take
several minutes. Review organization policy and Shared VPC requirements if
these commands fail.

## 4. Prepare the Supabase database securely

In the **correct Supabase project**:

1. Verify the project and database, backups, region and budget. In **Connect**,
   choose **Session pooler**, and note the exact pooler **host** and project
   reference. The shared session pooler supports IPv4 and port `5432`; direct
   connections commonly require IPv6 or the IPv4 add-on. Do not invent a host
   or paste a connection URL into chat.
2. Under **Database settings → SSL configuration**, download the project's
   server root CA certificate to a private, stable location on your Windows
   machine. You will enter its Windows path (e.g. using forward slashes) in the
   script. Enable SSL enforcement if appropriate. The app uses
   `sslmode=verify-full`, so both the server certificate and host are verified.
3. Review **Network Restrictions**. If enabled, add the **workstation's actual
   current public IPv4/32** and the Cloud NAT `NAT_IP/32` from section 3; wait
   for the changes to apply. Pooler and direct database connections are both
   subject to these restrictions. If restrictions are disabled, any network
   can reach the endpoint subject to authentication; decide a tighter policy
   with the project owner. Do not replace existing allowlists blindly.
4. Check that no unrelated `transport_portal` schema already exists. This
   migration intentionally fails if it does; it never drops or clears a schema.
   In Supabase **SQL Editor**, paste the entire contents of
   `backend/sql/001_initial.sql`, review them, and run it **once** as the
   database administrator. You may open the local file with:

   ```bash
   notepad.exe "$(cygpath -w "$PWD/backend/sql/001_initial.sql")"
   ```

   The script creates private tables and indexes in a transaction and revokes
   API-role access. Do **not** add `transport_portal` to Supabase's exposed
   Data API schemas. If the SQL fails, stop and inspect the transaction/error;
   do not drop an existing schema to make it pass.
5. If you already have `.env`, first make a private, verified backup **outside**
   the repository. The following copies it without printing its contents:

   ```bash
   if [ -e .env ]; then
     BACKUP_DIR="$HOME/srm-trp-private-backups"
     BACKUP_FILE="$BACKUP_DIR/env-before-supabase-$(date +%Y%m%d-%H%M%S)"
     mkdir -p "$BACKUP_DIR" && [ ! -e "$BACKUP_FILE" ] && \
       cp -p -- .env "$BACKUP_FILE" && cmp -s -- .env "$BACKUP_FILE" && \
       printf 'Backup verified at %s\n' "$BACKUP_FILE"
   fi
   ```

   Review the backup and decide how to retain the old settings. **Only after
   verifying it and choosing to move the original**, the following moves the
   old file into the same private backup directory, without overwriting:

   ```bash
   if [ -e .env ]; then
     ORIGINAL_FILE="$HOME/srm-trp-private-backups/env-original-$(date +%Y%m%d-%H%M%S)"
     [ -n "${BACKUP_FILE:-}" ] && [ -f "$BACKUP_FILE" ] && cmp -s -- .env "$BACKUP_FILE" && \
       [ ! -e "$ORIGINAL_FILE" ] && mv -- .env "$ORIGINAL_FILE" && \
       printf 'Original moved to %s\n' "$ORIGINAL_FILE"
   fi
   ```

   Protect both copies with Windows user ACLs. If any command fails, stop.
   Then create the dedicated application login and a **new** `.env`:

   ```bash
   set +x
   if [ -e .env ]; then
     echo 'STOP: .env already exists. Back it up and move it aside deliberately; it will not be overwritten.' >&2
   else
     python scripts/configure_supabase.py
   fi
   ```

   When prompted, enter the exact session-pooler host, project reference,
   downloaded CA's **Windows** path and the Supabase database administrator
   password (hidden), then type `CREATE`. The script creates role
   `transport_portal_app`, grants it access only to the application schema
   tables (audit logs are append/read only), generates a separate random role
   password and JWT/device secrets, writes the ignored `.env`, and tests the
   dedicated login. It does not overwrite an existing `.env` or role. Review
   any ambient Postgres `PUBLIC` grants in your project separately.

   If an `.env` already exists, keep a secure backup outside the repository;
   only move the old file aside after verifying the backup and deciding how to
   preserve its settings. Never paste it into chat. A partial failure may leave
   a `.env` and/or role behind: **inspect both** before retrying or rotating
   anything. Protect `.env` with your Windows user ACLs; `chmod` alone is not
   a reliable Windows permission boundary. The script hides driver details in
   errors, so check TLS, network, schema, role and credentials privately.

## 5. Verify the administrator and grant portal access

The verification helper signs in to Firebase and sends/checks a verification
email. It does not grant portal access. Keep the terminal private:

```bash
set +x
FIREBASE_WEB_API_KEY="$(python -c 'from dotenv import dotenv_values; print(dotenv_values(".env")["FIREBASE_API_KEY"])')"
read -r -s -p 'New Firebase administrator password (hidden): ' FIREBASE_USER_PASSWORD
printf '\n'
export FIREBASE_WEB_API_KEY FIREBASE_USER_PASSWORD
python scripts/send_firebase_verification.py 814725105014@trp.srmtrichy.edu.in
```

Open the verification email in that person's mailbox, follow the link, then
check it in the same shell:

```bash
python scripts/send_firebase_verification.py 814725105014@trp.srmtrichy.edu.in --check
unset FIREBASE_USER_PASSWORD FIREBASE_WEB_API_KEY
```

The result must report verified email. Clear those variables even if the helper
fails. A browser-referrer-only API key may reject this command-line request;
use an approved temporary key or trusted Firebase Admin workflow without
weakening the production key. Do not mark an email verified without verifying
both mailbox ownership and control of that specific Firebase account.

Review the PostgreSQL access list before granting anything:

```bash
python -m backend.manage_access list
```

For a fresh database it should be empty. If there are existing entries,
review their roles, active state and Firebase UID bindings first. `add` and
`set-role` reactivate an existing entry; `unlink` permits a different UID to
bind. Use them only after verifying account ownership and authorization.
After verification, grant the intended administrator:

```bash
python -m backend.manage_access add 814725105014@trp.srmtrichy.edu.in --role head_admin &&
python -m backend.manage_access list
```

Confirm the exact email is active and `head_admin`. All other users also need
explicit entries in the production build. Firebase self-registration and
Google identity alone do not grant portal access.

## 6. Store runtime values in Secret Manager

The build expects five secret names:

| Secret | Runtime use |
| --- | --- |
| `database-url` | `DATABASE_URL`, dedicated role's Supabase PostgreSQL URL |
| `supabase-ca` | mounted file `/secrets/supabase-ca.crt`, referenced by `PGSSLROOTCERT` |
| `jwt-secret` | `JWT_SECRET` |
| `device-keys` | `DEVICE_API_KEYS` |
| `firebase-api-key` | public Firebase web key supplied to the backend |

List metadata first. If any name already exists, inspect its consumers and
rotation plan; changing `latest` affects future starts of other revisions.
Create only absent names; do not delete unrelated secrets:

```bash
gcloud secrets list --project="$PROJECT_ID" --format='table(name,createTime)'
gcloud secrets create database-url --replication-policy=automatic --project="$PROJECT_ID" &&
gcloud secrets create supabase-ca --replication-policy=automatic --project="$PROJECT_ID" &&
gcloud secrets create jwt-secret --replication-policy=automatic --project="$PROJECT_ID" &&
gcloud secrets create device-keys --replication-policy=automatic --project="$PROJECT_ID" &&
gcloud secrets create firebase-api-key --replication-policy=automatic --project="$PROJECT_ID"
```

If a name exists, the chain stops. Review it and create only the remaining
absent names before continuing. The next block sends values from `.env` to
Secret Manager **without printing them**. It rotates the runtime JWT/device
keys to the values generated in section 4; plan a device/session cutover.

```bash
set +x
set -o pipefail
FAILED=0
for PAIR in DATABASE_URL:database-url JWT_SECRET:jwt-secret DEVICE_API_KEYS:device-keys FIREBASE_API_KEY:firebase-api-key; do
  ENV_NAME="${PAIR%%:*}"
  SECRET_NAME="${PAIR#*:}"
  if ! python -c 'import sys; from dotenv import dotenv_values; v=dotenv_values(".env").get(sys.argv[1]); assert v, "Missing value"; sys.stdout.write(v)' "$ENV_NAME" | \
       gcloud secrets versions add "$SECRET_NAME" --data-file=- --project="$PROJECT_ID"; then
    FAILED=1
    break
  fi
done
CA_PATH="$(python -c 'from dotenv import dotenv_values; print(dotenv_values(".env")["PGSSLROOTCERT"])')"
[ "$FAILED" -eq 0 ] && [ -n "$CA_PATH" ] && \
  gcloud secrets versions add supabase-ca --data-file="$CA_PATH" --project="$PROJECT_ID" && \
  echo 'All secret versions uploaded.'
```

If any operation fails, stop; check which versions were created before
retrying. Secret values and `.env` stay private. Securely distribute the device
key to authorized devices through a separate controlled channel.

Grant the runtime service account access to each specific secret:

```bash
FAILED=0
for SECRET in database-url supabase-ca jwt-secret device-keys firebase-api-key; do
  if ! gcloud secrets add-iam-policy-binding "$SECRET" --project="$PROJECT_ID" \
      --member="serviceAccount:$RUN_SA" --role=roles/secretmanager.secretAccessor --condition=None; then
    FAILED=1
    break
  fi
done
[ "$FAILED" -eq 0 ] && echo 'All runtime secret grants succeeded.'
```

Stop if the final success message is absent. Review earlier JWT versions and
retire old reachable revisions as appropriate; renaming a cookie does not
revoke a copied token. Rotate/update `database-url` and redeploy after any
PostgreSQL password change.

## 7. Deploy Cloud Run, then Hosting

The build config replaces its declared Cloud Run environment variables and
secrets. Inspect any existing service, IAM, secret references and traffic
before deployment; do not blindly overwrite a production service.

```bash
cd ~/frontend
source .venv/Scripts/activate
git status --short
gcloud meta list-files-for-upload
```

Review the upload list. It should contain application code, the Dockerfile and
`best.pt`, not `.env`, database dumps, JSON credentials or personal records.
Ignore files and the selective secret scanner are not complete audits.

```bash
gcloud builds submit . --project="$PROJECT_ID" --config=deploy/cloudbuild.yaml \
  --gcs-source-staging-dir="gs://$BUILD_BUCKET/source"
```

Wait for **SUCCESS**; stop and investigate on failure. The dedicated build
identity pushes a BUILD_ID-tagged image and deploys it. A Cloud Build trigger
must have the intended service account configured on the trigger itself.

```bash
gcloud run services describe srm-trp-transport --region="$REGION" --project="$PROJECT_ID"
RUN_URL="$(gcloud run services describe srm-trp-transport --region="$REGION" --project="$PROJECT_ID" --format='value(status.url)')"
[ -n "$RUN_URL" ] && printf 'Cloud Run URL: %s\n' "$RUN_URL" && curl -fsS "$RUN_URL/api/health"
```

Confirm the runtime identity, mounted CA, PostgreSQL URL secret, startup probe,
Direct VPC/subnet and all-traffic egress in Cloud Run. Health is available only
after database startup checks, but it is not a continuous DB health monitor.
Public Cloud Run invocation is required for this Hosting rewrite; protected
routes still require application authorization.

Only after Cloud Run succeeds, publish Hosting to the verified default site:

```bash
firebase deploy --only hosting --project="$PROJECT_ID"
```

`frontend/pages/` is excluded from Hosting: static files otherwise take
priority over rewrites and could bypass Flask page authorization. Firebase
Hosting forwards only the `__session` cookie. Check the real deployed
configuration rather than relying on the emulator.

## 8. Verify and operate

Use the **actual** Hosting URL from section 2. The following only applies if
its default URL really is `https://vision-ai-srmtrp.web.app`:

```bash
HOSTING_URL=https://vision-ai-srmtrp.web.app
curl -fsS "$HOSTING_URL/api/health"
curl -fsS "$HOSTING_URL/api/auth/config"
curl -fsS "$HOSTING_URL/api/config/firebase" | \
  python -c 'import json,sys; d=json.load(sys.stdin); print("enabled:", d.get("enabled"), "project:", d.get("projectId"), "has API key:", bool(d.get("config", {}).get("apiKey")))'
curl -sS -o /dev/null -w 'Unauthenticated /api/auth/me: %{http_code}\n' "$HOSTING_URL/api/auth/me"
curl -sS -o /dev/null -w 'Unauthenticated /dashboard: %{http_code}\n' "$HOSTING_URL/dashboard"
curl -sS -L -o /dev/null -w 'Direct template URL: %{http_code}\n' "$HOSTING_URL/pages/dashboard.html"
```

Expect health `ok`, Firebase project `vision-ai-srmtrp`, enabled API key,
`auto_provision: false`, `legacy_password_login: false`, unauthenticated `me`
**401**, a login redirect for the dashboard, and no directly served protected
template (normally **404**). Then test in a private browser:

1. Sign in as the verified administrator, refresh `/dashboard`, and check
   data operations. Inspect cookie attributes (`Secure`, `HttpOnly`,
   `SameSite=Lax`, name `__session`) without copying its value.
2. Sign out; protected routes should fail afterward. Test an independently
   verified but unapproved account, an unverified account, an inactive account
   and wrong-role access; all must be denied as appropriate.
3. Test the real browser camera/detector only after privacy and model-rights
   approval. Google popup/redirect flows must be tested in real browsers;
   cross-origin storage restrictions can break redirect fallback.

Hosting limits backend requests to 60 seconds even though Cloud Run's timeout
is 300 seconds. Cold starts or long SSE/camera/detection requests may exceed
that limit. NAT can take time to become ready; inspect logs and retry rather
than assuming a password error. Logs may contain personal information:

```bash
gcloud builds list --project="$PROJECT_ID" --limit=5
gcloud run services logs read srm-trp-transport --region="$REGION" --project="$PROJECT_ID" --limit=100
```

Before production, review backups and restore tests, retention, IAM, real
accounts/UIDs, previous exposed credentials, old sessions, Git history,
model/dataset licensing, CORS and distributed rate limiting. The default
in-memory login limiter is per process, not a global control. Use approved
procedures to remove sensitive Git history **after** credential rotation;
normal commits do not erase forks, PRs or caches.

For rollback, inspect the old revision's security and secret versions first;
it may still point to MongoDB or an old Firebase project. Database changes are
not rolled back automatically:

```bash
gcloud run revisions list --service=srm-trp-transport --region="$REGION" --project="$PROJECT_ID"
# Only after review: replace REVISION_ID with the known-good revision.
gcloud run services update-traffic srm-trp-transport --region="$REGION" --project="$PROJECT_ID" --to-revisions=REVISION_ID=100
```

Hosting rollback is in Firebase Console → Hosting → release history. The
Hosting rewrite is not pinned to a Cloud Run revision, so each side must be
reviewed separately.
