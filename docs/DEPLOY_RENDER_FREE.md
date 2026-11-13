# Complete setup from zero (free): Supabase + Render + Firebase

One linear runbook for a **brand-new Windows machine with only Git Bash**. Every
step says what to click **and** what to type. Total cost: **₹0**.

| Piece | Where it runs (free) | Why |
| --- | --- | --- |
| Flask API **and** the whole website | **Render** web service, Free, Singapore | `backend/app.py` already serves `frontend/`, so one container is the whole app |
| Database | **Supabase** PostgreSQL, Free project (Mumbai) | private `transport_portal` schema |
| Sign-in | **Firebase Authentication**, Spark plan | email/password + Google |

Read [§10](#10-limits-of-the-free-plan) before putting real driver data in.

---

## 0. What you create or enable (the whole list)

| # | Create / enable | Where | Needed for |
| --- | --- | --- | --- |
| 1 | Python 3.11 + Git (**Git Bash**) | winget, step 1 | running scripts locally |
| 2 | Supabase account + **one project** | <https://supabase.com/dashboard> | the database |
| 3 | `transport_portal` schema | Supabase → **SQL Editor** | tables the app requires |
| 4 | **CA certificate** download | Supabase → **Project Settings → Database → SSL Configuration** | `sslmode=verify-full` |
| 5 | **Session pooler** host + project ref | Supabase → **Connect** (top bar) | the connection URL |
| 6 | DB login `transport_portal_app` + local `.env` | `scripts/configure_supabase.py` | least-privilege runtime user |
| 7 | Render account (sign in with GitHub) | <https://dashboard.render.com> | hosting |
| 8 | **Blueprint** from this repo (`render.yaml`) | Render → **New → Blueprint** | creates the service |
| 9 | 5 environment values in Render | Render → service → **Environment** | secrets + public Firebase IDs |
| 10 | **Email/Password** provider enabled | Firebase Console → **Authentication → Sign-in method** | login |
| 11 | **Authorized domain** `…onrender.com` | Firebase Console → **Authentication → Settings → Authorized domains** | login from the Render URL |
| 12 | Firebase **user** for the administrator | Firebase Console → **Authentication → Users** | the account |
| 13 | Email **verified** + row in the access list | verification script + `backend.manage_access` | authorization |
| 14 | *(optional)* Firebase **Hosting** redirect | `firebase deploy --only hosting` — [guide](DEPLOY_FIREBASE_REDIRECT.md) | the `…web.app` address |

**You do NOT need** — for this free path only: a Google Cloud billing account,
`gcloud`, Docker Desktop, the **Supabase CLI** (`supabase init` / `supabase link`
/ `supabase db push`), or any Supabase API key (`sb_publishable_…`, anon or
service-role). The schema is applied once through the **SQL Editor**, and the
app talks to Postgres directly through the session pooler, never through the
Supabase Data API. (The Cloud Run path is in
[`DEPLOY_GITBASH_QUICKSTART.md`](DEPLOY_GITBASH_QUICKSTART.md).)

**Optional:** the Firebase CLI (`firebase-tools`) only if you also want the
`vision-ai-srmtrp.web.app` address. On the Spark plan Hosting cannot rewrite to
Cloud Run, so `firebase.json` **redirects** every path to the Render service —
see [`DEPLOY_FIREBASE_REDIRECT.md`](DEPLOY_FIREBASE_REDIRECT.md). The app works
fully without it: Render is the real address.

Keep a private folder for the certificate and `.env`, e.g.
`C:\Users\<you>\srm-trp-private\`.

---

## 1. Install the two tools you need

```bash
WINGET=winget.exe
if ! command -v "$WINGET" >/dev/null 2>&1; then
  WINGET="$(cygpath -u "$LOCALAPPDATA")/Microsoft/WindowsApps/winget.exe"
fi
"$WINGET" install --exact --id Python.Python.3.11 --source winget
"$WINGET" install --exact --id Git.Git --source winget
```

Close every Git Bash window and open a new one, then verify:

```bash
git --version && py -3.11 --version
```

`py -3.11` must print a real version, not open the Microsoft Store. If `git` is
missing, install **Git for Windows** from <https://git-scm.com/download/win> and
reopen Git Bash.

---

## 2. Get the code and prove it works locally

```bash
cd ~
git clone https://github.com/saran-44/VISION-AI-SRM-TRP.git
cd VISION-AI-SRM-TRP
git log -1 --oneline
ls render.yaml deploy/render/Dockerfile deploy/render/entrypoint.sh
```

All three `ls` paths must exist. They only exist on `main` after PR #10 was
merged; if one is missing, run `git switch main && git pull --ff-only`.

```bash
py -3.11 -m venv .venv
source .venv/Scripts/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
python -m pytest -q          # expect ~182 passed, 4 skipped
```

These tests use disposable in-memory SQLite. They never touch Supabase.

---

## 3. Supabase — create the database

**Browser:**

1. <https://supabase.com/dashboard> → sign in → **New project**.
   - Organisation: your default org.
   - Name: `srm-trp`.
   - Database password: **Generate a password** → copy it into a password manager.
     You will need it once, in step 4.
   - Region: **South Asia (Mumbai)** — `ap-south-1`.
   - Plan: **Free**.
2. Wait ~2 minutes until the project is `Active`.

**Browser — apply the schema (once):**

3. Open the migration in Notepad so you can read what you are running:

   ```bash
   notepad.exe "$(cygpath -w "$PWD/backend/sql/001_initial.sql")"
   ```

4. Supabase → **SQL Editor** → **New query** → paste the **entire** file →
   **Run**. It prints `Success. No rows returned`.
   It is one transaction and **fails if the schema already exists** — never drop
   the schema to "fix" a failure; inspect the error instead.
5. Confirm it worked — same SQL Editor:

   ```sql
   select version from transport_portal.schema_version;
   ```

   Must return exactly `1`.

**Browser — TLS certificate:**

6. **Project Settings** (gear) → **Database** → **SSL Configuration** →
   **Download certificate**. Save it as
   `C:\Users\<you>\srm-trp-private\prod-ca-2021.crt` (the file name may differ;
   it is a `.crt` root certificate). This is the file that makes
   `sslmode=verify-full` work.

**Browser — connection details:**

7. **Connect** (button at the top) → tab **Session pooler** → copy:
   - **Host** — looks like `aws-1-ap-south-1.pooler.supabase.com`
   - **Project reference** — the subdomain in your project URL,
     e.g. `abcdefghijklmnop` in `https://abcdefghijklmnop.supabase.co`.

   Use the **Session pooler** (port 5432), not the direct connection and not the
   transaction pooler.
8. **Project Settings → Database → Network Restrictions**: leave **disabled**
   for now (Render's outbound IPs change). Enabling them requires the Cloud NAT
   setup in the other runbook.

Do **not** add `transport_portal` to the exposed Data API schemas.

---

## 4. Create the app login and the private `.env`

```bash
source .venv/Scripts/activate
[ -e .env ] && echo 'STOP: .env exists — back it up and move it aside first.' || \
  winpty python scripts/configure_supabase.py
```

`winpty` is required, otherwise the hidden password prompt does not render.
Answer the prompts with:

| Prompt | What to type |
| --- | --- |
| Pooler host (host only) | `aws-1-ap-south-1.pooler.supabase.com` (no `https://`, no port) |
| Supabase project reference | `abcdefghijklmnop` |
| Absolute Windows path to CA | `C:/Users/<you>/srm-trp-private/prod-ca-2021.crt` |
| Administrator password (hidden) | the Supabase database password from step 3 |
| Confirmation | `CREATE` |

The script creates role `transport_portal_app` (no superuser, no bypass-rls,
audit logs append-only), writes a git-ignored `.env` with a fresh `JWT_SECRET`
and `DEVICE_API_KEYS`, and then **tests the new login** against every table.

Prove the connection works and start with an empty access list:

```bash
python -m backend.manage_access list
```

No secret is printed. If this command fails, stop — Render will fail too.

---

## 5. Render — deploy the backend

**Browser — once:**

1. <https://dashboard.render.com> → **Sign up / Sign in with GitHub** (no card).
2. **New +** → **Blueprint**.
3. Connect GitHub if asked, then select the repository
   `saran-44/VISION-AI-SRM-TRP` and branch **`main`**.
4. Render reads `render.yaml` and shows **one** service
   `srm-trp-transport` — Free, Docker, Singapore, health check `/api/health`.
5. It prompts for the five secret values. Fill them in this order:

| Render field | Where the value comes from |
| --- | --- |
| `DATABASE_URL` | `.env` line `DATABASE_URL=` (must end with `?sslmode=verify-full`) |
| `PGSSLROOTCERT_B64` | the certificate as **one base64 line**, see below |
| `JWT_SECRET` | `.env` line `JWT_SECRET=` |
| `DEVICE_API_KEYS` | `.env` line `DEVICE_API_KEYS=` |
| `FIREBASE_API_KEY` | `.env` line `FIREBASE_API_KEY=` (public, not a secret) |

Read `.env` privately — `notepad.exe .env` — and copy/paste; never paste these
into chat, an issue or a commit.

Build the base64 certificate line (Git Bash):

```bash
base64 -w0 "/c/Users/<you>/srm-trp-private/prod-ca-2021.crt" > "$HOME/prod-ca.b64"
notepad.exe "$(cygpath -w "$HOME/prod-ca.b64")"     # copy the single line
rm -f "$HOME/prod-ca.b64"                            # delete it afterwards
```

6. Click **Apply**. The Docker build takes ~4–8 minutes.
7. Open the service → **Logs**. Success looks like
   `Listening at: http://0.0.0.0:10000` followed by the health check passing.
8. Copy the URL from the top of the page — typically
   `https://srm-trp-transport.onrender.com`. **Write it down**; step 6 needs it
   exactly, without `https://`.

If the deploy fails, the log almost always names the cause: `DATABASE_URL`,
`PGSSLROOTCERT`, or `password authentication failed` (wrong/rotated DB
password). Fix the environment value and press **Manual Deploy → Deploy latest
commit**.

Smoke-test from Git Bash:

```bash
BASE=https://srm-trp-transport.onrender.com     # your real URL
curl -fsS "$BASE/api/health"; echo
curl -fsS "$BASE/api/auth/config"; echo
curl -sS -o /dev/null -w 'me:    %{http_code}\n' "$BASE/api/auth/me"     # 401
curl -sS -o /dev/null -w 'dash:  %{http_code}\n' "$BASE/dashboard"       # 302
```

`/api/health` printing `{"status":"ok",...}` means the app reached Supabase with
verified TLS. A `500` means the database layer failed — read the Render log.

---

## 6. Firebase — enable login for this domain

**Browser** — <https://console.firebase.google.com> → project **vision-ai-srmtrp**:

1. **Authentication** → **Get started** (first time only).
2. **Sign-in method** tab → **Email/Password** → **Enable** → **Save**.
   Optional: **Google** → **Enable** → pick a support email → **Save**.
3. **Settings** tab → **Authorized domains** → **Add domain** → paste the host
   from step 5 **without** `https://`, e.g. `srm-trp-transport.onrender.com`.
   Sign-in is blocked without this exact entry. Keep
   `vision-ai-srmtrp.firebaseapp.com` and `vision-ai-srmtrp.web.app` in the list.
4. **Users** tab → **Add user** → the administrator's real address, e.g.
   `814725105014@trp.srmtrichy.edu.in`, with a **new** strong password (never a
   password that has been in a chat).
5. Stay on **Users**; you will confirm `Email verified` in step 7.

Console values that must match the repository (project settings → General):

| Item | Expected |
| --- | --- |
| Project ID | `vision-ai-srmtrp` |
| Auth domain | `vision-ai-srmtrp.firebaseapp.com` |
| Web app ID | `1:235811571442:web:342e488e0ac2ee75b0f26b` |
| Sender ID | `235811571442` |

If the live project differs, update `render.yaml` (and restart) rather than
creating a duplicate web app.

---

## 7. Verify the mailbox, then grant portal access

A Firebase account alone grants **nothing**: the build runs with
`FIREBASE_AUTO_PROVISION=false`, so every address needs a row in the access list.

```bash
source .venv/Scripts/activate
set +x
FIREBASE_WEB_API_KEY="$(python -c 'from dotenv import dotenv_values; print(dotenv_values(".env")["FIREBASE_API_KEY"])')"
read -r -s -p 'Firebase password for that account (hidden): ' FIREBASE_USER_PASSWORD
printf '\n'
export FIREBASE_WEB_API_KEY FIREBASE_USER_PASSWORD
python scripts/send_firebase_verification.py 814725105014@trp.srmtrichy.edu.in
```

Open the message in that mailbox, click the verification link, then check it:

```bash
python scripts/send_firebase_verification.py 814725105014@trp.srmtrichy.edu.in --check
unset FIREBASE_USER_PASSWORD FIREBASE_WEB_API_KEY
```

The output must say the email is verified. Now create the access row:

```bash
python -m backend.manage_access add 814725105014@trp.srmtrichy.edu.in --role head_admin
python -m backend.manage_access list
```

Both commands talk to **Supabase** through your local `.env`. Confirm the exact
address is `active` with role `head_admin`.

Every other person needs their own row — `--role transport_office` is least
privilege — or use the **Manage** page in the browser once you are signed in.

---

## 8. Verify the live portal

Open the Render URL in a **private/incognito** window:

| # | Check | Expected |
| --- | --- | --- |
| 1 | Login screen loads | email/password form (Google button only if you enabled it) |
| 2 | Wrong password | error, no session |
| 3 | The verified admin signs in | lands on `/dashboard` |
| 4 | Dashboard numbers | real counters, not blank |
| 5 | `/logs`, `/analytics`, `/drivers`, `/buses`, `/audit` | load; office role cannot see `/audit` |
| 6 | DevTools → Application → Cookies | one `__session`, `Secure`, `HttpOnly`, `SameSite=Lax` (never copy its value) |
| 7 | Sign out, then reload `/dashboard` | redirected to the login page |
| 8 | An unverified or non-listed account | denied |

`/api/detection/status` will report the detector unavailable — the free image
deliberately ships without torch. See [§10](#10-limits-of-the-free-plan).

---

## 9. Everyday operations

| Task | How |
| --- | --- |
| Deploy a code change | `git push` to `main` → Render auto-deploys |
| Redeploy same commit | Render → **Manual Deploy → Clear build cache & deploy** |
| Add a user | `python -m backend.manage_access add <email> --role transport_office` |
| Change a role | `python -m backend.manage_access set-role <email> head_admin` |
| Suspend access | `python -m backend.manage_access deactivate <email>` |
| Rotate the JWT secret | change `JWT_SECRET` in Render → redeploy → all sessions end |
| Publish the `…web.app` address | `firebase deploy --only hosting` — [guide](DEPLOY_FIREBASE_REDIRECT.md) |
| Rotate the app DB password | SQL Editor: `alter role transport_portal_app password '<new>';` → update the password inside `DATABASE_URL` → redeploy |
| Rotate a device key | change `DEVICE_API_KEYS` → redeploy → update the camera/gateway |
| Add a camera | `CAMERA_STREAM_URLS` env var, JSON per [`CAMERAS.md`](CAMERAS.md) |
| Logs | Render → **Logs** (may contain personal data; restrict access) |

---

## 10. Limits of the free plan

| Limit | Effect | Mitigation |
| --- | --- | --- |
| 512 MB RAM, 0.1 CPU | torch/Ultralytics/OCR cannot run | detection disabled; use HF Spaces (16 GB free CPU) or an Oracle Always-Free VM with `deploy/Dockerfile` |
| Sleeps after ~15 min idle | first request takes 30–60 s | fine for office hours; don't rely on pingers (ToS grey area) |
| One instance | in-memory rate limiting (`TRUST_PROXY_HEADERS=true` keeps it per user, not global) | move to Redis before scaling out |
| 750 instance-hours/month | an always-on service would exceed it; a sleeping one will not | keep it idle when unused |
| Supabase free project | pauses after ~7 days idle; 500 MB database | resume in the dashboard; the app retries for ~4 minutes |
| Ephemeral disk | nothing persists locally | all state already lives in Supabase |
| No CDN | static files come from gunicorn | acceptable here; revisit Cloud Run + Hosting later |

---

## 11. Security checklist

- [ ] `.env`, `prod-ca.b64` and the certificate are never committed
      (`git status --short` stays clean).
- [ ] The Supabase database password and the Firebase admin password are new,
      private, and not reused from any chat or document.
- [ ] Rotate the credential that the README says is still in Git history, then
      plan a history purge (rotation first; a purge does not clean forks/caches).
- [ ] `FIREBASE_AUTO_PROVISION=false` stays false; approve each mailbox.
- [ ] Supabase backups enabled and one restore rehearsed before real driver data
      (`PRIVACY.md`).
- [ ] `best.pt` rights (Ultralytics AGPL-3.0 metadata) reviewed before public or
      commercial use.
- [ ] Render log access limited to the transport office.

---

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| Render build fails on `pip install` | wrong Dockerfile path or context | the Blueprint must use `dockerfilePath: ./deploy/render/Dockerfile`, `dockerContext: .` |
| `schema version is missing or incompatible` | migration never ran, or ran on another project | run `backend/sql/001_initial.sql` in **this** project's SQL Editor |
| `password authentication failed` | DB password changed after `.env` was written | reset it, update `DATABASE_URL` in Render, redeploy |
| `certificate verify failed` / `SSL error` | CA missing, truncated, or extra whitespace | regenerate `PGSSLROOTCERT_B64` with `base64 -w0` (one line, no newlines) |
| `PostgreSQL initialization failed after retries` | network restriction enabled, or project paused | disable restrictions / resume the project |
| Timeout / `could not translate host name db.<ref>.supabase.co` | the **direct** connection was used; new projects expose it over IPv6 only | use the **Session pooler** host (`…pooler.supabase.com:5432`) instead |
| `invalid dsn` / `password authentication failed` after copy-paste | the password was not URL-encoded (`@` → `%40`, `/` → `%2F`, `:` → `%3A`) | prefer `scripts/configure_supabase.py`, which URL-encodes for you |
| Login screen shows but sign-in fails with `auth/unauthorized-domain` | Render host missing in Firebase | add the exact host in **Authorized domains** |
| `auth/invalid-api-key` | `FIREBASE_API_KEY` empty or wrong | copy from `.env` into Render, redeploy |
| Sign-in works but immediately returns to login | no access row, or email unverified | `manage_access list`, re-run the verification check |
| `python` opens the Microsoft Store | store alias | use `py -3.11` or `source .venv/Scripts/activate` |
| `winpty: command not found` | very old Git for Windows | update Git for Windows, or run the script from PowerShell |
| `/api/detection/*` returns 503 | free image has no torch | expected; see §10 |
| Page reload after a pause is slow | instance was asleep | expected; first request warms it |
