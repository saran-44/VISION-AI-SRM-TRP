#!/usr/bin/env python3
"""Build personalised sprint PDFs for the VISION AI - SRM TRP team.
Sprint: Fri 13 Nov 2026 -> Wed 25 Nov 2026 (13 working days).
"""
import os
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, Frame, PageTemplate, Paragraph,
                                Spacer, Table, TableStyle, PageBreak, KeepTogether)

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pdf")
os.makedirs(OUT, exist_ok=True)

NAVY = colors.HexColor("#10243e")
ACCENT = colors.HexColor("#1f6feb")
LIGHT = colors.HexColor("#eef3fb")
GREY = colors.HexColor("#5a6675")
LINE = colors.HexColor("#c9d4e3")
GREEN = colors.HexColor("#1a7f37")
AMBER = colors.HexColor("#9a6700")
RED = colors.HexColor("#b42318")

S = getSampleStyleSheet()


def st(name, **kw):
    base = dict(fontName="Helvetica", fontSize=9.5, leading=13.5, textColor=colors.HexColor("#1c2530"))
    base.update(kw)
    return ParagraphStyle(name, **base)


TITLE = st("t", fontName="Helvetica-Bold", fontSize=22, leading=26, textColor=NAVY)
SUB = st("s", fontSize=11, leading=15, textColor=GREY)
H1 = st("h1", fontName="Helvetica-Bold", fontSize=14, leading=18, textColor=NAVY,
        spaceBefore=10, spaceAfter=6)
H2 = st("h2", fontName="Helvetica-Bold", fontSize=10.5, leading=14, textColor=ACCENT,
        spaceBefore=8, spaceAfter=3)
BODY = st("b")
SMALL = st("sm", fontSize=8.4, leading=11.4)
CELL = st("c", fontSize=8.4, leading=11)
CELLB = st("cb", fontName="Helvetica-Bold", fontSize=8.4, leading=11)
CELLH = st("ch", fontName="Helvetica-Bold", fontSize=8.4, leading=11, textColor=colors.white)
CODE = st("code", fontName="Courier", fontSize=8.2, leading=11, textColor=colors.HexColor("#0b3d91"))


def P(txt, style=BODY):
    return Paragraph(txt, style)


def bullets(items, style=CELL):
    return [Paragraph("&bull;&nbsp;&nbsp;" + i, style) for i in items]


# ----------------------------------------------------------------------------- data
DATES = ["Fri 13 Nov", "Sat 14 Nov", "Sun 15 Nov", "Mon 16 Nov", "Tue 17 Nov",
         "Wed 18 Nov", "Thu 19 Nov", "Fri 20 Nov", "Sat 21 Nov", "Sun 22 Nov",
         "Mon 23 Nov", "Tue 24 Nov", "Wed 25 Nov"]
EXAM = {4, 5, 6, 7}  # indexes of Tue17..Fri20 = exam-safe days (assumption)

LEAD = dict(name="HARIHARAN V", reg="814725105014", email="814725105014@trp.srmtrichy.edu.in",
            phone="6383388381", role="Team Lead / Backend Developer")

MEMBERS = [
    dict(
        name="SUTHARSON R", reg="814725105050", email="814725105050@trp.srmtrichy.edu.in",
        phone="9344539185", role="Co-Lead / Backend Developer",
        slug="sutharson", branch="feat/sutharson-vehicle-number",
        mission=("You own the product change that makes this project useful: every gate event must "
                 "carry the bus's <b>vehicle number</b> (registration), not just the sticker number. "
                 "Today that field exists only inside the offline benchmark script - it is in no API "
                 "response, no export and no screen. You also own the acceptance script that has to "
                 "start telling the truth, and closing the pull request."),
        owns=[
            "vehicle_number in every event response (source: fleet / plate / none)",
            "plate_mismatch flag when a plate disagrees with the fleet record",
            "Vehicle number column in the CSV and XLSX export",
            "scripts/gate_acceptance.py: assert the 12 ground-truth rows, exit non-zero on failure",
            "Gate configuration must not reproduce the '19' on busimage1",
            "Pull request closed with CI green; tag v1.0.0",
        ],
        setup=[
            "Install <b>Python 3.11</b> (python.org). Tick &quot;Add python.exe to PATH&quot;.",
            "In the project folder: <font face='Courier'>py -3.11 -m venv .venv</font> then "
            "<font face='Courier'>.venv\\Scripts\\activate</font>",
            "<font face='Courier'>pip install -r backend\\requirements.txt</font>",
            "Optional vision stack (large): <font face='Courier'>pip install -r backend\\requirements-vision.txt</font>",
            "Run the suite: <font face='Courier'>python -m pytest -q</font> - paste the exact "
            "&quot;N passed, M skipped&quot; line. A number you did not see is not evidence.",
            "Run the gate check: <font face='Courier'>python desktop\\gate\\launcher.py --check</font>",
        ],
        tips=[
            "Read the three files before writing code: <font face='Courier'>backend\\app.py</font> "
            "(create_event), <font face='Courier'>backend\\services.py</font> (compute_flag_reasons), "
            "<font face='Courier'>backend\\schemas.py</font> (EventCreate).",
            "The fleet record already exists: <font face='Courier'>backend\\sql\\001_initial.sql</font> "
            "line 29 has <font face='Courier'>buses.registration_number</font>. Resolve at read time - "
            "no new column, no SCHEMA_VERSION bump, the deployed database must keep starting.",
            "The fleet value is truth, the OCR plate is evidence. If they disagree, keep the fleet "
            "value and set flag reason <font face='Courier'>plate_mismatch</font>.",
            "Bus 105 has no plate mounted. It must still get its fleet vehicle number - that is the "
            "whole point of this design.",
        ],
        tasks=[
            ("Set up the repo: clone, venv, install backend requirements, run the full test suite. Paste the exact 'N passed, M skipped' line into the tracker.", 90,
             "Test count in the tracker; no failures"),
            ("Read the event path end to end (app.py, services.py, schemas.py, db.py) and write a one-page map of how a scan becomes an event row.", 60,
             "One-page map pasted in the row's Notes"),
            ("Create branch <font face='Courier'>feat/sutharson-vehicle-number</font>. Start the fleet lookup: registration_number -> vehicle_number, source 'fleet'.", 120,
             "Branch pushed; lookup returns a value for bus 57"),
            ("Finish the lookup for GET /api/events and GET /api/events/&lt;id&gt;. Tests: registered bus -> fleet value; unknown bus -> 'none' + unregistered_plate flag.", 120,
             "Two passing tests; sample JSON in the row"),
            ("EXAM DAY - 30 minutes only: run the tests, push the branch, open a DRAFT pull request.", 30,
             "Draft PR link"),
            ("EXAM DAY - 30 minutes: read the review comments and fix anything small.", 30,
             "Comment replied / fixed"),
            ("EXAM DAY - 30 minutes: update the tracker and post the standup note. No coding.", 30,
             "Tracker updated"),
            ("EXAM DAY - 45 minutes: add the 'Vehicle number' column to the CSV and XLSX export.", 45,
             "Exported file with the header row"),
            ("plate_mismatch flag when the OCR plate disagrees with the fleet value (fleet wins). Tests for all three cases.", 120,
             "Three passing tests"),
            ("Make scripts/gate_acceptance.py assert the 12 ground-truth rows and exit non-zero on any mismatch. It must FAIL on '19'.", 120,
             "Full output with 'X passed, Y failed'"),
            ("Set VISION_PLATE_MODE=always in the gate config. Show busimage1 second bus = null + TN 48 BK 2129.", 90,
             "Acceptance output showing the correct pair"),
            ("Close the pull request: four CI jobs green, review approved, merge, tag v1.0.0.", 90,
             "Merged PR + tag"),
            ("Final evidence pack: test counts, acceptance output, PR link. Hand over to Hariharan.", 60,
             "Evidence pack in the Drive folder"),
        ],
    ),
    dict(
        name="SARAN C", reg="814725105045", email="814725105045@trp.srmtrichy.edu.in",
        phone="7907354483", role="Frontend Developer",
        slug="saran", branch="feat/saran-vehicle-number-ui",
        mission=("You own what the operator actually sees. The new vehicle number has to appear on the "
                 "dashboard and in the exports, the branding has to come from the real logo, and the "
                 "three camera lights have to explain themselves without a manual."),
        owns=[
            "Vehicle number column in the dashboard logs table (reads the API field)",
            "Favicon set + header logo generated from the team's logo file",
            "Tooltips / one-sentence advice for Light, Focus, Size",
            "Export button verified against the new column",
            "Screenshot pack for the runbook and final status document",
            "Images for the Windows installer wizard (handed to Vijay)",
        ],
        setup=[
            "Start the app first: <font face='Courier'>python desktop\\gate\\launcher.py</font> then open "
            "<font face='Courier'>http://127.0.0.1:8080</font> and log in as the admin account.",
            "All HTML lives in <font face='Courier'>frontend\\</font>, CSS in "
            "<font face='Courier'>frontend\\assets\\</font>, JS next to the pages. No build step, no npm.",
            "Refresh with <b>Ctrl+F5</b> - the browser caches hard here.",
            "Never edit files under <font face='Courier'>local_media\\</font> and never commit images "
            "larger than 2 MB.",
        ],
        tips=[
            "Show an em dash (&mdash;) when vehicle_number is null. Never show 'undefined' or 'null'.",
            "Ask Sutharson for one real JSON response before you start, so you code against reality "
            "and not a guess.",
            "Keep the existing layout. You are swapping an image and adding a column, not redesigning.",
            "Test every page at 360 px wide in the phone browser - Harishwaran will check it on his "
            "phone the same week.",
        ],
        tasks=[
            ("Create GitHub account, install Git, clone the repo, start the portal and log in. Screenshot the running dashboard into the tracker.", 90,
             "Screenshot + clone working"),
            ("Branding: from logo.png generate favicon.ico (16/32/48/64/128/256) and replace the header logo.", 90,
             "New favicon visible in the tab"),
            ("Add the 'Vehicle number' column to the dashboard logs table. Reads the new API field, shows &mdash; when null.", 120,
             "Screenshot with a real row"),
            ("Accessibility + responsive pass on the new column (keyboard, focus-visible, horizontal scroll under 480 px).", 60,
             "Short note per item checked"),
            ("EXAM DAY - 30 minutes: push the branch and open a DRAFT pull request.", 30,
             "Draft PR link"),
            ("EXAM DAY - 30 minutes: PR review fixes.", 30,
             "Fixed"),
            ("EXAM DAY - 30 minutes: tracker + standup note.", 30,
             "Tracker updated"),
            ("EXAM DAY - 45 minutes: mobile Q&amp;A of the dashboard on a phone browser with Harishwaran; file what breaks as a GitHub issue.", 45,
             "Issue links"),
            ("Verify the export button: CSV and XLSX must both carry the Vehicle number column, and the error state must be readable.", 90,
             "Both files attached to the row"),
            ("Tooltips / help text for Light, Focus and Size - one sentence per colour, plain language.", 90,
             "Screenshot of the help open"),
            ("Prepare installer images for Vijay: app.ico, 256 px PNG, wizard banner. Put them in the branch.", 60,
             "Files in the PR"),
            ("Final UI review on the installed build (or the batch launcher): three real screens, list every defect.", 60,
             "Defect list"),
            ("Screenshot pack for docs/FINAL_STATUS.md and the runbook images.", 60,
             "Folder link in the tracker"),
        ],
    ),
    dict(
        name="VIJAY M", reg="814725105055", email="814725105055@trp.srmtrichy.edu.in",
        phone="7339698587", role="Co-Developer / Packaging &amp; Camera",
        slug="vijay", branch="feat/vijay-gate-package",
        mission=("You own the thing that has never existed yet: something double-clickable on the gate "
                 "PC. Either a real Windows installer, or - if the build keeps failing - the honest "
                 "fallback (batch launcher + desktop shortcut + scheduled task at boot). You also own "
                 "the camera wiring, because until CAMERA_SOURCE is set the gate runs on a browser "
                 "webcam."),
        owns=[
            "PyInstaller bundle: dependency fix, bundle content, first-run paths",
            "Inno Setup installer, or the documented batch-launcher fallback",
            "CAMERA_SOURCE for http snapshot / rtsp / usb, each with a readable failure message",
            "Live replay test: 8 buses, no duplicates, stable memory",
            "Release ZIP + SHA256 checksum",
            "Install on the gate PC together with the team lead",
        ],
        setup=[
            "Install <b>Python 3.11</b> and <b>Inno Setup 6</b> (jrsoftware.org/isdl.php).",
            "The build script: <font face='Courier'>desktop\\gate\\build_gate.ps1</font> - run it in "
            "<b>PowerShell</b> as a normal user, not as administrator.",
            "Known trap: the requirements pull a vision stack with <b>no detector</b>. "
            "<font face='Courier'>pip install ultralytics --no-deps</font> is required, plus CPU-only "
            "torch and exactly one <font face='Courier'>opencv-python-headless</font>.",
            "Record the <b>exact</b> failing line when a build fails. &quot;It didn't work&quot; cannot "
            "be fixed; a pasted error can.",
        ],
        tips=[
            "Time-box the build: 90 minutes per attempt, then write down the error and move to the "
            "fallback. Do not lose two days to PyInstaller.",
            "<font face='Courier'>start_gate.bat</font> + a desktop shortcut + a scheduled task is a "
            "legitimate delivery. Say clearly which one you are shipping - never claim an installer "
            "you did not build.",
            "For RTSP you need MediaMTX or ffmpeg in front of the camera. Say so in the report instead "
            "of pretending it works.",
            "Never write config or logs next to the exe in Program Files - everything goes to "
            "<font face='Courier'>%APPDATA%\\VisionAI</font>.",
        ],
        tasks=[
            ("GitHub account, Git, clone, run the app. Click every page and list what is broken in the tracker.", 90,
             "Broken-things list"),
            ("Packaging attempt A: run build_gate.ps1. Paste the exact failing lines into the tracker row.", 120,
             "Error text pasted"),
            ("Fix the dependency errors (ultralytics --no-deps, CPU torch, one cv2). Rebuild.", 120,
             "Build gets further; new error or success"),
            ("Bundle content check: frontend/, best.pt, anpr_best.pt, weights/vehicle.pt, RapidOCR models. Read VisionAI.spec.", 90,
             "Checklist with each item ticked"),
            ("EXAM DAY - 30 minutes: push the branch and open a DRAFT pull request.", 30,
             "Draft PR link"),
            ("EXAM DAY - 30 minutes: review fixes.", 30,
             "Fixed"),
            ("EXAM DAY - 30 minutes: tracker + standup note.", 30,
             "Tracker updated"),
            ("EXAM DAY - 45 minutes: attempt the Inno Setup compile. Record the outcome either way.", 45,
             "Outcome recorded"),
            ("Branch on the result: installer works -> install on a clean machine; installer fails -> build the batch-launcher release ZIP (start_gate.bat + shortcut + scheduled task).", 120,
             "Installer .exe or ZIP, with a path"),
            ("CAMERA_SOURCE: wire http snapshot, rtsp and usb:0. Test that each one fails with a readable message when the camera is absent.", 120,
             "Three results in the tracker"),
            ("Live replay: busvideo1.mp4 through the live path. 8 buses -> 8 events, no duplicates while a bus stays in frame, memory stable for 10 minutes.", 90,
             "Event list + memory before/after"),
            ("Final package + SHA256 checksum file.", 90,
             "Zip path + checksum"),
            ("Install on the gate PC with Hariharan. Three real scans. Evidence in the Drive folder.", 90,
             "Photos + event list"),
        ],
    ),
    dict(
        name="HARISHWARAN S", reg="814725105015", email="814725105015@trp.srmtrichy.edu.in",
        phone="8608883557", role="Database Developer (phone-only track)",
        slug="harishwaran", branch="docs/harishwaran-runbook",
        phone_only=True,
        mission=("You have no laptop this sprint, so we built your track around a phone and AI: data, "
                 "test cases, QA and documentation. That is not a lesser track - the runbook and the "
                 "fleet data are what make the product usable by someone who has never seen it. You "
                 "pair with Haris Krishna when something needs a laptop: he drives, you navigate."),
        owns=[
            "The fleet list: every bus number with its registration number",
            "Six manual test cases for the vehicle number feature",
            "docs/RUNBOOK.md - the operator's one page",
            "The 'what is not delivered and why' + FAQ section of docs/FINAL_STATUS.md",
            "Phone QA of the live portal and the dashboard",
            "Proofreading of every document before it ships",
        ],
        setup=[
            "No installation needed. Everything below works in a phone browser.",
            "<b>GitHub app</b> (Android/iOS) for reading code and filing issues. Create the account at "
            "github.com in Chrome - use the college email.",
            "<b>Google Docs</b> for writing documents; the leader or Haris Krishna pastes them into the "
            "repository.",
            "Use the AI assistant for first drafts (test cases, runbook wording, SQL), then check every "
            "line yourself - an unverified AI answer is not evidence.",
            "Keep a charger and use campus Wi-Fi for uploads; photos of screens count as evidence.",
        ],
        tips=[
            "You can file GitHub issues from the phone app - that is how you report a bug you found in "
            "QA. Title: &quot;[QA] what broke + screen&quot;.",
            "Write the runbook for a security guard, not for an engineer. If a sentence needs code to "
            "explain it, rewrite it.",
            "Fleet data: bus number (the sticker number), registration number, campus, route if known. "
            "Ask the transport office - one conversation beats guessing 40 rows.",
            "Pair with Haris Krishna on Saturday 15th for anything that needs a laptop (running the "
            "seed, opening the database).",
        ],
        tasks=[
            ("Create the GitHub account from the phone browser and install the GitHub app. Send your username to the group.", 45,
             "Username in the group chat"),
            ("Fleet data: fill bus number <-> registration number for every bus the college runs. One row per bus, in the tracker's Fleet tab.", 60,
             "Fleet table filled"),
            ("Read backend/sql/001_initial.sql in the GitHub app. Write a one-page field glossary: what each table and column means.", 60,
             "Glossary in Google Docs"),
            ("Write six manual test cases for the vehicle number: registered bus, unknown bus, plate mismatch, no plate (bus 105), CSV export, phone view.", 60,
             "Six cases in the tracker"),
            ("EXAM DAY - 15 minutes: standup note only.", 15,
             "Note posted"),
            ("EXAM DAY - 30 minutes: phone QA of the live portal (login, events list, filters). File each bug as a GitHub issue from the app.", 30,
             "Issue links"),
            ("EXAM DAY - 15 minutes: tracker update.", 15,
             "Tracker updated"),
            ("EXAM DAY - 30 minutes: mobile Q&amp;A of the dashboard with Saran; screenshots in the tracker.", 30,
             "Screenshots"),
            ("Write docs/RUNBOOK.md: start the app, what the three lights mean, what to do per colour, reinstall, report, support contact. One page.", 90,
             "Doc link"),
            ("Write the 'what is not delivered and why' section + FAQ for docs/FINAL_STATUS.md (video plates, AGPL, code signing).", 90,
             "Doc link"),
            ("Verify the CSV export against your six test cases, opened on the phone.", 60,
             "Results per case"),
            ("Proofread RUNBOOK, FINAL_STATUS and the invitation email. Report typos with line references.", 60,
             "Typo list"),
            ("Final fleet check: every bus in the seed file has a registration number. List any gaps to Hariharan.", 60,
             "Gap list (or 'none')"),
        ],
    ),
    dict(
        name="HARIS KRISHNA M J", reg="814725105016", email="814725105016@trp.srmtrichy.edu.in",
        phone="8903842733", role="Co-Developer / Database",
        slug="hariskrishna", branch="feat/hariskrishna-fleet-seed",
        mission=("You own the data the whole feature stands on. The vehicle number is a lookup, and a "
                 "lookup is only as good as its table. You seed the fleet, prove the query is fast, "
                 "and make sure the deployed database keeps starting. You also pair with Harishwaran, "
                 "who has no laptop: he navigates, you drive."),
        owns=[
            "Fleet seed: bus_number + registration_number for every bus in service",
            "Local dev database loaded and verified",
            "Lookup query + index, with a measured time",
            "Proof that no SCHEMA_VERSION bump is needed (read-time resolution)",
            "Backup and restore test of gate.db",
            "Deployed Supabase database still starts",
        ],
        setup=[
            "Install <b>Python 3.11</b>, Git, and optionally <b>DB Browser for SQLite</b>.",
            "Local database for testing: <font face='Courier'>DATABASE_URL=sqlite:///local_media/dev.db</font>",
            "The schema lives in <font face='Courier'>backend\\sql\\001_initial.sql</font>; migrations "
            "are applied by <font face='Courier'>backend\\db.py</font>.",
            "Never point your laptop at the production database. Never print DATABASE_URL or passwords.",
        ],
        tips=[
            "The deployed Supabase database is at schema v1 and must keep starting. A read-time lookup "
            "needs no migration - prove that and write it down.",
            "Seed data must be realistic: 40-ish buses with the real registration formats (TN 48 BH 6091).",
            "Measure the query - a number beats an opinion. Target: under 5 ms for one bus.",
            "Pair session with Harishwaran: Saturday 15th, 1 hour. You drive, he checks the data.",
        ],
        tasks=[
            ("GitHub, Git, clone, venv, confirm <font face='Courier'>python -m pytest -q</font> runs on your machine.", 90,
             "Test count in the tracker"),
            ("Write the fleet seed script: bus_number + registration_number (+ campus where known).", 120,
             "Script in the branch"),
            ("Load the seed into your local database and verify the row count.", 90,
             "Row count + query output"),
            ("Check the lookup query and its index; measure the time for one bus and for all buses.", 60,
             "Two timings"),
            ("EXAM DAY - 30 minutes: push the branch and open a DRAFT pull request.", 30,
             "Draft PR link"),
            ("EXAM DAY - 30 minutes: review fixes.", 30,
             "Fixed"),
            ("EXAM DAY - 30 minutes: tracker + standup note.", 30,
             "Tracker updated"),
            ("EXAM DAY - 45 minutes: backup and restore test of the gate database.", 45,
             "Restore verified"),
            ("Confirm no SCHEMA_VERSION change is needed for a read-time lookup. Write the reasoning in docs/ one paragraph.", 60,
             "Paragraph in the PR"),
            ("Export integrity: null handling, CSV escaping, XLSX header row.", 60,
             "Sample rows"),
            ("Tests for the fleet seed and the lookup.", 90,
             "Passing tests"),
            ("Confirm the deployed Supabase database (schema transport_portal) still starts and answers; paste the check.", 60,
             "Output pasted"),
            ("Database evidence pack + handover note for Hariharan.", 60,
             "Evidence pack"),
        ],
    ),
]

SHARED_DOD = [
    "Four CI jobs green on the pull request (Backend, Vision, Frontend, Secret scan).",
    "12/12 bus numbers and 3/3 still plates still pass - the detector is frozen, nobody tunes it.",
    "Every event shows a vehicle number (fleet record), with plate_mismatch flagged when the plate disagrees.",
    "The gate PC runs the app from a shortcut, reads a real bus, and the event appears on the portal.",
    "docs/RUNBOOK.md exists and a person who has never seen the project can start it.",
    "Everything in the tracker is marked Done with evidence, or Blocked with a reason.",
]

RULES = [
    "<b>Never push to main.</b> Always a branch, always a pull request, always reviewed by Hariharan.",
    "One task = one branch = one pull request. Keep PRs small enough to review in 15 minutes.",
    "<b>Evidence or it didn't happen.</b> Command + output, screenshot, or PR link. &quot;Done&quot; without evidence is Not started.",
    "Never commit videos, photos, <font face='Courier'>.pt</font> models or <font face='Courier'>.env</font> files. If a file is over 2 MB, stop.",
    "Never print DATABASE_URL, JWT_SECRET or any key in chat, in a document or in a commit.",
    "<b>The detector is frozen.</b> Do not change models, thresholds, tiling, image sizes or the 12 ground-truth rows.",
    "Update your tracker row before you sleep. Two minutes. It is the only reason the dashboard works.",
    "Blocked for more than 30 minutes? Set Status = Blocked, write one line, message the group. Do not spin.",
    "Practical exam days: 30 minutes maximum, only the small task listed for that day.",
    "Ask early. A question on 14 Nov costs minutes; the same question on 24 Nov costs the sprint.",
]

GIT_STEPS = [
    ("Step 1 - Create the GitHub account", [
        "Open <b>github.com</b> and click <b>Sign up</b>. Use your college email "
        "(<font face='Courier'>8147251xxxxx@trp.srmtrichy.edu.in</font>).",
        "Pick a username that is recognisable: <font face='Courier'>sutharson-r</font>, <font face='Courier'>saran-c</font>, etc.",
        "Free plan. Verify the email (check spam). Set a profile photo so the team recognises you in reviews.",
    ]),
    ("Step 2 - Install Git on Windows", [
        "Download from <b>git-scm.com/download/win</b> and run the installer: Next, Next, Next, Install.",
        "Prefer a visual tool? Install <b>GitHub Desktop</b> from <b>desktop.github.com</b> - it signs you in "
        "with the browser and avoids tokens. Both do the same thing.",
        "Check it worked: open <b>Git Bash</b> and type <font face='Courier'>git --version</font>.",
    ]),
    ("Step 3 - Tell Git who you are", [
        "<font face='Courier'>git config --global user.name &quot;Your Full Name&quot;</font>",
        "<font face='Courier'>git config --global user.email &quot;8147251xxxxx@trp.srmtrichy.edu.in&quot;</font>",
        "This name appears on every commit. Use the same email as GitHub or the commits will not link to your account.",
    ]),
    ("Step 4 - Log in (command line only)", [
        "GitHub - Settings - Developer settings - Personal access tokens - <b>Tokens (classic)</b> - "
        "Generate new token. Tick <b>repo</b> and <b>workflow</b>. Expiry: 30 days.",
        "Copy the token once. When Git asks for a password, paste the <b>token</b>, not your GitHub password.",
        "Never paste the token into chat, an email or a file in the repo. If it leaks, delete it on GitHub and make a new one.",
    ]),
    ("Step 5 - Clone the project", [
        "<font face='Courier'>cd %USERPROFILE%\\Documents</font>",
        "<font face='Courier'>git clone https://github.com/saran-44/VISION-AI-SRM-TRP.git</font>",
        "<font face='Courier'>cd VISION-AI-SRM-TRP</font>",
        "Open the folder in VS Code: <font face='Courier'>code .</font>",
    ]),
    ("Step 6 - The daily loop (learn these five commands)", [
        "<font face='Courier'>git switch main</font> &nbsp;&nbsp; - go to the shared branch",
        "<font face='Courier'>git pull</font> &nbsp;&nbsp; - get everyone else's merged work first",
        "<font face='Courier'>git switch -c feat/&lt;yourname&gt;-&lt;topic&gt;</font> &nbsp;&nbsp; - your own branch",
        "Do your work, then <font face='Courier'>git status</font> to see what changed",
        "<font face='Courier'>git add -A</font> then "
        "<font face='Courier'>git commit -m &quot;feat(events): resolve vehicle number&quot;</font>",
        "<font face='Courier'>git push -u origin feat/&lt;yourname&gt;-&lt;topic&gt;</font>",
    ]),
    ("Step 7 - Open the pull request", [
        "GitHub shows a green <b>Compare &amp; pull request</b> button after a push. Click it.",
        "Title: <font face='Courier'>feat(events): resolve vehicle number from fleet record</font>",
        "Description: what changed, why, and how you proved it (test output, screenshot, link).",
        "Reviewers: <b>Hariharan</b>. Leave it as a Draft until your task is actually finished.",
    ]),
    ("Step 8 - Review, fix, merge", [
        "Read every comment. Push fixes to the <b>same branch</b> - the PR updates itself, do not open a second PR.",
        "You never merge your own PR. The leader merges after the four CI jobs turn green.",
        "After the merge: <font face='Courier'>git switch main</font> and <font face='Courier'>git pull</font>.",
    ]),
]

GIT_ERRORS = [
    ("Authentication failed", "Your GitHub password is not accepted any more. Paste the <b>token</b> as the password, "
                              "or use GitHub Desktop's browser sign-in."),
    ("Updates were rejected / non-fast-forward", "Someone merged before you. Run "
                                                 "<font face='Courier'>git pull --rebase</font>, fix anything it complains about, push again."),
    ("src refspec does not match any", "You never committed. <font face='Courier'>git add -A</font> then commit, then push."),
    ("I committed a video or a .pt model", "Do not force-push. Tell Hariharan on the group. It gets fixed from the leader side."),
    ("LF will be replaced by CRLF", "Harmless Windows warning. Ignore it."),
    ("I am on the wrong branch", "<font face='Courier'>git switch &lt;branch&gt;</font>. If you have uncommitted work, commit it on a "
                                 "throwaway branch first - do not lose an hour of typing."),
]

RITUAL = [
    "Open the spreadsheet tab with your name.",
    "Find the row for today's date.",
    "Set <b>Status</b>: Not started / In progress / Blocked / Done.",
    "Paste <b>Evidence</b>: the command and its output, a screenshot link, or the PR link.",
    "Write <b>Notes</b> in one line: what worked, what you are stuck on, what you need from whom.",
    "Tick the <b>Updated</b> column with today's date. That is your daily standup - no meeting needed.",
]


# ----------------------------------------------------------------------------- pdf plumbing
class Doc(BaseDocTemplate):
    def __init__(self, path, member, **kw):
        BaseDocTemplate.__init__(self, path, pagesize=A4,
                                 leftMargin=16 * mm, rightMargin=16 * mm,
                                 topMargin=16 * mm, bottomMargin=16 * mm,
                                 title=f"{member['name']} - VISION AI sprint plan",
                                 author=LEAD["name"], **kw)
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="n")
        self.addPageTemplates([PageTemplate(id="all", frames=[frame], onPage=self._deco)])
        self.member = member

    def _deco(self, canv, doc):
        canv.saveState()
        canv.setStrokeColor(LINE)
        canv.setLineWidth(0.6)
        canv.line(16 * mm, 12 * mm, A4[0] - 16 * mm, 12 * mm)
        canv.setFont("Helvetica", 7.4)
        canv.setFillColor(GREY)
        canv.drawString(16 * mm, 8 * mm, "VISION AI - SRM TRP  |  Sprint 13-25 Nov 2026  |  confidential, team only")
        canv.drawRightString(A4[0] - 16 * mm, 8 * mm, f"{self.member['name']}  -  page {doc.page}")
        canv.restoreState()


def cover(m):
    flow = [Spacer(1, 26 * mm),
            P("VISION AI &mdash; SRM TRP", st("k", fontName="Helvetica-Bold", fontSize=10,
                                               textColor=ACCENT, leading=13)),
            Spacer(1, 4 * mm),
            P("Sprint Work Plan", TITLE),
            Spacer(1, 2 * mm),
            P("13 &ndash; 25 November 2026 &nbsp;&bull;&nbsp; 13 days &nbsp;&bull;&nbsp; 5 people &nbsp;&bull;&nbsp; one launch", SUB),
            Spacer(1, 12 * mm)]

    data = [
        [P("Team member", CELLB), P(m["name"], CELL)],
        [P("Registration No.", CELLB), P(m["reg"], CELL)],
        [P("Role in this sprint", CELLB), P(m["role"], CELL)],
        [P("Official mail", CELLB), P(m["email"], CELL)],
        [P("Mobile", CELLB), P("+91 " + m["phone"], CELL)],
        [P("Your branch", CELLB), P(m["branch"], CODE)],
        [P("Sprint owner", CELLB), P(f"{LEAD['name']} (Team Lead) &nbsp;&bull;&nbsp; +91 {LEAD['phone']}", CELL)],
        [P("Final deadline", CELLB), P("Wednesday 25 November 2026, end of day", CELL)],
    ]
    t = Table(data, colWidths=[38 * mm, 106 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ]))
    flow += [t, Spacer(1, 14 * mm)]

    box = Table([[P("<b>Read this first.</b> You are not being asked to understand the whole system. "
                    "You are being asked to own ten small steps, in order, and to write down what you did. "
                    "Every task below is sized for one sitting, has a definition of done, and has a place "
                    "in the tracker. If a day goes wrong, say so in the sheet the same evening - that is "
                    "how the plan survives.", CELL)]], colWidths=[144 * mm])
    box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), LIGHT),
                             ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                             ("LEFTPADDING", (0, 0), (-1, -1), 8),
                             ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                             ("TOPPADDING", (0, 0), (-1, -1), 8),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    flow += [box, Spacer(1, 10 * mm)]

    flow.append(P("What is inside", H2))
    toc = [("1", "Your mission - what you own and where the project stands"),
           ("2", "The calendar, including the practical-exam days"),
           ("3", "Your thirteen days, one row per day, with a definition of done"),
           ("4", "Set up your machine, and the traps to avoid"),
           ("5", "GitHub from zero - account to merged pull request"),
           ("6", "Your two minutes in the tracker, the ten rules, who to ask"),
           ("9", "A checklist you can print and tick")]
    rows = [[P("<b>" + a + "</b>", CELL), P(b, CELL)] for a, b in toc]
    t2 = Table(rows, colWidths=[10 * mm, 134 * mm])
    t2.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("LINEBELOW", (0, 0), (-1, -1), 0.3, LINE),
                            ("TOPPADDING", (0, 0), (-1, -1), 3),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                            ("LEFTPADDING", (0, 0), (-1, -1), 2)]))
    flow += [t2, Spacer(1, 8 * mm)]
    flow.append(P("Prepared by " + LEAD["name"] + ", Team Lead &nbsp;&bull;&nbsp; issued 13 November 2026 "
                  "&nbsp;&bull;&nbsp; the tracker spreadsheet is live and is the source of truth for "
                  "progress, this document is the plan.", SMALL))
    flow += [PageBreak()]
    return flow


def mission(m):
    flow = [P("1. Your mission", H1), P(m["mission"]), Spacer(1, 3 * mm)]
    flow += [P("What you own", H2)]
    flow += bullets(m["owns"])
    flow += [Spacer(1, 3 * mm), P("Where the project stands today (so you know what you are joining)", H2)]
    flow += bullets([
        "The detector reads <b>12/12</b> bus sticker numbers and <b>3/3</b> still-image number plates. It is frozen - nobody tunes it this sprint.",
        "The four blocking CI jobs are green. The Windows build job still fails, which is exactly why Vijay owns packaging.",
        "The bus's <b>vehicle number is not stored anywhere yet</b> - it exists only inside an offline benchmark script. That is Sutharson's job, and the reason Saran has a column to add.",
        "The gate app already starts on a Windows PC (<font face='Courier'>launcher.py</font>, preflight checks, port handling). Its camera is not configured yet - that is Vijay's.",
        "There is no installer yet. There is an honest fallback (batch launcher + shortcut + scheduled task), which counts as a delivery if the build fights us.",
    ])
    flow += [Spacer(1, 4 * mm), P("Definition of done for the whole project", H2)]
    flow += bullets(SHARED_DOD)
    flow += [PageBreak()]
    return flow


def calendar(m):
    flow = [P("2. The calendar, and why it looks like this", H1),
            P("Thirteen days, ending Wednesday 25 November. Normal days are 1.5&ndash;2 hours after "
              "college. <b>Tue 17 to Fri 20 November are treated as practical-exam days</b>: 15&ndash;45 "
              "minutes only, and only the small task listed. Weekend days carry the heavier blocks."),
            Spacer(1, 3 * mm)]

    rows = [[P("Date", CELLH), P("Load", CELLH), P("What happens", CELLH)]]
    plan = [("Fri 13 Nov", "start", "Setup, first commit, first pull request"),
            ("Sat 14 &ndash; Sun 15 Nov", "heavy", "First real task lands on your branch"),
            ("Mon 16 Nov", "normal", "Finish the feature, keep it reviewable"),
            ("Tue 17 &ndash; Fri 20 Nov", "exam", "30 minutes a day: push, fix, update the tracker"),
            ("Sat 21 &ndash; Sun 22 Nov", "heavy", "The two biggest tasks of your track"),
            ("Mon 23 &ndash; Tue 24 Nov", "normal", "Integration, CI green, merge"),
            ("Wed 25 Nov", "normal", "Evidence packs, install on the gate PC, handover")]
    for d, load, what in plan:
        mark = {"start": "Start", "heavy": "2 h", "normal": "1.5 h", "exam": "30 min"}[load]
        rows.append([P(d, CELL), P(mark, CELL), P(what, CELL)])

    t = Table(rows, colWidths=[42 * mm, 22 * mm, 80 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f9fc")]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    flow += [t, Spacer(1, 4 * mm)]
    flow.append(P("<i>Assumption:</i> your practical exams fall between 17 and 20 November. If your "
                  "dates are different, tell Hariharan on day one and he moves the light days - the "
                  "plan is built to be shifted, not to be broken.", SMALL))
    if m.get("phone_only"):
        flow += [Spacer(1, 4 * mm), P("Your track and the no-laptop rule", H2),
                 P("You are not blocked by hardware. Everything assigned to you runs in a phone "
                   "browser: creating the GitHub account, reading code in the GitHub app, filing "
                   "issues, writing the runbook in Google Docs, filling the fleet data, and doing "
                   "QA on the live portal. Where you need a laptop (running the seed, opening the "
                   "database, pasting a document into the repository), <b>Haris Krishna drives and "
                   "you navigate</b> - Saturday 15th and again on 21st. Write it in the tracker as a "
                   "pair task so nobody thinks the work vanished.", BODY)]
    flow += [PageBreak()]
    return flow


def tasks_table(m):
    flow = [P("3. Your thirteen days", H1),
            P("One row per day. The last column is the definition of done - copy it into your tracker "
              "row when you finish. Times are generous on purpose; if a task takes longer, stop and "
              "write down where it stuck."), Spacer(1, 3 * mm)]

    rows = [[P("Day", CELLH), P("Task", CELLH), P("Time", CELLH), P("Done means", CELLH)]]
    style = [("BACKGROUND", (0, 0), (-1, 0), NAVY),
             ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
             ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("GRID", (0, 0), (-1, -1), 0.4, LINE),
             ("TOPPADDING", (0, 0), (-1, -1), 4),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
             ("LEFTPADDING", (0, 0), (-1, -1), 4),
             ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
    for i, (task, mins, done) in enumerate(m["tasks"]):
        date = DATES[i]
        label = f"<b>{date}</b>"
        if i in EXAM:
            label += "<br/><font size=6.5 color='#9a6700'>EXAM</font>"
        rows.append([P(label, CELL), P(task, CELL), P(f"{mins}m", CELL), P(done, CELL)])
        if i in EXAM:
            style.append(("BACKGROUND", (0, i + 1), (-1, i + 1), colors.HexColor("#fff9ec")))

    t = Table(rows, colWidths=[20 * mm, 74 * mm, 12 * mm, 38 * mm], repeatRows=1)
    t.setStyle(TableStyle(style))
    flow += [t, PageBreak()]
    return flow


def setup(m):
    flow = [P("4. Set up your machine (once, 30&ndash;45 minutes)", H1)]
    flow += bullets(m["setup"])
    flow += [Spacer(1, 4 * mm), P("Things that will save you an hour", H2)]
    flow += bullets(m["tips"])
    flow += [Spacer(1, 5 * mm)]

    box = Table([[P("<b>The one rule that matters most:</b> never work on <font face='Courier'>main</font>. "
                    "Everything you do happens on <font face='Courier'>" + m["branch"] +
                    "</font> and reaches the project through a pull request. If you break your own branch, "
                    "nobody else is affected, and the leader can help you fix it in minutes.", CELL)]],
                colWidths=[144 * mm])
    box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fff4f2")),
                             ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#e5b3ab")),
                             ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                             ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    flow += [box, PageBreak()]
    return flow


def github(m):
    flow = [P("5. GitHub from zero - account to pull request", H1),
            P("You have never used GitHub. This section is the whole thing, in order, with the exact "
              "commands. Do not skip step 3: commits with the wrong email do not link to your account "
              "and your work looks invisible on the dashboard."), Spacer(1, 3 * mm)]

    for title, items in GIT_STEPS:
        flow.append(P(title, H2))
        flow += bullets(items)

    flow += [Spacer(1, 3 * mm), P("When something goes wrong", H2)]
    rows = [[P("Message", CELLH), P("What it means and what to do", CELLH)]]
    for a, b in GIT_ERRORS:
        rows.append([P(a, CODE), P(b, CELL)])
    t = Table(rows, colWidths=[52 * mm, 92 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), LIGHT),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("GRID", (0, 0), (-1, -1), 0.4, LINE),
                           ("TOPPADDING", (0, 0), (-1, -1), 4),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    flow += [t, PageBreak()]
    return flow


def tracker_and_rules(m):
    flow = [P("6. Your daily two minutes in the tracker", H1),
            P("The spreadsheet has one tab per person and a dashboard the leader reads every night. "
              "It only works if you update it. Nobody will chase you for it - a silent row is treated "
              "as no progress."), Spacer(1, 2 * mm)]
    for i, step in enumerate(RITUAL, 1):
        flow.append(P(f"<b>{i}.</b> {step}", CELL))
    flow += [Spacer(1, 5 * mm), P("7. The ten rules of this sprint", H1)]
    for i, r in enumerate(RULES, 1):
        flow.append(P(f"<b>{i}.</b> {r}", CELL))
    flow += [Spacer(1, 5 * mm), P("8. Who to ask", H1)]
    rows = [[P("Situation", CELLH), P("Who", CELLH)]]
    for a, b in [("Git, branches, pull requests, merge conflicts", "Hariharan (lead) - any time"),
                 ("Backend, API, vehicle number, tests", "Sutharson (co-lead)"),
                 ("UI, CSS, dashboard, screenshots", "Saran, then Vijay"),
                 ("Windows build, installer, camera", "Vijay"),
                 ("Database, seed data, exports", "Haris Krishna"),
                 ("Documents, runbook, QA, fleet list", "Harishwaran")]:
        rows.append([P(a, CELL), P(b, CELL)])
    t = Table(rows, colWidths=[90 * mm, 54 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), LIGHT),
                           ("GRID", (0, 0), (-1, -1), 0.4, LINE),
                           ("TOPPADDING", (0, 0), (-1, -1), 4),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    flow += [t, Spacer(1, 5 * mm),
             P("Group chat is the default channel. Anything that changes a plan goes in the group, not "
               "in a private message, so the leader can see it and the tracker stays truthful.", SMALL),
             PageBreak()]
    return flow


def checklist(m):
    flow = [P("9. Your checklist - print this page", H1),
            P("Tick as you go. If a box is unticked on 24 November, that is the conversation."), Spacer(1, 3 * mm)]
    rows = [[P("&#10003;", CELLH), P("Day", CELLH), P("Task (short)", CELLH), P("Page", CELLH)]]
    short = [t[0] for t in m["tasks"]]
    for i, s in enumerate(short):
        s = s.replace("EXAM DAY - ", "EXAM: ")
        if len(s) > 110:
            s = s[:107] + "..."
        rows.append([P("&#9744;", CELL), P(DATES[i], CELL), P(s, CELL), P("", CELL)])
    t = Table(rows, colWidths=[7 * mm, 22 * mm, 103 * mm, 12 * mm], repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                           ("GRID", (0, 0), (-1, -1), 0.4, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    flow += [t, Spacer(1, 6 * mm)]

    sign = Table([[P("Signed (member): ______________________", CELL), P("Date: ____________", CELL)],
                  [P("Reviewed (team lead): __________________", CELL), P("Date: ____________", CELL)]],
                 colWidths=[90 * mm, 54 * mm])
    sign.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 8)]))
    flow += [sign]
    return flow


def build(m):
    path = os.path.join(OUT, f"VISIONAI_Sprint_Plan_{m['name'].replace(' ', '_')}.pdf")
    doc = Doc(path, m)
    story = []
    story += cover(m)
    story += mission(m)
    story += calendar(m)
    story += tasks_table(m)
    story += setup(m)
    story += github(m)
    story += tracker_and_rules(m)
    story += checklist(m)
    doc.build(story)
    return path


LEAD_MATRIX = [
    ("SUTHARSON R", "Backend / co-lead", [
        "Repo + suite green; event path mapped",
        "Fleet lookup branch; tests for fleet + unknown bus",
        "Push, review fixes, tracker",
        "plate_mismatch; acceptance asserts the 12 rows",
        "Plate mode always; CI green; merge; tag v1.0.0",
        "Evidence pack"]),
    ("SARAN C", "Frontend", [
        "Account, clone, app running; favicon + logo",
        "Vehicle number column; accessibility pass",
        "Push, review fixes, tracker",
        "Export verify; three-light tooltips",
        "Installer images; UI review on the build",
        "Screenshot pack"]),
    ("VIJAY M", "Packaging / camera", [
        "Clone; build attempt A, errors pasted",
        "Dependency fix; bundle content check",
        "Push, review fixes; Inno attempt",
        "Installer or fallback ZIP; camera wiring",
        "Live replay; release + SHA256",
        "Install on the gate PC"]),
    ("HARISHWARAN S", "DB / docs (phone only)", [
        "GitHub app; fleet data started",
        "Field glossary; six test cases",
        "Phone QA; bugs filed as issues",
        "RUNBOOK; FINAL_STATUS section",
        "CSV verification; proofreading",
        "Fleet completeness check"]),
    ("HARIS KRISHNA M J", "Database", [
        "Environment; fleet seed script",
        "Seed loaded; query + index timed",
        "Push, review fixes; backup test",
        "No-schema-bump proof; export integrity",
        "Seed tests; deployed DB check",
        "DB evidence pack"]),
]

PHASES = ["13-14 Nov<br/>setup", "15-16 Nov<br/>build", "17-20 Nov<br/>exam, 30 min",
          "21-22 Nov<br/>heavy", "23-24 Nov<br/>integration", "25 Nov<br/>handover"]

CHECKPOINTS = [
    ("Sun 15 Nov", "Every member has at least one commit pushed to their own branch",
     "Anyone with zero commits gets a 15-minute call that evening. This is the only early warning you get."),
    ("Thu 19 Nov", "The API returns a vehicle number from the fleet record on Sutharson's machine",
     "If not, you write that code with him on Saturday - the whole feature depends on it."),
    ("Sun 22 Nov", "The acceptance script passes the 12 rows and no longer reports '19'",
     "If not: freeze scope, ship what works, mark the row PARTIAL in the report. Do not extend the date."),
    ("Tue 24 Nov", "Four CI jobs green and the pull request merged",
     "If red: merge only what is green, and record the failing job by name in the final status document."),
    ("Wed 25 Nov", "The app is installed on the gate PC and three real buses were scanned",
     "If the installer failed: ship the batch launcher, mark packaging PARTIAL, and say so plainly."),
]


def build_leader():
    lead = dict(name=LEAD["name"], reg=LEAD["reg"], email=LEAD["email"],
                phone=LEAD["phone"], role="Team Lead / Backend Developer",
                slug="leader", branch="main (review and merge only)")
    path = os.path.join(OUT, "VISIONAI_Team_Lead_Pack.pdf")
    doc = Doc(path, lead)

    flow = [Spacer(1, 24 * mm),
            P("VISION AI &mdash; SRM TRP", st("k2", fontName="Helvetica-Bold", fontSize=10,
                                               textColor=ACCENT, leading=13)),
            Spacer(1, 4 * mm),
            P("Team Lead Pack", TITLE),
            Spacer(1, 2 * mm),
            P("Sprint control, 13 &ndash; 25 November 2026 &nbsp;&bull;&nbsp; five members &nbsp;&bull;&nbsp; "
              "your ten minutes a day", SUB),
            Spacer(1, 10 * mm)]

    rows = [[P("Team lead", CELLB), P(f"{LEAD['name']} &nbsp;&bull;&nbsp; {LEAD['role']}", CELL)],
            [P("Sprint length", CELLB), P("13 days: Friday 13 November to Wednesday 25 November 2026", CELL)],
            [P("Team", CELLB), P("Sutharson (backend) - Saran (frontend) - Vijay (packaging/camera) - "
                                 "Harishwaran (docs/QA, phone only) - Haris Krishna (database)", CELL)],
            [P("Your role this sprint", CELLB), P("Review and merge, unblock, keep the tracker honest. "
                                                  "You do not code a member's task for them.", CELL)],
            [P("Tracker", CELLB), P("The VISION AI - TEAMS spreadsheet: Dashboard tab is yours, one tab per member", CELL)]]
    t = Table(rows, colWidths=[34 * mm, 110 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
                           ("TOPPADDING", (0, 0), (-1, -1), 4),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    flow += [t]

    # --- page 2: the sprint in one page
    flow += [PageBreak(), P("1. What has to be true on the evening of 25 November", H1)]
    flow += bullets(SHARED_DOD)
    flow += [Spacer(1, 4 * mm), P("What is being handed to whom", H2)]
    rows = [[P("Owner", CELLH), P("Track", CELLH), P("The one thing they must land", CELLH)]]
    for owner, track, thing in [
        ("SUTHARSON R", "Backend", "vehicle_number in the API and exports, fleet lookup, acceptance script tells the truth"),
        ("SARAN C", "Frontend", "the column on screen, branding from the real logo, lights explain themselves"),
        ("VIJAY M", "Packaging", "something double-clickable on the gate PC (installer or honest fallback) + camera wired"),
        ("HARISHWARAN S", "Docs / QA", "the runbook an operator can follow, and the fleet list that the lookup needs"),
        ("HARIS KRISHNA M J", "Database", "a seeded fleet, a fast lookup, and proof the deployed database still starts")]:
        rows.append([P(owner, CELLB), P(track, CELL), P(thing, CELL)])
    t = Table(rows, colWidths=[34 * mm, 24 * mm, 86 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("GRID", (0, 0), (-1, -1), 0.4, LINE),
                           ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f9fc")]),
                           ("TOPPADDING", (0, 0), (-1, -1), 4),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    flow += [t, Spacer(1, 5 * mm)]
    flow.append(P("<b>Scope discipline.</b> The detector is frozen: 12/12 bus numbers and 3/3 still "
                  "plates are accepted as final. The seven unreadable video plates stay documented as a "
                  "source limitation. If anyone proposes re-tuning the model this sprint, the answer is no.", CELL))

    # --- page 3: matrix
    flow += [PageBreak(), P("2. The whole sprint on one page", H1),
             P("Read across a row to see one person's sprint. Read down a column to see the pressure point "
               "of those days.", SMALL), Spacer(1, 2 * mm)]
    head = [P("Member", CELLH)] + [P(p, CELLH) for p in PHASES]
    rows = [head]
    for name, track, cells in LEAD_MATRIX:
        rows.append([P(f"<b>{name}</b><br/><font size=6.5>{track}</font>", CELL)] + [P(c, st("mx", fontSize=6.9, leading=9)) for c in cells])
    t = Table(rows, colWidths=[26 * mm] + [23.6 * mm] * 6, repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("GRID", (0, 0), (-1, -1), 0.4, LINE),
                           ("BACKGROUND", (3, 1), (3, -1), colors.HexColor("#fff9ec")),
                           ("TOPPADDING", (0, 0), (-1, -1), 3),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                           ("LEFTPADDING", (0, 0), (-1, -1), 3),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 3)]))
    flow += [t, Spacer(1, 3 * mm)]
    flow.append(P("Amber column = practical-exam window. Thirty minutes a day, small tasks only: push, "
                  "fix a review comment, update the tracker. Nobody starts new work in that column.", SMALL))

    # --- page 4: routine
    flow += [PageBreak(), P("3. Your ten minutes a day", H1),
             P("The tracker only works if someone reads it every night. That is the whole job: read, "
               "unblock, merge."), Spacer(1, 2 * mm)]
    routine = [
        ("Open the Dashboard tab", "Look at two numbers only: overall % and the Blocked count. Everything else is detail."),
        ("Scan the five member tabs", "Any row still 'Not started' whose date has passed is a red flag, not a rounding error."),
        ("Review one pull request", "Small PRs only. If it is huge, send it back and ask for it split - that is a kindness, not a delay."),
        ("Answer in the group, not in DMs", "Decisions must be visible so the tracker stays truthful."),
        ("Write one line in the Daily Log tab", "Date, who is blocked, what you did about it. Thirty seconds of writing saves a day of guessing."),
    ]
    for i, (a, b) in enumerate(routine, 1):
        flow.append(P(f"<b>{i}. {a}.</b> {b}", CELL))
        flow.append(Spacer(1, 1.6 * mm))

    flow += [Spacer(1, 3 * mm), P("4. Five checkpoints - where the sprint can still be saved", H1)]
    for when, what, action in CHECKPOINTS:
        flow.append(P(f"<b>{when}</b> &mdash; {what}", CELL))
        flow.append(P(f"&nbsp;&nbsp;&nbsp;&nbsp;<i>If not:</i> {action}", SMALL))
        flow.append(Spacer(1, 2 * mm))

    # --- page 5: stalling + approval
    flow += [PageBreak(), P("5. When a member stalls (they will, once)", H1)]
    flow += bullets([
        "Ask one question first: <b>&quot;what exactly is blocking you, right now?&quot;</b> Not &quot;how is it going&quot; - "
        "that gets you a polite answer and no information.",
        "If the answer is a technical error, ask for the last 10 lines of the output. Fix it with them for 15 minutes, then hand it back.",
        "If the answer is time or exams, move that member's heavy blocks to the weekend and mark the light days Skipped in the tracker - honestly, not silently.",
        "If the answer is &quot;I don't understand the repo&quot;, pair them with the person who owns the neighbouring track for one session.",
        "Never take the task away and do it yourself in the first week. You are the last resort on 24 November, not the first.",
        "Escalation order: group chat, then a call, then a 20-minute sit-down. Three strikes in the tracker is a conversation, not a punishment.",
    ])
    flow += [Spacer(1, 4 * mm), P("6. Nothing is DONE without evidence", H1)]
    flow += bullets([
        "A test count: the command and the exact 'N passed, M skipped' line.",
        "A feature: one real API response or one screenshot of the screen, pasted in the row.",
        "A build: the file path, its size, and the SHA256.",
        "CI: the four job names with their conclusions, copied from the Actions page.",
        "A document: the link, plus one sentence on who it is for.",
        "If a row says Done and the evidence is missing, set it back to In progress. That single habit is why this sprint finishes.",
    ])

    # --- page 6: sign-off
    flow += [PageBreak(), P("7. The sign-off you will do on 25 November", H1),
             P("Walk through this list on the installed build, in order, with the member who owns it "
               "standing next to you. Ten minutes per item, no exceptions, no &quot;it worked yesterday&quot;."),
             Spacer(1, 3 * mm)]
    items = [
        "The app starts from the desktop shortcut on the gate PC and the portal opens on localhost.",
        "A real bus is scanned and the event appears in the list with the right bus number.",
        "The same event shows a vehicle number, and it is the fleet registration, not a guess.",
        "A bus whose plate disagrees with its sticker is flagged plate_mismatch, and a bus with no plate is not.",
        "The CSV and XLSX exports open in Excel with the Vehicle number column populated.",
        "The three lights (Light / Focus / Size) are green at the gate, and one of them can be made amber on demand.",
        "The pull request is merged and the four CI jobs are green.",
        "No string in the repository prints a secret; the runbook is one page and reads plainly.",
        "The tracker shows every task Done with evidence, or Blocked/DEFERRED with a reason.",
        "docs/FINAL_STATUS.md states what is not delivered - video plates, AGPL decision, code signing - and why.",
    ]
    rows = [[P("&#9744;", CELLH), P("Check", CELLH)]]
    for it in items:
        rows.append([P("&#9744;", CELL), P(it, CELL)])
    t = Table(rows, colWidths=[9 * mm, 135 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY),
                           ("GRID", (0, 0), (-1, -1), 0.4, LINE),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("TOPPADDING", (0, 0), (-1, -1), 5),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    flow += [t, Spacer(1, 8 * mm)]
    flow.append(P("Signed (team lead): ______________________ &nbsp;&nbsp; Date: ____________ &nbsp;&nbsp; "
                  "Delivered as: installer / batch launcher (circle one)", CELL))
    doc.build(flow)
    return path


if __name__ == "__main__":
    made = []
    for m in MEMBERS:
        made.append(build(m))
    made.append(build_leader())
    for p in made:
        print(os.path.basename(p), round(os.path.getsize(p) / 1024), "KB")

