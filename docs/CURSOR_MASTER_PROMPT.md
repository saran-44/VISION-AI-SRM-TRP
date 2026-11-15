# MASTER PROMPT — finish VISION AI - SRM TRP

**Written for:** Cursor (works verbatim in Anti Gravity, or any agentic coding
tool that can run commands in the repo).
**Date:** 2026-11-15
**Repository:** `saran-44/VISION-AI-SRM-TRP`, branch `main` at commit
`cedf06d6f04c09bdfa0cf9e9ae946e453fce8f8d` (this clone has a single squashed
commit — do not look for older SHAs in `git log`; the history is on GitHub).

---

## 1. How to use this file (for you, the human)

1. Open a **new chat** in Cursor and open the repository folder.
2. If the folder is not cloned yet, run the clone commands in §2 first.
3. Paste **everything inside the block in §3** into the chat as one message.
4. The prompt is self-contained: it tells the agent to verify the tree, read the
   key documents, and report back before changing anything.
5. Do **not** paste `.env`, Supabase passwords, Firebase keys, device keys or
   camera URLs into the chat. The agent only ever needs the *name* of a variable.

**What is new in this version** (compared with the older
`ANTIGRAVITY_MASTER_PROMPT.md` / `ANTIGRAVITY_PROMPT.md` / `MASTER_PROMPT.md`):

- The issue register is **re-verified against the current tree**. Several items
  the old audit called blockers are already fixed (DET-2, ENT-1, ENT-2, DET-5,
  ENT-6/NEW-1, BE-1/BE-2/BE-6, DET-7). The old prompts tell the agent to
  re-implement them — that is now wrong and wastes the run.
- The test count is the **real current count** (347 passed / 24 skipped without
  the vision extras), not the audit's 328/23.
- A new **Phase 5: detector decision — local `.pt` first, Roboflow fallback**,
  which is the owner's explicit instruction.
- The `.exe` pipeline (build script, PyInstaller spec, Inno Setup script,
  Windows CI job) is described as it actually exists, and the work is to **run
  and prove it**, not to write it from scratch.
- Cloud (Render) work is a verification-and-harden phase, with the "no torch on
  Render" rule stated up front.

---

## 2. Clone / open the repository (new chat)

```bash
cd ~/VISION-AI-SRM-TRP        # or: git clone https://github.com/saran-44/VISION-AI-SRM-TRP.git
git fetch origin
git switch main && git pull --ff-only
git log --oneline -3
git status --short            # must be clean, or only files you meant to change
ls docs/                      # the real directory listing
```

Environment used for the numbers in this file: **Python 3.11.2, Node 22.22.3**.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt          # core app; no torch
# optional, only if you want to run the detector locally:
pip install -r backend/requirements-vision.txt \
  --index-url https://download.pytorch.org/whl/cpu \
  --extra-index-url https://pypi.org/simple
pip install --no-deps ultralytics==8.4.20
```

---

## 3. THE MASTER PROMPT — copy everything inside this block

```text
You are the lead engineer finishing a real, already-deployed product. You are
working in the Git repository VISION-AI-SRM-TRP. You may edit code, run
commands, run tests, open pull requests and ask me questions. You may NOT merge,
you may NOT push to main, and you may NOT invent results. If a check cannot be
run in this environment, you report it as NOT RUN with the reason — never as
passed.

=====================================================================
0. FIRST ACTIONS — prove you are looking at the right tree, then read
=====================================================================
Run and record the real output:

    pwd && git rev-parse --short HEAD && git status --short
    git log --oneline -3
    ls docs/
    python --version && node --version
    python -m pytest backend/tests -q
    for f in frontend/js/*.js; do node --check "$f"; done
    node scripts/check_frontend.mjs
    node scripts/check_auth_flow.mjs
    node scripts/check_firebase_loader.mjs
    node scripts/check_live_stream.mjs
    python scripts/scan_secrets.py

Then read, do not skim: README.md, docs/ARCHITECTURE.md, docs/DETECTION.md,
docs/EVENT_CONTRACT.md, docs/GATE_READY_AUDIT.md, docs/DEPLOY_GATE_PC.md,
docs/DEPLOY_RENDER_FREE.md, docs/DEPLOY_RENDER_HOBBY.md, ANALYSIS_REPORT.md
(§3 findings, §4 findings, §5 detection, §7 packaging, §8 roadmap),
backend/app.py, backend/services.py, backend/config.py, backend/vision.py,
backend/schemas.py, backend/preflight.py, desktop/gate/launcher.py,
desktop/gate/build_gate.ps1, desktop/gate/VisionAI.spec, render.yaml,
deploy/render/entrypoint.sh.

Reply with: the SHA you are on, the pytest summary line, the five check
results, and anything in this prompt that does not match the tree. Do not
change code in this step.

=====================================================================
1. THE PRODUCT
=====================================================================
VISION AI - SRM TRP is a gate-pass portal for SRM TRP Engineering College. A bus
arrives at the gate; a camera sees the bus-number sticker; the detector reads
the number; an event (bus, direction, gate, timestamp, confidence) is stored and
shown on a live dashboard. The transport office manages drivers, buses and
access lists; head admins see audit trails and exports.

One Flask application serves both the JSON API and the static frontend. Data is
SQL in a private Supabase PostgreSQL schema (transport_portal). Sign-in is a JWT
in an HttpOnly cookie, exchanged from a Firebase ID token. There are 47 routes.

=====================================================================
2. ARCHITECTURE AND THE THREE DEPLOYMENTS (they are NOT the same thing)
=====================================================================
(a) THE PORTAL — Render, one Docker container, free/hobby plan: 512 MB RAM,
    ephemeral disk, sleeps when idle, one instance. Serves the UI and the API.
    It CANNOT run the detector: no torch, no OCR, and no network route to a
    camera on the college LAN. /api/detection/scan therefore answers 503 with
    code "vision_local_agent_required". That is CORRECT behaviour. Do not "fix"
    it by installing torch, ultralytics, rapidocr, onnxruntime or opencv in
    deploy/render/Dockerfile. The slim image is deliberate.

(b) THE GATE PC — a Windows machine at the gate running VisionAI.exe
    (desktop/gate/: launcher.py, PyInstaller spec, Inno Setup script,
    build_gate.ps1). It owns the camera, runs the detection cascade, and posts
    identified events to the portal with an X-Device-Key header. It must keep
    working with no internet: record locally in SQLite, upload later. Its own
    database is the system of record today; cloud sync (stage 2) is NOT built.

(c) INSTABOX — an older LAN host (deploy/instabox/docker-compose.yml). It is
    being retired. Never run it as a second portal against the same database.

DETECTION CASCADE (backend/vision.py):
  best.pt        YOLOv10n, 2 classes (0 "red circle", 1 "sticker"), 5.5 MB.
                 Only class 1 is cropped and OCR'd.
  anpr_best.pt   YOLOv10n number-plate model, one class, upscaled 3x before OCR.
  weights/vehicle.pt  optional COCO vehicle model (not committed; fetched at
                 build time by scripts/fetch_vehicle_model.py).
  OCR: RapidOCR (ONNX, default) -> Tesseract -> EasyOCR fallback.
  normalize_plate() turns raw OCR text into a bus number; it returns "" when the
  text has no digit or is outside 2-20 chars.
  Every scan returns: candidates[], bus_number, confidence, raw_text, reason
  (no_detection | other_class | below_threshold | unreadable | ok), advice,
  detection{boxes_total, boxes_above_threshold, boxes_other_class,
  boxes_total_by_stage, best_confidence, threshold, image_size, sticker_class,
  inference_ms, model, frame_sharpness, frame_brightness}, frame{}, stage,
  vehicle, stages[].

=====================================================================
3. WHAT IS ALREADY BUILT — DO NOT REDO
=====================================================================
Built by Arena AI (committed, verified in CI):
- Flask backend: 47 routes, application factory, JWT HttpOnly+SameSite=Lax
  cookie, role decorators (head_admin, transport_office), Firebase ID-token
  exchange verified against Google public keys, per-route login rate limits,
  audit row on every mutation, pydantic strict validation, security headers,
  CSV/XLSX export with formula-injection guarding.
- Data: SQL over Supabase PostgreSQL in the private transport_portal schema
  (backend/sql/001_initial.sql), SQLAlchemy layer (backend/db.py), pooling
  tuned for the Supabase pooler. The app never auto-migrates Postgres.
- Events: ingest / list / filter / paginate / CSV / XLSX, flag rules
  (unregistered_plate, low_ocr_confidence, long_overstay), "who is inside"
  derivation, IN/OUT pairing, duplicate suppression.
- Detection: the cascade above, tiling, frame-quality guards, crop extraction,
  OCR fallbacks, diagnostics blocks in <data>/logs/.
- Gate agent: VisionAI.exe — waitress server, tray icon, --setup wizard,
  --check preflight, --report, --backup, --no-browser/--no-tray, X-Device-Key
  upload, offline-tolerant.
- Tests: 26 test files. CI: backend (SQLite + a disposable PostgreSQL service),
  vision stack (optional), frontend checks, secret scan, and a windows-gate
  build job (added, marked untested).
- Docs: 30+ documents in docs/.

Built/tuned in VS Code (local; the results are committed, the experiments are
not): inference at VISION_IMAGE_SIZE 960, probe floor 0.05, only class 1
("sticker") OCR'd, OCR gate 0.25; a training recipe for a custom number-plate
model (docs/TRAINING.md); webcam capture and the Test Lab; the gate-laptop
scans that produced the real evidence (crops 25-44 px, 2.8 s latency,
brightness 0.0 at startup); the 7.7 GB venv / libGL.so.1 failure and a
PyInstaller attempt that did not produce a usable bundle.

What NEITHER produced (this is the gap you are closing): a built dist/, a
signed installer, a green Windows CI run, real-photograph fixtures, and an
outside-in verification of the live Render URL.

=====================================================================
4. VERIFIED WORKING RIGHT NOW (re-run these; quote the output)
=====================================================================
- python -m pytest backend/tests -q  ->  347 passed, 24 skipped (vision extras
  NOT installed). With the vision extras the OCR-dependent tests also run.
  A skipped test is NOT a passing test: list which skipped and why.
- node scripts/check_frontend.mjs        -> 22 modules, 10 pages, all references
  resolve.
- node scripts/check_auth_flow.mjs      -> pass.
- node scripts/check_firebase_loader.mjs-> pass.
- node scripts/check_live_stream.mjs    -> pass.
- python scripts/scan_secrets.py         -> pass, no credential patterns.
- Gate readiness: docs/GATE_READY_AUDIT.md records the portal, file database,
  HTTP-snapshot camera path, preflight, setup and backup as verified on a
  Linux box; the PyInstaller bundle, installer, tray and detector inference
  were NOT executed there.

Already fixed on main — verify, do not redo:
- DET-2: normalize_plate("hello world") == "" (backend/vision.py:782) and
  EventCreate rejects a bus_number with no digit (backend/schemas.py:180).
- ENT-1: VISION_EVENT_DEBOUNCE_SECONDS (default 60) + duplicate merge
  (backend/config.py:185, backend/services.py:146-159, audit row
  "event_deduplicated").
- ENT-2: flag reason "out_without_in" (backend/services.py:128).
- ENT-4 / BE-1 / BE-2 / BE-6: bounded SSE with heartbeats and a shared stats
  cache; sse.js reconnects with backoff; compute_stats is bounded by
  STATS_LOOKBACK_DAYS (45).
- DET-5: scripts/inspect_model.py prints the real import exception.
- DET-7: detection.boxes_total_by_stage exists (backend/vision.py:271).
- ENT-6 / NEW-1: a naive timestamp is rejected with "timestamp must include a
  timezone offset, e.g. +05:30" (backend/schemas.py:192).
- BE-5 (partial): backend/requirements-vision.txt pins torch==2.9.1+cpu and
  opencv-python-headless; build_gate.ps1 installs CPU torch first.
- CI: a windows-gate job exists but is marked untested.

=====================================================================
5. GROUND RULES
=====================================================================
 1. Never commit, print or paste a secret: DATABASE_URL, JWT_SECRET,
    DEVICE_API_KEYS, FIREBASE_API_KEY, ROBOFLOW_API_KEY, camera URLs with
    credentials, certificates, .env files. Refer to values by variable name
    only. If you print one by accident, treat it as burned and say so.
 2. Do not add torch, ultralytics, rapidocr, onnxruntime or opencv to
    deploy/render/Dockerfile. The slim image is deliberate.
 3. Do not weaken security to make something pass: no COOKIE_SECURE=false, no
    debug mode, no DEMO_MODE in production, no wildcard CORS, no disabled rate
    limits, no skipped secret scan, no skipped test.
 4. Every behaviour change needs a test that fails before and passes after.
    Do not delete or skip an existing test to get green.
 5. Small commits, one concern each, conventional messages (fix:, feat:, test:,
    docs:, build:). One pull request per numbered item. Never rewrite history,
    never force-push, never merge.
 6. Keep the gate PC fully working offline while you change the portal.
 7. If you cannot verify something (no browser, no Windows, no real camera, no
    network), say so explicitly and produce a script or CI job that will verify
    it on the machine that can — do not declare it done.
 8. Do not refactor for taste. This is a product with one operator and a gate
    that opens at 8 a.m.; a change must reduce a real risk.
 9. Numbers in your report must come from output you actually ran. Quote the
    command and the output. If you extrapolate, label it ESTIMATE.
10. Preserve the audit's vocabulary: keep the IDs (DET-1, ENT-1, BE-3, PKG-1,
    ...) in commit messages and in your final report so every item traces back
    to ANALYSIS_REPORT.md.
11. The API contract is additive: new JSON fields are fine; renaming or
    removing an existing field or status code is not.

=====================================================================
6. ISSUE REGISTER — current status (re-verify each before you touch it)
=====================================================================
| ID     | Sev     | Issue                                                        | Status now |
|--------|---------|--------------------------------------------------------------|------------|
| DET-1  | Blocker | No real-image regression set; accuracy unverifiable          | OPEN       |
| DET-2  | Blocker | Garble OCR text became a bus number                          | FIXED (verify + regression test) |
| DET-3  | High    | VISION_IMAGE_SIZE mismatch: backend default 960, gate config 1280 | PARTIAL (desktop/gate/launcher.py:60,359 and gate.env.example:37 still say 1280) |
| DET-4  | High    | Sticker crop below OCR-readable size on the webcam path      | Code fixed (OCR_READABLE_CROP_PX=120); depends on real optics |
| DET-5  | Medium  | inspect_model.py misdiagnosed a broken install               | FIXED      |
| DET-6  | Medium  | Black frame and dark room give the same "too dark" advice   | OPEN (backend/vision.py:951) |
| DET-7  | Low     | boxes_total counted the sticker stage only                   | FIXED (verify) |
| ENT-1  | Blocker | No duplicate suppression                                     | FIXED (verify + tests) |
| ENT-2  | Medium  | OUT without a matching IN accepted and unflagged             | FIXED      |
| ENT-3  | Medium  | Stand-alone gate never checks its clock                      | PARTIAL (preflight skips when no API_URL; no w32tm check) |
| ENT-4  | Medium  | compute_stats read every event ever                          | FIXED      |
| ENT-5  | Low     | CSV flag_reasons contained a Python repr                     | FIXED      |
| ENT-6  | Low     | Naive timestamps rejected with a generic message             | FIXED      |
| BE-1   | Blocker | SSE pinned a worker thread forever                           | FIXED      |
| BE-2   | High    | Full-table aggregation per SSE tick                          | FIXED      |
| BE-3   | Medium  | MJPEG proxy holds a thread per viewer, no cap, no disconnect | OPEN (backend/app.py:620-657) |
| BE-4   | Medium  | Two OpenCV distributions installed at once                    | PARTIAL (headless pinned; verify on Windows) |
| BE-5   | Medium  | CUDA torch was the default install outcome                   | PARTIAL (+cpu pinned; bundle unmeasured) |
| BE-6   | Low     | SSE client never returned to SSE after one failure           | FIXED      |
| BE-7   | Low     | Oversized uploads downscaled silently                        | PARTIAL (frame.downscaled is hard-coded False at backend/app.py:851) |
| SEC-1  | High    | A credential remains in git history                          | OPEN (rotate; this clone has one commit, so inspect GitHub history) |
| UI-1   | Medium  | Modals not keyboard-accessible                               | PARTIAL (role/aria-modal/Escape/focus trap in tables.js; the search modal has no focus trap) |
| UI-2   | Medium  | Inputs remove the focus ring with no replacement             | LIKELY FIXED (no outline:none remains; verify) |
| UI-3   | Low     | Clickable rows unreachable by keyboard                       | OPEN (tabindex count ~1) |
| UI-4   | Low     | Wide tables scroll inside a 680 px box on phones             | Accepted; optional |
| UI-5   | Low     | Chart height !important-pinned to 240 px                     | Accepted; optional |
| NEW-1  | Low     | Naive timestamp silently read as UTC                         | FIXED      |
| NEW-2  | Low     | .dockerignore excludes **/*.json with no exceptions          | OPEN       |
| PKG-1  | Blocker | The .exe pipeline has never run end to end                   | PARTIAL (windows-gate CI job added, untested) |
| PKG-2  | Blocker | 7.7 GB dependency footprint                                  | PARTIAL (CPU pins; bundle never measured) |
| PKG-3  | High    | Build correctness depends on install order                   | PARTIAL    |
| PKG-4  | High    | AGPL-3.0 obligations for a distributed binary                | OPEN (owner decision) |
| GATE-1 | High    | Cloud sync (gate -> Supabase) is not built                   | OPEN (scope decision, not a bug) |

=====================================================================
7. WORK PACKET — one pull request per numbered item
=====================================================================
Nothing else matters until Phase 1 is closed. Phase 5 decides the detector;
Phase 6 builds the .exe. Phase 2 does not depend on Phase 1's code.

---------------------------------------------------------------------
PHASE 0 — GROUND TRUTH (no code changes; report findings)
---------------------------------------------------------------------
Run the commands in §0 and answer, two lines each: what runs, what fails, what
you cannot run here. Do not proceed until the suite is green or you have
reported exactly which tests fail and why.

---------------------------------------------------------------------
PHASE 1 — BLOCKERS
---------------------------------------------------------------------
1.1  DET-1 — a real-image regression set.
     Create backend/tests/fixtures/detection/ with 10-20 REAL frames: sticker
     close, mid, far, night, glare, two buses in frame, no bus. .gitignore
     ignores *.jpg/*.png, so add explicit ! exceptions for this directory only,
     and document in docs/DETECTION.md that these images are of vehicles, not
     people. Add a pytest module that runs the cascade over each fixture and
     asserts a per-frame expectation recorded in a small JSON manifest (bus
     number or "no_detection" + a confidence floor), plus a CI job that runs it
     only when backend/vision.py, best.pt, anpr_best.pt or the fixtures change.
     If you cannot obtain real images, implement the harness and ship the
     manifest format, and mark the fixtures MISSING. Do NOT synthesise them and
     call the accuracy verified.
     Accept: pytest -k fixtures runs the harness; a deliberately wrong manifest
     entry makes it fail.

1.2  DET-3 — the image size the gate actually ships.
     desktop/gate/launcher.py hard-codes VISION_IMAGE_SIZE=1280 (two places)
     while .env.example says 960 and the only sample that detected did so at
     960. Measure on the 1.1 fixtures: for each size in {640, 960, 1280, 1536},
     record detection rate and median latency. Choose from that data, set it in
     ONE place that the launcher, docs and .env.example all read or quote, and
     record the decision and its numbers in docs/DETECTION.md.
     Accept: a test asserts the launcher's value equals the documented value.

1.3  DET-2 — verify the fix, then lock it with tests.
     Confirm normalize_plate("hello world") == "" and that POST /api/events
     with "HELLO WORLD" returns 422 naming bus_number, while "KL01AB1234"
     still normalises and stores. Audit every caller (scan route, gate agent,
     scripts/scan_image.py, scripts/frame_report.py): an unreadable read must
     return 200 with bus_number null and create no event.
     Accept: the three assertions above, as tests.

1.4  ENT-1 — verify duplicate suppression on SQLite AND PostgreSQL.
     Three identical POSTs in 3 s -> 201, 200 duplicate, 200 duplicate, and
     exactly one row; a POST 61 s later inserts; IN then OUT 1 s later inserts
     both. Run the suite twice: once on SQLite, once against a local Postgres
     if one is available. If the behaviour differs between the two, fix it.
     Accept: the four scenarios as tests, green on both engines.

1.5  BE-4 / BE-5 / PKG-2 / PKG-3 — one cv2, CPU torch, reproducible install.
     Make the resolution deterministic: a constraints file (or --no-deps for
     ultralytics) so exactly one of opencv-python / opencv-python-headless is
     installed, and torch/torchvision come from the CPU index. Add a smoke
     check the build script runs: assert torch.version.cuda is None, assert
     opencv-python-headless is installed and opencv-python is not. Align
     deploy/Dockerfile with the same pins instead of keeping two recipes.
     Accept: on a clean venv the check passes and `pip list | grep -i opencv`
     shows exactly one line; document the expected installed size.

1.6  PKG-1 — make the Windows build run in CI.
     The windows-gate job exists but is marked untested. Make it pass: install
     Python 3.11, run desktop/gate/build_gate.ps1 (portable one-dir bundle
     only — no Inno Setup in CI), assert dist\VisionAI\VisionAI.exe exists, run
     "VisionAI.exe --check --json" and assert it reports ready, record the
     bundle size in the job summary, upload dist as an artifact. Keep it
     allowed to fail for the first run, then make it required once green.
     Accept: the job is green on a commit that changes nothing else, and the
     artifact runs on a clean Windows VM.

---------------------------------------------------------------------
PHASE 2 — CORE CORRECTNESS (data the office will trust)
---------------------------------------------------------------------
2.1  ENT-2 — verify out_without_in and surface it.
     POST OUT with no prior IN -> event stored with out_without_in;
     GET /api/events?flagged=true returns it; the flag appears in CSV/XLSX and
     in the dashboard legend. Update docs/EVENT_CONTRACT.md.
     Accept: the three assertions as tests.

2.2  ENT-3 — the gate must know its clock.
     In the stand-alone gate (no API_URL), compare local time with
     w32tm /query /status (or an NTP-less fallback) and warn in --check; if
     API_URL is set, keep the server comparison. Never block a scan because of
     a clock warning.
     Accept: a unit test for the parsing; --check prints the clock line in both
     modes.

2.3  DET-6 — separate "camera not ready" from "too dark".
     brightness < 2 -> "the camera returned a black frame (not started yet, or
     the lens is covered)"; below the configured minimum -> "too dark: light
     the subject". Same split for a fully flat frame.
     Accept: two tests, one per message.

2.4  DET-7 — verify boxes_total_by_stage and keep boxes_total as the sum.
     Accept: a plate-only frame reports reason "ok", boxes_total > 0 and the
     per-stage breakdown.

2.5  BE-3 — cap the MJPEG proxy.
     Close the upstream when the client goes away, cap concurrent proxies with
     a semaphore sized from config, and return 503 with a clear message when
     saturated. Same disconnect discipline as the SSE route.
     Accept: a test that opens more than the cap and gets 503, and that closing
     the client releases the slot.

2.6  BE-7 — say what the server did with a big upload.
     Compute frame.downscaled from the real original dimensions (do not leave
     it hard-coded False) and include the original width/height.
     Accept: a 12 MP upload reports downscaled: true with the original size.

2.7  NEW-2 — protect the deployment from .dockerignore.
     Add explicit exceptions for files the image needs, or a build-time
     assertion that every runtime asset exists (frontend/**, best.pt,
     anpr_best.pt, weights/ if present).
     Accept: removing a required asset makes the image build fail loudly.

---------------------------------------------------------------------
PHASE 3 — UI / UX (a product, not a demo)
---------------------------------------------------------------------
3.1  The gate verdict strip. Above the camera tile on the dashboard, render
     three lights — Light (brightness), Focus (sharpness), Size (sticker crop
     px) — each green/amber/red from the thresholds the backend already
     computes, with one sentence under it telling the operator what to do. This
     is the change that turns "it doesn't work" into "the light is the
     problem".
     Accept: a DOM test with three mocked scan responses (good, dark, small
     crop) asserting the three states and the sentence.

3.2  UI-1 — modals. role="dialog", aria-modal="true", focus moves to the first
     field on open, Tab is trapped, Escape closes, focus returns to the
     trigger. Apply to every .modal-overlay, including the search modal.
     Accept: a test that opens each modal, tabs around it, presses Escape and
     asserts focus is back on the trigger.

3.3  UI-2 — focus ring. Verify no outline:none remains without a sibling
     :focus-visible rule; add a visible ring where one is missing.
     Accept: grep proves it.

3.4  UI-3 — keyboard-reachable rows. Every clickable row/card becomes a button
     or gets tabindex="0" + role="button" + Enter/Space handling.
     Accept: a script counts tabbable interactive elements per page > 0 and a
     test that Enter opens a row.

3.5  Verify the pages, properly. Load every page at 1920, 1366, 1024, 768 and
     390 px wide, at 100%, 125% and 150% zoom, light and dark theme, and capture
     a screenshot per page per size into docs/ui-screenshots/. Report any
     horizontal scroll on body, overlapping control, unreadable text, element
     below the fold that should not be, and any blank empty/loading/error
     state. Fix what you find and keep the screenshots.
     Accept: the screenshots exist and every page renders in all five widths.

3.6  UI-4 / UI-5 (optional, only if cheap): a "scroll for more" affordance on
     narrow tables, and chart height as a CSS variable instead of !important.

---------------------------------------------------------------------
PHASE 4 — CLOUD (RENDER): make the deployment boring
---------------------------------------------------------------------
The portal is designed for one free/hobby container. Detection does NOT run
there. Verify and harden:
4.1  Confirm the hardening is live, not merely merged: deploy, then check the
     health endpoint, a login, a dashboard left open 10 minutes (the stream
     must reconnect, not die), and the Render Logs containing the boot lines
     "PostgreSQL initialization complete" and "Listening at:
     http://0.0.0.0:10000". Accept: a written pass/fail table with timestamps.
4.2  Cold start and memory: measure the first request after idle and steady RSS
     with three tabs open. If RSS climbs steadily, find the leak (exports and
     page size are the usual suspects) — the free plan never restarts itself.
     Accept: numbers in the report, and an issue if RSS > 400 MB.
4.3  Secrets and domains: confirm the five sync:false values are set in the
     Render dashboard (never in the repo), COOKIE_SECURE=true,
     TRUST_PROXY_HEADERS=true, DEMO_MODE absent, and the Render hostname listed
     in Firebase -> Authentication -> Authorized domains. Add a custom domain
     if I give you one. Accept: a checklist with value NAMES only.
4.4  Backups and recovery: confirm Supabase backups exist, rehearse one restore
     into a scratch project and run the app against it. Write the procedure
     (commands, no secrets) into docs/. Accept: a documented, executed restore.
4.5  The gate PC -> cloud path: with a device key, post one event from a
     gate-like client, confirm it appears on the dashboard, confirm a wrong key
     is 401, and confirm the portal still works if the gate is offline for an
     hour. Accept: four numbered checks with the API's actual responses.
4.6  GATE-1 (scope decision): stage-2 sync from the gate PC to Supabase is NOT
     built. Ask me whether to build it. If yes, it is a new phase: queue
     events locally, upload with the device key, reconcile duplicates with
     ENT-1's rule, and never let a sync failure lose a scan.

---------------------------------------------------------------------
PHASE 5 — DETECTOR DECISION: local .pt first, Roboflow fallback
---------------------------------------------------------------------
Owner's instruction: prove the local .pt path first; if it is problematic, move
the detector to Roboflow, which is easier to operate.

5.1  Prove the local path BEFORE writing any Roboflow code.
     - Build the real-frame fixture set from 1.1.
     - Run scripts/scan_image.py --dir <fixtures> and scripts/frame_report.py;
       record per frame: detected yes/no, bus number, confidence, stage, crop
       px, latency.
     - Once the bundle exists (Phase 6), run the same frames through the
       packaged exe and confirm best.pt loads inside it (--check --deep).
     - Record: recall at confidence >= 0.80, median latency, crop-size
       distribution, installed footprint, bundle size.
     Accept: a table of real numbers in docs/DETECTION.md and a verdict line
     "local .pt: KEEP" or "local .pt: REPLACE", with the reason.

5.2  Decision gate. Move to Roboflow if ANY of these is true:
     (a) recall on real frames at >= 0.80 confidence is below the owner's
         policy (default 0.80) — the model is not good enough;
     (b) best.pt / anpr_best.pt cannot be made to load reliably inside the
         PyInstaller bundle after one honest attempt;
     (c) the .exe must be distributed outside the institution and the AGPL-3.0
         obligation is not acceptable (see Phase 7);
     (d) the installed footprint or bundle is unacceptably large for the gate
         PC.
     If none is true, KEEP the local model and do not add Roboflow.

5.3  Roboflow implementation (only if 5.2 says REPLACE, or I ask for it).
     Add a detector-backend abstraction so the rest of the pipeline is
     unchanged:
       backend/detectors/__init__.py   -> get_detector() from config
       backend/detectors/local.py     -> the existing Ultralytics cascade
       backend/detectors/roboflow.py  -> Roboflow inference
     Config (all environment variables, never committed):
       VISION_DETECTOR_BACKEND = local | roboflow | auto   (default auto)
       ROBOFLOW_API_KEY, ROBOFLOW_WORKSPACE, ROBOFLOW_MODEL_ID,
       ROBOFLOW_MODEL_VERSION, ROBOFLOW_CONFIDENCE, ROBOFLOW_TIMEOUT
     Behaviour:
       - Map Roboflow predictions (x, y, width, height, class, confidence) to
         the same internal box/candidate shape the OCR stage already consumes,
         so normalize_plate, the flag rules and the API response do not change.
       - Two Roboflow routes are acceptable; pick and document one:
         (i) hosted inference API (https://detect.roboflow.com/<model>/<version>
             ?api_key=...) — easiest, but frames leave the gate PC;
         (ii) a Roboflow ONNX export running locally on onnxruntime — no torch,
             keeps frames on the gate PC, and shrinks the .exe the most.
       - `auto`: use local when its model is loaded and healthy, otherwise
         Roboflow; if neither is available, return the existing
         reason="unreadable"/vision_unavailable path — never invent a number.
       - Offline: Roboflow needs internet. If the gate PC is offline, `auto`
         falls back to local; if local is absent too, the scan returns a clear
         200/503 with a reason and NO event is created. Document this.
       - Privacy: the hosted API sends gate frames to Roboflow's cloud — that
         is third-party processing of campus vehicle images. Do not enable it
         by default; require my explicit consent and record it. Prefer the
         local ONNX export if the data must stay on the gate PC.
       - Tests: mock the HTTP call (no network and no key in CI); assert the
         mapping, the timeout, the offline fallback, and that the API key is
         never logged or echoed. Extend scripts/scan_secrets.py to catch a
         Roboflow key pattern.
       - Docs: docs/DETECTION.md gets a "Detector backends" section with the
         decision, the numbers that drove it, and the privacy note.
     Accept: with the local model disabled, a mocked Roboflow response produces
     the same scan JSON as the local path; with no backend available, a scan
     creates no event; the secret scan covers ROBOFLOW_API_KEY.

5.4  If Roboflow is chosen, re-run the .exe build (Phase 6). Without torch the
     bundle should drop to a fraction of its size. Record before/after.

---------------------------------------------------------------------
PHASE 6 — THE WINDOWS .EXE AND INSTALLER (the deliverable)
---------------------------------------------------------------------
The pipeline already exists in source and has never been run end to end:
  desktop/gate/build_gate.ps1  -> .venv-gate, CPU torch, pytest, PyInstaller,
                                  smoke test (--check --json + /api/health),
                                  Inno Setup
  desktop/gate/VisionAI.spec   -> onedir bundle; collects ultralytics,
                                  rapidocr_onnxruntime, onnxruntime, torch,
                                  frontend/, best.pt, anpr_best.pt, weights/
  desktop/gate/VisionAI.iss    -> VisionAI-Setup.exe; %PROGRAMDATA%\VisionAI
                                  data folder; autostart; uninstall keeps the
                                  database
  .github/workflows/ci.yml     -> windows-gate job (untested)

6.1  Make the CI Windows job pass (item 1.6) and keep it required.
6.2  Build once by hand on Windows and document: bundle size, boot time, what
     PyInstaller collected (rapidocr models? onnxruntime DLLs? frontend assets?
     best.pt? weights/vehicle.pt?). Use collect_data_files /
     collect_dynamic_libs where the spec misses something. Target: portable
     one-dir under ~1.2 GB with CPU torch (or far smaller with a Roboflow/ONNX
     backend).
     Accept: dist/VisionAI/VisionAI.exe runs on a clean Windows VM with no
     Python installed; --check --json says ready; the portal answers on the
     chosen port.
6.3  First-run and storage rules. Config, database, logs, crops and failed
     frames live under %APPDATA%\VisionAI or %PROGRAMDATA%\VisionAI (as already
     implemented); nothing is written next to the .exe in Program Files.
     Document the folder map and the retention defaults (40 failed frames,
     20 crops, 2 MB logs) and make them configurable.
     Accept: a test that runs the app with a fresh APPDATA and shows every file
     it creates, all inside it.
6.4  Process hygiene. Port conflict -> try the next port and say which one;
     second instance -> focus the existing one instead of starting a rival
     server; shutdown -> stop the tray, the server and any capture thread
     within a few seconds without a console window; crash -> write a
     diagnostics block that --report can pick up.
     Accept: four scripted checks on Windows (or a documented manual script).
6.5  Installer and trust. Inno Setup produces dist/installer/VisionAI-Setup.exe
     with the services, shortcut, uninstall entry and version metadata. Sign
     both binaries if a certificate exists; if not, document the exact steps
     and submit to Microsoft Defender for false-positive review after the first
     build.
     Accept: install on a clean VM, run the acceptance below, and uninstall
     leaves no service and no file outside %APPDATA% / %PROGRAMDATA%.
6.6  Gate acceptance, on the real gate PC, with the real camera:
     - --check reports READY, with the clock line.
     - Three consecutive real scans produce the right bus number at >= 0.80
       confidence, and the sticker crop is >= 120 px wide.
     - One deliberately bad frame (lens covered) produces the black-frame
       message, not a crash.
     - The event appears on the Render dashboard within the SSE refresh.
     - --report produces a clean one-block health record; attach it to the
       release notes.
     Accept: five numbered results, with the actual numbers.

---------------------------------------------------------------------
PHASE 7 — SECURITY AND LICENCE
---------------------------------------------------------------------
7.1  SEC-1 — rotation first, history second. Rotate the DATABASE_URL password,
     JWT_SECRET and every DEVICE_API_KEYS value (rotation makes the old ones
     worthless immediately); then plan the history purge with me — it rewrites
     every clone, so it needs a coordinated window and a note to anyone with a
     fork. Never paste a secret value into a commit, an issue or a report.
     Accept: proof of rotation (timestamps and which values changed, not the
     values) and a written purge plan.
7.2  PKG-4 — the licence decision is mine, but you must prepare it: one page
     stating (a) Ultralytics AGPL-3.0 obligations for distributing
     VisionAI.exe outside the institution, (b) what changes if it stays
     internal, (c) the cost and consequence of a commercial licence, (d) what
     replacing the detector would take. Record model provenance (where best.pt
     came from, what it was trained on) — it is currently undocumented. If
     Phase 5 moved to Roboflow, state how that changes the licence position.
     Accept: docs/LICENSING.md with those four sections and no invented facts.
7.3  Retention and privacy: confirm failed frames and crops are pruned by the
     documented defaults, and that logs never contain a password, a token, a
     full database URL or a camera URL with credentials. Extend the redaction
     tests if you add a new log site.
     Accept: the redaction tests pass, plus one test per new log site.

---------------------------------------------------------------------
PHASE 8 — VERIFICATION GATE (run before you report)
---------------------------------------------------------------------
    python -m pytest backend/tests                      (all green, count stated)
    for f in frontend/js/*.js; do node --check "$f"; done
    node scripts/check_frontend.mjs
    node scripts/check_auth_flow.mjs
    node scripts/check_firebase_loader.mjs
    node scripts/check_live_stream.mjs
    python scripts/scan_secrets.py
    python scripts/preflight.py --help                  (must not crash)
    git status --short                                 (only intended files)
Plus, if Phase 6 ran: the Windows build, the clean-VM install, and the five
gate acceptance results. A check you could not run is reported as NOT RUN with
the reason — never as passed.

---------------------------------------------------------------------
PHASE 9 — WHAT YOU DELIVER
---------------------------------------------------------------------
One report, in this order:
 1. A status table with one row per numbered item above:
    ID | title | status (DONE / PARTIAL / BLOCKED / NOT RUN) | commit | test that
    proves it. Use the audit's IDs so it maps to ANALYSIS_REPORT.md.
 2. The commands you ran and their real output, trimmed to the relevant lines.
    No invented output. ESTIMATE where you extrapolate.
 3. What changed in behaviour that an operator will notice — one line each, in
    plain language, because the person reading this runs a gate, not a CI.
 4. The detector decision from Phase 5, with its numbers.
 5. Everything you could not verify, and the exact machine or credential needed
    to verify it.
 6. A one-page "run it tomorrow" sheet: how to deploy the portal, how to build
    the .exe, how to install it at the gate, and what to check first if it does
    not work.
 7. The pull requests you opened, each linked to its item, each with the
    verification output pasted into the description.

=====================================================================
8. STOP AND ASK ME (do not guess)
=====================================================================
 1. The camera: make, model, and whether it offers an HTTP snapshot URL or only
    RTSP (an RTSP camera needs a transcoder in front of it). Until this is
    answered, CAMERA_SOURCE and the capture path are unverifiable.
 2. Geometry: sticker width in millimetres and the distance from lens to
    sticker at the gate. That arithmetic decides whether 120 px is achievable.
 3. Accuracy policy: is "flag below 0.80 for a human" acceptable at the gate, or
    must the system be right or silent?
 4. Distribution: may VisionAI.exe leave the institution? That is the AGPL
    question, and it decides whether Phase 7.2 is paperwork or a rewrite.
 5. Offline vs cloud, finally: is the gate PC the system of record (cloud is a
    mirror) or is Supabase authoritative (the gate must sync)? This changes the
    conflict rules in ENT-1 and whether GATE-1 gets built.
 6. Detector: do you consent to gate frames being sent to Roboflow's cloud?
    If not, the local ONNX export or the local .pt path is the only option.
 7. Who operates the system, and therefore whether the Test Lab ships.

If an answer is missing, implement the safe default (gate PC keeps its own
record; cloud mirrors it; local detector preferred; hosted cloud processing
refused), write the assumption in the report, and continue. Do not block on me
for anything that only code can answer.

=====================================================================
9. DEFINITION OF DONE
=====================================================================
The project is done when all of the following are true, and you have shown each
one with output rather than an assertion:
 - The suite is green with and without the vision extras, and the count is
   stated.
 - A real photograph of a real bus sticker produces the right number, and the
   harness that proved it runs in CI.
 - Three identical scans produce one event; garble produces no event.
 - The portal survives a week on Render's free plan with three dashboards open,
   and its logs are readable after a deploy.
 - VisionAI.exe installs on a clean Windows VM from the Inno Setup installer,
   runs without Python, survives a port conflict, a second launch and a reboot,
   and records three correct scans at the real gate.
 - The detector decision (local .pt vs Roboflow) is written down with its
   numbers and its privacy consequence.
 - The owner has a one-page runbook and the licence decision is written down.
```

---

## 4. What changed since the older handoff prompts

| Old prompt | Why it is replaced |
| --- | --- |
| `ANTIGRAVITY_MASTER_PROMPT.md` | Refers to commit `9c432f1`, which does not exist in this clone; claims DET-2, ENT-1, ENT-2, DET-5, ENT-6, BE-1/2/6 are still open when they are fixed; test count 328/23 is stale. |
| `ANTIGRAVITY_PROMPT.md` | Narrow (Render move + `.exe` only), no UI, no Roboflow, no cloud verification phase. |
| `MASTER_PROMPT.md` | Written for the Arena ⇄ VS Code split; its "do not push, Arena opens the PR" rule is obsolete now that one tool owns the work. |
| `MASTER_PROMPT_UIUX.md` | UI/UX only. |

Keep those files for history; use §3 of this file for the actual work.

---

## 5. Owner decisions still open (the agent will ask)

1. Camera make/model and whether it is HTTP-snapshot or RTSP.
2. Sticker width (mm) and lens-to-sticker distance at the gate.
3. Accuracy policy at the gate (flag below 0.80 vs right-or-silent).
4. Whether `VisionAI.exe` may be distributed outside the institution (AGPL).
5. Whether the gate PC or Supabase is the system of record (decides GATE-1).
6. Consent for gate frames to be processed by Roboflow's cloud.
7. Who operates the system, and data-retention policy on the gate PC.
