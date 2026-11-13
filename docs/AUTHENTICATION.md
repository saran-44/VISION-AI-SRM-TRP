# Authentication — Firebase sign-in with a restricted access list

This document explains how the SRM TRP Transport console authenticates, how
access is restricted to specific email addresses, and exactly what to click in
the Firebase console.

> Firebase Authentication verifies identities; Supabase PostgreSQL stores the
> server-side access list and application data. The private database schema is
> not exposed through Supabase's Data API. Follow [DEPLOY_WINDOWS.md](DEPLOY_WINDOWS.md)
> for onboarding and deployment. No live cloud integration has been verified.

---

## 1. The model in one picture

```
  Browser                    Firebase                     Flask backend
 ──────────                ───────────                  ──────────────────
  email + password   ──▶  signInWithEmailAndPassword
                           │
                           ▼
                        ID token  ───────────────────▶  POST /api/auth/firebase
                                                        │
                                                        ├─ 1. verify signature,
                                                        │     audience and issuer
                                                        ├─ 2. require a verified email
                                                        ├─ 3. require an active access
                                                        │     entry or, for password
                                                        │     users only, an approval
                                                        │     claim for provisioning
                                                        └─ 4. issue our own
                                                              HttpOnly session
                                                              cookie
```

**Two independent gates.** Firebase decides whether the *credential* is
valid. The backend's access list decides whether that *identity* may use the
portal. Both must pass.

### Why two gates?

Firebase's **email/password** provider can allow users to create their own
accounts via the Firebase SDK or REST API, even if this portal has no sign-up
page. Firebase's **Google** provider also permits sign-in by arbitrary Google
accounts. Neither provider alone proves that an administrator approved access.

Both providers must supply a **verified email**. The PostgreSQL access list then
controls authorization:

| Sign-in method | May an unknown email sign in? | Rule |
| --- | --- | --- |
| Email/password (Firebase) | Only if explicitly approved | With auto-provisioning enabled, the token must contain an admin-set `transport_portal_approved_email` claim matching its verified email. Otherwise the email must already be on the access list. |
| Google | **No** | The verified email must already be on the access list, even if the token carries the approval claim. |

> **Migrating an existing deployment:** Earlier versions accepted unapproved
> password sign-ups and did not require a verified email. Before reopening an
> affected deployment, review the Firebase users, old and current access entries, UID
> bindings and audit logs; deactivate unauthorized records. Rotate the app's
> `JWT_SECRET` to invalidate sessions issued before the fix. Do not assume
> that deploying the fix removes access records already created by the old
> code. No such review or deployment happens automatically.

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

For each password user, create their account and arrange for them to verify
ownership of their email through Firebase's email-verification flow. A trusted
administrator may instead mark it verified using the
[Firebase Admin SDK](https://firebase.google.com/docs/auth/admin/manage-users#update_a_user)
**only after independently confirming both mailbox ownership and control of
that specific Firebase account**; an attacker may have registered the email
first. Do not assume there is a verification checkbox in the console. An
unverified address cannot sign in to the portal, even if it appears on the
access list. The portal has no built-in verification or reset button;
[DEPLOY_WINDOWS.md](DEPLOY_WINDOWS.md)
explains how to send and check a verification email privately with
`scripts/send_firebase_verification.py`.

For an existing email, independently verify mailbox ownership and control of
the specific Firebase account/UID before recovery or granting `head_admin`.
Do not reuse any password previously shared in chat.

Add every authorized user to PostgreSQL with `backend.manage_access`, or use the
optional admin approval claim described in [§4](#4-the-access-list) for
password accounts. Google users always need an access-list entry.

### 2.3 Restrict the domains

**Authentication → Settings → Authorised domains**

Add only the domains the portal is actually served from. For the expected
`vision-ai-srmtrp` default site these may include `vision-ai-srmtrp.web.app` and
`vision-ai-srmtrp.firebaseapp.com`; verify the real site first. Add `localhost` only
when required for local development.

These domains control the Firebase web OAuth/redirect flow; they are **not**
an access list and do not prevent password sign-up through the Firebase API.
Keep the backend authorization checks enabled.

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
| 7 | The token contains a verified email | `403` |
| 8 | The email has an active access-list entry, or is an approved password account eligible for auto-provisioning | `403` |
| 9 | The email is not bound to a *different* Firebase UID | `403` |

Only after these checks does the backend mint its own session cookie.

**No service account is needed for token verification.** Google's *public*
JSON Web Key Set is fetched from the endpoint advertised by Firebase's OpenID
configuration:
`https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com`.
Keys are cached for five minutes and refreshed if a token's key ID is missing.
There is therefore **no private key to store, rotate or leak** for verification.

---

## 4. The access list

The access list is the `transport_portal.users` PostgreSQL table. Each record holds:

| Field | Meaning |
| --- | --- |
| `email` | The authorised address (lower-cased). |
| `role` | `head_admin` or `transport_office`. |
| `active` | `false` suspends access without deleting the record. |
| `auth_provider` | The provider last used (`password`, `google.com`, `allowlist`). |
| `firebase_uid` | The Firebase account bound to this email. |
| `last_sign_in_at` | Updated on every successful sign-in. |

### Managing it

The CLI reads `DATABASE_URL` and **loads `.env` automatically**. Use the
same private PostgreSQL URL and CA as the application:

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

# after verifying the replacement account and UID, allow it to bind
python -m backend.manage_access unlink transport.office@srmtrp.edu.in
```

> **Existing entries:** `add` changes the role and reactivates an existing
> record by default; `set-role` also reactivates it. Review the Firebase UID,
> account ownership and authorization before either operation or `unlink`.
> Unlinking allows a different verified Firebase identity with that email to
> bind; it must not be used to bypass an unexplained UID mismatch.

> **Which database it touches.** `DATABASE_URL` selects the database; the
> access list is in its private `transport_portal.users` table. Ensure the
> URL points to the intended Supabase project before granting a role.
>
> **Connection troubleshooting.** Errors are deliberately sanitized. A
> connection failure does not prove the credentials are invalid. Check the
> exact session-pooler host, qualified role/project username, TLS CA,
> network restrictions, schema migration, URL encoding and role grants.

Output looks like this:

```
EMAIL                    ROLE               ACTIVE  PROVIDER       FIREBASE
office@srmtrp.edu.in     transport_office   yes     password       linked
principal@srmtrp.edu.in  head_admin         yes     google.com    linked
```

### Auto-provisioning

`FIREBASE_AUTO_PROVISION` (default `true`) permits an unknown **password**
identity to receive an access record only when its Firebase ID token has
`email_verified: true` and an administrator-set `transport_portal_approved_email`
custom claim matching that verified address. Its new role is
`FIREBASE_DEFAULT_ROLE` (default `transport_office`). A password account
created in Firebase is not, by itself, proof of administrator approval.
Google users never auto-provision, and changing an email requires fresh approval.

The simplest approach is to add each verified user's email to PostgreSQL with the
access-list CLI; no custom claim is required for an existing active entry.
To require an explicit entry for everyone, set:

```bash
FIREBASE_AUTO_PROVISION=false
```

#### Optional: approve a password user for auto-provisioning

A trusted Firebase administrator can set the claim with the Firebase Admin
SDK. First independently confirm that the account belongs to the person and
its email is verified. **Do not grant this claim automatically on sign-up.**
Sign in with an account authorized to manage Firebase Authentication, then
use your existing Python virtual environment on your own machine:

```bash
python -m pip install firebase-admin==7.7.0
gcloud auth application-default login
read -r -p "Verified Firebase account email to approve: " APPROVED_EMAIL
export APPROVED_EMAIL
python - <<'PY'
import os
import firebase_admin
from firebase_admin import auth

firebase_admin.initialize_app(options={"projectId": "vision-ai-srmtrp"})
user = auth.get_user_by_email(os.environ["APPROVED_EMAIL"].strip())
if not user.email_verified or user.disabled:
    raise SystemExit("Account must be verified and enabled before approval.")
claims = dict(user.custom_claims or {})
claims["transport_portal_approved_email"] = user.email.strip().lower()
auth.set_custom_user_claims(user.uid, claims)
print("Approval saved. The user must sign in again to get a fresh token.")
PY
unset APPROVED_EMAIL
```

Custom-claim updates replace the entire claim object; the example preserves
other claims, but concurrent updates can still race. Removing this claim later
**does not** deactivate an access-list record already created. To revoke
portal access, deactivate the PostgreSQL entry and manage the Firebase account as
well. Keep the default role at `transport_office`; assign `head_admin`
explicitly only to trusted administrators.

---

## 5. The session

After a successful exchange the backend issues its own session:

- **HS256 JWT**, signed with `JWT_SECRET`, valid for `JWT_TTL_MINUTES`
  (default 15 minutes).
- Named `__session`, **HttpOnly**, `SameSite=Lax`, `Secure` in production.
  Firebase Hosting forwards this reserved name to Cloud Run.
- Contains the email and the role, so the role cannot be changed by the
  browser.
- The browser obtains a Firebase ID token and sends it for exchange. The
  backend does not persist that token; the Firebase SDK manages its own
  browser authentication state until sign-out.

Signing out clears the cookie and records the event in the audit log.

### The break-glass path

The legacy local password login can be enabled for controlled local
setups, but the checked-in Cloud Build deployment explicitly sets
`LEGACY_PASSWORD_LOGIN_ENABLED=false`. When disabled, `POST /api/auth/login`
returns `403` and the login page drops the local-account section. Do not
enable a production break-glass path without a reviewed security plan.

---

## 6. Configuration reference

| Variable | Default | Purpose |
| --- | --- | --- |
| `FIREBASE_PROJECT_ID` | empty | Firebase project ID; `vision-ai-srmtrp` in the checked-in build. |
| `FIREBASE_APP_ID` | empty | Web app ID; configuration is absent without it. |
| `FIREBASE_API_KEY` | empty | Public Firebase web API key, configured from the environment and sent to the browser. |
| `FIREBASE_AUTH_DOMAIN` | empty | Auth domain; confirm the actual value in Firebase. |
| `FIREBASE_STORAGE_BUCKET` | empty | Firebase storage bucket, if applicable. |
| `FIREBASE_MESSAGING_SENDER_ID` | empty | Messaging sender ID. |
| `FIREBASE_MEASUREMENT_ID` | empty | Analytics measurement ID, if enabled. |
| `FIREBASE_AUTH_ENABLED` | `true` | Master switch for Firebase sign-in. Only effective when a project id is set. |
| `FIREBASE_ALLOWED_PROVIDERS` | `password,google.com` | Which providers are accepted. |
| `FIREBASE_AUTO_PROVISION` | `true` | Auto-create an access record only for a verified password account with the admin-set approval claim. |
| `FIREBASE_DEFAULT_ROLE` | `transport_office` | The role given to an auto-provisioned account. |
| `LEGACY_PASSWORD_LOGIN_ENABLED` | `true` | Keep the local database password login. |

---

## 7. Supabase PostgreSQL and Firebase

The Flask backend connects directly to Supabase PostgreSQL using a dedicated
server-side database role and verified TLS. It verifies Firebase tokens itself
and enforces the access list and roles before serving application data. No
Supabase Auth or browser-side service-role key is required. Do not expose the
private `transport_portal` schema via PostgREST; RLS is not the enforcement
mechanism in this design. Switching Firebase projects requires verifying users
again and reviewing UID bindings; no old identities or records are copied.

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

This example shows the application defaults; the checked-in Cloud Build
production settings instead set `auto_provision` and `legacy_password_login`
to `false`. Refer to the Windows runbook for live, hosted checks.

### 8.2 Browser

1. Open the portal. The **"Sign in with Google"** button appears below the
   form.
2. Sign in with a verified Firebase password account that is **not** on the
   access list and has no approval claim → access is denied. With the
   admin-set approval claim and auto-provisioning enabled, the account is
   admitted and receives the configured default role.
3. Sign in with a **Google** account that is **not** on the access list →
   access is denied, even if an approval claim exists.
4. Add that verified Google email to the access list
   (`python -m backend.manage_access add <email>`) and try again → access is
   granted. An unverified account is denied even when its email is listed.

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
| "This email address is not authorised" | No active access entry or approved password auto-provisioning | Add the verified email to the access list, or follow the approval-claim steps above. |
| "Verify your email address before signing in" | Firebase did not assert `email_verified: true` | Complete email verification; then sign in again for a fresh token. |
| "This account has been deactivated" | The record exists but `active` is false | `python -m backend.manage_access activate <email>` |
| "This email is already bound to a different Firebase account" | The Firebase UID differs from the bound identity | Investigate and independently verify account ownership and the replacement UID before using `unlink`. |
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
