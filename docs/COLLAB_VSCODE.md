# Working together: Arena AI ⇄ VS Code ⇄ GitHub

Three places hold state. Keep each one's job small and the loop stays simple:

| Place | Owns | Never holds |
| --- | --- | --- |
| **Arena AI** | changes that must reach `main`: `backend/`, `frontend/`, `scripts/`, `docs/`, tests | your `.env`, datasets, weights, logs |
| **VS Code (local)** | experiments on your machine, the private project (`bus sticker extract sql/`), webcam tests, private data | anything that must survive a re-clone |
| **GitHub `main`** | the single source of truth both sides pull from | secrets (CI secret scan fails the PR) |

Rule of thumb: **if it belongs in the repo, Arena writes it; if it belongs to your machine, VS Code keeps it.**

---

## 0. One-time: connect VS Code to GitHub

```bash
cd ~/VISION-AI-SRM-TRP

git remote -v                      # expect origin -> github.com/saran-44/VISION-AI-SRM-TRP
git config user.name  "kp571"
git config user.email "your-github-email@example.com"

gh auth status                     # if not logged in: gh auth login  (HTTPS, browser)
git fetch origin
git switch main && git pull --ff-only
```

Then confirm your private files are ignored — they must never appear in `git status`:

```bash
git status --short                 # .env, data/, weights/, debug/, database/ must NOT show up
```

If any of them does show up, stop and fix `.gitignore` before committing anything.

---

## 1. The loop

```text
  ┌─ you ─────────────────────────────────────────────────────────┐
  │                                                              │
  │  ① Prompt 1 (context)  ──────────────▶  VS Code AI           │
  │  ② Prompt 2 (the task) ──────────────▶  VS Code AI           │
  │  ③ Prompt 3 (report)   ──────────────▶  VS Code AI           │
  │           ◀──────────── report text ──                       │
  │  ④ Prompt 4 + report   ──────────────▶  Arena AI             │
  │           ◀─────── PR opened, checks green ───               │
  │  ⑤ "merge"             ──────────────▶  Arena AI             │
  │  ⑥ Prompt 5 (pull + verify) ─────────▶  VS Code              │
  │                                                              │
  └──────────────────────────────────────────────────────────────┘
```

Steps ① and ③ exist so neither side guesses: VS Code is told what is already
true, and Arena receives facts (files, commands, output) instead of a summary.

---

## 2. Prompt 1 — what has been built so far (paste into VS Code)

> Use this once per VS Code session, before asking for anything.
> A single copy-paste version of everything below (plus the training recipe)
> lives in [`MASTER_PROMPT.md`](MASTER_PROMPT.md) — prefer that one.
> The current assignment for VS Code is [`TASK_ANPR_VSCODE.md`](TASK_ANPR_VSCODE.md);
> for UI/UX work (with Flowstep) plus backend triage, use
> [`MASTER_PROMPT_UIUX.md`](MASTER_PROMPT_UIUX.md).

```text
You are helping me work on the GitHub repository saran-44/VISION-AI-SRM-TRP
("VISION AI - SRM TRP": a campus bus transport portal). Read the repository
before changing anything. Do not regenerate or restructure the project, and do
not touch files I did not ask about.

Before you answer, check that you are looking at the right tree:
  pwd ; git rev-parse --short HEAD ; git status --short
This description is current as of af65914. If HEAD is older, pull first; if a
file named here is missing, say so and stop - do not create it.

ARCHITECTURE (current main)
- Backend: Flask app in backend/app.py, config in backend/config.py,
  Pydantic schemas in backend/schemas.py, auth in backend/auth.py.
  Database is PostgreSQL in production, SQLAlchemy + a small storage layer in
  backend/db.py; schema in backend/sql/001_initial.sql. There is no
  backend/storage.py - if your notes say otherwise they are out of date.
- Vision: backend/vision.py holds the whole detector pipeline as a cascade -
  best.pt (classes 0="red circle", 1="sticker"), then anpr_best.pt (one class,
  "licence"), then optional weights/vehicle.pt; crop, OCR (RapidOCR, Tesseract
  or EasyOCR fallback), plate normalisation.
  OCR, camera and app routes are NOT to be changed when tuning detection.
- Frontend: static HTML in frontend/pages/*.html, ES modules in frontend/js/*.js,
  styles in frontend/assets/styles.css + theme.css + layout.css (+ login.css).
  layout.css is loaded last and owns the responsive shell - do not duplicate it.
- Sign-in: Firebase in production, local password form for the demo bench.

WHAT IS ALREADY DONE (do not redo)
- scripts/run_preview.py: disposable in-memory SQLite preview with DEMO_MODE=1,
  admin / admin, Test Lab at /test-lab. It deliberately ignores DATABASE_URL in
  .env and only reads PREVIEW_DATABASE_URL.
- scripts/audit_local.sh: read-only audit (routes, secrets, config, tests).
- Detection tuning, already merged: inference at imgsz 960 (VISION_IMAGE_SIZE),
  boxes probed from confidence 0.05, only class 1 ("sticker") is cropped and
  OCR'd (VISION_STICKER_CLASS), OCR gate at 0.25 (VISION_CONFIDENCE).
  /api/detection/scan returns reason = no_detection | other_class |
  below_threshold | unreadable | ok, plus advice and box counters.
- scripts/scan_image.py: scan one image, or --camera 0 to grab a webcam frame
  (requests 1280x720, warns when the driver delivers 640x480).
- scripts/inspect_model.py: print a checkpoint's task, classes and size before
  swapping it in.
- docs/: TESTING_LAB.md, DETECTION.md, TRAINING.md, SECURITY_AUDIT.md,
  EVENT_CONTRACT.md, AUTHENTICATION.md, PRIVACY.md.

RULES
1. Never commit or print secrets: .env, credentials, tokens, logs.
2. Never add these to git: .conda/, data/, debug/, database/, weights/,
   generated logs, .env files.
3. Keep the API contract: additive changes only (new JSON fields are fine,
   renaming or removing them is not).
4. Every behaviour change needs a test in backend/tests/.
5. Verify with:
     python -m pytest -o addopts="" -q
     node scripts/check_frontend.mjs
   Both must stay green; the suite is currently 218 passed, 5 skipped.
6. If a request conflicts with the rules above, stop and say so instead of
   guessing.

Reply "context loaded" and list any file you believe is missing from this
description. Do not change code yet.
```

---

## 3. Prompt 2 — ask VS Code for a piece of work

> Fill in the task. One task per round keeps the diff reviewable.

```text
Task: <one sentence, e.g. "show the detected sticker box on the Test Lab camera
preview before OCR runs">

Scope: only <files or folders>.
Do not touch: <files>, .env, backend/sql/, frontend/assets/layout.css.
Acceptance: <observable behaviour, e.g. "a green rectangle is drawn over the
sticker for 2 seconds after a scan, and disappears if no box was found">.
Tests: add them under backend/tests/ (or explain why none are possible).

Before editing: list the files you will change and why.
After editing: run the two verification commands and paste their real output.
If you cannot finish, stop and say exactly where you are stuck.
```

---

## 4. Prompt 3 — get a report you can paste back to Arena

```text
Give me a handoff report, exactly in this format, no extra prose:

GOAL: <what was asked>
FILES CHANGED:
  - path: one line on what changed
FORBIDDEN FILES TOUCHED: none | <list>      (see the rules: .env, data/, weights/, debug/, database/)
API CONTRACT: unchanged | added <fields> | BREAKING <details>
TESTS ADDED: <test names> | none because <reason>
COMMANDS RUN:
  $ <command>
  <real output, trimmed to the important lines>
UNCOMMITTED WORK: <anything you tried and abandoned>
STILL OPEN: <what needs Arena or me to decide>
```

---

## 5. Prompt 4 — hand it to Arena

> Paste the report inside the markers, then send.

```text
Review this report from my VS Code session against the current main branch.
Check it for: secrets, forbidden files, API-breaking changes, missing tests,
and anything that conflicts with the detection tuning (imgsz 960, probe 0.05,
class 1 only, 0.25 gate).
If it is sound: implement/merge it on a branch, run the tests and open a PR.
If there is a conflict: stop and explain it in one paragraph before changing
anything.
Do not regenerate the project and do not overwrite unrelated work.

--- REPORT START ---
<paste the report from Prompt 3>
--- REPORT END ---
```

---

## 6. Prompt 5 — after Arena merges, pull it in VS Code

```bash
cd ~/VISION-AI-SRM-TRP
git fetch origin && git switch main && git pull --ff-only
git log --oneline -3
```

```text
main has been updated. Pull complete. Please:
1. run: python -m pytest -o addopts="" -q
2. run: node scripts/check_frontend.mjs
3. tell me which new files appeared (git show --stat HEAD)
4. tell me if any local change of mine now conflicts with main
Do not modify anything in this step.
```

---

## 7. Guardrails

| Situation | Do this |
| --- | --- |
| VS Code says "I rewrote the project" | `/undo` in VS Code, then re-run Prompt 1 — the wording "do not regenerate" must be present |
| A secret appears in `git diff` | do not commit; `git restore <file>`; rotate the credential |
| PR CI fails on **Secret scan** | something sensitive is tracked or pasted into a tracked file; remove it, never "fix" the scan |
| VS Code and Arena edited the same file | stop both, run `git diff` / `git status`, let **Arena** own the merge, then pull |
| The preview will not start | `python scripts/run_preview.py --port 4400` prints the reason; `docs/TESTING_LAB.md` §1 has the table |
| A scan finds nothing | `python scripts/scan_image.py --camera 0` prints reason + advice; `docs/TESTING_LAB.md` §3 has the four cases |

Never paste `.env` contents, Supabase passwords, Firebase service-account JSON or
`DATABASE_URL` into either assistant. Both sides only ever need the *name* of a
variable, never its value.
