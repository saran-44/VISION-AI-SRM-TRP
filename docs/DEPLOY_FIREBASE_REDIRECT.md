# Deploy the Firebase URL (free plan → redirect to Render)

**What you get:** `https://vision-ai-srmtrp.web.app` (and
`https://vision-ai-srmtrp.firebaseapp.com`) answering with a `302` that forwards
every path to the Render service, e.g.

```text
https://vision-ai-srmtrp.web.app/dashboard?tab=2
  -> 302 Location: https://srm-trp-transport.onrender.com/dashboard?tab=2
```

**Why a redirect and not a rewrite:** Firebase Hosting can only rewrite to
**Cloud Run** or **Cloud Functions**, and both need the Blaze plan (card on
file). This project runs the Flask app on **Render Free**, so Hosting gets the
free half of the deal: a branded, HTTPS domain that forwards to the real app.
Nothing is served from Firebase, so the free quotas
(10 GB stored, 360 MB/day transfer) are irrelevant — a redirect costs bytes,
not bandwidth.

Cost: **₹0**, no billing account, no card. Firebase **Authentication** stays
exactly as it is; sign-in happens on the Render origin.

> The repository already contains the finished config (`firebase.json`,
> `.firebaserc`, `deploy/firebase/public/index.html`). You do **not** run
> `firebase init` — it would overwrite the checked-in file.

---

## 0. Before you start

| Need | Check | Expected |
| --- | --- | --- |
| Render service is live | `curl -fsS https://srm-trp-transport.onrender.com/api/health` | `{"status":"ok",…}` |
| Node LTS (not v26) | `node -v` | `v22.x` or `v20.x` |
| Firebase project | <https://console.firebase.google.com> → **vision-ai-srmtrp** | project opens |
| Repo up to date | `git -C ~/VISION-AI-SRM-TRP status -sb` | `## main...origin/main` |

If the Render URL differs from `srm-trp-transport.onrender.com`, change it once
in `firebase.json` (step 2).

> Node **v26** on Windows breaks the Firebase CLI through MSYS path mangling.
> Install Node LTS 22 with `winget install OpenJS.NodeJS.LTS`, open a new Git
> Bash window, and re-check `node -v` before continuing.

---

## 1. Confirm Render answers (do not skip)

```bash
RENDER_HOST=srm-trp-transport.onrender.com
case "$RENDER_HOST" in
  *onrender.com) echo "target: https://$RENDER_HOST" ;;
  *) echo "STOP: set RENDER_HOST to the real onrender.com host"; exit 1 ;;
esac
curl -fsS -m 90 "https://$RENDER_HOST/api/health" || {
  echo "STOP: Render is not answering. A free instance wakes in ~30-60 s;"
  echo "      open the Render dashboard, wait for 'Live', then re-run this step."
}
```

A free instance sleeps after ~15 minutes idle, so the **first** request may take
30–60 seconds. That is expected; the redirect itself is instant.

---

## 2. Point the config at your Render host (only if it differs)

```bash
cd ~/VISION-AI-SRM-TRP
RENDER_HOST=srm-trp-transport.onrender.com          # your real host, no https://

grep -c "srm-trp-transport.onrender.com" firebase.json
sed -i "s|srm-trp-transport.onrender.com|$RENDER_HOST|g" firebase.json
sed -i "s|srm-trp-transport.onrender.com|$RENDER_HOST|g" deploy/firebase/public/index.html
grep -n "onrender.com" firebase.json
```

Expected: two `destination` lines, both `https://<your-host>/…`. If `$RENDER_HOST`
is still a placeholder (`<...>`, `YOUR-…`), stop and fix it — the `case` guard in
step 3 catches that.

---

## 3. Install and sign in to the CLI

```bash
npm install -g firebase-tools@13
hash -r
firebase --version          # 13.x
```

```bash
firebase login              # opens a browser; pick the Google account that owns the project
firebase projects:list | grep -i vision-ai-srmtrp
```

Notes for Git Bash on Windows:

- If `firebase login` hangs on the localhost callback, use
  `firebase login --no-localhost` and paste the code it prints.
- If Git Bash mangles the command, call `firebase.cmd` instead, or prefix with
  `winpty`.
- **Do not** create or paste a `FIREBASE_TOKEN`. The login token lives in
  `~/.config/configstore/firebase-tools.json`; `firebase logout` removes it.

Select the project explicitly so a stale `.firebaserc` can never surprise you:

```bash
cd ~/VISION-AI-SRM-TRP
firebase use vision-ai-srmtrp
```

---

## 4. Test the redirects locally first (no network, no quota)

```bash
cd ~/VISION-AI-SRM-TRP
firebase emulators:start --only hosting
```

In a **second** Git Bash window:

```bash
for p in / /login /dashboard "/dashboard?tab=2" /api/health /assets/theme.css /whatever; do
  printf '%-22s -> ' "$p"
  curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' "http://127.0.0.1:5000$p"
done
```

Expected, exactly:

```text
/                      -> 302 https://srm-trp-transport.onrender.com/
/login                 -> 302 https://srm-trp-transport.onrender.com/login
/dashboard             -> 302 https://srm-trp-transport.onrender.com/dashboard
/dashboard?tab=2       -> 302 https://srm-trp-transport.onrender.com/dashboard?tab=2
/api/health            -> 302 https://srm-trp-transport.onrender.com/api/health
/assets/theme.css      -> 302 https://srm-trp-transport.onrender.com/assets/theme.css
/whatever              -> 302 https://srm-trp-transport.onrender.com/whatever
```

Stop the emulator with `Ctrl+C` in the first window before deploying.

---

## 5. Deploy

```bash
cd ~/VISION-AI-SRM-TRP
firebase deploy --only hosting --project vision-ai-srmtrp
```

Expected tail:

```text
✔  Deploy complete!
Hosting URL: https://vision-ai-srmtrp.web.app
```

The CLI mentions that it could not enable the required API or that some
features need Blaze — ignore it, Hosting itself is free.

---

## 6. Verify the live URL

```bash
curl -sI https://vision-ai-srmtrp.web.app/dashboard | grep -iE "^(HTTP|location)"
```

Expected:

```text
HTTP/2 302
location: https://srm-trp-transport.onrender.com/dashboard
```

Follow it end to end:

```bash
curl -sL -o /dev/null -w '%{http_code} after redirect\n' https://vision-ai-srmtrp.web.app/
```

Expected `200` — that is the Flask login page **from Render**.

Then in a browser (private window):

1. Open <https://vision-ai-srmtrp.web.app> → it should land on the Render login
   page with the address bar showing `srm-trp-transport.onrender.com`.
2. Sign in as `814725105014@trp.srmtrichy.edu.in` → `/dashboard`.
3. Click **Logs**, **Analytics**, **Drivers**, **Buses**, **Audit**, reload, sign
   out. Every link must resolve on the Render origin.

---

## 7. Firebase Console — one setting to check

Firebase Auth runs on the **Render** origin after the redirect, so:

**Authentication → Settings → Authorized domains** must contain
`srm-trp-transport.onrender.com` (add it if step 11 of
[DEPLOY_RENDER_FREE.md](DEPLOY_RENDER_FREE.md) was skipped). Without it signing
in fails with `auth/unauthorized-domain`.

`vision-ai-srmtrp.web.app` and `vision-ai-srmtrp.firebaseapp.com` being in that
list is harmless but useless for this topology.

---

## 8. Everyday operations

| Task | How |
| --- | --- |
| Redeploy the same commit | `firebase deploy --only hosting` |
| Change the Render URL | edit the two destinations, `firebase deploy --only hosting` |
| Serve the site from Firebase instead | needs Blaze + Cloud Run rewrite — see [DEPLOY_GITBASH_QUICKSTART.md](DEPLOY_GITBASH_QUICKSTART.md) |
| Remove the Firebase URL | `firebase hosting:disable --project vision-ai-srmtrp` |
| Roll back a bad deploy | `firebase hosting:rollback --project vision-ai-srmtrp` |

Nothing about the backend or database is touched by these commands — the
redirect is a single config file on Firebase's CDN.

---

## 9. Why `302` and not `301`

A `301` is cached **permanently by browsers**: if the Render host ever changes,
every visitor who saw the old one keeps going there with no way for you to fix
it server-side. `302` keeps the mapping under your control at the cost of one
extra round trip. The check `test_hosting_redirects_every_path_to_the_free_render_backend`
in `backend/tests/test_hosting_deployment.py` fails if anyone switches it to 301.

---

## 10. Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `Error: Failed to get Firebase project` | wrong Google account → `firebase logout` then `firebase login` |
| `HTTP Error: 403` on deploy | the signed-in account is not an Owner/Editor of `vision-ai-srmtrp` |
| `public directory does not exist` | run the command from the repo root (`cd ~/VISION-AI-SRM-TRP`) |
| Deploy succeeds, `web.app` shows the fallback page | another project/site is targeted → `firebase use --add`, check `firebase.json` |
| `web.app/...` returns `404` instead of `302` | an older config is live → `firebase deploy --only hosting` again, then hard-refresh |
| Browser shows the Render site but with the `web.app` address | the redirect was cached — clear site data for `web.app` |
| `auth/unauthorized-domain` after signing in | add the Render host in **Authorized domains** (step 7) |
| `firebase: command not found` | `npm install -g firebase-tools`, then `hash -r` |
| Untracked `firebase-redirect/` or `firebase.hosting.redirect.json` in `git status` | leftovers from an earlier `firebase init` or an ad-hoc deploy. Inspect them (`cat firebase.hosting.redirect.json`), then delete them — this repository's config is the tracked `firebase.json` |
| Emulator port 5000 busy | another dev server owns it; change `emulators.hosting.port` in `firebase.json` |

---

## 11. What was verified in this repository

| Check | Result |
| --- | --- |
| `firebase emulators:start --only hosting` with the checked-in config | `/`, `/login`, `/dashboard`, `/dashboard?tab=2`, `/api/health`, `/assets/theme.css`, `/whatever` all `302` to the matching Render path (query strings preserved) |
| `pytest backend/tests/test_hosting_deployment.py` | 4 passed — redirect rules, fallback page, and the `__session` cookie boundary |
| `node scripts/check_frontend.mjs` | unchanged frontend, all references resolve |

A live deploy cannot be executed from a sandbox without Google network access —
step 5 is the one command that must run on your machine.
