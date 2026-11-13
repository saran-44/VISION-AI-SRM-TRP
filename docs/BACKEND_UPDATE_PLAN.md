# Backend Update Plan: SRM TRP Transport

- **Reviewed repository / commit:** `saran-44/VISION-AI-SRM-TRP` (`main` at `46f293ef6b1dc7f604fb65391ee409165569868b`)
- **Review date:** 2026-11-13
- **Baseline test result:**
  - `MONGO_URI=mongomock://t JWT_SECRET=test-secret-value-with-at-least-32-chars python -m pytest -q` (run in an isolated `/tmp/audit-venv` with `backend/requirements.txt`, excluding optional `backend/requirements-vision.txt`): **172 passed** (147 `def test_` functions across 13 test modules).
  - `python -m compileall -q backend`: **passed (exit 0)**.
  - `python scripts/scan_secrets.py`: **passed (exit 0)**.
  - *Note:* `backend/requirements-vision.txt` (`torch`, `ultralytics`, `opencv-python-headless`, `Pillow`, `rapidocr-onnxruntime`) was not installed in the sandbox, so live YOLO/OCR execution was not run.

---

## 1. Executive summary

The backend has solid foundations—strict Pydantic v2 schemas, Argon2id hashing, Firebase RS256 JWKS verification with a MongoDB allowlist, lazy vision imports, and 172 passing unit tests—but it has severe concurrency, memory, and edge-proxy gaps for Cloud Run + Firebase Hosting.
**Top 5 risks:** (1) `GET /api/stream` SSE loops hold gunicorn `gthread` threads indefinitely on a 2×4 pool, starving `/api/health` and `/api/events`; (2) `compute_stats()` loads the entire `events` collection into Python on every call and every 10 s SSE tick; (3) missing `ProxyFix` + per-worker `memory://` rate limiting breaks IP limits and audit IP logging behind Hosting/Cloud Run; (4) `deploy/Dockerfile` runs as `root` with `--workers 2`, doubling PyTorch/YOLO/OCR memory inside a 2 GiB / 1 vCPU container; (5) `ingest_event()` lacks deduplication/idempotency, and `/api/detection/scan` lacks image decompression-bomb caps, rate limits, and 400 error mapping.
**Fix first (Phase A):** bound SSE concurrency/lifetime (`CHG-01`), replace full-collection `compute_stats()` reads (`CHG-02`), wire `ProxyFix` + MongoDB-backed rate limits (`CHG-03`), harden the Dockerfile to non-root + 1 worker × 8 threads (`CHG-04`), and harden image decoding/ingestion deduplication (`CHG-05`, `CHG-06`).

---

## 2. Architecture as found

```text
  Browser Console ──HTTPS──▶ Firebase Hosting (static assets + /api/** & page rewrites)
                                        │ (forwards __session cookie only; 60s request cap)
                                        ▼
  Gate Cameras / Edge ──HTTPS──▶ Cloud Run: gunicorn (--workers 2 --threads 4 --timeout 180)
  (X-Device-Key)                        │
                                        ▼
                              Flask App (backend/app.py::create_app, 38 routes)
                                ├── Auth/RBAC: auth.py + firebase_auth.py + access.py
                                ├── Schemas:   schemas.py (Pydantic v2 strict models)
                                ├── Services:  services.py (ingest, stats, analytics, export, audit)
                                ├── Vision:    vision.py (lazy YOLOv10n best.pt + RapidOCR/Tesseract/EasyOCR)
                                └── Data:      db.py ──VPC/Cloud NAT──▶ MongoDB Atlas
                                                 (users, buses, drivers, events, audit_logs)
```

### Module responsibilities
- `backend/config.py`: `Config.from_env()` & `Config.validate()` load `.env`, parse `CORS_ALLOWED_ORIGINS`, `CAMERA_STREAM_URLS`, and Firebase settings.
- `backend/db.py`: `create_mongo_client()` (`mongomock://` or `MongoClient`), `ensure_indexes()` (12 startup indexes), `get_database_for_startup()` (120 s retry loop in production for Direct VPC/Cloud NAT cold starts), and `public_doc()` / UTC helpers.
- `backend/auth.py`: Argon2id hashing, HS256 JWT (`__session` cookie, `jti` issued), RBAC decorators (`require_roles`, `require_page_roles`, `require_device_key`, `require_device_key_or_roles`).
- `backend/firebase_auth.py` & `backend/access.py`: Google JWKS RS256 ID-token verification (`PyJWKClient`), `email_verified` gate, MongoDB `users` allowlist check, optional `transport_portal_approved_email` auto-provisioning, and `firebase_uid` binding.
- `backend/schemas.py`: `StrictModel` (`extra="forbid"`, control-char stripping, bus-number uppercase normalization, future-timestamp guard) for all JSON bodies and query strings.
- `backend/services.py`: `ingest_event()` + `compute_flag_reasons()`, `compute_stats()`, `compute_analytics()`, `events_for_export()`, `csv_bytes()`/`xlsx_bytes()` (formula-injection escaped), `record_audit()`, `camera_config()`.
- `backend/vision.py`: Lazy-loaded YOLOv10n (`best.pt`: `0=red circle`, `1=sticker`) + crop OCR (`rapidocr` -> `tesseract` -> `easyocr`) + `normalize_plate()`.
- `backend/app.py`: Single 883-line factory containing all page routes, API endpoints, Limiter, CORS, security headers, SSE, MJPEG proxy, and error handlers.
- `backend/wsgi.py`, `backend/manage_access.py`, `backend/seed_demo.py`, `backend/detection_client.py`: WSGI entrypoint, access-list CLI, opt-in demo seeder, and reference device CLI.

### Request / data flows
- **Event ingestion (`POST /api/events`):** `require_device_key` -> `validate(EventCreate)` -> `ingest_event()` checks `db.buses` (`unregistered_plate`), `confidence < 0.75` (`low_ocr_confidence`), and latest unmatched `prior_in` (`long_overstay`) -> `db.events.insert_one()` -> `record_audit()` (full event stored in `audit_logs`) -> `201 {"event": ...}`.
- **Sticker detection (`POST /api/detection/scan`):** `require_device_key_or_roles("head_admin")` -> reads multipart `image` or JSON base64 `image` (<= 1 MB global limit) -> `decode_image()` -> `detect()` (lazy `load_model()`, `model.predict()`, crops up to `VISION_MAX_CROPS=8`, runs `read_text()`, `normalize_plate()`) -> `best_candidate()` -> `record_audit()` (full `detection` dict logged as `device-client`) -> `200` (does **not** create an event).

---

## 3. Hypothesis check

| ID | Verdict | One-line evidence |
| --- | --- | --- |
| H1 | **Confirmed** | `app.py:stream:647-664` runs `while True` with `time.sleep(10)` on gunicorn `2 × 4` `gthread` (`Dockerfile:48-49`), saturating all 8 threads at ~8 tabs and hitting Firebase Hosting's 60 s edge limit (`docs/FIREBASE.md:139-143`). |
| H2 | **Confirmed** | `services.py:compute_stats:147-165` runs `list(db.events.find({}, ...).sort(...))` loading every event ever stored on every `/api/stats` call and every 10 s SSE tick, plus 6 separate today-queries (`lines 183-197`). |
| H3 | **Confirmed** | `services.py:compute_analytics:251` fetches up to 50,000 unprojected docs into Python; `events_for_export:297-314` truncates silently at 10,000 rows and buffers full CSV/XLSX bytes in RAM. |
| H4 | **Confirmed** | `services.py:ingest_event:125-141` and `compute_flag_reasons:93-122` have no `Idempotency-Key` or debounce window, use non-atomic read-then-insert, and `later_out` (`line 114`) uses strict `$gt`/`$lt` bounds that miss equal timestamps. |
| H5 | **Confirmed** | `vision.py:decode_image:295-301` uses `validate=False` and `image.load()` with Pillow's ~89 MP default limit; invalid images raise `VisionUnavailable` (`503`); `detect:341` slices `max_crops()` before sorting; `app.py:543` has no rate limit or concurrency cap. |
| H6 | **Confirmed** | `app.py:92` uses `get_remote_address` with `RATELIMIT_STORAGE_URI="memory://"` (`config.py:124`) across 2 workers / 4 Cloud Run instances and zero `ProxyFix` middleware, breaking IP throttling and `record_audit` `ip` (`services.py:362`). |
| H7 | **Refined** | JWT revocation gap is **Confirmed** (`jti` issued at `auth.py:58`, never checked in `user_from_token:80-89` or stored on `logout:391`); CSRF is mitigated on JSON routes via `get_json()` + `SameSite=Lax`, leaving `POST /api/auth/logout`, `DELETE` routes, and multipart `POST /api/detection/scan` unprotected by `Origin`/`Sec-Fetch-Site`. |
| H8 | **Confirmed** | `app.py:stream_proxy:495-534` hardcodes `boundary=frame`, opens `urllib.request.urlopen` inside the generator (returning 200 before checking upstream), swallows all errors silently, follows redirects, holds a worker thread forever, and `config.py:85` allows `type="mjpeg"` with `rtsp://`. |
| H9 | **Confirmed** | `db.py:24` omits `socketTimeoutMS` and `maxPoolSize` (default 100/worker risks Atlas connection limits); `events` and `audit_logs` lack TTL retention; `app.py:609-617` writes full `detection` blobs per scan; `audit_logs` `$regex` (`app.py:834-841`) scans unindexed fields (while `drivers`/`buses` regexes are tolerable at campus dozens/hundreds scale). |
| H10 | **Confirmed** | `deploy/Dockerfile` has no `USER` (runs as `root`), sets `--workers 2` (loading two PyTorch + YOLO + RapidOCR copies inside `cloudbuild.yaml`'s `--memory 2Gi` / `--cpu 1`), and omits `ULTRALYTICS_CONFIG_DIR` / `OMP_NUM_THREADS=1`. |
| H11 | **Refined** | `app.py` is 883 lines with 2 local imports (`lines 194, 425`), but `test_firebase_auth.py` monkeypatches `backend.app.verify_firebase_id_token`, so an early blueprint split adds regression risk; keep to optional Phase C cleanup. |
| H12 | **Refined** | Core RS256/aud/iss/exp/`email_verified`/allowlist logic is sound, but `firebase_auth.py:67` uses `PyJWKClient` default 30 s timeout, `verify_id_token:106` allows `sub=""` (bypassing UID check in `access.py:110`), and `access.py:_create_user` / `_record_provider` have concurrent insert/UID-binding races. |
| H13 | **Refined** | Confirmed `/api/detection/scan` ignores `gate`/`camera_id`/`direction` (`app.py:560, 607`) and never creates events; an **opt-in** `record_event=true` flag restricted to `X-Device-Key` auth saves round trips for edge cameras while keeping browser testing and `head_admin` read-only RBAC intact. |
| H14 | **Confirmed** | Zero tests exist in `backend/tests/` for `/api/stream` (SSE), happy-path `/api/stream/<camera_id>`, CSV `safe_cell` escaping, `long_overstay` flag rule, duplicate/out-of-order ingestion, image bombs, JWT revocation after logout, CSRF origin rejection, and `ProxyFix`. |

---

## 4. Findings

| ID | Severity | Confidence | File:function:lines | Problem | Impact in this deployment |
| --- | --- | --- | --- | --- | --- |
| F-01 | Critical | Confirmed | `backend/app.py:stream:645-664` | Infinite `while True` SSE loop with `time.sleep(10)` holds 1 gunicorn thread per tab, calls `compute_stats` every 10 s, omits `id` in `recent_events`, and lacks error handling/timeout under Hosting's 60 s limit. | ~8 open dashboards starve `/api/health`, `/api/events`, and auth on the 2×4 thread pool; Hosting forcibly severs connections every 60 s. |
| F-02 | Critical | Confirmed | `backend/services.py:compute_stats:144-221` | Fetches every document in `db.events` (`list(db.events.find(...))`) to compute latest event per bus, plus 6 separate today-queries on every call/SSE tick. | Memory and latency grow linearly forever (`O(N_total_events)`), risking Cloud Run OOM and NAT egress saturation. |
| F-03 | Critical | Confirmed | `backend/app.py:create_app:92-93`, `backend/config.py:Config:123-124`, `backend/services.py:record_audit:362` | No `ProxyFix` middleware; `Limiter` uses `get_remote_address` + per-worker `memory://` (`cloudbuild.yaml` sets `--max-instances 4`, `Dockerfile` uses `--workers 2`). | Behind Firebase Hosting/Cloud Run, shared proxy IP can lock out all campus logins; distributed brute-force bypasses per-worker limits; audit `ip` records proxy IP. |
| F-04 | Critical | Confirmed | `deploy/Dockerfile:10-49`, `deploy/cloudbuild.yaml:64-73` | Container runs as `root` without `USER`; `--workers 2` loads 2× PyTorch + YOLOv10n + RapidOCR in `--memory 2Gi` / `--cpu 1`; missing `OMP_NUM_THREADS=1` and `YOLO_CONFIG_DIR=/tmp/...`. | High OOM-kill risk under concurrent vision + export requests; CPU thread thrashing on 1 vCPU; non-root/readonly failures when Ultralytics writes `~/.config`. |
| F-05 | High | Confirmed | `backend/services.py:compute_flag_reasons:93-122, ingest_event:125-141` | No `Idempotency-Key` or short-window deduplication; non-atomic read-then-insert; `later_out` (`line 114`) uses strict `$gt`/`$lt` bounds missing same-timestamp `OUT`s. | Consecutive camera frames or network retries create duplicate `IN` events, inflating entry counts, distorting "buses inside", and falsely flagging `long_overstay`. |
| F-06 | High | Confirmed | `backend/vision.py:decode_image:289-303, detect:315-365`, `backend/app.py:detection_scan:543-618` | `validate=False` base64; no pixel/dimension limit before `image.load()` (~89 MP Pillow default); corrupt image raises `503` instead of `400`; `max_crops()` slices before confidence sorting; ignores EXIF orientation; no rate limit or concurrency limit on `/api/detection/scan` or `/api/events`. | Malformed/bomb uploads can trigger ~320 MB RAM spikes or misleading 503 alerts; rotated webcam images miss OCR; high-confidence stickers past index 8 are dropped; loops saturate 1 vCPU. |
| F-07 | High | Confirmed | `backend/auth.py:user_from_token:80-89`, `backend/app.py:logout:389-395, detection_scan:543-567` | `jti` is minted (`auth.py:58`) but never revoked on `logout()`; `POST /api/auth/logout`, `DELETE /api/drivers|buses/<id>`, and multipart `POST /api/detection/scan` lack `Origin`/`Sec-Fetch-Site` CSRF defense-in-depth. | Captured `__session` JWT remains usable for up to 15–60 min after logout; cross-site/same-site form posts could trigger logout or expensive scans if `SameSite=Lax` is bypassed. |
| F-08 | High | Confirmed | `backend/app.py:stream_proxy:493-534`, `backend/config.py:_parse_camera_streams:73-100` | Hardcodes `boundary=frame` instead of forwarding upstream boundary; connects inside generator (200 even if upstream fails); swallows all exceptions; follows redirects; allows `type="mjpeg"` with `rtsp://` and metadata IPs; holds thread forever. | Breaks MJPEG cameras using non-`frame` boundaries; masks upstream failures; starves worker threads; exposes SSRF risk to `169.254.169.254` if stream URLs are misconfigured. |
| F-09 | High | Confirmed | `backend/services.py:compute_analytics:224-295, events_for_export:297-347`, `backend/app.py:export_csv:620-643` | `compute_analytics` pulls up to 50,000 full docs into Python and truncates silently; exports buffer 10,000 rows as full strings/standard `openpyxl.Workbook` and truncate silently. | High memory spikes on XLSX exports and analytics queries; operators silently receive incomplete exports/charts without truncation headers. |
| F-10 | High | Confirmed | `backend/db.py:create_mongo_client:22-25, ensure_indexes:28-55`, `backend/app.py:detection_scan:578-617` | `MongoClient` lacks `socketTimeoutMS` and `maxPoolSize` (100/worker default); `events` & `audit_logs` have no TTL; `detection_scan` logs full candidate JSONs and misattributes `head_admin` scans as `device-client`; `audit_logs` lacks `collection/action` index. | Hung Atlas sockets stall threads forever; connection count risks Atlas M0/shared pool caps; `audit_logs` fills disk with per-frame bbox noise and wrong actor attribution. |
| F-11 | Medium | Confirmed | `backend/firebase_auth.py:_signing_key_client:61-68, verify_id_token:71-120`, `backend/access.py:resolve_identity:53-146` | `PyJWKClient` uses 30 s default timeout and unthrottled unknown-`kid` refreshes; `verify_id_token` allows `sub=""`; `_create_user` can raise `409 DuplicateKeyError` on concurrent first login; `_record_provider` UID update is non-atomic. | Google JWKS network hang stalls login workers 30 s; empty `sub` bypasses UID check; concurrent approved first logins fail with 409. |
| F-12 | Medium | Confirmed | `backend/vision.py:normalize_plate:276-283`, `backend/schemas.py:normalize_bus_number:14-15` | `normalize_plate()` does not strip leading/trailing `.`/`_` or cap at 20 chars, and preserves spaces (`"TN 12 AB 1234"`) while registered plates without spaces (`"TN12AB1234"`) do not match in `compute_flag_reasons`. | OCR outputs >20 chars fail `/api/events` validation; space formatting differences cause false `unregistered_plate` flags and split `inside_buses` state. |
| F-13 | Medium | Confirmed | `backend/app.py:update_bus:775-793, delete_bus:797-804` | `delete_bus` allows deleting a bus with assigned drivers; `update_bus` allows renaming `bus_number` without updating `db.drivers`. | Leaves orphaned driver records referencing nonexistent or old bus numbers. |
| F-14 | Medium | Confirmed | `backend/config.py:_int:19-25, _firebase_config:47-70, validate:177-209` | `APP_TIMEZONE` is not validated at startup; `_int`/`_float` raise raw `ValueError`; `firebase_project_id` becomes `""` silently if `FIREBASE_PROJECT_ID` is set without `FIREBASE_APP_ID`. | Typo in `APP_TIMEZONE` causes runtime 500s on `/api/stats`, `/api/analytics`, and `/api/events?date=...` instead of failing fast on startup. |
| F-15 | Medium | Confirmed | `backend/app.py:health:258-260` | `/api/health` never checks MongoDB connectivity post-startup and is not marked `@limiter.exempt`. | Cloud Run/load balancers keep routing traffic if Atlas becomes unreachable after startup; future default rate limits could throttle health checks. |
| F-16 | Medium | Confirmed | `backend/app.py:create_app:75`, `backend/vision.py:vision_status:430-452` | No logging handler configured for `backend.*` loggers under gunicorn; `vision_status()` instantiates full OCR runtimes (and could trigger EasyOCR downloads) just to check availability. | Warnings from `db.py`, `firebase_auth.py`, and `vision.py` may be lost in Cloud Run logs; `GET /api/detection/status` pays heavy initialization cost or fails offline. |
| F-17 | Medium | Confirmed | `backend/app.py:detection_scan:545-618` | `/api/detection/scan` receives `gate`, `camera_id`, `direction` from clients/docs but ignores them, forcing edge cameras to make two requests. | Edge devices must coordinate two HTTP calls (`/api/detection/scan` then `/api/events`) without optional atomic server-side handoff. |
| F-18 | Medium | Confirmed | `backend/vision.py:_ocr_tesseract:150-162, read_text:247-273` | `_ocr_tesseract()` spawns `tesseract --version` on every crop; `auto` mode falls back to `easyocr`, which downloads model weights over the network on cold start. | Unnecessary subprocess overhead per crop under Tesseract; unexpected network/disk download failures under Cloud Run if RapidOCR fails. |
| F-19 | Medium | Confirmed | `backend/auth.py:public_user:42-48`, `backend/app.py:paginated:171-181` | `public_user()` pops only `password_hash` and `_id`, returning `firebase_uid` and internal flags like `demo_user`; `paginated()` uses `count_documents({})` on empty filters. | Minor internal-field leakage in `/api/auth/me` and audit entries; avoidable full-collection count scan on unfiltered pagination. |
| F-20 | Medium | Confirmed | `docs/UPGRADE_SPECIFICATION.md`, `docs/DETECTION.md`, `docs/EVENT_CONTRACT.md`, `docs/ARCHITECTURE.md` | Docs cite `/api/events/stream` (actual `/api/stream`), `422` validation status (actual `400`), space-stripping in `normalize_plate()`, `429` on unthrottled `/api/events`, and omit new auth/vision modules. | Misleads operators and integrators implementing camera clients or debugging API responses. |
| F-21 | Medium | Confirmed | `backend/tests/*` | Missing tests for `/api/stream`, happy-path MJPEG proxy, CSV `safe_cell` formula escaping, `long_overstay`, duplicate/out-of-order events, image bombs, JWT revocation, CSRF, and `ProxyFix`. | High regression risk on concurrency, security, and ingestion flag rules during future edits. |
| F-22 | Low | Confirmed | `backend/app.py:create_app:75-883` | 883-line monolithic factory with 2 local imports inside handlers (`lines 194, 425`); `test_firebase_auth.py` monkeypatches `backend.app.verify_firebase_id_token`. | Slightly harder code navigation; naive blueprint extraction would break existing test monkeypatches unless done carefully. |

---

## 5. Change set

### CHG-01: Bound SSE concurrency, lifetime, and DB polling   (fixes: F-01)
- **Files:** `backend/app.py` (`stream`, `create_app`), `backend/config.py` (`Config`), `.env.example`
- **Change:**
  1. Add `sse_max_connections: int = 3` (`SSE_MAX_CONNECTIONS`) and `sse_max_seconds: int = 50` (`SSE_MAX_SECONDS`) to `Config` (below Firebase Hosting's 60 s dynamic request timeout).
  2. Guard `stream()` with a `threading.BoundedSemaphore(config.sse_max_connections)`. If acquiring non-blocking (`blocking=False`) fails, return `503 {"error": "Live stream capacity reached; use polling"}` with `Retry-After: 10` so the browser's `EventSource.onerror` switches cleanly to polling without starving `/api/health` or `/api/events`.
  3. Inside `generate()`, wrap the loop in `try ... finally` to always release the semaphore; bound total duration to `config.sse_max_seconds`; sleep in 1 s steps (e.g., `for _ in range(10):` checking deadline); catch `PyMongoError` cleanly by emitting an `event: error` frame and exiting rather than crashing the stream; remove `{"_id": 0}` from `db.events.find({})` at line 651 so `recent_events` includes `id` consistently.
  - **Before (`backend/app.py:645-664`):**
    ```python
    def generate():
        yield "retry: 5000\n\n"
        while True:
            recent = db.events.find({}, {"_id": 0}).sort(event_sort()).limit(8)
            payload = {"type": "tick", "generated_at": iso_utc(naive_now()),
                       "stats": compute_stats(db, config), "recent_events": serialize_many(recent)}
            yield "data: " + json.dumps(payload, default=str) + "\n\n"
            time.sleep(10)
    ```
  - **After:**
    ```python
    if not sse_semaphore.acquire(blocking=False):
        return jsonify({"error": "Too many active live streams"}), 503, {"Retry-After": "10"}
    def generate():
        deadline = time.monotonic() + config.sse_max_seconds
        try:
            yield "retry: 5000\n\n"
            while time.monotonic() < deadline:
                try:
                    recent = db.events.find({}).sort(event_sort()).limit(8)
                    payload = {"type": "tick", "generated_at": iso_utc(naive_now()),
                               "stats": compute_stats(db, config), "recent_events": serialize_many(recent)}
                    yield "data: " + json.dumps(payload, default=str) + "\n\n"
                except PyMongoError:
                    yield "event: error\ndata: {\"error\":\"temporarily unavailable\"}\n\n"
                    break
                for _ in range(10):
                    if time.monotonic() >= deadline:
                        break
                    time.sleep(1)
        finally:
            sse_semaphore.release()
    ```
- **New env vars / dependencies:** `SSE_MAX_CONNECTIONS` (default `3`, validate `>= 1` and `<= 50`), `SSE_MAX_SECONDS` (default `50`, validate `5 <= x <= 290`). No new packages.
- **Tests to add:** `backend/tests/test_events.py` — `test_sse_stream_returns_initial_tick_and_closes_at_max_seconds`, `test_sse_stream_rejects_excess_concurrent_connections_with_503_and_releases_slot`, `test_sse_stream_recent_events_include_id`. Assert SSE payload shape (`type`, `generated_at`, `stats`, `recent_events[0]["id"]`), `503` when semaphore full, and slot release after generator closes.
- **Acceptance check:** Open `SSE_MAX_CONNECTIONS + 1` concurrent `GET /api/stream` requests; confirm the `(N+1)`th returns `503` immediately and `GET /api/health` still responds in `<50 ms`.
- **Risk / rollback:** If clients connect directly to Cloud Run without Hosting and expect >50 s streams, raise `SSE_MAX_SECONDS` to `240` via env var; rollback by removing semaphore/deadline wrapper.
- **Depends on:** None (benefits directly from CHG-02 stats caching).

### CHG-02: Replace full-collection scan in `compute_stats` with `bus_states` + single today-aggregation + TTL cache   (fixes: F-02)
- **Files:** `backend/services.py` (`compute_stats`, `ingest_event`), `backend/db.py` (`ensure_indexes`), `backend/seed_demo.py` (`seed_demo_data`), `backend/config.py` (`Config`), `.env.example`
- **Change:**
  1. Maintain a `bus_states` collection (`1` doc per `bus_number`: `{"bus_number", "direction", "last_timestamp", "last_event_id", "gate", "camera_id", "updated_at"}`). Update it monotonically in `ingest_event()` whenever the new `(timestamp, _id)` is newer than the stored `(last_timestamp, last_event_id)` (using conditional `update_one` + `DuplicateKeyError` retry on first insert).
  2. In `ensure_indexes(db)` (or helper `sync_bus_states_if_needed(db)`), if `db.bus_states.estimated_document_count() == 0` and `db.events.find_one({}, {"_id": 1})` exists, backfill `bus_states` once using `$sort` + `$group` (`$first`), which works identically in MongoDB and `mongomock`. Also clear `db.bus_states.delete_many({"demo": True})` (and mark `demo` when `source == "demo"` or rebuild on `seed_demo_data()`).
  3. Collapse the 6 `today_query` operations (`entries_today`, `exits_today`, `events_today`, `flagged_today`, `unrecognized_today`, `flagged_events`) in `compute_stats()` into one projected cursor or `$group` over `today_query` (`{"direction": 1, "flagged": 1, "flag_reasons": 1, "_id": 0}`) — typically hundreds/low-thousands of docs/day (`O(N_today)` instead of 6 queries + `O(N_all_time)`).
  4. Add an in-process thread-safe TTL cache (keyed by `(id(db), config.app_timezone)`, default `STATS_CACHE_SECONDS=5`) in `services.py`, invalidated immediately inside `ingest_event()` and bus/driver write handlers.
  - **Before (`backend/services.py:147-166`):**
    ```python
    all_events = list(db.events.find({}, {...}).sort([("timestamp", ASCENDING), ("_id", ASCENDING)]))
    latest_by_bus = {}
    for event in all_events:
        latest_by_bus[event["bus_number"]] = event
    ```
  - **After:**
    ```python
    inside_docs = db.bus_states.find(
        {"direction": "IN"},
        {"bus_number": 1, "last_timestamp": 1, "_id": 0},
    )
    ```
- **New env vars / dependencies:** `STATS_CACHE_SECONDS` (default `5`, validate `0 <= x <= 60`). No new packages.
- **Tests to add:** `backend/tests/test_events.py` — `test_compute_stats_uses_bus_states_on_out_of_order_events`, `test_bus_states_backfills_from_existing_events`, `test_compute_stats_cache_invalidated_on_ingest`. Assert `BUS-001` stays `OUT` when an older `IN` arrives out-of-order, backfill works when `bus_states` is cleared, and cache updates immediately on new event.
- **Acceptance check:** Seed 10,000 events into `mongomock`, assert `compute_stats()` inspects only `bus_states` (`O(buses)`) and today's docs, and `GET /api/stats` passes all existing assertions in `test_events.py`.
- **Risk / rollback:** If external scripts write directly to `db.events` bypassing `ingest_event()`, `bus_states` would lag unless synced; mitigate by documenting `ingest_event()` as the single write path and adding a `db.bus_states` rebuild CLI command (`--rebuild-states`) or fallback when `STATS_CACHE_SECONDS=0`. Rollback: restore `$sort + $group` aggregation in `compute_stats()`.
- **Depends on:** None (coordinates with CHG-05 & CHG-06/bus_states index in Section 6).

### CHG-03: Add `ProxyFix` and MongoDB-backed distributed rate limiting   (fixes: F-03)
- **Files:** `backend/app.py` (`create_app`), `backend/config.py` (`Config`, `from_env`, `validate`), `deploy/cloudbuild.yaml`, `.env.example`
- **Change:**
  1. Add `trusted_proxy_count: int = 0` (`TRUSTED_PROXY_COUNT`) to `Config` (validate `0 <= x <= 10`). When `config.trusted_proxy_count > 0`, wrap `app.wsgi_app = ProxyFix(app.wsgi_app, x_for=config.trusted_proxy_count, x_proto=config.trusted_proxy_count, x_host=config.trusted_proxy_count)` (from `werkzeug.middleware.proxy_fix import ProxyFix`, already installed with Flask/Werkzeug).
  2. In `Config.from_env()`, if `RATELIMIT_STORAGE_URI` is unset/empty and `environment == "production"` and `mongo_uri.startswith(("mongodb://", "mongodb+srv://"))`, default `rate_limit_storage_uri = mongo_uri` (using `limits`' built-in `MongoDBStorage`, no Redis needed!). Otherwise keep `"memory://"` for dev/testing/`mongomock://`.
  3. Pass `storage_options` and `in_memory_fallback_enabled=True, swallow_errors=True` when initializing `Limiter` in `create_app()`:
     - When `config.rate_limit_storage_uri.startswith(("mongodb://", "mongodb+srv://"))`, set `app.config["RATELIMIT_STORAGE_OPTIONS"] = {"database_name": config.mongo_db_name, "counter_collection_name": "rate_limit_counters", "window_collection_name": "rate_limit_windows", "serverSelectionTimeoutMS": 2000, "connectTimeoutMS": 2000}` so the least-privilege Atlas user (`readWrite` on `srmtrpai` only) can write counters without touching a separate `limits` database!
  - **Before (`backend/app.py:92`):**
    ```python
    limiter = Limiter(key_func=get_remote_address, app=app)
    ```
  - **After:**
    ```python
    if config.trusted_proxy_count > 0:
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=config.trusted_proxy_count,
            x_proto=config.trusted_proxy_count,
            x_host=config.trusted_proxy_count,
        )
    limiter = Limiter(
        key_func=get_remote_address,
        app=app,
        storage_options=storage_options,
        in_memory_fallback_enabled=True,
        swallow_errors=True,
    )
    ```
- **New env vars / dependencies:** `TRUSTED_PROXY_COUNT` (default `0`; set `1` or `2` in `deploy/cloudbuild.yaml` after verifying hop count in Cloud Run logs). Uses existing `Werkzeug` `ProxyFix` and `limits[mongodb]` (`pymongo` already installed).
- **Tests to add:** `backend/tests/test_auth.py` — `test_proxy_fix_extracts_client_ip_for_rate_limit_and_audit`, `test_rate_limit_blocks_firebase_login`, `test_mongodb_storage_options_configured_when_mongodb_uri_used`. Assert distinct `X-Forwarded-For` client IPs get independent rate-limit buckets and `audit_logs.ip` logs the real client IP (not `127.0.0.1`).
- **Acceptance check:** Send 6 failed logins from two distinct `X-Forwarded-For` client IPs through a `TRUSTED_PROXY_COUNT=1` test client; confirm IP A gets `429` while IP B still gets `401` and `audit_logs.ip` equals IP A/B.
- **Risk / rollback:** Wrong `TRUSTED_PROXY_COUNT` (too high) lets callers spoof `X-Forwarded-For`; validate exact hop count behind Firebase Hosting -> Cloud Run once deployed (see Section 12). Rollback: set `TRUSTED_PROXY_COUNT=0` and `RATELIMIT_STORAGE_URI=memory://`.
- **Depends on:** None.

### CHG-04: Harden Dockerfile (non-root user, 1 worker × 8 threads, CPU thread caps, writable Ultralytics dir)   (fixes: F-04)
- **Files:** `deploy/Dockerfile`, `deploy/cloudbuild.yaml`
- **Change:**
  1. Create dedicated non-root user `appuser` (UID `10001`), set `chown -R appuser:appuser /app`, clean `/tmp/requirements*.txt`, and switch to `USER appuser`.
  2. Set `ENV HOME=/tmp YOLO_CONFIG_DIR=/tmp/Ultralytics OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1` so PyTorch/OpenBLAS/ONNXRuntime do not oversubscribe 1 vCPU across 8 threads and Ultralytics writes config to `/tmp`.
  3. Update gunicorn `CMD` from `--workers 2 --threads 4` to `--workers 1 --threads 8 --worker-tmp-dir /dev/shm --graceful-timeout 30 --keep-alive 5 --timeout 180` (keeping `"--timeout", "180"` so `test_deployment_config.py` passes). This halves Torch/YOLO/RapidOCR RSS from ~1.6 GB to ~800 MB inside Cloud Run's `--memory 2Gi`, eliminating worker-to-worker contention on `--cpu 1`.
  4. Increase Docker `HEALTHCHECK --start-period=40s` to `--start-period=130s` (matching the 120 s MongoDB startup window).
  5. In `deploy/cloudbuild.yaml`, add `--concurrency "20"` on Cloud Run `gcloud run deploy` so Cloud Run scales out cleanly instead of queueing >20 requests behind 8 threads.
- **New env vars / dependencies:** Container env vars `HOME=/tmp`, `YOLO_CONFIG_DIR=/tmp/Ultralytics`, `OMP_NUM_THREADS=1`, `MKL_NUM_THREADS=1`, `OPENBLAS_NUM_THREADS=1`. No new packages.
- **Tests to add:** `backend/tests/test_deployment_config.py` — `test_dockerfile_runs_as_non_root_and_uses_single_worker_for_2gi_limit`, `test_cloudbuild_sets_concurrency_limit`. Assert `USER appuser`, `--workers 1`, `--threads 8`, `--timeout 180`, and `OMP_NUM_THREADS=1` in `Dockerfile`.
- **Acceptance check:** Build container locally (`docker build -f deploy/Dockerfile .`), run `id` (`uid=10001(appuser)`), and verify `pytest` passes `test_deployment_config.py`.
- **Risk / rollback:** With 1 worker, an uncaught native segfault in OpenCV/ONNXRuntime restarts the container (`startup_probe` handles recovery); if `--cpu 2 --memory 4Gi` is provisioned later, `--workers 2` can be restored. Rollback: revert `deploy/Dockerfile` and `deploy/cloudbuild.yaml`.
- **Depends on:** CHG-03 (shared rate limits recommended if Cloud Run scales >1 instance, though 1 worker per instance simplifies in-instance behavior).

### CHG-05: Add event idempotency, short-window deduplication, and fix `later_out` boundary   (fixes: F-05)
- **Files:** `backend/services.py` (`compute_flag_reasons`, `ingest_event`), `backend/app.py` (`create_event`), `backend/db.py` (`ensure_indexes`), `backend/detection_client.py` (`main`), `backend/config.py` (`Config`), `.env.example`
- **Change:**
  1. Add `event_dedup_window_seconds: int = 60` (`EVENT_DEDUP_WINDOW_SECONDS`) to `Config` (validate `>= 0`).
  2. In `create_event()` (`app.py:451`), read optional `X-Idempotency-Key` header (max 128 printable ASCII chars; reject invalid format with `400`). Pass `idempotency_key` into `ingest_event()`.
  3. In `ingest_event()`:
     - If `idempotency_key` is provided and `db.events.find_one({"idempotency_key": idempotency_key})` exists, return `(public_doc(existing), False)` -> `create_event` returns `200 {"event": event, "deduplicated": True}`. Handle `DuplicateKeyError` on `idempotency_key` unique sparse index cleanly for concurrent identical retries.
     - Else if `config.event_dedup_window_seconds > 0`, check recent matching `(bus_number, direction, camera_id)` within `[ts - window, ts + window]` (sorted DESC); if found, return `(public_doc(existing), False)` without inserting a duplicate row (`seed_demo.py:95-96` has `BUS-004` `IN` events 13.5 h apart, well outside 60 s, so `long_overstay` demo behavior is untouched).
  4. Fix `compute_flag_reasons()` (`services.py:110-118`): include `direction == "OUT"` with `$gte: prior_in["timestamp"]` and `$lte: event["timestamp"]` (excluding `prior_in["_id"]`, and checking `_id` ordering on equal timestamps) so an `OUT` at the same second closes the `prior_in`. Also check `bus_number` against normalized/space-stripped plate (see CHG-12).
  5. Update `backend/detection_client.py` to attach a deterministic or per-attempt UUID4 `Idempotency-Key` (`X-Idempotency-Key`) and retry up to 2 times with 1 s backoff on connection error / `503` / `429`.
- **New env vars / dependencies:** `EVENT_DEDUP_WINDOW_SECONDS` (default `60`, validate `0 <= x <= 3600`). No new packages.
- **Tests to add:** `backend/tests/test_events.py` — `test_event_ingestion_idempotency_key_deduplicates_retries`, `test_event_ingestion_dedup_window_suppresses_frame_burst`, `test_long_overstay_flag_triggers_and_closes_on_out`, `test_out_event_at_same_timestamp_closes_prior_in`.
- **Acceptance check:** Post two identical events 2 seconds apart (and retry one with same `X-Idempotency-Key`); confirm `db.events.count_documents({}) == 1` and second response is `200` with `"deduplicated": true`.
- **Risk / rollback:** If two distinct movements of the *same* bus past the *same* camera happen in <60 s (practically impossible for campus buses), second is merged; set `EVENT_DEDUP_WINDOW_SECONDS=0` to disable window dedup while keeping `X-Idempotency-Key`.
- **Depends on:** CHG-02 (`bus_states` monotonic update), CHG-10 (unique sparse index on `idempotency_key`).

### CHG-06: Harden `/api/detection/scan` (image validation, bomb protection, crop sort, EXIF, semaphore, rate limit)   (fixes: F-06)
- **Files:** `backend/vision.py` (`InvalidImageError`, `decode_image`, `detect`, `load_model`), `backend/app.py` (`create_app`, `create_event`, `detection_scan`), `backend/config.py` (`Config`), `.env.example`
- **Change:**
  1. Add `InvalidImageError(ValueError)` in `vision.py`. Catch it in `app.py:detection_scan()` to return **`400`** (`{"error": str(exc)}`) instead of `503` (audit as `detection_scan_rejected`), keeping `VisionUnavailable` (`503`) strictly for missing deps/model/OCR.
  2. In `decode_image()`:
     - Enforce raw byte cap `VISION_MAX_IMAGE_BYTES` (default `2_000_000`) BEFORE decoding.
     - If `payload` is a `str` with `data:` prefix, validate `^data:image/(jpeg|jpg|png|webp|bmp);base64,` (reject arbitrary MIME types like SVG/HTML); call `base64.b64decode(data, validate=True)` after stripping ASCII whitespace.
     - Open with `Image.open(io.BytesIO(payload))`, verify `image.format in {"JPEG", "PNG", "WEBP", "BMP"}`, check `image.width <= max_dim and image.height <= max_dim and (image.width * image.height) <= max_pixels` (`VISION_MAX_IMAGE_PIXELS=16_000_000`, `VISION_MAX_IMAGE_DIM=4096`) **before** calling `image.load()`, and apply `ImageOps.exif_transpose(image)`.
  3. In `detect()`: collect all boxes, sort by `(0 if class_id == CLASS_STICKER else 1, -confidence)` **before** slicing `[:max_crops()]`, so high-confidence `sticker` boxes are never discarded behind >8 `red circle` boxes.
  4. Guard `detect()` execution in `detection_scan()` with `threading.BoundedSemaphore(config.vision_max_concurrency)` (default `2`, timeout `5` s -> return `503 {"error": "Detector is busy; retry shortly"}`).
  5. Add `@limiter.limit(config.detection_rate_limit)` on `POST /api/detection/scan` (`DETECTION_RATE_LIMIT`, default `"30 per minute"`) and `@limiter.limit(config.event_rate_limit)` on `POST /api/events` (`EVENT_RATE_LIMIT`, default `"120 per minute"`), keyed by `X-Device-Key` (hashed prefix) or `get_remote_address` so one camera key cannot lock out another gate behind NAT.
  - **Before (`backend/vision.py:293-301`):**
    ```python
    data = payload.split(",", 1)[-1] if payload.startswith("data:") else payload
    payload = base64.b64decode(data, validate=False)
    image = Image.open(io.BytesIO(payload))
    image.load()
    ```
  - **After:**
    ```python
    if payload.startswith("data:"):
        header, _, data = payload.partition(",")
        if not DATA_IMAGE_RE.match(header):
            raise InvalidImageError("Unsupported image data URI")
    payload_bytes = base64.b64decode("".join(data.split()), validate=True)
    # check len <= max_bytes, verify format & (w * h <= max_pixels) BEFORE image.load()
    ```
- **New env vars / dependencies:** `VISION_MAX_IMAGE_BYTES` (`2000000`), `VISION_MAX_IMAGE_PIXELS` (`16000000`), `VISION_MAX_IMAGE_DIM` (`4096`), `VISION_MAX_CONCURRENCY` (`2`), `DETECTION_RATE_LIMIT` (`"30 per minute"`), `EVENT_RATE_LIMIT` (`"120 per minute"`), `MAX_CONTENT_LENGTH_BYTES` (`1000000` default or configurable up to `2000000`). No new packages (`PIL.ImageOps` is part of `Pillow`).
- **Tests to add:** `backend/tests/test_detection.py` — `test_scan_rejects_invalid_base64_with_400`, `test_scan_rejects_oversized_pixel_bomb_before_load`, `test_detect_prioritizes_sticker_and_confidence_before_max_crops`, `test_scan_and_event_rate_limits_return_429`. (Mock `PIL.Image.open` when Pillow is absent in CI `backend` job, plus real-Pillow check in `vision` CI job.)
- **Acceptance check:** Post a corrupt string `"image": "not!base64"` and a mocked `10000x10000` PNG header to `/api/detection/scan`; verify both return `400` without allocating pixel buffers.
- **Risk / rollback:** Valid cameras sending >4096 px frames or >30 scans/min could get `400`/`429`; tune env vars without code changes.
- **Depends on:** CHG-03 (for accurate rate limiting behind proxy).

### CHG-07: Enforce JWT `jti` revocation on logout and `Origin`/`Sec-Fetch-Site` CSRF guard   (fixes: F-07)
- **Files:** `backend/auth.py` (`create_access_token`, `decode_access_token`, `user_from_token`, `revoke_token`), `backend/app.py` (`create_app`, `logout`), `backend/db.py` (`ensure_indexes`), `backend/config.py` (`Config`), `.env.example`
- **Change:**
  1. In `auth.py`, require `"jti"` in `decode_access_token()` `options["require"]`. Add `revoke_token(db, payload: dict) -> None` which upserts `{"jti": payload["jti"], "expires_at": datetime.fromtimestamp(payload["exp"], timezone.utc).replace(tzinfo=None)}` into `db.revoked_tokens`.
  2. In `user_from_token()`, check `db.revoked_tokens.find_one({"jti": payload["jti"]}, {"_id": 1})` (and optionally check a small 60 s LRU/TTL or direct indexed PK query—1 point lookup by unique `jti` is <1 ms); return `None` if revoked.
  3. In `logout()` (`app.py:391`), decode the incoming `__session` cookie token and call `revoke_token(db, payload)` before clearing the cookie.
  4. Add `@app.before_request` CSRF check (`csrf_origin_guard`) for unsafe methods (`POST`, `PUT`, `PATCH`, `DELETE`) on `/api/*` whenever `request.cookies.get(COOKIE_NAME)` is present **and** request is **not** device-key authenticated (`not provided_device_key` — note `POST /api/auth/login` and `/api/auth/firebase` are exempt or allowed from same origin):
     - If `Sec-Fetch-Site` header is present and equals `"cross-site"` (and `Origin` is not in `config.cors_allowed_origins`), abort `403 {"error": "Cross-site request blocked"}`.
     - If `Origin` header is present, compare `Origin.rstrip("/")` against `f"{request.scheme}://{request.host}"` (respecting `ProxyFix`) and `config.cors_allowed_origins`; reject mismatches with `403`.
     - *Frontend compatibility verified:* `frontend/js/api.js`, `auth.js`, and `dashboard.js` run same-origin `fetch()`, where browsers send `Origin` matching host and `Sec-Fetch-Site: same-origin`, so zero frontend changes are needed.
- **New env vars / dependencies:** None.
- **Tests to add:** `backend/tests/test_auth.py` — `test_logout_revokes_jwt_jti_even_if_cookie_replayed`, `test_csrf_rejects_cross_site_sec_fetch_site_and_foreign_origin`, `test_csrf_allows_same_origin_and_device_key_requests`.
- **Acceptance check:** Log in, capture `__session` cookie value, call `POST /api/auth/logout`, replay captured `__session` against `GET /api/auth/me` -> assert `401`. Send `POST /api/auth/logout` with `Origin: https://evil.example` -> assert `403`.
- **Risk / rollback:** If `ProxyFix` host/scheme (`TRUSTED_PROXY_COUNT`) is misconfigured, `request.scheme` might be `http` while `Origin` is `https://...`; match scheme/host carefully or also trust configured `PUBLIC_ORIGIN` / `CORS_ALLOWED_ORIGINS`. Rollback: toggle guard or remove `revoked_tokens` check.
- **Depends on:** CHG-03 (`ProxyFix` ensures `request.scheme` and `request.host` match `Origin`), Section 6 (`revoked_tokens` TTL index).

### CHG-08: Harden MJPEG camera proxy and camera URL config validation   (fixes: F-08)
- **Files:** `backend/config.py` (`_parse_camera_streams`), `backend/app.py` (`stream_proxy`, `create_app`), `.env.example`
- **Change:**
  1. In `config.py:_parse_camera_streams`:
     - Enforce type-to-scheme coupling: `stream_type == "rtsp"` requires `parts.scheme == "rtsp"`; `stream_type in {"hls", "mjpeg"}` requires `parts.scheme in {"http", "https"}`.
     - Reject loopback/link-local/cloud-metadata hostnames/IPs (`169.254.0.0/16`, `127.0.0.0/8`, `::1`, `metadata.google.internal`) unless `ALLOW_PRIVATE_LOOPBACK_CAMERAS=true` (while continuing to permit RFC1918 LAN NVRs like `192.168.x.x` / `10.x.x.x`).
  2. In `app.py:stream_proxy` (`lines 495-534`):
     - Acquire `stream_proxy_semaphore = BoundedSemaphore(config.stream_proxy_max_connections)` (default `2`) non-blocking; return `503` if saturated.
     - Open upstream using `requests.get(stream["url"], stream=True, timeout=(5, 10), allow_redirects=False)` **before** returning the `Response`. Return `502 {"error": "Upstream camera unavailable"}` on `requests.RequestException`, non-200 upstream status, or invalid `Content-Type` (must start with `multipart/x-mixed-replace` or `image/jpeg`).
     - Forward the upstream `Content-Type` header verbatim when valid (`multipart/x-mixed-replace; boundary=...`), avoiding the hardcoded `boundary=frame` bug.
     - Stream via `upstream.iter_content(chunk_size=8192)` bounded by `STREAM_PROXY_MAX_SECONDS` (default `50`), logging upstream disconnects as warnings (without URL credentials, already forbidden) and always closing `upstream.close()` and releasing the semaphore in `finally`.
- **New env vars / dependencies:** `STREAM_PROXY_MAX_CONNECTIONS` (`2`), `STREAM_PROXY_MAX_SECONDS` (`50`). Uses `requests` (already in `backend/requirements.txt`).
- **Tests to add:** `backend/tests/test_detection.py` & `backend/tests/test_config.py` — `test_config_rejects_mjpeg_with_rtsp_scheme_and_metadata_ip`, `test_stream_proxy_forwards_upstream_boundary_and_closes`, `test_stream_proxy_returns_502_on_upstream_error`, `test_stream_proxy_enforces_concurrency_cap`.
- **Acceptance check:** Mock an upstream MJPEG server sending `Content-Type: multipart/x-mixed-replace; boundary=cam01`; assert `GET /api/stream/gate-1-entry` returns `200` with `boundary=cam01` and returns `502` when upstream returns `500` or times out.
- **Risk / rollback:** Strict `Content-Type` check may reject misconfigured cameras returning `application/octet-stream`; allow `multipart/x-mixed-replace` or `image/jpeg` and log rejected types.
- **Depends on:** None.

### CHG-09: Aggregate `compute_analytics` on server (mongomock-safe fallback) and stream/header exports   (fixes: F-09)
- **Files:** `backend/services.py` (`compute_analytics`, `events_for_export`, `stream_csv_rows`, `xlsx_bytes`), `backend/app.py` (`export_csv`, `export_xlsx`), `backend/config.py` (`Config`), `.env.example`
- **Change:**
  1. In `compute_analytics()`:
     - When `not isinstance(db.client, mongomock.MongoClient)`, run one `$facet` aggregation pipeline (`per_hour` via `$dateTrunc` / `$dateToString` with `timezone: config.app_timezone`, `per_gate` top 12 + distinct gate count, `per_bus` top 12 + distinct bus count, and `total` count) — zero 50,000-doc transfers across Cloud NAT!
     - When `mongomock` is active (since `mongomock` lacks `$dateTrunc` and `$dateToString` with `timezone`, verified locally), iterate `db.events.find(query, {"timestamp": 1, "gate": 1, "bus_number": 1, "_id": 0})` directly over the cursor without `list(...)` and without sorting 50,000 docs. Include `"truncated": False` (or exact matched count) in `"totals"`.
  2. For `/api/export/events.csv` and `/api/export/events.xlsx`:
     - Keep `max_rows` configurable (`EXPORT_MAX_ROWS=10_000`). Compute `total_matched = db.events.count_documents(build_event_query(...))` (or fetch `max_rows + 1` docs using `.limit(max_rows + 1)` to detect truncation in 1 query!).
     - Set response headers `X-Export-Truncated: true|false` and `X-Export-Limit: <max_rows>` on both CSV and XLSX responses (`Access-Control-Expose-Headers: Content-Disposition, X-Export-Truncated, X-Export-Limit` in CORS config).
     - Stream CSV rows in batches (`stream_with_context`) via `csv.writer` (keeping UTF-8 BOM `\ufeff` and `safe_cell` escaping!).
     - Switch `xlsx_bytes()` to `openpyxl.Workbook(write_only=True)`, tracking row count so `ws.auto_filter.ref = f"A1:H{count + 1}"` and `ws.freeze_panes = "A2"` continue working with ~5–10× lower RAM usage.
- **New env vars / dependencies:** `EXPORT_MAX_ROWS` (default `10000`, validate `100 <= x <= 100000`). No new packages.
- **Tests to add:** `backend/tests/test_events.py` — `test_csv_export_escapes_spreadsheet_formulas`, `test_export_sets_truncation_header_when_over_limit`, `test_xlsx_write_only_preserves_freeze_panes_and_autofilter`, `test_analytics_cursor_handles_more_than_previous_cap_in_mongomock`.
- **Acceptance check:** Insert 5 events where `gate="=CMD()"` and export with `EXPORT_MAX_ROWS=3`; verify CSV starts with UTF-8 BOM, escapes `'=CMD()`, yields 3 rows, and sets `X-Export-Truncated: true`.
- **Risk / rollback:** `compute_analytics` aggregation path runs only on real MongoDB; requires staging/Atlas verification test against real MongoDB 6+/7+ (noted in Section 10). Rollback: restore `events_for_export` buffering.
- **Depends on:** None.

### CHG-10: Tune MongoDB pool/timeouts, add TTL & missing indexes, and trim detection audit payload   (fixes: F-10)
- **Files:** `backend/db.py` (`create_mongo_client`, `ensure_indexes`), `backend/app.py` (`detection_scan`), `backend/services.py` (`record_audit`), `backend/config.py` (`Config`), `.env.example`
- **Change:**
  1. In `db.py:create_mongo_client()`: add `socketTimeoutMS=15_000`, `maxPoolSize=15`, `minPoolSize=0`, `maxIdleTimeMS=60_000`, `retryWrites=True`, `retryReads=True`, `appName="srm-trp-transport"` (protects Atlas M0/shared connection limits across instances).
  2. In `db.py:ensure_indexes()`:
     - Add `events_bus_dir_timestamp` (`[("bus_number", ASCENDING), ("direction", ASCENDING), ("timestamp", DESCENDING), ("_id", DESCENDING)]`), `events_idempotency_unique` (`[("idempotency_key", ASCENDING)]`, `unique=True, sparse=True`), `users_firebase_uid` (`[("firebase_uid", ASCENDING)]`, `sparse=True`), `audit_collection_action_timestamp` (`[("collection", ASCENDING), ("action", ASCENDING), ("timestamp", DESCENDING)]`), `bus_states_bus_unique`, `bus_states_direction`, and `revoked_tokens_ttl` (`expireAfterSeconds=0`).
     - Add configurable TTL indexes on `events` (`created_at` ASC, `EVENT_RETENTION_DAYS=365`) and `audit_logs` (`timestamp` ASC, `AUDIT_RETENTION_DAYS=180`), skipping creation when `<= 0` and safely updating existing TTL index options via `db.command({"collMod": ...})` if `expireAfterSeconds` changes (avoiding `IndexOptionsConflict` crash).
  3. In `app.py:detection_scan()` (`lines 578-617`):
     - Attribute actor using `actor = getattr(g, "current_user", None) or {"email": "device-client", "role": "device"}`.
     - Log compact summary (`{"bus_number": ..., "confidence": ..., "candidate_count": len(result.candidates), "inference_ms": result.inference_ms, "source": ...}`) instead of storing the full `detection.candidates` bbox array on every scan; optionally allow `AUDIT_DETECTION_SCANS=false` if cameras scan continuously.
- **New env vars / dependencies:** `EVENT_RETENTION_DAYS` (`365`), `AUDIT_RETENTION_DAYS` (`180`), `AUDIT_DETECTION_SCANS` (`true`). No new packages.
- **Tests to add:** `backend/tests/test_config.py` & `backend/tests/test_detection.py` — `test_indexes_include_ttl_idempotency_and_bus_states`, `test_detection_scan_by_head_admin_audits_admin_email_and_compact_payload`.
- **Acceptance check:** Run `test_config.py` and `test_detection.py`; inspect `db.audit_logs.find_one({"action": "detection_scan"})` to verify `actor == head_admin` email and no raw `bbox` array stored.
- **Risk / rollback:** Once TTL is active in real MongoDB, expired events/audits are permanently purged (keep `365`/`180` day defaults conservative; `0` disables TTL).
- **Depends on:** CHG-02, CHG-05, CHG-07.

### CHG-11: Tighten Firebase JWKS timeouts/claims and make `access.py` provisioning atomic   (fixes: F-11)
- **Files:** `backend/firebase_auth.py` (`_signing_key_client`, `verify_id_token`), `backend/access.py` (`_create_user`, `_record_provider`), `backend/config.py` (`Config`), `.env.example`
- **Change:**
  1. Pass `timeout=int(os.getenv("FIREBASE_JWKS_TIMEOUT_SECONDS", "5"))` (default `5` s instead of 30 s) to `PyJWKClient(GOOGLE_SECURE_TOKEN_JWKS, lifespan=300, timeout=...)`.
  2. In `verify_id_token()`: pass `issuer=f"https://securetoken.google.com/{project_id}"` and `options={"require": ["exp", "iat", "sub", "aud", "iss"]}` directly into `jwt.decode()`, and explicitly verify `sub` is a non-empty `str` (`0 < len(sub) <= 128`) so `firebase_uid()` cannot return `""` and skip UID binding.
  3. In `access.py:_create_user()`: wrap `db.users.insert_one(document)` in `try ... except DuplicateKeyError`: on collision, re-query `find_user(db, email)` and return it cleanly (returning `created=False` from `resolve_identity` if another request won the race).
  4. In `access.py:_record_provider()`: use conditional `update_one({"_id": user["_id"], "$or": [{"firebase_uid": {"$exists": False}}, {"firebase_uid": None}, {"firebase_uid": ""}, {"firebase_uid": uid}]}, {"$set": updates})`; if `matched_count == 0` when `uid` is set, raise `AccessDenied("This email is already bound to a different Firebase account.", status=403)`.
- **New env vars / dependencies:** `FIREBASE_JWKS_TIMEOUT_SECONDS` (`5`). No new packages.
- **Tests to add:** `backend/tests/test_firebase_token.py` & `backend/tests/test_firebase_auth.py` — `test_empty_sub_claim_is_rejected`, `test_jwk_client_uses_short_timeout`, `test_concurrent_auto_provision_handles_duplicate_key_error`, `test_concurrent_uid_binding_rejects_mismatch`.
- **Acceptance check:** Pass RS256 token with `sub=""` to `verify_id_token()` -> assert `FirebaseAuthError(status=401)`.
- **Risk / rollback:** Very low; tests use stubbed keys or `PyJWKClient` monkeypatches that stay compatible.
- **Depends on:** None.

### CHG-12: Normalize plate edge chars/length and match space-collapsed bus numbers   (fixes: F-12)
- **Files:** `backend/vision.py` (`normalize_plate`), `backend/services.py` (`compute_flag_reasons`), `backend/schemas.py` (`BusBase`, `DriverBase`, `EventCreate`)
- **Change:**
  1. In `vision.py:normalize_plate()`: strip leading/trailing `"._- "` (`cleaned = re.sub(r"\s+", " ", cleaned).strip(" ._-")`), validate leading char is alphanumeric, and truncate/reject safely to `<= 20` chars (`[:20].strip(" ._-")`) matching `EventCreate.bus_number`.
  2. Add helper `plate_lookup_key(value: str) -> str` (`re.sub(r"[\s._-]+", "", normalize_bus_number(value))`) and store optional `plate_key` (non-unique or indexed) on `buses`, OR check both exact `bus_number` and `re.sub(r"\s+", "", bus_number)` fallback in `compute_flag_reasons()` when checking `db.buses` registration so `"TN 12 AB 1234"` matches registered `"TN12AB1234"` without changing stored display strings!
- **New env vars / dependencies:** None.
- **Tests to add:** `backend/tests/test_detection.py` & `backend/tests/test_events.py` — `test_normalize_plate_strips_edge_punctuation_and_limits_length`, `test_spaced_plate_matches_compact_registered_bus_without_unregistered_flag`.
- **Acceptance check:** Register bus `"TN12AB1234"`, post event `"TN 12 AB 1234"` -> assert `"unregistered_plate"` is NOT in `flag_reasons`.
- **Risk / rollback:** If `plate_key` were used for `bus_states` too, two events `"TN12AB1234"` and `"TN 12 AB 1234"` should normalize consistently; document canonical registration format (`TN12AB1234` vs `TN 12 AB 1234`).
- **Depends on:** None.

### CHG-13: Protect driver-bus referential integrity on bus update and delete   (fixes: F-13)
- **Files:** `backend/app.py` (`update_bus`, `delete_bus`)
- **Change:**
  1. In `delete_bus()` (`app.py:797-804`): check `db.drivers.count_documents({"bus_number": before["bus_number"]})`; if `> 0`, return `409 {"error": "Reassign or remove drivers assigned to this bus before deleting it"}`.
  2. In `update_bus()` (`app.py:775-793`): if `"bus_number"` is in `changes` and `changes["bus_number"] != before["bus_number"]`, update `db.drivers.update_many({"bus_number": before["bus_number"]}, {"$set": {"bus_number": changes["bus_number"], "updated_at": now}})` and record `reassigned_drivers` count in audit metadata.
- **New env vars / dependencies:** None.
- **Tests to add:** `backend/tests/test_events.py` — `test_delete_bus_with_assigned_driver_returns_409`, `test_rename_bus_cascades_to_assigned_drivers`.
- **Acceptance check:** Create bus `BUS-555`, create driver on `BUS-555`, `DELETE /api/buses/<id>` -> `409`; `PUT /api/buses/<id>` with `bus_number: "BUS-555-NEW"` -> driver `bus_number` updates automatically.
- **Risk / rollback:** Operators must unlink/reassign drivers before deleting a retired bus (`409` message explains why); rollback is trivial.
- **Depends on:** None.

### CHG-14: Validate `APP_TIMEZONE`, numeric env vars, and Firebase config consistency at startup   (fixes: F-14)
- **Files:** `backend/config.py` (`_int`, `_float`, `_firebase_config`, `from_env`, `validate`), `scripts/run_preview.py` (`build_config`)
- **Change:**
  1. Wrap `_int()` and `_float()` parsing errors in `RuntimeError(f"{name} must be an integer/number")`.
  2. In `Config.validate()`: verify `ZoneInfo(self.app_timezone)` succeeds (raising `RuntimeError(f"Unknown APP_TIMEZONE: {self.app_timezone}")` on `ZoneInfoNotFoundError`).
  3. Read `FIREBASE_PROJECT_ID` directly into `firebase_project_id` even if `FIREBASE_APP_ID` is absent (logging a startup warning if `FIREBASE_PROJECT_ID` is set without `FIREBASE_APP_ID` so browser SDK cannot initialize while token verification works).
  4. Ensure any new `Config` fields added by CHG-01..CHG-10 have defaults on the dataclass so `scripts/run_preview.py::build_config` never breaks.
- **New env vars / dependencies:** None.
- **Tests to add:** `backend/tests/test_config.py` — `test_invalid_app_timezone_is_rejected_at_startup`, `test_invalid_numeric_env_raises_runtime_error`.
- **Acceptance check:** `APP_TIMEZONE=Invalid/Zone python -c "from backend.config import Config; Config.from_env()"` exits non-zero with `RuntimeError`.
- **Risk / rollback:** None; catches misconfiguration at startup instead of runtime 500s.
- **Depends on:** None.

### CHG-15: Add `/api/ready` DB readiness probe and exempt `/api/health` from rate limits   (fixes: F-15)
- **Files:** `backend/app.py` (`health`, add `ready`)
- **Change:**
  1. Decorate `/api/health` with `@limiter.exempt` (preserving fast liveness response for Cloud Run startup probe and `test_deployment_config.py`).
  2. Add `GET /api/ready` (`@limiter.exempt`), running `db.command("ping")` with `mongo_timeout(2)` (or catching `PyMongoError` -> `503 {"status": "unavailable", "database": "unreachable"}`, returning `200 {"status": "ready", "database": "ok"}` on success).
- **New env vars / dependencies:** None.
- **Tests to add:** `backend/tests/test_events.py` — `test_ready_endpoint_returns_200_when_db_ok_and_503_on_pymongo_error`.
- **Acceptance check:** `GET /api/health` and `GET /api/ready` both return `200`; mocking `db.command` to raise `ConnectionFailure` makes `/api/ready` return `503`.
- **Risk / rollback:** Keep Cloud Run `--startup-probe` on `/api/health` (since `create_app()` already verifies startup DB init) and optionally use `/api/ready` for external monitoring.
- **Depends on:** None.

### CHG-16: Configure structured `backend` logger and make `vision_status()` side-effect free   (fixes: F-16)
- **Files:** `backend/app.py` (`create_app`), `backend/vision.py` (`vision_status`), `backend/config.py` (`Config`), `.env.example`
- **Change:**
  1. Configure `logging.getLogger("backend")` in `create_app()` (if no handlers exist) with a single-line formatter (`%(asctime)s %(levelname)s %(name)s %(message)s`) to `sys.stdout` at `LOG_LEVEL` (default `INFO`), ensuring `db.py`, `firebase_auth.py`, and `vision.py` logs appear in Cloud Run Logging without logging tokens/URIs/passwords.
  2. In `vision.py:vision_status()` (`lines 430-452`): probe OCR availability via `importlib.util.find_spec` (`rapidocr_onnxruntime`, `pytesseract` + `shutil.which("tesseract")`, `easyocr`) or check `_ocr_cache` instead of calling `_ocr_rapidocr()` / `_ocr_easyocr()` (which allocate ~100+ MB ONNX/EasyOCR sessions or attempt downloads during a status check!).
- **New env vars / dependencies:** `LOG_LEVEL` (`INFO`, validate `DEBUG|INFO|WARNING|ERROR`).
- **Tests to add:** `backend/tests/test_detection.py` — `test_vision_status_probes_without_instantiating_ocr_engines`.
- **Acceptance check:** Call `GET /api/detection/status`; verify `_ocr_cache` remains empty (`{}`) after the call while `ocr_available` / `problems` are accurately reported.
- **Risk / rollback:** If `rapidocr-onnxruntime` is installed but its ONNX model files are corrupt, `find_spec` returns `True` until first `detect()` call; acceptable trade-off vs instantiating heavy engines or triggering EasyOCR downloads on `GET`.
- **Depends on:** None.

### CHG-17: Add opt-in `record_event` flag on `POST /api/detection/scan` for device-key callers   (fixes: F-17)
- **Files:** `backend/app.py` (`detection_scan`), `backend/schemas.py` (`ScanMetadata` or inline `EventCreate` validation)
- **Change:**
  1. Support optional boolean field `record_event` (`false` by default; accepts `"true"/"1"/"yes"` in multipart form or `bool` in JSON).
  2. When `record_event` is `true`:
     - Enforce **device-key authentication** (`if not getattr(g, "device_authenticated", False): return jsonify({"error": "Only device API keys may record events"}), 403`) so `head_admin` browser webcam tests remain read-only per role contract.
     - If `candidate` has a valid `bus_number`, construct `EventCreate` from `(bus_number, direction, gate, camera_id, confidence, timestamp or naive_now())` (returning `400` if `gate`/`direction`/`camera_id` are missing/invalid), call `ingest_event()` (respecting CHG-05 deduplication/idempotency!), and add `"event": event` to the JSON response. If no `bus_number` was detected, return `"event": None` with `200` (no fabricated event).
- **New env vars / dependencies:** None.
- **Tests to add:** `backend/tests/test_detection.py` — `test_scan_with_record_event_requires_device_key`, `test_scan_with_record_event_ingests_when_device_key_and_plate_present`, `test_scan_without_record_event_never_writes_event`.
- **Acceptance check:** `POST /api/detection/scan` with `X-Device-Key` + `record_event=true` + mocked `detect()` returning `BUS-001` creates 1 event and returns `"event": {...}`; browser session with `record_event=true` returns `403`; default `record_event=false` leaves `db.events` untouched.
- **Risk / rollback:** Completely opt-in (`default=False`), 100% backward compatible with existing `frontend/js/dashboard.js` and `test_detection.py`.
- **Depends on:** CHG-05, CHG-06.

### CHG-18: Cache Tesseract check and gate EasyOCR auto-fallback   (fixes: F-18)
- **Files:** `backend/vision.py` (`_ocr_tesseract`, `read_text`), `backend/config.py` / env docs (`.env.example`)
- **Change:**
  1. Cache `pytesseract` binary verification in `_ocr_cache["tesseract"]` behind `_ocr_lock` so `get_tesseract_version()` runs once per process instead of per crop.
  2. In `read_text()`, when `engine_name == "auto"`, default order is `("rapidocr", "tesseract")` unless `VISION_OCR_ALLOW_EASYOCR=true` (preventing unexpected runtime model downloads in Cloud Run); explicit `VISION_OCR_ENGINE=easyocr` continues to work.
- **New env vars / dependencies:** `VISION_OCR_ALLOW_EASYOCR` (`false`).
- **Tests to add:** `backend/tests/test_detection.py` — `test_tesseract_version_checked_once`, `test_auto_ocr_skips_easyocr_by_default`.
- **Acceptance check:** Call `_ocr_tesseract()` twice -> assert `get_tesseract_version` called once.
- **Risk / rollback:** Set `VISION_OCR_ALLOW_EASYOCR=true` if EasyOCR fallback is intentionally desired.
- **Depends on:** None.

### CHG-19: Allowlist fields in `public_user()` and optimize empty-query pagination count   (fixes: F-19)
- **Files:** `backend/auth.py` (`public_user`), `backend/app.py` (`paginated`, `list_events`)
- **Change:**
  1. Update `public_user(doc)` to return only safe allowlisted keys (`id`, `email`, `role`, `active`, `auth_provider`, `created_at`, `last_sign_in_at`), omitting `firebase_uid` and `demo_user`.
  2. In `paginated()` and `list_events()`, use `collection.estimated_document_count()` when `query == {}` (verified supported in `mongomock` and MongoDB).
- **New env vars / dependencies:** None.
- **Tests to add:** `backend/tests/test_auth.py` — `test_public_user_omits_internal_fields_such_as_firebase_uid_and_demo_user`.
- **Acceptance check:** Sign in with Firebase user; assert `"firebase_uid"` is absent from `GET /api/auth/me` JSON while `"id"`, `"email"`, `"role"`, `"active"` remain present.
- **Risk / rollback:** Verify no consumer expects `firebase_uid` on `/api/auth/me` (verified: `frontend/js/` only reads `user.email` and `user.role`, and `manage_access.py` uses `list_access_entries()`, not `public_user()`).
- **Depends on:** None.

### CHG-20: Reconcile backend documentation contradictions   (fixes: F-20)
- **Files:** `docs/ARCHITECTURE.md`, `docs/DETECTION.md`, `docs/EVENT_CONTRACT.md`, `docs/UPGRADE_SPECIFICATION.md`
- **Change:**
  1. `docs/UPGRADE_SPECIFICATION.md`: correct `/api/events/stream` -> `/api/stream` (lines 255, 714) and `422` validation status -> `400` (line 242).
  2. `docs/DETECTION.md`: align `normalize_plate()` description with actual behavior (and CHG-12 edge trimming/20-char cap/canonical matching), document `detection_scan_failed` and `detection_scan_rejected` (`400`) + `429` + optional `record_event`.
  3. `docs/EVENT_CONTRACT.md`: document `X-Idempotency-Key`, `200` deduplicated response, `EVENT_RATE_LIMIT` (`429`), and exact `long_overstay` matching semantics.
  4. `docs/ARCHITECTURE.md`: list `access.py`, `firebase_auth.py`, `manage_access.py`, `vision.py`, and the Firebase/detection/camera/readiness endpoints.
- **New env vars / dependencies:** None.
- **Tests to add:** Optional doc link/route sanity assertion in `backend/tests/test_deployment_config.py`.
- **Acceptance check:** `git grep "/api/events/stream" docs/` returns zero stale matches.
- **Risk / rollback:** Docs-only; zero runtime risk.
- **Depends on:** CHG-05, CHG-06, CHG-12, CHG-15, CHG-17.

### CHG-21: Expand automated test suite for concurrency, security, and ingestion gaps   (fixes: F-21)
- **Files:** `backend/tests/test_events.py`, `backend/tests/test_auth.py`, `backend/tests/test_detection.py`, `backend/tests/test_config.py`, `.github/workflows/ci.yml`
- **Change:** Add all test functions listed under CHG-01 through CHG-19, plus add a `detect()` synthetic-image smoke test inside `.github/workflows/ci.yml` (`vision` job, where `torch`/`ultralytics`/`Pillow`/`rapidocr` are installed).
- **New env vars / dependencies:** None.
- **Tests to add:** Full inventory in Section 10.
- **Acceptance check:** `MONGO_URI=mongomock://t JWT_SECRET=test-secret-value-with-at-least-32-chars python -m pytest -q` passes all ~172 + ~28 new tests.
- **Risk / rollback:** None.
- **Depends on:** CHG-01..CHG-19.

### CHG-22: Optional Phase C cleanup of `backend/app.py` local imports & helpers   (fixes: F-22)
- **Files:** `backend/app.py` (`lines 194, 425`), optional `backend/http_helpers.py`
- **Change:** Move `from .auth import authenticate_request` (`line 194`) and `from .services import build_event_query` (`line 425`) to module-level imports (neither `auth.py` nor `services.py` imports `app.py`). Optionally extract `validation_details`, `validate`, `mongo_payload`, `oid_or_none`, `serialize_many`, `paginated`, `search_regex` into `backend/http_helpers.py`, **without** moving `firebase_login` out of `backend/app.py` (or keep `app_module.verify_firebase_id_token` lookup preserved) so `test_firebase_auth.py` monkeypatches keep working.
- **New env vars / dependencies:** None.
- **Tests to add:** Existing 172+ tests verify zero behavioral regressions.
- **Acceptance check:** `python -m pytest -q && python -m compileall -q backend`.
- **Risk / rollback:** Moving route handlers risks breaking `monkeypatch.setattr(app_module, ...)` in tests; keep routes inside `app.py` unless split carefully in a dedicated PR.
- **Depends on:** CHG-01..CHG-21.

---

## 6. Database changes

All index changes belong in `backend/db.py::ensure_indexes(db)` (and TTL option updates via safe helper `_ensure_ttl_index()`).

### New collections
1. **`bus_states`** (1 doc per bus; replaces full `events` scan in `compute_stats`)
   ```python
   {
       "bus_number": "BUS-001",          # unique
       "direction": "IN",                # "IN" | "OUT"
       "last_timestamp": datetime(...),  # UTC naive
       "last_event_id": ObjectId(...),
       "gate": "Gate 1",
       "camera_id": "gate-1-entry",
       "demo": False,
       "updated_at": datetime(...),
   }
   ```
2. **`revoked_tokens`** (JWT logout blacklist; auto-pruned after 15–60 min)
   ```python
   {
       "jti": "hex-uuid",                # unique
       "expires_at": datetime(...),      # UTC naive; TTL expireAfterSeconds=0
   }
   ```
3. **`rate_limit_counters` & `rate_limit_windows`** (managed automatically by `limits.storage.MongoDBStorage` inside `config.mongo_db_name` when `RATELIMIT_STORAGE_URI` uses MongoDB; creates `expireAt` TTL index automatically).

### Exact `create_index` additions & updates
```python
db.bus_states.create_index([("bus_number", ASCENDING)], unique=True, name="bus_states_number_unique")
db.bus_states.create_index([("direction", ASCENDING)], name="bus_states_direction")

db.revoked_tokens.create_index([("jti", ASCENDING)], unique=True, name="revoked_jti_unique")
db.revoked_tokens.create_index([("expires_at", ASCENDING)], expireAfterSeconds=0, name="revoked_expires_ttl")

db.events.create_index(
    [("bus_number", ASCENDING), ("direction", ASCENDING), ("timestamp", DESCENDING), ("_id", DESCENDING)],
    name="events_bus_dir_timestamp",
)
db.events.create_index(
    [("idempotency_key", ASCENDING)],
    unique=True,
    sparse=True,
    name="events_idempotency_unique",
)
db.users.create_index([("firebase_uid", ASCENDING)], sparse=True, name="users_firebase_uid")
db.audit_logs.create_index(
    [("collection", ASCENDING), ("action", ASCENDING), ("timestamp", DESCENDING)],
    name="audit_collection_action_timestamp",
)
```

### Retention TTL indexes (configurable, safe against `IndexOptionsConflict`)
- Do **not** alter existing `"events_timestamp"` (`timestamp DESC`) or `"audit_timestamp"` (`timestamp DESC`) index options directly (MongoDB rejects `create_index` with mismatched `expireAfterSeconds` on an existing name).
- Instead, create separate ascending TTL indexes when retention `> 0`:
  - `db.events`: `[("created_at", ASCENDING)]`, `name="events_created_ttl"`, `expireAfterSeconds=event_retention_days * 86400` (default `365 * 86400`).
  - `db.audit_logs`: `[("timestamp", ASCENDING)]`, `name="audit_timestamp_ttl"`, `expireAfterSeconds=audit_retention_days * 86400` (default `180 * 86400`).
- Before calling `create_index`, inspect `collection.index_information()`. If the TTL index exists with a different `expireAfterSeconds`, run `db.command({"collMod": collection.name, "index": {"name": idx_name, "expireAfterSeconds": ttl_seconds}})` (skipping `collMod` on `mongomock`).

### `mongomock` caveats
- `create_index(..., expireAfterSeconds=...)` and `sparse=True` succeed in `mongomock 4.3.0`, **but** `mongomock` does not run background TTL deletion; tests verifying revocation expiry must rely on JWT `exp` or mock timestamps.
- `mongomock` does **not** support `$dateTrunc` or `$dateToString` with `timezone` (`NotImplementedError` / `OperationFailure` verified locally). `compute_analytics()` must retain a projected cursor path when `isinstance(db.client, mongomock.MongoClient)`.
- `mongomock` does **not** support `collMod`; guard `collMod` behind `not _is_mongomock(db)`.

---

## 7. API contract changes

| Endpoint | Method | Old request / response | New request / response | Backward compatible? |
| --- | --- | --- | --- | --- |
| `/api/events` | `POST` | JSON `EventCreate`; always returns `201 {"event": ...}` (no rate limit) | Optional `X-Idempotency-Key` header; returns `200 {"event": ..., "deduplicated": true}` on idempotent/window duplicate; enforces `EVENT_RATE_LIMIT` (`429`) | **Mostly yes** (clients checking `response.ok` / `200-299` work; `detection_client.py` uses `response.ok`; strict `== 201` callers only change on duplicate retries) |
| `/api/detection/scan` | `POST` | Multipart/JSON image; bad image returns `503`; ignores `gate`/`direction`/`camera_id`; no rate limit | Bad base64/image/bomb returns `400`; optional `record_event` (`false` default; `403` if `true` without `X-Device-Key`, adds `"event": {...}\|null` when `true`); enforces `DETECTION_RATE_LIMIT` (`429`) & concurrency cap (`503`) | **Yes** (`record_event` defaults to `false`; all existing response keys unchanged) |
| `/api/stream` | `GET` | Infinite SSE; `recent_events` omits `id` | Bounded to `SSE_MAX_SECONDS` (`50`), capped at `SSE_MAX_CONNECTIONS` (`503` + `Retry-After` when full); `recent_events` items include `id` | **Yes** (`frontend/js/sse.js` falls back cleanly to polling on `503`/close) |
| `/api/stream/<camera_id>` | `GET` | Always `200` with hardcoded `boundary=frame` | Probes upstream first: returns `502` on upstream failure, `503` if proxy slots full, `200` with upstream `Content-Type` boundary; bounded duration (`50 s`) | **Yes** (fixes broken non-`frame` MJPEG browsers; error status replaces silent dead stream) |
| `/api/export/events.csv`, `.xlsx` | `GET` | Truncates silently at 10,000 rows | Same body/columns; adds `X-Export-Truncated` and `X-Export-Limit` headers | **Yes** (purely additive headers) |
| `/api/auth/me`, `/api/auth/login`, `/api/auth/firebase` | `GET` / `POST` | `user` dict included `firebase_uid` and `demo_user` | `public_user()` returns allowlisted safe fields only (`id`, `email`, `role`, `active`, `auth_provider`, `created_at`, `last_sign_in_at`) | **Yes** (no client consumes `firebase_uid` or `demo_user` via HTTP) |
| `/api/buses/<bus_id>` | `DELETE` | Deletes bus even with assigned drivers (`200`) | Returns `409` if drivers are still assigned to this bus | **Behavior tighten** (prevents orphaned driver records) |
| `/api/ready` | `GET` | Did not exist | New unauthenticated readiness check (`ping` MongoDB -> `200` or `503`) | **Yes** (new endpoint) |

---

## 8. Security and reliability checklist

| Control | Current status | Notes / Evidence | Target after CHG |
| --- | --- | --- | --- |
| Input validation | **Pass (with gaps)** | Strict Pydantic on all REST routes, but `decode_image` uses `validate=False`, no pixel-bomb guard, and `APP_TIMEZONE` unvalidated. | **Pass** (`CHG-06`, `CHG-14`) |
| AuthN / AuthZ | **Pass (with gaps)** | Strong RBAC & verified-email Firebase allowlist, but `sub=""` allowed in `firebase_auth.py:106` and `_create_user` races. | **Pass** (`CHG-11`) |
| Session revocation | **Fail** | `jti` issued (`auth.py:58`) but never checked; logged-out JWTs stay valid up to 15–60 min. | **Pass** (`CHG-07`) |
| CSRF protection | **Partial** | `SameSite=Lax` + JSON content-type on most writes, but `POST /api/auth/logout`, `DELETE`, and multipart `/api/detection/scan` lack `Origin`/`Sec-Fetch-Site` validation. | **Pass** (`CHG-07`) |
| Secrets management | **Pass** | Read from env/Secret Manager; `.env` ignored; `scan_secrets.py` passes. *(Historical Git leak rotation/purge tracked outside code.)* | **Pass** |
| Rate limiting | **Fail** | Only on login/firebase; per-worker `memory://` bypassed across workers/instances; absent on `/api/detection/scan` and `/api/events`. | **Pass** (`CHG-03`, `CHG-06`) |
| Proxy headers | **Fail** | No `ProxyFix`; `request.remote_addr` & `audit_logs.ip` log proxy IP behind Hosting/Cloud Run. | **Pass** (`CHG-03`) |
| Logging without secrets | **Partial** | Secrets/URIs already scrubbed in `db.py` & `manage_access.py`, but `backend.*` loggers lack configured handler under gunicorn. | **Pass** (`CHG-16`) |
| Timeouts | **Fail** | `MongoClient` has no `socketTimeoutMS`; `PyJWKClient` uses 30 s default timeout; SSE/MJPEG streams have no max duration. | **Pass** (`CHG-01`, `CHG-08`, `CHG-10`, `CHG-11`) |
| Retries | **Partial** | Startup Mongo retry exists (`120 s`); `detection_client.py` has no retry/idempotency; Firebase JWKS fails cleanly to `503`. | **Pass** (`CHG-05`) |
| Graceful shutdown & bounds | **Fail** | Unbounded SSE/MJPEG generator threads; container runs as `root` with 2× PyTorch workers inside 2 GiB. | **Pass** (`CHG-01`, `CHG-04`, `CHG-08`) |
| Health checks | **Partial** | `/api/health` is liveness-only (no DB ping, not `@limiter.exempt`); no `/api/ready` endpoint. | **Pass** (`CHG-15`) |

---

## 9. Deployment and container changes

### `deploy/Dockerfile`
- Add non-root user before copying app files or right after venv install:
  ```dockerfile
  RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser \
   && rm -f /tmp/requirements.txt /tmp/requirements-vision.txt
  ```
- Add container environment defaults:
  ```dockerfile
  ENV HOME=/tmp \
      YOLO_CONFIG_DIR=/tmp/Ultralytics \
      OMP_NUM_THREADS=1 \
      MKL_NUM_THREADS=1 \
      OPENBLAS_NUM_THREADS=1
  ```
- Copy with ownership (`COPY --chown=appuser:appuser ...`) and set `USER appuser`.
- Update `HEALTHCHECK` start period to `--start-period=130s` (covering `MONGO_STARTUP_TIMEOUT_SECONDS=120`).
- Change `CMD` (preserving `"--timeout", "180"` required by `test_deployment_config.py`):
  ```dockerfile
  CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "8", \
       "--worker-tmp-dir", "/dev/shm", "--timeout", "180", "--graceful-timeout", "30", \
       "--keep-alive", "5", "--access-logfile", "-", "backend.app:create_app()"]
  ```

### `deploy/cloudbuild.yaml`
- Add `--concurrency` flag (`"20"`) under `run deploy` args so Cloud Run distributes spikes across up to 4 instances rather than queueing excessively behind 8 threads.
- Add new environment variables to `--set-env-vars`:
  `TRUSTED_PROXY_COUNT=1` *(verify 1 vs 2 behind Firebase Hosting -> Cloud Run in Section 12)*, `SSE_MAX_CONNECTIONS=3`, `SSE_MAX_SECONDS=50`, `STREAM_PROXY_MAX_CONNECTIONS=2`, `STREAM_PROXY_MAX_SECONDS=50`, `EVENT_RETENTION_DAYS=365`, `AUDIT_RETENTION_DAYS=180`.
- Keep `--cpu "1"`, `--memory 2Gi` (safe once `--workers 1` is applied), `--timeout "300"`, `--startup-probe` on `/api/health`, and `--vpc-egress all-traffic`.

### `.github/workflows/ci.yml`
- In `vision` job (`lines 69-82`), add a synthetic RGB frame `decode_image` + `detect()` smoke test (`100x100` solid PNG/JPEG via Pillow) so `detect()`, `best_candidate()`, and `read_text()` are verified in CI whenever vision dependencies change.

### `.env.example`
- Document every new variable added in CHG-01..CHG-18 (`TRUSTED_PROXY_COUNT`, `SSE_MAX_CONNECTIONS`, `SSE_MAX_SECONDS`, `STATS_CACHE_SECONDS`, `EVENT_DEDUP_WINDOW_SECONDS`, `DETECTION_RATE_LIMIT`, `EVENT_RATE_LIMIT`, `VISION_MAX_IMAGE_BYTES`, `VISION_MAX_IMAGE_PIXELS`, `VISION_MAX_IMAGE_DIM`, `VISION_MAX_CONCURRENCY`, `VISION_OCR_ALLOW_EASYOCR`, `STREAM_PROXY_MAX_CONNECTIONS`, `STREAM_PROXY_MAX_SECONDS`, `EXPORT_MAX_ROWS`, `EVENT_RETENTION_DAYS`, `AUDIT_RETENTION_DAYS`, `AUDIT_DETECTION_SCANS`, `FIREBASE_JWKS_TIMEOUT_SECONDS`, `LOG_LEVEL`).

---

## 10. Test plan

### Automated tests to add (`backend/tests/`)
- **`test_auth.py`:**
  - `test_logout_revokes_jwt_jti_even_if_cookie_replayed`
  - `test_csrf_rejects_cross_site_sec_fetch_site_and_foreign_origin`
  - `test_csrf_allows_same_origin_and_device_key_requests`
  - `test_proxy_fix_extracts_client_ip_for_rate_limit_and_audit`
  - `test_rate_limit_blocks_firebase_login`
  - `test_mongodb_storage_options_configured_when_mongodb_uri_used`
  - `test_public_user_omits_internal_fields_such_as_firebase_uid_and_demo_user`
- **`test_events.py`:**
  - `test_sse_stream_returns_initial_tick_and_closes_at_max_seconds`
  - `test_sse_stream_rejects_excess_concurrent_connections_with_503_and_releases_slot`
  - `test_sse_stream_recent_events_include_id`
  - `test_compute_stats_uses_bus_states_on_out_of_order_events`
  - `test_bus_states_backfills_from_existing_events`
  - `test_compute_stats_cache_invalidated_on_ingest`
  - `test_event_ingestion_idempotency_key_deduplicates_retries`
  - `test_event_ingestion_dedup_window_suppresses_frame_burst`
  - `test_long_overstay_flag_triggers_and_closes_on_out`
  - `test_out_event_at_same_timestamp_closes_prior_in`
  - `test_csv_export_escapes_spreadsheet_formulas`
  - `test_export_sets_truncation_header_when_over_limit`
  - `test_xlsx_write_only_preserves_freeze_panes_and_autofilter`
  - `test_delete_bus_with_assigned_driver_returns_409`
  - `test_rename_bus_cascades_to_assigned_drivers`
  - `test_ready_endpoint_returns_200_when_db_ok_and_503_on_pymongo_error`
- **`test_detection.py`:**
  - `test_scan_rejects_invalid_base64_with_400`
  - `test_scan_rejects_oversized_pixel_bomb_before_load`
  - `test_detect_prioritizes_sticker_and_confidence_before_max_crops`
  - `test_scan_and_event_rate_limits_return_429`
  - `test_scan_with_record_event_requires_device_key`
  - `test_scan_with_record_event_ingests_when_device_key_and_plate_present`
  - `test_scan_without_record_event_never_writes_event`
  - `test_detection_scan_by_head_admin_audits_admin_email_and_compact_payload`
  - `test_normalize_plate_strips_edge_punctuation_and_limits_length`
  - `test_spaced_plate_matches_compact_registered_bus_without_unregistered_flag`
  - `test_vision_status_probes_without_instantiating_ocr_engines`
  - `test_tesseract_version_checked_once`
  - `test_auto_ocr_skips_easyocr_by_default`
  - `test_stream_proxy_forwards_upstream_boundary_and_closes`
  - `test_stream_proxy_returns_502_on_upstream_error`
  - `test_stream_proxy_enforces_concurrency_cap`
- **`test_firebase_auth.py` / `test_firebase_token.py`:**
  - `test_empty_sub_claim_is_rejected`
  - `test_jwk_client_uses_short_timeout`
  - `test_concurrent_auto_provision_handles_duplicate_key_error`
  - `test_concurrent_uid_binding_rejects_mismatch`
- **`test_config.py` / `test_deployment_config.py`:**
  - `test_config_rejects_mjpeg_with_rtsp_scheme_and_metadata_ip`
  - `test_invalid_app_timezone_is_rejected_at_startup`
  - `test_invalid_numeric_env_raises_runtime_error`
  - `test_indexes_include_ttl_idempotency_and_bus_states`
  - `test_dockerfile_runs_as_non_root_and_uses_single_worker_for_2gi_limit`
  - `test_cloudbuild_sets_concurrency_limit`

### Verification & soak checks (run against built container / real MongoDB)
1. **Unit & compile check (every CHG):**
   `MONGO_URI=mongomock://t JWT_SECRET=test-secret-value-with-at-least-32-chars python -m pytest -q && python -m compileall -q backend`
2. **Real MongoDB aggregation & TTL check (not testable on `mongomock`):**
   Point a local Docker MongoDB 7 container at `compute_analytics()`, `MongoDBStorage` rate limiter, and `ensure_indexes()` (`collMod` TTL update); verify `$facet`/`$dateTrunc` matches `Asia/Kolkata` hour buckets and `rate_limit_counters` writes to `config.mongo_db_name`.
3. **SSE & `/api/health` starvation soak check:**
   Start the built container (`--memory=2g --cpus=1`), open 10 concurrent `GET /api/stream` requests, confirm excess return `503` while `GET /api/health` and `POST /api/events` maintain `<100 ms` p95 latency and RSS stays `<1.1 GiB` after running 20 `/api/detection/scan` calls.

---

## 11. Implementation order for Claude

### Phase A — Quick, low-risk, high-impact (ship first)
1. `CHG-14` *(independent)* — Startup validation for `APP_TIMEZONE`, `_int`/`_float`, and `Config` dataclass defaults.
2. `CHG-01` *(independent)* — Bound SSE concurrency (`SSE_MAX_CONNECTIONS`) & lifetime (`SSE_MAX_SECONDS`), add error handling & `id` in `recent_events`.
3. `CHG-03` *(independent)* — `ProxyFix` gated by `TRUSTED_PROXY_COUNT` + `MongoDBStorage` default rate-limit backend in production.
4. `CHG-04` *(independent)* — Harden `deploy/Dockerfile` (non-root `appuser`, `--workers 1 --threads 8`, `OMP_NUM_THREADS=1`, `YOLO_CONFIG_DIR=/tmp/Ultralytics`) + `cloudbuild.yaml` `--concurrency 20`.
5. `CHG-15` *(independent)* — Exempt `/api/health` from Limiter and add `/api/ready` DB ping endpoint.
6. `CHG-06` *(depends on CHG-03)* — `InvalidImageError` (`400`), `validate=True`, pixel/dim checks before `image.load()`, EXIF transpose, box sort before `max_crops()`, semaphore, and `/api/detection/scan` + `/api/events` rate limits.

### Phase B — Medium scope (core data model, security, & MongoDB efficiency)
7. `CHG-10` *(combine index setup with CHG-02, CHG-05, CHG-07)* — Mongo pool/socket timeouts, compact & properly attributed `detection_scan` audits, new indexes, configurable TTLs.
8. `CHG-02` *(depends on CHG-10)* — `bus_states` collection + backfill + single today-query + 5 s TTL cache in `compute_stats()`.
9. `CHG-05` *(depends on CHG-02, CHG-10)* — `X-Idempotency-Key`, `EVENT_DEDUP_WINDOW_SECONDS`, `later_out` boundary fix, and `detection_client.py` retry/idempotency.
10. `CHG-07` *(depends on CHG-03, CHG-10)* — `revoked_tokens` JTI revocation on logout + `Origin`/`Sec-Fetch-Site` CSRF guard.
11. `CHG-08` *(independent)* — MJPEG proxy upstream probe/boundary forwarding/`502`/SSRF guard/concurrency cap & `type`-`scheme` config coupling.
12. `CHG-09` *(independent)* — Real-MongoDB `$facet` analytics + `mongomock` streaming fallback + streaming CSV / `write_only` XLSX + `X-Export-*` truncation headers.
13. `CHG-11` *(independent)* — 5 s Firebase JWKS timeout, non-empty `sub`, `issuer` check in `jwt.decode()`, concurrent `_create_user`/`_record_provider` race fixes.
14. `CHG-12` *(independent)* — `normalize_plate()` edge trimming/length cap + space-insensitive bus match in `compute_flag_reasons()`.
15. `CHG-13` *(independent)* — Prevent `delete_bus` with assigned drivers (`409`) and cascade `bus_number` updates to `db.drivers`.
16. `CHG-16` *(independent)* — Structured `backend` logger setup + side-effect-free `vision_status()`.
17. `CHG-18` *(independent)* — Cache Tesseract binary check + disable unrequested `easyocr` auto-fallback.

### Phase C — Optional / polish & documentation
18. `CHG-17` *(depends on CHG-05, CHG-06)* — Opt-in `record_event=true` on `POST /api/detection/scan` (device-key only).
19. `CHG-19` *(independent)* — Field allowlist in `public_user()` + `estimated_document_count()` for empty pagination filter.
20. `CHG-20` *(depends on CHG-05, CHG-06, CHG-12, CHG-15, CHG-17)* — Reconcile doc contradictions across `docs/`.
21. `CHG-21` *(depends on CHG-01..CHG-19)* — Finalize full test suite + CI `vision` `detect()` smoke test.
22. `CHG-22` *(optional, depends on CHG-01..CHG-21)* — Move 2 local imports in `backend/app.py` to module level while preserving `backend.app.verify_firebase_id_token` test patch target.

---

## 12. Assumptions, unknowns and questions

### Known blockers & assumptions
- **Model provenance & licensing (`best.pt`):** Already tracked as a known production blocker in `docs/DETECTION.md` and `TRANSPORT_PROJECT_STATUS.md`; excluded from code recommendations here.
- **Vision stack runtime in sandbox:** `torch`, `ultralytics`, `opencv-python-headless`, `Pillow`, and `rapidocr-onnxruntime` were not installed locally, so peak container RSS (~800 MB for 1 worker) and CPU inference latency under `--cpu 1` are **Likely** estimates derived from `docs/UPGRADE_SPECIFICATION.md` (~114 ms inference, 0.9 s cold load) and wheel sizes rather than live sandbox profiling.
- **Historical secret rotation:** Previously committed credentials in Git history are an operational blocker already documented in `docs/DEPLOY_WINDOWS.md`.

### Unknowns requiring live environment verification
1. **Exact `X-Forwarded-For` hop count (`TRUSTED_PROXY_COUNT`):** Behind Firebase Hosting -> Cloud Run, confirm whether `X-Forwarded-For` contains 1 or 2 proxy entries in live Cloud Run request logs before setting `TRUSTED_PROXY_COUNT` in `deploy/cloudbuild.yaml`.
2. **Real MongoDB `MongoDBStorage` latency & Atlas tier limits:** Confirm whether Atlas cluster tier is M0 (500 connections, shared CPU) or M10+, and verify `compute_analytics()` `$facet` + `$dateTrunc` performance against real production data.
3. **Real camera behavior:** Verify actual MJPEG cameras' `Content-Type` headers, keyframe intervals, and whether edge detection devices will run on-gate (`detection_client.py` / `POST /api/events`) or post frames to `/api/detection/scan`.

### Questions for the project owner
1. **Retention policy:** Are **365 days** for gate `events` and **180 days** for `audit_logs` acceptable under the transport department's compliance rules, or should exports/archival run before TTL expiry?
2. **Same-plate spacing convention:** Are buses registered in MongoDB with spaces (`TN 12 AB 1234`) or without spaces (`TN12AB1234`)? (`CHG-12` matches both safely without changing stored bus strings.)
3. **Edge camera integration:** Do the 4 gate cameras push pre-OCR'd JSON to `POST /api/events`, or do they need `record_event=true` on `POST /api/detection/scan`?
4. **Live camera stream consumers:** Are MJPEG streams consumed via Firebase Hosting (which enforces a 60 s cap anyway) or only via operator intranet/HLS (`MediaMTX` -> `hls.js`)?
