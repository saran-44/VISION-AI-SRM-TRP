# Task for the VS Code assistant — validate both checkpoints on real frames

Copy everything between the rules into the VS Code assistant as **one message**.
It continues from `main` at the merge of the cascade work; the two models are
already wired.

---

**CONTEXT — read this first**

The repository now runs a three-stage detection cascade in `backend/vision.py`:

| Stage | Checkpoint | Classes | Notes |
| --- | --- | --- | --- |
| `sticker` | `best.pt` (tracked) | 0 `red circle`, 1 `sticker` | only class 1 is cropped and OCR'd |
| `number_plate` | `anpr_best.pt` (tracked) | **0 `licence` (single class)** | YOLOv10n on `Car_License_Plates`, 120 epochs, trained 2024-07-02 |
| `vehicle` | `weights/vehicle.pt` (not tracked) | COCO subset | bus / car / bike / truck |

Agreed numbers, do **not** change them silently:

```
VISION_IMAGE_SIZE=960        VISION_CONFIDENCE=0.25      VISION_STICKER_CLASS=1
VISION_PLATE_CONFIDENCE=0.25 VISION_PLATE_UPSCALE=3      VISION_VEHICLE_CONFIDENCE=0.35
```

Everything below runs on the operator's own machine. Do not push, do not open a
pull request — Arena reviews and opens them.

**YOUR TASK**

1. **Environment.** From Git Bash in the repo root:

   ```bash
   source .venv/Scripts/activate
   python -m pip install -r backend/requirements-vision.txt
   python scripts/fetch_vehicle_model.py
   ```

   If Torch installs as the CUDA build and the machine has no GPU, reinstall it
   from the CPU index instead (`docs/DETECTION.md` §5).

2. **Confirm each checkpoint loads and carries the classes above.**

   ```bash
   python scripts/inspect_model.py best.pt
   python scripts/inspect_model.py anpr_best.pt
   python scripts/inspect_model.py weights/vehicle.pt
   ```

   `anpr_best.pt` must print **one** class, `licence`. If it prints anything
   else, stop and report — the code assumes a single class so it applies no
   class filter.

3. **Capture ten real frames** of an actual bus sticker at gate distance — not
   one lucky photo. Phone-held photos of the sticker are fine.

   ```bash
   mkdir -p frames
   python scripts/scan_image.py --camera 0 --save frames/f01.jpg
   # repeat for f02 … f10, varying distance and angle
   ```

4. **Run the batch report and keep the output verbatim.**

   ```bash
   python scripts/scan_image.py --dir frames/
   ```

   Record the summary line and every row. That table is the evidence: how many
   frames produced a number, and *which stage* produced it.

5. **Only if recall is poor**, run one variable at a time and re-run the batch,
   keeping both outputs:

   ```bash
   VISION_PLATE_UPSCALE=4 python scripts/scan_image.py --dir frames/
   VISION_PLATE_CONFIDENCE=0.15 python scripts/scan_image.py --dir frames/
   VISION_IMAGE_SIZE=1280 python scripts/scan_image.py --dir frames/
   ```

   A change earns a place in `.env` only if it beats the baseline on the same
   ten frames. Never tune on one frame.

6. **Check the panel.** Run the app, sign in as `admin` / `admin`, open Test Lab,
   scan a sticker with each stage switched on and off. Confirm the chips read
   `Sticker off` / `Number plate unavailable` and that a scan still returns the
   vehicle type with a single stage enabled.

**RULES**

- Do not edit `backend/`, `frontend/`, `scripts/` or the docs — Arena owns those.
  Your job is measurement, not code.
- Do not commit `frames/`, `weights/`, `.env` or any dataset. They are ignored
  on purpose; keep it that way.
- Do not paste secrets, database URLs or device keys into chat or a commit.
- If a number is read wrongly, report the wrong text next to the right one —
  do not "fix" it by hand.

**REPORT BACK** (this exact shape, so it can be pasted straight to Arena)

```
GOAL:        validate best.pt + anpr_best.pt on 10 real gate frames
MODELS:      best.pt <classes> | anpr_best.pt <classes> | vehicle.pt <classes>
ENV:         <windows/venv/python + torch + ultralytics versions>
BASELINE:    summary: N/10 frames produced a number
             reasons: <reason=n, …>
             read by: <stage=n, …>
TABLE:       <the 10 rows verbatim>
TUNING:      <variant -> summary, one line each, or "none needed">
PANEL:       <what the Test Lab chips showed, on/off>
WRONG READS: <expected -> got, or "none">
ARTIFACTS:   <paths of saved frames, not committed>
BLOCKERS:    <anything that stopped you>
```

---

## Why this task and not another

The code is done and tested (247 tests). What is **not** known is how the two
checkpoints behave on *this* campus's stickers at gate distance — and that is
measured, not written. Ten frames with a stage-by-stage breakdown either prove
the cascade works or point at the exact knob (`VISION_IMAGE_SIZE` for small
plates, `VISION_PLATE_UPSCALE` for blurry crops, `VISION_CONFIDENCE` for missed
stickers). No amount of further coding substitutes for that table.
