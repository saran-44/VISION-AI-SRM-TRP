"""Bus-sticker detection and plate-number extraction using the trained `best.pt` model.

The model shipped in this repository (`best.pt`) is an Ultralytics YOLOv10n
detector trained for two classes:

    0 -> "red circle"   (the painted red ring around the bus number)
    1 -> "sticker"      (the sticker panel that carries the bus number)

The detector therefore only localises *where* the number is; the actual text
has to be read out of that crop. This module wires the two together:

    frame -> YOLO detection -> sticker crop -> OCR -> normalised bus number

Everything heavy (torch, ultralytics, OpenCV, OCR engine) is imported lazily
so that the Flask application still starts on a machine that has none of the
vision extras installed. `vision_available()` reports what is usable.
"""
from __future__ import annotations

import base64
import binascii
import io
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

# Root of the repository (backend/ -> repo root).
ROOT = Path(__file__).resolve().parents[1]

# Default location of the trained model inside the repository.
DEFAULT_MODEL_PATH = ROOT / "best.pt"

# Class ids as exported by the trained model.
CLASS_STICKER = 1
CLASS_RED_CIRCLE = 0

CLASS_LABELS = {
    CLASS_RED_CIRCLE: "red circle",
    CLASS_STICKER: "sticker",
}

# Bus numbers seen in this project look like "TN 12 AB 1234" / "BUS-001".
# The OCR result is normalised to the same shape the API accepts.
PLATE_CLEAN_RE = re.compile(r"[^A-Z0-9 .\-]")

_model_lock = threading.Lock()
_model_cache: dict[str, Any] = {}
_ocr_lock = threading.Lock()
_ocr_cache: dict[str, Any] = {}


class VisionUnavailable(RuntimeError):
    """Raised when a vision dependency or the model file is missing."""


@dataclass
class PlateCandidate:
    """One detected sticker and the text read from it."""

    bus_number: str | None = None
    confidence: float = 0.0
    raw_text: str = ""
    bbox: list[int] = field(default_factory=list)
    class_id: int = CLASS_STICKER
    class_name: str = "sticker"

    def to_dict(self) -> dict[str, Any]:
        return {
            "bus_number": self.bus_number,
            "confidence": round(float(self.confidence), 4),
            "raw_text": self.raw_text,
            "bbox": list(self.bbox),
            "class_id": self.class_id,
            "class_name": self.class_name,
        }


@dataclass
class DetectionResult:
    """Outcome of running the detector over a single frame."""

    candidates: list[PlateCandidate] = field(default_factory=list)
    model: str = ""
    inference_ms: int = 0
    frame_width: int = 0
    frame_height: int = 0
    # Diagnostics. "No sticker in this frame" used to cover three very different
    # situations: nothing detected, something detected below the confidence
    # threshold, and a sticker found whose number the OCR could not read. The
    # counters below separate them.
    boxes_total: int = 0
    boxes_above_threshold: int = 0
    best_confidence: float = 0.0
    threshold: float = 0.0
    image_size: int = 0
    reason: str = ""
    advice: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "model": self.model,
            "inference_ms": self.inference_ms,
            "frame_width": self.frame_width,
            "frame_height": self.frame_height,
            "boxes_total": self.boxes_total,
            "boxes_above_threshold": self.boxes_above_threshold,
            "best_confidence": round(float(self.best_confidence), 4),
            "threshold": round(float(self.threshold), 4),
            "image_size": self.image_size,
            "reason": self.reason,
            "advice": self.advice,
        }


# --------------------------------------------------------------------------- #
# Configuration helpers
# --------------------------------------------------------------------------- #
def model_path() -> Path:
    """Resolve the model file location (env override, then the repo copy)."""
    configured = os.getenv("VISION_MODEL_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_MODEL_PATH


def confidence_threshold() -> float:
    try:
        value = float(os.getenv("VISION_CONFIDENCE", "0.35"))
    except ValueError:
        return 0.35
    return max(0.01, min(0.99, value))


def image_size() -> int:
    """Inference letterbox size for the detector.

    A bus number plate occupies a small part of a 1080p gate frame, so the
    default 640 px of a COCO model is often the limiting factor — not the
    backbone. Raise it to 960 (or 1280) when the plates are far from the
    camera; it costs quadratic compute, so it is an explicit trade-off.

    Train at the size you infer at: a model fine-tuned at 640 and run at 960
    is usually still fine, the reverse is not.
    """
    try:
        value = int(os.getenv("VISION_IMAGE_SIZE", "640"))
    except ValueError:
        return 640
    return max(320, min(1536, value))


def ocr_engine_name() -> str:
    """Which OCR backend to use: `auto`, `tesseract`, `easyocr` or `none`."""
    return os.getenv("VISION_OCR_ENGINE", "auto").strip().lower() or "auto"


def _require_cv2():
    try:
        import cv2  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise VisionUnavailable(
            "OpenCV is not installed. Install the vision extras with "
            "`pip install -r backend/requirements-vision.txt`."
        ) from exc
    return cv2


def _require_pil():
    try:
        from PIL import Image  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise VisionUnavailable(
            "Pillow is not installed. Install the vision extras with "
            "`pip install -r backend/requirements-vision.txt`."
        ) from exc
    return Image


def _ocr_tesseract():
    try:
        import pytesseract  # type: ignore
    except ImportError as exc:
        raise VisionUnavailable("pytesseract is not installed") from exc
    try:
        pytesseract.get_tesseract_version()
    except Exception as exc:  # pragma: no cover - depends on environment
        raise VisionUnavailable(
            "The tesseract binary is not available on this machine. Install the "
            "`tesseract-ocr` system package or choose another OCR engine."
        ) from exc
    return pytesseract


def _ocr_easyocr():
    try:
        import easyocr  # type: ignore
    except ImportError as exc:
        raise VisionUnavailable("easyocr is not installed") from exc
    with _ocr_lock:
        reader = _ocr_cache.get("easyocr")
        if reader is None:
            reader = easyocr.Reader(["en"], gpu=False, verbose=False)
            _ocr_cache["easyocr"] = reader
        return reader


# --------------------------------------------------------------------------- #
# Model loading
# --------------------------------------------------------------------------- #
def load_model():
    """Load (and cache) the Ultralytics model. Raises VisionUnavailable."""
    path = model_path()
    if not path.exists():
        raise VisionUnavailable(
            f"Detection model not found at {path}. Set VISION_MODEL_PATH to a valid "
            "best.pt file."
        )
    with _model_lock:
        cached = _model_cache.get("model")
        if cached is not None:
            return cached
        try:
            from ultralytics import YOLO  # type: ignore
        except ImportError as exc:
            raise VisionUnavailable(
                "ultralytics is not installed. Install the vision extras with "
                "`pip install -r backend/requirements-vision.txt`."
            ) from exc
        logger.info("Loading detection model from %s", path)
        model = YOLO(str(path))
        _model_cache["model"] = model
        return model


def unload_model() -> None:
    with _model_lock:
        _model_cache.pop("model", None)


# --------------------------------------------------------------------------- #
# OCR
# --------------------------------------------------------------------------- #
def _ocr_rapidocr():
    try:
        from rapidocr_onnxruntime import RapidOCR  # type: ignore
    except ImportError as exc:
        raise VisionUnavailable("rapidocr-onnxruntime is not installed") from exc
    with _ocr_lock:
        engine = _ocr_cache.get("rapidocr")
        if engine is None:
            engine = RapidOCR()
            _ocr_cache["rapidocr"] = engine
        return engine


def _run_tesseract(image, engine) -> str:
    text = engine.image_to_string(image, config="--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -")
    return text or ""


def _run_easyocr(image, reader) -> str:
    results = reader.readtext(image, detail=0, paragraph=False)
    return " ".join(str(item) for item in results)


def _run_rapidocr(image, engine) -> str:
    import numpy as np

    array = np.array(image.convert("RGB"))
    result, _ = engine(array)
    if not result:
        return ""
    return " ".join(str(item[1]) for item in result)


def read_text(image, engine_name: str | None = None) -> str:
    """Read text out of an image using the configured OCR backend."""
    engine_name = (engine_name or ocr_engine_name()).lower()
    if engine_name == "none":
        return ""
    errors: list[str] = []
    order: Iterable[str]
    if engine_name == "auto":
        order = ("rapidocr", "tesseract", "easyocr")
    else:
        order = (engine_name,)

    for name in order:
        try:
            if name == "tesseract":
                engine = _ocr_tesseract()
                return _run_tesseract(image, engine)
            if name == "easyocr":
                reader = _ocr_easyocr()
                return _run_easyocr(image, reader)
            if name == "rapidocr":
                engine = _ocr_rapidocr()
                return _run_rapidocr(image, engine)
            raise VisionUnavailable(f"Unknown OCR engine '{name}'")
        except VisionUnavailable as exc:
            errors.append(str(exc))
    raise VisionUnavailable("; ".join(errors) or "No OCR engine is available")


def normalize_plate(text: str) -> str:
    """Normalise raw OCR output into the bus-number format used by the API."""
    if not text:
        return ""
    upper = text.upper().replace("\n", " ").strip()
    cleaned = PLATE_CLEAN_RE.sub("", upper)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -")
    return cleaned


# --------------------------------------------------------------------------- #
# Detection
# --------------------------------------------------------------------------- #
# Frame guards. A 1 MB request body can still decode into a gigantic bitmap,
# so the pixel count is capped before any pixel data is allocated, and the
# side length is capped before the decoder touches it.
MAX_IMAGE_PIXELS = 12_000_000  # ~12 MP, comfortably above 4K video frames
MAX_IMAGE_SIDE = 6_000
MAX_IMAGE_BYTES = 8_000_000


def decode_image(payload: bytes | str) -> "Any":
    """Decode raw image bytes or a base64 string into a PIL image."""
    Image = _require_pil()
    # PIL's own bomb guard covers formats that declare a huge canvas.
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    if isinstance(payload, str):
        if len(payload) > MAX_IMAGE_BYTES * 2:
            raise VisionUnavailable("The image payload is too large")
        data = payload.split(",", 1)[-1] if payload.startswith("data:") else payload
        try:
            payload = base64.b64decode(data, validate=False)
        except (binascii.Error, ValueError) as exc:
            raise VisionUnavailable("The image payload is not valid base64") from exc
    if len(payload) > MAX_IMAGE_BYTES:
        raise VisionUnavailable("The image payload is too large")
    try:
        with Image.open(io.BytesIO(payload)) as probe:
            width, height = probe.size
            if width * height > MAX_IMAGE_PIXELS or max(width, height) > MAX_IMAGE_SIDE:
                raise VisionUnavailable(
                    f"Image is larger than the {MAX_IMAGE_PIXELS // 1_000_000} MP limit"
                )
            probe.load()
            return probe.copy()
    except VisionUnavailable:
        raise
    except Exception as exc:
        raise VisionUnavailable("The uploaded data is not a readable image") from exc


def max_crops() -> int:
    """Maximum number of sticker crops that are OCR'd in a single frame."""
    try:
        value = int(os.getenv("VISION_MAX_CROPS", "8"))
    except ValueError:
        return 8
    return max(1, value)


def detect(image, *, model=None, threshold: float | None = None) -> DetectionResult:
    """Run the detector over an image and OCR each detected sticker.

    The model is asked for boxes down to 0.05 confidence and filtered here, so
    a "nothing found" answer can say *why*: no boxes at all, boxes under the
    threshold, or a sticker whose number the OCR could not read.
    """
    import time

    model = model or load_model()
    threshold = confidence_threshold() if threshold is None else threshold
    probe_conf = min(threshold, 0.05)
    size = image_size()
    started = time.perf_counter()

    results = model.predict(source=image, conf=probe_conf, imgsz=size, verbose=False)
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    result = DetectionResult(
        model=str(model_path().name),
        inference_ms=elapsed_ms,
        frame_width=getattr(image, "width", 0) or 0,
        frame_height=getattr(image, "height", 0) or 0,
        threshold=float(threshold),
        image_size=size,
    )
    if not results:
        return _explain(result)

    boxes = getattr(results[0], "boxes", None)
    if boxes is None or len(boxes) == 0:
        return _explain(result)

    names = getattr(model, "names", {}) or {}
    limit = max_crops()
    rows = []
    for index in range(len(boxes)):
        rows.append((
            float(boxes.conf[index].item()),
            int(boxes.cls[index].item()),
            [int(value) for value in boxes.xyxy[index].tolist()],
        ))
    # Ultralytics sorts by confidence already; do not rely on it.
    rows.sort(key=lambda row: row[0], reverse=True)

    result.boxes_total = len(rows)
    result.best_confidence = rows[0][0]

    for confidence, class_id, coords in rows:
        if confidence < threshold:
            break  # everything after this one is weaker still
        if len(result.candidates) >= limit:
            break
        class_name = names.get(class_id, CLASS_LABELS.get(class_id, str(class_id)))
        candidate = PlateCandidate(
            confidence=confidence,
            bbox=coords,
            class_id=class_id,
            class_name=str(class_name),
        )
        crop = _crop(image, coords)
        if crop is not None:
            try:
                raw = read_text(crop)
            except VisionUnavailable as exc:
                logger.info("OCR unavailable for this frame: %s", exc)
                raw = ""
            candidate.raw_text = raw.strip()
            candidate.bus_number = normalize_plate(candidate.raw_text)
        result.candidates.append(candidate)

    result.boxes_above_threshold = len(result.candidates)
    return _explain(result)


def _explain(result: DetectionResult) -> DetectionResult:
    """Fill in `reason`/`advice` so the caller never has to guess."""
    readable = [candidate for candidate in result.candidates if candidate.bus_number]

    if result.boxes_total == 0:
        result.reason = "no_detection"
        result.advice = (
            "No box at all, even at 0.05 confidence. Point the camera at the sticker, "
            "fill more of the frame with it, and check the model matches these stickers: "
            "python scripts/inspect_model.py"
        )
    elif not result.candidates:
        result.reason = "below_threshold"
        result.advice = (
            f"{result.boxes_total} box(es) found, best {result.best_confidence:.2f} is under the "
            f"{result.threshold:.2f} threshold. Lower VISION_CONFIDENCE (0.15-0.25) to confirm the "
            "sticker is being seen, or raise VISION_IMAGE_SIZE when it is small in the frame."
        )
    elif not readable:
        largest = max(
            (abs(candidate.bbox[2] - candidate.bbox[0]) for candidate in result.candidates),
            default=0,
        )
        result.reason = "unreadable"
        result.advice = (
            f"Sticker detected at {result.candidates[0].confidence:.2f} but the OCR read no text. "
            f"The crop was about {largest} px wide: get closer, raise VISION_IMAGE_SIZE, "
            "or install a stronger OCR engine (see docs/DETECTION.md)."
        )
    else:
        result.reason = "ok"
        result.advice = ""
    return result


def _crop(image, coords: list[int]):
    """Crop a bbox out of a PIL image, returning None when it is degenerate."""
    try:
        left, top, right, bottom = coords
    except (TypeError, ValueError):
        return None
    width = getattr(image, "width", 0)
    height = getattr(image, "height", 0)
    left = max(0, min(left, width - 1))
    top = max(0, min(top, height - 1))
    right = max(left + 1, min(right, width))
    bottom = max(top + 1, min(bottom, height))
    if right <= left or bottom <= top:
        return None
    return image.crop((left, top, right, bottom))


def best_candidate(result: DetectionResult) -> PlateCandidate | None:
    """Pick the most trustworthy candidate: a readable number beats confidence."""
    if not result.candidates:
        return None
    with_number = [candidate for candidate in result.candidates if candidate.bus_number]
    pool = with_number or result.candidates
    return max(pool, key=lambda candidate: candidate.confidence)


# --------------------------------------------------------------------------- #
# Health reporting
# --------------------------------------------------------------------------- #
def _module_present(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:  # ImportError plus any broken native dependency
        return False


def vision_setup() -> dict[str, Any]:
    """The one-screen install checklist the Test Lab shows.

    A missing Pillow used to surface as a bare `503` sentence with a single
    "install the vision extras" line. That is not actionable on a machine that
    half-installed the stack, so every component reports its own state and the
    exact command that fixes it.
    """
    requirements = "-r backend/requirements-vision.txt"
    rows = [
        {
            "name": "torch",
            "label": "PyTorch (model runtime)",
            "present": _module_present("torch"),
            "size": "~200 MB (CPU wheel)",
            "command": "python -m pip install torch==2.9.1 torchvision==0.24.1 --index-url https://download.pytorch.org/whl/cpu",
        },
        {
            "name": "ultralytics",
            "label": "Ultralytics (YOLO loader)",
            "present": _module_present("ultralytics"),
            "size": "~15 MB",
            "command": "python -m pip install ultralytics==8.4.20",
        },
        {
            "name": "opencv",
            "label": "OpenCV headless (framing)",
            "present": _module_present("cv2"),
            "size": "~35 MB",
            "command": "python -m pip install opencv-python-headless==4.10.0.84",
        },
        {
            "name": "Pillow",
            "label": "Pillow (image decode)",
            "present": _module_present("PIL"),
            "size": "~4 MB",
            "command": 'python -m pip install "Pillow>=10.0.0"',
        },
        {
            "name": "ocr",
            "label": "OCR engine (reads the sticker)",
            "present": _ocr_usable(),
            "size": "~60 MB (RapidOCR, no system packages)",
            "command": "python -m pip install rapidocr-onnxruntime==1.4.4",
        },
        {
            "name": "model",
            "label": "best.pt (trained weights)",
            "present": DEFAULT_MODEL_PATH.exists(),
            "size": "5.5 MB, tracked in git",
            "command": "git checkout -- best.pt   # restore the tracked weights",
        },
    ]
    missing = [row for row in rows if not row["present"]]
    return {
        "ready": not missing,
        "missing": [row["name"] for row in missing],
        "components": rows,
        "install_all": f"python -m pip install {requirements}",
        "note": (
            "Everything stays optional: without these the console, tables, filters and "
            "exports work normally and only the detector answers 503 with this checklist."
        ),
    }


def _ocr_usable() -> bool:
    """True when at least one configured OCR backend can be imported."""
    engine = ocr_engine_name()
    if engine == "none":
        return False
    probes = ("rapidocr", "tesseract", "easyocr") if engine == "auto" else (engine,)
    loaders = {"rapidocr": _ocr_rapidocr, "tesseract": _ocr_tesseract, "easyocr": _ocr_easyocr}
    for probe in probes:
        try:
            loaders[probe]()
            return True
        except (VisionUnavailable, KeyError):
            continue
    return False


def vision_status() -> dict[str, Any]:
    """Describe what the vision stack can currently do."""
    path = model_path()
    loaded = _model_cache.get("model")
    status: dict[str, Any] = {
        "model_path": str(path),
        "model_present": path.exists(),
        "model_loaded": loaded is not None,
        "confidence_threshold": confidence_threshold(),
        "image_size": image_size(),
        "ocr_engine": ocr_engine_name(),
        # The labels the loaded checkpoint actually carries. A freshly trained
        # number-plate model (one class, "number_plate") must not be described
        # with this repository's old sticker/red-circle pair.
        "classes": {
            str(key): value
            for key, value in (
                (getattr(loaded, "names", None) or CLASS_LABELS).items()
            )
        },
        "classes_source": "model" if loaded is not None else "default",
        "available": False,
        "problems": [],
    }
    if not path.exists():
        status["problems"].append(f"Model file missing at {path}")

    try:
        import torch  # type: ignore  # noqa: F401
    except ImportError:
        status["problems"].append("torch is not installed")
    try:
        import ultralytics  # type: ignore  # noqa: F401
    except ImportError:
        status["problems"].append("ultralytics is not installed")
    try:
        import cv2  # type: ignore  # noqa: F401
    except ImportError:
        status["problems"].append("opencv is not installed")
    try:
        import PIL  # type: ignore  # noqa: F401
    except ImportError:
        status["problems"].append("Pillow is not installed")

    engine = ocr_engine_name()
    if engine != "none":
        usable = False
        for probe in ("rapidocr", "tesseract", "easyocr"):
            try:
                if probe == "rapidocr":
                    _ocr_rapidocr()
                elif probe == "tesseract":
                    _ocr_tesseract()
                else:
                    _ocr_easyocr()
                usable = True
                status["ocr_available"] = probe
                break
            except VisionUnavailable:
                continue
        if not usable:
            status["problems"].append(
                "no OCR engine is usable (install rapidocr-onnxruntime, tesseract-ocr or easyocr)"
            )
    else:
        status["problems"].append("OCR is disabled (VISION_OCR_ENGINE=none)")

    status["available"] = not status["problems"]
    status["setup"] = vision_setup()
    return status
