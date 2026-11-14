# Bus Sticker Detection — Model, Backend and API

This document records the provenance of `best.pt`, how the detection backend
works, and the HTTP contract the console uses.

---

## 1. Model investigation (exact provenance unverified)

| Property | Value |
| --- | --- |
| File | `best.pt` (repository root, tracked in Git) |
| Size | 5,729,139 bytes |
| Architecture | **Ultralytics YOLOv10n** (end-to-end, NMS-free) |
| Saved by | `ultralytics 8.4.20` |
| Classes | `{0: 'red circle', 1: 'sticker'}` (`nc=2`) |
| Inference size | 640 px |
| Checkpoint metadata | Identifies an Ultralytics AGPL-3.0 licence; actual model and dataset rights require review |

### Related notebook

A related public GitHub repository was found during the upgrade:

**`814725105014-debug/SRM-TRP-TRANSPORT-AI`** — <https://github.com/814725105014-debug/SRM-TRP-TRANSPORT-AI>

| Property | Value |
| --- | --- |
| Default branch | `main` |
| Commits | 1 (`ae546f9` — "Created using Colab") |
| License | **None declared** (all rights reserved by default) |
| Created / pushed | 2026-03-02 / 2026-03-04 |

Repository contents:

```
README.md                                          (22 bytes)
SRM_TRP_AI.ipynb                                  (195,287 bytes)  ← the YOLOv10 notebook
train_yolov9_object_detection_on_trp_dataset.ipynb (4,134,102 bytes) ← Roboflow YOLOv9 notebook
data/{train,val,test}/README.md                   (1 byte each, empty)
models/README.md, scripts/README.md               (1 byte each, empty)
```

The relevant pipeline from `SRM_TRP_AI.ipynb`:

```python
!git clone https://github.com/THU-MIG/yolov10.git
%cd yolov10
!pip install .

# download the YOLOv10 nano checkpoints
url = "https://github.com/jameslahm/yolov10/releases/download/v1.0/yolov10n.pt"

!unzip license_data.zip

!yolo task=detect mode=train epochs=100 batch=16 plots=True \
      model=weights/yolov10n.pt data=data.yaml

!yolo task=detect mode=predict conf=0.25 save=True \
      model=runs/detect/train/weights/best.pt source=car.jpg

!yolo task=detect mode=predict conf=0.25 save=True \
      model=runs/detect/train/weights/best.pt source=video.mp4
```

### Important consequences

1. **No hosted inference API was found in that repository.** It is a Colab
   notebook, not a server with an endpoint contract. This project implements
   its own detection/OCR integration in `backend/vision.py` rather than
   inventing a third-party API.
2. **`data.yaml`, `license_data.zip`, and the trained weights are not committed**
   there. A similar architecture or filename does not prove the supplied
   checkpoint was produced by this notebook. Its exact provenance and dataset
   remain unverified.
3. **Licensing.** The checkpoint metadata identifies an Ultralytics AGPL-3.0
   licence, while the related notebook repository declares no licence. Model,
   dataset and software rights require separate review. Obtain written rights
   and qualified licence advice, or replace the model and dependencies with
   appropriately licensed alternatives before production or distribution.
4. A second repository, `814725105014-debug/SRM-TRP-TRANSPORT-AI-NEW`, exists
   but is **empty** (GitHub returns `409 Git Repository is empty`).

### Related (unrelated-weight) repositories

`hemanathanmd01/Clg-bus-project` is an earlier prototype of the same college
transport project. It contains **no model weights** (only `app.py`, HTML,
CSV logs, a PDF, sample videos and images), declares **no licence**, and its
code embeds credentials. No checkpoint was found there, and none of its code
was copied here for the detector integration.

---

## 2. Detection backend — `backend/vision.py`

`backend/vision.py` is a self-contained bridge between the Ultralytics
checkpoint and OCR. It has no hard dependency on Torch at import time, so the
API starts (and reports "detection unavailable") on a host without the vision
extras.

| Function | Purpose |
| --- | --- |
| `load_model()` | Lazily loads `best.pt` through Ultralytics; cached for the process lifetime. |
| `detect(image, model=None)` | Runs inference, crops every detected sticker, OCRs each crop and returns ranked candidates. |
| `decode_image(payload)` | Decodes raw bytes, a `data:` URL or bare base64 into a PIL image. |
| `read_text(image, engine=None)` | Runs OCR through the configured engine. |
| `normalize_plate(text)` | Cleans OCR output into a canonical plate string. |
| `best_candidate(result)` | Picks the highest-confidence candidate. |
| `vision_status()` | Reports model presence, load state, class names and OCR availability. |

### OCR engines

`VISION_OCR_ENGINE` selects the engine; `auto` (the default) tries them in
this order and uses the first that works:

| Order | Engine | Package | Notes |
| --- | --- | --- | --- |
| 1 | **RapidOCR** | `rapidocr-onnxruntime` | **Default.** ONNX-based, bundles its own models, needs no system packages. Recommended. |
| 2 | Tesseract | `pytesseract` + system `tesseract-ocr` | Requires the binary to be installed on the host. |
| 3 | EasyOCR | `easyocr` | Heavy (PyTorch already present, but pulls `scikit-image`). |

Verified in this environment: RapidOCR read a synthetic plate at **0.994**
confidence, and the full pipeline runs a frame in **~114 ms** on CPU.

### Plate normalisation

`normalize_plate()` upper-cases the text, strips characters that cannot
appear on an Indian registration plate, collapses whitespace, and removes the
spaces that separate the two halves of a plate (`TN 12 AB 1234` → `TN12AB1234`)
while preserving the internal grouping used for display
(`TN 12 AB 1234`).

---

## 3. HTTP contract

### `GET /api/detection/status` — `head_admin`

```json
{
  "model_path": "/srv/srm-trp/best.pt",
  "model_present": true,
  "model_loaded": true,
  "confidence_threshold": 0.35,
  "ocr_engine": "auto",
  "ocr_available": "rapidocr",
  "classes": {"0": "red circle", "1": "sticker"},
  "available": true,
  "problems": []
}
```

`available` is `true` only when the checkpoint is present *and* an OCR engine
is usable. `problems` lists the reasons otherwise.

### `POST /api/detection/scan` — device key **or** `head_admin` session

Accepts a multipart upload (`image` file part) or a JSON body with an
`image` field holding base64 data.

```bash
curl -X POST http://localhost:5000/api/detection/scan \
  -H "X-Device-Key: $DEVICE_API_KEY" \
  -F "image=@frame.jpg" \
  -F "camera_id=gate-1-entry" \
  -F "direction=IN" \
  -F "gate=Gate 1 Entry"
```

```json
{
  "detection": {
    "candidates": [
      {
        "bus_number": "TN12AB1234",
        "raw_text": "TN 12 AB 1234",
        "confidence": 0.94,
        "bbox": [412, 288, 596, 352],
        "class_name": "sticker",
        "class_id": 1
      }
    ],
    "model": "best.pt",
    "inference_ms": 118,
    "frame_width": 1280,
    "frame_height": 720
  },
  "bus_number": "TN12AB1234",
  "confidence": 0.94,
  "raw_text": "TN 12 AB 1234",
  "source": "device"
}
```

Error responses:

| Status | Meaning |
| --- | --- |
| `400` | No image supplied, or a malformed body. |
| `401` | No device key and no valid session. |
| `403` | A session was supplied but the role is not `head_admin`. |
| `503` | The vision stack is unavailable (model missing, no OCR engine). |
| `500` | Inference raised an unexpected error. |

Every scan is written to the audit log with the action `detection_scan`.

---

## 4. Turning a detection into a transport event

A detection is a *reading*, not yet a movement. To record a movement, post the
read result through the normal event endpoint so the existing flag rules
(`unregistered_plate`, `low_ocr_confidence`, `long_overstay`) and the
"Currently Inside" state are applied consistently:

```bash
curl -X POST http://localhost:5000/api/events \
  -H "X-Device-Key: $DEVICE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
        "bus_number": "TN12AB1234",
        "direction": "IN",
        "gate": "Gate 1 Entry",
        "camera_id": "gate-1-entry",
        "confidence": 0.94,
        "timestamp": "2026-11-12T09:15:00+05:30"
      }'
```

The event contract is unchanged from `docs/EVENT_CONTRACT.md`.

---

## 5. Installing the vision extras

```bash
python -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/pip install -r backend/requirements-vision.txt
```

On Windows (Git Bash), `source .venv/Scripts/activate` first, then the same
two commands. If the single `-r` line fails part-way, install the components in
this order — each one is independent, and the Test Lab's **Detector setup** card
shows which ones are already present:

```bash
python -m pip install torch==2.9.1 torchvision==0.24.1 --index-url https://download.pytorch.org/whl/cpu
python -m pip install ultralytics==8.4.20
python -m pip install opencv-python-headless==4.10.0.84
python -m pip install "Pillow>=10.0.0"
python -m pip install rapidocr-onnxruntime==1.4.4
```

Budgets on a normal laptop: torch ≈ 200 MB download / 900 MB on disk (CPU
wheel), ultralytics ≈ 15 MB, OpenCV ≈ 35 MB, Pillow ≈ 4 MB, RapidOCR ≈ 60 MB
plus its bundled ONNX models. A full install is 5–10 minutes on a home
connection; nothing else in the portal waits for it.

`backend/requirements-vision.txt` pins the versions verified in this
repository:

```
torch==2.9.1
torchvision==0.24.1
ultralytics==8.4.20
opencv-python-headless==4.10.0.84
Pillow>=10.0
rapidocr-onnxruntime==1.4.4
pytesseract>=0.3.10
```

> **Disk note.** The default `torch` wheel from PyPI is the CUDA build and
> pulls ~3 GB of NVIDIA libraries. On a CPU-only host, install the CPU wheel
> from `https://download.pytorch.org/whl/cpu` instead:
>
> ```bash
> pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
> ```
>
> `opencv-python-headless` is used deliberately: the full `opencv-python`
> wheel requires `libGL.so.1`, which is absent on minimal server images and
> breaks `import cv2`.

---

## 6. Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `VISION_MODEL_PATH` | `best.pt` | Path to the Ultralytics checkpoint. |
| `VISION_CONFIDENCE` | `0.35` | Minimum detection confidence. |
| `VISION_OCR_ENGINE` | `auto` | `auto`, `rapidocr`, `tesseract`, `easyocr` or `none`. |
| `VISION_MAX_CROPS` | `8` | Maximum sticker crops OCR'd per frame. |
| `OCR_CONFIDENCE_THRESHOLD` | `0.75` | Below this an event is flagged `low_ocr_confidence`. |
