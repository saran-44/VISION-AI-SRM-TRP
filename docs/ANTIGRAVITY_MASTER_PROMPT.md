# Master prompt for Antigravity — finish the project

**What this file is.** The handover from Arena AI + VS Code to Antigravity, in two
parts: the state of the project as it actually is today (§1–§3), and one
copy-paste prompt (§4) that takes an agent from that state to a working,
installable product: prototype verified, UI fixed, backend fixed, cloud
deployment hardened, Windows `.exe` built.

**Related.** [`ANTIGRAVITY_PROMPT.md`](ANTIGRAVITY_PROMPT.md) is the narrower
version of this brief — only the remaining audit items, no UI, no `.exe`. Use
this file unless you specifically want the short one.

**How to use it.** Paste **§4 only** into Antigravity — everything between the
first and last line of the `text` block. §1–§3 exist so you can answer the agent
when it asks, and so nothing is lost between sessions. Keep the file in the repo:
the agent can read it.

If Antigravity has a context limit, run the prompt in the order given
(§5 explains how to split it) — Phase 1 is the one that matters most.

---

## 1. What has been done so far

Nothing below is a claim about effort. It is what exists in the repository at
commit `9c432f1` and what the audit could measure.

### 1.1 The product, in one paragraph

A gate-pass portal for **SRM TRP Engineering College**. A bus arrives at the
gate, a camera sees the bus-number sticker, the detector reads the number, and
the event (bus, direction, gate, timestamp, confidence) is stored and shown on a
live dashboard. Transport-office staff manage drivers, buses and access; head
admins see audit trails and exports. Detection runs either in the browser
(webcam), on the gate PC (`VisionAI.exe`), or — historically — on a LAN server
("InstaBox"). The portal is now hosted on **Render**, with **Supabase**
PostgreSQL and **Firebase** sign-in.

### 1.2 Built by Arena AI, verified in CI

Every one of these is visible in `git log` and in the CI runs:

| Area | What exists |
| --- | --- |
| Backend | 47 routes on Flask, 14 622 lines of Python in 57 files, application-factory pattern (`create_app()`), one process serves both the API and `frontend/` |
| Auth | JWT in an `HttpOnly`+`SameSite=Lax` cookie, role-based decorators (`head_admin`, `transport_office`), Firebase ID-token exchange, per-route login rate limits, audit log on every mutation |
| Data | SQL over Supabase PostgreSQL in a private `transport_portal` schema (`backend/sql/001_initial.sql`), a thin document-style layer over it (`backend/db.py`), connection pooling tuned for the Supabase pooler |
| Events | ingest / list / filter / paginate / CSV / XLSX export, flag rules (`unregistered_plate`, `low_ocr_confidence`, `long_overstay`), "who is inside" derivation, IN/OUT pairing |
| Detection | two-stage cascade (vehicle/sticker → plate), tiling, frame-quality guards, crop extraction, RapidOCR/Tesseract/EasyOCR fallbacks, diagnostics blocks in `<data>/logs/` |
| Gate agent | `VisionAI.exe`: waitress server, tray icon, setup wizard, `--check`, `--report`, posts scans with `X-Device-Key`, offline-tolerant |
| Tests | 25 test files. **383 passed / 5 skipped** with the vision extras installed; **328 passed / 23 skipped** without them (the 23 are OCR-dependent) |
| Checks | `check_frontend.mjs` (22 modules, 10 pages), `check_auth_flow.mjs`, `check_firebase_loader.mjs`, `check_live_stream.mjs`, `scan_secrets.py` — all wired into a 4-job GitHub Actions pipeline |
| Docs | 26 documents in `docs/` — deployment (Render, Cloud Run, InstaBox, gate PC, Git Bash), detection, cameras, event contract, architecture, security, privacy, upgrade spec |

### 1.3 Delivered in the last two Arena sessions

| PR | Content |
| --- | --- |
| **#52** | `ANALYSIS_REPORT.md`, 591 lines: an independent QA + full-stack + computer-vision audit. Health **6.5/10**, verdict **not ready for the `.exe`**. It contains every finding with path:line, the command that produced it and the exact output; §5 detection accuracy; §6 UI/UX; §7 `.exe` feasibility (PyInstaller vs pywebview vs Electron/Tauri vs browser); §8 a phased roadmap; Appendix B listing what could **not** be verified and why |
| **#53** | Made the portal survive Render's free/hobby plan: the live SSE stream no longer holds a worker thread forever (it ends itself and the page reconnects), `compute_stats()` no longer reads the entire events table, gunicorn moved to 8 threads with worker recycling, error blocks now reach the Render log stream, the 503 message names the real executable, and the second conflicting Windows build script now forwards to the supported one |

### 1.4 Your VS Code sessions — what they proved

The repository records the *results* of local work even where it cannot record the
work itself. These are the facts your local runs established, and they are cited
in the audit:

| Evidence | Where it appears |
| --- | --- |
| The gate PC's own scan log: 16 scans, sticker crops only **25–44 px**, `reason=unreadable`, sharpness 13–36 | `ANALYSIS_REPORT.md` §4 `DET-4`, §5.4 |
| Two scans at **brightness 0.0** at startup, then 12 at 67–115 — indistinguishable in the advice text | §4 `DET-6` |
| Real gate latency **2 783–2 877 ms** per scan (vs 712–1 594 ms in the sandbox) | §5.3 |
| The vision install produced a **7.7 GB** `.venv` and `ImportError: libGL.so.1` | §2.4, `BE-4`/`BE-5`, `PKG-2` |
| A PyInstaller build attempt that did not produce a usable bundle | §2.5, `PKG-1` |

What VS Code sessions have **not** produced, and Antigravity must not assume:
no `dist/` build, no signed installer, no Windows CI job, no real-photo detection
fixtures, no verified live Render deployment. That is the gap this prompt closes.

### 1.5 What is honestly unfinished

Short version: **the software runs; the product is not installable.** The portal
works end to end on a workstation and on Render, but the gate PC cannot yet be
handed a signed `.exe`, the detector's accuracy has never been measured on a real
photograph, and three correctness bugs can corrupt the record (duplicate events,
garble accepted as a bus number, a `VISION_IMAGE_SIZE` that misses the frame the
gate actually sends).

---

## 2. Current progress snapshot

| Piece | State | Proof / gap |
| --- | --- | --- |
| Portal UI (9 pages + login, 22 ES modules, 3 888 lines of CSS) | Works | static checks pass; **never reviewed in a real browser** — no screenshots exist |
| Backend API (47 routes) | Works | 328 tests pass without vision extras |
| Auth + roles + audit | Works | cookie flags, rate limits and export-injection guards audited as **Verified OK** |
| Database (Supabase, private schema) | Works | schema applied manually; app never auto-migrates Postgres |
| Detection on a workstation | Works, **unmeasured** | synthetic frames only; 960 px detects, 1280/1536/1920 miss on the same sample |
| Detection on the gate PC | **Blocked on optics** | crops of 25–44 px vs the 120 px OCR needs |
| Live dashboard (SSE) | Works, bounded | PR #53; page reconnects instead of dropping to polling |
| Render free/hobby deployment | Configured + hardened | no outside-in verification of the live URL from this repo |
| InstaBox (LAN host) | Optional | documented decision: retire it unless server-side RTSP detection is still wanted |
| `VisionAI.exe` | Source + spec + Inno script exist | **never built successfully**, no Windows CI, bundle size unknown |
| Accuracy gate in CI | Missing | no real-image fixtures (`DET-1`) |
| Licence decision (Ultralytics AGPL-3.0) | Undecided | blocks distribution outside the institution |

---

## 3. Issue register (as of `9c432f1`)

Severity and IDs are the audit's, so they stay traceable to
[`ANALYSIS_REPORT.md`](../ANALYSIS_REPORT.md). **Status** is what is true now.

| ID | Sev | Issue | Status |
| --- | --- | --- | --- |
| `DET-1` | Blocker | No real-image regression set — accuracy unverifiable | **OPEN** |
| `DET-2` | Blocker | Arbitrary OCR text becomes a bus number (`normalize_plate("hello world")` → `HELLO WORLD`, accepted with 201) | **OPEN** |
| `DET-3` | High | `VISION_IMAGE_SIZE=1280` ships while 960 is the only size that detected the sample | **OPEN** (decision) |
| `DET-4` | High | Crop below OCR-readable size on the webcam path | Code fixed (`OCR_READABLE_CROP_PX=120`); depends on real optics |
| `DET-5` | Medium | `inspect_model.py` reports "ultralytics is not installed" for any import failure | **OPEN** |
| `DET-6` | Medium | A black frame and a dark room give the same advice | **OPEN** |
| `DET-7` | Low | `boxes_total` counts sticker stage only; plate-only hit shows `0 boxes` with `reason=ok` | **OPEN** |
| `ENT-1` | Blocker | No duplicate suppression — 3 identical POSTs ⇒ 3 events | **OPEN** |
| `ENT-2` | Medium | `OUT` without a matching `IN` accepted and unflagged | **OPEN** |
| `ENT-3` | Medium | Stand-alone gate never checks its clock, yet >5 min future is rejected | **OPEN** |
| `ENT-4` | Medium | `compute_stats()` read every event ever | **FIXED** (bounded to `STATS_LOOKBACK_DAYS`, default 45) |
| `ENT-5` | Low | CSV `flag_reasons` contained a Python repr | **FIXED** |
| `ENT-6` | Low | Naive timestamps rejected with a generic message | **CHANGED** — naive is now read as UTC, which is friendlier but silently shifts a local-time sender by 5.5 h in IST (see `NEW-1`) |
| `BE-1` | Blocker | SSE pinned a worker thread forever | **FIXED** (stream ends after `API_SSE_SECONDS`, heartbeats, 8 threads) |
| `BE-2` | High | Full-table aggregation per SSE tick | **FIXED** (shared cache + bounded scan) |
| `BE-3` | Medium | MJPEG proxy holds a thread per viewer, no cap | **OPEN** |
| `BE-4` | Medium | Two OpenCV distributions installed at once; `libGL.so.1` | **PARTIAL** — the Docker image now uninstalls `opencv-python` and pins headless; a Windows `pip install -r requirements-desktop.txt` can still do it |
| `BE-5` | Medium | CUDA torch is the default install outcome (7.7 GB) | **PARTIAL** — `build_gate.ps1` installs CPU torch first, `requirements-vision.txt` still has no `+cpu` marker and no assertion |
| `BE-6` | Low | SSE client never returned to SSE after one failure | **FIXED** |
| `BE-7` | Low | Oversized uploads downscaled silently | **OPEN** |
| `SEC-1` | High | A credential remains in git history (project's own admission) | **OPEN** — rotation + history purge |
| `UI-1` | Medium | Modals not keyboard-accessible | **PARTIAL** — `role="dialog"`/`aria-modal` and Escape exist on two overlays; no focus trap, no focus-on-open |
| `UI-2` | Medium | Three inputs remove the focus ring with no replacement | **OPEN** |
| `UI-3` | Low | Custom clickable rows unreachable by keyboard (`tabindex` count: 0) | **OPEN** |
| `UI-4` | Low | Wide tables scroll inside a 680 px box on phones | Accepted; optional affordance |
| `UI-5` | Low | Chart height `!important`-pinned to 240 px | Accepted; optional CSS variable |
| `PKG-1` | Blocker | The `.exe` pipeline has never run; CI has no Windows job | **OPEN** |
| `PKG-2` | Blocker | 7.7 GB dependency footprint | **PARTIAL** — CPU index used by the build script; bundle never measured |
| `PKG-3` | High | Build correctness depends on install order | **OPEN** |
| `PKG-4` | High | AGPL-3.0 obligations for a distributed binary | **OPEN** — owner decision |

### Two things found while writing this file

| ID | Sev | Issue |
| --- | --- | --- |
| `NEW-1` | Low | `EventCreate.validate_timestamp` treats a naive timestamp as UTC (`schemas.py:189-196`). A script or a third-party gateway sending local Indian time is silently recorded 5.5 h in the past. Either reject naive values with a message that says "include an offset, e.g. +05:30", or document it loudly. |
| `NEW-2` | Low | `.dockerignore` excludes `**/*.json`. Nothing needs a JSON file in the Render image today (only `firebase.json` exists, and it is not used at runtime), but a future `frontend/assets/*.json` or model metadata would vanish from the deployment with no error. Add an explicit `!` exception list, or a build assertion. |

---

## 4. THE PROMPT — copy everything inside this block

```text
You are the lead engineer finishing a real, deployed product. Work in the
repository you have been given (VISION-AI-SRM-TRP). You may edit code, run
commands, open pull requests, and ask me questions — but you may not merge, and
you may not invent results.

=====================================================================
1. THE PRODUCT
=====================================================================
A gate-pass portal for SRM TRP Engineering College. A bus arrives; a camera sees
the bus-number sticker; the detector reads the number; an event (bus, direction,
gate, timestamp, confidence) is stored and shown on a live dashboard. The
transport office manages drivers, buses and access lists; head admins see audit
trails and exports.

One Flask application (backend/app.py, 47 routes) serves both the JSON API and
the static frontend (frontend/: 9 pages + a login page, 22 ES modules). Data is
SQL in a private Supabase PostgreSQL schema (transport_portal); sign-in is a JWT
in an HttpOnly cookie, optionally exchanged from a Firebase ID token.

Two deployments exist and they are NOT the same thing:

  (a) The portal — Render, one Docker container, free/hobby plan: 512 MB RAM,
      ephemeral disk, sleeps when idle, one instance. Serves the UI and the API.
      It cannot run the detector: no torch, no OCR, and no network route to a
      camera on the college LAN. /api/detection/scan therefore answers 503 with
      code "vision_local_agent_required". That is correct behaviour. Do not
      "fix" it by installing torch.

  (b) The gate PC — a Windows machine at the gate running VisionAI.exe
      (desktop/gate/: PyInstaller spec, Inno Setup script, build_gate.ps1,
      launcher.py). It owns the camera, runs the detection cascade, and posts
      identified events to the portal with an X-Device-Key header. It must keep
      working with no internet: record locally, upload later.

A third, older deployment — "InstaBox", a LAN host at 172.16.0.2:8080 running
deploy/instabox/docker-compose.yml with INSTALL_VISION=1 — is being retired. It
exists only if server-side detection of a LAN camera is still wanted. Never run
it as a second portal against the same database.

=====================================================================
2. STATE OF PLAY (verify all of this before you change anything)
=====================================================================
Branch from main at or after commit 9c432f1.

Tests: 25 files. With the vision extras installed the suite reports
383 passed / 5 skipped; without them 328 passed / 23 skipped (the 23 are
OCR-dependent). Node checks: check_frontend.mjs (22 modules, 10 pages),
check_auth_flow.mjs, check_firebase_loader.mjs, check_live_stream.mjs,
scan_secrets.py. CI is four ubuntu-latest jobs; there is no Windows job.

Already fixed on main — verify, do not redo:
  - /api/stream is bounded: it ends itself after API_SSE_SECONDS (210 s) with an
    "event: end", sends ": keep-alive" between ticks, and shares one
    compute_stats() result across clients. backend/app.py, functions
    sse_lifetime_seconds / sse_refresh_seconds / sse_heartbeat_seconds, route
    around app.py:995.
  - frontend/js/sse.js reconnects with backoff and only polls after five
    consecutive failures. Pinned by scripts/check_live_stream.mjs.
  - compute_stats() only reads the last STATS_LOOKBACK_DAYS (45) of events.
  - deploy/render/entrypoint.sh: --workers ${WEB_CONCURRENCY:-1},
    --threads ${GUNICORN_THREADS:-8}, --graceful-timeout 30,
    --max-requests 800 --max-requests-jitter 80, binds 0.0.0.0:$PORT, decodes
    PGSSLROOTCERT_B64.
  - backend/diagnostics.py mirrors every error block to the Python logger,
    because a hosted disk is ephemeral.
  - Nothing in the repository says "VisionAI-GateAgent"; the binary is
    VisionAI.exe and desktop/build_windows.ps1 forwards to the supported build.
  - CSV flag_reasons is a joined string, not a Python list repr.

Still broken, in the order this prompt fixes it: see the work packet below.
The full evidence for every item is in ANALYSIS_REPORT.md — read §3, §4, §6, §7
and Appendix B before you write code.

=====================================================================
3. GROUND RULES
=====================================================================
 1. Never commit a secret. No DATABASE_URL, JWT_SECRET, DEVICE_API_KEYS,
    Firebase keys, camera URLs with credentials, certificates or .env files.
    If you print one, treat it as burned and say so.
 2. Do not add torch, ultralytics, rapidocr, onnxruntime or opencv to
    deploy/render/Dockerfile. The slim image is deliberate.
 3. Do not weaken security to make something pass: no COOKIE_SECURE=false, no
    debug mode, no DEMO_MODE, no wildcard CORS, no disabled rate limits, no
    skipped secret scan, no skipped test.
 4. Every behaviour change needs a test that fails before and passes after. A
    skipped test is not a passing test — list what skipped and why.
 5. Small commits, one concern each, conventional messages (fix:, feat:, test:,
    docs:, build:). One pull request per numbered item in section 5. Never
    rewrite history, never force-push, never merge.
 6. Keep the gate PC (b) fully working offline while you change the portal (a).
 7. If you cannot verify something (no browser, no Windows, no real camera),
    say so explicitly and produce a script or a CI job that will verify it on
    the machine that can, rather than declaring it done.
 8. Do not refactor for taste. This is a product with one operator and a gate
    that opens at 8 a.m. — changes must reduce a real risk.
 9. Numbers in your report must come from output you actually ran. Quote the
    command and the output. If you extrapolate, label it ESTIMATE.
10. Preserve the audit's vocabulary: keep the IDs (DET-1, ENT-1, ...) in commit
    messages and in your final report so the owner can trace every item back to
    ANALYSIS_REPORT.md.

=====================================================================
4. PHASE 0 — GROUND TRUTH (no code changes; report findings)
=====================================================================
Run and record:
    pwd && git log --oneline -5 && git status --short
    python --version && node --version
    cat render.yaml && cat deploy/render/entrypoint.sh
    python -m pytest backend/tests            (expect a summary line with
                                               counts; with no vision extras
                                               expect ~328 passed / 23 skipped)
    for f in frontend/js/*.js; do node --check "$f"; done
    node scripts/check_frontend.mjs
    node scripts/check_auth_flow.mjs
    node scripts/check_firebase_loader.mjs
    node scripts/check_live_stream.mjs
    python scripts/scan_secrets.py

Then answer, in two lines each: what runs, what fails, what you cannot run here.
Do not proceed to Phase 1 until the suite is green (or until you have reported
exactly which tests fail and why).

=====================================================================
5. WORK PACKET
=====================================================================
Each item = one pull request. "Accept" lists the test that must exist.

--- PHASE 1: BLOCKERS. Nothing else matters until these are closed. ---------

1.1  DET-1 — a real-image regression set.
     Create tests/fixtures/detection/ with 10–20 real frames: sticker close,
     mid, far, night, glare, two buses in frame, no bus. The repository ignores
     *.jpg/*.png, so add explicit ! exceptions for this directory only, and
     document in docs/DETECTION.md that these images are of vehicles, not people.
     Add a pytest module that runs the cascade over each fixture and asserts a
     per-frame expectation recorded in a small JSON manifest (bus number or
     "no_detection" + a confidence floor), and a CI job that runs it only when
     backend/vision.py, best.pt or the fixtures change.
     If you cannot provide real images, implement the harness, ship the manifest
     format, and mark the fixtures MISSING — do not synthesise them and call the
     accuracy verified.
     Accept: pytest -k fixtures runs the harness; a deliberately wrong manifest
     entry makes it fail.

1.2  DET-3 — the image size the gate actually ships.
     desktop/gate/launcher.py hard-codes VISION_IMAGE_SIZE=1280 (two places)
     while .env.example says 960 and the only sample that detected did so at 960.
     Measure on the 1.1 fixtures: for each size in {640, 960, 1280, 1536},
     record detection rate and median latency. Choose from that data, set it in
     ONE place (a single constant the launcher, docs and .env.example all read
     or quote), and record the decision and its numbers in docs/DETECTION.md.
     Accept: a test asserts the launcher's value equals the documented value.

1.3  DET-2 — garble must not become a bus number.
     normalize_plate (backend/vision.py:758) currently returns "HELLO WORLD" for
     "hello world", and EventCreate.bus_number (backend/schemas.py, pattern at
     line 9) accepts it, so a bad OCR read creates a real event.
     - normalize_plate returns "" unless the result is 2–20 chars AND contains
       at least one digit. Callers must treat "" as "unreadable": a scan returns
       200 with bus_number null and a reason, and never creates an event.
     - EventCreate rejects a bus_number with no digit (422, message names
       bus_number). Keep the existing character rules.
     - Audit every caller: the scan route, the gate agent path, scripts/
       scan_image.py, scripts/frame_report.py.
     Accept: normalize_plate("hello world") == ""; POST /api/events with
     "HELLO WORLD" → 422; "KL01AB1234" still normalises and stores; a scan with
     unreadable OCR returns 200 and creates nothing.

1.4  ENT-1 — duplicate suppression.
     ingest_event (backend/services.py:123) inserts unconditionally: three
     identical POSTs in three minutes create three rows.
     - Add EVENT_DEBOUNCE_SECONDS (default 60). Inside the window, an event with
       the same (bus_number, direction, gate) is not inserted: return 200 with
       {"duplicate": true, "event": <existing>} and write an audit row
       "event_deduplicated". Outside the window, insert normally — a bus really
       does leave and come back.
     - A different direction or gate is never a duplicate.
     - Behaviour must be identical on SQLite (tests) and PostgreSQL
       (production). Prefer a partial unique index plus conflict handling, or a
       single transaction; do not rely on timing.
     Accept: 3 POSTs in 3 s → 201, 200 duplicate, 200 duplicate and exactly one
     row in GET /api/events; a POST 61 s later inserts; IN then OUT 1 s later
     inserts both. Run the suite twice: once on SQLite, once against a local
     Postgres if you have one.

1.5  BE-4 / BE-5 / PKG-2 / PKG-3 — one cv2, CPU torch, reproducible install.
     On Windows, `pip install -r requirements-desktop.txt` currently resolves
     ultralytics' opencv-python over opencv-python-headless (→ ImportError:
     libGL.so.1 on Linux images, two cv2 distributions on Windows) and torch
     from PyPI is the CUDA build (7.7 GB installed).
     - Make the resolution deterministic: constraints file (or --no-deps for
       ultralytics) so exactly one of opencv-python / opencv-python-headless is
       installed, and torch/torchvision come from
       https://download.pytorch.org/whl/cpu.
     - Add a smoke check the build script runs: assert torch.version.cuda is
       None, assert importlib.metadata.version("opencv-python-headless") exists
       and that no "opencv-python" distribution is installed.
     - deploy/Dockerfile already does this by hand; align it with the new pins
       instead of keeping two recipes.
     Accept: on a clean venv the check script passes and `pip list | grep -i
     opencv` shows exactly one line; document the expected installed size.

1.6  PKG-1 — a Windows build that runs in CI.
     Add a windows-latest job that installs Python 3.11, runs
     desktop/gate/build_gate.ps1 (portable one-dir bundle only — no Inno Setup
     in CI), asserts dist\VisionAI\VisionAI.exe exists, runs
     "VisionAI.exe --check --json" and asserts status "ready", records the
     bundle size in the job summary, and uploads dist as an artifact. Keep it
     allowed to fail for the first run, then make it required once green.
     Accept: the job is green on a commit that changes nothing else, and the
     artifact downloads and runs on a clean Windows VM.

--- PHASE 2: CORE CORRECTNESS (data the office will trust) -------------------

2.1  ENT-2 — flag OUT without IN. Add flag reason "out_without_in"; add
     "duplicate_in" if ENT-1's merge keeps the second row instead. Update
     docs/EVENT_CONTRACT.md and the dashboard legend.
     Accept: POST OUT with no prior IN → event stored with out_without_in;
     GET /api/events?flagged=true returns it; the flag appears in CSV/XLSX.

2.2  ENT-3 — the gate must know its clock. In the stand-alone gate (no
     API_URL), compare local time with w32tm /query /status (or an NTP-less
     fallback) and warn in --check; if API_URL is set, keep the server
     comparison. Never block a scan because of a clock warning.
     Accept: a unit test for the parsing, and --check prints the clock line in
     both modes.

2.3  DET-5 — inspect_model.py must report the real error. Replace the broad
     except ImportError with one that prints the exception (so libGL.so.1 shows
     up as itself, not as "ultralytics is not installed").
     Accept: monkeypatched import failure prints "the vision stack failed to
     import: <original text>".

2.4  DET-6 — separate "camera not ready" from "too dark". brightness < 2 →
     "the camera returned a black frame (not started yet, or the lens is
     covered)"; < the configured minimum → "too dark: light the subject". Same
     split for a fully flat frame.
     Accept: two tests, one per message.

2.5  DET-7 — boxes_total must not say 0 when the plate stage found boxes.
     Add boxes_total_by_stage (sticker/plate) and keep boxes_total as the sum.
     Accept: a plate-only frame reports reason "ok", boxes_total > 0 and the
     per-stage breakdown.

2.6  BE-3 — cap the MJPEG proxy. Close the upstream when the client goes away
     and cap concurrent proxies (a semaphore sized from config); return 503 with
     a clear message when saturated. Same disconnect discipline as the SSE route.
     Accept: a test that opens more than the cap and gets 503, and that closing
     the client releases the slot.

2.7  BE-7 / NEW-1 — say what the server did. Add frame.downscaled plus the
     original width/height to the scan response when a big upload was reduced.
     For timestamps: reject a naive value with "include a timezone offset, e.g.
     +05:30" (preferred), or document the UTC assumption in docs/EVENT_CONTRACT.md
     and in the 422 details. Pick one and be consistent.
     Accept: a 12 MP upload reports downscaled: true with the original size; a
     naive timestamp gets the documented answer.

2.8  NEW-2 — protect the deployment from .dockerignore. Either add explicit
     exceptions for files the image needs, or add a build-time assertion that
     every runtime asset exists (frontend/**, best.pt if present, weights/).
     Accept: removing a required asset makes the image build fail loudly.

--- PHASE 3: UI / UX (a product, not a demo) ---------------------------------

3.1  The gate verdict strip. Above the camera tile on the dashboard, render
     three lights — Light (brightness), Focus (sharpness), Size (sticker crop
     px) — each green/amber/red from the thresholds the backend already
     computes (backend/vision.py: OCR_READABLE_CROP_PX, min_frame_brightness,
     the sharpness floor). One sentence under it, from the same numbers, telling
     the operator what to do. This single change is what turns "it doesn't work"
     into "the light is the problem".
     Accept: a DOM test with three mocked scan responses (good, dark, small
     crop) asserting the three states and the sentence.

3.2  UI-1 — modals. role="dialog", aria-modal="true", focus moves to the first
     field on open, Tab is trapped, Escape closes, focus returns to the
     trigger. Apply to every .modal-overlay (search, table overlay, any manage
     page dialog).
     Accept: a test that opens each modal, tabs around it, presses Escape and
     asserts focus is back on the trigger.

3.3  UI-2 — focus ring. The three outline:none controls (login.css:170,
     styles.css:216, styles.css:1219) get a visible :focus-visible ring
     (box-shadow 0 0 0 2px var(--primary), with the existing contrast).
     Accept: grep proves no outline:none remains without a sibling
     :focus-visible rule.

3.4  UI-3 — keyboard-reachable rows. Every clickable row/card becomes a
     button or gets tabindex="0" + role="button" + Enter/Space handling.
     Accept: a script that counts tabbable interactive elements per page > 0 and
     a test that Enter opens a row.

3.5  Verify the pages, properly. You have a browser; the audit did not. Load
     every page at 1920, 1366, 1024, 768 and 390 px wide, at 100 %, 125 % and
     150 % zoom, in a light and a dark theme, and capture a screenshot per page
     per size into docs/ui-screenshots/. Report: any horizontal scroll on body,
     any overlapping control, any unreadable text, any element below the fold
     that should not be, and any page whose empty/loading/error state is blank.
     Fix what you find and keep the screenshots.
     Accept: the screenshots exist and every page renders in all five widths.

3.6  UI-4 / UI-5 (optional, only if cheap): a "scroll for more" affordance on
     narrow tables, and chart height as a CSS variable instead of !important.

--- PHASE 4: CLOUD (Render) — make the deployment boring --------------------

4.1  Verify the hardening is live, not merely merged. Deploy, then check: the
     health endpoint, a login, a dashboard left open for 10 minutes (the stream
     must reconnect, not die), and the Render Logs containing the boot lines
     "PostgreSQL initialization complete" and "Listening at: http://0.0.0.0:10000".
     Accept: a written pass/fail table with timestamps.

4.2  Cold start and memory. Measure: first request after idle, and steady RSS
     with three tabs open. If RSS climbs steadily, find the leak (exports and
     page-size are the usual suspects) — the free plan never restarts itself.
     Accept: numbers in the report, and an issue if RSS > 400 MB.

4.3  Secrets and domains. Confirm the five sync:false values are set in the
     Render dashboard (never in the repo), COOKIE_SECURE=true,
     TRUST_PROXY_HEADERS=true, DEMO_MODE absent, and the Render hostname listed
     in Firebase → Authentication → Authorized domains. Add the custom domain
     if I give you one.
     Accept: a checklist with the value names only, never the values.

4.4  Backups and recovery. Confirm Supabase backups exist, then rehearse one
     restore into a scratch project and run the app against it. Write the
     procedure (with commands, no secrets) into docs/.
     Accept: a documented, executed restore.

4.5  The gate PC → cloud path. With a device key, post one event from a gate-like
     client, confirm it appears on the dashboard, confirm a wrong key is 401,
     and confirm the portal still works if the gate is offline for an hour.
     Accept: four numbered checks with the API's actual responses.

--- PHASE 5: THE WINDOWS .EXE (the deliverable) -----------------------------

5.1  Build it once, by hand, and document what happened: bundle size, boot
     time, what PyInstaller collected (rapidocr models? onnxruntime DLLs?
     frontend assets? best.pt? weights/vehicle.pt?). Use collect_data_files /
     collect_dynamic_libs where the spec misses something. Target: portable
     one-dir under ~1.2 GB with CPU torch.
     Accept: dist/VisionAI/VisionAI.exe runs on a clean Windows VM with no
     Python installed; --check --json says "ready"; the portal answers on the
     chosen port.

5.2  First-run and storage rules. Config, database, logs, crops and failed
     frames live under %APPDATA%\VisionAI (or %PROGRAMDATA% for machine-wide
     config as already implemented); nothing is written next to the .exe in
     Program Files. Document the folder map and the retention defaults (40
     failed frames, 20 crops, 2 MB logs) and make them configurable.
     Accept: a test that runs the app with a fresh APPDATA and shows every file
     it creates, all inside it.

5.3  Process hygiene. Port conflict → try the next port and say which one;
     second instance → focus the existing one instead of starting a rival
     server; shutdown → stop the tray, the server and any capture thread within
     a few seconds without a console window; crash → write a diagnostics block
     that --report can pick up.
     Accept: four scripted checks on Windows (or a documented manual script if
     CI cannot do it).

5.4  Installer and trust. Inno Setup script produces dist/installer/
     VisionAI-Setup.exe with the services, firewall rule (if needed), shortcut,
     uninstall entry and version metadata. Sign both binaries if a certificate
     exists; if not, document the exact steps and submit to Microsoft Defender
     for false-positive review after the first build.
     Accept: install on a clean VM, run the acceptance below, uninstall leaves
     no service and no file outside %APPDATA%.

5.5  Gate acceptance, on the real gate PC, with the real camera:
     - --check reports READY, with the clock line.
     - Three consecutive real scans produce the right bus number at
       ≥ 0.80 confidence, and the sticker crop is ≥ 120 px wide.
     - One deliberately bad frame (lens covered) produces the black-frame
       message, not a crash.
     - The event appears on the Render dashboard within the SSE refresh.
     - --report produces a clean one-block health record; attach it to the
       release notes.
     Accept: five numbered results, with the actual numbers.

--- PHASE 6: SECURITY AND LICENCE ------------------------------------------

6.1  SEC-1 — rotation first, history second. Rotate DATABASE_URL's password,
     JWT_SECRET and every DEVICE_API_KEYS value (rotation makes the old ones
     worthless immediately); then plan the history purge with me — it rewrites
     every clone, so it needs a coordinated window and a note to anyone with a
     fork. Never paste a secret value into a commit, an issue or a report.
     Accept: proof of rotation (timestamps and which values changed, not the
     values), and a written purge plan.

6.2  PKG-4 — the licence decision is mine, but you must prepare it: state in one
     page (a) Ultralytics AGPL-3.0 obligations for distributing VisionAI.exe
     outside the institution, (b) what changes if it stays internal, (c) the
     cost and consequence of a commercial licence, (d) what replacing the
     detector would take. Record model provenance (where best.pt came from, what
     it was trained on) — it is currently undocumented.
     Accept: docs/LICENSING.md with those four sections and no invented facts.

6.3  Retention and privacy: confirm failed frames and crops are pruned by the
     documented defaults, and that logs never contain a password, a token, a
     full database URL or a camera URL with credentials (the redaction tests
     already cover the patterns; extend them if you add a new log site).
     Accept: the redaction tests pass, plus one test per new log site.

=====================================================================
6. PHASE 7 — VERIFICATION GATE (run before you report)
=====================================================================
    python -m pytest backend/tests                      (all green, count stated)
    for f in frontend/js/*.js; do node --check "$f"; done
    node scripts/check_frontend.mjs
    node scripts/check_auth_flow.mjs
    node scripts/check_firebase_loader.mjs
    node scripts/check_live_stream.mjs
    python scripts/scan_secrets.py
    python scripts/preflight.py --help
    git status --short                                   (only intended files)

Plus, if Phase 5 ran: the Windows build, the clean-VM install, and the five gate
acceptance results. A check you could not run is reported as NOT RUN with the
reason — never as passed.

=====================================================================
7. PHASE 8 — WHAT YOU DELIVER
=====================================================================
One report, in this order:

 1. A status table with one row per numbered item above:
    ID | title | status (DONE / PARTIAL / BLOCKED / NOT RUN) | commit | test that
    proves it. Use the audit's IDs so it maps to ANALYSIS_REPORT.md.
 2. The commands you ran and their real output, trimmed to the relevant lines.
    No invented output. ESTIMATE where you extrapolate.
 3. What changed in behaviour that an operator will notice — one line each, in
    plain language, because the person reading this runs a gate, not a CI.
 4. Everything you could not verify, and the exact machine or credential needed
    to verify it.
 5. A one-page "run it tomorrow" sheet: how to deploy the portal, how to build
    the .exe, how to install it at the gate, and what to check first if it does
    not work.
 6. The pull requests you opened, each linked to its item, each with the
    verification output pasted into the description.

=====================================================================
8. STOP AND ASK ME (do not guess)
=====================================================================
 1. The camera: make, model, and whether it offers an HTTP snapshot URL or only
    RTSP (an RTSP camera needs a transcoder in front of it). Until this is
    answered, CAMERA_SOURCE and the whole capture path are unverifiable.
 2. Geometry: sticker width in millimetres and the distance from lens to
    sticker at the gate. That arithmetic decides whether 120 px is achievable at
    all — it is the difference between tuning and replacing optics.
 3. Accuracy policy: is "flag below 0.80 for a human" acceptable at the gate, or
    must the system be right or silent?
 4. Distribution: may VisionAI.exe leave the institution? That is the AGPL
    question, and it decides whether Phase 6.2 is paperwork or a rewrite.
 5. Offline vs cloud, finally: is the gate PC the system of record (cloud is a
    mirror) or is Supabase authoritative (gate must sync)? This changes the
    conflict rules in ENT-1 and the offline queue in the gate agent.

If an answer is missing, implement the safe default (gate PC keeps its own record;
cloud mirrors it), write the assumption down in the report, and continue. Do not
block on me for anything that only code can answer.

=====================================================================
9. DEFINITION OF DONE
=====================================================================
The project is done when all of the following are true, and you have shown each
one with output rather than an assertion:
 - The suite is green with and without the vision extras, and the count is stated.
 - A real photograph of a real bus sticker produces the right number, and the
   harness that proved it runs in CI.
 - Three identical scans produce one event; garble produces no event.
 - The portal survives a week on Render's free plan with three dashboards open,
   and its logs are readable after a deploy.
 - VisionAI.exe installs on a clean Windows VM from the Inno Setup installer,
   runs without Python, survives a port conflict, a second launch and a reboot,
   and records three correct scans at the real gate.
 - The owner has a one-page runbook and the licence decision is written down.
```

---

## 5. How to run this in Antigravity

**One session per phase.** The prompt is written so Phase 2 does not depend on
Phase 1's code, but Phase 5 does. Suggested order and what to paste:

| Session | Paste | Ask for |
| --- | --- | --- |
| 1 | the whole block | Phase 0 + Phase 1 only; stop after the blockers |
| 2 | §1–§3 + Phase 2 | the correctness items, one PR each |
| 3 | §1–§3 + Phase 3 | UI fixes **and** the screenshot matrix |
| 4 | §1–§3 + Phase 4 | cloud verification, using your Render dashboard access |
| 5 | §1–§3 + Phase 5 | the `.exe` build — this needs a Windows machine with the gate camera |
| 6 | §1–§3 + Phase 6 + Phase 7 | security, licensing, and the final verification gate |

**What to watch for.** Antigravity is good at executing a checklist and bad at
knowing when a checklist does not apply. Three guardrails are already in the
prompt; enforce them:

- If it reports `383 passed` without installing the vision extras, it is copying
  a number from the audit. The real count without extras is **328 passed /
  23 skipped**.
- If it proposes adding torch to the Render image to "enable detection", it has
  not read §1(a). Refuse.
- If it marks `DET-1` done with synthetic fixtures, that is a regression of the
  audit's own finding — real frames or `MISSING`, nothing in between.

**When to stop and give it a new constraint.** Two owner questions genuinely
change the code rather than the paperwork: the camera (§8.1) and whether the gate
PC or Supabase is the system of record (§8.5). Answer those two before session 2
if you can; the rest can arrive later.

---

## 6. What is still mine to decide, not the agent's

1. The camera model and its snapshot/RTSP URL.
2. Sticker width + lens distance (decides whether the optics are adequate).
3. Whether `VisionAI.exe` may be distributed outside the institution (AGPL).
4. The accuracy policy at the gate.
5. Who operates the system, and therefore whether the Test Lab ships.
6. Data retention on the gate PC.
7. The Windows version of the gate PC and whether WebView2 is present.

Everything else in this file is the agent's job.
