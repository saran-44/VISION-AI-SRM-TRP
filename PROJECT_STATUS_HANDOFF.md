# VISION AI - SRM TRP project handoff

Last updated: 2026-11-14 18:21 IST

This file is intentionally non-secret. Never add passwords, API keys, SSH
tokens, database URLs containing passwords, Firebase private keys, or
certificates here.

## Current architecture

- **Web/API:** Flask application in `backend/`, currently deployed on Render.
- **Database:** Supabase PostgreSQL.
- **Authentication:** Firebase Authentication.
- **Full-vision cloud target:** One InstaBox Linux sandbox running
  `deploy/Dockerfile`.
- **Gate fallback:** `dist/VisionAI-GateAgent/VisionAI-GateAgent.exe` runs the
  camera, OCR, ANPR fallback, vehicle classification, duplicate suppression,
  local logs, and device event upload.
- **Firebase Hosting:** Redirects to the web/API service; it is not the AI
  compute host.
- **InstaBox machine:** Created by the operator; SSH connection and deployment
  are pending after the initial environment check. Verified `x86_64`, Docker
  29.8.2, Docker Compose 5.6.0, and Git 2.47.3.
- **Deployable GitHub branch:** `agent/instabox-vision`, containing deployment
  commit `20e89fb` and latest handoff/template commits `aec11b0`, `87df755`,
  and `acc9deb`. The pull-request page is
  `https://github.com/saran-44/VISION-AI-SRM-TRP/pull/new/agent/instabox-vision`.

## Completed in this session

- Added structured response for Render Free vision failure:
  `vision_local_agent_required`.
- Added automatic browser-camera scanning with operator start/stop control.
- Removed unconfigured demo camera tiles from the camera wall.
- Added responsive CCTV-style camera layouts based on connected camera count.
- Gate agent now ignores non-buses and accepts numbers only from sticker or ANPR
  stages.
- Gate agent default scan interval is one second.
- Added local agent activity log under `%APPDATA%\VisionAI\GateAgent\agent.log`.
- Built the Windows executable successfully.
- Prepared InstaBox full-vision Docker Compose deployment.
- Full Docker image now includes `best.pt`, `anpr_best.pt`, and downloads the
  vehicle model during build.
- Added `docs/DEPLOY_INSTABOX.md`.
- Focused backend and frontend validation passed; Docker Compose validation is
  deferred because Docker is not installed on this Windows workstation.

## Release files

- `desktop/detector_agent.py`
- `requirements-desktop.txt`
- `desktop/build_windows.ps1`
- `dist/VisionAI-GateAgent/VisionAI-GateAgent.exe`
- `deploy/Dockerfile`
- `deploy/instabox/docker-compose.yml`
- `deploy/instabox/.env.instabox.example`
- `docs/DEPLOY_INSTABOX.md`

## InstaBox creation form

The attached guide says a standard Linux sandbox provides approximately 4 vCPU,
8 GiB RAM, and 20 GiB SSD. One sandbox is enough; the 10-node cluster is not
needed.

To satisfy the machine-creation form, add this harmless bootstrap variable:

```text
Name: ENVIRONMENT
Value: production
```

The application secrets are configured later on the machine, not pasted into
this handoff file.

## Application configuration names

### Non-secret environment variables

```text
ENVIRONMENT=production
PORT=8080
COOKIE_SECURE=true
TRUST_PROXY_HEADERS=false
APP_TIMEZONE=Asia/Kolkata
JWT_TTL_MINUTES=15
RATELIMIT_ENABLED=true
RATELIMIT_STORAGE_URI=memory://
OCR_CONFIDENCE_THRESHOLD=0.75
OVERSTAY_HOURS=12
FIREBASE_PROJECT_ID=vision-ai-srmtrp
FIREBASE_AUTH_DOMAIN=vision-ai-srmtrp.firebaseapp.com
FIREBASE_STORAGE_BUCKET=vision-ai-srmtrp.firebasestorage.app
FIREBASE_MESSAGING_SENDER_ID=235811571442
FIREBASE_APP_ID=1:235811571442:web:342e488e0ac2ee75b0f26b
FIREBASE_MEASUREMENT_ID=G-S4HS9TGV4H
FIREBASE_ALLOWED_PROVIDERS=password,google.com
FIREBASE_AUTO_PROVISION=false
FIREBASE_DEFAULT_ROLE=transport_office
LEGACY_PASSWORD_LOGIN_ENABLED=false
```

### Secret values required during deployment

```text
DATABASE_URL
JWT_SECRET
DEVICE_API_KEYS
FIREBASE_API_KEY
PGSSLROOTCERT
```

`PGSSLROOTCERT` must point to the mounted Supabase CA certificate inside the
container. The real `.env.instabox` and `supabase-ca.crt` must stay private.

## InstaBox deployment sequence

1. Create one standard Linux sandbox.
2. Check architecture with `uname -m`; prefer `x86_64` for the pinned PyTorch
   wheels.
3. Connect using the InstaBox SSH token. Never share the token in chat.
4. Clone the repository.
5. Copy `deploy/instabox/.env.instabox.example` to
   `deploy/instabox/.env.instabox`.
6. Add the real Supabase CA certificate at
   `deploy/instabox/supabase-ca.crt`.
7. Fill the private environment values.
8. Run the Docker Compose build and start commands in
   `docs/DEPLOY_INSTABOX.md`.
9. Verify `/api/health` and `/api/detection/status`.
10. Configure HTTPS before login. `COOKIE_SECURE=true` requires HTTPS.
11. Add the new HTTPS hostname to Firebase Authorized Domains and
    `CORS_ALLOWED_ORIGINS`.

## Known limitations and pending work

- InstaBox free sandboxes have an 8-hour runtime cap and cooldown. Do not use
  keepalive scripts to bypass it. Use the Windows agent for continuous gate
  operation or upgrade the server plan.
- Remote web control of the Windows agent is not implemented yet. Current
  controls are available locally in the agent window and system tray.
- A reverse proxy/HTTPS hostname must be configured on InstaBox before
  production login.
- The final cloud deployment has not been run because the InstaBox machine has
  not been created yet.
- Model licensing and dataset rights must be reviewed before corporate
  distribution.

## Continuation instruction

Before making future changes, read this file, inspect the current worktree, and
update this file at the end of the task with the new status, validation result,
and remaining blockers. Keep all secrets outside this file.
