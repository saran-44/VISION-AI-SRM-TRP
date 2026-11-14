# Master prompt for the VS Code assistant — UI/UX (with Flowstep) and backend triage

Copy everything between the two rules into VS Code as **one message**. It
assumes the repo is at `af65914` or later and that the Flowstep extension is
connected in this workspace. The first thing it does is prove that.

---

**WHO YOU ARE WORKING WITH**

Two assistants share this repository and you are one of them.

- **Arena** owns `backend/`, `frontend/`, `scripts/`, `docs/` and the tests. It
  writes what has to reach `main` and opens the pull requests.
- **You (VS Code)** own the workspace: running the app, exploring designs with
  Flowstep, measuring real screens, and reporting. You do **not** push, and you
  do **not** open pull requests.
- **Flowstep** is a design tool, not an author. Its output is *reference*. It
  does not know this codebase, and nothing it generates is merged as-is.

**ENVIRONMENT GATE — before you read anything**

```bash
pwd                        # must be the repository root
git rev-parse --short HEAD # a1ef06c or a descendant
git status --short         # must not list files from another project
ls docs/                   # the real directory listing
```

Stop and report if the folder is wrong, if HEAD is older than `a1ef06c` (the
tree is stale — `git pull --ff-only origin main` and restart), or if the working
tree holds another project's files.

**If `ls docs/` shows a file that your own file search cannot find, your index is
stale, not the file.** Say exactly that — *"my index does not include X, the
directory listing does"* — and ask for the window to be reloaded. Do not report
it as missing, and never create a file to make this prompt true. The terminal
listing is the ground truth; a codebase index built before the last `git pull`
is not.

**READ FIRST — in this order**

```
README.md                      what the product is
docs/ARCHITECTURE.md           how the pieces fit
docs/MASTER_PROMPT.md          the backend/detection prompt — the rules there still apply
docs/TASK_ANPR_VSCODE.md       the current measurement task
frontend/assets/theme.css      design tokens + glass3d + dark mode
frontend/assets/styles.css     components (card, btn, table, chip, toast …)
frontend/assets/layout.css     shell geometry, every breakpoint, Test Lab switches
frontend/js/layout.js          sidebar, role-aware navigation, top bar
frontend/js/ui.js              el(), badge(), icon(), setState(), showToast()
backend/app.py                 every route and the response shapes
```

List the files before you edit anything. If a request needs a file not in that
list, say so and stop.

**THE PRODUCT**

VISION AI - SRM TRP — a bus entry/exit console for SRM TRP Engineering College.
Nine pages, all server-rendered shells plus one ES module each:

| Page | Route | Job |
| --- | --- | --- |
| Login | `/login` | password + Firebase sign-in, demo hint |
| Dashboard | `/dashboard` | live camera tiles, scan result, KPI cards, charts, recent events |
| Live Logs | `/logs` | event stream, filters, CSV/XLSX export |
| Analytics | `/analytics` | charts over date ranges |
| Drivers / Buses | `/drivers`, `/buses` | records, search, pagination |
| Driver details | `/driver-details` | one driver, history |
| Audit Log | `/audit` | who did what |
| Manage Records | `/manage` | create/edit, head_admin only |
| Test Lab | `/test-lab` | demo-only bench: camera, detection stages, setup checklist |

**THE DESIGN SYSTEM — use it, do not reinvent it**

- Light and dark are both first class: every colour comes from a token in
  `theme.css` (`--app-bg`, `--card-bg`, `--card-border`, `--surface-muted`,
  `--text-main`, `--text-muted`, `--primary`, `--accent`, `--success*`,
  `--warning*`, `--danger*`). A hard-coded hex outside those files is a bug.
- Brand: `--brand-purple-700 #5b21b6`, `--brand-gold-500 #c9a227`,
  `--app-bg #faf7ff` (dark `#140c26`). Theme choice lives in
  `localStorage["transport-theme"]`.
- Shape: `--radius-sm/md/lg/xl`, `--shadow`. Cards also take `class="glass3d"`
  for the frosted layer — do not re-implement the blur by hand.
- Components that already exist: `.card`, `.glass3d`, `.btn` (+`-outline`,
  `-sm`, `-danger`), `.data-table`, `.table-container`, `.tag`, `.badge`,
  `.state-box`, `.toast`, `.modal-overlay`, `.camera-tile`, `.stage-toggle`,
  `.stage-chip`, `.setup-grid`. Extend them; do not add a parallel system.
- Icons: Boxicons (`bx bx-*`), via `icon()` from `ui.js`.
- **No CSS framework, no build step, no npm package.** Vanilla ES modules and
  three CSS files, loaded in this order: `theme.css` → `styles.css` →
  `layout.css`.
- Breakpoints already defined in `layout.css`: 1024, 768, 380 px, plus
  `(pointer: coarse)`, `(prefers-reduced-motion)`, `print`. Add to those, do not
  create new ones.
- Tap targets ≥ 44 px (`--tap`), focus visible on everything interactive,
  `aria-live` on anything that changes without a reload.

**HOW TO USE FLOWSTEP — the rules that keep the repo clean**

1. **Reference, not code.** Ask Flowstep for directions, palettes, layout
   studies and critiques of a screenshot of the *current* page. Never paste its
   React/Next/Tailwind output — this project has none of that.
2. **Translate before you write.** Every colour it suggests must land on an
   existing token or a new token added to `theme.css` (light **and** dark
   values). Every spacing value must reuse the existing scale.
3. **One direction at a time.** Pick the smallest slice (one card, one table,
   one empty state), implement it, screenshot it, then continue. No page-wide
   rewrites in one go.
4. **Screen before and after.** Save both, same viewport, same data. A change
   with no before/after pair is not reviewable.
5. **Flowstep never sees the repo.** Do not give it `.env`, keys, database
   URLs, real driver names or real plate numbers. Use the seeded demo data.

**WHAT TO IMPROVE, in priority order**

1. **Mobile first.** The gate runs on a phone: `/dashboard` and `/test-lab` must
   be usable at 360 px with one thumb. Tables become stacked cards below 768 px
   instead of scrolling sideways.
2. **Scan feedback.** One glance must answer: was a bus read, from which stage,
   how confident, what kind of vehicle. Reuse `.stage-chip` and `.scan-status`;
   never a bare "no detection".
3. **Empty, loading and error states** on every list and chart. They exist for
   some (`setState()`); find the ones that show a blank box.
4. **Dark-mode parity.** Check every page in dark mode; contrast on
   `--surface-muted` and badge colours.
5. **Login page.** Brand-first, honest error text, no placeholder copy.
6. **Navigation.** Active state, drawer behaviour on touch, breadcrumb on detail
   pages.
7. **Accessibility.** Keyboard order, focus rings, labelled form fields, toasts
   announced.

**BACKEND ISSUES — how to treat them**

- **Frontend never hides a backend failure.** A 500 shows an error state, not an
  empty table. If the fix is "catch and ignore", it is not a fix.
- **The API contract is fixed.** Adding a field is fine; renaming or removing
  one breaks devices in the field. `docs/EVENT_CONTRACT.md` and
  `docs/DETECTION.md` are the references.
- **Detection numbers are tuned and frozen:** `VISION_IMAGE_SIZE=960`,
  `VISION_CONFIDENCE=0.25`, `VISION_STICKER_CLASS=1`,
  `VISION_PLATE_CONFIDENCE=0.25`, `VISION_PLATE_UPSCALE=3`. Changing one
  requires ten real frames of evidence, not a hunch.
- **Diagnose before proposing.** Give the failing request, the exact response,
  the server log line and the command that reproduces it. A report without a
  reproduction is a guess.
- **You may read and run the backend; you may not restructure it.** Schema,
  authentication and storage changes come back to Arena.

**VERIFY BEFORE YOU REPORT**

```bash
node scripts/check_frontend.mjs          # every import and page reference resolves
python -m pytest -o addopts="" -q        # 247 passed, 5 skipped at 227ba7b
bash scripts/audit_local.sh              # secrets / ignore rules / frontend
```

Then the manual matrix, every time:

| Check | Pass looks like |
| --- | --- |
| 360 px | no horizontal scroll, everything reachable with a thumb |
| 768 px | tables either fit or stack; no cut-off headers |
| 1280 px | content column capped, not stretched |
| Light + dark | no unreadable text, no white flash |
| Keyboard only | tab reaches every control, focus is visible |
| Empty + error | a sentence, not a blank box |

**DEFINITION OF DONE**

A change is done when: the smallest slice is implemented, before/after
screenshots exist at 360 and 1280 px in both themes, `check_frontend` and the
suite are still green, the API contract is unchanged, and the rules below are
respected.

**HARD RULES**

- Do not push. Do not open pull requests. Do not merge.
- Do not commit `.env`, `weights/`, `frames/`, datasets or logs.
- Do not print or paste secret values — variable names only.
- Do not change the app title: exactly **VISION AI - SRM TRP**.
- Do not remove or restyle a feature that currently works.
- Do not add dependencies, build steps, or a second styling system.
- On any conflict between a request and these rules: stop, explain, wait.

**REPORT BACK — this exact shape**

```
GOAL:            <one sentence>
PAGES TOUCHED:   <routes/files>
DESIGN SOURCE:   <flowstep direction, or "hand-authored">
BEFORE / AFTER:  <screenshot paths, 360 and 1280, light and dark>
TOKENS ADDED:    <name: light value / dark value, or "none">
CSS FILES:       <which of theme/styles/layout, and why>
JS CHANGED:      <module + one line each>
API CONTRACT:    unchanged | <what changed and why it is additive>
FORBIDDEN FILES: <none touched, confirm>
BACKEND ISSUES:  <reproduction + evidence, or "none">
CHECKS:          <check_frontend / pytest / audit output, verbatim>
MOBILE:          <360 px result>
DARK MODE:       <result>
STILL OPEN:      <what you did not do>
```

**FIRST ACTION**

Run the environment gate, read the eight files at the top, run the three
verification commands, then reply with exactly:

```
context loaded · pages: <count> · suite: <passed>/<skipped> · ready for the first slice
```

and wait. Do not start redesigning anything until the first slice is named.

---

## Why this prompt is shaped this way

Flowstep is good at *taste* and this repo has strong constraints: vanilla ES
modules, three CSS files, a frozen API contract and a working detection
pipeline. Handing a design tool the keys produces a rewrite nobody can review;
handing it a screenshot and a token list produces an upgrade. The prompt makes
that boundary explicit, then defines "done" in terms of screenshots and green
checks rather than adjectives.
