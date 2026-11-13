# Windows Git Bash: recover tools, configure Firebase and Atlas, and deploy

This is the ordered runbook for the **existing** repository clone (formerly
`saran-44/frontend`, now `saran-44/VISION-AI-SRM-TRP`), Firebase/Google Cloud
project **`srmtrpai`**, Cloud Run region **`asia-south1`**, and initial portal
administrator **`814725105014@trp.srmtrichy.edu.in`**.
It is written for Git Bash on Windows and can also be imported into Claude.

> **Read this first.** No real Firebase, Atlas, Cloud Run or Hosting deployment
> has been verified by the author of this guide. Use it first in a controlled
> environment. Do not put live personal data into the portal or declare it
> production-ready until the [security checklist](#11-production-gates) is
> complete and an authorized administrator has tested the real services.
>
> A password was previously shared in chat. **Do not use that password.** If
> it was already configured, reset it to a different, unique strong password.
> Rotate **both** previously exposed Atlas credentials and verify the old
> credentials are revoked. Never paste a password, connection string, ID
> token, Firebase service-account key, or session cookie into chat, Git,
> terminal command arguments, screenshots, or logs.
>
> These commands create billable Google Cloud resources, including a Cloud NAT
> gateway, reserved IP, Cloud Build, Cloud Run and Secret Manager resources.
> Check pricing, budget and billing first. Run the numbered steps in order;
> **stop if a command fails** rather than continuing. The Google Cloud/Firebase
> operator must have permission to enable APIs, create network and IAM
> resources, manage secrets, build/deploy and administer Firebase Auth.

## 0. What will be deployed

| Component | Destination | Important boundary |
| --- | --- | --- |
| Login HTML, CSS, JS, images and vendor libraries | Firebase Hosting | Static files are served directly. |
| Authenticated pages and `/api/**` | Cloud Run `srm-trp-transport` | Unmatched Hosting paths rewrite to the Flask service in `asia-south1`. |
| Protected page templates | Container only | `frontend/pages/` is excluded from Hosting uploads so Flask checks roles. |
| Portal session | HttpOnly `__session` cookie | Firebase Hosting forwards this specific cookie to Cloud Run. |
| User access list | Atlas database `srmtrpai`, collection `users` | Firebase identity **and** a verified email **and** an active access entry are required. |
| Outbound backend traffic | Direct VPC egress + Cloud NAT | The NAT's reserved IP must be on the Atlas IP access list before the first deploy. |

The production build disables legacy local-password login and Firebase
self-provisioning. Both Firebase password and Google providers can be used, but
**every** identity must already be explicitly listed in MongoDB; an arbitrary
Google account is denied. Creating a Firebase Auth user is not sufficient by
itself. The public Cloud Run endpoint is intentionally invocable by Hosting;
protected routes still require application authorization.

## 1. Install or repair the Windows toolchain

Git Bash itself does not install Node.js, Python, Firebase CLI, or `gcloud`.
If a tool was just installed, **close every Git Bash window and open a new one**
so it receives the updated Windows `PATH`.

### 1.1 Install missing tools

In Git Bash, locate `winget`:

```bash
WINGET=winget.exe
if ! command -v "$WINGET" >/dev/null 2>&1; then
  WINGET="$(cygpath -u "$LOCALAPPDATA")/Microsoft/WindowsApps/winget.exe"
fi
"$WINGET" --version
```

If that fails, install/update **App Installer** from Microsoft Store, or use
the vendors' Windows installers. Run the following **only for tools that are
missing**; approve the installers' prompts:

```bash
"$WINGET" install --exact --id OpenJS.NodeJS.LTS --source winget
"$WINGET" install --exact --id Python.Python.3.11 --source winget
"$WINGET" install --exact --id Google.CloudSDK --source winget
```

The [Google Cloud CLI Windows installer](https://cloud.google.com/sdk/docs/install-sdk)
can be used if the `winget` package fails. Accept its bundled Python option.
Docker Desktop is **not** needed: Cloud Build builds the container remotely.

Close and reopen Git Bash, then check:

```bash
git --version
node --version
npm --version
py -3.11 --version
gcloud --version
```

Use Node **20 or newer** for the CLI version below. If the Microsoft Store
`python.exe` alias opens the Store or reports Python was not found, do not use
that alias to create the environment: use `py -3.11` as shown. If `py` is also
missing, find the real Python 3.11 installation with `where.exe python` or the
Windows **Manage app execution aliases** settings, and use its full
`python.exe` path to create the venv in §2.2.

If Node is installed but not found in the new Git Bash window, a common
per-machine path is:

```bash
export PATH="/c/Program Files/nodejs:$PATH"
hash -r
node --version && npm --version
```

If `gcloud` is installed but not found, the usual **per-user** installer path
contains `google-cloud-sdk/bin`, not just `Cloud SDK/bin`:

```bash
GCLOUD_BIN="$(cygpath -u "$LOCALAPPDATA")/Google/Cloud SDK/google-cloud-sdk/bin"
export PATH="$GCLOUD_BIN:$PATH"
hash -r
gcloud --version
```

If that folder does not exist, locate the actual `google-cloud-sdk/bin` folder
in Windows and add that folder instead. These `export PATH` changes apply only
to the current window; use Windows Environment Variables for a permanent fix.

### 1.2 Install the Firebase CLI before logging in

```bash
npm install -g firebase-tools@15.36.0
firebase --version
```

If npm succeeds but Git Bash cannot find `firebase`, convert npm's Windows
prefix before using it as a POSIX path:

```bash
NPM_PREFIX="$(npm config get prefix)"
export PATH="$(cygpath -u "$NPM_PREFIX"):$PATH"
hash -r
firebase --version
```

Do not paste a literal `/c/Users/you/...` path. If installation or a version
check fails, fix it before continuing. The pinned Firebase CLI was tested with
this repository's Hosting configuration; update it deliberately later.

## 2. Safely update the existing clone and install Python dependencies

### 2.1 Inspect first; do not clone over the existing folder

```bash
cd ~/frontend
git rev-parse --show-toplevel
git remote -v
git status --short
git branch --show-current
```

The repository's current canonical URL is
`https://github.com/saran-44/VISION-AI-SRM-TRP.git`; GitHub redirects its former
`https://github.com/saran-44/frontend.git` URL to the same repository. Either
remote is acceptable if it resolves to the correct repository. The status
should show **no local changes or untracked files that matter**. If the folder
is elsewhere, `cd` to your actual existing clone instead. If there are local
changes, stop and back them up or commit them appropriately; do not overwrite
`.env`, use `git reset --hard`, or delete the clone. Git ignores `.env`, so an
empty status does not mean that the local `.env` is absent.

Only after these Hosting/network fixes have been merged into `main`, and after
inspecting/backing up your changes, run:

```bash
git fetch origin &&
git switch main &&
git pull --ff-only origin main &&
git log -1 --oneline &&
git status --short
```

If switching or the fast-forward pull fails, stop and resolve the local branch
state without a destructive reset. Confirm that the updated files are present:

```bash
git grep -n '"serviceId": "srm-trp-transport"' -- firebase.json
git grep -n 'COOKIE_NAME = "__session"' -- backend/auth.py
git grep -n 'srm-trp-vpc' -- deploy/cloudbuild.yaml
```

All three commands must find a match. The previous merged `main` version did
not have the necessary Hosting fixes; do not deploy that old version.

### 2.2 Create/activate a Windows venv

```bash
if [ ! -f .venv/Scripts/activate ]; then
  py -3.11 -m venv .venv
fi
source .venv/Scripts/activate
python --version
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
python -m backend.manage_access --help
python -m pytest backend/tests -q
```

`python --version` must show Python 3.11 inside the venv. If an old venv uses a
different interpreter, stop and back it up/recreate it rather than assuming it
is correct. Windows uses `.venv/Scripts/activate`, **not** `.venv/bin/activate`.
These tests use local mocks; passing them does not verify Firebase or Atlas.

## 3. Log in and confirm the actual project, app and Hosting site

```bash
firebase login
firebase projects:list
gcloud auth login
gcloud config set project srmtrpai
gcloud config set compute/region asia-south1
gcloud auth list
gcloud projects describe srmtrpai --format='value(projectId,projectNumber)'
gcloud billing projects describe srmtrpai --format='value(billingEnabled)'
```

Firebase and gcloud each open a browser. Confirm the correct Google accounts,
project ID, and billing access. Billing must be enabled and Firebase must be
on a plan that permits the Cloud Run/Hosting integration. If permissions are
insufficient, ask your project administrator to grant them; do not change to a
different project to make a command succeed.

First inspect Hosting, before enabling Firebase Authentication or creating a
web app (either action can create a default site implicitly):

```bash
firebase hosting:sites:list --project=srmtrpai --json
```

Check the JSON for a `DEFAULT_SITE` and its actual `defaultUrl`. Firebase
projects created after October 15, 2026 may not yet have a default Hosting
site. **Only if there is no default site**, create the desired one:

```bash
firebase hosting:sites:create srmtrpai --project=srmtrpai
firebase hosting:sites:get srmtrpai --project=srmtrpai --json
```

If the site ID is already taken, or an existing default site uses another ID,
stop and use its actual URL/auth domain after reviewing the configuration;
`https://srmtrpai.web.app` is not guaranteed in that case. Do not run
`firebase init` in this existing repository: it can replace the checked-in
Hosting configuration. [Firebase default-site documentation](https://firebase.google.com/docs/hosting/default-site).

Now inspect the existing web app:

```bash
firebase apps:list WEB --project=srmtrpai
firebase apps:sdkconfig WEB 1:734375891811:web:6851938bef332bc0e53956 --project=srmtrpai
```

If that app ID is absent, stop and inspect the actual app list in Firebase
Console; do not create a duplicate without the project owner's approval. The
build currently expects web app ID `1:734375891811:web:6851938bef332bc0e53956`,
sender ID `734375891811`, and auth domain `srmtrpai.firebaseapp.com`. Compare
these and the other fields with **Project settings → General → Your apps →
SDK setup and configuration**. The web API key is a public browser identifier,
but do not paste the whole configuration or any credential into chat. If the
IDs or auth domain differ, **stop and update/review `deploy/cloudbuild.yaml`
and Firebase authorized domains** before deploying; do not assume the values
are correct.

## 4. Firebase Console: set up the initial administrator

1. Open <https://console.firebase.google.com/>, select **srmtrpai**, then
   **Build → Authentication** (the console may label this **Security →
   Authentication**). Click **Get started** if prompted.
2. Open **Sign-in method → Add new provider → Email/Password**, enable
   **Email/Password**, and save. Enable **Google** as well if you want the
   configured Google button; select the project support email and save. Google
   sign-in is still restricted by the backend access list.
3. Under **Settings → Authorized domains**, confirm the actual Hosting domain
   and its `firebaseapp.com` auth domain are listed. Add the actual
   `srmtrpai.web.app` domain if applicable. Add `localhost` only if needed for
   local development. Authorized domains are **not** a user allowlist.
4. Open **Users** and search for
   `814725105014@trp.srmtrichy.edu.in`.
   - If absent, select **Add user**, enter that email, and privately enter a
     **new strong password that was never shared in chat**. Save it securely.
   - If present, **do not create a duplicate or assume the existing account is
     yours**. Independently establish ownership of the mailbox and control of
     the specific Firebase account/UID. Use the row's menu to send a password
     reset email where available, follow the link privately, and choose a new
     password. If ownership cannot be established, stop and investigate with
     the Firebase administrator before granting `head_admin`.
5. Under **Templates**, review the **Email verification** and **Password
   reset** templates and sender. Adding a user does not guarantee the email is
   verified. The portal currently has no built-in verification/reset button;
   §7 sends and checks the verification email using Firebase's REST API.

No account or role is created by these instructions until you perform them.

## 5. Google Cloud: APIs, identities, repository and static egress

The following names are used by the checked-in build file. They assume a
**new, standalone VPC in the same project**, not a Shared VPC. If any resource
already exists, stop, inspect its project, region and configuration, and reuse
it only if appropriate; do not delete or replace an existing production setup.

```bash
export PROJECT_ID=srmtrpai REGION=asia-south1
export PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
export RUN_SA="srm-trp-run@${PROJECT_ID}.iam.gserviceaccount.com"
export BUILD_SA="srm-trp-build@${PROJECT_ID}.iam.gserviceaccount.com"
export BUILD_BUCKET="${PROJECT_ID}-build-src-${PROJECT_NUMBER}"
printf 'Project: %s  Number: %s  Region: %s\n' "$PROJECT_ID" "$PROJECT_NUMBER" "$REGION"
```

Stop if the project number is blank or the project is wrong. If a new shell is
opened later, rerun these exports and reactivate `.venv`.

### 5.1 Enable APIs

```bash
gcloud services enable \
  cloudbuild.googleapis.com run.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com compute.googleapis.com iam.googleapis.com \
  logging.googleapis.com storage.googleapis.com cloudresourcemanager.googleapis.com \
  --project="$PROJECT_ID"
```

### 5.2 Create the artifact repository and service accounts

Run each create command only if the named resource does not already exist:

```bash
gcloud artifacts repositories create srm-trp \
  --repository-format=docker --location="$REGION" \
  --description="SRM TRP Transport backend images" --project="$PROJECT_ID"
```

```bash
gcloud iam service-accounts create srm-trp-run \
  --display-name="SRM TRP Cloud Run runtime" --project="$PROJECT_ID"
```

```bash
gcloud iam service-accounts create srm-trp-build \
  --display-name="SRM TRP Cloud Build deployer" --project="$PROJECT_ID"
```

```bash
gcloud artifacts repositories describe srm-trp --location="$REGION" --project="$PROJECT_ID"
gcloud iam service-accounts describe "$RUN_SA" --project="$PROJECT_ID"
gcloud iam service-accounts describe "$BUILD_SA" --project="$PROJECT_ID"
```

Create a private source-staging bucket. Bucket names are globally unique; if
this name is already taken, **verify that it belongs to this project** before
reusing it, or choose another private bucket and keep `BUILD_BUCKET` consistent.
Source archives can persist in this bucket; restrict access and set an
appropriate retention/lifecycle policy.

```bash
gcloud storage buckets create "gs://$BUILD_BUCKET" --project="$PROJECT_ID" \
  --location="$REGION" --uniform-bucket-level-access --public-access-prevention
```

```bash
gcloud storage buckets describe "gs://$BUILD_BUCKET" --raw \
  --format='value(name,projectNumber,location)'
```

The reported project number must equal `$PROJECT_NUMBER` before you grant
access or upload source.

### 5.3 Create a VPC, subnet, router and reserved NAT IP

These one-time commands create a `/24` subnet; confirm `10.42.0.0/24` does not
conflict with any future peering/on-premises ranges. For an existing network,
review the configuration with your network administrator instead.

```bash
gcloud compute networks create srm-trp-vpc --subnet-mode=custom \
  --bgp-routing-mode=regional --project="$PROJECT_ID" &&
gcloud compute networks subnets create srm-trp-subnet --network=srm-trp-vpc \
  --region="$REGION" --range=10.42.0.0/24 --enable-private-ip-google-access \
  --project="$PROJECT_ID" &&
gcloud compute routers create srm-trp-router --network=srm-trp-vpc \
  --region="$REGION" --project="$PROJECT_ID" &&
gcloud compute addresses create srm-trp-nat-ip --region="$REGION" --project="$PROJECT_ID" &&
gcloud compute routers nats create srm-trp-nat --router=srm-trp-router \
  --region="$REGION" --nat-custom-subnet-ip-ranges=srm-trp-subnet \
  --nat-external-ip-pool=srm-trp-nat-ip --project="$PROJECT_ID"
```

Read the reserved public IPv4 address, then add its `/32` entry to Atlas in §6:

```bash
NAT_IP="$(gcloud compute addresses describe srm-trp-nat-ip --region="$REGION" \
  --project="$PROJECT_ID" --format='value(address)')"
printf 'Cloud Run NAT entry for Atlas: %s/32\n' "$NAT_IP"
gcloud compute routers nats describe srm-trp-nat --router=srm-trp-router \
  --region="$REGION" --project="$PROJECT_ID"
```

Stop if the IP is blank. Cloud NAT is outbound only: the workstation's public
IP is a **different** entry. Google documents that Direct VPC/NAT can take
more than a minute to become ready at cold start. This build uses a 120-second
target retry window and an HTTP startup probe, but the first real deployment
must still be validated. PyMongo's operation deadline does not strictly bound
SRV/TXT DNS during client construction, so resolver/OS delays may extend the
window. See [Google's static outbound IP guide](https://cloud.google.com/run/docs/configuring/static-outbound-ip).

### 5.4 Grant the build identity only the needed access

The build account needs project-level `run.admin` for first service creation
and public-invoker configuration. This is powerful; restrict who can submit
builds as this identity and review/narrow the grant after initial setup. The
runtime identity receives secret access in §8, not project-wide secret access.

```bash
gcloud artifacts repositories add-iam-policy-binding srm-trp --location="$REGION" \
  --project="$PROJECT_ID" --member="serviceAccount:$BUILD_SA" \
  --role=roles/artifactregistry.writer --condition=None &&
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$BUILD_SA" --role=roles/run.admin --condition=None &&
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$BUILD_SA" --role=roles/logging.logWriter --condition=None &&
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$BUILD_SA" --role=roles/compute.networkViewer --condition=None &&
gcloud compute networks subnets add-iam-policy-binding srm-trp-subnet \
  --region="$REGION" --project="$PROJECT_ID" \
  --member="serviceAccount:$BUILD_SA" --role=roles/compute.networkUser &&
gcloud storage buckets add-iam-policy-binding "gs://$BUILD_BUCKET" \
  --member="serviceAccount:$BUILD_SA" --role=roles/storage.objectViewer &&
gcloud iam service-accounts add-iam-policy-binding "$RUN_SA" --project="$PROJECT_ID" \
  --member="serviceAccount:$BUILD_SA" --role=roles/iam.serviceAccountUser
```

Allow the **human operator** who will submit builds to act as the build
identity. The following assumes `gcloud auth list` showed a human Google user,
not a service account. Confirm the displayed email before running the grant:

```bash
DEPLOYER_EMAIL="$(gcloud config get-value account 2>/dev/null)"
printf 'Build-submitting Google user: %s\n' "$DEPLOYER_EMAIL"
```

```bash
gcloud iam service-accounts add-iam-policy-binding "$BUILD_SA" --project="$PROJECT_ID" \
  --member="user:$DEPLOYER_EMAIL" --role=roles/iam.serviceAccountUser
```

The submitter also needs Cloud Build create/read, Service Usage consumer, and
source-bucket upload permissions. A project owner typically has them; use
least-privilege IAM grants if not. Google normally grants its **Cloud Run
service agent** `roles/run.serviceAgent` automatically, including the network
permissions needed in a same-project VPC. If your organization removed that
grant or uses Shared VPC, follow [Google's Direct VPC IAM instructions](https://cloud.google.com/run/docs/configuring/vpc-direct-vpc#set-up-iam-permissions)
rather than granting service-agent roles to the runtime account. IAM changes
can take several minutes to propagate.

## 6. MongoDB Atlas: rotate credentials and permit both network paths

Open <https://cloud.mongodb.com/> and select the correct Atlas organization,
project and cluster. Atlas UI labels can vary slightly by version.

1. Go to **Security → Database & Network Access → Database Users** (or
   **Database Access**). Atlas console users and database users are different.
2. Identify **both** database credentials exposed earlier. Plan any required
   cutover, then rotate or delete/revoke each exposed database user/password;
   verify the old credentials no longer work. Update other dependent services
   securely. Do not reuse either exposed password.
3. Select **Add New Database User → Password**. Create a **separate**
   application database user with a new long random password. Under **User
   Privileges**, choose **Add Default Privileges / Grant Specific Privileges**,
   then role `readWrite`, database `srmtrpai`, all application collections.
   Do **not** choose Atlas admin or `readWriteAnyDatabase`. If offered, restrict
   the user to the intended cluster. Save the password in a password manager.
4. Go to **Security → Database & Network Access → IP Access List** (or
   **Network Access**). Add **Current IP Address** for this workstation, and
   add the exact `NAT_IP/32` printed in §5.3 for Cloud Run. Wait for both
   entries to become active. Remove unintended broad entries such as
   `0.0.0.0/0`; do not use allow-from-anywhere as the production default.
5. Go to **Database → your cluster → Connect → Drivers**. Note only the
   cluster host after the `@` and before the `/` in the SRV example, such as
   `cluster-name.example.mongodb.net`. Do not paste the full connection string
   or real credentials into chat. Retain the cluster's TLS/SRV defaults.

The workstation and Cloud Run are separate network clients. Allowing only the
workstation does not allow Cloud Run. `readWrite` on `srmtrpai` must permit
the app to create its indexes. [Atlas database-user documentation](https://www.mongodb.com/docs/atlas/security-add-mongodb-users/).

### 6.1 Construct the URI privately in the current Git Bash window

The prompts take a host, username, and **raw** new password; the Python code
percent-encodes username and password, so characters such as `@`, `/`, `:` and
`%` are handled. Do not paste a Markdown link. Keep the terminal private.

```bash
set +x
read -r -p 'Atlas cluster host only (no scheme, username, or slash): ' ATLAS_HOST
read -r -p 'New Atlas database username: ' ATLAS_USER
read -r -s -p 'New Atlas database password (hidden): ' ATLAS_PASSWORD
printf '\n'
export ATLAS_HOST ATLAS_USER ATLAS_PASSWORD
MONGO_URI="$(python - <<'PY'
import os, re
from urllib.parse import quote

host = os.environ.get('ATLAS_HOST', '').strip()
user = os.environ.get('ATLAS_USER', '')
password = os.environ.get('ATLAS_PASSWORD', '')
if not re.fullmatch(r'[A-Za-z0-9.-]+\.mongodb\.net', host) or not user or not password:
    raise SystemExit('Invalid/empty Atlas host, username or password; no URI created.')
print('mongodb+srv://' + quote(user, safe='') + ':' + quote(password, safe='')
      + '@' + host + '/?retryWrites=true&w=majority')
PY
)"
unset ATLAS_HOST ATLAS_USER ATLAS_PASSWORD
if [ -n "$MONGO_URI" ]; then
  export MONGO_URI MONGO_DB_NAME=srmtrpai
  echo 'URI prepared privately for this shell; it has not been printed.'
else
  echo 'STOP: no URI was created.' >&2
fi
```

Do not run the next steps if the last line reports `STOP`. If your Atlas setup
uses a custom/private endpoint or connection options, consult Atlas's exact
Drivers instructions rather than forcing this public-SRV example. The URI is
kept in process memory/environment for this session, not encrypted on disk;
other programs running as your Windows user may be able to inspect it. A
pre-existing `.env` is loaded automatically, but exported values take
precedence. Never commit an onboarding file or `.env`.

## 7. Verify the Firebase email and seed the administrator

### 7.1 Request a real verification email

In Firebase Console **Project settings → General → Your apps**, copy the
**web API key for the confirmed `srmtrpai` web app**. With the venv active and
in the repository root, use hidden prompts. The helper authenticates with
Firebase, requests a verification link, and never prints its password, ID token
or refresh token. This does not grant portal access.

```bash
set +x
read -r -s -p 'Firebase web API key (hidden): ' FIREBASE_WEB_API_KEY
printf '\n'
read -r -s -p 'New Firebase administrator password (hidden): ' FIREBASE_USER_PASSWORD
printf '\n'
export FIREBASE_WEB_API_KEY FIREBASE_USER_PASSWORD
python scripts/send_firebase_verification.py 814725105014@trp.srmtrichy.edu.in
```

Open the email in **that account's mailbox**, follow Firebase's verification
link, then return to the **same** Git Bash window and check the freshly signed
in identity:

```bash
python scripts/send_firebase_verification.py 814725105014@trp.srmtrichy.edu.in --check
```

After the check, clear both values even if it failed:

```bash
unset FIREBASE_USER_PASSWORD FIREBASE_WEB_API_KEY
```

The check must say the email is verified. If it fails, stop: check spam, the
Firebase email template/quota, project/API-key restrictions and the password.
A browser-referrer-only web API key can reject this command-line REST flow;
use an appropriately restricted temporary API key or an approved Admin SDK
verification-link workflow rather than weakening a production key. Do not mark
an email verified by hand unless a trusted administrator independently
confirmed both mailbox ownership and control of that specific Firebase account.
If a temporary API key was used for the helper, it must **not** accidentally
replace the app's confirmed web key in §8.

### 7.2 Review existing access and add the initial administrator

Use the **same MongoDB database** as Cloud Run. The access CLI validates a
nonempty `JWT_SECRET` but does not sign sessions; generate a temporary local
value, not the runtime signing key:

```bash
export MONGO_DB_NAME=srmtrpai ENVIRONMENT=production
export JWT_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
python -m backend.manage_access list
```

If initialization reports a network/TLS/DNS error, it does **not** establish
whether the password is correct. Check the workstation Atlas IP entry, cluster
state, TLS, URI encoding and network first. If it reports auth/permission
failure, check the new database user, role and URI. Do not print the URI while
troubleshooting.

**Before granting or reactivating access**, review the list, Firebase Auth
users, and Atlas **Database → Browse Collections → `srmtrpai` → `users`**.
Compare any existing `firebase_uid` for this email with the verified account's
UID in Firebase. Investigate and deactivate unauthorized entries. `add` on an
existing email updates its role and **reactivates** it; it does not replace an
existing UID. `unlink` is appropriate only after an administrator verifies the
intended replacement identity.

Once the account and UID are trusted:

```bash
python -m backend.manage_access add 814725105014@trp.srmtrichy.edu.in --role head_admin
python -m backend.manage_access list
```

Confirm the exact email is **active** and has role `head_admin`. Keep the
`MONGO_URI` variable in this shell for §8. Later user access can be managed
with `python -m backend.manage_access --help`; never grant a role merely
because a person registered with Firebase.

## 8. Secret Manager: create/rotate values and grant the runtime access

The following four names are referenced by `deploy/cloudbuild.yaml`:

| Secret | Runtime variable | Purpose |
| --- | --- | --- |
| `mongo-uri` | `MONGO_URI` | The newly rotated Atlas application URI |
| `jwt-secret` | `JWT_SECRET` | Random application session-signing secret |
| `device-keys` | `DEVICE_API_KEYS` | Random device ingestion key(s) |
| `firebase-api-key` | `FIREBASE_API_KEY` | Confirmed Firebase web API key |

First list **metadata only**. If a secret already exists, check that it belongs
to this deployment and is not shared with an unrelated service. Adding a
version changes `latest` for future starts of any service using that secret.

```bash
gcloud secrets list --project="$PROJECT_ID" --format='table(name,createTime)'
```

Create **only the names that are absent**; if a create command reports that a
name exists, inspect it rather than deleting it:

```bash
gcloud secrets create mongo-uri --replication-policy=automatic --project="$PROJECT_ID"
```

```bash
gcloud secrets create jwt-secret --replication-policy=automatic --project="$PROJECT_ID"
```

```bash
gcloud secrets create device-keys --replication-policy=automatic --project="$PROJECT_ID"
```

```bash
gcloud secrets create firebase-api-key --replication-policy=automatic --project="$PROJECT_ID"
```

After all four exist and their use has been reviewed, add **new versions**.
This deliberately rotates the JWT signing key and the device key. It makes
existing sessions invalid after all traffic is on the new revision and old
reachable revisions have been retired. If existing devices are in use, plan a
secure key cutover; a new random key is created here, not displayed.

```bash
set +x
set -o pipefail
[ -n "$MONGO_URI" ] && printf '%s' "$MONGO_URI" | \
  gcloud secrets versions add mongo-uri --data-file=- --project="$PROJECT_ID"
```

```bash
python -c 'import secrets,sys; sys.stdout.write(secrets.token_urlsafe(48))' | \
  gcloud secrets versions add jwt-secret --data-file=- --project="$PROJECT_ID" &&
python -c 'import secrets,sys; sys.stdout.write(secrets.token_urlsafe(48))' | \
  gcloud secrets versions add device-keys --data-file=- --project="$PROJECT_ID"
```

Privately re-enter the **confirmed Firebase web app key** from §3 (not a
separate temporary verification-helper key), then create the secret version:

```bash
read -r -s -p 'Confirmed Firebase web app API key (hidden): ' FIREBASE_WEB_API_KEY
printf '\n'
[ -n "$FIREBASE_WEB_API_KEY" ] && printf '%s' "$FIREBASE_WEB_API_KEY" | \
  gcloud secrets versions add firebase-api-key --data-file=- --project="$PROJECT_ID"
```

After confirming the command succeeded, clear the shell variable:

```bash
unset FIREBASE_WEB_API_KEY
```

`printf '%s'` avoids a trailing newline. Stop if a value was empty or a
version-add command failed. Authorized device provisioning must retrieve the
device key through a secure channel; never print it into chat. If you replace
an Atlas password later, update `mongo-uri` and redeploy the backend. The
runtime identity needs access to each secret:

```bash
BINDING_FAILED=0
for SECRET in mongo-uri jwt-secret device-keys firebase-api-key; do
  if ! gcloud secrets add-iam-policy-binding "$SECRET" --project="$PROJECT_ID" \
    --member="serviceAccount:$RUN_SA" --role=roles/secretmanager.secretAccessor \
    --condition=None; then
    BINDING_FAILED=1
    break
  fi
done
if [ "$BINDING_FAILED" -ne 0 ]; then
  echo 'STOP: at least one secret IAM grant failed.' >&2
else
  echo 'All four secret IAM grants succeeded.'
fi
```

Check that **each** binding succeeded before continuing. Secret Manager and
IAM changes may take a few minutes to propagate. Existing Cloud Run revisions
that used an old JWT key must no longer be reachable if that key was
compromised; renaming a cookie alone does not revoke a copied JWT.

## 9. Deploy backend, then Hosting

This operation changes the real Google Cloud/Firebase project. The build uses
its dedicated identity, sets all-traffic Direct VPC egress **on the first
revision**, and uses the four Secret Manager values. Its `--set-env-vars` and
`--set-secrets` replace the corresponding settings on an existing Cloud Run
service; inspect and plan a cutover first if that service already exists.

```bash
cd ~/frontend
source .venv/Scripts/activate
git status --short
gcloud meta list-files-for-upload
```

Review the upload list **before** submitting. `.gcloudignore` includes the
application, Dockerfile and `best.pt`, while excluding `.env`, JSON keys,
tests and common personal data. Ignore rules are not a credential scanner;
stop if any secret, onboarding document, real driver/bus register or personal
media appears. Confirm your local checkout is the reviewed merged code.

```bash
gcloud builds submit . --project="$PROJECT_ID" \
  --config=deploy/cloudbuild.yaml \
  --gcs-source-staging-dir="gs://$BUILD_BUCKET/source"
```

Wait for **SUCCESS**. The build uses the unique Cloud Build `BUILD_ID` image
tag and deploys that image to Cloud Run. It may take several minutes to install
the vision stack. A failed build means **stop**, inspect the Cloud Build and
Cloud Run logs, and do not deploy Hosting as if the backend succeeded. For
builds triggered automatically, configure the same dedicated identity on the
trigger: a trigger's service account overrides the YAML `serviceAccount`.

Check the service and its actual URL:

```bash
gcloud run services describe srm-trp-transport --region="$REGION" --project="$PROJECT_ID"
RUN_URL="$(gcloud run services describe srm-trp-transport --region="$REGION" \
  --project="$PROJECT_ID" --format='value(status.url)')"
printf 'Cloud Run URL: %s\n' "$RUN_URL"
curl -fsS "$RUN_URL/api/health"
```

In Cloud Run → service → **Networking / Revisions**, confirm Direct VPC
`srm-trp-vpc`, subnet `srm-trp-subnet`, **all traffic**, runtime identity
`$RUN_SA`, and the HTTP startup probe. `/api/health` is served only after the
app has initialized MongoDB, so it is useful for startup; it is not a
continuous database health monitor. Public invocation is required for this
Hosting rewrite; application authentication still protects data routes.

Finally publish Hosting, using the verified default site:

```bash
firebase deploy --only hosting --project=srmtrpai
```

A successful deployment publishes static files and the Cloud Run rewrite. It
does not create the Firebase account, Atlas access entry or network resources
for you. When finished with the Atlas session, clear local environment values:

```bash
unset MONGO_URI JWT_SECRET
```

## 10. Verify the complete connection

The commands below assume the default site really is `srmtrpai`; otherwise use
the actual site URL you verified in §3 and update the Firebase configuration.

```bash
curl -fsS https://srmtrpai.web.app/api/health
curl -fsS https://srmtrpai.web.app/api/auth/config
curl -fsS https://srmtrpai.web.app/api/config/firebase | \
  python -c 'import json,sys; d=json.load(sys.stdin); print("enabled:", d.get("enabled"), "project:", d.get("projectId"), "has API key:", bool(d.get("config", {}).get("apiKey")))'
curl -sS -o /dev/null -w 'Unauthenticated /api/auth/me: %{http_code}\n' \
  https://srmtrpai.web.app/api/auth/me
curl -sS -o /dev/null -w 'Unauthenticated /dashboard: %{http_code}\n' \
  https://srmtrpai.web.app/dashboard
curl -sS -L -o /dev/null -w 'Direct template URL: %{http_code}\n' \
  https://srmtrpai.web.app/pages/dashboard.html
```

Expected: health `status: ok`; Firebase config enabled for `srmtrpai` with
`has API key: True`; `/api/auth/config` reports Firebase enabled, providers
`password` and `google.com`, `auto_provision: false`,
`legacy_password_login: false`; unauthenticated `me` is **401**, dashboard
redirects to login, and a direct page-template URL is not served as a static
protected page (normally **404**).

Then, in a private browser window:

1. Open `https://srmtrpai.web.app/`, sign in as
   `814725105014@trp.srmtrichy.edu.in` using the **new private password**,
   and confirm the head-admin dashboard and data requests work.
2. Refresh `/dashboard` directly. In browser developer tools, verify a
   `Secure`, `HttpOnly`, `SameSite=Lax` cookie named `__session` exists; do
   **not** copy its value. Test sign-out and confirm protected requests are
   denied afterward.
3. Test an independently verified but **unapproved** Firebase/Google account:
   it must be refused. Test that unverified, inactive, and wrong-role accounts
   are refused as appropriate. Do not use a real unauthorized person's
   account for testing.
4. Test the operator webcam over HTTPS, and the real detector/Atlas integration
   only after rights, privacy and production approvals are complete. If using
   Google redirect sign-in from `web.app`, test the actual browsers and follow
   [Firebase's redirect guidance](https://firebase.google.com/docs/auth/web/redirect-best-practices)
   for same-origin auth helpers and OAuth redirect URIs; otherwise allow the popup.

Firebase Hosting has a **60-second request timeout** even though Cloud Run is
configured for 300 seconds. A cold start waiting for NAT/Atlas can time out at
Hosting before the service is ready; inspect service health and retry. Long
camera/SSE streams and slow detection requests may be interrupted and need
real testing or an alternative streaming/processing architecture. See
[Firebase's Hosting serverless limits](https://firebase.google.com/docs/hosting/serverless-overview).

For logs (read privately; redact before sharing):

```bash
gcloud builds list --project="$PROJECT_ID" --limit=5
gcloud run services logs read srm-trp-transport --region="$REGION" \
  --project="$PROJECT_ID" --limit=100
```

## 11. Production gates

- [ ] Rotate/revoke **both** exposed Atlas credentials and verify old access
      no longer works; review Atlas users and network access.
- [ ] Reset the password that appeared in chat if it was ever configured.
- [ ] Review existing Firebase users, access entries, UID bindings, audit logs,
      and old sessions from earlier versions; deactivate unauthorized entries.
- [ ] Rotate `JWT_SECRET`, deploy the new revision, and retire old reachable
      revisions/secret versions as appropriate. A captured JWT is not revoked
      merely by the cookie-name change; users must sign in again.
- [ ] Purge sensitive data from Git history **after rotation**. Coordinate a
      repository-wide rewrite with all collaborators and GitHub Support; a
      normal new commit does not erase old commits, pull requests, forks or
      cached copies. Follow [GitHub's sensitive-data removal guide](https://docs.github.com/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).
      This guide does not perform that destructive history rewrite for you.
- [ ] Resolve the provenance/licence of `best.pt` and the model's upstream
      material before production use or distribution.
- [ ] Verify the actual Firebase configuration, real email verification,
      least-privilege Atlas user, static NAT IP, IAM, secrets, real login,
      unauthorized-user denial, sign-out and camera/detector behavior.
- [ ] Review budgets, backups, audit retention, privacy obligations, CORS,
      and distributed rate limiting. The default in-memory rate limiter is per
      process/instance and is not a global brute-force control.

## 12. Troubleshooting, updates and rollback

| Symptom | First checks |
| --- | --- |
| `node`, `npm`, `gcloud`, or `firebase` not found | Reopen Git Bash; use the PATH fallbacks in §1. Do not substitute a literal `you` path. |
| Python opens Microsoft Store | Use `py -3.11` and `.venv/Scripts/activate`; repair Windows app execution aliases. |
| `Permission denied` during build | Confirm the human submitter can act as `$BUILD_SA`; the builder has source-bucket read, Artifact Registry write, Cloud Run deploy and act-as-`$RUN_SA`; review organization policy. |
| Cloud Run startup fails | Inspect Cloud Run logs privately; verify all four secrets and runtime grants, Direct VPC/NAT, Atlas `NAT_IP/32`, DNS/TLS, database user and index permissions. |
| Local Atlas CLI cannot connect | Verify the **workstation** public IP entry as well as URI encoding and network/TLS; a TLS timeout does not prove credentials are wrong. |
| `Verify your email` | Run §7.1 and follow the link; a Firebase user or reset password alone is not verification. |
| `not authorised` or a different-UID error | Inspect the active `srmtrpai.users` entry and compare UID with the trusted Firebase account before adding or unlinking. |
| Login returns to login / dashboard shows login page | Confirm updated `firebase.json`, Hosting deployment, `__session`, Cloud Run region/service, and clean URLs. Existing browser sessions must sign in again. |
| Cloud Run health works but `/api/config/firebase` is disabled | Check the confirmed web app ID, project ID and `firebase-api-key` secret; redeploy after updating. |
| Camera denied despite HTTPS | Check the browser permission and the actual page's `Permissions-Policy`; both Hosting and Flask should allow `camera=(self)`. |

To update later, reactivate the venv, safely fast-forward your **clean** local
`main`, inspect `gcloud meta list-files-for-upload`, and repeat the build and
Hosting commands in §9. Re-export the project/bucket variables from §5. Never
use `git reset --hard` to repair a checkout containing work.

To roll back a Cloud Run revision, first review the security implications of
restoring its old code, environment and signing key:

```bash
gcloud run revisions list --service=srm-trp-transport --region="$REGION" --project="$PROJECT_ID"
# Replace REVISION_ID with a specific known-good revision after review.
gcloud run services update-traffic srm-trp-transport --region="$REGION" \
  --project="$PROJECT_ID" --to-revisions=REVISION_ID=100
```

For Hosting, use **Firebase Console → Hosting & Serverless → Hosting → Release
history → menu → Roll back**. The Hosting rewrite is not pinned to a Cloud Run
revision, so rolling back one side does not roll back the other. A rollback to
an old revision may restore a compromised secret or insecure behavior; do not
assume it is safe.
