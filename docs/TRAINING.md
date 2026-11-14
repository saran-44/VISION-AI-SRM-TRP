# Training the number-plate detector

This page answers the question the training dialog asks: **which base model**,
and what to change so the result actually works inside this portal.

---

## 1. Which one to pick

From the dialog's list (COCO mAP50-95, weights size):

| Model | COCO mAP50-95 | Weights | CPU inference @640 | Verdict for this project |
| --- | --- | --- | --- | --- |
| `yolo26n` | 40.1 | 5.3 MB | fastest (~25–40 ms/frame) | Fine if you only ever run the webcam on a laptop and the bus fills the frame |
| **`yolo26s`** | **47.8** | **19.5 MB** | ~60–90 ms/frame | **Choose this** — best accuracy you can still serve on a CPU at a usable rate |
| `yolo26m` | 52.5 | 42.2 MB | ~180–250 ms/frame | Only if plates are small/far and you can accept 3–5 FPS |
| `yolo26l` | 54.3 | 50.7 MB | ~350 ms/frame | No |
| `yolo26x` | 56.8 | 113.2 MB | ~600 ms/frame | No — bigger than this repo's whole frontend |

**Pick `yolo26s`.** It is the knee of the curve: 19.5 MB fits comfortably in git
next to the 5.5 MB `best.pt` already tracked, and it is roughly 2.5× faster than
`m` on the CPU you are actually testing on.

If you cannot spare the download or the FPS, `yolo26n` is not a disaster — see
§2 for why.

> Those mAP numbers are **COCO** numbers, i.e. the pretrained starting point.
> Your fine-tuned model will not have 40–56% mAP50-95 on plates; a clean
> single-class plate dataset typically lands at **0.90+ mAP50 and 0.70+
> mAP50-95**. Compare runs of your own dataset with each other, never with this
> table.

### Why not the biggest model

The detector in this project does **not** read the number. It only finds the
rectangle; `RapidOCR` reads the text out of the crop:

```text
frame → YOLO (where is the plate) → crop → OCR (what does it say) → normalise → bus number
```

So the detector's job is "give me a tight crop", and OCR's job is the hard part.
A `yolo26x` that finds the same rectangle 1% more reliably buys nothing while
the plate is 40×40 pixels and the OCR is guessing between `8` and `B`. Spend the
budget on **input resolution** instead:

```bash
export VISION_IMAGE_SIZE=960     # 640 default; 960 or 1280 for far plates
```

Raising the letterbox size on `yolo26s` usually beats `yolo26m` at 640, both in
accuracy and in latency.

---

## 2. Two rules that matter more than the model

**Train on your own stickers.** "VISION AI SRM TRP NUMBER PLATE" is the right
idea; a public Indian-plate dataset is not. The app matches the OCR result
against the bus numbers in *your* database, and your stickers have a specific
font, border and placement. Public plate datasets teach the model a different
visual language.

**One class is enough.** Train a single class, `number_plate`. The old model in
this repo had two (`red circle`, `sticker`) because it was locating a ring
around the number; a plate detector does not need that. The code crops and OCRs
**every** detected box regardless of its class name, so a single-class model
works with no code change.

---

## 3. Dataset checklist

| Item | Target |
| --- | --- |
| Images per camera/gate | ≥ 300, ideally 500 |
| Conditions | morning sun, midday glare, evening, headlights at night, rain |
| Angles | straight on, ±30°, from a 4–5 m gantry |
| Plate size in frame | deliberately include small ones — plates under ~40 px wide are the ones models miss |
| Labels | tight boxes around the **number region only**, not the whole sticker panel |
| Blur / motion | at least 10% of the set: buses brake, so motion blur is normal |
| Negative frames | 10% with no plate (empty gate, a car) so the model learns to stay quiet |
| Train / valid / test | 70 / 20 / 10, split **by video frame**, not by random crop |

Label in Roboflow, then **Download → YOLOv8/YOLO11 format**. You do not have to
use Roboflow's paid training for this.

---

## 4. Where to train (free)

Roboflow's **Start Training** consumes credits; on a free account the run can
stop early or refuse outright. Two zero-cost options:

**A. Colab free T4 (recommended)** — 12-hour session limits are irrelevant at
this dataset size:

```python
!pip install ultralytics==8.4.20
# upload the YOLO-format zip Roboflow gave you, then:
!yolo detect train model=yolo26s.pt data=/content/dataset/data.yaml \
      imgsz=960 epochs=100 batch=16 patience=25 \
      project=/content/runs name=plates exist_ok=True
```

*(On the free T4 use `batch=8` if 16 runs out of memory at `imgsz=960`; drop to
`imgsz=640` if you would rather have the speed — but then set `VISION_IMAGE_SIZE=640` too.)*

**B. This laptop, CPU** — works, but 100 epochs on 300 images takes hours.
Fine for a 10-epoch sanity run to prove the data loads:

```bash
source .venv/Scripts/activate
python -m ultralytics yolo detect train model=yolo26s.pt data=dataset/data.yaml \
       imgsz=960 epochs=10 batch=4 device=cpu
```

**Never train on Render.** The free instance is 0.1 CPU / 512 MB and torch is
deliberately not installed there.

---

## 5. Settings that suit this task

| Setting | Value | Why |
| --- | --- | --- |
| `imgsz` | 960 | plates are small; match `VISION_IMAGE_SIZE` |
| `epochs` | 100 with `patience=25` | 300–1500 images converge well before 100 |
| `batch` | 16 (T4) / 8 (small GPU) | |
| Augmentation | defaults + `mosaic=1.0`, `scale=0.5`, `hsv_v=0.5` | gate lighting varies enormously |
| `degrees` | 5–10 | cameras are not perfectly aligned |
| `fliplr` | 0.0 | **do not** mirror: text is not symmetric |
| `close_mosaic` | 10 (default) | |

`fliplr` is the one default worth overriding. A flipped plate is mirrored text —
it teaches the model to accept something that never happens, and the OCR will
never read it.

---

## 6. Bring it into the portal

```bash
# 1. keep the old weights — they are your fallback
cp best.pt best-v10n-backup.pt

# 2. drop the new checkpoint in place (or point at it, see below)
cp ~/Downloads/best.pt best.pt

# 3. verify what the file actually contains
python scripts/inspect_model.py best.pt
```

`inspect_model.py` prints the task, the class names and the size, so you catch
the classic mistake — pointing at `last.pt`, or at a checkpoint trained on a
different dataset — before a gate does.

### A number-plate model is the second stage

The repository already ships one: `anpr_best.pt` (YOLOv10n, one class
`licence`, trained on `Car_License_Plates`). The text below is for replacing it
with a model trained on your own gate footage.

Keep the sticker model in `best.pt`: it is the stage that reads the number off
the sticker, and the one this project validates against. If you also train a
plain number-plate detector (one class, `number_plate`), do **not** overwrite
`best.pt` with it — drop it beside the sticker model instead:

```bash
cp ~/Downloads/best.pt weights/number_plate.pt
python scripts/inspect_model.py weights/number_plate.pt
```

`backend/vision.py` then uses it as the fallback stage: sticker first, plate
only when the sticker read nothing. Point `VISION_PLATE_MODEL_PATH` at your file
to make it the default; `weights/` is git-ignored, so it never reaches GitHub.
Verify the swap with `python scripts/inspect_model.py weights/number_plate.pt` —
you want `task: detect` and the class list you trained.

Prefer not to touch git? Leave the file anywhere and set:

```bash
export VISION_MODEL_PATH=/c/Users/kp571/models/plates-s-960.pt
export VISION_CONFIDENCE=0.25
export VISION_IMAGE_SIZE=960
```

Then `GET /api/detection/status` reports the classes **from the loaded file**
(`classes_source: "model"`), not the built-in sticker labels, and the Test Lab's
Detector setup card shows the same.

---

## 7. How to tell whether it is good

Do not chase mAP. Measure the thing the portal does:

| Metric | How | Target |
| --- | --- | --- |
| Plate found | Test Lab → Detection bench → Scan plate, 20 frames | ≥ 18/20 |
| Plate read correctly | those same 20 frames | ≥ 15/20 |
| False reads | scan an empty gate 10 times | 0 events created |
| Latency | `inference_ms` in the scan response | < 250 ms on your laptop |

A missed read creates no event and is harmless; a **wrong** read creates an
event for the wrong bus, which is the failure that matters. Keep
`VISION_CONFIDENCE` conservative (0.25–0.5) and let
`OCR_CONFIDENCE_THRESHOLD` (0.75) flag the doubtful ones.

---

## 8. Licence

Ultralytics weights and code are **AGPL-3.0**. This repository is already
AGPL-3.0 and `best.pt` is tracked under that licence, so training with
Ultralytics keeps you consistent. If you ever host a modified version publicly,
the AGPL requires you to publish those modifications. See
`docs/SECURITY_AUDIT.md` for the open licence note about the current `best.pt`.
