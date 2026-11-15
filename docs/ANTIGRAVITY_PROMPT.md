# Antigravity prompt: finish the Render move and the `.exe`

Copy everything inside the block below into Antigravity (or any coding agent that
can run commands in the repository). It assumes the checkout is this repository
and that the agent may edit code, run tests and commit on a branch.

Replace nothing except the two placeholders marked `<...>` if they differ for you.

---

```text
You are working in the Git repository "VISION-AI-SRM-TRP": a Flask backend
(backend/) that also serves the static frontend (frontend/), a Windows detector
and gate launcher (desktop/), a rewritten SQL over Supabase PostgreSQL
(backend/sql/001_initial.sql, schema transport_portal), and a Render deployment
(render.yaml, deploy/render/). Python 3.11. Tests live in backend/tests.

CONTEXT AND DECISION ALREADY MADE
The project is moving off the college LAN machine ("InstaBox", 172.16.0.2:8080)
onto Render. The portal runs on Render's free/hobby plan: ONE container, 512 MB
RAM, ephemeral disk, sleeping when idle. Detection does NOT run there — the free
plan cannot hold CPU torch + Ultralytics + ONNX OCR (~2 GB), and Render cannot
reach a camera on the college LAN anyway. Detection runs on the gate PC via
VisionAI.exe (Windows), which posts identified events to the Render portal with
an X-Device-Key header. On a Render instance /api/detection/scan must answer
503 with code "vision_local_agent_required" — that is correct behaviour, not a
bug, and must not be "fixed" by installing torch.

Read first, do not skim: README.md, docs/DEPLOY_RENDER_FREE.md,
docs/DEPLOY_RENDER_HOBBY.md, ANALYSIS_REPORT.md (§3 findings, §7 packaging),
render.yaml, deploy/render/Dockerfile, deploy/render/entrypoint.sh,
backend/app.py, backend/services.py, backend/config.py, backend/diagnostics.py.

GROUND RULES
1. Never commit secrets. No DATABASE_URL, JWT_SECRET, DEVICE_API_KEYS, Firebase
   keys, camera URLs with credentials, or certificates in any tracked file or in
   your own output. If you print one by accident, treat it as burned.
2. Do not add torch, ultralytics, rapidocr, onnxruntime or opencv to
   deploy/render/Dockerfile. The slim image is deliberate.
3. Do not weaken security to make something pass: no COOKIE_SECURE=false, no
   debug mode, no DEMO_MODE, no wildcard CORS, no disabling the secret scan.
4. Small commits, one concern each, conventional messages (fix:, feat:, docs:,
   test:). Never rewrite history. Never force-push.
5. Every behaviour change comes with a test that fails before and passes after.
   Do not delete or skip an existing test to get green.
6. If you cannot verify something (e.g. no browser, no Windows), say so
   explicitly in your report instead of guessing.
7. Keep the gate PC working offline. It must still be able to record events with
   no network and upload them later.

PHASE 1 — Verify the Render readiness work that is already in the tree.
Confirm each of these is present and covered by a test; fix only if broken:
  a) /api/stream is bounded and heartbeats. `grep -n "sse_lifetime_seconds" backend/app.py`
     Expect: API_SSE_SECONDS (default 210), a `: keep-alive` comment between
     ticks, a final `event: end`, and an app-level cache so several tabs share
     one compute_stats() call. Route must not contain `while True` with an
     unbounded body.
  b) frontend/js/sse.js reconnects after the stream ends and only falls back to
     10-second polling after 5 consecutive failures. `node scripts/check_live_stream.mjs`
     must exit 0.
  c) deploy/render/entrypoint.sh runs `--workers ${WEB_CONCURRENCY:-1}`,
     `--threads ${GUNICORN_THREADS:-8}`, `--graceful-timeout 30`,
     `--max-requests 800 --max-requests-jitter 80`, binds 0.0.0.0:$PORT, and
     decodes PGSSLROOTCERT_B64 to /tmp/srm-trp-certs/supabase-ca.crt.
  d) render.yaml: plan free, runtime docker, dockerfilePath
     ./deploy/render/Dockerfile, healthCheckPath /api/health, one web service,
     GUNICORN_THREADS=8, API_SSE_SECONDS=210, and the five `sync: false` secrets.
  e) backend/diagnostics.py mirrors every log block to the Python logger (Render
     has no disk, so Logs is the only survivor).
  f) Nothing in the repository says "VisionAI-GateAgent": the shipped binary is
     VisionAI.exe (desktop/gate/VisionAI.spec, desktop/gate/build_gate.ps1).
     desktop/build_windows.ps1 must forward to that build, not build its own.

PHASE 2 — Fix the two correctness blockers from ANALYSIS_REPORT.md §3/§4.

2a. ENT-1 — no duplicate-event suppression (blocker).
    Today: three POSTs of bus 57 / IN / gate 1 within three minutes create three
    rows (services.py ingest_event, ~line 123-139, inserts unconditionally).
    Required: a configurable window, `EVENT_DEBOUNCE_SECONDS`, default 60.
      - If an event with the same (bus_number, direction, gate) exists inside the
        window, do not insert. Return HTTP 200 with
        {"duplicate": true, "event": <the existing event>} instead of 201, and
        record an audit row "event_deduplicated".
      - Outside the window the event is inserted normally (a bus really can go
        out and come back; do not collapse legitimate repeats).
      - A different direction or a different gate is never a duplicate.
      - The behaviour must be identical on SQLite (tests) and PostgreSQL
        (production): do the check and the insert in one transaction, or add a
        partial unique index and handle the conflict (backend/sql/).
    Tests to add: three identical POSTs in 3 s → first 201, next two 200 with
    duplicate=true, and GET /api/events shows exactly one row; a POST 61 s later
    inserts; IN followed by OUT 1 s later inserts both.

2b. DET-2 — arbitrary OCR text becomes a bus number (blocker).
    Today: normalize_plate("hello world") == "HELLO WORLD" (vision.py:758-765)
    and POST /api/events with bus_number "HELLO WORLD" returns 201.
    Required:
      - normalize_plate() returns "" when the result has no digit, is shorter
        than 2 characters, or is longer than 20. Callers must treat "" as
        "unreadable", never as a bus number (check every caller: the scan route,
        the gate agent path, and scripts/scan_image.py).
      - EventCreate.bus_number (backend/schemas.py) rejects a value that contains
        no digit, and stores the normalised form.
      - A scan whose OCR text is unreadable keeps returning 200 with
        bus_number: null and a reason, as it does today for low confidence —
        it must not create an event.
    Tests to add: normalize_plate("hello world") == ""; POST /api/events with
    "HELLO WORLD" → 422 with a message naming bus_number; "KL01AB1234" still
    normalises and stores; the scan fallback path still returns 200.

PHASE 3 — Make the Windows build reproducible (ANALYSIS_REPORT.md BE-4, BE-5).
    - requirements-vision.txt: ultralytics declares opencv-python, which
      overwrites opencv-python-headless and breaks `import cv2` with
      "libGL.so.1: cannot open shared object file". Pin the resolution so a fresh
      install has exactly ONE cv2 distribution, and add a check that fails loudly
      (`python -c "import cv2, importlib.metadata as m;
      print(m.version('opencv-python-headless'))"` plus a guard that
      `importlib.util.find_spec` cannot see a second one). Verify with
      `pip list | grep -i opencv`.
    - torch: the default PyPI wheel is the CUDA build (~7.7 GB installed).
      requirements-desktop.txt and desktop/gate/build_gate.ps1 must install
      torch/torchvision from https://download.pytorch.org/whl/cpu, and the build
      script must assert `python -c "import torch; assert torch.version.cuda is
      None"` before packaging.
    - desktop/gate/build_gate.ps1: keep producing dist\VisionAI\VisionAI.exe and
      the Inno Setup installer; add a final summary print of the .exe size and
      the bundle contents that matter (best.pt, weights\vehicle.pt, frontend/).
      If you cannot run it (no Windows), say so and leave a commented check.

PHASE 4 — Verification gate. Run all of these and paste the real output:
    python -m pytest backend/tests -q
    node scripts/check_frontend.mjs
    node scripts/check_auth_flow.mjs
    node scripts/check_firebase_loader.mjs
    node scripts/check_live_stream.mjs
    python scripts/scan_secrets.py
    python scripts/preflight.py --help      (must not crash)
  Expected: pytest with zero failures (the suite is ~328 passed / 23 skipped
  without the vision extras installed), every node check exit 0, and the secret
  scan reporting no credential patterns. A skipped test is not a passing test —
  list which ones skipped and why.

DELIVERABLE
One summary, in this order:
  1. What you changed, file by file, with the reason, in a table.
  2. The exact commands you ran and their real output (trimmed to the relevant
     lines). No invented output.
  3. What you could not verify in this environment, and why.
  4. Anything still open from ANALYSIS_REPORT.md §3 with severity, so it is not
     silently lost.
Then commit on a branch and open a pull request titled
"Render hobby migration: bounded stream, event deduplication, plate validation,
reproducible Windows build". Do not merge it.
```

---

## Why the prompt is shaped like this

| Instruction | Reason |
| --- | --- |
| "Detection does not run on Render" up front | the most common wrong fix is adding torch to the image, which then fails the health check on 512 MB |
| Phase 1 says *verify, don't redo* | those changes are already on `main`; an agent that rewrites them wastes a review cycle and risks regressing the thread bounds |
| Two blockers only, with exact acceptance tests | an agent asked to "fix everything" rewrites things that already work |
| "A skipped test is not a passing test" | 23 tests skip without the vision extras; without this line a green run reads as full coverage |
| Verification gate lists the six commands | they are the same six CI runs, so a local pass predicts a green PR |
| Deliverable demands real output | it keeps the agent honest about what it actually ran |

## If you want it to fix more

Add one task at a time from [§3 of the audit](../ANALYSIS_REPORT.md), each with
its own acceptance test. The order that costs least: `ENT-2`
(`out_without_in` flag), then `BE-3` (MJPEG proxy holds a thread per viewer), then
`PKG-*` (installer, signing, auto-update). Do not batch them: each one changes
behaviour an operator depends on.
