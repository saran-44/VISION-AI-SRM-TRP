# Authentication — Firebase sign-in with a restricted access list

This document explains how the SRM TRP Transport console authenticates, how
access is restricted to specific email addresses, and exactly what to click in
the Firebase console.

> **Recommendation: stay with Firebase. Do not add Supabase.** See
> [§7](#7-why-not-supabase) for the reasoning.

---

## 1. The model in one picture

```
  Browser                    Firebase                     Flask backend
 ──────────                ───────────                  ──────────────────
  email + password   ──▶  signInWithEmailAndPassword
                           │  (only emails created
                           │   in the Firebase console
                           │   can succeed here)
                           ▼
                        ID token  ───────────────────▶  POST /api/auth/firebase
                                                        │
                                                        ├─ 1. verify the signature
                                                        │     against Google's
                                                        │     public keys
                                                        ├─ 2. check the audience
                                                        │     and the issuer
                                                        ├─ 3. check the email is on
                                                        │     the ACCESS LIST and
                                                        │     is active
                                                        └─ 4. issue our own
                                                              HttpOnly session
                                                              cookie
```

**Two independent gates.** Firebase decides whether the *credential* is
valid. The backend's access list decides whether that *identity* may use the
portal. Both must pass.

### Why two gates?

Firebase's **email/password** provider only accepts accounts you created in
the Firebase console, so on its own it already behaves like an allowlist.

Firebase's **Google** provider is the opposite: it will issue a valid token
for *any* Google account on Earth. If you relied on Firebase alone, anyone
with a Google account could reach your portal. The backend's access list is
what closes that door.

| Sign-in method | May an unknown email sign in? | Why |
| --- | --- | --- |
| Email/password (Firebase) | **Yes, the first time** | A successful sign-in proves an administrator created that Firebase account, so the access record is created automatically (see [§4](#4-the-access-list)). |
| Google | **No** | A Google account proves nothing. The email must already be on the access list. |

---

## 2. What to do in the Firebase console

### 2.1 Enable the sign-in providers

**Authentication → Sign-in method → Get started**

| Provider | Action | Notes |
| --- | --- | --- |
| **Email/Password** | Enable | The sign-in method you asked for. |
| **Google** | Enable, then enter your support email and finish the OAuth consent screen | Only for people who already have a Google account on the **same email address**. |

### 2.2 Add the users

**Authentication → Users → Add user**

For each person:

1. Enter the email address.
2. Enter a password (at least 6 characters; 12+ is better).
3. Tick **"Add email verified"** — this makes the account immediately usable
   and removes the "verify your email" step.
4. **Create user**.

Do this for every member of the transport office and the head of the
department.

### 2.3 Restrict the domains

**Authentication → Settings → Authorised domains**

Add only the domains the portal is served from:

```
srmtrpai.web.app
srmtrpai.firebaseapp.com
localhost
```

Anything not on this list is refused by Firebase before the sign-in even
starts. This is a useful second lock on the Google provider.

---

## 3. The backend checks

`POST /api/auth/firebase` performs these checks, in order. Any failure stops
the sign-in.

| # | Check | Failure response |
| --- | --- | --- |
| 1 | The ID token is well-formed and not absurdly long | `400` |
| 2 | The signature matches one of Google's current public keys (RS256) | `401` |
| 3 | `aud` equals your Firebase project id | `401` |
| 4 | `iss` equals `https://securetoken.google.com/<project-id>` | `401` |
| 5 | The token has not expired | `401` |
| 6 | The provider is in `FIREBASE_ALLOWED_PROVIDERS` | `403` |
| 7 | The email is on the access list and active | `403` |
| 8 | The email is not bound to a *different* Firebase UID | `403` |

Only after all eight does the backend mint its own session cookie.

**No service account is needed.** The signing keys are Google's *public*
certificates, fetched from
`https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com`
and cached for five minutes (so Google's key rotation is picked up
automatically). There is therefore **no private key to store, rotate or leak**.

---

## 4. The access list

The access list is the `users` collection in MongoDB. Each record holds:

| Field | Meaning |
| --- | --- |
| `email` | The authorised address (lower-cased). |
| `role` | `head_admin` or `transport_office`. |
| `active` | `false` suspends access without deleting the record. |
| `auth_provider` | The provider last used (`password`, `google.com`, `allowlist`). |
| `firebase_uid` | The Firebase account bound to this email. |
| `last_sign_in_at` | Updated on every successful sign-in. |

### Managing it

```bash
# see who has access
python -m backend.manage_access list

# allow an email (needed before Google sign-in works for it)
python -m backend.manage_access add transport.office@srmtrp.edu.in

# give somebody the administrator role
python -m backend.manage_access set-role principal@srmtrp.edu.in head_admin

# suspend somebody without losing their history
python -m backend.manage_access deactivate transport.office@srmtrp.edu.in
python -m backend.manage_access activate transport.office@srmtrp.edu.in

# let a deleted-and-recreated Firebase account take over an email
python -m backend.manage_access unlink transport.office@srmtrp.edu.in
```

Output looks like this:

```
EMAIL                    ROLE               ACTIVE  PROVIDER       FIREBASE
office@srmtrp.edu.in     transport_office   yes     password       linked
principal@srmtrp.edu.in  head_admin         yes     google.com    linked
```

### Auto-provisioning

`FIREBASE_AUTO_PROVISION` (default `true`) means the first time somebody
signs in with **email/password**, an access record is created for them with
the role in `FIREBASE_DEFAULT_ROLE` (default `transport_office` — least
privilege).

This is safe *because* only someone with access to the Firebase console can
create a Firebase email/password account. If you would rather require an
explicit entry for everybody:

```bash
FIREBASE_AUTO_PROVISION=false
```

…or set the default role higher for a first administrator:

```bash
FIREBASE_DEFAULT_ROLE=head_admin
```

> **Google sign-in never auto-provisions**, whatever this setting says.
> Firebase cannot list Google accounts, so there is no way to know whether a
> Google account was deliberately added. Those emails must be on the list
> already.

---

## 5. The session

After a successful exchange the backend issues its own session:

- **HS256 JWT**, signed with `JWT_SECRET`, valid for `JWT_TTL_MINUTES`
  (default 15 minutes).
- **HttpOnly**, `SameSite=Lax`, `Secure` in production.
- Contains the email and the role, so the role cannot be changed by the
  browser.
- The **Firebase ID token is discarded** — it is never stored, never written
  to `localStorage`, and is not readable by JavaScript.

Signing out clears the cookie and records the event in the audit log.

### The break-glass path

The original MongoDB password login still works and is handy while you are
setting Firebase up:

```bash
LEGACY_PASSWORD_LOGIN_ENABLED=false   # turn it off once Firebase is working
```

When it is disabled, `POST /api/auth/login` returns `403` and the login page
drops the local-account section.

---

## 6. Configuration reference

| Variable | Default | Purpose |
| --- | --- | --- |
| `FIREBASE_PROJECT_ID` | `srmtrpai` | The Firebase project. Required for sign-in. |
| `FIREBASE_APP_ID` | *(supplied)* | Required — without it the configuration is treated as absent. |
| `FIREBASE_API_KEY` | *(secret)* | The web API key. Never commit it. |
| `FIREBASE_AUTH_DOMAIN` | `srmtrpai.firebaseapp.com` | Auth domain. |
| `FIREBASE_STORAGE_BUCKET` | `srmtrpai.firebasestorage.app` | Storage bucket. |
| `FIREBASE_MESSAGING_SENDER_ID` | `734375891811` | Messaging sender id. |
| `FIREBASE_MEASUREMENT_ID` | `G-7MXBNH3N7D` | Analytics measurement id. |
| `FIREBASE_AUTH_ENABLED` | `true` | Master switch for Firebase sign-in. Only effective when a project id is set. |
| `FIREBASE_ALLOWED_PROVIDERS` | `password,google.com` | Which providers are accepted. |
| `FIREBASE_AUTO_PROVISION` | `true` | Auto-create the access record on a first email/password sign-in. |
| `FIREBASE_DEFAULT_ROLE` | `transport_office` | The role given to an auto-provisioned account. |
| `LEGACY_PASSWORD_LOGIN_ENABLED` | `true` | Keep the local MongoDB password login. |

---

## 7. Why not Supabase?

**Recommendation: Firebase. A second provider would add cost and risk without
adding protection.**

| Consideration | Firebase | Supabase |
| --- | --- | --- |
| Already set up | ✅ `srmtrpai` exists; Hosting and Analytics are already integrated | ❌ A second project, a second SDK, a second set of secrets |
| Hosting | ✅ Already configured in `firebase.json` | ❌ Would need a separate deployment |
| Where your data lives | MongoDB | MongoDB — **not** Postgres |
| Row Level Security | n/a | Supabase's headline security feature — but it only protects **Postgres tables**. Your events, drivers and buses live in **MongoDB**, so RLS would not apply to a single row of your actual data. |
| Server-side token verification | ✅ Public JWKS, no service account needed | ✅ Also good, but you would still need the anon/service key configured |
| Provider mix | ✅ Firebase (Google) + optional email/password | ✅ Similar |

The decisive point is the third row. Supabase's main advantage is a policy
language attached to its own database. Since this project's data is in
MongoDB, moving the identity provider to Supabase would buy **no** additional
data protection — you would still enforce the allowlist in application code,
exactly as described above.

If you later want to move the *data* into Postgres (and want RLS), that is a
separate migration decision, and then Supabase becomes worth revisiting. For
identity alone, Firebase is the smaller and safer change.

---

## 8. Verifying the setup

### 8.1 Backend

```bash
curl -s http://localhost:5000/api/auth/config | jq
```

```json
{
  "mode": "firebase",
  "firebase": {
    "enabled": true,
    "providers": ["password", "google.com"],
    "auto_provision": true
  },
  "legacy_password_login": true
}
```

### 8.2 Browser

1. Open the portal. The **"Sign in with Google"** button appears below the
   form.
2. Sign in with a Firebase email/password account that is **not** on the
   access list → you are admitted and a `transport_office` record is created
   automatically.
3. Sign in with a **Google** account that is **not** on the access list →
   you are refused with *"This email address is not authorised for the
   transport portal."*
4. Add that Google email to the access list
   (`python -m backend.manage_access add <email>`) and try again → you are
   admitted.

### 8.3 Audit trail

Every attempt is recorded:

| Action | Meaning |
| --- | --- |
| `login` | An existing account signed in. |
| `login_provisioned` | A new account signed in and was added to the access list. |
| `login_denied` | The identity authenticated but was not authorised. |
| `login_failed` | The token could not be verified. |
| `logout` | The session ended. |

```bash
python -m backend.manage_access list    # who has access
```

---

## 9. Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| "Sign-in with Firebase is not available on this deployment." | `FIREBASE_PROJECT_ID` or `FIREBASE_APP_ID` missing | Set both in `.env` and restart |
| `auth/operation-not-allowed` | The provider is not enabled in the Firebase console | Enable Email/Password or Google under **Sign-in method** |
| `auth/unauthorized-domain` | The domain is not authorised | Add the host to **Authorised domains** |
| "This email address is not authorised" (Google) | Not on the access list | `python -m backend.manage_access add <email>` |
| "This account has been deactivated" | The record exists but `active` is false | `python -m backend.manage_access activate <email>` |
| "This email is already bound to a different Firebase account" | The Firebase user was deleted and re-created | `python -m backend.manage_access unlink <email>` |
| "The authentication service is temporarily unavailable." | Google’s key endpoint could not be reached | Check the server's outbound internet access |
| The Google button does not appear | `google.com` is not in `FIREBASE_ALLOWED_PROVIDERS`, or Firebase is off | Check `/api/auth/config` and the environment |

---

## 10. Files

| Path | Role |
| --- | --- |
| `backend/firebase_auth.py` | ID token verification (RS256 via Google's public JWKS) |
| `backend/access.py` | The access list: resolve, authorise, auto-provision, bind |
| `backend/manage_access.py` | The `python -m backend.manage_access` CLI |
| `backend/app.py` | `POST /api/auth/firebase` and `GET /api/auth/config` |
| `backend/schemas.py` | `FirebaseTokenSchema` |
| `frontend/js/auth.js` | Sign-in flows and the token exchange |
| `frontend/js/login.js` | The login page |
| `frontend/js/firebase.js` | Lazy SDK loading, including the Auth bundle |
| `frontend/vendor/firebase/firebase-auth-compat.js` | The vendored Auth SDK (Apache-2.0) |
| `backend/tests/test_firebase_auth.py` | Access-list and exchange tests |
| `backend/tests/test_firebase_token.py` | Token-verification tests |
