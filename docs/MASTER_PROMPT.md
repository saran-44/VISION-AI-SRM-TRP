# Master prompt

One block to paste into the VS Code assistant (and into Colab when you train).
It carries the state of `main`, the rules, the detection numbers that are
already tuned, the training recipe, and the report format Arena expects.

Copy everything inside the block, including the first and last lines.

---

```text
MASTER CONTEXT - VISION AI - SRM TRP
Repository: saran-44/VISION-AI-SRM-TRP   (current as of af65914)

WHO YOU ARE WORKING WITH
Two assistants share this repository. You (in VS Code, and in Colab for
training) and Arena AI. Arena writes what must reach main and opens the pull
requests; you own local experiments, Colab runs and private data. Neither side
ever sees a secret value - only variable names. Never ask me for a password,
token or connection string.

ENVIRONMENT GATE - run these three before anything else
  pwd                      -> must be the repository root
  git rev-parse --short HEAD
  git status --short
  ls docs/                 -> the real directory listing
Version marker: docs/WORKSPACE_SYNC.md exists only at cd8cfbe and later. If the
listing does not show it, the checkout is stale.
Stop and report if:
  - pwd is not the repository root (a different folder was opened);
  - the marker is absent, or HEAD is older than cd8cfbe (run
    "git pull --ff-only origin main" and start again);
  - git status lists files from another project - do not touch or revert them.
A partially-synced docs/ is impossible: every commit has all four prompt docs or
none. If one is listed and another is not, run "git status --short docs/" - a
line starting with " D " is a local deletion, fixed by "git restore docs/".
This prompt describes the tree at cd8cfbe.
If ls docs/ shows a file your own file search cannot find, your INDEX is stale,
not the file: say so and ask for the window to be reloaded. The terminal listing
is the ground truth. Never report a file as missing when the listing has it, and
never create a file to make the prompt true.

READ FIRST
Read the repository before changing anything: README.md, docs/ARCHITECTURE.md,
backend/vision.py, backend/app.py, frontend/assets/layout.css.
Never regenerate or restructure the project. Never touch files outside the task.
Reply "context loaded" and list anything you think is missing.

ARCHITECTURE (what exists on main)
- Flask backend: backend/app.py (all routes), backend/config.py (env config),
  backend/schemas.py (Pydantic), backend/auth.py (sessions, device keys),
  backend/db.py + backend/sql/001_initial.sql (PostgreSQL through SQLAlchemy;
  SQLite only for the disposable preview). There is no backend/storage.py.
- Vision pipeline: backend/vision.py - Ultralytics YOLO > crop > OCR
  (RapidOCR, then Tesseract, then EasyOCR) > normalize_plate, as a three-stage
  cascade: best.pt (sticker) > anpr_best.pt (number plate) > weights/vehicle.pt.
  When tuning detection do NOT change the OCR engine, the camera code or the
  API routes.
- Frontend: frontend/pages/*.html + ES modules in frontend/js/*.js +
  frontend/assets/{styles,theme,layout,login}.css. layout.css is loaded last on
  every page and owns the responsive shell - do not duplicate its rules.
- Auth: Firebase sign-in in production; local password form plus DEMO_MODE
  (admin / admin, Test Lab at /test-lab) for the isolated bench.
- Scripts: scripts/run_preview.py (in-memory SQLite preview, ignores
  DATABASE_URL from .env), scripts/audit_local.sh (read-only audit),
  scripts/scan_image.py (scan one image or --camera 0),
  scripts/inspect_model.py (print a checkpoint's task/classes/size).
- Docs: TESTING_LAB, DETECTION, TRAINING, COLLAB_VSCODE, SECURITY_AUDIT,
  EVENT_CONTRACT, AUTHENTICATION, PRIVACY.

DETECTION SETTINGS - ALREADY TUNED, DO NOT SILENTLY CHANGE
- VISION_IMAGE_SIZE=960   inference letterbox (a 640 frame upscaled only blurs)
- probe floor 0.05        the model is asked for boxes from 0.05 so diagnostics
                          can report near-misses; candidates are filtered after
- VISION_STICKER_CLASS=1  only class 1 ("sticker") is cropped and OCR'd;
                          class 0 ("red circle") is counted, never read. A
                          single-class checkpoint uses its only class.
- VISION_CONFIDENCE=0.25  a sticker box below this never reaches the OCR
- STAGES sticker -> plate -> vehicle (VISION_STAGE_*), each switchable per scan;
  a missing optional checkpoint is `skipped`, never a 503
- MODELS best.pt = sticker/red-circle (classes 0 "red circle", 1 "sticker"),
  OCRs class 1 only; anpr_best.pt = number plate (YOLOv10n on Car_License_Plates,
  ONE class 0 "licence" -> no class filter, upscaled 3x before OCR);
  weights/vehicle.pt = optional COCO model for bus/car/bike
- PLATE  VISION_PLATE_CONFIDENCE=0.25 and VISION_PLATE_UPSCALE=3 are separate
  from VISION_CONFIDENCE on purpose: do not merge them
- POST /api/detection/scan returns: candidates[], bus_number, confidence,
  raw_text, reason, advice, detection{boxes_total, boxes_above_threshold,
  boxes_other_class, best_confidence, threshold, image_size, sticker_class,
  inference_ms, model}
  reason = no_detection | other_class | below_threshold | unreadable | ok
Changing any of these numbers is allowed, but state it explicitly in your
report and add/adjust a test for it.

MODEL AND TRAINING
- best.pt in the repo root: YOLOv10n, 2 classes (0 red circle, 1 sticker),
  5.5 MB, AGPL-3.0.
- A new number-plate model: base yolo26s (47.8 COCO mAP, 19.5 MB), single class
  "number_plate", imgsz 960, epochs 100 with patience 25, fliplr=0 (mirrored
  plates are text that never occurs), trained on OUR OWN stickers - not a public
  number-plate dataset. Target: >=300 images per gate, varied light, angles,
  motion blur, ~10% negative frames, split by video frame.
- Colab (free T4, 12 h cap) recipe:
    !pip install ultralytics==8.4.20
    !yolo detect train model=yolo26s.pt data=/content/dataset/data.yaml \
          imgsz=960 epochs=100 batch=16 patience=25 \
          project=/content/runs name=plates exist_ok=True
  Use batch=8 if the T4 runs out of memory. Mount Drive and copy
  /content/runs/plates/weights/best.pt there before the session ends.
  Never train on Render (0.1 CPU, 512 MB, torch is not installed there).
- Bringing the model back: run python scripts/inspect_model.py <file> and paste
  its real output; then either cp it to best.pt or set VISION_MODEL_PATH. Do not
  commit weights without being asked.

HARD RULES
1. Never commit, print or paste secrets: .env, tokens, device keys, service
   account JSON, database URLs. Refer to them by variable name only.
2. Never add to git: .conda/, data/, debug/, database/, weights/, generated
   logs, .env*. Check with: git status --short
3. API contract stays additive: new JSON fields are fine; renaming or removing
   an existing field or status code is not.
4. Every behaviour change needs a test in backend/tests/.
5. Verification, both must stay green:
     python -m pytest -o addopts="" -q          (currently 218 passed, 5 skipped)
     node scripts/check_frontend.mjs            (21 modules, 10 pages)
6. If a request conflicts with these rules, or with the settings above, stop
   and say so in one paragraph instead of guessing.

WORKING PROTOCOL
- Before editing: list the files you will change and why.
- After editing: run the two verification commands and paste their real output,
  not a summary.
- If you cannot finish: stop and say exactly where you are stuck.
- Do not push to main and do not open pull requests; Arena does that.

REPORT BACK AT THE END OF EVERY SESSION - exactly this format, no extra prose
GOAL: <what was asked>
FILES CHANGED:
  - path: one line on what changed
FORBIDDEN FILES TOUCHED: none | <list>
API CONTRACT: unchanged | added <fields> | BREAKING <details>
DETECTION SETTINGS CHANGED: none | <variable: old -> new, and why>
TESTS ADDED: <test names> | none because <reason>
COMMANDS RUN:
  $ <command>
  <real output, important lines only>
ARTIFACTS: <paths, sizes, e.g. best.pt 19.5 MB saved to Drive:/plates/>
UNCOMMITTED WORK: <what you tried and abandoned>
STILL OPEN: <what needs a decision>

WHAT HAPPENS NEXT
I paste your report to Arena AI. Arena checks it for secrets, forbidden files,
API breaks, missing tests and conflicts with the detection settings, then
implements or merges it on a branch, runs the four CI checks and opens a pull
request. After it is merged I pull with: git pull --ff-only

FIRST ACTION
Run the environment gate above, read the files, then reply exactly
"context loaded" plus the short SHA you are reading, and wait for the task.
Read the repository, reply "context loaded", list anything missing from this
description, and wait for my task. Do not edit anything yet.
```
