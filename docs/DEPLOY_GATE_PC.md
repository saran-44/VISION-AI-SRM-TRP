# Gate PC install — the whole portal as one executable

This is the runbook for putting VISION AI - SRM TRP on the gate computer: the
portal, the detector and the camera in one program, with its own database, so a
scan is recorded whether or not the campus link is up.

| | |
|---|---|
| Installed program | `C:\Program Files\VisionAI\VisionAI.exe` |
| Configuration | `C:\ProgramData\VisionAI\gate.env` (secret, written by `--setup`) |
| Database | `C:\ProgramData\VisionAI\data\gate.db` (SQLite, WAL) |
| Logs | `C:\ProgramData\VisionAI\logs\portal.log` (5 × 2 MB, rotated) |
| Backups | `C:\ProgramData\VisionAI\backups\` |
| Listens on | `http://127.0.0.1:8080` — this PC only, by design |

Why not the cloud portal: `deploy/render/entrypoint.sh` runs gunicorn, which
needs `fork()` and does not exist on Windows. The gate bundle runs **waitress**
instead (`requirements-desktop.txt`). The database is a SQLite *file*, which
`ENVIRONMENT=gate` is the only mode allowed to use (`backend/config.py`
`validate()`, `backend/db.py` `create_local_sqlite_engine`).

---

## 1. Build it (on the laptop, once per release)

Requires Windows, Python 3.11, and Inno Setup 6 for the installer
(`winget install --id JRSoftware.InnoSetup`).

```bash
cd ~/VISION-AI-SRM-TRP
git pull --ff-only
powershell -ExecutionPolicy Bypass -File desktop/gate/build_gate.ps1
```

Six steps, each failing loudly:

1. `.venv-gate` + **CPU** torch (`+https://download.pytorch.org/whl/cpu`). The
   default PyPI wheel drags in ~3 GB of CUDA libraries a gate PC cannot use.
2. Checkpoints: `best.pt`, `anpr_best.pt`, and `weights/vehicle.pt` (fetched if
   missing).
3. The test suite — packaging a failing tree is not a thing this script does.
4. PyInstaller `onedir` → `dist\VisionAI\` (expect **700 MB – 1.5 GB** and
   10–20 minutes; `onedir`, not `onefile`, because a 1 GB single file is
   unpacked to a temp folder on every start).
5. **Smoke test of the built executable**: `VisionAI.exe --check --json` must
   print a report, then a real server instance must answer `/api/health` and
   serve `/` on 8080. A build that starts but does not answer is not a build.
6. Inno Setup → `dist\installer\VisionAI-Setup.exe`.

Copy either the installer or the portable `dist\VisionAI` folder to the gate PC.

---

## 2. First run at the gate

Run `VisionAI-Setup.exe` (admin). The installer creates the Program Files
folder, the `C:\ProgramData\VisionAI` data folders, a Start Menu group, and
optionally a desktop icon and an autostart entry (`--no-browser`, so the gate
desk does not get a browser window at every boot).

The post-install step opens **First-time setup**, which asks for:

| Prompt | What to enter |
|---|---|
| Administrator email | e.g. `transport.office@trp.srmtrichy.edu.in` |
| Administrator password | 12+ characters, typed twice. Three attempts before the wizard stops; nothing is written until the password is accepted |
| Camera source | see §3 — blank means "browser camera only" |
| Portal port | Enter for 8080 |

It writes `gate.env` with a fresh `JWT_SECRET`, creates `gate.db`, and creates
that one `head_admin` account. It never prints the password and never stores it
in plain text (argon2 hash, `backend/auth.py`).

If the wizard is closed, run **First-time setup** from the Start Menu later.

---

## 3. Camera

One setting, three shapes. Get the **snapshot** URL from the camera's own web
page (not a video stream URL):

| Camera | Typical URL |
|---|---|
| Hikvision / most OEM | `http://user:pass@192.168.1.64/ISAPI/Streaming/channels/101/picture` |
| Axis | `http://user:pass@192.168.1.64/axis-cgi/jpg/image.cgi` |
| Dahua | `http://user:pass@192.168.1.64/cgi-bin/snapshot.cgi` |
| RTSP stream | `rtsp://user:pass@192.168.1.64:554/Streaming/Channels/101` |
| USB / UVC webcam | `usb:0` |

Put it in `C:\ProgramData\VisionAI\gate.env`:

```ini
CAMERA_SOURCE=http://user:pass@192.168.1.64/ISAPI/Streaming/channels/101/picture
CAMERA_TIMEOUT=8
```

**Resolution matters more than brand.** The sticker detector was validated on
full gate frames where the sticker is ~140 px wide (`docs/DETECTION.md`). Use the
camera's **full-resolution** snapshot (3–12 MP), not a thumbnail stream. A 720p
frame only works when the sticker is at least ~45 px wide in it.

Verify the camera before trusting it:

```bash
"C:\Program Files\VisionAI\VisionAI.exe" --check
```

The `camera` line reports the shape, the frame size and the **sharpness**. Under
60 the frame is soft and the detector will find nothing, no matter the
threshold — clean the lens, check focus, or drop to a smaller sensor mode.

---

## 4. Check the installation

```bash
"C:\Program Files\VisionAI\VisionAI.exe" --check --deep
```

Fifteen checks. `--deep` adds a real inference pass (loads torch, ~10 s). Exit
code is 0 only when nothing failed. Expected on a good install:

```
VisionAI gate preflight — 15 checks
  PASS  configuration    loaded (gate)
  PASS  gate config      C:\ProgramData\VisionAI\gate.env
  PASS  environment      ENVIRONMENT=gate, sqlite storage, demo off, password login
  PASS  data folder      C:\ProgramData\VisionAI is writable
  PASS  disk             118.4 GB free on the data drive
  PASS  database         schema v1, 0 bus row(s), sqlite at C:/ProgramData/VisionAI/data/gate.db
  PASS  database write   inserted and removed a probe row
  PASS  administrator    1 active head_admin account(s)
  PASS  frontend         9 page(s), 22 script(s)
  PASS  models           best.pt 5594 KB, anpr_best.pt 5630 KB
  PASS  ocr              rapidocr is available
  PASS  detector         one 1280×720 pass in 3299 ms at 1280px, model best.pt
  PASS  camera           http at http://192.168.1.64/... → 2560×1440 in 180 ms, sharpness 412
  PASS  port             127.0.0.1:8080 is free
  SKIP  clock            no API_URL configured (this gate may be stand-alone)

READY: 0 failed, 0 warning(s)
```

`database write` is a real insert and delete. A read-only folder or a full disk
passes every other check and fails the first scan of the day.

`gate config` and `administrator` exist because of a real half-install: a wizard
that stopped on a short password still left a working schema on disk, and every
other check passed while **nobody could sign in**. Both now fail loudly, with the
fix in the same line.

---

## 5. Prove the scan path end to end

1. Start **VISION AI - SRM TRP** from the Start Menu (or it is already running —
   the tray icon shows it).
2. Open `http://127.0.0.1:8080/`, sign in with the account from §2.
3. Go to the dashboard, point the gate camera at a bus, press **Scan plate**.
4. Expect a real sentence: `57 (0.93, via sticker)`, not "No plate detected".

The same flow without a browser, from the PC itself:

```bash
curl -s -b cookies -X POST http://127.0.0.1:8080/api/auth/login ^
  -H "Content-Type: application/json" ^
  -d "{\"email\":\"you@example.edu\",\"password\":\"...\"}" -c cookies
curl -s -b cookies "http://127.0.0.1:8080/api/camera/status"
curl -s -b cookies -o frame.jpg "http://127.0.0.1:8080/api/camera/snapshot"
curl -s -b cookies -X POST http://127.0.0.1:8080/api/detection/scan ^
  -H "Content-Type: application/json" -d "{\"capture\": true}"
```

`{"capture": true}` grabs the frame from the gate camera and scans it in one
call — that is the whole high-end-camera path without a browser.
The `X-Camera-Source` header on the snapshot response never contains the camera
password (`backend/frame_source.py` `mask_source`).

---

## 6. Daily operation

| Task | How |
|---|---|
| Start | Start Menu, or it starts with Windows if that task was ticked |
| Stop | Right-click the tray icon → Quit |
| Logs | `C:\ProgramData\VisionAI\logs\portal.log` |
| Data folder | Start Menu → Data folder |
| Backup | `VisionAI.exe --backup` (safe while running: SQLite backup API) |
| Check | `VisionAI.exe --check` |

**Backups.** `--backup` copies the live database with SQLite's own backup API —
copying `gate.db` by hand while the portal runs can miss the last transactions.
It keeps the newest 30 copies. Schedule it daily:

```powershell
schtasks /Create /TN "VisionAI backup" /SC DAILY /ST 22:00 /RU SYSTEM ^
  /TR "\"C:\Program Files\VisionAI\VisionAI.exe\" --backup"
```

Copy `C:\ProgramData\VisionAI\backups` to a second disk or a network share; a
backup on the same disk is not a backup.

**Upgrade.** Close the portal, run the new `VisionAI-Setup.exe` over the old
install, run `--check`. The program folder is replaced; `C:\ProgramData\
VisionAI` (database, logs, backups) is not touched, and the uninstaller refuses
to delete it on purpose.

---

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `--check` says `ocr: no OCR engine` | vision extras not in the bundle | rebuild; the bundle includes rapidocr, a hand-made venv may not |
| `camera: HTTP 401` | camera password or account | use the camera's own web page to confirm a snapshot URL works in a browser first |
| `camera: answered text/html, not an image` | snapshot path wrong, or the camera wants a login | check the path per §3 |
| `camera: could not open the RTSP stream` but the network answers | H.265-only stream | switch the camera's sub/main stream to H.264 |
| `sharpness` under 60 | soft frame: focus, dirt, or a 720p substream | full-resolution snapshot, clean lens |
| `no box at all` | sticker too small, or the frame is soft | read the `frame` line: `sharpness` under 60 → clean the lens/let it focus; otherwise move closer or set `VISION_TILES=auto` (costs 4× the sticker stage) |
| Failed scans leave no trace to inspect | `VISION_SAVE_FAILURES=false` | unset it: every scan that reads nothing writes `C:\ProgramData\VisionAI\failed-frames\fail-*.jpg` (newest 40), readable with `python scripts/frame_report.py` |
| `port: already in use` | the portal is already running | open `http://127.0.0.1:8080/`; a second start reuses the running instance |
| Browser says "site can't be reached" | the portal is not running | tray icon → Open portal, or Start Menu → the app |
| `--setup` said "Use at least 12 characters" | the wizard rejects short passwords: it can create a `head_admin` that edits every record | run `--setup` again; it asks three times before stopping, and writes nothing until a password is accepted |
| Login says "Password sign-in is disabled" | `LEGACY_PASSWORD_LOGIN_ENABLED=false` in `gate.env` | set it back to `true` — the gate PC has no Firebase project |

---

## 8. What this install does **not** do yet

- **Cloud sync.** The gate database is local and authoritative. Pushing events
  to Supabase/Render and reconciling ids is stage 2 of the "both" decision and
  is not built. Until then the gate PC is the only place its events exist.
- **LAN access.** The portal binds `127.0.0.1`. Other devices on the campus
  network cannot open it; that was a deliberate choice for this install. A
  LAN-exposed variant needs `--host 0.0.0.0`, `CORS_ALLOWED_ORIGINS`, a firewall
  rule and TLS before it is safe.
- **HTTPS.** Not needed on loopback; required the moment you expose it.
- **Code signing.** The installer is unsigned, so Windows SmartScreen will warn
  the first time. A certificate is a purchase, not a build step.
