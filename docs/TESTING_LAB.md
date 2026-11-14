# Test Lab — isolated demo for detection, entries and the whole console

A separate, disposable environment where you can sign in as `admin` / `admin`,
point a webcam at a bus sticker, insert test gate events and click every page
without touching real records.

**It cannot run in production.** `DEMO_MODE` is refused when
`ENVIRONMENT=production`, the `admin` alias is rejected without it, and
`/test-lab` plus `/api/test-lab/*` return `404`. See
[SECURITY_AUDIT.md §3](SECURITY_AUDIT.md#3-demo--test-lab-containment).

---

## 1. Start it (Windows Git Bash)

```bash
cd ~/VISION-AI-SRM-TRP
git checkout main && git pull

python -m venv .venv
source .venv/Scripts/activate        # Git Bash on Windows
pip install -r backend/requirements.txt

python scripts/run_preview.py --port 4400
```

The banner prints everything you need:

```text
 VISION AI - SRM TRP — local preview
 URL          : http://0.0.0.0:4400/
 Database     : in-memory SQLite (disposable)
 Head admin   : head.admin@example.invalid
 Transport    : transport.office@example.invalid
 Password     : <random, printed once>
 Demo login   : admin@demo.local / admin
 DEMO MODE    : ON — Test Lab at /test-lab, no real records.
```

Open <http://localhost:4400>, type `admin` in the email field and `admin` as the
password, then **Sign In**. The top bar shows a gold `DEMO` chip and the sidebar
gains **Test Lab**.

> The preview DB is in-memory: stop the process and everything you inserted is
> gone. That is the point — it is a sandbox, not a second production.
>
> Your `.env` is loaded by the app for the *real* settings, but the preview
> deliberately **ignores `DATABASE_URL` from it**. Before this change, a local
> `.env` pointing at Supabase made the preview refuse to start with
> “Refusing to connect the preview to an external database”. That is gone.
> Pointing the preview at another database now takes two deliberate actions:
> `PREVIEW_DATABASE_URL=…` **and** `ALLOW_REAL_PREVIEW_DB=true`.

Non-demo checks (production-shaped, no demo login):

```bash
python scripts/run_preview.py --port 4400 --no-seed
```

### If the preview will not start

| Message | Meaning | Fix |
| --- | --- | --- |
| `Refusing to use an external database for the preview.` | `PREVIEW_DATABASE_URL` is set | `unset PREVIEW_DATABASE_URL` for the disposable database |
| `Refusing to seed an external database without ALLOW_DEMO_SEED=true` | you opted into an external DB and it would be seeded | add `--no-seed`, or drop `PREVIEW_DATABASE_URL` |
| `Address already in use` | port 4400 is taken | `python scripts/run_preview.py --port 4410` |
| Blank page, no camera | the browser blocks `getUserMedia` on non-HTTPS non-localhost origins | use `http://localhost:4400`, not the machine's LAN IP |

Activate the environment first — the system interpreter has no Flask:

```bash
source .venv/Scripts/activate     # Git Bash on Windows
python scripts/run_preview.py --port 4400
```

### A test that fails only on your machine

`backend/config.py` reads `.env` when it is imported, so a filled-in `.env`
becomes part of the environment for the whole test session. `conftest.py` now
removes every key your `.env` defines for the duration of the run (keeping
`TEST_*` / `ALLOW_TEST_*`), so the suite gives the same result on your laptop as
in CI. A real example: a local `LEGACY_PASSWORD_LOGIN_ENABLED=true` — the
pre-Firebase default — made
`test_config.py::test_production_defaults_cookie_secure_to_true` fail with
`Password sign-in must be off in production`, although the code was correct.

`test_local_dotenv_cannot_change_suite_defaults` guards this: it skips when
there is no `.env` (CI), and fails loudly if a `.env` key leaks in again.

---

## 2. What to test, in order

| # | Where | Do this | Expect |
| --- | --- | --- | --- |
| 1 | Login | `admin` / `admin` | lands on `/dashboard`, gold `DEMO` chip |
| 2 | Sign-in guard | wrong password three times | error message, `429` after 5 attempts/minute |
| 3 | Dashboard | stat cards, charts, live clock | numbers change after step 6 |
| 4 | **Test Lab → System checks** | press **Re-run checks** | rows for session, database, bus/driver/event counts, detection, demo |
| 5 | **Test Lab → Detection bench** | allow the webcam, press **Scan plate** | either a read plate or a clear "detector unavailable" reason (see §3) |
| 6 | **Test Lab → Post a test entry** | change bus/direction/gate, submit | “Inserted …” + the event count on the next checks run goes up |
| 7 | Live Logs | filter by that bus, direction and gate | the `test-lab` row appears with `source: test-lab` |
| 8 | Exports | CSV / Excel on Live Logs | the file downloads and contains the row |
| 9 | Search | search the bus number | result modal lists the bus and driver |
| 10 | Theme | toggle sun/moon in the top bar | dark amethyst theme persists after reload |
| 11 | Roles | sign out, sign in as `transport.office@example.invalid` | no Dashboard/Logs/Audit, `manage` allowed, `/test-lab` 404s |
| 12 | Mobile | DevTools device toolbar | bottom nav, search overlay, tables scroll |

Every row above maps to a backend route that a test already covers
(`197 passed, 5 skipped`, or `198 passed, 4 skipped` once your own `.env`
exists), so a failure here is a UI/runtime problem, not an unknown.

### If Firebase is configured in your `.env`

The bench ignores it on purpose. `FIREBASE_PROJECT_ID` normally makes the login
page sign in through Firebase, but the demo credentials are not Firebase
accounts — every attempt came back `403` from `POST /api/auth/firebase` and the
Test Lab stayed unreachable. In demo mode:

```text
GET /api/auth/config   {"mode":"password","firebase":{"enabled":false,...},"demo_mode":true}
POST /api/auth/login   {"email":"admin","password":"admin"} → 200, admin@demo.local
POST /api/auth/firebase  → 503 "Firebase sign-in is not used in demo mode."
```

The login form also relaxes two browser constraints that reject `admin` /
`admin`: the address field becomes `type="text"` (a bare username is not an
email) and the password minimum drops to one character. Both changes exist only
when the page is told `demo_mode: true`; the production login path is byte for
byte what it was, and the server still validates every credential.

With `DEMO_MODE` off, `GET /api/auth/config` still returns `"mode":"firebase"`.

---

## 3. Detection: webcam now, IP cameras later

**Webcam (works today).** The Test Lab and the dashboard both render a
“this device” tile and post a captured JPEG to `POST /api/detection/scan` with
the session cookie. No device key is involved — it was removed from the browser
in this change.

The detector needs **torch, ultralytics, OpenCV, PIL and an OCR engine** plus
`best.pt`. Those packages are deliberately **not** in `backend/requirements.txt`
and not in the free Docker image (512 MB RAM), so on the free tier the scan
answers `503` and the Test Lab prints exactly why:

```json
{"error": "Detection is unavailable: torch is not installed"}
```

Run it locally with the vision extras. The **Detector setup** card in the Test
Lab lists each component, marks the ones that are already there, and hands you
the exact command for the missing ones (plus a copy button):

```bash
source .venv/Scripts/activate          # Git Bash on Windows
python -m pip install torch==2.9.1 torchvision==0.24.1 --index-url https://download.pytorch.org/whl/cpu
python -m pip install ultralytics==8.4.20
python -m pip install opencv-python-headless==4.10.0.84
python -m pip install "Pillow>=10.0.0"
python -m pip install rapidocr-onnxruntime==1.4.4
```

or in one line, if you have the bandwidth:

```bash
python -m pip install -r backend/requirements-vision.txt
```

Then press **Re-check after installing** in the Test Lab — no restart needed for
`Pillow`/`OpenCV`/OCR, because they are imported lazily on the next scan:

```bash
python scripts/run_preview.py --port 4400
curl -s http://localhost:4400/api/detection/status | head -c 200   # "available": true
```

If a half-finished install left you with only some of the packages, the card
still works: it reports `Pillow is not installed` next to `torch: installed`,
instead of the single sentence that made this confusing.

**IP / NVR camera (later, no code change).** Set `CAMERA_STREAM_URLS` to a JSON
object and the same tiles switch source:

```bash
export CAMERA_STREAM_URLS='{
  "gate-1-entry": {"type": "mjpeg", "url": "http://10.0.0.11/video.mjpg", "label": "Gate 1 Entry"},
  "gate-2-exit":  {"type": "hls",   "url": "http://10.0.0.12/live/index.m3u8", "label": "Gate 2 Exit"}
}'
```

- `mjpeg` is proxied by the backend (`/api/stream/<camera_id>`), so the camera can
  stay on a private LAN.
- `hls` plays directly in the browser — the camera or a MediaMTX gateway must
  serve it over HTTP**S** (a mixed-content HTTPS page cannot load plain HTTP).
- `rtsp` cannot play in a browser; put MediaMTX or FFmpeg in front and point the
  entry at the transcoded HLS/MJPEG URL. The UI explains this on the tile.
- Credentials must not be embedded in the URL — `Config` rejects `user:pass@`
  on purpose.

---

## 4. Model: what "prepare the model" means here

The shipped `best.pt` is a **bus-sticker detector**, not a number-plate reader;
OCR reads the sticker text. Nothing in this repository can *train* a model: the
gate images needed for training are personal data and are deliberately absent
(`docs/PRIVACY.md`, `docs/DETECTION.md`).

What you can do today, in order:

1. **Measure before training.** Run the detector over a folder of frames you are
   allowed to keep locally and compare the OCR output with the true bus number.
   That gives a real precision/recall baseline instead of a guess.
2. **Collect with consent.** Gate frames containing drivers and plates are
   personal data: keep them out of Git, out of chat, and on a machine you
   control. Only annotate what the model needs (the sticker region).
3. **Train where the GPU is.** Fine-tuning YOLO weights needs a GPU and a
   labelled dataset; a laptop CPU run is not practical. Once you have weights,
   replace `best.pt`, keep a model card (dataset, date, metrics, licence) and
   re-run `/api/detection/status`.
4. **Respect the licence.** The checkpoint metadata cites Ultralytics
   AGPL-3.0. Get written model/dataset rights before any public or commercial
   deployment — see `docs/DETECTION.md`.

A small labelled set (a few hundred sticker crops from your own gates) is enough
to fine-tune the OCR step; the detector itself usually needs more.

---

## 5. Design

The Test Lab is the first page using the **Glass3D** surface (`.glass3d` in
`frontend/assets/theme.css`): layered shadows, a 32 px backdrop blur, a subtle
inline-SVG noise texture, and inset highlights. It is theme-aware, uses no
remote assets (CSP-safe, works offline), and degrades to a flat card when
`backdrop-filter` is unsupported or the user asks for reduced transparency.

To roll it out to another surface, add the class in markup:

```html
<section class="card glass3d">…</section>
```

Do **not** put it on a component that already uses `::before`/`::after`
(`.stat-card`, `.login-container`) — the pseudo-elements would collide.

### Layout: why `layout.css` exists

`frontend/assets/layout.css` is loaded last on every page (before `login.css` on
the sign-in page) and owns the shell geometry:

| Problem it removes | Cause it replaces |
| --- | --- |
| The wheel did nothing over the sidebar, top bar or page gutter | `body { height: 100vh; overflow: hidden }` scrolled a nested `.main-content` box |
| The last card hid under the phone's browser chrome | `100vh` instead of `100dvh`, no safe-area padding |
| The whole page could be dragged sideways by a wide table | overflow on `body` instead of on `.table-container` |
| Four stat cards squeezed to ~150 px on a laptop | fixed `repeat(4, 1fr)` grid |
| A camera tile that jumped while the stream negotiated | no `aspect-ratio` on `.camera-container` |

The document now scrolls natively, the sidebar is `position: sticky` on desktop
and an off-canvas drawer below 1024 px, the content column is capped at 1560 px
and centred, and the grids are `auto-fit`/`minmax` instead of fixed counts.

Check it at four widths (DevTools device toolbar is enough):

| Width | Expect |
| --- | --- |
| 1920 | content capped and centred; sidebar fixed, page scrolls; no horizontal scrollbar |
| 1366 | four stat tiles per row; tables fit without horizontal scroll |
| 1024 → 769 | sidebar becomes a drawer behind the ☰ button; backdrop closes it |
| 390 | two stat tiles per row; filters stack; tables scroll inside their card; nothing cut off at the bottom |

---

## 6. Cleanup

```bash
# stop the preview with Ctrl+C; the in-memory database disappears with it
git status --short      # nothing should be dirty
```

If you ever pointed a demo run at a real database (`ALLOW_REAL_PREVIEW_DB`
+ `ALLOW_DEMO_SEED`), delete the seeded rows:

```sql
DELETE FROM transport_portal.events  WHERE demo IS TRUE;
DELETE FROM transport_portal.buses   WHERE demo IS TRUE;
DELETE FROM transport_portal.drivers WHERE demo IS TRUE;
DELETE FROM transport_portal.users   WHERE demo_user IS TRUE;
```

That is also why the preview refuses an external `DATABASE_URL` unless you pass
both flags by hand.
