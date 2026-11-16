# team_pack — the sprint handover pack

Printable material for the five developers plus the lead, sprint **13–25 November 2026**.

## What is here

| File | What it builds |
|---|---|
| `handbook.py` | `pdf/VISIONAI_Team_Handbook.pdf` — 16 pages, written for someone who has never used Git. Covers what we are building, the folder map, the daily tracker ritual, evidence rules, Git from zero, the minimum Python/Flask/DB, a 26-term glossary, a 3-hour learning path, ten project-specific errors, the rules, who to ask, and the first 90 minutes of 13 November. |
| `build.py` | `pdf/VISIONAI_Sprint_Plan_<MEMBER>.pdf` for SUTHARSON R, SARAN C, VIJAY M, HARISHWARAN S, HARIS KRISHNA M J, plus `pdf/VISIONAI_Team_Lead_Pack.pdf`. |

## How to regenerate

```bash
python -m venv .venv-pack
.venv-pack/bin/pip install reportlab pymupdf      # Windows: .venv-pack\Scripts\pip
.venv-pack/bin/python team_pack/handbook.py
.venv-pack/bin/python team_pack/build.py
```

`pymupdf` is only used to read the pages back during the build (the handbook is built
twice: once to discover which page each part really starts on, so the contents page
numbers are true rather than guessed, and once to write it with those numbers).

## Why the PDFs are not in Git

`pdf/` and the `.zip` bundle are generated output — every rebuild changes the bytes.
No PDF has ever been tracked in this repository, and the pack reaches the team through
the Drive folder and their email, not through a clone. Regenerate with the two commands
above; the sources are what belong in history.

## Verification used when these were built

* Every page read back with `pymupdf` — page count, no empty page, no orphan page.
* Contents page numbers checked against where each `Part N` banner actually lands.
* Cover cross-reference (Part 3 / Part 5 page numbers) generated, not typed.
* Cover, Git chapter and glossary rendered to PNG and inspected by eye.

## Content rules these PDFs follow

* The detector is frozen: nothing in the pack suggests training, threshold or evaluation changes.
* Unreadable stays unreadable — `TN 13/15/19 R 4376` keeps its slashes, bus 105 has no plate and
  therefore `vehicle_number: null`. A guessed plate is described as a failure.
* Secrets never appear: no database URL, token or key, and screenshots are told to be cropped.
* Exam days (Tue 17 – Fri 20 Nov) carry 15–45 minute tasks only.
* HARISHWARAN S has no laptop; his track is written for a phone browser without apologising for it.
* The tracker baseline is honest: 0 of 65 tasks started on 13 November, and the workbook says so.
