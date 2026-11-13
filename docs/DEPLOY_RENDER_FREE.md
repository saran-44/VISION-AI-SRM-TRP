# Free backend: Render (single service) + Supabase + Firebase

This is the **zero-cost** deployment. It needs no billing account and no card.

| Piece | Where it runs (free) | Cost |
| --- | --- | --- |
| Flask API **and** the website it serves | **Render** web service, free plan, Singapore | $0 |
| Database | **Supabase** PostgreSQL, free project | $0 |
| Sign-in | **Firebase Authentication**, Spark plan | $0 |

Because `backend/app.py` already serves `frontend/` (login page, `assets/`,
`js/`, `vendor/` and every protected page), a single Render service is the whole
application. That matters: Firebase Hosting rewrites can only target **Cloud
Run** or **Cloud Functions**, so a free host cannot sit behind the checked-in
`firebase.json` rewrite. Opening the Render URL directly avoids that entirely,
and keeps everything same-origin, which the `__session` cookie requires.

Do **not** deploy `frontend/` to Firebase Hosting in this mode, and do not open
`frontend/index.html` as a file. Use the Render URL.

> Differences from the Cloud Run path: no vision/OCR (512 MB RAM cannot hold
> torch), the instance sleeps after 15 minutes idle, and there is exactly one
> application instance. Read [§7](#7-limits-of-this-free-path) before real use.
> The Cloud Run runbook stays in [`DEPLOY_GITBASH_QUICKSTART.md`](DEPLOY_GITBASH_QUICKSTART.md).

---

## 1. Local prerequisites (Git Bash)

```bash
git --version && node --version && py -3.11 --version
cd ~ && git clone https://github.com/saran-44/VISION-AI-SRM-TRP.git && cd VISION-AI-SRM-TRP
py -3.11 -m venv .venv && source .venv/Scripts/activate
python -m pip install -U pip && python -m pip install -r backend/requirements.txt
python -m pytest -q          # expect ~178 passed, 4 skipped
```

Render deploys from a **Git branch**, so the branch you deploy must contain
`render.yaml`, `deploy/render/Dockerfile` and `deploy/render/entrypoint.sh`.
Merge them into `main` (or point Render at the branch) before step 3.

```bash
git fetch origin && git switch main && git pull --ff-only
ls render.yaml deploy/render/Dockerfile deploy/render/entrypoint.sh
```

---

## 2. Supabase database (once)

1. Create a project in region **South Asia (Mumbai)**; store the database
   password in a password manager.
2. **SQL Editor** → paste the whole of `backend/sql/001_initial.sql` → **Run**
   once. It fails loudly if the schema already exists; never drop it to "fix" it.
3. **Project Settings → Database → SSL Configuration** → download the CA
   certificate to a private folder.
4. **Connect → Session pooler** → copy the host and the project reference.
5. Leave **Network Restrictions disabled** — Render's outbound IPs are dynamic.

Create the least-privilege login and a private `.env` (this `.env` is only used
from your laptop; Render gets the same values as environment variables):

```bash
[ -e .env ] && echo 'STOP: .env exists — back it up and move it aside.' || \
  winpty python scripts/configure_supabase.py
python -m backend.manage_access list     # proves TLS, CA and grants work
```

---

## 3. Deploy on Render

```bash
# 1. Commit and push first: Render builds from Git, not from your laptop.
git status --short
```

In the Render dashboard — <https://dashboard.render.com> → **New → Blueprint**:

1. Connect the GitHub repository `saran-44/VISION-AI-SRM-TRP` and the branch
   that contains `render.yaml`.
2. Render reads the Blueprint and shows one service, `srm-trp-transport`,
   **Free**, Docker, Singapore.
3. Fill the four prompted values (`sync: false`). All four are in your private
   `.env` — open it with `notepad.exe .env` and copy, never paste into chat:

   | Render key | Comes from |
   | --- | --- |
   | `DATABASE_URL` | `.env` → must end with `?sslmode=verify-full` |
   | `JWT_SECRET` | `.env` |
   | `DEVICE_API_KEYS` | `.env` |
   | `FIREBASE_API_KEY` | `.env` (public identifier) |

   `PGSSLROOTCERT_B64` is the fifth secret — build it from the certificate you
   downloaded, as one line with no newlines:

   ```bash
   base64 -w0 "/c/Users/<you>/srm-trp-private/prod-ca-2021.crt" > ca.b64
   notepad.exe ca.b64      # copy the single line, then delete the file
   rm -f ca.b64
   ```

4. **Apply**. The Docker build takes ~4–8 minutes (no torch, so it is far
   smaller than the Cloud Run image).
5. When the log shows `Listening at: http://0.0.0.0:10000` and the health check
   passes, note the URL: `https://srm-trp-transport.onrender.com`.

How the CA works without a mounted file: `deploy/render/entrypoint.sh` decodes
`PGSSLROOTCERT_B64` into `/tmp/srm-trp-certs/supabase-ca.crt` at boot and exports
`PGSSLROOTCERT`, so `sslmode=verify-full` still verifies the server certificate
and host name.

Confirm the service picked up the right config:

```bash
BASE=https://srm-trp-transport.onrender.com     # your actual URL
curl -fsS "$BASE/api/health"; echo
curl -fsS "$BASE/api/auth/config"; echo
curl -sS -o /dev/null -w 'unauthenticated /api/auth/me: %{http_code}\n' "$BASE/api/auth/me"
curl -sS -o /dev/null -w 'unauthenticated /dashboard:  %{http_code}\n' "$BASE/dashboard"
```

Expect `ok`, a config that lists `password` (and `google` if enabled), `401`,
and a redirect. A `500` here means the database, the CA or `DATABASE_URL` is
wrong — check **Logs** in Render; the app prints a bounded retry warning before
giving up.

---

## 4. Firebase: authorize the new domain

Firebase Console → **Authentication**:

1. Enable **Email/Password** (and **Google** if you want it).
2. **Settings → Authorized domains → Add domain** →
   `srm-trp-transport.onrender.com`. Sign-in fails without this.
3. **Users → Add user** → the administrator, e.g.
   `814725105014@trp.srmtrichy.edu.in`, with a new strong password.

Verify the mailbox, then grant portal access in Postgres (both steps run from
your laptop against the same Supabase database):

```bash
source .venv/Scripts/activate
set +x
FIREBASE_WEB_API_KEY="$(python -c 'from dotenv import dotenv_values; print(dotenv_values(".env")["FIREBASE_API_KEY"])')"
read -r -s -p 'Firebase password (hidden): ' FIREBASE_USER_PASSWORD; printf '\n'
export FIREBASE_WEB_API_KEY FIREBASE_USER_PASSWORD
python scripts/send_firebase_verification.py 814725105014@trp.srmtrichy.edu.in
# click the link in the mailbox, then:
python scripts/send_firebase_verification.py 814725105014@trp.srmtrichy.edu.in --check
unset FIREBASE_USER_PASSWORD FIREBASE_WEB_API_KEY

python -m backend.manage_access add 814725105014@trp.srmtrichy.edu.in --role head_admin
python -m backend.manage_access list
```

Everyone else also needs an entry (`--role transport_office` is least
privilege), or the **Manage** page once you are signed in as `head_admin`.

---

## 5. Verify end to end

Open `https://srm-trp-transport.onrender.com` in a private window and check:

1. The Firebase login screen appears (if it does not, `FIREBASE_*` values are
   missing — see `/api/config/firebase`).
2. Sign-in succeeds for the verified, access-listed administrator.
3. `/dashboard`, `/logs`, `/analytics`, `/drivers`, `/buses` load real data.
4. Browser DevTools → Application → Cookies: one `__session` cookie, `Secure`,
   `HttpOnly`, `SameSite=Lax`. Do not copy its value.
5. `/api/detection/status` reports the detector unavailable — expected, see below.
6. Sign out, then reload `/dashboard`: you must be sent back to the login page.

---

## 6. Operating it

| Task | How |
| --- | --- |
| Deploy a change | `git push` to the connected branch (auto-deploy) |
| Force a rebuild | Render dashboard → **Manual Deploy → Clear build cache & deploy** |
| Read logs | Dashboard → **Logs** (personal data may appear; restrict access) |
| New user | `python -m backend.manage_access add <email> --role transport_office` |
| Rotate the JWT secret | change `JWT_SECRET` → redeploy; all sessions end |
| Rotate the DB password | Supabase → reset → update `DATABASE_URL` → redeploy |
| Add a camera stream | `CAMERA_STREAM_URLS` env var, JSON per `docs/CAMERAS.md` |

---

## 7. Limits of this free path

| Limit | Effect | Mitigation |
| --- | --- | --- |
| 512 MB RAM, 0.1 CPU | torch/Ultralytics/OCR cannot run | Detection is disabled; use a paid instance, Hugging Face Spaces (16 GB CPU) or an Oracle Always-Free VM with `deploy/Dockerfile` |
| Sleeps after 15 min idle | First request after a pause takes 30–60 s | Acceptable for office hours; a free uptime pinger is a ToS grey area — don't rely on it |
| One instance | `memory://` rate limiting is per instance (now correct per user thanks to `TRUST_PROXY_HEADERS=true`) | Fine at this scale; move to Redis if you scale out |
| 750 instance-hours/month | One always-on service would exceed it, a sleeping one will not | Keep the service idle when unused |
| Supabase free project | Pauses after ~7 days idle; 500 MB database | Resume from the dashboard; the app retries for ~4 minutes |
| Render free disk | Ephemeral; nothing is stored locally | All state is in Supabase, so this is already correct |
| No CDN | Assets are served by gunicorn | Acceptable; revisit Cloud Run + Hosting when billing is available |

**If you later need the detector online**, use the same image definition on a
host with more RAM — `deploy/Dockerfile` (with `INSTALL_VISION=1`) already
builds torch, Ultralytics and RapidOCR. Hugging Face Spaces runs Docker images
on a free 16 GB CPU tier (expose port `7860` and set `PORT=7860`); an Oracle
Cloud Always-Free ARM VM runs the same container behind nginx. Both need the
same five environment values used here.

---

## 8. Security checklist

- [ ] `.env` and `ca.b64` never committed (`git status --short` stays clean).
- [ ] `TRUST_PROXY_HEADERS=true` **only** because Render is in front of gunicorn.
- [ ] Rotate any credential previously shared in chat or committed — the README
      records an old credential in Git history.
- [ ] Review who can see Render logs and the Supabase dashboard.
- [ ] Keep `FIREBASE_AUTO_PROVISION=false`; approve every mailbox individually.
- [ ] Enable Supabase backups and rehearse one restore before real driver and
      vehicle data goes in (`docs/PRIVACY.md`).
- [ ] Revisit `best.pt` licensing (Ultralytics AGPL-3.0 metadata) before public
      or commercial use.
