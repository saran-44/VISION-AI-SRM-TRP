# Gate PC readiness audit

Date: 2026-11-14 · Branch: `arena/dee3f6ec-vision-ai-srm-trp` · Base: `f9a438f`

What this document is: an honest split between **what was executed and observed**,
**what only the Windows build machine can execute**, and **what only the physical
gate can prove**. Nothing below is marked ready because it looks right.

---

## Verdict

| Area | State |
|---|---|
| Portal on a Windows-style deployment (waitress, file database, localhost) | **Verified**, ran end to end here |
| Local database (`ENVIRONMENT=gate`, SQLite file, WAL, persistence) | **Verified** |
| Camera frame source (HTTP snapshot → JPEG → detector) | **Verified** against a real HTTP endpoint |
| RTSP / USB capture | **Code complete, not hardware-tested** (no camera on this machine) |
| Preflight (13 checks, exit codes, JSON) | **Verified** |
| Setup wizard (config + admin account) | **Verified** (non-interactive path) |
| Backup (`--backup`, live database, integrity) | **Verified** |
| PyInstaller bundle | **Not built here** — Linux sandbox, cannot produce a Windows PE |
| Inno Setup installer | **Not compiled here** — same reason |
| Tray icon, hidden console, autostart | **Not executed here** — no Windows desktop |
| Detector inference (torch, `best.pt`) | **Not executed here** — no torch in the sandbox; verified earlier on the laptop (2/2 full frames, 0.90–0.93) |
| Cloud sync to Supabase (stage 2) | **Not built** — deliberate scope decision |

---

## 1. Executed and observed (this machine)

Environment: Linux, Python 3.11 venv with `backend/requirements.txt` + Pillow,
numpy, waitress 3.0.2, python-dotenv. No torch, no GPU, no camera hardware.

### 1.1 The portal runs on the gate's real stack

`desktop/gate/launcher.py` started under waitress and served the real frontend
from a real file database:

```
GET  /api/health               200  {"status":"ok","service":"srm-trp-transport",...}
GET  /                         200  3458 B (the portal shell)
POST /api/auth/login           200  user head_admin, expires in 15 min
GET  /api/auth/me              200  same user
GET  /api/detection/status     200  model_present true, best.pt, sticker class 1 "sticker"
```

### 1.2 The camera path, with a stand-in camera

A local HTTP server served a 1280×960 JPEG (the shape a camera snapshot has):

```
GET  /api/camera/status        200  {"configured":true,"kind":"http","source":"http://…/snapshot.jpg"}
GET  /api/camera/snapshot      200  image/jpeg, X-Frame-Size: 1280x960, Cache-Control: no-store
GET  /api/camera/snapshot      401  anonymous (device key or head_admin required)
GET  /api/camera/snapshot      400  code=camera_not_configured when CAMERA_SOURCE is blank
POST /api/detection/scan       503  {"capture":true} reached the detector: the frame was fetched,
                                     decoded and passed in, and only torch was missing
```

The 503 body is gate-aware: `code=vision_unavailable`,
"…Open VisionAI.exe --check for the failing component", no mention of Render —
because on the gate PC this *is* the detector (`backend/app.py`).

### 1.3 Setup, preflight, backup

```
launcher.py --setup (email, password, camera, port)
  → Wrote C:\ProgramData-like gate.env (fresh 48-char JWT_SECRET)
  → Created the head administrator (argon2 hash)
  → Created data/gate.db

scripts/preflight.py --env-file gate.env   (16 checks)
  PASS configuration / environment / data folder / disk / database /
       database write / frontend / models / port
  FAIL ocr        (no torch in this sandbox — the bundle ships it)
  WARN camera     (none configured in that run)
  SKIP detector   (no --deep)
  exit 1          → "NOT READY: 1 failed, 1 warning(s)"

launcher.py --backup /tmp/bk   (against the *running* database)
  → gate-20261114-172414.db, 56 KB, PRAGMA integrity_check = ok
```

### 1.4 Tests

```
287 passed, 5 skipped        (was 257 + 30 new)
```

New: `backend/tests/test_gate_install.py` (30) covers the gate database rules,
the camera source, both camera routes, the scan-capture flow, the gate-specific
503 wording and the preflight. `backend/tests/test_frame_report.py` (4) covers
the frame reporter.

### 1.5 Bugs found and fixed on the way

| Bug | Evidence | Fix |
|---|---|---|
| Every model-load failure was reported as "Detection model not found at …" — including "ultralytics is not installed" | `backend/vision.py` `load_model()` caught `StageNotConfigured` and rebuilt the message; reproduced by scanning with no torch: the file was present and the message said it was not | the real reason is propagated (`model_missing` / `not_installed` / `load_failed`) |
| The gate PC was told to "run VisionAI-GateAgent.exe on the gate computer" — about itself | 503 body from `/api/detection/scan` on a gate config | gate branch: `vision_unavailable`, points at `--check` |
| A wizard stopped by a short password left a half-install that the preflight called READY — no `gate.env`, no account, nobody able to sign in | reproduced on the gate laptop: `--setup` aborted, `--check` printed `READY: 0 failed` | two new checks (`gate config`, `administrator`) fail that state; the wizard now retries the password three times and says nothing was written |
| A windowed PyInstaller build would have made `--setup` and `--check` unusable (no stdio) | `desktop/gate/VisionAI.spec` | console program + `hide_console()` for normal runs |

---

## 2. Steps only the Windows build machine can run

Each of these is scripted; none needs a decision at the keyboard.

```powershell
powershell -ExecutionPolicy Bypass -File desktop\gate\build_gate.ps1
```

| Step | Expected |
|---|---|
| CPU torch + `requirements-desktop.txt` install | no CUDA packages pulled |
| `pytest -q` inside the build venv | green (fails the build otherwise) |
| PyInstaller `dist\VisionAI\` | 700 MB – 1.5 GB, 10–20 min |
| `dist\VisionAI\VisionAI.exe --check --json` | prints a report with `"ready"` |
| the built exe answers `/api/health` + `/` on a random port | portal serves from the bundle |
| ISCC → `dist\installer\VisionAI-Setup.exe` | installer produced |

If the bundle starts but `--check` reports `ocr: no OCR engine`, the vision
extras were not collected: check the `WARNING: could not collect …` lines the
spec prints during the build.

---

## 3. Acceptance checklist at the gate (operator, ~15 minutes)

Tick every line before calling the installation done.

- [ ] `VisionAI.exe --check` prints **READY: 0 failed**
- [ ] The `camera` line shows the **full-resolution** frame (3 MP or more) and
      `sharpness` **above 150**
- [ ] `VisionAI.exe --check --deep` shows `detector … model best.pt` with a time
      in ms — no exception
- [ ] `http://127.0.0.1:8080/` opens and the login page appears
- [ ] The administrator from `--setup` can sign in
- [ ] Dashboard → **Scan gate camera** (the button only appears when
      `CAMERA_SOURCE` is set) returns a number (`NN (0.NN, via sticker)`), not
      "No plate detected". This button is the high-end-camera path: the gate PC
      grabs the frame itself, no browser camera involved
- [ ] The event appears in Events/logs with the right gate name and time
- [ ] `VisionAI.exe --backup` writes a file, and it opens (`sqlite3` or the
      portal's own restore copy)
- [ ] The tray icon is present; Quit stops the portal; the Start Menu shortcut
      starts it again
- [ ] After a reboot the portal starts by itself (if autostart was ticked)
- [ ] Ten real scans in a row: note **how many produce a number** and **which
      stage answered**. That number is the only real recall figure this project
      has, and it goes in `docs/DETECTION.md`

---

## 4. Known gaps, ranked

| # | Gap | Impact | When |
|---|---|---|---|
| 1 | **No cloud sync.** The gate database is authoritative and local | Events live on one PC; no campus-wide view until stage 2 | Stage 2, agreed |
| 2 | **RTSP / USB capture untested** against real hardware | May need a URL or codec fix on the day | Verify with `--check` before the gate opens |
| 3 | **Installer is unsigned** | SmartScreen warning on first install | Needs a certificate (purchase) |
| 4 | **No TLS** and loopback-only binding | Fine for this install; blocks LAN access until added | Only if LAN access is requested |
| 5 | **Single local account model** — one head_admin created by setup | No per-operator accounts on the gate PC | Add users through the portal UI as needed |
| 6 | **Manual backup schedule** — `--backup` exists, the scheduled task is a documented one-liner | A PC that dies loses everything since the last copy | Set the daily task on install day |
| 7 | **CPU-only inference** (3–5 s per scan) | Fine for a gate queue; not for a highway | Accept, or a GPU later |
| 8 | **Detector accuracy on the gate's own camera** — proven 2/2 on two 12 MP photos | Not yet a measured recall figure | The checklist's last line produces it |

---

## 5. Security posture of this install

- Binds **127.0.0.1**; nothing on the campus LAN can reach it.
- `ENVIRONMENT=gate` keeps the production secret rules: 32+ char `JWT_SECRET`
  generated per install, `DEMO_MODE` refused, debug refused, `TRUST_PROXY_HEADERS`
  refused (`backend/config.py`).
- Password sign-in is allowed **only** because this is a single machine with no
  Firebase project; `--setup` refuses passwords under 12 characters and stores
  argon2 hashes only.
- Camera passwords never reach the logs, an audit row, or a response header —
  every path goes through `mask_source()` (`backend/frame_source.py`), which has
  its own test.
- `/api/camera/snapshot` requires the device key or `head_admin`, and a
  `?source=` override is refused unless the request comes from loopback.
- The audit log records `detection_scan`, `camera_snapshot_failed` and
  `detection_scan_failed` rows, so a broken camera leaves a trail.
- `C:\ProgramData\VisionAI\gate.env` holds the signing secret and is written
  with owner-only permissions where the filesystem allows it.
- Uninstalling deliberately **keeps** the database and logs and says so.

---

## 6. Reproduce this audit

```bash
# 1. the gate database and the camera path
python -m pytest backend/tests/test_gate_install.py -q

# 2. a full installation, without Windows
export VISION_DATA_DIR=/tmp/visionai
python desktop/gate/launcher.py --setup        # interactive
python scripts/preflight.py --env-file /tmp/visionai/gate.env
python desktop/gate/launcher.py --no-tray --no-browser
curl -s http://127.0.0.1:8080/api/health

# 3. the whole suite
python -m pytest -q
```
