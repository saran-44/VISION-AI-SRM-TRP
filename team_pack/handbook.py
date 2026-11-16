#!/usr/bin/env python3
"""Build the beginner team handbook PDF for VISION AI - SRM TRP.

Written for five people who have never run this project, never used Git and,
in one case, have no laptop at all. Sprint: Fri 13 Nov 2026 -> Wed 25 Nov 2026.
Output: team_pack/pdf/VISIONAI_Team_Handbook.pdf
"""
import os
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
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
GREENBG = colors.HexColor("#e8f5ec")
AMBER = colors.HexColor("#9a6700")
AMBERBG = colors.HexColor("#fdf5e2")
RED = colors.HexColor("#b42318")
REDBG = colors.HexColor("#fdecea")
INK = colors.HexColor("#1c2530")


def st(name, **kw):
    base = dict(fontName="Helvetica", fontSize=9.5, leading=13.5, textColor=INK)
    base.update(kw)
    return ParagraphStyle(name, **base)


TITLE = st("t", fontName="Helvetica-Bold", fontSize=26, leading=30, textColor=NAVY)
SUBTITLE = st("st", fontSize=12, leading=17, textColor=GREY)
H1 = st("h1", fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=NAVY,
        spaceBefore=2, spaceAfter=6)
H2 = st("h2", fontName="Helvetica-Bold", fontSize=10.5, leading=14, textColor=ACCENT,
        spaceBefore=9, spaceAfter=3)
BODY = st("b")
BODYS = st("bs", fontSize=9, leading=13)
SMALL = st("sm", fontSize=8.2, leading=11.2, textColor=GREY)
CELL = st("c", fontSize=8.4, leading=11.2)
CELLB = st("cb", fontName="Helvetica-Bold", fontSize=8.4, leading=11.2)
CELLH = st("ch", fontName="Helvetica-Bold", fontSize=8.4, leading=11.2, textColor=colors.white)
CODE = st("code", fontName="Courier", fontSize=8.0, leading=11, textColor=colors.HexColor("#0b3d91"))
CODEW = st("codew", fontName="Courier", fontSize=8.0, leading=11, textColor=colors.white)


def P(txt, style=BODY):
    return Paragraph(txt, style)


def banner(text, sub=None):
    """Navy section bar."""
    rows = [[Paragraph(text, st("bt", fontName="Helvetica-Bold", fontSize=11.5,
                                leading=15, textColor=colors.white))]]
    if sub:
        rows.append([Paragraph(sub, st("bsub", fontSize=8.4, leading=11.5,
                                       textColor=colors.HexColor("#c3d3ea")))])
    t = Table(rows, colWidths=[174 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def callout(text, kind="info"):
    bg, bar, label = {
        "info": (LIGHT, ACCENT, "NOTE"),
        "good": (GREENBG, GREEN, "GOOD"),
        "warn": (AMBERBG, AMBER, "CARE"),
        "bad": (REDBG, RED, "NEVER"),
    }[kind]
    t = Table([[Paragraph("<b>%s</b>&nbsp;&nbsp;%s" % (label, text),
                          st("co", fontSize=8.6, leading=12))]],
              colWidths=[174 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("LINEBEFORE", (0, 0), (0, -1), 2.4, bar),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def code_box(lines, width=174 * mm):
    body = "<br/>".join(l.replace("&", "&amp;").replace("<", "&lt;") for l in lines)
    t = Table([[Paragraph(body, CODEW)]], colWidths=[width])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#16283f")),
        ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def table(header, rows, widths, hdr=True, zebra=True, align=None):
    data = []
    if hdr:
        data.append([Paragraph(h, CELLH) for h in header])
    for r in rows:
        data.append([c if isinstance(c, Paragraph) else Paragraph(str(c), CELL)
                     for c in r])
    t = Table(data, colWidths=widths, repeatRows=1 if hdr else 0)
    style = [
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ]
    if hdr:
        style.append(("BACKGROUND", (0, 0), (-1, 0), NAVY))
    if zebra:
        for i in range(1, len(data)):
            if i % 2 == 0:
                style.append(("BACKGROUND", (0, i), (-1, i), LIGHT))
    t.setStyle(TableStyle(style))
    return t


class Doc(BaseDocTemplate):
    def __init__(self, path, **kw):
        BaseDocTemplate.__init__(self, path, pagesize=A4, **kw)
        frame = Frame(18 * mm, 16 * mm, A4[0] - 36 * mm, A4[1] - 34 * mm,
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
                      id="body")
        self.addPageTemplates([PageTemplate(id="all", frames=[frame], onPage=self._deco)])

    def _deco(self, canv, doc):
        canv.saveState()
        w, h = A4
        canv.setFillColor(NAVY)
        canv.rect(0, h - 13 * mm, w, 13 * mm, stroke=0, fill=1)
        canv.setFillColor(colors.white)
        canv.setFont("Helvetica-Bold", 8.5)
        canv.drawString(18 * mm, h - 8.6 * mm, "VISION AI  ·  SRM TRP  ·  TEAM HANDBOOK")
        canv.setFont("Helvetica", 7.5)
        canv.setFillColor(colors.HexColor("#c3d3ea"))
        canv.drawRightString(w - 18 * mm, h - 8.6 * mm, "Sprint 13 - 25 November 2026")
        canv.setStrokeColor(LINE)
        canv.setLineWidth(0.4)
        canv.line(18 * mm, 12 * mm, w - 18 * mm, 12 * mm)
        canv.setFillColor(GREY)
        canv.setFont("Helvetica", 7.5)
        canv.drawString(18 * mm, 8.4 * mm,
                        "Read once, then keep it open while you work. No question here is a stupid one.")
        canv.drawRightString(w - 18 * mm, 8.4 * mm, "Page %d" % doc.page)
        canv.restoreState()


DATES = ["Fri 13 Nov", "Sat 14 Nov", "Sun 15 Nov", "Mon 16 Nov", "Tue 17 Nov",
         "Wed 18 Nov", "Thu 19 Nov", "Fri 20 Nov", "Sat 21 Nov", "Sun 22 Nov",
         "Mon 23 Nov", "Tue 24 Nov", "Wed 25 Nov"]

ROLES = [
    ("HARIHARAN V", "Team Lead", "Runs the sprint, reviews every pull request, is the only person whose sheet shows all five tabs."),
    ("SUTHARSON R", "Backend / co-lead", "The vehicle number itself: API, CSV/XLSX export, mismatch flag, the acceptance script, closing the pull request."),
    ("SARAN C", "Frontend", "What a human sees: the Vehicle number column, tooltips, branding, error states, screenshots."),
    ("VIJAY M", "Packaging + camera", "Getting it onto the gate PC: the build, the installer or launcher, CAMERA_SOURCE, the live replay."),
    ("HARISHWARAN S", "Docs + QA, PHONE ONLY", "The runbook a guard can follow, the fleet list, manual test cases, proofreading. Everything on a phone browser."),
    ("HARIS KRISHNA M J", "Database", "The fleet seed data, the lookup query and its index, backup/restore, export integrity."),
]


def cover():
    return [
        Spacer(1, 22 * mm),
        P("VISION AI", st("cv", fontName="Helvetica-Bold", fontSize=12, leading=14,
                          textColor=ACCENT)),
        Spacer(1, 3 * mm),
        P("The Team Handbook", TITLE),
        Spacer(1, 4 * mm),
        P("Everything you need from zero: what we are building, what your job is, "
          "how to use Git without fear, and how to prove your work is real.", SUBTITLE),
        Spacer(1, 8 * mm),
        banner("Sprint 13 - 25 November 2026  ·  6 people  ·  65 tasks  ·  13 days",
               "Bus sticker extraction and transport register for SRM TRP Engineering College"),
        Spacer(1, 8 * mm),
        table(["Who", "In this sprint", "One line"],
              [(n, r, d) for n, r, d in ROLES],
              [34 * mm, 32 * mm, 108 * mm]),
        Spacer(1, 7 * mm),
        callout("If you read one thing, read Part 3 (page %s) and Part 5 (page %s). "
                "Part 3 is the two minutes a day that keeps you visible. Part 5 is Git, "
                "which is the only thing here that will make you feel stupid for an hour "
                "and then never again." % (PAGES.get(3, "-"), PAGES.get(5, "-")), "info"),
        Spacer(1, 6 * mm),
        P("Prepared for the team. Sprint dates respect the practical exams "
          "(Tue 17 - Fri 20 Nov, 15-45 minute tasks only). One member works entirely "
          "from a phone browser, and the plan is written that way.", SMALL),
    ]


PAGES = {}


def contents():
    rows = [
        ("1", "What we are building, in plain words", PAGES.get(1, "-")),
        ("2", "The map: what lives where in the project", PAGES.get(2, "-")),
        ("3", "Your two minutes a day in the tracker", PAGES.get(3, "-")),
        ("4", "Evidence: what counts and what does not", PAGES.get(4, "-")),
        ("5", "Git and GitHub from absolute zero", PAGES.get(5, "-")),
        ("6", "The only Python, Flask and database you need", PAGES.get(6, "-")),
        ("7", "Glossary - every word you will hear", PAGES.get(7, "-")),
        ("8", "Learning path: three hours, in this order", PAGES.get(8, "-")),
        ("9", "When something breaks: the ten errors", PAGES.get(9, "-")),
        ("10", "The ten rules, privacy, and what 'done' means", PAGES.get(10, "-")),
        ("11", "Who to ask, and when to stop trying alone", PAGES.get(11, "-")),
        ("12", "Your first 90 minutes (13 November)", PAGES.get(12, "-")),
    ]
    return [
        PageBreak(),
        banner("Contents", "Page numbers are the printed page, not the PDF page count."),
        Spacer(1, 5 * mm),
        table(["Part", "Title", "Page"], rows, [14 * mm, 140 * mm, 20 * mm]),
        Spacer(1, 8 * mm),
        P("How to use this handbook", H2),
        P("Read Parts 1 to 3 today. Skim Part 5 before your first commit and keep it open "
          "the first three times - after that you will not need it. Use Part 7 as a "
          "dictionary, not as reading. Parts 9 to 11 are for the day something goes wrong, "
          "and something will."),
        Spacer(1, 3 * mm),
        P("This handbook deliberately repeats what your personal PDF says. Repetition is "
          "how a new team gets consistent, not a sign that you were not listening."),
        Spacer(1, 6 * mm),
        callout("Nothing in this project requires you to understand the machine learning. "
                "The model is finished and frozen. Your work is the ordinary software "
                "around it: storing a number, showing it, packaging it, writing it down.", "good"),
    ]


def part1():
    flow = [PageBreak(), banner("Part 1  ·  What we are building, in plain words",
                   "Two paragraphs, then a picture. That is all you need to start.")]
    flow += [
        Spacer(1, 5 * mm),
        P("A bus arrives at the college gate. A camera sees it. Our software reads the "
          "number sticker painted on the bus - something like <b>57</b> - works out which "
          "bus that is, and writes a line into the transport register: the time, the gate, "
          "the bus number, and the vehicle's registration number. The guard writes nothing. "
          "Nobody can quietly edit the register afterwards.", BODYS),
        Spacer(1, 3 * mm),
        P("The hard part - reading the sticker and the number plate from a photograph - is "
          "already done and already proven. On our ground-truth set the pipeline reads "
          "<b>12 of 12</b> bus numbers and <b>3 of 3</b> number plates in still images. "
          "What is left is everything around that: putting the vehicle number into the data "
          "we return, showing it on a screen, packaging it for the gate PC, and writing it "
          "down so a guard can run it without us.", BODYS),
        Spacer(1, 5 * mm),
        P("The pipeline, left to right", H2),
        table(["Step", "What happens", "Who owns it"],
              [("1. Capture", "A frame comes from the gate camera (RTSP stream, HTTP snapshot, or a USB camera) or from a video file during testing.", "Vijay"),
               ("2. Sticker", "The model finds the painted bus-number sticker in the frame.", "Nobody - frozen"),
               ("3. Number", "OCR turns that crop into text: <b>57</b>.", "Nobody - frozen"),
               ("4. Plate", "A second pass reads the registration plate where one is mounted.", "Nobody - frozen"),
               ("5. Lookup", "Bus 57 is looked up in the fleet table and becomes <b>TN 48 BH 6091</b>.", "Haris Krishna"),
               ("6. Event", "One row is written: time, gate, bus number, vehicle number, confidence, any flags.", "Sutharson"),
               ("7. Screen", "The register appears on the portal - and in the CSV/XLSX export.", "Saran"),
               ("8. Proof", "The acceptance script and the runbook prove it still works.", "Sutharson, Harishwaran")],
              [22 * mm, 126 * mm, 26 * mm]),
        Spacer(1, 5 * mm),
        callout("A wrong number is worse than no number. If the model is not sure, it stays "
                "silent, and the event is recorded with a flag instead of a guess. That is a "
                "design decision, not a bug - never 'fix' it by lowering a threshold.", "warn"),
        PageBreak(),
        banner("Part 1 (continued)  ·  The numbers that must not move",
               "If a change makes any line below worse, the change is wrong - however clever it is."),
        Spacer(1, 5 * mm),
        table(["What", "Must stay", "Why it matters"],
              [("Bus numbers read, still images", "12 of 12", "The whole accuracy claim rests on it."),
               ("Number plates read, still images", "3 of 3 - TN 48 BH 6091, TN 48 BK 2129, TN 48 BK 2106", "Plates are how we prove the fleet mapping."),
               ("Video appearance #5 plate", "TN.48.BF.1480", "The one plate we can check frame by frame."),
               ("Bus 105 (no plate mounted)", "vehicle_number: null", "Empty is correct. A guessed plate is a failure."),
               ("Bus 116 (two digits unreadable)", "TN 13/15/19 R 4376", "The slash means unreadable. Never invent digits."),
               ("Bus 57", "open question: BH 6091 (image) vs BN 6091 (video)", "Only the transport office can settle it.")],
              [40 * mm, 66 * mm, 68 * mm]),
        Spacer(1, 5 * mm),
        P("Timings on the test machine (one frame)", H2),
        table(["Input", "Total", "Note"],
              [("busimage1.jpg", "14,065 ms", "Cold start included"),
               ("busimage2.jpg", "10,964 ms", "Warm"),
               ("One video frame", "7,702 ms", "Steady state"),
               ("of which OCR", "about 55%", "The single biggest cost")],
              [40 * mm, 30 * mm, 104 * mm]),
        Spacer(1, 5 * mm),
        P("What we are NOT doing this sprint", H2),
        P("No model training, no threshold tuning, no new detection features, no cloud rewrite, "
          "no mobile app. The detector is frozen until 25 November; touching it would invalidate "
          "the 12/12 and 3/3 result the whole project rests on. If you believe a threshold must "
          "change, that is a conversation with the lead, not an edit."),
        Spacer(1, 4 * mm),
        callout("A guessed '/' in a plate is a failure. A guessed plate for bus 105 is a failure. "
                "Unreadable is a legitimate answer; invented is not.", "bad"),
    ]
    return flow


def part2():
    flow = [PageBreak(), banner("Part 2  ·  The map: what lives where",
                                "So you stop asking 'where is that file' and start asking better questions.")]
    flow += [
        Spacer(1, 5 * mm),
        table(["Folder / file", "What it is", "Touch it if"],
              [("backend/", "The Flask server: API routes, event services, database access, SQL schema.", "You are Sutharson, Haris Krishna, or Vijay"),
               ("frontend/", "The portal: HTML, CSS, JS. What the guard and the transport office see.", "You are Saran or Vijay"),
               ("models/", "The trained .pt checkpoints that find stickers and plates.", "Never. They are frozen."),
               ("scripts/", "Offline tools: media evaluation, the acceptance script.", "You are Sutharson"),
               ("docs/", "RUNBOOK.md, CONTINUATION_GUIDE.md, this sprint's evidence.", "You are Harishwaran"),
               ("tests/", "The automated suite that CI runs on every pull request.", "You added behaviour that needs proving"),
               (".github/workflows/ci.yml", "The four CI jobs. All four must be green before a merge.", "Almost never - and never to silence a job"),
               ("backend/sql/001_initial.sql", "The database shape, including the fleet table with registration_number.", "You are Haris Krishna")],
              [40 * mm, 100 * mm, 34 * mm]),
        Spacer(1, 5 * mm),
        P("The three places the truth lives", H2),
        P("<b>The fleet table</b> - bus number to registration number. This is the authority. "
          "If the table says TN 48 BK 2106, that is the vehicle number, even if the plate OCR "
          "disagrees; disagreement is recorded as a <font face='Courier'>plate_mismatch</font> flag."),
        P("<b>The event table</b> - one row per bus movement. It is append-only in spirit: you "
          "record, you do not rewrite history."),
        P("<b>The gate configuration</b> - <font face='Courier'>CAMERA_SOURCE</font>, "
          "<font face='Courier'>VISION_PLATE_MODE</font>, the debounce window. On the gate PC "
          "this lives in <font face='Courier'>C:\\ProgramData\\VisionAI\\gate.env</font>. "
          "Secrets live there and nowhere else."),
        Spacer(1, 4 * mm),
        callout("Never paste a database URL, a JWT secret or an API key into a chat, a "
                "commit, a screenshot or this handbook. If you need to show a connection "
                "string, replace the middle with XXXX first.", "bad"),
    ]
    return flow


def part3():
    flow = [PageBreak(), banner("Part 3  ·  Your two minutes a day",
                                "This is the only obligation that never moves. Everything else is your task list.")]
    flow += [
        Spacer(1, 5 * mm),
        P("Do this before you sleep, every single day, including exam days. It takes two "
          "minutes and it is how five people stay in step without a meeting.", BODYS),
        Spacer(1, 3 * mm),
        table(["#", "Click", "What to type"],
              [("1", "Open your own tab in the sprint workbook.", "Your name is on the tab. Not the COMMAND CENTRE."),
               ("2", "Find today's date row.", "One row per day, 13 Nov to 25 Nov. Today only."),
               ("3", "Set Status (column E).", "Exactly one of: <b>Not started</b> / <b>In progress</b> / <b>Blocked</b> / <b>Done</b> / <b>Skipped</b>"),
               ("4", "Paste Evidence (column F).", "The real output, link or file path. See Part 4."),
               ("5", "One line in Notes (column G).", "What you actually did, or what stopped you."),
               ("6", "Type today's date in Updated (column H).", "13/11 and so on. It costs two seconds.")],
              [8 * mm, 66 * mm, 100 * mm]),
        Spacer(1, 5 * mm),
        P("Why the exact word matters", H2),
        P("The COMMAND CENTRE counts the word <b>Done</b> literally, with a formula. "
          "'done', 'DONE', 'completed', 'finished' count as zero and the meter will not move. "
          "If your work is finished but the meter says it is not, you have typed a different word - "
          "check that before you tell the lead the sheet is broken."),
        Spacer(1, 4 * mm),
        P("The daily log", H2),
        P("One row on the DAILY LOG tab: today, your name, and one sentence. If something is "
          "blocking you, the 'blocking? what exactly' column is the important one - "
          "'waiting for Vijay's installer, then I cannot test the export button' is useful. "
          "'blocked' is not."),
        Spacer(1, 4 * mm),
        callout("Blocked for more than 30 minutes: set Status = Blocked, write one line "
                "saying what you tried, and message the group. Spinning alone for two hours "
                "is the single most expensive thing you can do in a 13-day sprint.", "warn"),
        Spacer(1, 4 * mm),
        P("The weekly shape", H2),
        table(["When", "What the lead does", "What you do"],
              [("Every evening", "Reads the command centre, nothing else.", "Updates your row."),
               ("15 Nov (Sun)", "First checkpoint: everyone has a commit pushed.", "One small push, however small."),
               ("17-20 Nov", "Practical exams. No meetings, no pressure.", "15-45 minute task only, then stop."),
               ("22 Nov", "Second checkpoint: the acceptance script passes.", "Fix whatever the tests say."),
               ("24 Nov", "Merge day: four CI jobs green, tagged v1.0.0.", "Final evidence in your row."),
               ("25 Nov", "Install on the gate PC, three real buses, sign-off.", "Hand over.")],
              [24 * mm, 78 * mm, 72 * mm]),
    ]
    return flow


def part4():
    flow = [PageBreak(), banner("Part 4  ·  Evidence: what counts and what does not",
                                "If it cannot be shown, the row is not Done. This is not distrust - it is how five people see reality.")]
    flow += [
        Spacer(1, 5 * mm),
        table(["Your work type", "What goes in the Evidence cell", "Example"],
              [("Ran the tests", "The exact summary line, pasted.", "12 passed, 3 skipped in 41.2s"),
               ("Built a feature", "One real API response or one screenshot.", "GET /api/events?id=8 shows \"vehicle_number\": \"TN 48 BK 2106\""),
               ("Built a package", "File path, size in MB, SHA256.", "VisionAI-Setup-1.0.0.exe  284 MB  a3f1..." ),
               ("CI / pull request", "The four job names and their conclusions.", "All four green on PR #55; link pasted"),
               ("Wrote a document", "The link, plus one sentence on who it is for.", "RUNBOOK.md - for a guard who has never seen the project"),
               ("Fixed a bug", "Before and after, one line each.", "was 500 on null plate; now 200 with vehicle_number: null")],
              [34 * mm, 62 * mm, 78 * mm]),
        Spacer(1, 5 * mm),
        P("Weak evidence, and the stronger version of the same sentence", H2),
        table(["Does not count", "Counts"],
              [("'Tests are fine.'", "'12 passed, 3 skipped in 41.2s'"),
               ("'It works on my machine.'", "'Windows 11, Python 3.11.9, output pasted, screenshot attached'"),
               ("'Export is done.'", "'export.csv header line: id,timestamp,gate,bus_number,vehicle_number'"),
               ("'I pushed my branch.'", "'feat/sutharson-vehicle-number at 4a19c22, pushed; draft PR #55 open'"),
               ("'Model is accurate.'", "'12/12 bus numbers, 3/3 still plates, unchanged checkpoints'")],
              [78 * mm, 96 * mm]),
        Spacer(1, 5 * mm),
        callout("Screenshots: crop out anything with a password field, a token, or a full "
                "connection string. If you cannot crop it, do not post it - describe it instead.", "warn"),
    ]
    return flow


def part5():
    flow = [PageBreak(), banner("Part 5  ·  Git and GitHub from absolute zero",
                                "Eight steps. Do them once, slowly. After the third commit this stops being scary.")]
    flow += [
        Spacer(1, 5 * mm),
        P("The idea in one paragraph", H2),
        P("Git keeps a complete history of the project. GitHub is where that history is stored "
          "online so five people can share it. <b>main</b> is the shared, working version - "
          "nobody pushes to it. You copy main into your own <b>branch</b>, work there, save "
          "your work in <b>commits</b>, push the branch, and ask for it to be merged with a "
          "<b>pull request</b>. The lead reviews it. That is the entire workflow."),
        Spacer(1, 4 * mm),
        P("Step 1 - Create your GitHub account", H2),
        P("Go to github.com, Sign up, use your college email (the 8147251... address), verify "
          "the email, and set your username to something you are happy to show a recruiter. "
          "Write the username in your workbook row - the lead needs it to add you."),
        P("Step 2 - Install Git on Windows", H2),
        P("Download from git-scm.com/download/win and click through every default. You get a "
          "'Git Bash' app - that is your terminal. Open it and check:"),
        code_box(["git --version", "# git version 2.4x.x.windows.1"]),
        Spacer(1, 3 * mm),
        P("Step 3 - Tell Git who you are (once per machine)", H2),
        code_box(['git config --global user.name "Your Name"',
                  'git config --global user.email "8147251xxxxx@trp.srmtrichy.edu.in"']),
        Spacer(1, 3 * mm),
        P("Step 4 - Make a token. This is your password.", H2),
        P("GitHub will not accept your account password from Git. You create a token instead: "
          "Settings &rarr; Developer settings &rarr; Personal access tokens &rarr; "
          "Tokens (classic) &rarr; Generate new token &rarr; tick <b>repo</b> and "
          "<b>workflow</b> &rarr; Generate &rarr; copy it once and paste it into a private "
          "note. When Git asks for a password, paste the token."),
        callout("That token is a password. Never paste it in chat, never commit it, never "
                "screenshot it. If it leaks, revoke it and make a new one - it costs 30 seconds.", "bad"),
        Spacer(1, 3 * mm),
        P("Step 5 - Get the project onto your machine", H2),
        code_box(["git clone https://github.com/saran-44/VISION-AI-SRM-TRP.git",
                  "cd VISION-AI-SRM-TRP",
                  "git switch main"]),
        Spacer(1, 3 * mm),
        P("Step 6 - The five commands you will type every day", H2),
        code_box(["git switch main                 # go to the shared branch",
                  "git pull                        # take everyone else's merged work",
                  "git switch -c feat/yourname-topic   # your own branch, once per task",
                  "git add -A                      # stage everything you changed",
                  'git commit -m "feat(api): add vehicle_number to event response"',
                  "git push -u origin feat/yourname-topic"]),
        Spacer(1, 3 * mm),
        P("Step 7 - Ask for it to be merged", H2),
        P("On github.com you will see a yellow 'Compare &amp; pull request' button. Title it "
          "the same way as the commit: <font face='Courier'>feat(area): short description</font>. "
          "In the description say what changed, why, and how you proved it (that is your "
          "evidence). Then ask the lead to review. You never merge your own pull request."),
        Spacer(1, 3 * mm),
        P("Step 8 - Fix the review by pushing again", H2),
        P("Comments are normal; they are not a judgement. Change the code, "
          "<font face='Courier'>git add -A</font>, <font face='Courier'>git commit</font>, "
          "<font face='Courier'>git push</font>. The pull request updates itself. CI re-runs. "
          "Repeat until four jobs are green and the lead approves."),
        Spacer(1, 4 * mm),
        P("The five errors everyone hits", H2),
        table(["What Git says", "What it means", "What to type"],
              [("Authentication failed", "You typed your GitHub password instead of the token.", "Use the token as the password."),
               ("Updates were rejected... fetch first", "Someone merged while you were working.", "git pull --rebase, then push again."),
               ("Your branch is behind 'origin/main'", "You are out of date.", "git switch main &amp;&amp; git pull, then rebase your branch."),
               ("CONFLICT (content): merge conflict", "Two people edited the same lines.", "Stop. Read the &lt;&lt;&lt;&lt;&lt;&lt;&lt; markers, keep both intentions, ask the lead if unsure."),
               ("nothing to commit, working tree clean", "You forgot to save the file, or you are on the wrong branch.", "git status, then git switch back.")],
              [46 * mm, 66 * mm, 62 * mm]),
        Spacer(1, 4 * mm),
        callout("Commit message format, used by everyone, no exceptions: "
                "<font face='Courier'>type(area): what you did</font>. Types: feat, fix, docs, test, chore. "
                "Present tense, no full stop, under 72 characters. Future you reads these.", "good"),
    ]
    return flow


def part6():
    flow = [PageBreak(), banner("Part 6  ·  The only Python, Flask and database you need",
                                "You do not need a course. You need these nine ideas and the ability to read one function.")]
    flow += [
        Spacer(1, 5 * mm),
        table(["Idea", "In one sentence", "Where you will see it"],
              [("Variable", "A name for a value: <font face='Courier'>bus_number = \"57\"</font>", "Everywhere"),
               ("Function", "A named block that takes inputs and returns an output.", "<font face='Courier'>def get_event(event_id):</font>"),
               ("Dictionary", "A lookup box: <font face='Courier'>{\"bus_number\": \"57\"}</font>. Keys map to values.", "Every API response is one"),
               ("List", "An ordered row of things: <font face='Courier'>[e1, e2, e3]</font>.", "Every list endpoint returns one"),
               ("None / null", "Deliberately empty. Not zero, not an empty string - 'we do not know'.", "<font face='Courier'>vehicle_number: null</font> for bus 105"),
               ("try / except", "Do the risky thing; if it fails, handle it instead of crashing.", "Plate OCR and lookups"),
               ("Route", "A URL the server answers: <font face='Courier'>@app.route(\"/api/events\")</font>", "backend/app.py"),
               ("JSON", "The text format APIs speak. Curly braces, quoted keys.", "All responses"),
               ("SQL SELECT", "Ask the database for rows: <font face='Courier'>SELECT * FROM buses WHERE bus_number = ?</font>", "The fleet lookup")],
              [24 * mm, 96 * mm, 54 * mm]),
        Spacer(1, 5 * mm),
        P("Reading one request end to end - the exercise worth doing", H2),
        P("Open <font face='Courier'>backend/app.py</font> and find the route for "
          "<font face='Courier'>/api/events</font>. Follow it: the browser asks, the route "
          "reads query parameters, a service function talks to the database, a schema shapes "
          "the answer, and JSON goes back. Do that once with a print statement or a breakpoint "
          "and the whole project stops being a mystery."),
        Spacer(1, 4 * mm),
        P("Your local setup, exactly", H2),
        code_box(["py -3.11 -m venv .venv",
                  ".venv\\\\Scripts\\\\activate",
                  "pip install -r backend\\\\requirements.txt",
                  "python -m pytest -q          # paste the last line into your workbook"]),
        Spacer(1, 3 * mm),
        P("The vision stack is large (several hundred MB). Only install it if your task needs "
          "it: <font face='Courier'>pip install -r backend\\requirements-vision.txt</font>. "
          "If your laptop struggles, you are not blocked - Harishwaran's whole track runs in a "
          "phone browser and yours can too for most tasks."),
        Spacer(1, 4 * mm),
        callout("A test that passes when it should fail is worse than no test. Earlier in this "
                "project the acceptance script 'passed' while checking nothing. If you write or "
                "change a test, break the code on purpose once - it must go red.", "warn"),
    ]
    return flow


GLOSSARY = [
    ("API endpoint", "A URL the frontend calls to get data, e.g. GET /api/events."),
    ("Append-only", "You add rows; you do not rewrite old ones. The register must stay honest."),
    ("Branch", "Your private copy of the project where you can work without breaking anyone."),
    ("Checkpoint (.pt)", "The trained model file. Frozen this sprint."),
    ("CI", "GitHub automatically runs our tests on every pull request. Four jobs must be green."),
    ("Commit", "A saved snapshot with a message. 'Save' in other apps."),
    ("Confidence", "How sure the model is, 0 to 1. Below the threshold we stay silent."),
    ("Debounce", "If the same bus is still in frame, do not create a second event (60 s default)."),
    ("Event", "One recorded bus movement: time, gate, bus number, vehicle number, confidence."),
    ("Flag", "A warning attached to an event, e.g. unregistered_plate or plate_mismatch."),
    ("Fleet", "The table of buses and their registration numbers. The authority for vehicle number."),
    ("Inference", "Running the model on one image. Measured in milliseconds."),
    ("Installer / bundle", "The packaged version that runs on the gate PC without Python installed."),
    ("main", "The shared branch that must always work. Nobody pushes to it directly."),
    ("Migration", "A script that changes the database shape safely."),
    ("OCR", "Optical Character Recognition - turning the picture of a number into text."),
    ("Plate mismatch", "The plate OCR disagrees with the fleet record. The fleet wins; the event is flagged."),
    ("Preflight", "The app's own health check before it starts: database, models, disk, port."),
    ("Pull request (PR)", "Please review my branch and merge it into main. The unit of work here."),
    ("Push / pull", "Send your commits to GitHub / take everyone else's merged work."),
    ("RTSP", "The streaming protocol IP cameras use. The gate camera uses RTSP or an HTTP snapshot."),
    ("Schema", "The shape of the database: which tables, which columns, which types."),
    ("Sticker", "The painted bus number on the bus body, e.g. 57. Not the plate."),
    ("Threshold", "The confidence below which we refuse to report a number."),
    ("Vehicle number", "The registration, e.g. TN 48 BK 2106. What a human actually needs."),
    ("YOLO", "The object-detection architecture our checkpoints use (Ultralytics)."),
]


def part7():
    half = (len(GLOSSARY) + 1) // 2
    left, right = GLOSSARY[:half], GLOSSARY[half:]
    rows = []
    for i in range(half):
        a = left[i]
        b = right[i] if i < len(right) else ("", "")
        rows.append((a[0], a[1], b[0], b[1]))
    return [
        PageBreak(),
        banner("Part 7  ·  Glossary", "Use it as a dictionary. When a word is unfamiliar, come back here instead of nodding along."),
        Spacer(1, 4 * mm),
        table(["Term", "Meaning", "Term", "Meaning"], rows,
              [24 * mm, 63 * mm, 24 * mm, 63 * mm]),
    ]


def part8():
    return [
        PageBreak(),
        banner("Part 8  ·  Learning path: three hours, in this order",
               "Not a course. The minimum that makes you useful by tomorrow."),
        Spacer(1, 5 * mm),
        table(["Time", "What", "Where", "You are done when"],
              [("45 min", "Git basics: repository, branch, commit, push, pull request.", "docs.github.com/en/get-started/quickstart/hello-world",
                "You have made one commit on a throwaway branch of your own."),
               ("45 min", "Python only what we use: variables, functions, lists, dicts, try/except.", "docs.python.org/3/tutorial, sections 3-5 and 8",
                "You can read a route function in app.py and say what it returns."),
               ("30 min", "HTTP and Flask: request in, response out, status codes.", "flask.palletsprojects.com quickstart",
                "You can explain what 200, 404 and 500 mean without looking."),
               ("30 min", "Sheets formulas you will actually use: =COUNTIF, =IFERROR, =TEXT, dropdowns.", "support.google.com/docs",
                "You can read the COMMAND CENTRE formulas and follow them."),
               ("30 min", "Your own material: the member PDF for your role and the runbook.", "docs/RUNBOOK.md, your PDF",
                "You can name your first three tasks without opening anything.")],
              [18 * mm, 58 * mm, 52 * mm, 46 * mm]),
        Spacer(1, 6 * mm),
        P("What not to do", H2),
        P("Do not try to understand the whole system. Do not read the model code. Do not watch "
          "a six-hour Python course. Follow one request from the browser to the database and "
          "back, and you are already more useful than most people on day one."),
        Spacer(1, 5 * mm),
        callout("Learning on this project is allowed to be visible. If you spend an hour "
                "learning Git instead of writing code, put that in your row - 'spent 60 min on "
                "Git, made first commit, evidence: link'. It is progress, and the lead needs to "
                "see it as progress.", "good"),
    ]


def part9():
    rows = [
        ("ModuleNotFoundError: No module named 'flask'", "The virtual environment is not active.", "Activate .venv, then pip install -r backend\\requirements.txt"),
        ("'python' is not recognized", "Python is not on PATH.", "Reinstall with 'Add python.exe to PATH', or use py -3.11"),
        ("Port 5000 already in use", "Another copy is running.", "Close it, or start with a different port."),
        ("Address already in use / database is locked", "A second process has gate.db open.", "Close the other app; SQLite allows one writer."),
        ("401 / 403 from the API", "Missing or wrong token.", "Check the admin token in gate.env; never paste it anywhere."),
        ("500 on an event with no plate", "A null is being treated as a string.", "Return null, and test the null path explicitly."),
        ("pip install fails on opencv / torch", "Conflicting wheels, or CUDA instead of CPU.", "Install CPU-only torch; one cv2 only; ultralytics with --no-deps."),
        ("PyInstaller build fails", "A hidden import or a missing data file.", "Read the last 15 lines, add the import to the spec, rebuild."),
        ("CI red on a file you did not touch", "Someone else's change, or a flaky job.", "Re-run once; if still red, tell the lead - do not edit ci.yml to silence it."),
        ("Screen shows old data after a change", "Browser cache.", "Ctrl + F5. If it persists, it is a real bug."),
    ]
    return [
        PageBreak(),
        banner("Part 9  ·  When something breaks",
               "Ten errors cover most of this sprint. The method matters more than the list."),
        Spacer(1, 5 * mm),
        table(["Error / symptom", "Usual cause", "What to do"],
              rows, [62 * mm, 52 * mm, 60 * mm]),
        Spacer(1, 6 * mm),
        P("The method, when the list does not have your error", H2),
        P("<b>1.</b> Read the <b>last</b> 30 lines of the error, not the first. The cause is "
          "usually at the bottom."),
        P("<b>2.</b> Copy the exact message, paste it into a search engine with the library name. "
          "Someone has hit it before you."),
        P("<b>3.</b> If it is your environment: delete .venv, recreate it, reinstall. That fixes "
          "half of everything."),
        P("<b>4.</b> If it is a test failure: read the assertion line - it tells you what was "
          "expected and what arrived."),
        P("<b>5.</b> Then ask, with three things: what you ran, what you expected, what happened."),
        Spacer(1, 4 * mm),
        callout("'It did not work' cannot be fixed by anybody, including you. "
                "The exact command and the last fifteen lines can always be fixed.", "warn"),
    ]


def part10():
    return [
        PageBreak(),
        banner("Part 10  ·  The ten rules, privacy, and what 'done' means",
               "Short, because they matter."),
        Spacer(1, 5 * mm),
        table(["#", "Rule"],
              [("1", "Never push to main. Branch, pull request, review, merge."),
               ("2", "One task = one branch = one pull request, small enough to review in 15 minutes."),
               ("3", "Evidence or it did not happen."),
               ("4", "Never commit videos, photos, .pt model files or .env files. Over 2 MB, stop and ask."),
               ("5", "Never print a password, database URL or key - not in chat, not in a document, not in code."),
               ("6", "The detector is frozen: no model, threshold, tiling or evaluation changes this sprint."),
               ("7", "Update your row before you sleep."),
               ("8", "Blocked for 30 minutes: Status = Blocked, one line, message the group. Do not spin."),
               ("9", "Practical exams (17-20 Nov): 30 minutes maximum, only the small task listed."),
               ("10", "Ask early. A question on 14 Nov costs minutes; the same question on 24 Nov costs the sprint.")],
              [10 * mm, 164 * mm]),
        Spacer(1, 6 * mm),
        P("Privacy, in plain terms", H2),
        P("Bus and registration numbers are institutional data. Keep them inside this Drive "
          "folder and the repository - never in a personal group chat, never in a public gist. "
          "No student names, phone numbers or passwords go into code, screenshots or commits. "
          "When you take an evidence screenshot, crop anything with a password field or a token."),
        Spacer(1, 5 * mm),
        P("Definition of done - for the whole project, 25 November", H2),
        table(["Check", "Owner"],
              [("Four CI jobs green on the merged pull request.", "Sutharson"),
               ("12/12 bus numbers and 3/3 still plates still pass - the detector was not touched.", "Sutharson, Harishwaran"),
               ("Every event shows a vehicle number from the fleet record; disagreement is flagged.", "Sutharson, Haris Krishna"),
               ("The Vehicle number column is visible in the portal, the CSV and the XLSX.", "Saran"),
               ("The gate PC runs the app from a shortcut, reads a real bus, the event appears on the portal.", "Vijay"),
               ("docs/RUNBOOK.md exists and a guard who has never seen the project can start it.", "Harishwaran"),
               ("Every row in the workbook is Done with evidence, or Blocked/Skipped with a reason.", "Everyone")],
              [140 * mm, 34 * mm]),
    ]


def part11():
    return [
        PageBreak(),
        banner("Part 11  ·  Who to ask, and when to stop trying alone",
               "Asking the right person is a skill; asking nobody is a failure mode."),
        Spacer(1, 5 * mm),
        table(["If the problem is...", "Ask", "How fast"],
              [("Git, branches, pull requests, merge conflicts", "Hariharan (6383388381)", "Same day"),
               ("Backend, API, vehicle number, tests", "Sutharson (9344539185)", "Same day"),
               ("UI, CSS, dashboard, screenshots", "Saran (7907354483), then Vijay", "Same day"),
               ("Windows build, installer, camera", "Vijay (7339698587)", "Same day"),
               ("Database, seed data, exports", "Haris Krishna (8903842733)", "Same day"),
               ("Documents, runbook, QA, fleet list", "Harishwaran (8608883557)", "Same day"),
               ("Two people disagree", "Hariharan decides, once, in writing", "Immediately"),
               ("The whole plan is wrong", "Hariharan, same day - do not absorb it silently", "Immediately")],
              [78 * mm, 68 * mm, 28 * mm]),
        Spacer(1, 6 * mm),
        P("How to ask so you get an answer", H2),
        P("Three lines, every time:"),
        code_box(["What I ran:   python -m pytest tests/test_events.py -q",
                  "What I expected: 12 passed",
                  "What happened: 1 failed - KeyError: 'vehicle_number' at services.py:141"]),
        Spacer(1, 3 * mm),
        P("With those three lines, anyone can help you in two minutes. Without them, the "
          "conversation costs twenty and usually ends with 'send me your screen'."),
        Spacer(1, 5 * mm),
        P("Escalation ladder", H2),
        P("15 minutes alone -&gt; 30 minutes with the docs and a search -&gt; post the three "
          "lines in the group -&gt; if still blocked at 60 minutes, set Status = Blocked and "
          "message the lead directly. Nobody on this team is annoyed by a question; the sprint "
          "cannot absorb a silent two-day stall."),
    ]


def part12():
    return [
        PageBreak(),
        banner("Part 12  ·  Your first 90 minutes (13 November)",
               "Do these in order. Do not read the whole codebase first."),
        Spacer(1, 5 * mm),
        table(["Min", "Do this", "You are done when"],
              [("0-15", "Create the GitHub account with your college email, verify it, note the username.", "You can log in on a phone browser."),
               ("15-35", "Install Git, set user.name and user.email, create the access token.", "git --version prints a version; the token is saved privately."),
               ("35-50", "Clone the repository and open your own tab in the workbook.", "The folder exists locally; your tab shows 13 rows."),
               ("50-70", "Follow your personal PDF: environment setup for your role.", "The setup commands ran; any error is pasted in your row."),
               ("70-85", "Make one tiny commit on your own branch - even a typo fix in a doc you own.", "A commit exists with your name on it."),
               ("85-90", "Fill today's row: Status, Evidence, Notes, Updated.", "One row is green-lit and honest.")],
              [14 * mm, 92 * mm, 68 * mm]),
        Spacer(1, 6 * mm),
        P("The one thing to remember on day one", H2),
        P("Nothing here is expected to work first time. The people who succeed on this project "
          "are not the fastest coders - they are the ones whose row is filled in every night, "
          "whose evidence is real, and who ask at minute 30 instead of hour three."),
        Spacer(1, 5 * mm),
        callout("Everyone starts at zero. The workbook says so on purpose: 0 of 65, baseline "
                "day 1. Nobody is behind on 13 November, and nobody stays ahead by guessing.", "good"),
        Spacer(1, 8 * mm),
        banner("End of handbook", "VISION AI · SRM TRP · sprint 13-25 November 2026 · keep this open while you work"),
    ]


def _flow():
    flow = []
    flow += cover()
    flow += contents()
    flow += part1()
    flow += part2()
    flow += part3()
    flow += part4()
    flow += part5()
    flow += part6()
    flow += part7()
    flow += part8()
    flow += part9()
    flow += part10()
    flow += part11()
    flow += part12()
    return flow


def build():
    import pymupdf
    path = os.path.join(OUT, "VISIONAI_Team_Handbook.pdf")
    title = dict(title="VISION AI - Team Handbook", author="VISION AI - SRM TRP",
                 subject="Beginner team handbook, sprint 13-25 Nov 2026")
    # pass 1: find where each part actually starts
    Doc(path, **title).build(_flow())
    d = pymupdf.open(path)
    for i, page in enumerate(d):
        for line in page.get_text().splitlines():
            if line.startswith("Part ") and "·" in line:
                n = int(line.split()[1])
                PAGES.setdefault(n, i + 1)
    d.close()
    # pass 2: rebuild with true page numbers
    Doc(path, **title).build(_flow())
    d = pymupdf.open(path)
    print("wrote", path, os.path.getsize(path), "bytes,", d.page_count, "pages")
    print("contents map:", dict(sorted(PAGES.items())))
    return path


if __name__ == "__main__":
    build()
